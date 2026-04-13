---
title: "Limbic System and SemanticModulation"
subtitle: "Arousal-Driven Cognitive State Classification (Fas 2.5)"
author: "Björn Wikström"
date: "2026-04-11"
abstract: |
  This note documents the Limbic subsystem and SemanticModulation module introduced in Fas 2.5, which classify the agent's internal physiological state and modulate LLM system prompts accordingly. The limbic layer provides arousal, resource, and drive-balance signals that map to discrete cognitive states, each carrying a distinct behavioral bias injected into the Larynx prompt. This mechanism was a necessary precursor to the Intrinsic Drive Engine: limbic modulation supplies the "feeling" that later drives converted into directed "wants," but by itself it adjusts tone without setting goals.
---

# Limbic System and SemanticModulation

**Arousal-Driven Cognitive State Classification (Fas 2.5)**

Björn Wikström\
Base76 Research Lab

*11 April 2026*

---

## 1. Biological Analogy

In vertebrate brains the limbic system — amygdala, hypothalamus, hippocampal formation — regulates arousal, homeostatic drives, and the valence of internal states. It does not plan or deliberate; it biases. High arousal sharpens attention and narrows the behavioral repertoire; low arousal opens it. Resource depletion shifts the organism toward conservative, energy-saving regimes.

The Nous LimbicState model mirrors this three-axis structure:

- **Arousal** — activation level, analogous to sympathetic tone
- **Resource level** — available computational/attentional budget, analogous to metabolic reserves
- **Drive balance** — relative strength of competing internal drives, analogous to homeostatic set-points

The analogy is deliberately coarse. Nous is not a biological simulation; the limbic layer exists to give the LLM substrate a principled, state-dependent behavioral bias rather than a static persona.

## 2. SemanticModulation Design

SemanticModulation is the bridge from LimbicState to LLM behavior. Given a classified cognitive state, it rewrites portions of the Larynx system prompt to shift the LLM's conversational posture:

| Cognitive State | Prompt Modulation |
|---|---|
| Focused (high arousal, adequate energy) | Prioritize precision, cite sources, suppress digression |
| Exploring (low arousal, adequate energy) | Encourage breadth, tolerate ambiguity, propose alternatives |
| Conserving (any arousal, low energy) | Raise response thresholds, favor minimal output, defer non-urgent work |
| Stressed (high arousal, low energy) | Constrain scope, flag overload, request human guidance |

The modulation is additive: it prepends or appends directive fragments to the base system prompt rather than replacing it. This preserves the LLM's baseline capabilities while biasing its output style.

## 3. Cognitive State Classifier

The classifier maps the continuous (arousal, energy) space into discrete states using threshold boundaries:

- **Focused**: arousal > 0.7, energy > 0.4
- **Exploring**: arousal < 0.3, energy > 0.4
- **Conserving**: energy < 0.4, arousal < 0.7
- **Stressed**: arousal > 0.7, energy < 0.4

These thresholds are empirical defaults, not theoretically derived. Future work should validate them against behavioral outcomes in FNC-Bench evaluations.

## 4. Precursor to the Drive Engine

Fas 2.5 sits between infrastructure hardening (Fas 2.0, including the SQLite migration in c2e298d) and full autonomy (Fas 3.0). The limbic layer supplies *valenced state* — how the system "feels" — but not *directed intent* — what the system "wants." Commit 5937285 established the physiological signal pipeline; the Intrinsic Drive Engine (documented separately, 2026-04-13) consumes those signals and couples them to goal selection.

Without the limbic layer, drives would operate on raw signals without the smoothing and classification that make them behaviorally useful.

## 5. Limitations

The central limitation is **modulation without direction**. SemanticModulation can make the LLM sound focused or cautious, but it cannot decide *what* to focus on or *why* caution is warranted. The limbic layer adjusts tone; it does not set goals.

A second limitation is the hard-coded classifier thresholds, which lack adaptive calibration. Third, the current model treats arousal and energy as scalar globals rather than domain-specific variables, collapsing distinctions that biological systems maintain across modalities.

These gaps are acknowledged and addressed by the Drive Engine (Fas 3.0).

*Commit: 5937285 — feat(limbic): add SemanticModulation and cognitive state classifier (Fas 2.5)*