# Intrinsic Drive Engine — WORKPLAN

**Skapad:** 2026-04-13
**Mål:** Gör grafen mål-genererande. Från reaktiv nyfikenhet till generativ intention.

---

## Problem

Nous har reaktiv autonomi men saknar generativ:
- **Ghost Q** kryller svaga noder men har ingen uppfattning om *varför*
- **Curiosity loop** triggas av limbisk arousal + TDA-gap, men har inget minne av vad den försöker uppnå
- **`goal_weight`** existerar på `NodeStateSpace` men sätts aldrig dynamiskt
- **living_core drives** ("curiosity", "maintenance", etc.) är statiska beräkningar — de genererar inte mål som lever över cykler
- **Ingen mekanism** säger "Jag bör undersöka X för att Y är oklart och Z beror på det"

Kort: systemet reagerar. Det formar inte egna intentioner.

---

## Princip

En Intrinsic Drive Engine omvandlar graf-topologi till mål. Den:
1. **Identifierar** vad grafen behöver (evidens-gap, kontradiktionszoner, dangling edges, låg crystallization)
2. **Formulerar** mål som lever över cykler (inte bara strängar — strukturerade objekt med prioritet och tillstånd)
3. **Dirigerar** existerande system (Ghost Q, curiosity, DeepDive) mot målen
4. **Detekterar** när ett mål är uppnått eller föråldrat
5. **Mäter** goal-satisfaction-rate i eval_log

---

## Prioritet D1 — Goal Registry (mål-lager)

**Vad:** En persistent lagring av aktiva mål som överlever cykler.
**Varför nu:** Utan detta är alla andra komponenter blinda för intention.

### Uppgifter

**D1.1 `daemon/goal_registry.py` — ny fil**

Datamodell:
```python
@dataclass
class Goal:
    id: str                   # uuid
    title: str                # "Öka evidens för X→Y i domän Z"
    kind: str                 # "evidence_gap" | "contradiction_resolve" | "domain_expand" | "crystallization" | "operator_mission"
    status: str               # "active" | "satisfied" | "expired" | "blocked"
    priority: float           # 0.0–1.0, beräknas från graf-topologi
    target_concepts: list[str]# noder som målet gäller
    target_domain: str         # domän
    source: str                # "gap_map" | "eval_decline" | "operator" | "contradiction"
    created_cycle: int
    updated_cycle: int
    deadline_cycle: int | None # max-cykel innan expiry (default: created + 50)
    satisfaction_criteria: dict  # mätbara kriterier, t.ex. {"evidence_floor": 0.55}
    progress: float           # 0.0–1.0, uppdateras varje cykel
    parent_goal_id: str | None # hierarki: sub-mål
```

Funktioner:
- `create_goal(*, title, kind, target_concepts, ...) -> Goal`
- `load_goals(path=None) -> list[Goal]` — läs från `goal_registry.jsonl`
- `save_goal(goal, path=None) -> Goal`
- `active_goals(path=None) -> list[Goal]` — filtrera status="active"
- `update_goal_progress(goal_id, cycle, metrics) -> Goal` — evaluera satisfaction_criteria
- `expire_stale_goals(cycle, path=None) -> int` — markera mål som passerat deadline
- `goal_by_concepts(concepts, path=None) -> Goal | None` — hitta existerande mål för koncept

**D1.2 Integration i NightRun**

Lägg till Steg 14 i `nightrun.py`:
- Läs `active_goals()`
- För varje aktivt mål: evaluera `satisfaction_criteria` mot nuvarande graf-state
- Uppdatera `progress` och ev. status → "satisfied"
- Expirera mål som passerat `deadline_cycle`
- Logga: `{goals_active, goals_satisfied, goals_expired, goal_progress_mean}`

---

## Prioritet D2 — Goal Generation (topologi → mål)

**Vad:** Skapa mål automatiskt från grafens topologiska signaler.
**Varför:** Detta är kärnan — grafen säger *själv* vad som behövs.

### Uppgifter

**D2.1 `daemon/goal_generator.py` — ny fil**

Fyra källor till målbildning:

**Källa 1: gap_map → evidence_gap-mål**
```python
def generate_from_gap_map(field, cycle) -> list[Goal]:
    # Noder med evidence_score < 0.35 OCH > 2 utgående kanter
    # = "koncept vi vet lite om men som är viktiga"
    # Mål: "Öka evidens för {node}" med criteria: {evidence_floor: 0.45}
```

**Källa 2: contradiction_events → contradiction_resolve-mål**
```python
def generate_from_contradictions(field, cycle) -> list[Goal]:
    # Noder som deltar i contradiction events
    # Mål: "Lös kontradiktion kring {node}" med criteria: {contradiction_count: 0}
```

