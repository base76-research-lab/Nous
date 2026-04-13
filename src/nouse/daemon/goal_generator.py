"""
daemon.goal_generator — Goal Generation from Graph Topology
============================================================
Genererar mål automatiskt från grafens topologiska signaler.

Fyra källor:
  1. gap_map → evidence_gap-mål  (noder med låg evidens men hög grad)
  2. contradiction_events → contradiction_resolve-mål
  3. crystallization_rate → crystallization-mål  (om rate sjunker)
  4. dangling edges → domain_expand-mål

Prioritetsberäkning väger:
  - topological_urgency (grad * (1 - evidence))
  - eval_trend_signal (sjunkande trend → högre prioritet)
  - drive_alignment (match med living_core active drive)
  - operator_feedback (negativ feedback → högre prioritet)

Deduplicering: om mål för samma concepts+kind redan finns → uppdatera prioritet.
"""
from __future__ import annotations

import logging
from typing import Any

from nouse.daemon.goal_registry import (
    Goal,
    KIND_CONTRADICTION_RESOLVE,
    KIND_CRYSTALLIZATION,
    KIND_DOMAIN_EXPAND,
    KIND_EVIDENCE_GAP,
    active_goals,
    goals_by_kind,
    create_goal,
    goal_by_concepts,
    load_goals,
    save_goal,
)

_log = logging.getLogger("nouse.goal_generator")


# ── Prioritetsberäkning ─────────────────────────────────────────────────────────

def compute_priority(
    *,
    topological_urgency: float = 0.0,
    eval_trend_signal: float = 0.0,
    drive_alignment: float = 0.0,
    operator_feedback: float = 0.0,
) -> float:
    """
    Beräkna målprioritet (0.0–1.0) som vägt summa av signaler.

    Vikter:
      0.35 * topological_urgency  — grad * (1 - evidence) för mål-koncept
      0.25 * eval_trend_signal     — sjunkande trend → högre prioritet
      0.20 * drive_alignment       — match med living_core active drive
      0.20 * operator_feedback     — negativ feedback → högre prioritet
    """
    raw = (
        0.35 * topological_urgency
      + 0.25 * eval_trend_signal
      + 0.20 * drive_alignment
      + 0.20 * operator_feedback
    )
    return max(0.0, min(1.0, raw))


def _topological_urgency(field: Any, concepts: list[str]) -> float:
    """
    Beräkna topologisk prioritet för en uppsättning koncept.
    Högre grad (fler relationer) + lägre evidens = högre prioritet.
    """
    if not concepts:
        return 0.0

    scores: list[float] = []
    nodes_attr = getattr(field, "nodes", None)

    for concept in concepts:
        urgency = 0.3  # baseline

        # Försök hämta från Brain-kernel
        if nodes_attr is not None and isinstance(nodes_attr, dict):
            node = nodes_attr.get(concept)
            if node is not None:
                ev = float(getattr(node, "evidence_score", 0) or 0)
                uncertainty = float(getattr(node, "uncertainty", 0) or 0)
                # Låg evidens + hög osäkerhet = hög prioritet
                urgency = (1.0 - ev) * 0.6 + uncertainty * 0.4
        else:
            # Försök FieldSurface-format
            try:
                knowledge = field.concept_knowledge(concept)
                if isinstance(knowledge, dict):
                    ev = float(knowledge.get("evidence_score", 0) or 0)
                    urgency = (1.0 - ev) * 0.7 + 0.3
            except Exception:
                pass

        # Grad: antal utgående relationer
        try:
            rels = field.out_relations(concept, limit=20)
            degree = len(rels) if isinstance(rels, list) else 0
            # Grad-faktor: fler relationer → viktigare koncept
            degree_bonus = min(0.3, degree * 0.05)
            urgency += degree_bonus
        except Exception:
            pass

        scores.append(max(0.0, min(1.0, urgency)))

    return sum(scores) / len(scores) if scores else 0.0


