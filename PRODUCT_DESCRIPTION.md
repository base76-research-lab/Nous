# Nous — Plastic Metacognitive Layer for Any LLM

## One-Line Pitch
**Nous is a plastic metacognitive layer that gives any LLM a brain and persistent memory — the more input it receives, the richer its topology, the better its understanding.**

---

## What Is Nous?

Nous is not RAG. Nous is not a graph database. Nous is not a smarter prompt.

Nous is a **plastic metacognitive layer** — a persistent epistemic substrate that attaches to any LLM and provides what LLMs structurally lack: the ability to know what they know, with what confidence, and what they do not know.

**The Larynx Problem:** LLMs are stateless formal systems. They process symbol strings without epistemic commitment. They cannot distinguish what they know from what they hallucinate. Scaling makes them more fluent — not more grounded.

**The architecture:**

```
question → LLM → answer_v1
answer_v1 + question → Nous.metacognition → epistemic_signal
question + answer_v1 + epistemic_signal → LLM → answer_final
```

Pass 1 — LLM thinks freely, full parametric knowledge, no pollution.  
Pass 2 — Nous evaluates epistemic status: which claims are supported? contradicted? uncertain? what bisociative connections exist that the LLM missed?  
Pass 3 — LLM refines with epistemic grounding: corrects hallucinations, expresses calibrated uncertainty, extends with genuine cross-domain connections.

**The scaling property:** The more input Nous receives, the richer the topology — the better the metacognition. Not because the database grows, but because topological richness enables bisociation. More nodes across more diverse domains create structural bridges between previously unconnected knowledge. The health metric is bisociation readiness, not concept count.

**Model-agnostic:** Nous attaches to any LLM. The contract never changes. GPT-5 today, LLaMA-6 tomorrow.

**The core insight:** LLMs are the larynx (language production). Nous is the brain (epistemic substrate). Together: a bisociation engine capable of discovering connections that neither component could find alone.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Nous Daemon                             │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │  Brain Loop   │  │   NightRun   │  │  Limbic System     │    │
│  │  (Heartbeat)  │  │  (Sleep/     │  │  ┌─────────────┐  │    │
│  │  18-step      │  │   Consolid.) │  │  │ Dopamine    │  │    │
│  │  autonomous   │  │  11-phase    │  │  │ Noradrenalin│  │    │
│  │  cycle        │  │  pipeline    │  │  │ Acetylcholin│  │    │
│  │  every 10min  │  │              │  │  └─────────────┘  │    │
│  └──────┬───────┘  └──────┬───────┘  └────────┬───────────┘    │
│         │                 │                    │                │
│  ┌──────┴─────────────────┴────────────────────┴──────────┐    │
│  │              Knowledge Graph Substrate                  │    │
│  │  ┌─────────┐  ┌──────────┐  ┌───────────┐  ┌────────┐ │    │
│  │  │ SQLite  │  │ NetworkX │  │    TDA    │  │Embeddin│ │    │
│  │  │  WAL    │  │ In-Memory│  │  (Betti)  │  │  gs    │ │    │
│  │  └─────────┘  └──────────┘  └───────────┘  └────────┘ │    │
│  │  22,000+ concepts | 24,000+ relations | 1,600 domains  │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    REST API (55 endpoints)              │    │
│  │  /api/ingest  /api/context  /api/bisociate  /api/graph  │    │
│  │  /api/nightrun/now  /api/limbic  /api/status  ...       │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Features

### 1. Brain Loop — Autonomous 18-Step Cognitive Cycle

The daemon runs continuously (default: every 10 minutes), executing:

