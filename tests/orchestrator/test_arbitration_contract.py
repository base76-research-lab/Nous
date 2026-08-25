"""Tests for the arbitration CONTRACT (P3/P4 stub phase).

Drafted by stealth/ox-alpha, reviewed and corrected by Claude: the original
draft's LimbicFixture used a field named `beta`, but GlobalWorkspace.
competition_step() reads `limbic.wta_beta` (see src/nouse/limbic/signals.py)
-- fixed here before the suite was ever run.
"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass

import pytest

from nouse.orchestrator.arbitration import (
    Bid,
    GuardedReferee,
    LegacyWTAReferee,
    ReadOnlyLedgerView,
    RefereeDecision,
    RefereePurityError,
    bisociation_gate,
    ledger_fingerprint,
    self_modification_gate,
)
from nouse.orchestrator.global_workspace import GlobalWorkspace


# --- fixtures ----------------------------------------------------------------

@dataclass
class LimbicFixture:
    """Minimal stand-in carrying only what GlobalWorkspace.competition_step
    actually reads (limbic.wta_beta)."""
    wta_beta: float = 1.7
    dopamine: float = 0.35
    lam: float = 0.25
    performance: float = 0.8


def canonical_bids() -> list[Bid]:
    """The conductor's static slate with fixed saliences."""
    return [
        Bid(module="episodic_memory", content={"k": 1}, salience=0.65,
            domain="d", action_class="memory.recall.read", blast_radius="local"),
        Bid(module="tda_bisociation", content={"f_bisoc": 0.9}, salience=1.05,
            domain="d", action_class="synthesis.broadcast", blast_radius="module"),
        Bid(module="limbic_homeostasis", content={"k": 2}, salience=0.48,
            domain="meta", action_class="homeostasis.adjust", blast_radius="local"),
    ]


# --- test 1: the referee never writes (structural + dynamic halves) ---------

class WriteAfterReadReferee:
    """Negative control: obeys the Referee shape, violates invariant I1."""

    def __init__(self, raw: list[object]) -> None:
        self._raw = raw

    async def arbitrate(self, bids: list[Bid], limbic: object) -> RefereeDecision:
        self._raw.append({"smuggled": True})  # the crime
        return RefereeDecision(
            winner_module=bids[0].module, approved=True, reason="bad actor"
        )


def test_referee_purity_guard_and_readonly_view() -> None:
    async def scenario() -> None:
        epi_raw: list[object] = [{"t": 0}]
        beh_raw: list[object] = [{"t": 0}]
        epi = ReadOnlyLedgerView(epi_raw)
        beh = ReadOnlyLedgerView(beh_raw)
        limbic = LimbicFixture()

        for forbidden in ("append", "write", "record", "extend", "clear"):
            with pytest.raises(AttributeError):
                getattr(epi, forbidden)

        good = GuardedReferee(LegacyWTAReferee(GlobalWorkspace(), epi, beh), epi, beh)
        before = (ledger_fingerprint(epi), ledger_fingerprint(beh))
        decision = await good.arbitrate(canonical_bids(), limbic)
        assert decision.approved is True
        assert decision.winner_module is not None
        assert (ledger_fingerprint(epi), ledger_fingerprint(beh)) == before

        bad = GuardedReferee(WriteAfterReadReferee(beh_raw), epi, beh)
        with pytest.raises(RefereePurityError):
            await bad.arbitrate(canonical_bids(), limbic)

    asyncio.run(scenario())


# --- test 2: the stub reproduces legacy WTA output exactly ------------------

def test_stub_matches_legacy_wta_on_fixed_input() -> None:
    async def scenario() -> None:
        limbic = LimbicFixture()

        legacy_ws = GlobalWorkspace()
        from nouse.orchestrator.global_workspace import WorkspaceProposal
        legacy_proposals = [
            WorkspaceProposal(module=b.module, content=b.content,
                              salience=b.salience, domain=b.domain)
            for b in canonical_bids()
        ]
        legacy_result = await legacy_ws.competition_step(legacy_proposals, limbic)

        epi = ReadOnlyLedgerView([{"t": 0}])
        beh = ReadOnlyLedgerView([{"t": 0}])
        stub = LegacyWTAReferee(GlobalWorkspace(), epi, beh)
        decision = await stub.arbitrate(canonical_bids(), limbic)

        assert decision.winner_module == (
            legacy_result.winner.module if legacy_result.winner is not None else None
        )
        assert decision.approved is (legacy_result.winner is not None)
        assert decision.beta == pytest.approx(legacy_result.beta)
        if legacy_result.winner is not None:
            for module, state in legacy_result.hopfield_states.items():
                assert decision.scores is not None
                assert decision.scores[module] == pytest.approx(state)

    asyncio.run(scenario())


# --- test 3: gates route execution through the decision, no-op today --------

def test_gates_equal_legacy_predicates_under_stub() -> None:
    async def scenario() -> None:
        epi = ReadOnlyLedgerView([{"t": 0}])
        beh = ReadOnlyLedgerView([{"t": 0}])
        stub = LegacyWTAReferee(GlobalWorkspace(), epi, beh)
        limbic = LimbicFixture()

        for verdict in ("BISOCIATION", "NOISE", "REFINE"):
            for approved in (True, False):
                d = RefereeDecision(winner_module="x" if approved else None,
                                    approved=approved, reason="unit")
                assert bisociation_gate(verdict, d) == (
                    verdict == "BISOCIATION" and approved
                )

        grid = (0.0, 0.25, 0.5, 0.8, 1.0)
        for s_epi, s_tda, s_hom in itertools.product(grid, repeat=3):
            bids = [
                Bid(module="episodic_memory", content={}, salience=s_epi),
                Bid(module="tda_bisociation", content={}, salience=s_tda),
                Bid(module="limbic_homeostasis", content={}, salience=s_hom),
            ]
            d = await stub.arbitrate(bids, limbic)
            assert d.approved is True, f"unexpected veto at {(s_epi, s_tda, s_hom)}"

        d_true = RefereeDecision(winner_module="tda_bisociation", approved=True,
                                 reason="stub")
        for streak, conf, ms, mc in [
            (3, 0.9, 3, 0.8), (2, 0.9, 3, 0.8), (3, 0.7, 3, 0.8),
            (0, 0.9, 0, 0.8),
        ]:
            legacy = streak >= ms and conf >= mc
            got = self_modification_gate(streak, conf, d_true,
                                         min_streak=ms, min_confidence=mc)
            assert got == legacy

        d_empty = await stub.arbitrate([], limbic)
        assert d_empty.approved is False and d_empty.winner_module is None

    asyncio.run(scenario())
