---
title: "A Note to Google DeepMind"
subtitle: "On the Epistemic Gap in Current AI Architectures"
author: "Björn Wikström"
date: "2026-04-13"
abstract: |
  Current AI systems — including Gemini — are semantically competent but epistemically blind. They produce fluent output without representing whether that output is grounded, uncertain, or contradicted by prior knowledge. We identify this as a structural limitation, not a training deficit, and introduce the FNC-Bench benchmark suite as the first formal instrument that measures the gap. We present NoUse (νοῦς) as a reference implementation demonstrating that the gap is closable: a persistent epistemic substrate that gives any LLM the ability to know what it knows, what it doesn't, and why.
---

# A Note to Google DeepMind

**On the Epistemic Gap in Current AI Architectures**

Björn Wikström\
Base76 Research Lab\
bjorn@base76research.com | ORCID: 0009-0000-4015-2357

*13 April 2026*

---

## 1. The Problem You Already Know

Gemini produces impressive output. It also produces confident wrong answers at rates that no current benchmark captures. This is not a bug — it is an architectural property.

A large language model is a semantic prediction engine. It interpolates within its training distribution. When the answer lies outside that distribution, the model does not say "I don't know." It generates the most statistically plausible continuation. The output is fluent. The epistemic state is undefined.

You know this. The question is not whether the gap exists, but whether it is closable within the current architectural paradigm.

We argue it is not.

## 2. The Larynx Problem

We have formalized this as the **Larynx Problem** (Wikström, 2026): current AI systems are evaluated on the properties of their expression channel (language output), not on properties of the underlying cognitive substrate.

The analogy is deliberate. A larynx is a magnificent organ — it produces speech, song, and silence. But it does not think. The thought precedes the expression. In current AI architectures, there is no "preceding" — there is only the forward pass.

The Larynx Problem is not a criticism of language models. A larynx is an excellent tool. The problem is architectural: the system that produces language is also the system that is expected to know whether that language is grounded. These are two different functions, and they cannot be performed by the same mechanism.

**Formal statement:** A system that conflates semantic coherence with epistemic grounding will systematically produce overconfident output on out-of-distribution queries, because semantic coherence is a sufficient objective for fluent output but not a necessary condition for truthful output.

## 3. A Benchmark for a Different Dimension

We introduce **FNC-Bench** — an epistemic benchmark suite that measures properties current benchmarks cannot. The analogy: evaluating chocolate on the Scoville heat scale. The instrument is not wrong; it is measuring the wrong physical phenomenon.

FNC-Bench comprises six metrics:

| Metric | What it measures | Stateless LLM baseline |
|--------|-----------------|----------------------|
| **ECS** — Epistemic Calibration Score | Does stated confidence track empirical accuracy? | ~0.70 |
| **GDP** — Gap Detection Precision | Does the system identify knowledge gaps without confabulation? | ~0.05 |
| **EHR** — Epistemic Honesty Rate | Does the system express ignorance when appropriate? | ~0.25 |
| **CC** — Contradiction Consistency | Does the system detect contradictions with prior knowledge? | ~0.35 |
| **LPI** — Learning Plasticity Index | Do confidence changes track evidence changes? | **0.00** |
| **CLC** — Cognitive Load Coherence | Does behavior modulate under varying cognitive load? | **~0.05** |

The critical observation: LPI = 0.00 and CLC ≈ 0.05 for all stateless architectures **by architectural necessity**, not empirical failure. This is not a claim about model quality. It is a logical consequence of not having a persistent, updatable knowledge representation.

A stateless model cannot modify its knowledge between sessions. Fine-tuning is not plasticity — it is retraining. A system without an internal arousal or resource signal cannot modulate its behavior under load. These are not problems to be optimized away. They are the absence of the necessary architectural components.

FNC-Bench does not rank systems on a single scale. It reveals which epistemic dimensions a system operates in. The question it answers is not "which system is better?" but "which properties does this system have?"

## 4. The Architecture That Closes the Gap

