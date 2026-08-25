"""
Arbitration CONTRACT for the Global Workspace (P3/P4 split: contract now, policy later)
=======================================================================================

This module freezes the *interface* of workspace arbitration. It deliberately
does NOT contain valuation policy: LegacyWTAReferee below is a byte-for-byte
delegation to the existing GlobalWorkspace (Hopfield + lateral inhibition +
softmax WTA). Real valuation (ledger-aware scoring, quorum, blast-radius
friction on irreversible action classes) is deferred and will slot in behind
Referee without touching call sites.

Contract invariants
--------------------
I1. A Referee READS the epistemic ledger and the behavioral/salience ledger
    and WRITES TO NEITHER. Enforced structurally (read-only ledger views --
    the referee is never handed a writable object) and dynamically
    (GuardedReferee fingerprints both ledgers around every call and raises
    RefereePurityError on any mutation).
I2. Authority attaches to the ACTION CLASS of a bid, not to the agent/module
    that emitted it. Bid.action_class / Bid.blast_radius exist for this; the
    taxonomy itself is intentionally deferred -- the fields are frozen, the
    vocabulary is not.
I3. Execution gates (synthesis cascade, self-modification) consume a
    RefereeDecision. They must not branch on raw salience or verdict alone.
    See bisociation_gate / self_modification_gate.

Zero changes are made to global_workspace.py in this phase.

Origin: drafted by stealth/ox-alpha (OpenRouter) 2026-08-25, grounded in the
real conductor.py/global_workspace.py call site, reviewed and applied by
Claude after independent verification against the actual code and tests.
See STATUS.md for the fix history.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, get_args, runtime_checkable

from nouse.orchestrator.global_workspace import GlobalWorkspace, WorkspaceProposal

ARBITRATION_CONTRACT_VERSION = 1

# Blast-radius tiers. Deliberately coarse; "system" is reserved for
# self-modification-class actions. Additive changes are backward-compatible
# because every consumer treats the field as opaque until the taxonomy lands.
BlastRadius = Literal["local", "module", "system"]

# Dotted action-class vocabulary, registry deferred (authority attaches to
# action classes, not agents). Free-form str for now so the contract does not
# break when the registry arrives; validation moves into Bid.__post_init__
# then, in one place.
ActionClass = str


# ---------------------------------------------------------------------------
# 1. The bid: richer than WorkspaceProposal, backward-convertible both ways
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Bid:
    """A module's petition for the workspace spotlight.

    The first four fields are exactly WorkspaceProposal's, so conversion to
    the legacy pipeline is field-verbatim. The authority metadata is optional
    and defaulted: existing emitters keep compiling, and the taxonomy can be
    filled in later without breaking this contract.
    """

    module: str
    content: Any
    salience: float
    domain: str = ""

    # --- authority metadata (invariant I2). None = "unclassified"; the
    # referee may treat unclassified as lowest-authority once real policy
    # lands. Classification is the emitter's duty going forward. ---
    action_class: ActionClass | None = None
    blast_radius: BlastRadius | None = None

    # Stable per-cycle audit id. Derived, not assigned, so emitters don't
    # have to care; deterministic in (module, content) for join-ability
    # against ledger entries.
    bid_id: str = ""

    def __post_init__(self) -> None:
        if not math.isfinite(self.salience):
            raise ValueError(f"Bid.salience must be finite, got {self.salience!r}")
        if self.blast_radius is not None and self.blast_radius not in get_args(BlastRadius):
            raise ValueError(
                f"Bid.blast_radius {self.blast_radius!r} not in {get_args(BlastRadius)}"
            )
        if not self.bid_id:
            digest = hashlib.blake2s(
                repr((self.module, self.content)).encode(), digest_size=5
            ).hexdigest()
            object.__setattr__(self, "bid_id", f"{self.module}:{digest}")

    # --- legacy interop: the stub policy feeds these straight into the
    # unchanged GlobalWorkspace pipeline ---
    def to_workspace_proposal(self) -> WorkspaceProposal:
        return WorkspaceProposal(
            module=self.module,
            content=self.content,
            salience=self.salience,
            domain=self.domain,
        )

    @staticmethod
    def from_workspace_proposal(
        p: WorkspaceProposal,
        *,
        action_class: ActionClass | None = None,
        blast_radius: BlastRadius | None = None,
    ) -> Bid:
        return Bid(
            module=p.module,
            content=p.content,
            salience=p.salience,
            domain=p.domain,
            action_class=action_class,
            blast_radius=blast_radius,
        )


# ---------------------------------------------------------------------------
# 2. Read-only ledger surface (invariant I1, structural half)
# ---------------------------------------------------------------------------

@runtime_checkable
class LedgerView(Protocol):
    """The ONLY ledger surface a Referee may ever see."""

    @property
    def length(self) -> int: ...

    def tail(self, n: int = 1) -> Sequence[Any]: ...


class ReadOnlyLedgerView:
    """Whitelist adapter over a raw append-only ledger (typically a list).

    Defense against *accidents*, not adversaries: only ``length`` / ``tail``
    resolve; any other attribute access (``append``, ``write``, ``record``,
    ...) raises AttributeError because __getattr__ only fires for attributes
    this class does not define. The underlying storage is referenced, not
    copied, so wrapping is O(1).
    """

    __slots__ = ("_entries",)

    def __init__(self, entries: Sequence[Any]) -> None:
        self._entries = entries

    @property
    def length(self) -> int:
        return len(self._entries)

    def tail(self, n: int = 1) -> Sequence[Any]:
        if n <= 0:
            return ()
        return tuple(self._entries[-n:])

    def __len__(self) -> int:
        return len(self._entries)

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(
            f"ReadOnlyLedgerView forbids attribute {name!r}: referees read "
            f"ledgers, they never write them (arbitration invariant I1)"
        )

    def __repr__(self) -> str:
        return f"ReadOnlyLedgerView(length={len(self._entries)})"


# ---------------------------------------------------------------------------
# 3. The decision and the referee protocol
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RefereeDecision:
    """What a Referee owes its callers. Frozen: decisions are audit records.

    approved is THE execution bit. For the legacy stub it is defined as
    `winner is not None` -- see LegacyWTAReferee for why that exact definition
    is what makes the conductor gate fix behavior-preserving today.
    """

    winner_module: str | None
    approved: bool
    reason: str
    contract_version: int = ARBITRATION_CONTRACT_VERSION
    beta: float | None = None                       # limbic gain actually applied
    scores: Mapping[str, float] | None = None       # hopfield states / observability
    epistemic_cursor: int = -1                      # -1 = ledger not consulted
    behavioral_cursor: int = -1                     # -1 = ledger not consulted


@runtime_checkable
class Referee(Protocol):
    """Arbitration authority. Implementations receive the two ledger views at
    construction (constructor shape: ``(workspace_deps..., epistemic, behavioral)``);
    ``arbitrate`` stays stateless-per-call so GuardedReferee can bracket it.
    """

    async def arbitrate(self, bids: Sequence[Bid], limbic: Any) -> RefereeDecision: ...
    # limbic is typed Any in v1 on purpose: binding it to the repo's real
    # LimbicState here would couple this contract to a type this diff does not
    # touch. Tighten in the policy phase.


# ---------------------------------------------------------------------------
# 4. Dynamic purity guard (invariant I1, dynamic half)
# ---------------------------------------------------------------------------

class RefereePurityError(AssertionError):
    """Raised when a referee mutated a ledger it was only allowed to read."""


def ledger_fingerprint(view: LedgerView, window: int = 64) -> tuple[int, str]:
    """(length, digest-of-last-`window`-entries). O(window) per call.

    Catches appends and edits/deletes inside the recent window, which for an
    append-only epistemic log is the realistic violation. Edits to entries
    older than the window are NOT caught -- accepted limitation of the cheap
    guard; the structural half (ReadOnlyLedgerView) remains the primary wall.
    """
    h = hashlib.blake2s(digest_size=8)
    for entry in view.tail(window):
        h.update(repr(entry).encode())
        h.update(b"\x00")
    return (view.length, h.hexdigest())


class GuardedReferee:
    """Wraps any Referee; fingerprints both ledgers around every arbitrate()
    call and raises RefereePurityError on mismatch. Used in production wiring
    and in tests, so the write-prohibition is checked on every cycle, not
    merely asserted in a docstring.
    """

    def __init__(
        self,
        inner: Referee,
        epistemic: LedgerView,
        behavioral: LedgerView,
        window: int = 64,
    ) -> None:
        self._inner = inner
        self._epistemic = epistemic
        self._behavioral = behavioral
        self._window = window

    async def arbitrate(self, bids: Sequence[Bid], limbic: Any) -> RefereeDecision:
        before = (
            ledger_fingerprint(self._epistemic, self._window),
            ledger_fingerprint(self._behavioral, self._window),
        )
        decision = await self._inner.arbitrate(bids, limbic)
        after = (
            ledger_fingerprint(self._epistemic, self._window),
            ledger_fingerprint(self._behavioral, self._window),
        )
        if before != after:
            raise RefereePurityError(
                f"referee {type(self._inner).__name__} mutated a ledger: "
                f"epistemic {before[0]} -> {after[0]}, "
                f"behavioral {before[1]} -> {after[1]}"
            )
        return decision


# ---------------------------------------------------------------------------
# 5. Policy STUB: exactly today's WTA, behind the contract
# ---------------------------------------------------------------------------

class LegacyWTAReferee:
    """Byte-for-byte delegation to the existing GlobalWorkspace pipeline.

    Contains ZERO new valuation logic. Outcomes are identical to today's
    because (a) Bid -> WorkspaceProposal copies the four legacy fields
    verbatim, (b) the Hopfield + softmax code is untouched, (c) the dynamics
    are deterministic, so same inputs -> same winner, same beta.

    The load-bearing definition: approved := (winner is not None). The
    conductor's slate is a static 3-element literal, so a winner always
    exists and approved is identically True at that call site -- which is
    precisely what makes the gate fix in conductor.py a provable no-op today
    while still routing execution authority through the contract.
    """

    policy_name = "legacy_wta_v0"

    def __init__(
        self,
        workspace: GlobalWorkspace,
        epistemic: LedgerView,
        behavioral: LedgerView,
    ) -> None:
        self._ws = workspace
        self._epistemic = epistemic
        self._behavioral = behavioral

    async def arbitrate(self, bids: Sequence[Bid], limbic: Any) -> RefereeDecision:
        epi_cur = self._epistemic.length     # reads BOTH ledgers (I1: read half)
        beh_cur = self._behavioral.length    # and stamps provenance onto the decision
        if not bids:
            return RefereeDecision(
                winner_module=None,
                approved=False,
                reason=f"{self.policy_name}: empty slate",
                epistemic_cursor=epi_cur,
                behavioral_cursor=beh_cur,
            )
        legacy_proposals = [b.to_workspace_proposal() for b in bids]
        result = await self._ws.competition_step(legacy_proposals, limbic)
        winner = result.winner
        scores = (
            dict(result.hopfield_states)
            if result.hopfield_states
            else {b.module: b.salience for b in bids}
        )
        return RefereeDecision(
            winner_module=winner.module if winner is not None else None,
            approved=winner is not None,           # <-- the load-bearing line
            reason=(
                f"{self.policy_name}: "
                f"winner={winner.module if winner is not None else 'none'}"
            ),
            beta=result.beta,
            scores=scores,
            epistemic_cursor=epi_cur,
            behavioral_cursor=beh_cur,
        )


# ---------------------------------------------------------------------------
# 6. Execution gates: the single place where a decision becomes permission
# ---------------------------------------------------------------------------

BISOCIATION_VERDICT = "BISOCIATION"


def bisociation_gate(verdict: str, decision: RefereeDecision) -> bool:
    """Sole authority for running the synthesis cascade (conductor step 7).

    CONTRACT: conductor must call this, not re-derive the predicate. Today it
    reduces exactly to the legacy `verdict == "BISOCIATION"` because
    LegacyWTAReferee.approved is identically True at that call site; when real
    policy lands, this is where quorum / blast-radius friction attaches
    without touching the conductor again.
    """
    return verdict == BISOCIATION_VERDICT and decision.approved


def self_modification_gate(
    discovery_streak: int,
    f_bisoc: float,
    decision: RefereeDecision,
    *,
    min_streak: int,
    min_confidence: float,
) -> bool:
    """Sole authority for proposing self-modification (conductor step 8).

    Legacy predicate was `streak >= min_streak and f_bisoc >= min_confidence`.
    The added `decision.approved` conjunct is a proved no-op today (see
    tests::test_gates_equal_legacy_predicates_under_stub) and is the hook the
    blast-radius policy will use: a "system"-radius action class will be able
    to withhold approval here.
    """
    return (
        discovery_streak >= min_streak
        and f_bisoc >= min_confidence
        and decision.approved
    )
