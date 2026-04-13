---
title: "Intrinsic Drive Engine"
subtitle: "From Reactive Consolidation to Autonomous Goal-Directed Behavior"
author: "Björn Wikström"
date: "2026-04-13"
abstract: |
  We implement the Intrinsic Drive Engine — a system that converts graph topology into persistent autonomous goals, enabling Nous to exhibit self-directed behavior rather than purely reactive consolidation. Goals are generated from four topological sources (evidence gaps, contradictions, crystallization deficits, dangling edges), prioritized by a weighted formula (topological urgency 0.35, eval trend 0.25, drive alignment 0.20, operator feedback 0.20), and drive execution through Ghost Q topic selection, curiosity loop domain targeting, and Brain node goal_weight propagation. Goal satisfaction is evaluated per-cycle and feeds back into the cognitive policy layer, creating a closed adaptive loop. First live test: two crystallization goals generated automatically from a 20k-concept graph. This note documents the architecture, implementation, and initial longitudinal data for research traceability.
---

# Intrinsic Drive Engine

**From Reactive Consolidation to Autonomous Goal-Directed Behavior**

Björn Wikström\
Base76 Research Lab\
bjorn@base76research.com | ORCID: 0009-0000-4015-2357

*13 April 2026*

---

## 1. Motivation

Prior to this implementation, Nous operated in a **reactive** mode: the NightRun daemon consolidated incoming episodes, but had no internal representation of *what it should be doing*. Consolidation was triggered by the clock, not by goals. The system had drives (curiosity, improvement, maintenance) in its living_core layer, but these were static strings — they influenced the system prompt but had no persistent state, no progress tracking, and no feedback loop.

This is the architectural gap between a system that *processes* information and one that *pursues* it. The distinction matters for longitudinal study: a reactive system's behavior is determined by its input stream. A goal-directed system's behavior is determined by its internal state, which in turn is shaped by the topology of what it already knows and what it doesn't.

## 2. Architecture

### 2.1 Goal Data Model

```
Goal
├── id: str (uuid, first 12 chars)
├── title: str
├── kind: evidence_gap | contradiction_resolve | crystallization | domain_expand | operator_mission
├── status: active → satisfied | expired | blocked
├── priority: float 0.0–1.0
├── target_concepts: list[str]
├── target_domain: str
├── source: gap_map | contradiction | crystallization | dangling | operator
├── created_cycle: int
├── deadline_cycle: int | None (default: created + 50)
├── satisfaction_criteria: dict
├── progress: float 0.0–1.0
└── parent_goal_id: str | None
```

Persistence: JSONL at `~/.local/share/nouse/personal/goal_registry.jsonl`. Append-only writes, periodic rewrite for compaction.

### 2.2 Goal Generation Sources

Four topological sources convert graph state into goals:

| Source | Trigger | Goal Kind | What it targets |
|--------|---------|-----------|-----------------|
| Gap map | Nodes with `evidence_score < evidence_floor` | `evidence_gap` | Under-evidenced concepts |
| Contradictions | Edges flagged as contradictory | `contradiction_resolve` | Contradicted concept pairs |
| Crystallization | Domains where `crystallization_rate < 0.55` | `crystallization` | Weakly connected domains |
| Dangling edges | Nodes with < 2 connections | `domain_expand` | Isolated concepts needing links |

### 2.3 Priority Computation

Each goal's priority is a weighted sum:

```
priority = 0.35 × topological_urgency
         + 0.25 × eval_trend_signal
         + 0.20 × drive_alignment
         + 0.20 × operator_feedback
```

- **Topological urgency** (0.35): How bad is the gap? Based on `1 - evidence_score` for gap goals, contradiction severity for contradiction goals, distance from crystallization threshold for crystallization goals.
- **Eval trend signal** (0.25): Are evalving metrics improving or declining? Declining metrics increase priority for corrective goals.
- **Drive alignment** (0.20): Does this goal align with the active drive? Evidence gaps align with curiosity (0.8), contradictions with improvement (0.8), crystallization with maintenance (0.7), domain expansion with curiosity (0.9).
- **Operator feedback** (0.20): Recent operator thumbs-up increases priority of similar goals; thumbs-down decreases it.

### 2.4 Goal-Directed Execution

Goals influence behavior at three points:

1. **Ghost Q** (70/30 split): 70% of Ghost Q queries target concepts from active `evidence_gap` goals; 30% from regular weak-node selection. This ensures the LLM is directed toward knowledge gaps, not just any weak node.

2. **Curiosity loop**: When no explicit task is given, the initiative module checks for active `contradiction_resolve` and `domain_expand` goals and uses their target domain as the curiosity topic. Goal context is injected into the system prompt.

3. **Brain goal_weight**: `Brain.apply_goal_weights()` sets `node.goal_weight = max(current, goal.priority)` for all concepts targeted by active goals. This biases node selection toward goal-relevant concepts throughout the system.

### 2.5 Goal Satisfaction

Each goal kind has specific satisfaction criteria:

