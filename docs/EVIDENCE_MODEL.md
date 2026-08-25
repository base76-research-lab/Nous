# Evidence model — what "confidence" actually means

Added 2026-08-25, following a repo validation that pointed out `confidence`
and `evidence_score` were conflating several distinct signals under one
name. This document defines the terms the code now keeps separate, and
where each one lives.

## The five signals

| Term | What it measures | Where |
| --- | --- | --- |
| `source_support` | A relation's explicitly given `evidence_score` — set by a caller who actually had a source. `None` when no source was given. | `Axiom.source_support`, `relation.evidence_score` column |
| `extraction_confidence` | The relation extractor's own per-relation confidence when parsing free text into structured relations. Feeds into `evidence_score` at write time when present; not yet surfaced as its own field. | `daemon/extractor.py` |
| `retrieval_salience` | How much of the requested `top_k` a query actually matched — a coverage ratio, not an evidence judgment. | `/api/context` response field `retrieval_salience` (`web/server.py`) |
| `hebbian_strength` | Raw traversal-based strength — how often/recently a relation has been accessed. Independent of whether the relation is *true*. | `Axiom.strength`, `relation.strength` / `strength_fast` columns |
| `epistemic_confidence` | The aggregate score returned as `QueryResult.confidence` — mean evidence across "strong" axioms (evidence ≥ 0.75, not flagged). This is the one number most external callers see. | `QueryResult.confidence` |

`QueryResult.confidence_breakdown` decomposes `epistemic_confidence` into:
`source_backed_fraction`, `mean_source_support`, `mean_hebbian_strength`, and
`parametric_hypothesis_fraction` — see below.

## Why `evidence` and `confidence` stay as single numbers

Both fields predate this document and are part of the public API
(`NouseBrain.query()`, HTTP `/api/brain/query`, MCP tool output, SaaS API).
They are not being removed or renamed — that would break every existing
caller for a naming change alone. Instead, the fields above are additive:
`evidence` is still whatever it always was (source_support if present,
otherwise a Hebbian-derived estimate), and the new fields let a caller who
cares tell the two cases apart instead of trusting a number that might be
either.

## Parametric hypotheses — the domain_bootstrap circularity

`NouseBrain.domain_bootstrap()` asks an LLM to describe a topic from its own
parametric knowledge, then stores the result as graph relations. Read back
later, those relations look exactly like any other graph content — the
risk a reviewer flagged: *LLM says X → Nous stores X → Nous returns X to
the LLM (or to Björn) as if it were grounded knowledge*.

Two mechanisms now prevent that from being silent:

1. **Provenance travels with the relation, not the concept.** `source_tag`
   is stored on the `relation` row itself (migrated 2026-08-25 — it used to
   only reach `concept.source`, which is first-write-wins and therefore
   unreliable once a concept is touched by more than one source). Any
   relation written with `source_tag="domain_bootstrap"` is exposed as
   `Axiom.provenance_class = "parametric_hypothesis"`; everything else is
   `"external_source"`.
2. **A parametric hypothesis can never write itself in as "strong".**
   `FieldSurface.add_relation()` caps `evidence_score` at
   `PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING` (default `0.70`, env override
   `NOUSE_PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING`) for any
   `source_tag="domain_bootstrap"` relation, regardless of what evidence
   score the caller requested. Since `is_strong` requires `evidence >= 0.75`,
   a bootstrapped relation cannot reach "strong" through the bootstrap path
   alone — promoting it requires a separate, explicit write with a
   different `source_tag` (i.e. an actual source, or a human review step),
   not just repeated model activity.

`EscalationResult.contains_parametric_hypothesis` (in
`search/escalator.py`) surfaces the same signal at the point where context
actually gets injected into an LLM prompt: `True` whenever any axiom in the
returned context has `provenance_class == "parametric_hypothesis"`, even if
the overall query cleared the confidence threshold on other, real evidence.

## What this does not yet cover

- `extraction_confidence` (the extractor's own per-relation score) is not
  yet a distinct stored field — it is absorbed into `evidence_score` at
  write time along with everything else the caller passes in.
- `src/nouse/kernel/*` has a separate, possibly-legacy implementation of
  similar evidence/relation concepts that this pass did not touch — flagged
  in STATUS.md pending a decision on whether `kernel/` is still live.
- The ceiling on `domain_bootstrap` writes is a blunt instrument (a fixed
  number), not a calibrated one. It stops silent self-promotion; it does
  not make 0.70 a validated probability of correctness.