def _eval_trend_signal(eval_entries: list[dict[str, Any]] | None = None) -> float:
    """
    Beräkna trend-signal från eval_log.
    Sjunkande crystallization/evidence → högre prioritet för mål.
    """
    if not eval_entries or len(eval_entries) < 2:
        return 0.1  # baseline

    from nouse.daemon.eval_log import compute_trend

    cryst_trend = compute_trend(eval_entries, "crystallization_rate")
    ev_trend = compute_trend(eval_entries, "evidence_quality")

    signal = 0.1  # baseline
    if cryst_trend == "falling":
        signal += 0.3
    elif cryst_trend == "stable":
        signal += 0.1

    if ev_trend == "falling":
        signal += 0.3
    elif ev_trend == "stable":
        signal += 0.1

    return max(0.0, min(1.0, signal))


def _drive_alignment(kind: str, active_drive: str = "") -> float:
    """
    Beräkna alignment mellan goal-kind och living_core active drive.
    """
    alignment_map = {
        KIND_EVIDENCE_GAP: {"curiosity": 0.8, "improvement": 0.6, "maintenance": 0.3, "recovery": 0.1},
        KIND_CONTRADICTION_RESOLVE: {"improvement": 0.8, "curiosity": 0.5, "maintenance": 0.4, "recovery": 0.2},
        KIND_CRYSTALLIZATION: {"maintenance": 0.7, "improvement": 0.7, "curiosity": 0.3, "recovery": 0.2},
        KIND_DOMAIN_EXPAND: {"curiosity": 0.9, "improvement": 0.4, "maintenance": 0.2, "recovery": 0.1},
    }
    kind_map = alignment_map.get(kind, {})
    return kind_map.get(active_drive, 0.3)


def _operator_feedback_signal() -> float:
    """
    Beräkna signal från operator-feedback.
    Negativ feedback → högre prioritet för improvement-mål.
    """
    try:
        from nouse.daemon.eval_log import feedback_summary
        summary = feedback_summary(limit=20)
        ratio = float(summary.get("ratio", 0.5) or 0.5)
        # Låg ratio (mycket "bad") → hög signal
        return max(0.0, min(1.0, 1.0 - ratio))
    except Exception:
        return 0.1  # baseline


# ── Målkällor ────────────────────────────────────────────────────────────────────

def generate_from_gap_map(
    field: Any,
    cycle: int,
    *,
    max_goals: int = 5,
) -> list[Goal]:
    """
    Källa 1: gap_map → evidence_gap-mål.

    Identifierar noder med låg evidens men hög grad
    (viktiga koncept vi vet lite om).
    """
    existing = active_goals()
    new_goals: list[Goal] = []

    try:
        gap = field.gap_map() if hasattr(field, "gap_map") else {}
    except Exception as e:
        _log.debug("generate_from_gap_map: gap_map misslyckades: %s", e)
        return []

    weak_nodes = gap.get("weak_nodes", [])
    if not weak_nodes:
        _log.debug("generate_from_gap_map: inga svaga noder hittades")
        return []

    for node in weak_nodes[:max_goals * 2]:
        node_id = str(node.get("node_id", "") or "")
        if not node_id:
            continue
        uncertainty = float(node.get("uncertainty", 0) or 0)
        evidence = float(node.get("evidence_score", 0) or 0)

        # Hoppa över noder med hyfsad evidens
        if evidence >= 0.45:
            continue

        # Hoppa om vi redan har mål för detta koncept
        existing_goal = goal_by_concepts([node_id], kind=KIND_EVIDENCE_GAP)
        if existing_goal is not None:
            # Uppdatera prioritet på existerande mål
            urgency = (1.0 - evidence) * 0.6 + uncertainty * 0.4
            new_priority = compute_priority(
                topological_urgency=urgency,
                eval_trend_signal=0.1,
                drive_alignment=_drive_alignment(KIND_EVIDENCE_GAP),
            )
            if new_priority > existing_goal.priority:
                existing_goal.priority = new_priority
                existing_goal.updated_cycle = cycle
                # Skriv uppdaterat mål (rewrite hanterar dubbletter via id)
            continue

        # Hämta domän
        domain = ""
        try:
            domain = str(field.concept_domain(node_id) or "")
        except Exception:
            pass

        # Beräkna prioritet
        urgency = (1.0 - evidence) * 0.6 + uncertainty * 0.4
        priority = compute_priority(
            topological_urgency=urgency,
            eval_trend_signal=0.1,
            drive_alignment=_drive_alignment(KIND_EVIDENCE_GAP),
        )

        if priority < 0.2:
            continue  # för låg prioritet

        goal = create_goal(
            title=f"Öka evidens för {node_id}" + (f" i {domain}" if domain else ""),
            kind=KIND_EVIDENCE_GAP,
            priority=priority,
            target_concepts=[node_id],
            target_domain=domain,
            source="gap_map",
            created_cycle=cycle,
            satisfaction_criteria={"evidence_floor": 0.55},
        )
        new_goals.append(goal)

        if len(new_goals) >= max_goals:
            break

    _log.info("generate_from_gap_map: %d nya mål", len(new_goals))
    return new_goals


