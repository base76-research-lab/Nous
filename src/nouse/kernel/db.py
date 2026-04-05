from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _quote(value: str) -> str:
    return value.replace("'", "''")


@dataclass
class ResidualEdgeState:
    edge_id: str
    src: str
    rel_type: str
    tgt: str
    w: float = 0.02
    r: float = 0.0
    u: float = 0.80
    evidence_score: float = 0.0
    provenance: str = "unknown"
    created_at: str = ""
    last_snapshot_cycle: int = -1
    last_snapshot_r: float = 0.0
    last_snapshot_w: float = 0.0
    last_snapshot_u: float = 0.0

    def __post_init__(self) -> None:
        self.w = _clamp(self.w, 0.0, 1.0)
        self.u = _clamp(self.u, 0.0, 1.0)
        self.r = _clamp(self.r, -2.0, 2.0)
        self.evidence_score = _clamp(self.evidence_score, 0.0, 1.0)
        if not self.created_at:
            self.created_at = _now_iso()


@dataclass
class ArchivedEdgeRecord:
    edge_id: str
    src: str
    rel_type: str
    tgt: str
    w: float
    u: float
    evidence_score: float
    provenance: str
    created_at: str
    updated_at: str
    crystallized_at: str | None = None
    snapshot_cycle: int | None = None
    snapshot_reason: str = "manual"