| Step | Function | Description |
|------|----------|-------------|
| 1 | Load state | Graph, limbic state, missions |
| 2 | Process events | HITL responses, wake signals |
| 3 | Source polling | Files, conversations, bookmarks, bash history, clipboard |
| 4 | Extract relations | LLM parses text → typed relations (12 relation types) |
| 5 | Update graph | Add/strengthen edges with Hebbian learning |
| 6 | Nerve path discovery | BFS multi-hop between new concepts |
| 7 | TDA bisociation | Detect topologically novel domain pairs |
| 8 | Bridge synthesis | LLM generates connecting axioms for bisociation candidates |
| 9 | Self-layer update | Emergent property crystallization |
| 10 | Curiosity burst | Research queue processing, gap-filling |
| 11 | Memory consolidation | Strengthen high-evidence paths, prune weak ones |
| 12 | Knowledge backfill | Fill fact gaps in high-degree nodes |
| 13 | Mission audit | Check research mission progress |
| 14 | NightRun scheduler | Check if deep consolidation should trigger |
| 15 | Compaction | Aggressive pruning guided by noradrenaline |
| 16 | Journal/trace | Log cycle for debugging |
| 17 | Limbic update | Recalculate dopamine, noradrenaline, acetylcholine, λ |
| 18 | Sleep | Interruptible wait until next cycle |

**Environment variables:**
```
NOUSE_LOOP_INTERVAL_SEC = 600        # Cycle interval (seconds)
NOUSE_MEMORY_CONSOLIDATION_EVERY = 3 # Consolidate every N cycles
NOUSE_MEMORY_CONSOLIDATION_BATCH = 40
NOUSE_KNOWLEDGE_BACKFILL_EVERY = 6
NOUSE_KNOWLEDGE_BACKFILL_LIMIT = 160
NOUSE_MISSION_SEED_EVERY = 1
NOUSE_MISSION_SEED_MAX = 2
NOUSE_MISSION_AUDIT_EVERY = 3
NOUSE_HITL_ENABLED = 1
NOUSE_HITL_PRIORITY_THRESHOLD = 0.98
NOUSE_SOURCE_THROTTLE_FAIL_THRESHOLD = 3
NOUSE_SOURCE_THROTTLE_BASE_SEC = 300
NOUSE_SOURCE_THROTTLE_MAX_SEC = 7200
NOUSE_SYSTEM_EVENTS_PER_CYCLE = 8
```

---

### 2. NightRun — 11-Phase Deep Consolidation (Slow-Wave Sleep Analog)

Triggered during idle periods or manually. Processes temporary memories into permanent knowledge.

| Phase | Name | Description |
|-------|------|-------------|
| 1 | Replay | Read all unconsolidated inbox posts |
| 2 | Evaluate evidence | Apply grace period for new concepts (< 48h) |
| 3 | Consolidate strong | evidence_score ≥ threshold → permanent graph |
| 4 | Discard weak | Below threshold → evaporated |
| 5 | Bisociation pass | Link new domains to existing domains via path finding |
| 6 | Pruning/Compaction | Remove weak edges, guided by noradrenaline |
| 7 | Node enrichment | Add contextual metadata to high-degree nodes |
| 8 | ReviewQueue flush | Flagged axioms undergo deep LLM review (PROMOTE/KEEP/DISCARD) |
| 9 | DeepDive axiom discovery | Extract foundational axioms from hub nodes |
| 10 | Ghost Q | LLM-driven graph crawling on dangling edges |
| 11 | Decomposition burst | Recursive epistemics → universal primitives |

**Environment variables:**
```
NOUSE_NIGHTRUN_MIN_EVIDENCE = 0.45      # Normal evidence threshold
NOUSE_NIGHTRUN_MIN_SUPPORT = 1          # Minimum support count
NOUSE_NIGHTRUN_STRONG_EVIDENCE = 0.65   # Strong evidence threshold
NOUSE_NIGHTRUN_GRACE_HOURS = 48         # Grace period for new concepts
NOUSE_NIGHTRUN_GRACE_EVIDENCE = 0.15    # Lower threshold during grace
```

**NightRun modes:** `idle` (wait for inactivity), `night` (22:00–06:00), `always`, `never`

---

### 3. Hebbian Plasticity + STDP — Biological Learning Rules

#### Hebbian Learning (LearningCoordinator)

Edges are strengthened through co-activation, modulated by the limbic system:

```
Δw = BASE_DELTA × (1 + noradrenaline)
```

**4-Phase Learning Pipeline:**
1. **Limbic-modulated delta** — Surprise (noradrenaline) accelerates learning
2. **Spreading activation** — Strengthen neighbors with decay factor
3. **Assumption flag evolution** — Clear uncertainty flag when evidence ≥ CONFIDENCE_GATE
4. **Granularity update** — `granularity = 1 + floor(log2(support_count))`