def generate_from_contradictions(
    field: Any,
    cycle: int,
    *,
    max_goals: int = 3,
) -> list[Goal]:
    """
    Källa 2: contradiction_events → contradiction_resolve-mål.

    Skapar mål för att lösa identifierade kontradiktioner i grafen.
    """
    existing = goals_by_kind(KIND_CONTRADICTION_RESOLVE)
    new_goals: list[Goal] = []

    try:
        from nouse.daemon.journal import count_contradiction_events
        count = count_contradiction_events(since_cycle=cycle - 10)
    except Exception:
        count = 0

    if count == 0:
        return []

    # Om vi redan har tillräckligt med kontradiktions-mål, hoppa
    if len(existing) >= max_goals:
        return []

    # Hitta koncept med motsägelse-relationer
    contradiction_concepts: set[str] = set()
    try:
        edges = getattr(field, "edges", {})
        if isinstance(edges, dict):
            for edge in edges.values():
                rel_type = str(getattr(edge, "rel_type", "") or "").lower()
                # Identifiera kontradiktiva relationstyper
                if any(w in rel_type for w in ["motstrid", "contradict", "förhindrar", "inhiberar", "blocks"]):
                    src = str(getattr(edge, "src", "") or "")
                    tgt = str(getattr(edge, "tgt", "") or "")
                    if src:
                        contradiction_concepts.add(src)
                    if tgt:
                        contradiction_concepts.add(tgt)
    except Exception:
        pass

    if not contradiction_concepts:
        # Fallback: använd koncept från gap_map med hög uncertainty
        try:
            gap = field.gap_map() if hasattr(field, "gap_map") else {}
            for node in gap.get("weak_nodes", [])[:3]:
                nid = str(node.get("node_id", "") or "")
                if nid and float(node.get("uncertainty", 0) or 0) > 0.7:
                    contradiction_concepts.add(nid)
        except Exception:
            pass

    for concept in list(contradiction_concepts)[:max_goals]:
        # Hoppa om vi redan har mål för detta
        if goal_by_concepts([concept], kind=KIND_CONTRADICTION_RESOLVE):
            continue

        priority = compute_priority(
            topological_urgency=0.7,
            eval_trend_signal=0.3,
            drive_alignment=_drive_alignment(KIND_CONTRADICTION_RESOLVE),
        )

        goal = create_goal(
            title=f"Lös kontradiktion kring {concept}",
            kind=KIND_CONTRADICTION_RESOLVE,
            priority=priority,
            target_concepts=[concept],
            source="contradiction",
            created_cycle=cycle,
            satisfaction_criteria={"contradiction_count": 0},
        )
        new_goals.append(goal)

    _log.info("generate_from_contradictions: %d nya mål", len(new_goals))
    return new_goals


