"""Load agent contracts from folders.

Two directories are scanned, same dual-dir pattern as
`nouse.plugins.loader` (builtin + runtime):

- ``NOUSE_AGENT_POLICY_DIR`` — the private, deployment-specific policy
  overlay (e.g. ``IIC/04_SYSTEM/agents/`` for this deployment). Not set by
  default; stage 03 fails closed (``POLICY_UNAVAILABLE``) without it. This
  repo intentionally ships no agent cards of its own — cards encode
  deployment-specific rules and belong in the overlay, not in the public
  package.
"""
from __future__ import annotations

import os
from pathlib import Path

from nouse.agent_system.contract import AgentContract, load_agent_contract


def policy_dir() -> Path | None:
    raw = os.getenv("NOUSE_AGENT_POLICY_DIR", "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.is_dir() else None


def load_all_agents() -> dict[str, AgentContract]:
    """Return {agent_id: AgentContract} for every AGENT.md under the policy dir.

    Empty dict if no policy dir is configured or it contains no cards —
    callers must treat an empty result as ROUTE_NOT_FOUND / POLICY_UNAVAILABLE,
    not as "no agents needed".
    """
    base = policy_dir()
    if base is None:
        return {}
    out: dict[str, AgentContract] = {}
    for card in sorted(base.glob("*/AGENT.md")):
        try:
            contract = load_agent_contract(card)
        except ValueError:
            continue
        if contract.id:
            out[contract.id] = contract
    return out


def read_policy_text(filename: str) -> str:
    """Read a plain policy file (e.g. jarvis-policy.md) from the overlay dir.

    Returns "" if unavailable — callers must treat that as
    POLICY_UNAVAILABLE, not as "no hard rules apply".
    """
    base = policy_dir()
    if base is None:
        return ""
    path = base / filename
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")