```
NOUSE_LEARN_BASE_DELTA = 0.05       # Base weight increment
NOUSE_LEARN_SPREAD_DECAY = 0.4      # Neighbor activation decay
NOUSE_LEARN_CONFIDENCE_GATE = 0.65  # Threshold to clear assumption flag
```

#### STDP (Spike-Timing-Dependent Plasticity)

Neuroscience-grade temporal learning. Uses Brian2 (Rust backend) with Python fallback.

**STDP Window (exponential):**
- `Δt > 0` (pre before post): **LTP** (Long-Term Potentiation) — strengthen
- `Δt < 0` (pre after post): **LTD** (Long-Term Depression) — weaken

```
NOUSE_STDP_A_PLUS = 0.01        # LTP amplitude
NOUSE_STDP_A_MINUS = 0.012      # LTD amplitude (asymmetry biases toward potentiation)
NOUSE_STDP_TAU_PLUS = 20.0      # LTP time constant (seconds)
NOUSE_STDP_TAU_MINUS = 20.0     # LTD time constant (seconds)
NOUSE_STDP_W_MIN = 0.0          # Weight floor
NOUSE_STDP_W_MAX = 5.0          # Weight ceiling
```

---

### 4. Limbic System — Neuromodulatory Drive

Three neuromodulators govern system behavior:

| Neuromodulator | Signal | Effect | Baseline | Decay |
|----------------|--------|--------|----------|-------|
| **Dopamine** | Reward prediction error (TD error: `δ = r + γV(s') - V(s)`) | Modulates λ (creativity coefficient) | 0.5 | 0.15/cycle |
| **Noradrenaline** | Surprise (`-log P(x)`) | Modulates pruning aggressivity | 0.3 | 0.20/cycle |
| **Acetylcholine** | Attention (β temperature) | Modulates focus selectivity (Winner-Take-All) | 1.0 | 0.10/cycle |

**Derived signals:**
```
arousal = 0.4 × dopamine + 0.4 × noradrenaline + 0.2 × acetylcholine

λ (creativity) = LAMBDA_MIN + (dopamine × (LAMBDA_MAX - LAMBDA_MIN))
    LAMBDA_MIN = 0.1, LAMBDA_MAX = 0.9

pruning_aggression = 0.1 + min(0.8, noradrenaline × 1.5)

Yerkes-Dodson performance = max(0, 1.0 - K × (arousal - OPTIMAL)²)
    AROUSAL_OPTIMAL = 0.6, AROUSAL_K = 2.0
```

**Homeostatic control:**
- Tonic (slow) baselines adapt over ~500 cycles via EMA
- Phasic (fast) signals: deviations from tonic → moment-to-moment drive

```
NOUSE_AROUSAL_DORMANT = 0.88    # Threshold for compaction aggressivity
```

---

### 5. TDA (Topological Data Analysis) — Bisociation Detection

**Betti numbers** characterize the "shape" of each knowledge domain:
- `H0` = number of connected components (clusters)
- `H1` = number of independent cycles (loops, feedback structures)

**Bisociation formula:**
```
τ(D_a, D_b) = topological_similarity(H0_a, H1_a, H0_b, H1_b)  ∈ [0, 1]
```

**Detection rule:** High τ (similar topology) + Low semantic similarity = **bisociation candidate**. Two domains that are structurally alike but semantically distant → creative bridge opportunity.

Implementation: Rust (fast) or Python scipy (fallback).

```
NOUSE_BISOC_SEMANTIC_WEIGHT = 0.35
NOUSE_BISOC_SEMANTIC_SIM_MAX = 0.92
```

---

### 6. Recursive Epistemic Decomposition — Universal Primitives

**Nollanalys (Zero Analysis):** Recursively decompose any concept to its fundamental building blocks.

```
Monstera deliciosa
  → fotosyntes → kvantkoherens → kvantmekanik (EXISTS in graph!)
  → tropism → auxin-gradient → gradient descent (EXISTS!)
  → celldelning → mitos → DNA-replikation (EXISTS!)
```

When a sub-concept's parent domain already exists in the graph → **automatic cross-domain bridge**.

**Philosophy:** "Nothing is classless — everything is built on something else." By finding each sub-concept's TRUE parent, connections emerge naturally.

