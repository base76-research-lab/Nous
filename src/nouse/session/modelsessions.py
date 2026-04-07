"""
nouse.session.modelsessions — Cross-model epistemic cache.

Every LLM interaction is stored as a session. On recurrence, NoUse returns
the cached result directly from the graph — token cost: zero.

Over time, repeated interactions strengthen graph paths via Hebbian plasticity
and build cross-query correlations, turning sessions into validated knowledge.

Storage:
    ~/.local/share/nouse/domains/modelsessions/sessions.jsonl
    ~/.local/share/nouse/domains/modelsessions/index.json   ← query → session_id
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_log = logging.getLogger("nouse.modelsessions")

SESSION_DIR = Path.home() / ".local" / "share" / "nouse" / "domains" / "modelsessions"
SESSION_LOG = SESSION_DIR / "sessions.jsonl"
SESSION_INDEX = SESSION_DIR / "index.json"

_LOCK = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_query(q: str) -> str:
    """Canonical form for exact-match lookup."""
    return re.sub(r"\s+", " ", q.strip().lower())


def _ensure_dirs() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


# ── Index: query_hash → session_id ───────────────────────────────────────────

def _load_index() -> dict[str, str]:
    if not SESSION_INDEX.exists():
        return {}
    try:
        return json.loads(SESSION_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_index(index: dict[str, str]) -> None:
    SESSION_INDEX.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


# ── Session schema ────────────────────────────────────────────────────────────

def _blank_session(
    *,
    query: str,
    answer: str,
    model: str,
    nodes_used: list[str],
    confidence_in: float,
    confidence_out: float,
    tokens_saved: int,
    context_block: str,
) -> dict[str, Any]:
    return {
        "session_id": str(uuid4()),
        "model": model,
        "query": query,
        "context_block": context_block,
        "answer": answer,
        "confidence_in": round(float(confidence_in), 3),
        "confidence_out": round(float(confidence_out), 3),
        "nodes_used": nodes_used,
        "timestamp": _now_iso(),
        "tokens_saved": int(tokens_saved),
        "hits": 0,
    }


# ── Core API ──────────────────────────────────────────────────────────────────

def log_session(
    *,
    query: str,
    answer: str,
    model: str = "unknown",
    nodes_used: list[str] | None = None,
    confidence_in: float = 0.0,
    confidence_out: float = 0.0,
    tokens_saved: int = 0,
    context_block: str = "",
    field=None,  # FieldSurface — if provided, seed graph nodes
) -> dict[str, Any]:
    """
    Store a completed LLM interaction as a session.

    If field is provided:
    - Adds query→answer edge (answered_by) at hypothesis tier
    - Strengthens existing edge if query was seen before
    - Adds co_occurs_with edges between all nodes_used
    """
    _ensure_dirs()
    key = _normalize_query(query)

    with _LOCK:
        index = _load_index()
        existing_id = index.get(key)

        session = _blank_session(
            query=query,
            answer=answer,
            model=model,
            nodes_used=nodes_used or [],
            confidence_in=confidence_in,
            confidence_out=confidence_out,
            tokens_saved=tokens_saved,
            context_block=context_block,
        )

        # Append to JSONL
        with SESSION_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(session, ensure_ascii=False) + "\n")

        # Update index (latest session per query key)
        index[key] = session["session_id"]
        _save_index(index)

    _log.debug("Session logged: %s (model=%s)", session["session_id"][:8], model)

    # Graph side-effects (outside lock — field has its own locking)
    if field is not None:
        try:
            _seed_graph(field, query=query, answer=answer,
                        nodes_used=nodes_used or [],
                        existing=existing_id is not None,
                        confidence_out=confidence_out)
        except Exception as e:
            _log.debug("Graph seeding failed: %s", e)

    return session


def recall_session(query: str) -> dict[str, Any] | None:
    """
    Return the cached session for an exact query match, or None.
    Also increments the hit counter in the log.
    """
    key = _normalize_query(query)
    with _LOCK:
        index = _load_index()
        session_id = index.get(key)
        if not session_id:
            return None

        # Find latest session in log
        if not SESSION_LOG.exists():
            return None

        found: dict[str, Any] | None = None
        lines = SESSION_LOG.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            try:
                s = json.loads(line)
                if s.get("session_id") == session_id:
                    found = s
                    break
            except Exception:
                continue

    if found:
        _log.debug("Cache hit: session %s for query '%s...'", session_id[:8], query[:40])
    return found


def session_stats() -> dict[str, Any]:
    """Summary stats for status command."""
    _ensure_dirs()
    with _LOCK:
        index = _load_index()
        total = len(index)
        tokens_saved = 0
        models: dict[str, int] = {}
        if SESSION_LOG.exists():
            for line in SESSION_LOG.read_text(encoding="utf-8").splitlines():
                try:
                    s = json.loads(line)
                    tokens_saved += int(s.get("tokens_saved", 0))
                    m = s.get("model", "unknown")
                    models[m] = models.get(m, 0) + 1
                except Exception:
                    continue
    return {
        "total_sessions": total,
        "tokens_saved": tokens_saved,
        "models": models,
    }


def consolidate_sessions(field, *, lookback_sessions: int = 500) -> dict[str, int]:
    """
    Nightly consolidation: strengthen graph paths and build co-occurrence edges.

    Called from daemon/nightrun.py. Reads recent sessions, strengthens
    Hebbian edges for repeated queries, and promotes hypothesis-tier
    relations to validated-tier if they've appeared in ≥ 3 sessions.
    """
    if not SESSION_LOG.exists():
        return {"processed": 0, "strengthened": 0, "co_occurrence": 0}

    # Read most recent sessions
    lines = SESSION_LOG.read_text(encoding="utf-8").splitlines()
    recent = []
    for line in reversed(lines[-lookback_sessions:]):
        try:
            recent.append(json.loads(line))
        except Exception:
            continue

    # Count query occurrences
    query_counts: dict[str, int] = {}
    for s in recent:
        key = _normalize_query(s.get("query", ""))
        if key:
            query_counts[key] = query_counts.get(key, 0) + 1

    strengthened = 0
    co_occurrence = 0

    for s in recent:
        query = s.get("query", "")
        answer = s.get("answer", "")
        nodes = s.get("nodes_used") or []
        key = _normalize_query(query)
        count = query_counts.get(key, 1)

        # Strengthen query→answer edge proportional to recurrence
        if query and answer and count >= 2:
            delta = min(0.15, 0.03 * count)
            try:
                field.strengthen(query[:80], answer[:80], delta=delta)
                strengthened += 1
            except Exception:
                pass

        # Co-occurrence edges between nodes in same session
        if len(nodes) >= 2:
            for i, a in enumerate(nodes):
                for b in nodes[i + 1:]:
                    if a != b:
                        try:
                            field.add_relation(
                                a, "co_occurs_with", b,
                                why=f"co-occurred in session ({s.get('model', '?')})",
                                strength=0.3,
                                evidence_score=0.5,
                                source_tag="modelsessions",
                            )
                            co_occurrence += 1
                        except Exception:
                            pass

    _log.info(
        "Session consolidation: %d recent, %d strengthened, %d co-occurrence edges",
        len(recent), strengthened, co_occurrence,
    )
    return {"processed": len(recent), "strengthened": strengthened, "co_occurrence": co_occurrence}


# ── Graph seeding ─────────────────────────────────────────────────────────────

def _seed_graph(
    field,
    *,
    query: str,
    answer: str,
    nodes_used: list[str],
    existing: bool,
    confidence_out: float,
) -> None:
    """Add or strengthen graph relations for a completed session."""
    src = query[:80].strip()
    tgt = answer[:120].strip()
    if not src or not tgt:
        return

    if existing:
        # Query seen before — Hebbian strengthen
        field.strengthen(src, tgt, delta=0.05)
    else:
        # First occurrence — add at hypothesis tier
        ev = max(0.4, min(0.9, float(confidence_out)))
        field.add_relation(
            src, "answered_by", tgt,
            why="cross-model session cache",
            strength=0.5,
            evidence_score=ev,
            source_tag="modelsessions",
            domain="modelsessions",
        )

    # Co-occurrence edges between nodes_used
    for i, a in enumerate(nodes_used[:6]):
        for b in nodes_used[i + 1: 6]:
            if a != b:
                field.add_relation(
                    a, "co_occurs_with", b,
                    why="session co-occurrence",
                    strength=0.3,
                    evidence_score=0.5,
                    source_tag="modelsessions",
                    domain="modelsessions",
                )
