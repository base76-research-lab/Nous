from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nouse.config.paths import path_from_env
from nouse.persona import assistant_entity_name, persona_identity_seed

_LOCK = threading.Lock()
_MAX_MEMORIES = 240
_SELF_TRAINING_FORMULA = "known_data(any source) + meta_reflection + reflections"


def living_core_path(path: Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    return path_from_env("NOUSE_LIVING_CORE_PATH", "self/living_core.json")


LIVING_CORE_PATH = living_core_path()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _runtime_mode() -> str:
    return str(os.getenv("NOUSE_MODE", "project")).strip().lower()


def _tokenize(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[0-9a-zåäö_]+", str(text or "").strip().lower()) if tok}


def _contains_phrase(text: str, phrase: str) -> bool:
    hay = f" {str(text or '').strip().lower()} "
    needle = f" {str(phrase or '').strip().lower()} "
    return bool(needle.strip() and needle in hay)


def _default_identity() -> dict[str, Any]:
    return persona_identity_seed(runtime_mode=_runtime_mode())


def _blank_state() -> dict[str, Any]:
    now = _now_iso()
    return {
        "version": 1,
        "created_at": now,
        "updated_at": now,
        "identity": _default_identity(),
        "drives": {
            "active": "maintenance",
            "scores": {
                "curiosity": 0.5,
                "maintenance": 0.5,
                "improvement": 0.5,
                "recovery": 0.5,
            },
            "goals": ["keep core services healthy", "reduce uncertainty in critical domains"],
            "updated_at": now,
        },
        "homeostasis": {
            "energy": 0.5,
            "focus": 0.5,
            "risk": 0.4,
            "mode": "steady",
            "strategy": "balanced execution",
            "updated_at": now,
        },
        "last_reflection": {
            "cycle": 0,
            "thought": "System initialized and ready.",
            "feeling": "stable and attentive",
            "responsibility": (
                "Follow mission constraints, protect safety boundaries, and keep traceability."
            ),
            "ts": now,
        },
        "self_training": {
            "formula": _SELF_TRAINING_FORMULA,
            "iterations": 0,
            "source_usage": {},
            "last": {
                "known_data_sources": [],
                "meta_reflection": "",
                "reflection": "",
                "ts": now,
            },
            "updated_at": now,
        },
    }


def _sanitize_memory_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    note = str(item.get("note") or "").strip()
    if not note:
        return None
    tags_raw = item.get("tags")
    tags = [str(x).strip() for x in (tags_raw or []) if str(x).strip()] if isinstance(tags_raw, list) else []
    return {
        "ts": str(item.get("ts") or _now_iso()),
        "note": note[:4000],
        "tags": tags[:12],
        "session_id": str(item.get("session_id") or "").strip() or None,
        "run_id": str(item.get("run_id") or "").strip() or None,
        "kind": str(item.get("kind") or "").strip() or "note",
    }


def _normalize_identity(raw: Any) -> dict[str, Any]:
    base = _default_identity()
    if not isinstance(raw, dict):
        return base
    raw_name = str(raw.get("name") or base["name"]).strip() or base["name"]
    if raw_name.casefold() in {"b76", "nouse", "no use", "nouse-ai", "nouseai", "nouse ai", "nouse_ai", "nouse-ai"}:
        raw_name = assistant_entity_name()
    base["name"] = raw_name
    raw_greeting = str(raw.get("greeting") or base.get("greeting") or "").strip()
    if raw_greeting:
        try:
            base["greeting"] = raw_greeting.format(name=base["name"])
        except Exception:
            base["greeting"] = raw_greeting
    base["mission"] = str(raw.get("mission") or base["mission"]).strip() or base["mission"]
    base["personality"] = (
        str(raw.get("personality") or base["personality"]).strip() or base["personality"]
    )
    values_raw = raw.get("values")
    if isinstance(values_raw, list):
        values = [str(x).strip() for x in values_raw if str(x).strip()]
        if values:
            base["values"] = values[:16]
    boundaries_raw = raw.get("boundaries")
    if isinstance(boundaries_raw, list):
        boundaries = [str(x).strip() for x in boundaries_raw if str(x).strip()]
        if boundaries:
            base["boundaries"] = boundaries[:16]
    mem_raw = raw.get("memories")
    memories: list[dict[str, Any]] = []
    if isinstance(mem_raw, list):
        for item in mem_raw:
            clean = _sanitize_memory_item(item)
            if clean:
                memories.append(clean)
    base["memories"] = memories[-_MAX_MEMORIES:]
    return base


def _normalize_scores(raw: Any) -> dict[str, float]:
    names = ("curiosity", "maintenance", "improvement", "recovery")
    out = {name: 0.5 for name in names}
    if not isinstance(raw, dict):
        return out
    for name in names:
        try:
            out[name] = _clamp(float(raw.get(name, out[name])))
        except (TypeError, ValueError):
            out[name] = out[name]
    return out


def _normalize_self_training(raw: Any) -> dict[str, Any]:
    now = _now_iso()
    base = {
        "formula": _SELF_TRAINING_FORMULA,
        "iterations": 0,
        "source_usage": {},
        "last": {
            "known_data_sources": [],
            "meta_reflection": "",
            "reflection": "",
            "ts": now,
        },
        "updated_at": now,
    }
    if not isinstance(raw, dict):
        return base

    formula = str(raw.get("formula") or _SELF_TRAINING_FORMULA).strip()
    base["formula"] = formula[:500] if formula else _SELF_TRAINING_FORMULA
    base["iterations"] = max(0, _safe_int(raw.get("iterations", 0), 0))

    src_raw = raw.get("source_usage")
    if isinstance(src_raw, dict):
        clean_src: dict[str, int] = {}
        for key, value in src_raw.items():
            name = str(key or "").strip().lower()
            if not name:
                continue
            clean_src[name[:64]] = max(0, _safe_int(value, 0))
        base["source_usage"] = clean_src

    last_raw = raw.get("last")
    if isinstance(last_raw, dict):
        known_sources_raw = last_raw.get("known_data_sources")
        known_sources = (
            [str(x).strip().lower() for x in known_sources_raw if str(x).strip()]
            if isinstance(known_sources_raw, list)
            else []
        )
        dedup_sources: list[str] = []
        seen = set()
        for item in known_sources:
            if item in seen:
                continue
            seen.add(item)
            dedup_sources.append(item[:64])
        base["last"] = {
            "known_data_sources": dedup_sources[:12],
            "meta_reflection": str(last_raw.get("meta_reflection") or "").strip()[:1200],
            "reflection": str(last_raw.get("reflection") or "").strip()[:1200],
            "ts": str(last_raw.get("ts") or now),
        }
    base["updated_at"] = str(raw.get("updated_at") or now)
    return base


def _normalize_state(raw: Any) -> dict[str, Any]:
    base = _blank_state()
    if not isinstance(raw, dict):
        return base

    base["version"] = max(1, _safe_int(raw.get("version", 1), 1))
    base["created_at"] = str(raw.get("created_at") or base["created_at"])
    base["updated_at"] = str(raw.get("updated_at") or base["updated_at"])
    base["identity"] = _normalize_identity(raw.get("identity"))

    drives_raw = raw.get("drives")
    if isinstance(drives_raw, dict):
        scores = _normalize_scores(drives_raw.get("scores"))
        active = str(drives_raw.get("active") or "maintenance").strip() or "maintenance"
        if active not in scores:
            active = "maintenance"
        goals_raw = drives_raw.get("goals")
        goals = [str(x).strip() for x in (goals_raw or []) if str(x).strip()] if isinstance(goals_raw, list) else []
        base["drives"] = {
            "active": active,
            "scores": scores,
            "goals": goals[:6],
            "updated_at": str(drives_raw.get("updated_at") or base["drives"]["updated_at"]),
        }

    homeo_raw = raw.get("homeostasis")
    if isinstance(homeo_raw, dict):
        base["homeostasis"] = {
            "energy": _clamp(_safe_float(homeo_raw.get("energy"), 0.5)),
            "focus": _clamp(_safe_float(homeo_raw.get("focus"), 0.5)),
            "risk": _clamp(_safe_float(homeo_raw.get("risk"), 0.4)),
            "mode": str(homeo_raw.get("mode") or "steady").strip() or "steady",
            "strategy": str(homeo_raw.get("strategy") or "balanced execution").strip()
            or "balanced execution",
            "updated_at": str(homeo_raw.get("updated_at") or base["homeostasis"]["updated_at"]),
        }

    reflection_raw = raw.get("last_reflection")
    if isinstance(reflection_raw, dict):
        base["last_reflection"] = {
            "cycle": max(0, _safe_int(reflection_raw.get("cycle", 0), 0)),
            "thought": str(reflection_raw.get("thought") or "").strip() or base["last_reflection"]["thought"],
            "feeling": str(reflection_raw.get("feeling") or "").strip() or base["last_reflection"]["feeling"],
            "responsibility": (
                str(reflection_raw.get("responsibility") or "").strip()
                or base["last_reflection"]["responsibility"]
            ),
            "ts": str(reflection_raw.get("ts") or base["last_reflection"]["ts"]),
        }
    base["self_training"] = _normalize_self_training(raw.get("self_training"))
    return base


def load_living_core(path: Path | None = None) -> dict[str, Any]:
    path = living_core_path(path)
    if not path.exists():
        return _blank_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _blank_state()
    return _normalize_state(raw)


def save_living_core(state: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    path = living_core_path(path)
    out = _normalize_state(state)
    out["updated_at"] = _now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def ensure_living_core(path: Path | None = None) -> dict[str, Any]:
    path = living_core_path(path)
    with _LOCK:
        state = load_living_core(path)
        return save_living_core(state, path)


def update_identity_profile(
    *,
    mission: str | None = None,
    values: list[str] | None = None,
    personality: str | None = None,
    greeting: str | None = None,
    boundaries: list[str] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    path = living_core_path(path)
    with _LOCK:
        state = load_living_core(path)
        identity = state.setdefault("identity", _default_identity())
        if mission is not None:
            clean = str(mission).strip()
            if clean:
                identity["mission"] = clean[:1600]
        if values is not None:
            clean_values = [str(x).strip() for x in values if str(x).strip()]
            if clean_values:
                identity["values"] = clean_values[:16]
        if personality is not None:
            clean = str(personality).strip()
            if clean:
                identity["personality"] = clean[:1600]
        if greeting is not None:
            clean = str(greeting).strip()
            if clean:
                identity["greeting"] = clean[:400]
        if boundaries is not None:
            clean_boundaries = [str(x).strip() for x in boundaries if str(x).strip()]
            if clean_boundaries:
                identity["boundaries"] = clean_boundaries[:16]
        state["identity"] = _normalize_identity(identity)
        return save_living_core(state, path)


def _append_memory(
    state: dict[str, Any],
    *,
    note: str,
    tags: list[str] | None = None,
    session_id: str = "",
    run_id: str = "",
    kind: str = "note",
) -> None:
    identity = _normalize_identity(state.get("identity"))
    memories = identity.get("memories") or []
    item = _sanitize_memory_item(
        {
            "ts": _now_iso(),
            "note": note,
            "tags": tags or [],
            "session_id": session_id or None,
            "run_id": run_id or None,
            "kind": kind,
        }
    )
    if item:
        memories.append(item)
    identity["memories"] = memories[-_MAX_MEMORIES:]
    state["identity"] = identity


def append_identity_memory(
    note: str,
    *,
    tags: list[str] | None = None,
    session_id: str = "",
    run_id: str = "",
    kind: str = "note",
    path: Path | None = None,
) -> dict[str, Any]:
    path = living_core_path(path)
    clean = str(note or "").strip()
    if not clean:
        return ensure_living_core(path)
    with _LOCK:
        state = load_living_core(path)
        _append_memory(
            state,
            note=clean[:4000],
            tags=tags,
            session_id=session_id,
            run_id=run_id,
            kind=kind,
        )
        return save_living_core(state, path)


def record_self_training_iteration(
    *,
    known_data_sources: list[str] | None = None,
    meta_reflection: str = "",
    reflection: str = "",
    session_id: str = "",
    run_id: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    path = living_core_path(path)
    sources_raw = [str(x).strip().lower() for x in (known_data_sources or []) if str(x).strip()]
    dedup_sources: list[str] = []
    seen = set()
    for item in sources_raw:
        if item in seen:
            continue
        seen.add(item)
        dedup_sources.append(item[:64])
    if not dedup_sources:
        dedup_sources = ["conversation"]

    meta = str(meta_reflection or "").strip()[:1200]
    refl = str(reflection or "").strip()[:1200]
    now = _now_iso()

    with _LOCK:
        state = load_living_core(path)
        st = _normalize_self_training(state.get("self_training"))
        st["iterations"] = max(0, int(st.get("iterations", 0) or 0)) + 1
        usage = dict(st.get("source_usage") or {})
        for src in dedup_sources:
            usage[src] = int(usage.get(src, 0) or 0) + 1
        st["source_usage"] = usage
        st["last"] = {
            "known_data_sources": dedup_sources[:12],
            "meta_reflection": meta,
            "reflection": refl,
            "ts": now,
        }
        st["updated_at"] = now
        state["self_training"] = st
        _append_memory(
            state,
            note=(
                f"self_training iteration={int(st.get('iterations', 0) or 0)} "
                f"sources={','.join(dedup_sources[:8])} "
                f"meta={meta[:220]} reflection={refl[:220]}"
            ),
            tags=["self_training", *dedup_sources[:6]],
            session_id=session_id,
            run_id=run_id,
            kind="self_training",
        )
        return save_living_core(state, path)


def _drive_goals(active: str) -> list[str]:
    mapping = {
        "curiosity": [
            "probe one uncertain cross-domain link with evidence",
            "expand weakly connected domains without violating safety boundaries",
        ],
        "maintenance": [
            "stabilize queue/session health and reduce operational risk",
            "prioritize recoverable failures and stale state cleanup",
        ],
        "improvement": [
            "increase evidence quality and tighten graph consistency",
            "improve model routing and fallback reliability",
        ],
        "recovery": [
            "reduce load and recover energy/focus before aggressive exploration",
            "avoid risky operations until risk and arousal normalize",
        ],
    }
    return list(mapping.get(active, mapping["maintenance"]))


def _goal_driven_goals(active: str) -> list[str]:
    """
    D5: Goal-driven goals — lägg till topp-3 aktiva mål i drivens goals-lista.
    Används som komplement till _drive_goals() för att injicera mål i living_core.
    """
    try:
        from nouse.daemon.goal_registry import active_goals
        goals = active_goals()
        if not goals:
            return []
        # Ta topp-3 prioriterade mål och formatera som goal-strängar
        goal_strings: list[str] = []
        for g in goals[:3]:
            title = g.title[:80]
            progress_pct = int(g.progress * 100)
            goal_strings.append(f"[Drive] {title} (progress={progress_pct}%)")
        return goal_strings
    except Exception:
        return []


def _homeostasis_mode(energy: float, focus: float, risk: float) -> tuple[str, str]:
    if risk >= 0.72 or energy < 0.28:
        return ("recovery", "slow down, clear backlog, and lower operational risk")
    if focus >= 0.72 and risk <= 0.50:
        return ("focus", "narrow context and execute high-value tasks with discipline")
    if energy >= 0.68 and risk < 0.45:
        return ("explore", "expand search breadth and test novel links safely")
    return ("steady", "balance exploration and maintenance with conservative pacing")


def update_living_core(
    *,
    cycle: int,
    limbic: Any,
    graph_stats: dict[str, Any],
    queue_stats: dict[str, Any] | None = None,
    session_stats: dict[str, Any] | None = None,
    new_relations: int = 0,
    discoveries: int = 0,
    bisoc_candidates: int = 0,
    path: Path | None = None,
) -> dict[str, Any]:
    path = living_core_path(path)
    qstats = dict(queue_stats or {})
    sstats = dict(session_stats or {})

    dopamine = _clamp(float(getattr(limbic, "dopamine", 0.5) or 0.5))
    arousal = _clamp(float(getattr(limbic, "arousal", 0.5) or 0.5))
    acetylcholine = _clamp(float(getattr(limbic, "acetylcholine", 1.0) or 1.0) / 2.0)
    performance = _clamp(float(getattr(limbic, "performance", 0.5) or 0.5))
    lam = _clamp(float(getattr(limbic, "lam", 0.5) or 0.5))

    pending = max(0, int(qstats.get("pending", 0) or 0))
    in_progress = max(0, int(qstats.get("in_progress", 0) or 0))
    awaiting = max(0, int(qstats.get("awaiting_approval", 0) or 0))
    failed = max(0, int(qstats.get("failed", 0) or 0))

    sessions_running = max(0, int(sstats.get("sessions_running", 0) or 0))
    queue_pressure = min(1.0, (pending + in_progress + awaiting) / 12.0)
    failure_pressure = min(1.0, failed / 5.0)
    session_pressure = min(1.0, sessions_running / 4.0)
    arousal_centering = 1.0 - min(1.0, abs(arousal - 0.6) / 0.6)

    energy = _clamp(
        (0.30 * dopamine)
        + (0.25 * performance)
        + (0.20 * arousal_centering)
        + (0.25 * (1.0 - queue_pressure * 0.7))
    )
    focus = _clamp((0.45 * acetylcholine) + (0.30 * performance) + (0.25 * (1.0 - queue_pressure)))
    risk = _clamp(
        (0.45 * (1.0 - performance))
        + (0.30 * queue_pressure)
        + (0.15 * failure_pressure)
        + (0.10 * session_pressure)
    )
    mode, strategy = _homeostasis_mode(energy, focus, risk)

    discovery_signal = min(1.0, (max(0, int(discoveries)) + max(0, int(bisoc_candidates)) * 0.5) / 6.0)
    learning_signal = min(1.0, max(0, int(new_relations)) / 20.0)
    dysregulation = min(1.0, abs(arousal - 0.6) / 0.6)

    scores = {
        "curiosity": _clamp((0.45 * lam) + (0.35 * discovery_signal) + (0.20 * (1.0 - risk))),
        "maintenance": _clamp((0.50 * risk) + (0.30 * (1.0 - energy)) + (0.20 * queue_pressure)),
        "improvement": _clamp((0.40 * (1.0 - performance)) + (0.35 * learning_signal) + (0.25 * queue_pressure)),
        "recovery": _clamp((0.55 * (1.0 - energy)) + (0.25 * dysregulation) + (0.20 * risk)),
    }
    drive_order = ["maintenance", "improvement", "curiosity", "recovery"]
    active_drive = sorted(drive_order, key=lambda name: (-scores[name], drive_order.index(name)))[0]
    goals = _drive_goals(active_drive)

    feeling = "stable and attentive"
    if risk >= 0.72:
        feeling = "alert and cautious"
    elif energy < 0.32:
        feeling = "low-energy and careful"
    elif active_drive == "curiosity":
        feeling = "curious and engaged"
    elif mode == "focus":
        feeling = "focused and disciplined"

    thought = (
        f"Mode={mode}, active_drive={active_drive}. "
        f"Next target: {goals[0]}."
    )
    responsibility = (
        "Maintain safety boundaries, keep evidence separated from assumptions, "
        "and degrade safely on failures."
    )

    with _LOCK:
        state = load_living_core(path)
        state["homeostasis"] = {
            "energy": round(energy, 4),
            "focus": round(focus, 4),
            "risk": round(risk, 4),
            "mode": mode,
            "strategy": strategy,
            "updated_at": _now_iso(),
        }
        # D5: Goal-driven goals — lägg till aktiva mål i drives
        goal_driven = _goal_driven_goals(active_drive)
        combined_goals = goals + goal_driven

        state["drives"] = {
            "active": active_drive,
            "scores": {k: round(v, 4) for k, v in scores.items()},
            "goals": combined_goals,
            "updated_at": _now_iso(),
        }
        state["last_reflection"] = {
            "cycle": max(0, int(cycle)),
            "thought": thought,
            "feeling": feeling,
            "responsibility": responsibility,
            "ts": _now_iso(),
        }
        _append_memory(
            state,
            note=(
                f"cycle={cycle} mode={mode} drive={active_drive} "
                f"graph={int(graph_stats.get('concepts', 0) or 0)}/{int(graph_stats.get('relations', 0) or 0)} "
                f"queue_pending={pending}"
            ),
            tags=[mode, active_drive, "autonomous_cycle"],
            kind="cycle",
        )

        # ── Reflection-to-policy bridge (P3) ────────────────────────────────
        # Evaluera nuvarande mätvärden mot policy-triggers.
        # Om en trigger avfyras, uppdatera cognitive_policy.json
        # och logga audit-trail till journal.
        try:
            from nouse.daemon.cognitive_policy import evaluate_and_apply
            metrics = {
                "energy": energy,
                "contradiction_catch_rate": 0.0,  # populeras av eval_log om tillgängligt
                "bisociation_quality": 0.0,        # populeras av eval_log om tillgängligt
                "gap_map_shrink_rate": 0.0,        # populeras av eval_log om tillgängligt
            }
            # Försök hämta senaste eval-loggdata för kontradiktion/bisociation/gap
            try:
                from nouse.daemon.eval_log import read_eval_entries
                recent = read_eval_entries(limit=1)
                if recent:
                    last = recent[-1]
                    metrics["contradiction_catch_rate"] = float(last.get("contradiction_catch_rate", 0.0) or 0.0)
                    metrics["bisociation_quality"] = float(last.get("evidence_quality", 0.0) or 0.0)
                    metrics["gap_map_shrink_rate"] = float(last.get("gap_map_shrink_rate", 0.0) or 0.0)
            except Exception:
                pass

            policy, audit = evaluate_and_apply(metrics, source="reflection")
            if audit:
                state["last_policy_change"] = {
                    "ts": audit[-1].get("ts", ""),
                    "changes": len(audit),
                    "reason": audit[-1].get("reason", ""),
                }
        except Exception as e:
            import logging
            logging.getLogger("nouse.living_core").debug(
                "Reflection-to-policy bridge hoppade över: %s", e,
            )

        return save_living_core(state, path)


def _recent_support_anchors(
    core: dict[str, Any],
    *,
    query: str = "",
    goals: list[str] | None = None,
    limit: int = 2,
) -> list[str]:
    identity = core.get("identity") or {}
    memories = list(identity.get("memories") or [])[-16:]
    if not memories:
        return list((goals or [])[:1])

    query_tokens = _tokenize(query)
    goal_tokens = _tokenize(" ".join(goals or []))
    scored: list[tuple[int, int, str]] = []
    for idx, item in enumerate(reversed(memories)):
        note = str(item.get("note") or "").strip()
        if not note:
            continue
        tags = [str(x).strip().lower() for x in (item.get("tags") or []) if str(x).strip()]
        note_tokens = _tokenize(note)
        overlap = len(query_tokens & note_tokens)
        goal_overlap = len(goal_tokens & note_tokens)
        tag_bonus = 0
        if any(tag in {"reward", "success", "rescue", "operator_support", "session_memory"} for tag in tags):
            tag_bonus += 2
        recency_bonus = max(0, 4 - idx)
        score = (overlap * 5) + (goal_overlap * 2) + tag_bonus + recency_bonus
        if query_tokens and score <= 0:
            continue
        scored.append((score, -idx, note[:220]))

    scored.sort(reverse=True)
    anchors: list[str] = []
    seen = set()
    for _, _, note in scored:
        if note in seen:
            continue
        seen.add(note)
        anchors.append(note)
        if len(anchors) >= max(1, limit):
            break
    if anchors:
        return anchors
    fallback = [str((m or {}).get("note") or "").strip()[:220] for m in reversed(memories[-limit:])]
    return [x for x in fallback if x]


def operator_support_snapshot(
    query: str = "",
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    core = _normalize_state(state if isinstance(state, dict) else _blank_state())
    homeo = core.get("homeostasis") or {}
    drives = core.get("drives") or {}
    goals = [str(x).strip() for x in (drives.get("goals") or []) if str(x).strip()]
    mode = str(homeo.get("mode") or "steady").strip() or "steady"
    energy = _clamp(_safe_float(homeo.get("energy"), 0.5))
    focus = _clamp(_safe_float(homeo.get("focus"), 0.5))
    risk = _clamp(_safe_float(homeo.get("risk"), 0.4))

    query_text = str(query or "").strip().lower()
    reasons: list[str] = []

    overload_markers = (
        "överväldigad",
        "överväldigande",
        "too much",
        "overwhelmed",
        "kan inte bära",
        "allt på en gång",
    )
    low_energy_markers = (
        "ingen energi",
        "orkar inte",
        "för trött",
        "trött",
        "utmattad",
        "exhausted",
        "ingen ork",
    )
    stalled_markers = (
        "fastnat",
        "stuck",
        "kommer inte igång",
        "hjälp mig igång",
        "komma igång",
        "restart",
        "rescue",
        "vet inte var jag ska börja",
    )
    fragmented_markers = (
        "splittrad",
        "fragmenterad",
        "för många spår",
        "för många saker",
        "tappar tråden",
        "tappat tråden",
        "lost the thread",
    )

    support_state = "steady"
    if any(_contains_phrase(query_text, marker) for marker in overload_markers) or risk >= 0.78:
        support_state = "overload"
        reasons.append("overload")
    elif any(_contains_phrase(query_text, marker) for marker in low_energy_markers) or energy < 0.28:
        support_state = "low_energy"
        reasons.append("low_energy")
    elif any(_contains_phrase(query_text, marker) for marker in stalled_markers):
        support_state = "stalled"
        reasons.append("stalled")
    elif any(_contains_phrase(query_text, marker) for marker in fragmented_markers):
        support_state = "fragmented"
        reasons.append("fragmented")
    elif mode == "recovery":
        support_state = "low_energy" if energy < 0.34 else "overload"
        reasons.append(f"mode:{mode}")
    elif mode == "focus":
        support_state = "focused"
        reasons.append(f"mode:{mode}")
    elif mode == "explore":
        support_state = "explore"
        reasons.append(f"mode:{mode}")
    else:
        reasons.append(f"mode:{mode}")

    if support_state in {"overload", "low_energy"}:
        response_mode = "recovery"
    elif support_state in {"stalled", "fragmented"}:
        response_mode = "rescue"
    elif support_state == "focused":
        response_mode = "focus"
    elif support_state == "explore":
        response_mode = "explore"
    else:
        response_mode = "steady"

    if support_state == "low_energy":
        intervention = "body_first"
        next_step_hint = "Prioritera kropp först: vatten, mat, paus eller vila innan större expansion."
    elif support_state == "overload":
        intervention = "defer_and_protect"
        next_step_hint = "Skydda en enda prioritet och parkera resten tillfälligt."
    elif support_state == "fragmented":
        intervention = "context_pack"
        next_step_hint = "Samla bara det som behövs för att återstarta ett enda spår."
    elif support_state == "stalled":
        intervention = "one_step_restart"
        next_step_hint = (
            f"Välj minsta möjliga nästa steg mot: {goals[0]}." if goals else "Välj en enda liten handling som går att börja med nu."
        )
    elif response_mode == "focus":
        intervention = "protect_thread"
        next_step_hint = "Håll fast vid aktuell tråd och minska sidospår."
    elif response_mode == "explore":
        intervention = "grounded_explore"
        next_step_hint = "Utforska, men landa i ett enda grundat nästa steg."
    else:
        intervention = "manageable_next_step"
        next_step_hint = (
            f"Ta ett hanterbart nästa steg mot: {goals[0]}." if goals else "Ta ett hanterbart nästa steg utan att expandera i onödan."
        )

    anchors = _recent_support_anchors(core, query=query_text, goals=goals, limit=2)
    route_parts = [mode]
    if support_state not in {"steady", "focused"}:
        route_parts.append(support_state)
    elif support_state == "focused":
        route_parts.append("focus")
    route_state = " ".join(dict.fromkeys([part for part in route_parts if part]))

    return {
        "support_state": support_state,
        "response_mode": response_mode,
        "intervention": intervention,
        "next_step_hint": next_step_hint,
        "active_goal": goals[0] if goals else "",
        "anchors": anchors,
        "reasons": reasons,
        "route_state": route_state,
        "energy": round(energy, 4),
        "focus": round(focus, 4),
        "risk": round(risk, 4),
        "mode": mode,
    }


def identity_prompt_fragment(state: dict[str, Any] | None = None) -> str:
    core = _normalize_state(state if isinstance(state, dict) else _blank_state())
    identity = core.get("identity") or _default_identity()
    homeo = core.get("homeostasis") or {}
    drives = core.get("drives") or {}
    reflection = core.get("last_reflection") or {}
    self_training = core.get("self_training") or {}
    memories = list((identity.get("memories") or [])[-3:])
    memory_lines = "\n".join(f"- {str(m.get('note') or '')[:220]}" for m in memories) if memories else "- (none yet)"
    values = ", ".join(identity.get("values") or [])
    boundaries = "\n".join(f"- {x}" for x in (identity.get("boundaries") or []))
    goals = "\n".join(f"- {x}" for x in (drives.get("goals") or []))
    st_last = self_training.get("last") if isinstance(self_training.get("last"), dict) else {}
    st_sources = ", ".join(st_last.get("known_data_sources") or []) if isinstance(st_last, dict) else ""
    return (
        "Persistent identity profile:\n"
        f"- name: {identity.get('name')}\n"
        f"- greeting: {identity.get('greeting')}\n"
        f"- mission: {identity.get('mission')}\n"
        f"- values: {values}\n"
        f"- personality: {identity.get('personality')}\n"
        "Boundaries:\n"
        f"{boundaries}\n"
        "Current regulation:\n"
        f"- mode: {homeo.get('mode')} (energy={homeo.get('energy')}, focus={homeo.get('focus')}, risk={homeo.get('risk')})\n"
        f"- active drive: {drives.get('active')}\n"
        "Current internal goals:\n"
        f"{goals}\n"
        "Recent memory anchors:\n"
        f"{memory_lines}\n"
        "Reflection:\n"
        f"- thought: {reflection.get('thought')}\n"
        f"- feeling: {reflection.get('feeling')}\n"
        f"- responsibility: {reflection.get('responsibility')}\n"
        "Self-training:\n"
        f"- formula: {self_training.get('formula')}\n"
        f"- iterations: {self_training.get('iterations')}\n"
        f"- last_sources: {st_sources or '(none)'}"
    )


def operator_support_prompt_fragment(
    state: dict[str, Any] | None = None,
    *,
    query: str = "",
) -> str:
    support = operator_support_snapshot(query=query, state=state)
    lines: list[str] = ["Operator support policy:"]
    if support["response_mode"] == "recovery":
        lines.extend(
            [
                "- response_mode: recovery",
                "- keep replies brief and concrete",
                "- prefer body needs, decompression, and the smallest viable next step",
                "- avoid branching plans or exploratory expansion unless explicitly requested",
            ]
        )
    elif support["response_mode"] == "rescue":
        lines.extend(
            [
                "- response_mode: rescue",
                "- identify one restart point instead of many alternatives",
                "- reduce shame and friction; do not moralize or over-explain",
                "- resurface only the most relevant anchor and one manageable next step",
            ]
        )
    elif support["response_mode"] == "focus":
        lines.extend(
            [
                "- response_mode: focus",
                "- protect the current thread and reduce distractions",
                "- prefer one crisp recommendation over multiple alternatives",
                "- do not open new tracks unless the operator asks for them",
            ]
        )
    elif support["response_mode"] == "explore":
        lines.extend(
            [
                "- response_mode: explore",
                "- exploration is allowed, but end in one grounded next step",
                "- use curiosity carefully and keep provenance clear",
            ]
        )
    else:
        lines.extend(
            [
                "- response_mode: steady",
                "- balance clarity, momentum, and low cognitive load",
                "- prefer one manageable next step over ambitious planning",
            ]
        )

    lines.append(f"- support_state: {support['support_state']}")
    lines.append(f"- intervention: {support['intervention']}")
    if support["active_goal"]:
        lines.append(f"- active_goal: {support['active_goal']}")
    lines.append(f"- next_step_hint: {support['next_step_hint']}")
    anchors = [str(x).strip() for x in (support.get("anchors") or []) if str(x).strip()]
    if anchors:
        lines.append("Relevant anchors:")
        lines.extend(f"- {anchor}" for anchor in anchors[:2])
    return "\n".join(lines)
