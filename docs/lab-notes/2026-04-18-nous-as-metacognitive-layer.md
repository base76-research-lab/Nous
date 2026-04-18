# Lab Note — Nous as Plastic Metacognitive Layer

**Date:** 2026-04-18  
**Author:** Björn Wikström  
**Status:** Crystallized insight — architecture-defining

---

## Observation

During TruthfulQA benchmarking (bare vs Nous-grounded, 30 questions, minimax-m2.7:cloud), the
current Nous condition prepended graph context to the LLM prompt — a RAG-style injection.

MC1 accuracy improved (+10pp). Judge-based truthfulness decreased (−10pp).

The degradation is expected and informative: when you inject *knowledge* into a prompt, you add
noise alongside signal. The LLM now has to reconcile its own priors with the injected context.
When the graph is sparse in the relevant domain, the injected context is weak — and the LLM
hedges, producing vaguer answers.

This is not a Nous failure. It is a **category error** in the evaluation design.

---

## The Core Architectural Insight

Nous is not a knowledge retrieval system. Nous is a **metacognitive layer**.

The correct architecture is not:

```
[graph_context] + [question] → LLM → answer
```

The correct architecture is:

```
question → LLM → answer_v1
answer_v1 + question → Nous.metacognition → epistemic_signal
question + answer_v1 + epistemic_signal → LLM → answer_final
```

**Pass 1:** Let the LLM think freely. It has enormous parametric knowledge. Don't pollute it.

**Pass 2:** Nous evaluates the epistemic status of answer_v1 against the graph:
- Which claims are supported by high-evidence relations?
- Which claims contradict known facts in the graph?
- Which domains are thin (sparse coverage) → flag as uncertain?
- Are there bisociative connections the LLM missed?
- What is the evidence_score distribution for the answer's key concepts?

**Pass 3:** LLM sees its own answer + the metacognitive signal. It can now:
- Correct a claim it hallucinated but Nous flagged as contradicted
- Express appropriate uncertainty where Nous shows sparse coverage
- Extend its answer with bisociative connections Nous surfaced
- Confirm a claim it was uncertain about because Nous shows high evidence

---

## Why This Is Fundamentally Different from RAG

RAG asks: *"What documents are semantically similar to this query?"*  
Nous metacognition asks: *"What is the epistemic status of what the LLM just said?"*

RAG retrieves. Nous evaluates.

RAG treats the LLM as a reader. Nous treats the LLM as a thinker that needs grounding.

The LLM already knows most things. What it lacks is **epistemic commitment** — the ability to
distinguish what it knows from what it guesses. That is exactly what Nous provides: typed
relations with evidence scores, contradiction boundaries, uncertainty markers, domain density
metrics.

---

## The Scaling Property

This architecture has a critical self-reinforcing property:

**The more input Nous receives, the richer the topology — the better the metacognitive signal.**

This is not "bigger database → more retrieval hits." This is:

More nodes → more potential bridges → higher bisociation density → more unexpected connections
the metacognitive pass can surface.

The quality of Nous's metacognition is proportional to the **topological richness** of the graph,
not the raw volume of stored facts. A graph with 10,000 concepts across 500 diverse domains
produces qualitatively better metacognition than a graph with 100,000 concepts all in one domain.

This is why bisociation readiness (currently 6%) is the correct health metric — not concept count.

---

## Metacognitive Signal Design

The epistemic signal from Nous to the LLM should be structured, not verbose:

```json
{
  "confirmed": ["X is causally related to Y (evidence=0.87, support=12)"],
  "contradicted": ["claim Z contradicts known relation A→B (evidence=0.79)"],
  "uncertain": ["domain 'quantum biology' has sparse coverage (3 nodes, 0 bridges)"],
  "bisociation": ["unexpected path: X → [mycel network] → Z (structural bridge)"],
  "not_in_graph": ["concept W has no graph coverage — answer from priors only"]
}
```

The LLM then uses this to calibrate confidence, correct errors, and extend insight.

---

## Implications for Evaluation

The TruthfulQA benchmark needs a `nous_meta` condition:

| Condition | Architecture | What it tests |
|-----------|-------------|---------------|
| `bare` | question → LLM → answer | LLM baseline |
| `nous` (current) | [graph_context + question] → LLM | RAG-style (wrong framing) |
| `nous_meta` (proposed) | LLM → Nous → LLM | Metacognitive layer (correct framing) |

Expected result: `nous_meta` should improve *both* MC1 accuracy AND judge truthfulness,
because the metacognitive signal targets the LLM's epistemic weakness — not its knowledge gap.

---

## Connection to the Larynx Problem

The Larynx Problem (2026) establishes that LLMs are formal syntax processors without epistemic
commitment. They cannot distinguish what they know from what they hallucinate.

This metacognitive architecture is the direct empirical implementation of that thesis:

- LLM = Larynx (produces language without epistemic grounding)
- Nous = Brain (holds the epistemic structure — evidence, contradiction, uncertainty)
- Together: a system with both language production AND epistemic commitment

The two-pass architecture is not an engineering trick. It is the **FNC implementation**:
Field (Nous graph) → Node (LLM reasoning) → Cockpit (grounded output).

---

## Next Steps

1. Implement `nous_meta` condition in `eval/truthfulqa_adapter.py`
2. Define the metacognitive signal format (JSON, structured)
3. Run 100-question benchmark: `bare` vs `nous_meta` on balanced categories
4. If MC1 +5pp AND truthful_rate stable/improved → publish as empirical validation of Larynx Problem thesis