**Källa 3: crystallization_rate → crystallization-mål**
```python
def generate_from_crystallization(field, cycle) -> list[Goal]:
    # Om crystallization_rate < 0.15 (från eval_log)
    # Mål: "Driv kristallisering i domän {domain}" med criteria: {crystallization_rate: 0.20}
```

**Källa 4: dangling edges → domain_expand-mål**
```python
def generate_from_dangling(field, cycle) -> list[Goal]:
    # Dangling targets (X→Y där Y ej är nod)
    # Mål: "Expandera domän kring {dangling_target}" med criteria: {node_exists: True}
```

**Deduplicering:** Om ett mål för samma target_concepts+kind redan finns → uppdatera prioritet istället för att skapa nytt.

**Prioritetsberäkning:**
```python
priority = (
    0.35 * topological_urgency    # grad * (1 - evidence_score) för target_concepts
  + 0.25 * eval_trend_signal      # sjunkande trend → högre prioritet
  + 0.20 * drive_alignment       # om living_core active_drive matchar goal.kind
  + 0.20 * operator_feedback      # om feedback_log visar "bad" → prioritera improvement
)
```

**D2.2 Integration i NightRun**

Lägg till i Steg 14 (efter D1.2):
- Kör `generate_from_*()` med nuvarande graf-state
- Skapa nya mål (om inte redan existerande)
- Uppdatera prioritet på existerande mål
- Skriv till `goal_registry.jsonl`

---

## Prioritet D3 — Goal-Directed Execution (mål → handling)

**Vad:** Dirigera existerande autonoma system mot aktiva mål.
**Varför:** Mål utan execution är dagbok. Execution utan mål är slump.

### Uppgifter

**D3.1 Mål-styrning av Ghost Q**

Ändra `ghost_q.py:find_weak_nodes()`:
- Om aktiva mål finns med kind="evidence_gap": prioritera dessa noder
- `goal_registry.active_goals(kind="evidence_gap") → target_concepts`
- Blanda: 70% goal-directed + 30% vanlig weak-node (behåller utforskande)

**D3.2 Mål-styrning av curiosity loop**

Ändra `initiative.py:run_curiosity_burst()`:
- Om aktiva mål finns: välj domän från målets `target_domain`
- Mål med kind="contradiction_resolve": formulera system_prompt kring konflikt-lösning
- Mål med kind="domain_expand": prioritera dangling targets

**D3.3 goal_weight-dynamik**

Ny funktion i `brain.py` eller `field/surface.py`:
```python
def apply_goal_weights(self, goals: list[Goal]) -> int:
    """Uppdatera goal_weight på noder baserat på aktiva mål."""
    updated = 0
    for goal in goals:
        if goal.status != "active":
            continue
        for concept in goal.target_concepts:
            node = self.nodes.get(concept)
            if node:
                # goal_weight = max(existerande, mål-prioritet)
                new_gw = max(node.goal_weight, goal.priority)
                node.goal_weight = _clamp(new_gw, 0.0, 1.0)
                updated += 1
    return updated
```

Detta knyter `goal_weight` (som redan används i `collapse()` och `wrapper.py`) till faktiska mål.

**D3.4 Integration i NightRun**

Lägg till i Steg 14:
- `apply_goal_weights(brain, active_goals)` — uppdatera noder
- Skicka aktiva mål till Ghost Q och curiosity loop som kontext

---

## Prioritet D4 — Goal Satisfaction & Feedback (stäng loopen)

**Vad:** Detektera när mål är uppnådda och mata tillbaka till systemet.
**Varför:** Utan satisfaction detection ackumuleras mål i oändlighet.

### Uppgifter

**D4.1 Satisfaction-evaluering**

I `goal_registry.py`:
```python
def evaluate_satisfaction(goal: Goal, field, cycle: int) -> str:
    """Returnera "satisfied"|"progressing"|"blocked"|"expired"."""
    criteria = goal.satisfaction_criteria

    if goal.kind == "evidence_gap":
        # Kolla om target_concepts har evidence_score >= criteria.evidence_floor
        scores = [field.evidence_score(c) or 0 for c in goal.target_concepts]
        goal.progress = sum(1 for s in scores if s >= criteria.get("evidence_floor", 0.55)) / len(scores)
        return "satisfied" if goal.progress >= 1.0 else "progressing"

    if goal.kind == "contradiction_resolve":
        # Kolla om contradiction_count == 0 för target_concepts
        count = count_contradiction_events_for(goal.target_concepts)
        goal.progress = 1.0 if count == 0 else max(0, 1.0 - count / 3.0)
        return "satisfied" if count == 0 else "progressing"

    if goal.kind == "crystallization":
        # Kolla crystallization_rate från eval_log
        rate = latest_crystallization_rate()
        target = criteria.get("crystallization_rate", 0.20)
        goal.progress = min(1.0, rate / target)
        return "satisfied" if rate >= target else "progressing"

    if goal.kind == "domain_expand":
        # Kolla om target_concept nu är en nod
        exists = all(field.node_exists(c) for c in goal.target_concepts)
        goal.progress = 1.0 if exists else 0.0
        return "satisfied" if exists else "progressing"

    # Deadline-check
    if goal.deadline_cycle and cycle > goal.deadline_cycle:
        return "expired"

    return "active"
```