**Incubation queue with creative free energy:**
```
F_bisoc^τ:  T* = (T_min / γ) × ln(1 / (1 - τ))
```
Partial decompositions incubate for T* cycles before maturation check.

**Seed primitives (domain-agnostic):**
```
entropi, gradient, oscillation, feedback, prediktionsfel, tröskel, symmetri,
emergens, självorganisering, attraktor, bifurkation, phase transition,
stochasticity, hierarki, modularitet, scalability, robustness, adaptability,
homeostasis, allostasis, control, regulation, amplification
```

```
NOUSE_DECOMP_MODEL = qwen3.5:latest
NOUSE_DECOMP_TIMEOUT_SEC = 20
NOUSE_DECOMP_MAX_DEPTH = 5
NOUSE_DECOMP_MIN_CONVERGENCE = 2   # Domains before axiom promotion
NOUSE_FBISOC_GAMMA = 0.5
NOUSE_FBISOC_T_MIN = 9
```

---

### 7. Axon Growth Cone — Structural Resonance

Dynamically grows new synaptic connections based on **topological isomorphism** (structural shape matching), not semantic similarity.

Two domains with similar graph structure (same branching patterns, cycle counts) get connected even if their content is completely different.

```
NOUSE_GROWTH_MAX_CANDIDATES = 50
NOUSE_GROWTH_MAX_SYNAPSES = 5
NOUSE_GROWTH_MIN_RESONANCE = 0.35     # Minimum structural match
NOUSE_GROWTH_META_THRESHOLD = 0.70    # Meta-axiom crystallization threshold
```

---

### 8. Bisociative Problem Solver — Cross-Domain Engineering

**The killer application:** When solving a problem, instead of searching only within the same domain, Nous decomposes the problem to primitives and searches ALL domains for solutions.

**Example flow:**
```
Problem: "Python GIL blocks multicore performance"

Step 1 — DECOMPOSE to primitives:
  → parallellism, resource contention, exclusive locking, workload partitioning

Step 2 — SEARCH Nous cross-domain:
  → Go: goroutines (CSP model)
  → Erlang: actors (message passing)
  → Neuroscience: parallel processing
  → Biology: cell division
  → Traffic engineering: flow control

Step 3 — SYNTHESIZE:
  "CSP model from Go can be implemented in Python via asyncio"
  "Traffic flow scheduling → time-windowed DB writes"

Step 4 — FEEDBACK:
  New knowledge ingested → graph grows → better suggestions next time
```

**Self-reinforcing loop:** Every problem solved makes the system smarter for the next one.

---

### 9. Knowledge Graph Substrate

**Dual storage:** SQLite WAL (persistence) + NetworkX (fast in-memory traversal)

**Node structure:**
- `name` — concept name
- `domain` — knowledge domain (e.g., "kvantmekanik", "mykologi")
- `metadata` — arbitrary JSON
- `created_at`, `updated_at`

**Edge structure (Axiom):**
- `src` → `tgt` (directed)
- `rel_type` — one of 12 typed relations
- `why` — natural language explanation
- `evidence_score` — confidence (0.0–1.0)
- `support_count` — how many times confirmed
- `domain_src`, `domain_tgt` — source/target domains
- `assumption_flag` — uncertain until confirmed
- `granularity` — `1 + floor(log2(support_count))`

**12 Relation Types:**
```
modulerar, orsakar, konsoliderar, är_del_av, synkroniserar, reglerar,
oscillerar, är_analogt_med, stärker, försvagar, producerar, beskriver
```

**Key operations:**
```python
add_concept(name, domain, metadata)
add_relation(src, rel_type, tgt, why, evidence_score, support_count)
strengthen(src, tgt, delta)           # Hebbian increment
find_path(src, tgt, max_hops)         # BFS path finding
bisociation_candidates(tau, max)      # TDA-based detection
domain_tda_profile(domain)            # Betti numbers (H0, H1)
```

```
NOUSE_GRAPH_EMBED_ENABLED = True
NOUSE_GRAPH_EMBED_MODEL = nomic-embed-text-v2-moe:latest
NOUSE_STRONG_FACT_MIN_SCORE = 0.65
```

---

### 10. LLM Relation Extraction (Broca's Area)

