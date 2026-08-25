# Nous Strategic Doctrine

**Status:** Draft distillation of the updated roadmap  
**Source documents:** `docs/archive/ROADMAP_2026-04-17_superseded.md`, `STATUS.md` (two of the three original source files, `docs/PLASTIC_COGNITIVE_SYSTEM_ROADMAP.md` and `docs/WORKPLAN.md`, no longer exist in this repo — link corrected 2026-08-25)

---

## 1. Core Claim

What is currently called AI is mostly semantic prediction, not intelligence.

A language model is a powerful expression system. It is the larynx, not the mind.

`Nous` exists to build the missing layer: a persistent epistemic substrate that can:

- store typed relations rather than only text
- maintain confidence and uncertainty explicitly
- detect contradiction against prior knowledge
- consolidate and revise structure across time
- shape what the model attends to before and after it speaks

The project should therefore be understood as a cognitive architecture effort, not as a better prompt wrapper or a memory add-on.

---

## 2. The Architectural Inversion

The dominant industry pattern is:

```text
LLM = core intelligence
tools, skills, MCP, memory = accessories
```

The `Nous` pattern is:

```text
Nous = cognitive core
LLM = larynx / semantic layer
tools = reach
operator = direction
```

This inversion is the doctrinal center of the project.

If that inversion is right, then a better frontier model gives a better larynx, not a better brain.

---

## 3. What Already Exists

The substrate is not hypothetical. The roadmap describes a system that already has:

- a residual-stream graph core (`w`, `r`, `u`)
- a local graph substrate (SQLite WAL + NetworkX)
- an 18-step daemon loop
- limbic modulation
- a global workspace
- TDA-based bisociation
- a self-layer
- model routing
- MCP, REST, CLI, and atlas surfaces

This means the strategic problem is no longer "invent the system."

It is "close the cognitive loop."

---

## 4. The Four Critical Gaps

### Gap 1: No contradiction authority

If the model says X and the graph knows not-X with strong evidence, the system still does too little.

Without contradiction handling, the graph is memory, not epistemic authority.

### Gap 2: Reflection is not causal

The system can observe itself, but self-observation does not yet reliably change behavior.

Without causal reflection, metacognition is journaling.

### Gap 3: Evidence does not mature

Relations accumulate, but too little pushes them toward crystallization.

Without evidence promotion, plasticity becomes accumulation rather than maturation.

### Gap 4: The substrate does not yet steer the larynx strongly enough

The flow is still too often:

```text
LLM -> extract -> store in Nous
```

It must become more strongly:

```text
Nous -> prioritize -> constrain -> redirect -> LLM
```

Without this reversal, the system remains "memory for an LLM" instead of "brain using a larynx."

---

## 5. Order of Operations

The roadmap is explicit that the next phase is not feature growth. It is loop closure.

The build order should remain:

```text
1. contradiction
2. evidence promotion
3. causal reflection
4. Nous -> LLM authority
5. evalving harness
```

This order matters because each stage makes the next one meaningful:

- contradiction turns the graph into an authority
- evidence promotion makes the authority mature
- causal reflection lets the system alter itself
- Nous-to-LLM steering makes the architecture visible in behavior
- evalving makes improvement measurable across time

---

## 6. What Must Be Measured

Standard LLM benchmarks are insufficient because they measure output fluency at a moment.

The doctrine says `Nous` must instead be judged by native longitudinal metrics such as:

- `crystallization_rate`
- `evidence_quality`
- `contradiction_catch_rate`
- `gap_map_shrink_rate`
- `bisociation_quality`

If those metrics do not improve over time, then the architecture is not becoming more cognitive, only more complex.

---

## 7. Internal State Is the Deep Bet

The roadmap's most important research move is the transition from a merely simulated limbic layer to calibrated internal state.

That means:

- state must have direction, not only value
- modulation must propagate through the whole system
- future behavior must differ because of present state
- operator interventions should be shaped by actual system state

This is where the project most clearly stops looking like an advanced memory system and starts looking like artificial cognition.

---

## 8. What Not To Do

The roadmap is also clear about what should *not* dominate the next phase:

- do not add more daemon features first
- do not prioritize SaaS first
- do not get distracted by infrastructure expansion
- do not treat frontend polish as the main bottleneck
- do not confuse more wrappers with more cognition

The bottleneck is not missing surface area.

The bottleneck is unresolved internal closure.

---

## 9. Strategic Reading

The project should now be read through a three-layer frame:

### Layer 1: The ontological claim

The Larynx Problem: language output is not intelligence.

### Layer 2: The architectural claim

`Nous` is a persistent epistemic substrate designed to supply what the output layer lacks.

### Layer 3: The measurement claim

A different category of system requires different benchmarks and longitudinal metrics.

If those three layers remain aligned, the project can plausibly support a paradigm-shift claim.

If they drift apart, it collapses back into "LLM memory tooling."

---

## 10. The Short Version

If the doctrine needs to be carried in one paragraph:

> `Nous` is not an LLM enhancement layer. It is an attempt to define a new category of AI system: a persistent epistemic substrate that can store, revise, consolidate, and act on knowledge across time. In this architecture, the language model is the larynx, not the mind. The next strategic step is therefore not feature expansion, but closing the cognitive loop through contradiction authority, evidence maturation, causal reflection, stronger substrate-to-model control, and longitudinal self-evaluation.

---

## 11. Model Routing Doctrine (added 2026-08-24)

From a conversation about which SLMs to run and where a free cloud API
(Groq) fits: routing between a frontier model (conductor) and a
small/cheap model (executor) is not decided by task complexity or step
count. A single LLM call can be either high-stakes or low-stakes; a
multi-step task can be either.

The two axes that actually matter:

1. **Volume/frequency** — a task repeated continuously (Nous's own
   `extract` workload: dozens of calls per cycle) risks rate limits and
   needs a model that can sustain that pace without contention. A task
   that fires rarely (`bisoc`, every 48 cycles; a curiosity research
   burst, triggered occasionally) has no such constraint — model
   *quality* matters more than *throughput* there, since there is room
   to spend it on the best available model.
2. **Stakes/reversibility** — a draft the human reviews and edits
   anyway (a lead-outreach angle, a voice-note summary) tolerates a
   weaker first attempt. A decision that becomes standing state (a
   relation written into the production graph, a threshold gating a
   HITL interrupt) deserves the strongest reasoning available.

Rule of thumb: **high volume OR low stakes → route to a small/free
model (Groq, local Ollama). Low volume AND high stakes → route to the
frontier model, or at minimum to the best available option regardless
of cost.** Step count is a poor proxy for either axis — it correlates
with neither how often a task runs nor how much a wrong answer costs.

Concrete split as of 2026-08-24, verified not just assumed (see
STATUS.md): `extract` stays local-first (gemma4:e2b/dolphin3:8b) because
of volume; `bisoc`/`synth`/curiosity-burst are good Groq candidates
because of low volume and creative-quality payoff, verified end-to-end
against Groq's live API (`groq/qwen/qwen3.6-27b`, quality 0.967, beating
gemma4:e2b's own 0.927) — not yet activated as the production default,
tracked as a pending decision in STATUS.md.