| Kind | Satisfied when |
|------|---------------|
| `evidence_gap` | All target concepts reach `evidence_score ≥ evidence_floor` |
| `contradiction_resolve` | Contradiction count for target concepts drops to 0 |
| `crystallization` | Domain crystallization rate reaches ≥ 0.55 |
| `domain_expand` | Target concept has ≥ 2 relations (no longer dangling) |

Unsatisfied goals expire after 50 cycles (configurable). Expired and satisfied goals remain in the registry for audit.

### 2.6 Cognitive Policy Integration

Two new cognitive policy triggers connect goal metrics to system behavior:

- `goal_satisfaction_rate < 0.20` → `curiosity_priority = "high"` — when goals are chronically unsatisfied, increase curiosity drive
- `goals_active > 15` → `extraction_threshold += 0.05` — when too many goals are active, become more selective about new ones

This creates a feedback loop: goals shape behavior → behavior affects graph topology → topology generates new goals → goals adjust policy.

## 3. NightRun Integration (Steg 14)

The goal cycle runs as the final step of each NightRun consolidation:

```
14a. expire_stale_goals(cycle)
14b. evaluate_satisfaction for each active goal → satisfy completed ones
14c. generate_goals(field, cycle) → create new goals from topology
14d. apply_goal_weights(goals) → propagate to Brain nodes
14e. log goal metrics to eval_log
```

Goal metrics are also fed to the cognitive policy evaluator, so policy triggers based on `goals_active` and `goal_satisfaction_rate` fire automatically.

## 4. First Live Results

Date: 2026-04-13. Graph: 20,677 concepts, 20,008 relations.

Two crystallization goals generated automatically:

| ID | Kind | Title | Priority | Target |
|----|------|-------|----------|--------|
| 007abd97 | crystallization | Driv kristallisering i AI-forskning | 0.46 | AI-forskning |
| 083b7f92 | crystallization | Driv kristallisering i NoUse | 0.46 | NoUse |

No evidence_gap goals were generated — this indicates the graph's evidence scores are above the floor for most concepts. No contradiction goals — no flagged contradictions in the current graph. No dangling-edge goals — few isolated nodes.

The initial eval_log entry after integration:

```json
{
  "cycle": 100,
  "crystallization_rate": 0.12,
  "evidence_quality": 0.41,
  "gap_map_shrink_rate": -0.02,
  "goals_active": 5,
  "goals_satisfied_total": 2,
  "goal_satisfaction_rate": 0.4,
  "goal_progress_mean": 0.35
}
```

Note: `goals_active=5` includes goals from the test cycle; the production state has 2 active goals.

## 5. Longitudinal Measurement Protocol

Starting from this implementation, each NightRun cycle logs the following goal metrics to `eval_log.jsonl`:

- `goals_active` — number of active goals
- `goals_satisfied_total` — cumulative satisfied goals
- `goal_satisfaction_rate` — fraction of goals that reach satisfaction
- `goal_progress_mean` — average progress across active goals

After 5+ cycles, the evalving trend analysis will detect:
- Declining `goal_satisfaction_rate` → auto-trigger `curiosity_priority: high`
- Rising `goals_active` above 15 → auto-trigger `extraction_threshold += 0.05`
- Rising `goal_satisfaction_rate` → system is effectively pursuing and achieving goals

The cognitive policy state is also logged, enabling correlation between policy changes and goal outcomes.

## 6. What This Is Not

The Intrinsic Drive Engine gives Nous **autonomous will** — persistent goals that direct behavior based on what the system knows it doesn't know. It does not give Nous:

- **Metacognitive self-model**: Nous models its knowledge graph, not itself as an agent
- **Persistent identity**: Goals persist, but there is no continuous "I" that experiences them
- **Grounding**: All knowledge is symbolic; no sensorimotor anchoring
- **Consciousness**: The system strives, but does not experience striving

These are separate architectural challenges. The Drive Engine is a necessary but not sufficient component for what could meaningfully be called self-awareness.

## 7. Files

| File | Role |
|------|------|
| `src/nouse/daemon/goal_registry.py` | Goal dataclass, CRUD, persistence, satisfaction evaluation |
| `src/nouse/daemon/goal_generator.py` | 4 generation sources, priority computation |
| `src/nouse/daemon/ghost_q.py` | 70/30 goal-directed topic selection |
| `src/nouse/daemon/initiative.py` | Goal-driven curiosity loop |
| `src/nouse/kernel/brain.py` | `apply_goal_weights()` method |
| `src/nouse/daemon/eval_log.py` | Goal metrics in eval_log |
| `src/nouse/daemon/cognitive_policy.py` | 2 new goal-related triggers |
| `src/nouse/self_layer/living_core.py` | Goal-driven goals injection |
| `src/nouse/daemon/nightrun.py` | Steg 14: goal cycle integration |
| `src/nouse/cli/main.py` | `nouse goal` CLI command |
| `docs/WORKPLAN_DRIVE.md` | Implementation workplan |

---

*Commit: e37924b — feat: Intrinsic Drive Engine (D1–D6)*
*Commit: 7d9647e — fix: add goal cycle to consolidation-run CLI*