def generate_from_crystallization(
    field: Any,
    cycle: int,
    *,
    eval_entries: list[dict[str, Any]] | None = None,
    max_goals: int = 2,
) -> list[Goal]:
    """
    Källa 3: crystallization_rate → crystallization-mål.

    Om crystallization_rate är låg eller sjunkande,
    skapa mål för att driva kristallisering i specifika domäner.
    """
    existing = goals_by_kind(KIND_CRYSTALLIZATION)
    new_goals: list[Goal] = []

    # Hämta crystallization_rate från eval_entries
    current_rate = 0.0
    trend = "stable"
    if eval_entries:
        from nouse.daemon.eval_log import compute_trend
        trend = compute_trend(eval_entries, "crystallization_rate")
        last = eval_entries[-1] if eval_entries else {}
        current_rate = float(last.get("crystallization_rate", 0) or 0)

    # Skapa bara mål om rate är låg ELLER sjunkande
    if current_rate >= 0.20 and trend != "falling":
        return []  # Tillräckligt hög och inte sjunkande

    # Identifiera domäner med lägst crystallization
    try:
        domains = field.domains() if hasattr(field, "domains") else []
    except Exception:
        domains = []

    if not domains:
        return []

    # Välj domäner med flest relationer men lägst genomsnittlig w
    domain_scores: list[tuple[str, float]] = []
    for domain in domains:
        try:
            concepts = field.concepts(domain=domain)
            if not concepts or len(concepts) < 3:
                continue
            # Beräkna genomsnittlig w för domänens kanter
            total_w = 0.0
            count = 0
            for c in concepts[:20]:
                name = c.get("name", "") if isinstance(c, dict) else str(c)
                if not name:
                    continue
                try:
                    rels = field.out_relations(name, limit=10)
                    for r in rels:
                        w = float(r.get("w", 0) or 0)
                        total_w += w
                        count += 1
                except Exception:
                    pass
            avg_w = total_w / max(1, count)
            # Låg avg_w = mer behov av kristallisering
            domain_scores.append((domain, avg_w))
        except Exception:
            continue

    # Sortera: lägst avg_w först
    domain_scores.sort(key=lambda x: x[1])

    for domain, avg_w in domain_scores[:max_goals]:
        # Hoppa om vi redan har mål för denna domän
        existing_for_domain = [g for g in existing if g.target_domain == domain]
        if existing_for_domain:
            continue

        priority = compute_priority(
            topological_urgency=max(0.3, 1.0 - avg_w),
            eval_trend_signal=0.5 if trend == "falling" else 0.2,
            drive_alignment=_drive_alignment(KIND_CRYSTALLIZATION),
        )

        target_rate = max(0.15, current_rate + 0.05)

        goal = create_goal(
            title=f"Driv kristallisering i {domain}",
            kind=KIND_CRYSTALLIZATION,
            priority=priority,
            target_concepts=[domain],
            target_domain=domain,
            source="eval_decline" if trend == "falling" else "crystallization",
            created_cycle=cycle,
            satisfaction_criteria={"crystallization_rate": round(target_rate, 2)},
        )
        new_goals.append(goal)

    _log.info("generate_from_crystallization: %d nya mål (rate=%.3f trend=%s)", len(new_goals), current_rate, trend)
    return new_goals