Parses raw text into typed relations. NOT reasoning — pure structured extraction.

```
NOUSE_EXTRACT_MODEL = deepseek-r1:1.5b
NOUSE_EXTRACT_FALLBACK_MODEL = ""
NOUSE_EXTRACT_MAX_CHARS = 2200
NOUSE_EXTRACT_MAX_RELATIONS = 15
NOUSE_EXTRACT_TIMEOUT_SEC = 19
NOUSE_EXTRACT_HEURISTIC_FALLBACK = 1  # Regex fallback if LLM fails
NOUSE_MODEL_AUTODISCOVER = 1          # Auto-detect available models
```

---

### 11. Source Management — Multi-Channel Ingestion

Nous monitors multiple input sources autonomously:
- **File system** — watched directories (markdown, PDFs, code)
- **Conversations** — .gemini, .claude project folders
- **Chrome bookmarks** — browser bookmark changes
- **Chrome history** — browsing patterns
- **Bash history** — terminal commands
- **Capture queue** — manual captures
- **Clipboard daemon** — copy/paste content
- **API ingestion** — `/api/ingest` endpoint

```
NOUSE_SOURCE_PROGRESS_TRACE = 1
NOUSE_SOURCE_PROGRESS_DOC_EVERY = 5
```

---

### 12. Human-in-the-Loop (HITL)

Low-confidence decisions pause and wait for human feedback:
- `GET /api/hitl/interrupts` — view pending decisions
- `POST /api/hitl/approve` — confirm
- `POST /api/hitl/reject` — reject

```
NOUSE_HITL_ENABLED = 1
NOUSE_HITL_PRIORITY_THRESHOLD = 0.98
```

---

### 13. Metacognition — Self-Awareness

- **Snapshots** — Frozen copies of entire system state (graph + limbic + TDA profiles)
- **Genesis** — Self-modifying tool creation (`create_new_tool(name, description, code)`)
- **Self-layer** — Emergent properties written as discoveries

---

### 14. Missions & Research Tasks

Goal-directed knowledge acquisition:
- **Kickstart** — Seed missions from domain gaps
- **Scorecard** — Track mission progress
- **Curiosity burst** — Autonomous gap-filling research

---

## REST API — 55 Endpoints

### Status & System
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | HTML dashboard |
| `/api/status` | GET | Graph stats + limbic state |
| `/api/write-queue/stats` | GET | Write queue depth/throughput |
| `/api/system/events` | GET | System event log |
| `/api/brain_regions` | GET | Brain anatomy stats |
| `/api/system/wake` | POST | Wake signal (trigger cycle) |

### Graph Navigation & Search
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/graph` | GET | Full graph export (nodes, edges, domains) |
| `/api/graph/focus` | GET | Focused subgraph around node(s) |
| `/api/nerv` | GET | Find nerve path between domains (BFS, novelty score) |
| `/api/bisoc` | GET | Bisociation candidates via TDA |
| `/api/knowledge/audit` | GET | Facts, axioms, contradictions, gaps |
| `/api/memory/audit` | GET | Memory consolidation stats |

### Learning & Consolidation
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/memory/consolidate` | POST | Trigger memory consolidation |
| `/api/nightrun/now` | POST | Trigger full NightRun immediately |
| `/api/knowledge/enrich` | POST | LLM-driven node enrichment |
| `/api/knowledge/deepdive` | POST | Axiom discovery on specific node |
| `/api/knowledge/backfill` | POST | Fill knowledge gaps |

### Ingestion & Context
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ingest` | POST | Ingest text → extract relations → add to graph |
| `/api/context` | POST | Lightweight read-only context lookup (no LLM) |
| `/api/bisociate` | POST | Bisociative problem solver (decompose → search → synthesize) |

### Limbic & Models
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/limbic` | GET | Limbic state (dopamine, noradrenaline, acetylcholine, λ, arousal) |
| `/api/models/policy` | GET | LLM model selection policy |
| `/api/usage/summary` | GET | Token usage summary |

