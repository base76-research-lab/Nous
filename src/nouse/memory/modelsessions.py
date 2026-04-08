"""
modelsessions.py — Cross-model session memory for NoUse
Stores/retrieves all LLM interactions for zero-token replay and Hebbian correlation.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4
from datetime import datetime

MODELSESSIONS_PATH = Path.home() / ".local" / "share" / "nouse" / "domains" / "modelsessions" / "sessions.jsonl"
_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def log_session(
    model: str,
    query: str,
    answer: str,
    context_block: str = "",
    confidence_in: float = None,
    confidence_out: float = None,
    nodes_used: list[str] = None,
    tokens_saved: int = 0,
    session_id: str = None,
    timestamp: str = None,
    extra: dict[str, Any] = None,
    path: Path = MODELSESSIONS_PATH,
) -> None:
    """Append a session interaction to the modelsessions log."""
    row = {
        "session_id": session_id or f"ms_{uuid4().hex[:10]}",
        "model": model,
        "query": query,
        "context_block": context_block,
        "answer": answer,
        "confidence_in": confidence_in,
        "confidence_out": confidence_out,
        "nodes_used": nodes_used or [],
        "timestamp": timestamp or _now_iso(),
        "tokens_saved": tokens_saved,
    }
    if extra:
        row.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def iter_sessions(path: Path = MODELSESSIONS_PATH, limit: int = 1000) -> list[dict[str, Any]]:
    """Yield session dicts from the log, most recent first."""
    if not path.exists():
        return []
    with _LOCK:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
    return [json.loads(line) for line in reversed(lines)]


def find_session(query: str, model: str = None, path: Path = MODELSESSIONS_PATH) -> dict[str, Any] | None:
    """Return the most recent session matching the query (exact match)."""
    for row in iter_sessions(path=path, limit=1000):
        if row.get("query") == query and (model is None or row.get("model") == model):
            return row
    return None
