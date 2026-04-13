"""
daemon.goal_registry — Persistent Goal Management
====================================================
Goal Registry för Intrinsic Drive Engine.

Mål genereras från graf-topologi (gap_map, contradictions, crystallization,
dangling edges) och persisterar över cykler. Varje mål har mätbara
satisfaction-criteria och progress som uppdateras varje NightRun-cykel.

Analogt med prefrontal cortex goal-setting:
  - Identifierar vad som behövs (intention formation)
  - Prioriterar mellan konkurrerande behov
  - Detekterar när intentionen är uppnådd (satisfaction)
  - Expireerar föråldrade intentioner (pruning)
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nouse.config.paths import path_from_env

_log = logging.getLogger("nouse.goal_registry")

GOAL_REGISTRY_PATH = path_from_env("NOUSE_GOAL_REGISTRY", "goal_registry.jsonl")

# ── Goal-kinds ─────────────────────────────────────────────────────────────────

KIND_EVIDENCE_GAP = "evidence_gap"
KIND_CONTRADICTION_RESOLVE = "contradiction_resolve"
KIND_CRYSTALLIZATION = "crystallization"
KIND_DOMAIN_EXPAND = "domain_expand"
KIND_OPERATOR_MISSION = "operator_mission"

VALID_KINDS = {
    KIND_EVIDENCE_GAP,
    KIND_CONTRADICTION_RESOLVE,
    KIND_CRYSTALLIZATION,
    KIND_DOMAIN_EXPAND,
    KIND_OPERATOR_MISSION,
}

# ── Status ──────────────────────────────────────────────────────────────────────

STATUS_ACTIVE = "active"
STATUS_SATISFIED = "satisfied"
STATUS_EXPIRED = "expired"
STATUS_BLOCKED = "blocked"

VALID_STATUSES = {STATUS_ACTIVE, STATUS_SATISFIED, STATUS_EXPIRED, STATUS_BLOCKED}

# ── Default deadline ─────────────────────────────────────────────────────────────

DEFAULT_GOAL_LIFECYCLE_CYCLES = 50  # max-cykler innan expiry


# ── Dataklass ───────────────────────────────────────────────────────────────────

@dataclass
class Goal:
    """Ett aktivt mål i Intrinsic Drive Engine."""

    id: str = ""                          # uuid
    title: str = ""                       # mänskligt-läsbar beskrivning
    kind: str = KIND_EVIDENCE_GAP         # goal-kind
    status: str = STATUS_ACTIVE           # active|satisfied|expired|blocked
    priority: float = 0.5                 # 0.0–1.0, beräknas från graf-topologi
    target_concepts: list[str] = field(default_factory=list)  # noder som målet gäller
    target_domain: str = ""               # domän
    source: str = "gap_map"               # varifrån målet skapades
    created_cycle: int = 0
    updated_cycle: int = 0
    deadline_cycle: int | None = None     # max-cykel innan expiry
    satisfaction_criteria: dict[str, Any] = field(default_factory=dict)
    progress: float = 0.0                # 0.0–1.0, uppdateras varje cykel
    parent_goal_id: str | None = None     # hierarki: sub-mål

    def __post_init__(self) -> None:
        if not self.id:
            self.id = str(uuid.uuid4())[:12]
        if self.kind not in VALID_KINDS:
            _log.warning("Okänt goal-kind: %s — sätter till evidence_gap", self.kind)
            self.kind = KIND_EVIDENCE_GAP
        if self.status not in VALID_STATUSES:
            self.status = STATUS_ACTIVE
        self.priority = max(0.0, min(1.0, float(self.priority)))
        self.progress = max(0.0, min(1.0, float(self.progress)))


# ── Persistence ──────────────────────────────────────────────────────────────────

def _goal_path(path: Path | str | None = None) -> Path:
    p = Path(path) if path else GOAL_REGISTRY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_goals(path: Path | str | None = None) -> list[Goal]:
    """Läs alla mål från registry-filen."""
    p = _goal_path(path)
    if not p.exists():
        return []
    goals: list[Goal] = []
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                # Filtrera bort okända nycklar
                known = {f.name for f in Goal.__dataclass_fields__.values()}
                filtered = {k: v for k, v in data.items() if k in known}
                goals.append(Goal(**filtered))
        except (json.JSONDecodeError, TypeError) as e:
            _log.debug("Ogiltig goal-rad: %s", e)
            continue
    return goals


def save_goal(goal: Goal, path: Path | None = None) -> Goal:
    """Skriv ett mål till registry-filen (append)."""
    p = _goal_path(path)
    line = json.dumps(asdict(goal), ensure_ascii=False, sort_keys=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    _log.info(
        "Goal %s: kind=%s status=%s priority=%.2f title=%r",
        goal.id, goal.kind, goal.status, goal.priority, goal.title[:60],
    )
    return goal


def rewrite_goals(goals: list[Goal], path: Path | None = None) -> Path:
    """Skriv om hela registry-filen (t.ex. efter status-uppdateringar)."""
    p = _goal_path(path)
    lines = [json.dumps(asdict(g), ensure_ascii=False, sort_keys=True) for g in goals]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log.debug("Rewrite_goals: %d mål skrivna", len(goals))
    return p


# ── Queries ─────────────────────────────────────────────────────────────────────

def active_goals(path: Path | None = None) -> list[Goal]:
    """Returnera alla aktiva mål sorterade efter prioritet (högst först)."""
    goals = load_goals(path)
    active = [g for g in goals if g.status == STATUS_ACTIVE]
    active.sort(key=lambda g: g.priority, reverse=True)
    return active


def goals_by_kind(kind: str, path: Path | None = None) -> list[Goal]:
    """Returnera aktiva mål av en viss kind."""
    return [g for g in active_goals(path) if g.kind == kind]


def goal_by_concepts(
    concepts: list[str],
    kind: str | None = None,
    path: Path | None = None,
) -> Goal | None:
    """Hitta existerande mål som matchar koncept (och ev. kind)."""
    concept_set = set(c.lower() for c in concepts)
    for goal in load_goals(path):
        if goal.status != STATUS_ACTIVE:
            continue
        if kind and goal.kind != kind:
            continue
        goal_concepts = set(c.lower() for c in goal.target_concepts)
        # Match om >50% överlapp
        if concept_set and goal_concepts:
            overlap = len(concept_set & goal_concepts) / max(len(concept_set), len(goal_concepts))
            if overlap > 0.5:
                return goal
    return None


def goal_by_id(goal_id: str, path: Path | None = None) -> Goal | None:
    """Hitta mål med specifikt ID."""
    for goal in load_goals(path):
        if goal.id == goal_id:
            return goal
    return None


# ── Mutationer ──────────────────────────────────────────────────────────────────

def create_goal(
    *,
    title: str,
    kind: str = KIND_EVIDENCE_GAP,
    priority: float = 0.5,
    target_concepts: list[str] | None = None,
    target_domain: str = "",
    source: str = "gap_map",
    created_cycle: int = 0,
    deadline_cycle: int | None = None,
    satisfaction_criteria: dict[str, Any] | None = None,
    parent_goal_id: str | None = None,
    path: Path | None = None,
) -> Goal:
    """Skapa och spara ett nytt mål."""
    if deadline_cycle is None:
        deadline_cycle = created_cycle + DEFAULT_GOAL_LIFECYCLE_CYCLES

    goal = Goal(
        title=title[:200],
        kind=kind,
        status=STATUS_ACTIVE,
        priority=priority,
        target_concepts=target_concepts or [],
        target_domain=target_domain,
        source=source,
        created_cycle=created_cycle,
        updated_cycle=created_cycle,
        deadline_cycle=deadline_cycle,
        satisfaction_criteria=satisfaction_criteria or {},
        progress=0.0,
        parent_goal_id=parent_goal_id,
    )
    save_goal(goal, path)
    return goal


def update_goal_progress(
    goal_id: str,
    cycle: int,
    progress: float,
    status: str | None = None,
    path: Path | None = None,
) -> Goal | None:
    """Uppdatera progress och ev. status på ett mål. Skriv om hela filen."""
    goals = load_goals(path)
    found = False
    for i, g in enumerate(goals):
        if g.id == goal_id:
            goals[i].progress = max(0.0, min(1.0, float(progress)))
            goals[i].updated_cycle = cycle
            if status and status in VALID_STATUSES:
                goals[i].status = status
            found = True
            break
    if not found:
        _log.warning("update_goal_progress: mål %s hittades inte", goal_id)
        return None
    rewrite_goals(goals, path)
    return next(g for g in goals if g.id == goal_id)


def expire_stale_goals(cycle: int, path: Path | None = None) -> int:
    """Markera mål som passerat deadline_cycle som expired. Returnerar antal."""
    goals = load_goals(path)
    expired = 0
    for i, g in enumerate(goals):
        if g.status != STATUS_ACTIVE:
            continue
        if g.deadline_cycle is not None and cycle > g.deadline_cycle:
            goals[i].status = STATUS_EXPIRED
            goals[i].updated_cycle = cycle
            expired += 1
            _log.info("Goal %s expired: deadline_cycle=%d current=%d", g.id, g.deadline_cycle, cycle)
    if expired > 0:
        rewrite_goals(goals, path)
    return expired


def satisfy_goals(goals_to_satisfy: list[str], cycle: int, path: Path | None = None) -> int:
    """Markera specifika mål som satisfied. Returnerar antal."""
    all_goals = load_goals(path)
    satisfied = 0
    for i, g in enumerate(all_goals):
        if g.id in goals_to_satisfy and g.status == STATUS_ACTIVE:
            all_goals[i].status = STATUS_SATISFIED
            all_goals[i].progress = 1.0
            all_goals[i].updated_cycle = cycle
            satisfied += 1
    if satisfied > 0:
        rewrite_goals(all_goals, path)
    return satisfied


# ── Satisfaction-evaluering ──────────────────────────────────────────────────────

def evaluate_satisfaction(
    goal: Goal,
    field: Any,
    cycle: int,
    *,
    eval_entries: list[dict[str, Any]] | None = None,
) -> str:
    """
    Evaluera om ett mål är uppnått baserat på graf-state.

    Returnerar: "satisfied"|"progressing"|"blocked"|"active"

    field: FieldSurface eller Brain-kernel med .nodes och .edges
    eval_entries: senaste eval_log-entries (för crystallization-rate)
    """
    criteria = goal.satisfaction_criteria

    # Deadline-check först
    if goal.deadline_cycle is not None and cycle > goal.deadline_cycle:
        return STATUS_EXPIRED

    if goal.kind == KIND_EVIDENCE_GAP:
        # Kolla om target_concepts har evidence_score >= floor
        floor = float(criteria.get("evidence_floor", 0.55))
        if not goal.target_concepts:
            return "active"
        scores = []
        for concept in goal.target_concepts:
            node = _find_node(field, concept)
            if node is not None:
                ev = float(getattr(node, "evidence_score", 0) or 0)
                scores.append(ev)
            else:
                scores.append(0.0)
        above_floor = sum(1 for s in scores if s >= floor)
        goal.progress = above_floor / len(scores) if scores else 0.0
        return STATUS_SATISFIED if goal.progress >= 1.0 else "progressing"

    if goal.kind == KIND_CONTRADICTION_RESOLVE:
        # Kolla om contradiction_count == 0 för target_concepts
        # Enkel heuristik: om inga contradiction events nämner dessa noder
        from nouse.daemon.journal import count_contradiction_events
        try:
            recent_count = count_contradiction_events(since_cycle=cycle - 5)
            # Om vi har target_concepts, kolla specifikt
            if goal.target_concepts:
                # Broad check: om få kontradiktioner totalt, anta löst
                goal.progress = max(0.0, 1.0 - recent_count / max(1, len(goal.target_concepts) * 2))
            else:
                goal.progress = 1.0 if recent_count == 0 else max(0.0, 1.0 - recent_count / 10)
            return STATUS_SATISFIED if goal.progress >= 1.0 else "progressing"
        except Exception:
            return "active"

    if goal.kind == KIND_CRYSTALLIZATION:
        # Kolla crystallization_rate från eval_log
        target_rate = float(criteria.get("crystallization_rate", 0.20))
        current_rate = 0.0
        if eval_entries:
            last = eval_entries[-1] if eval_entries else {}
            current_rate = float(last.get("crystallization_rate", 0.0) or 0.0)
        goal.progress = min(1.0, current_rate / target_rate) if target_rate > 0 else 0.0
        return STATUS_SATISFIED if current_rate >= target_rate else "progressing"

    if goal.kind == KIND_DOMAIN_EXPAND:
        # Kolla om target_concepts nu är noder i grafen
        exists_count = 0
        for concept in goal.target_concepts:
            if _find_node(field, concept) is not None:
                exists_count += 1
        goal.progress = exists_count / len(goal.target_concepts) if goal.target_concepts else 0.0
        return STATUS_SATISFIED if goal.progress >= 1.0 else "progressing"

    if goal.kind == KIND_OPERATOR_MISSION:
        # Operator-mission: satisfied när operatören markerar det
        # Annars kolla progress-criteria
        custom_criteria = criteria.get("custom_satisfied")
        if custom_criteria:
            goal.progress = 1.0
            return STATUS_SATISFIED
        return "active"

    return "active"


def _find_node(field: Any, concept: str) -> Any:
    """Hitta en nod i field oavsett format."""
    # Brain-kernel format
    if hasattr(field, "nodes") and isinstance(field.nodes, dict):
        return field.nodes.get(concept)
    # FieldSurface format
    if hasattr(field, "concept_knowledge"):
        try:
            knowledge = field.concept_knowledge(concept)
            if knowledge:
                return knowledge
        except Exception:
            pass
    return None


# ── Metrics ──────────────────────────────────────────────────────────────────────

def goal_metrics(path: Path | None = None) -> dict[str, Any]:
    """Snabb sammanfattning för eval_log och CLI."""
    goals = load_goals(path)
    active = [g for g in goals if g.status == STATUS_ACTIVE]
    satisfied = [g for g in goals if g.status == STATUS_SATISFIED]

    total = len(goals)
    active_count = len(active)
    satisfied_total = len(satisfied)
    satisfaction_rate = round(satisfied_total / max(1, total), 4)
    progress_mean = round(sum(g.progress for g in active) / max(1, len(active)), 4)

    by_kind: dict[str, int] = {}
    for g in active:
        by_kind[g.kind] = by_kind.get(g.kind, 0) + 1

    return {
        "goals_total": total,
        "goals_active": active_count,
        "goals_satisfied_total": satisfied_total,
        "goal_satisfaction_rate": satisfaction_rate,
        "goal_progress_mean": progress_mean,
        "goals_by_kind": by_kind,
    }