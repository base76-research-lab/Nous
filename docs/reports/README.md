# Technical reports

Numbered, dated, 1-3 pages, tied to a commit SHA, with a status field
(`draft` / `stable` / `superseded`). Written once a result or design decision
is substantial enough to document properly — not every log entry needs one.

Naming convention: `REPORT-NNN-short-slug.md`.

- [`2026-04-intent-disambiguation-pilot.md`](2026-04-intent-disambiguation-pilot.md)
  — historical pilot, incomplete provenance, moved here 2026-08-25 from a
  wiki page that presented it as confident headline evidence.

Two natural next candidates, per the current evidence ledger
([`../../eval/RESULTS_INDEX.md`](../../eval/RESULTS_INDEX.md)):

1. The LongMemEval task-shape diagnosis (why the relation vocabulary doesn't
   represent atomic personal facts, and what that bounds).
2. An evidence-scoring semantics report — the `confidence` value is explicitly
   documented as uncalibrated (see
   [`../EVIDENCE_MODEL.md`](../EVIDENCE_MODEL.md)); measuring the actual
   calibration is a natural next experiment.