def generate_from_dangling(
    field: Any,
    cycle: int,
    *,
    max_goals: int = 3,
) -> list[Goal]:
    """
    Källa 4: dangling edges → domain_expand-mål.

    Dangling targets (X→Y där Y ej är nod) representerar
    kunskapsfrontieren — systemet vet att X relaterar till Y men inget om Y.
    """
    existing = goals_by_kind(KIND_DOMAIN_EXPAND)
    new_goals: list[Goal] = []

    try:
        # Använd ghost_q's dangling-funktion
        from nouse.daemon.ghost_q import find_dangling_edges
        dangling = find_dangling_edges(field, limit=max_goals * 3)
    except Exception:
        # Fallback: manuell sökning
        dangling = []
        try:
            all_concepts = {str(c.get("name") or "") for c in field.concepts() if c.get("name")}
            dangling_rows = field.find_dangling_targets(limit=50)
            for row in dangling_rows:
                tgt = str(row.get("tgt", "") or "")
                if tgt and tgt not in all_concepts:
                    dangling.append(tgt)
        except Exception:
            pass

    if not dangling:
        return []

    # Prioritera: dangling med flest inkommande relationer = mer viktigt
    dangling_scores: dict[str, int] = {}
    try:
        for tgt in dangling:
            count = 0
            try:
                in_rels = field._in_relations(tgt) if hasattr(field, "_in_relations") else []
                count = len(in_rels) if isinstance(in_rels, list) else 0
            except Exception:
                count = 1  # Minst en referens (den som skapade dangling)
            dangling_scores[tgt] = max(1, count)
    except Exception:
        dangling_scores = {tgt: 1 for tgt in dangling}

    # Sortera: flest referenser först
    sorted_dangling = sorted(dangling_scores.keys(), key=lambda t: -dangling_scores.get(t, 1))

    for target in sorted_dangling[:max_goals]:
        # Hoppa om vi redan har mål för detta koncept
        if goal_by_concepts([target], kind=KIND_DOMAIN_EXPAND):
            continue

        # Försök identifiera domän från refererande koncept
        domain = ""
        try:
            in_rels = field._in_relations(target) if hasattr(field, "_in_relations") else []
            if in_rels and isinstance(in_rels, list):
                src = str(in_rels[0].get("source", "") or "")
                domain = str(field.concept_domain(src) or "")
        except Exception:
            pass

        priority = compute_priority(
            topological_urgency=min(0.9, 0.3 + dangling_scores.get(target, 1) * 0.1),
            drive_alignment=_drive_alignment(KIND_DOMAIN_EXPAND),
        )

        goal = create_goal(
            title=f"Expandera domän kring {target}" + (f" ({domain})" if domain else ""),
            kind=KIND_DOMAIN_EXPAND,
            priority=priority,
            target_concepts=[target],
            target_domain=domain,
            source="dangling_edge",
            created_cycle=cycle,
            satisfaction_criteria={"node_exists": True},
        )
        new_goals.append(goal)

    _log.info("generate_from_dangling: %d nya mål från %d dangling targets", len(new_goals), len(dangling))
    return new_goals


# ── Huvudfunktion ─────────────────────────────────────────────────────────────────

def generate_goals(
    field: Any,
    cycle: int,
    *,
    eval_entries: list[dict[str, Any]] | None = None,
    max_total: int = 10,
) -> list[Goal]:
    """
    Kör alla fyra målkällor och returnera nya mål.

    Deduplicering sker automatiskt — existerande mål uppdateras istället
    för att skapas på nytt.
    """
    new_goals: list[Goal] = []

    # Källa 1: gap_map → evidence_gap
    try:
        goals_1 = generate_from_gap_map(field, cycle, max_goals=max_total // 2)
        new_goals.extend(goals_1)
    except Exception as e:
        _log.warning("generate_from_gap_map misslyckades: %s", e)

    # Källa 2: contradiction_resolve
    try:
        goals_2 = generate_from_contradictions(field, cycle, max_goals=2)
        new_goals.extend(goals_2)
    except Exception as e:
        _log.warning("generate_from_contradictions misslyckades: %s", e)

    # Källa 3: crystallization
    try:
        goals_3 = generate_from_crystallization(field, cycle, eval_entries=eval_entries, max_goals=2)
        new_goals.extend(goals_3)
    except Exception as e:
        _log.warning("generate_from_crystallization misslyckades: %s", e)

    # Källa 4: dangling edges
    try:
        goals_4 = generate_from_dangling(field, cycle, max_goals=2)
        new_goals.extend(goals_4)
    except Exception as e:
        _log.warning("generate_from_dangling misslyckades: %s", e)

    # Sortera efter prioritet och kapta
    new_goals.sort(key=lambda g: g.priority, reverse=True)
    capped = new_goals[:max_total]

    _log.info(
        "generate_goals: %d nya mål (kapade från %d) cycle=%d",
        len(capped), len(new_goals), cycle,
    )
    return capped