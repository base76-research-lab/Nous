"""
b76.daemon.research_queue — autonom gap-detektion + research-queue
===================================================================
Bygger en enkel persistent kö av kunskapsgap som B76 kan utforska autonomt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from nouse.field.surface import FieldSurface

DEFAULT_QUEUE_PATH = Path.home() / ".local" / "share" / "nouse" / "research_queue.json"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_utc(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _retry_after_for_attempts(attempts: int) -> str:
    # 45s, 90s, 180s ... upp till 15 minuter.
    safe_attempts = max(1, int(attempts))
    delay_sec = min(900, 45 * (2 ** (safe_attempts - 1)))
    return (datetime.now(timezone.utc) + timedelta(seconds=delay_sec)).isoformat()


def _load(path: Path = DEFAULT_QUEUE_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return [r for r in raw if isinstance(r, dict)]


def _save(rows: list[dict[str, Any]], path: Path = DEFAULT_QUEUE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _next_id(rows: list[dict[str, Any]]) -> int:
    max_id = 0
    for r in rows:
        rid = r.get("id")
        if isinstance(rid, int) and rid > max_id:
            max_id = rid
    return max_id + 1


def _concept_connectivity(field: FieldSurface, name: str) -> int:
    out_degree = len(field.out_relations(name))
    in_degree = field.in_degree(name)
    return int(out_degree + in_degree)


def _detect_domain_fragmentation_gaps(field: FieldSurface, max_candidates: int = 8) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for domain in field.domains():
        profile = field.domain_tda_profile(domain, max_epsilon=2.0)
        h0 = int(profile.get("h0", 1) or 1)
        n_concepts = int(profile.get("n_concepts", 0) or 0)
        if h0 <= 1 or n_concepts < 2:
            continue

        concepts = [c["name"] for c in field.concepts(domain=domain) if c.get("name")]
        if len(concepts) < 2:
            continue

        ranked = sorted(concepts, key=lambda c: _concept_connectivity(field, c))
        sample = ranked[: min(4, len(ranked))]

        priority = min(1.0, 0.3 + 0.12 * h0 + 0.04 * min(n_concepts, 10))
        query = (
            f"Kartlägg och förklara samband mellan {', '.join(sample)} i domänen '{domain}'. "
            "Hitta mekanismer, empiriska stöd och eventuella motsägelser."
        )

        candidates.append(
            {
                "domain": domain,
                "concepts": sample,
                "query": query,
                "rationale": f"Domänen är fragmenterad (H0={h0}) och behöver nya bryggor.",
                "priority": round(priority, 3),
                "gap_type": "fragmented_domain",
            }
        )

    candidates.sort(key=lambda c: float(c["priority"]), reverse=True)
    return candidates[:max_candidates]


def _detect_isolated_concept_gaps(field: FieldSurface, max_candidates: int = 6) -> list[dict[str, Any]]:
    all_concepts = field.concepts()
    if not all_concepts:
        return []

    isolated: list[dict[str, Any]] = []
    for c in all_concepts:
        name = c.get("name")
        if not name:
            continue
        connectivity = _concept_connectivity(field, name)
        if connectivity == 0:
            isolated.append({
                "name": name,
                "domain": c.get("domain") or "okänd",
            })

    if not isolated:
        return []

    by_domain: dict[str, list[str]] = {}
    for row in isolated:
        by_domain.setdefault(row["domain"], []).append(row["name"])

    candidates: list[dict[str, Any]] = []
    for domain, names in sorted(by_domain.items(), key=lambda kv: len(kv[1]), reverse=True):
        sample = names[: min(4, len(names))]
        priority = min(1.0, 0.42 + 0.05 * len(sample))
        query = (
            f"Undersök hur de isolerade koncepten {', '.join(sample)} i '{domain}' kan kopplas "
            "till etablerad kunskap med tydlig evidens och antaganden."
        )
        candidates.append(
            {
                "domain": domain,
                "concepts": sample,
                "query": query,
                "rationale": "Koncepten saknar relationer och riskerar att bli kunskapsöar.",
                "priority": round(priority, 3),
                "gap_type": "isolated_concepts",
            }
        )

    candidates.sort(key=lambda c: float(c["priority"]), reverse=True)
    return candidates[:max_candidates]


def detect_knowledge_gaps(field: FieldSurface, max_candidates: int = 10) -> list[dict[str, Any]]:
    """Identifiera gap som lämpar sig för autonom research."""
    candidates = []
    candidates.extend(_detect_domain_fragmentation_gaps(field, max_candidates=max_candidates))
    candidates.extend(_detect_isolated_concept_gaps(field, max_candidates=max_candidates))
    candidates.sort(key=lambda c: float(c.get("priority", 0.0)), reverse=True)
    return candidates[:max_candidates]


def _task_key(item: dict[str, Any]) -> str:
    concepts = item.get("concepts") or []
    return "|".join(
        [
            str(item.get("gap_type", "?")),
            str(item.get("domain", "okänd")),
            ",".join(sorted(str(c) for c in concepts)),
            str(item.get("query", "")).strip().lower(),
        ]
    )


def enqueue_gap_tasks(
    field: FieldSurface,
    max_new: int = 5,
    seed_tasks: list[dict[str, Any]] | None = None,
    detect_gaps: bool = True,
    path: Path = DEFAULT_QUEUE_PATH,
) -> list[dict[str, Any]]:
    """Lägg till nya gap-tasks i kön (utan dubbletter)."""
    rows = _load(path)
    existing = {_task_key(r): r for r in rows}

    new_rows: list[dict[str, Any]] = []
    next_id = _next_id(rows)

    candidates: list[dict[str, Any]] = []
    candidates.extend(seed_tasks or [])
    if detect_gaps:
        candidates.extend(detect_knowledge_gaps(field, max_candidates=max_new * 3))

    for item in candidates:
        key = _task_key(item)
        if key in existing:
            continue

        row = {
            "id": next_id,
            "status": "pending",
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
            "started_at": None,
            "completed_at": None,
            "attempts": 0,
            "last_error": "",
            "retry_after": None,
            "last_report_chars": 0,
            "added_relations": 0,
            "domain": item.get("domain", "okänd"),
            "concepts": list(item.get("concepts") or []),
            "gap_type": item.get("gap_type", "unknown"),
            "priority": float(item.get("priority", 0.5)),
            "query": str(item.get("query", "")),
            "rationale": str(item.get("rationale", "")),
            "source": str(item.get("source") or "gap_detector_v1"),
            "hitl_interrupt_id": None,
            "hitl_status": "none",
            "hitl_approved": False,
        }
        next_id += 1
        rows.append(row)
        new_rows.append(row)
        existing[key] = row

        if len(new_rows) >= max_new:
            break

    if new_rows:
        _save(rows, path)
    return new_rows


def claim_next_task(path: Path = DEFAULT_QUEUE_PATH) -> dict[str, Any] | None:
    rows = _load(path)
    now = datetime.now(timezone.utc)
    pending: list[dict[str, Any]] = []
    for r in rows:
        if r.get("status") != "pending":
            continue
        retry_after = _parse_utc(r.get("retry_after"))
        if retry_after and retry_after > now:
            continue
        pending.append(r)
    if not pending:
        return None

    pending.sort(
        key=lambda r: (
            -float(r.get("priority", 0.0)),
            int(r.get("attempts", 0)),
            int(r.get("id", 0)),
        )
    )
    task_id = int(pending[0]["id"])

    selected: dict[str, Any] | None = None
    for r in rows:
        if int(r.get("id", -1)) != task_id:
            continue
        r["status"] = "in_progress"
        r["updated_at"] = _utcnow()
        r["started_at"] = _utcnow()
        r["attempts"] = int(r.get("attempts", 0)) + 1
        r["retry_after"] = None
        selected = dict(r)
        break

    _save(rows, path)
    return selected


def complete_task(
    task_id: int,
    added_relations: int,
    report_chars: int,
    avg_evidence: float | None = None,
    max_evidence: float | None = None,
    tier_counts: dict[str, int] | None = None,
    path: Path = DEFAULT_QUEUE_PATH,
) -> None:
    rows = _load(path)
    for r in rows:
        if int(r.get("id", -1)) != int(task_id):
            continue
        r["status"] = "done"
        r["updated_at"] = _utcnow()
        r["completed_at"] = _utcnow()
        r["last_error"] = ""
        r["retry_after"] = None
        r["added_relations"] = int(added_relations)
        r["last_report_chars"] = int(report_chars)
        r["hitl_status"] = (
            "approved" if bool(r.get("hitl_approved")) else str(r.get("hitl_status") or "none")
        )
        if avg_evidence is not None:
            r["avg_evidence"] = float(avg_evidence)
        if max_evidence is not None:
            r["max_evidence"] = float(max_evidence)
        if tier_counts is not None:
            r["tier_counts"] = {
                "hypotes": int(tier_counts.get("hypotes", 0)),
                "indikation": int(tier_counts.get("indikation", 0)),
                "validerad": int(tier_counts.get("validerad", 0)),
            }
        break
    _save(rows, path)


def fail_task(task_id: int, reason: str, path: Path = DEFAULT_QUEUE_PATH) -> None:
    rows = _load(path)
    for r in rows:
        if int(r.get("id", -1)) != int(task_id):
            continue
        attempts = int(r.get("attempts", 0))
        r["status"] = "failed" if attempts >= 3 else "pending"
        r["updated_at"] = _utcnow()
        r["last_error"] = str(reason)[:500]
        r["retry_after"] = None
        if r["status"] == "pending":
            r["retry_after"] = _retry_after_for_attempts(attempts)
        break
    _save(rows, path)


def pause_task_for_hitl(
    task_id: int,
    *,
    interrupt_id: int,
    reason: str,
    path: Path = DEFAULT_QUEUE_PATH,
) -> dict[str, Any] | None:
    rows = _load(path)
    out: dict[str, Any] | None = None
    for r in rows:
        if int(r.get("id", -1)) != int(task_id):
            continue
        r["status"] = "awaiting_approval"
        r["updated_at"] = _utcnow()
        r["last_error"] = str(reason)[:500]
        r["hitl_interrupt_id"] = int(interrupt_id)
        r["hitl_status"] = "pending"
        r["hitl_approved"] = False
        out = dict(r)
        break
    _save(rows, path)
    return out


def approve_task_after_hitl(
    task_id: int,
    *,
    note: str = "",
    path: Path = DEFAULT_QUEUE_PATH,
) -> dict[str, Any] | None:
    rows = _load(path)
    out: dict[str, Any] | None = None
    for r in rows:
        if int(r.get("id", -1)) != int(task_id):
            continue
        r["status"] = "pending"
        r["updated_at"] = _utcnow()
        r["last_error"] = str(note or "").strip()[:500]
        r["hitl_status"] = "approved"
        r["hitl_approved"] = True
        out = dict(r)
        break
    _save(rows, path)
    return out


def reject_task_after_hitl(
    task_id: int,
    *,
    reason: str,
    path: Path = DEFAULT_QUEUE_PATH,
) -> dict[str, Any] | None:
    rows = _load(path)
    out: dict[str, Any] | None = None
    for r in rows:
        if int(r.get("id", -1)) != int(task_id):
            continue
        r["status"] = "failed"
        r["updated_at"] = _utcnow()
        r["last_error"] = str(reason)[:500]
        r["hitl_status"] = "rejected"
        r["hitl_approved"] = False
        out = dict(r)
        break
    _save(rows, path)
    return out


def queue_stats(path: Path = DEFAULT_QUEUE_PATH) -> dict[str, Any]:
    rows = _load(path)
    now = datetime.now(timezone.utc)
    counts = {
        "pending": 0,
        "in_progress": 0,
        "done": 0,
        "failed": 0,
        "awaiting_approval": 0,
        "cooling_down": 0,
    }
    for r in rows:
        status = str(r.get("status", "pending"))
        if status in counts:
            counts[status] += 1
        if status == "pending":
            retry_after = _parse_utc(r.get("retry_after"))
            if retry_after and retry_after > now:
                counts["cooling_down"] += 1

    return {
        "total": len(rows),
        **counts,
        "path": str(path),
    }


def peek_tasks(limit: int = 5, path: Path = DEFAULT_QUEUE_PATH) -> list[dict[str, Any]]:
    rows = _load(path)
    order = {
        "pending": 0,
        "awaiting_approval": 1,
        "in_progress": 2,
        "done": 3,
        "failed": 4,
    }
    rows.sort(key=lambda r: (
        order.get(str(r.get("status", "pending")), 9),
        -float(r.get("priority", 0.0)),
        int(r.get("id", 0)),
    ))
    return rows[:max(1, limit)]


def list_tasks(
    *,
    status: str | None = None,
    limit: int | None = None,
    path: Path = DEFAULT_QUEUE_PATH,
) -> list[dict[str, Any]]:
    rows = _load(path)
    if status:
        want = str(status).strip().lower()
        rows = [r for r in rows if str(r.get("status", "")).strip().lower() == want]
    rows.sort(key=lambda r: int(r.get("id", 0) or 0), reverse=True)
    if limit is None:
        return rows
    return rows[: max(1, int(limit))]


def retry_failed_tasks(
    *,
    limit: int = 5,
    reason: str = "manuell retry",
    path: Path = DEFAULT_QUEUE_PATH,
) -> list[dict[str, Any]]:
    rows = _load(path)
    out: list[dict[str, Any]] = []
    budget = max(1, int(limit or 1))
    for r in rows:
        if len(out) >= budget:
            break
        if str(r.get("status", "")).strip().lower() != "failed":
            continue
        r["status"] = "pending"
        r["updated_at"] = _utcnow()
        r["last_error"] = str(reason or "manuell retry")[:500]
        r["retry_after"] = None
        out.append(dict(r))
    if out:
        _save(rows, path)
    return out