### Sessions, Missions, HITL, Queues
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sessions` | GET | Active sessions |
| `/api/sessions/open` | POST | Open new session |
| `/api/mission/scorecard` | GET | Mission progress |
| `/api/hitl/interrupts` | GET | Pending human decisions |
| `/api/hitl/approve` | POST | Approve decision |
| `/api/conductor/cycle` | POST | Cognitive conductor cycle |
| `/api/snapshot` | POST | Create system snapshot |

*(Plus 20+ additional endpoints for queues, tracing, journaling, clawbot ingestion, etc.)*

---

## Tools

### Island Bridge — Domain Fusion + Nerve Bootstrap
Merges duplicate domains (e.g., "software engineering" = "programvaruutveckling" = "mjukvaruutveckling") and bootstraps initial cross-domain connections via LLM.

### Recursive Ingest — Hierarchical Decomposition
New concept → analyze → find parent domain → exists in graph? → automatic bridge. Recurses to configurable depth.

### Bisociative Solver — Cross-Domain Problem Solving
Problem → decompose to primitives → search ALL domains → synthesize solutions → feedback loop.

### Seed Decomposition — Mass Axiom Seeding
Pre-populate graph with universal primitives by running decomposition on top hub nodes.

---

## Technical Specifications

| Spec | Value |
|------|-------|
| Language | Python 3.11+ |
| Codebase | ~39,000 lines, 150 modules |
| Database | SQLite WAL + NetworkX in-memory |
| API | FastAPI + Uvicorn (55 endpoints) |
| LLM Backend | Ollama (local), Cerebras, Groq (cloud) |
| Embedding | nomic-embed-text-v2-moe, qwen3-embedding:4b |
| TDA Engine | Rust (fast) / Python scipy (fallback) |
| STDP | Brian2 (Rust) / Python (fallback) |
| License | MIT |
| Version | 0.3.2 (alpha) |

**Dependencies:** ollama, rich, networkx, watchdog, numpy, scipy, fastapi, uvicorn, pydantic, pandas, httpx, beautifulsoup4, lxml, pypdf

---

## Benchmark Results

**TruthfulQA (retrieval-augmented):**
- llama-3.1-8b baseline: **46%**
- llama-3.1-8b + Nous: **96%**

---

## What Makes Nous Different?

| | Traditional RAG | Vector DB | Nous |
|---|---|---|---|
| **Role** | Knowledge retrieval | Similarity search | Metacognitive layer |
| **Architecture** | Inject context into prompt | Embed + cosine rank | LLM → Nous → LLM |
| **Storage** | Flat vector chunks | Embeddings | Typed graph, evidence-scored |
| **Learning** | None — static | None — static | Hebbian plasticity + STDP + limbic |
| **Discovery** | Semantic similarity | Semantic similarity | TDA bisociation (topological) |
| **Consolidation** | None | None | 11-phase NightRun (sleep analog) |
| **Epistemic signal** | None | None | Contradiction, evidence, uncertainty, bisociation |
| **Scaling property** | More docs → more retrieval hits | More vectors → more matches | More input → richer topology → better metacognition |
| **Autonomy** | Query-response | Query-response | 18-step autonomous brain loop |
| **Cross-domain** | None | None | Automatic bridge synthesis |
| **Metacognition** | None | None | Knows what it knows, with what confidence |

---

## Philosophy

> "LLM(Larynx) + Nous(Brain) = Bisociation Engine"

LLMs are stateless. They know but do not remember. They answer but do not believe. They produce but cannot distinguish what they know from what they guess.

Nous is the missing layer. Not retrieval — **metacognition**. The capacity to evaluate one's own epistemic state: what is known with high confidence, what is contradicted, what is thin, and what unexpected connections exist across domains that no one made explicit.

Intelligence is not about having the right answer. It is about knowing the epistemic status of your answer — and having the structural memory to improve it.

Nous grows plastically with every input. Not because it stores more facts, but because a richer topology enables richer bisociation. The brain does not get smarter by adding more neurons — it gets smarter by forming better connections between them.

The system is built around Arthur Koestler's concept of **bisociation**: the creative act of connecting two previously unrelated frames of reference. Nous automates this through topological analysis — finding domains that are structurally similar but semantically distant, then using the metacognitive pass to surface the bridge to the LLM.

> Nous is not a memory system. It is what makes memory *mean something*.

---

*Built by Björn Wikström at Base76 Research Lab*
*22,000+ concepts | 24,000+ relations | 1,600+ domains | Growing autonomously*