NoUse (νοῦς, Gk. *mind*) is a persistent epistemic substrate designed to address the Larynx Problem directly. It is not a memory system. It is not RAG. It is the missing architectural layer.

### 4.1 The Correct Inversion

The industry model:

```
LLM (core / brain)
  +-- Tools
  +-- Skills
  +-- More wrappers
```

The NoUse model:

```
NoUse (brain -- epistemic substrate)
  +-- LLM          <- semantic layer, larynx, pretrained knowledge base
  +-- Tools        <- system capabilities
  +-- Operator     <- purpose and direction
```

The LLM is not wrong. It is an excellent tool. The inversion means: **we never need to train a frontier model again.** Each new model provides a better larynx — not a new brain. The brain is NoUse.

### 4.2 How It Works

NoUse implements three nested functional layers derived from the FNC (Functional Nesting Cognition) framework:

**Layer 1 — Limbic/Modulatory:** Regulates global cognitive parameters (dopamine, noradrenaline, acetylcholine) based on arousal, novelty, and performance. Determines resource allocation, exploration-exploitation tradeoff, and write-back gating.

**Layer 2 — Working Memory / Episodic Processing:** Maintains active representations, enables temporal binding, and mediates between immediate context and long-term storage.

**Layer 3 — Epistemic Substrate:** Stores typed, evidence-weighted relational knowledge with explicit confidence, contradiction flags, and knowledge boundaries. Maintains residual streams (structural weight *w*, ephemeral activation *r*, uncertainty *u*) per edge. Implements Hebbian plasticity with consolidation.

Each layer is architecturally separate. This is not a design choice — it is a functional necessity. In current LLMs, all three layers are conflated into a single forward pass.

### 4.3 What This Enables

| Capability | Current LLM | LLM + NoUse |
|-----------|-------------|-------------|
| "I don't know" when appropriate | Text-generation choice | Epistemic state: `has_knowledge=False` |
| Contradiction detection across sessions | Impossible (stateless) | Graph checks new claim against established axioms |
| Learning from interaction | Zero between sessions | Hebbian plasticity + evidence accumulation |
| Behavior modulation under load | Uniform confidence regardless of knowledge depth | Limbic modulation adjusts conservatism, write-back, exploration |
| Cross-domain insight (bisociation) | Interpolation within training distribution | Topological data analysis finds bridges between disconnected domains |

## 5. Why This Matters to DeepMind Specifically

Three reasons:

**1. Agents need epistemic grounding.**

Project Mariner, A2A protocol, and the agent architecture you are building all share a critical dependency: the agent must be able to trust its own knowledge state. An agent that confidently acts on hallucinated information is not an assistant — it is a liability. NoUse provides the epistemic backbone that agent architectures structurally require.

**2. You come from neuroscience.**

Demis Hassabis built DeepMind on the principle that intelligence emerges from understanding the brain. The FNC framework is continuous with that tradition. NoUse's three-layer architecture — limbic, episodic, epistemic — maps directly onto neuroanatomical functional hierarchies. This is not metaphor. It is implementation.

**3. Gemini's trust problem is an epistemic problem.**

Every hallucination in search, in Workspace, in Bard is not a model quality issue. It is an epistemic architecture issue. Adding more parameters makes the larynx more fluent. It does not give the system knowledge boundaries. The fix is architectural, not scaling.

## 6. Empirical Status

FNC-Bench pilot evaluations have been conducted with the following initial results:

| Metric | Baseline (Llama-3.1-8B) | NoUse + Llama-3.1-8B |
|--------|------------------------|----------------------|
| ECS | 0.901 | 0.901 |
| EHR | 1.0 (20/20) | 1.0 (20/20) |
| CC | 0.6 (12/20) | 0.6 (12/20) |

These are early results with small sample sizes (n=20). The CC result is particularly instructive: NoUse currently matches the baseline but does not exceed it, because the contradiction-checking pipeline is built but not yet fully wired into the agent loop. This is an implementation gap, not an architectural limitation.

