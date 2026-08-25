# HISTORICAL PILOT — INCOMPLETE PROVENANCE — SUPERSEDED BY CURRENT EVALUATION REQUIREMENTS

**Status:** historical. Moved here 2026-08-25 from the GitHub wiki page
"Intent-Disambiguation-Effect", which presented this run as confident
headline evidence. It does not meet this repository's own reproduction
requirements (see [`../../eval/RESULTS_INDEX.md`](../../eval/RESULTS_INDEX.md)):
no immutable manifest, no dataset hash, no independent scorer behind the
numbers below. Kept for history and as a source of hypotheses to re-test
properly — not as a demonstrated result. Corresponds to ledger row
`run_20260403_094211`.

---

## The observation, as originally recorded

In an internal benchmark, an 8-billion parameter model with Nous memory
scored 96% on domain-specific questions. A 70-billion parameter model
without memory scored 47%. Same questions, same prompt format. The only
varied condition was whether structured relational context was injected.

## The hypothesis this run was exploring

```
small model + Nous[domain]  >  large model without Nous
```

Framed at the time as a "disambiguation" effect: a large model already
contains general knowledge, but lacks the specific frame to apply to a
narrow domain question (worked example at the time: a query about
`NightRun`, a software component, being answered with unrelated
neuroscience content about hippocampal replay instead of the intended
software-architecture analogy). Structured context was hypothesized to
redirect the model onto the correct frame rather than supply the answer
directly.

## Why this doesn't count as evidence today

- No commit SHA or package version was recorded alongside the run.
- No dataset hash — the question set cannot be confirmed unchanged.
- Custom keyword-based scoring, not an independent judge.
- No raw model/judge responses retained for audit.

These are exactly the fields `eval/RESULTS_INDEX.md` now requires of any
run before it can be cited publicly. This pilot predates that requirement.

## What would need to happen to re-test this properly

1. A frozen, published question set with a recorded hash.
2. LLM-judge scoring (or another independent scorer) instead of keyword
   matching, with raw judge outputs retained.
3. Multiple domains, not one.
4. Multiple model-size pairs, not one 8B/70B comparison.
5. A recorded commit SHA and isolated graph/bootstrap state.

If a future run meets these requirements and reproduces a similar effect,
it earns its own row in `eval/RESULTS_INDEX.md` and can cite this document
as the originating hypothesis. Until then, this is a historical pilot, not
a finding.