**D4.2 Operator missions**

Ny mekanism för operatörs-drivna mål:
- `nouse goal add "Förstå sambandet mellan X och Y"` → skapar Goal med kind="operator_mission"
- `nouse goal list` → visa aktiva mål
- `nouse goal status <id>` → visa mål-status och framsteg
- Operatörs-mål har `deadline_cycle=None` (lever tills uppnått eller operatören stänger)

**D4.3 Eval-mätvärde**

Lägg till i `eval_log.py:write_eval_entry()`:
- `goals_active: int`
- `goals_satisfied_total: int`
- `goal_satisfaction_rate: float` (% av mål som uppnåtts per cykel)
- `goal_progress_mean: float`

Detta ger longitudinell mätning av om systemets intentioner faktiskt leder till resultat.

---

## Prioritet D5 — Drive-Cognitive Policy Integration

**Vad:** Koppla målbildning till kognitiv policy.
**Varför:** När målbildning fungerar bör den styra policy, inte bara tvärtom.

### Uppgifter

**D5.1 Nya trigger-regler i `cognitive_policy.py`**

Lägg till:
```python
{
    "metric": "goal_satisfaction_rate",
    "condition": "below",
    "threshold": 0.20,
    "param": "curiosity_priority",
    "value": "high",
    "reason": "goal_satisfaction_rate < 0.2 → prioritera kunskapsgap",
},
{
    "metric": "goals_active",
    "condition": "above",
    "threshold": 15,
    "param": "extraction_threshold",
    "delta": +0.05,
    "reason": "too many active goals → var mer selektiv med nya mål",
},
```

**D5.2 Goal-driven living_core**

I `living_core.py:update_living_core()`:
- Läs `active_goals()` och inkludera i `drives.goals` (ersätt nuvarande statiska `_drive_goals()`)
- Om mål med hög prioritet matchar aktiv drive → stärk den drivens score
- `last_reflection.thought` inkluderar topp-3 måls titlar

---

## Filöversikt

| Fil | Typ | Beskrivning |
|-----|-----|-------------|
| `daemon/goal_registry.py` | NY | Goal-dataklass, persistence, satisfaction |
| `daemon/goal_generator.py` | NY | 4 målkällor, prioritering |
| `daemon/nightrun.py` | ÄNDRA | Steg 14: goal cycle |
| `daemon/ghost_q.py` | ÄNDRA | Goal-directed topic selection |
| `daemon/initiative.py` | ÄNDRA | Goal-directed curiosity |
| `kernel/brain.py` | ÄNDRA | `apply_goal_weights()` |
| `daemon/cognitive_policy.py` | ÄNDRA | Nya trigger-regler |
| `daemon/eval_log.py` | ÄNDRA | goal-mätvärden |
| `self_layer/living_core.py` | ÄNDRA | Goal-driven drives |
| `cli/main.py` | ÄNDRA | `nouse goal`-kommandon |

---

## Sekvens

```
D1: Goal Registry      ← datastrukturen, allt bygger på denna
 └── D2: Goal Generation ← graf → mål (fyra källor)
      └── D3: Goal-Directed Execution ← målen dirigerar Ghost Q / curiosity
           └── D4: Satisfaction & Feedback ← stäng loopen
                └── D5: Policy Integration ← målbildning styr policy
```

D1 → D2 kan göras parallellt (D1 = data, D2 = logik), men D3 beror på båda.

---

## Longitudinell mätning

| Mätvärde | Nu | Mål (3 månader) |
|----------|-----|-----------------|
| `goals_active` | 0 | 5–15 per cykel |
| `goal_satisfaction_rate` | N/A | >30% |
| `goal_weight` användning | 0 (aldrig satt) | Dynamisk på >20% av noder |
| Ghost Q goal-hit rate | ~0% (slump) | >40% goal-directed |
| Curiosity goal-alignment | ~0% (slump) | >30% goal-directed |

---

## Vad vi inte gör just nu

- Hierarkisk målnedbrytning (parent_goal_id finns men sub-mål-generering är D6)
- Multi-step plan-hierarchier (AGI-nivå, kräver fungerande D1–D5)
- External goal-negotiation (operatören kan lägga till men systemet föreslår inte ännu)
- Goal conflict resolution (när två mål motsäger varandra — behöver fler cykler av data)