class BrainDB:
    """Two-plane Brain DB:

    - Live plane (in memory): ResidualEdgeState with dynamic `r`.
    - Persistent plane (archive): canonical `w`, `u`, evidence, provenance.

    `r` is intentionally live-primary and not canonical persistent state.
    """

    def __init__(
        self,
        kuzu_path: str | Path,
        *,
        w_threshold: float = 0.60,
        u_ceiling: float = 0.40,
        r_decay: float = 0.89,
        snapshot_interval: int = 25,
        r_delta_snapshot: float = 0.30,
        use_kuzu: bool = True,
    ) -> None:
        self.kuzu_path = Path(kuzu_path)
        self.w_threshold = w_threshold
        self.u_ceiling = u_ceiling
        self.r_decay = r_decay
        self.snapshot_interval = max(1, snapshot_interval)
        self.r_delta_snapshot = max(0.0, r_delta_snapshot)

        self._cycle = 0
        self._live: dict[str, ResidualEdgeState] = {}
        self._archive: dict[str, ArchivedEdgeRecord] = {}

        self._sqlite_conn: sqlite3.Connection | None = None
        self._sqlite_write_enabled = False
        self._sqlite_error: str | None = None
        if use_kuzu:  # parameter kept for API compat
            self._init_sqlite()

    @property
    def cycle(self) -> int:
        return self._cycle

    @property
    def kuzu_error(self) -> str | None:
        return self._sqlite_error

    def _init_sqlite(self) -> None:
        path = self.kuzu_path.with_suffix(".sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._sqlite_conn = sqlite3.connect(str(path), check_same_thread=False)
            self._sqlite_conn.execute("PRAGMA journal_mode=WAL")
            self._sqlite_conn.execute("PRAGMA busy_timeout=5000")
            self._sqlite_write_enabled = True
            self._ensure_schema()
        except Exception as exc:  # pragma: no cover
            self._sqlite_error = f"init_failed: {exc}"
            self._sqlite_conn = None
            self._sqlite_write_enabled = False

    def _try_exec(self, query: str, params: tuple = ()) -> bool:
        if not self._sqlite_conn:
            return False
        try:
            self._sqlite_conn.execute(query, params)
            self._sqlite_conn.commit()
            return True
        except Exception as exc:  # pragma: no cover
            self._sqlite_error = f"query_failed: {exc}"
            return False

    def _ensure_schema(self) -> None:
        if not self._sqlite_conn:
            return
        self._sqlite_conn.executescript("""
            CREATE TABLE IF NOT EXISTS brain_node (
                node_id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS residual_edge (
                edge_id TEXT PRIMARY KEY,
                src TEXT NOT NULL,
                tgt TEXT NOT NULL,
                rel_type TEXT,
                w REAL,
                u REAL,
                evidence_score REAL,
                provenance TEXT,
                created_at TEXT,
                updated_at TEXT,
                crystallized_at TEXT,
                snapshot_cycle INTEGER,
                snapshot_reason TEXT
            );
        """)
        self._sqlite_conn.commit()

    def upsert_live_edge(
        self,
        edge_id: str,
        *,
        src: str,
        rel_type: str,
        tgt: str,
        w: float = 0.02,
        r: float = 0.0,
        u: float = 0.80,
        evidence_score: float = 0.0,
        provenance: str = "unknown",
    ) -> ResidualEdgeState:
        st = ResidualEdgeState(
            edge_id=edge_id,
            src=src,
            rel_type=rel_type,
            tgt=tgt,
            w=w,
            r=r,
            u=u,
            evidence_score=evidence_score,
            provenance=provenance,
        )
        self._live[edge_id] = st
        return st

    def get_live_edge(self, edge_id: str) -> ResidualEdgeState | None:
        return self._live.get(edge_id)

    def update_live_edge(
        self,
        edge_id: str,
        *,
        w_delta: float = 0.0,
        r_delta: float = 0.0,
        u_delta: float = 0.0,
        evidence_score: float | None = None,
        provenance: str | None = None,
    ) -> ResidualEdgeState:
        st = self._live[edge_id]
        st.w = _clamp(st.w + w_delta, 0.0, 1.0)
        st.r = _clamp(st.r + r_delta, -2.0, 2.0)
        st.u = _clamp(st.u + u_delta, 0.0, 1.0)
        if evidence_score is not None:
            st.evidence_score = _clamp(evidence_score, 0.0, 1.0)
        if provenance is not None:
            st.provenance = provenance
        return st

    def advance_cycle(self, cycles: int = 1) -> None:
        for _ in range(max(1, cycles)):
            self._cycle += 1
            for st in self._live.values():
                st.r = _clamp(st.r * self.r_decay, -2.0, 2.0)
            if any(self._should_snapshot(st) for st in self._live.values()):
                self.snapshot(force=False, reason="auto")

    def _should_snapshot(self, st: ResidualEdgeState) -> bool:
        if st.last_snapshot_cycle < 0:
            return True
        if self._cycle - st.last_snapshot_cycle >= self.snapshot_interval:
            return True
        if abs(st.r - st.last_snapshot_r) >= self.r_delta_snapshot:
            return True
        return False

    def crystallize_edge(self, edge_id: str) -> bool:
        st = self._live[edge_id]
        if st.w > self.w_threshold and st.u < self.u_ceiling:
            rec = ArchivedEdgeRecord(
                edge_id=st.edge_id,
                src=st.src,
                rel_type=st.rel_type,
                tgt=st.tgt,
                w=st.w,
                u=st.u,
                evidence_score=st.evidence_score,
                provenance=st.provenance,
                created_at=st.created_at,
                updated_at=_now_iso(),
                crystallized_at=_now_iso(),
                snapshot_cycle=self._cycle,
                snapshot_reason="crystallize",
            )
            self._write_archive(rec)
            st.last_snapshot_cycle = self._cycle
            st.last_snapshot_w = st.w
            st.last_snapshot_u = st.u
            st.last_snapshot_r = st.r
            return True
        return False

    def snapshot(self, *, force: bool = False, reason: str = "manual") -> int:
        written = 0
        for st in self._live.values():
            if not force and not self._should_snapshot(st):
                continue
            rec = ArchivedEdgeRecord(
                edge_id=st.edge_id,
                src=st.src,
                rel_type=st.rel_type,
                tgt=st.tgt,
                w=st.w,
                u=st.u,
                evidence_score=st.evidence_score,
                provenance=st.provenance,
                created_at=st.created_at,
                updated_at=_now_iso(),
                crystallized_at=None,
                snapshot_cycle=self._cycle,
                snapshot_reason=reason,
            )
            self._write_archive(rec)
            st.last_snapshot_cycle = self._cycle
            st.last_snapshot_w = st.w
            st.last_snapshot_u = st.u
            st.last_snapshot_r = st.r
            written += 1
        return written

    def shutdown(self) -> int:
        return self.snapshot(force=True, reason="shutdown")

    def get_archived_edge(self, edge_id: str) -> ArchivedEdgeRecord | None:
        return self._archive.get(edge_id)

    def iter_archived_edges(self) -> list[ArchivedEdgeRecord]:
        return list(self._archive.values())

    def _write_archive(self, rec: ArchivedEdgeRecord) -> None:
        self._archive[rec.edge_id] = rec
        self._write_kuzu_record(rec)

    def _write_kuzu_record(self, rec: ArchivedEdgeRecord) -> None:
        if not self._sqlite_conn or not self._sqlite_write_enabled:
            return
        try:
            self._sqlite_conn.execute(
                "INSERT OR REPLACE INTO brain_node (node_id) VALUES (?)", (rec.src,))
            self._sqlite_conn.execute(
                "INSERT OR REPLACE INTO brain_node (node_id) VALUES (?)", (rec.tgt,))
            self._sqlite_conn.execute(
                "INSERT OR REPLACE INTO residual_edge "
                "(edge_id, src, tgt, rel_type, w, u, evidence_score, provenance, "
                "created_at, updated_at, crystallized_at, snapshot_cycle, snapshot_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (rec.edge_id, rec.src, rec.tgt, rec.rel_type, rec.w, rec.u,
                 rec.evidence_score, rec.provenance, rec.created_at, rec.updated_at,
                 rec.crystallized_at or "", rec.snapshot_cycle if rec.snapshot_cycle is not None else -1,
                 rec.snapshot_reason))
            self._sqlite_conn.commit()
        except Exception as exc:
            self._sqlite_write_enabled = False
            self._sqlite_error = f"write_failed: {exc}"