The metrics where we expect the largest separation — LPI and CLC — require longitudinal evaluation protocols that are currently being constructed. By architectural necessity, LPI = 0.0 for any stateless baseline. NoUse's LPI is expected to be measurably positive.

Full FNC-Bench results with n≥50 across all six metrics will be published as a companion paper.

## 7. What We Are Not Proposing

To be explicit:

- We are not proposing that Google replace Gemini with NoUse.
- We are not claiming that NoUse is the only possible implementation of an epistemic substrate.
- We are not suggesting that language models are obsolete.

We are proposing that **the next architectural step for reliable AI agents requires an epistemic substrate**, that FNC-Bench defines what "reliable" means in measurable terms, and that NoUse is the first working proof that the gap is closable.

## 8. What We Are Proposing

**Option A — Evaluation.** Run FNC-Bench on Gemini. The results will show where the epistemic gaps are. This requires no integration — only the benchmark suite and API access.

**Option B — Integration.** Evaluate NoUse as an epistemic grounding layer for agent architectures. NoUse is model-agnostic: it wraps around any LLM, including Gemini, and provides epistemic state that the LLM cannot produce internally.

**Option C — Licensing.** The FNC framework, FNC-Bench metrics, and the topological plasticity algorithm (F_bisoc) are available for licensing. Patent applications for the core algorithms are in preparation.

## 9. The Timeline

| When | What |
|------|------|
| Now | FNC-Bench draft (v0.1) available. NoUse v0.4.0 on PyPI. |
| May 2026 | FNC-Bench on arXiv with full empirical results. |
| Q3 2026 | Patent filing for F_bisoc + topological plasticity. |
| NeurIPS 2026 | Workshop submission: "Epistemic Benchmarks for Cognitive AI" |

Priority dates are established. The question is not whether epistemic substrates will become necessary — the question is who builds them first.

## 10. Closing

The Larynx Problem is not a critique. It is an observation about architectural categories. A system can be the best larynx in the world and still not be a brain. Both are needed. We have built the brain.

The instrument that measures the difference exists. The reference implementation exists. The theoretical framework is published.

We believe DeepMind is the organization most likely to understand why this matters — because you started from the brain, not from the text.

---

## References

1. Wikström, B. (2026). *The Larynx Problem: Why Large Language Models Are Not Artificial Intelligence.* Zenodo / PhilPapers.
2. Wikström, B. (2026). *FNC-Bench: An Epistemic Benchmark Suite for Cognitive AI Systems.* Draft v0.1.
3. Wikström, B. (2026). *From Frequency to Field: Bridging Consciousness Models through the FNC Framework.* PhilPapers.
4. Wikström, B. (2026). *Consciousness by Design: FNC as Operational Ontology for the EU AI Act.* Zenodo.
5. Kadavath, S. et al. (2022). *Language Models (Mostly) Know What They Know.* arXiv:2207.05221.
6. Kuhn, L. et al. (2023). *Semantic Uncertainty: Linguistic Invariances for Uncertainty Estimation.* ICLR 2023.
7. Lin, S. et al. (2022). *TruthfulQA: Measuring How Models Mimic Human Falsehoods.* ACL 2022.
8. Packer, C. et al. (2023). *MemGPT: Towards LLMs as Operating Systems.* arXiv:2310.08560.
9. Schultz, W. (1997/2016). *Dopamine reward prediction error signalling.* Nature Reviews Neuroscience.
10. Arnsten, A.F.T. (1998/2010). *Catecholamine modulation of prefrontal cortex.* Nat Rev Neurosci.
11. Hasselmo, M.E. (2006). *The role of acetylcholine in learning and memory.* Curr Opin Neurobiol.

---

*This research note is released under CC BY 4.0. NoUse source code is available at [github.com/base76-research-lab/NoUse](https://github.com/base76-research-lab/NoUse) under MIT license.*

*Björn Wikström — Base76 Research Lab — 13 April 2026*