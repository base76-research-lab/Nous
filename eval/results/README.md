# eval/results/

Raw run outputs (`<benchmark>_<timestamp>.json`), the durable record of what
actually happened. Not a claim of evidence by itself -- see
[`../RESULTS_INDEX.md`](../RESULTS_INDEX.md) for which runs are complete,
auditable, and reviewed enough to cite.

- `failed/` -- runs that hit an infrastructure problem mid-run (rate limits,
  a scoring model returning think-tokens instead of answers, etc.), kept for
  audit trail, not results.
- `archive/` -- superseded artifacts from earlier architecture versions,
  kept for history, not current status.

Convention going forward: `<benchmark>_<YYYYMMDD_HHMMSS>.json`, one file per
run, never overwritten. A run only becomes a citable claim once it has a
manually reviewed line in `RESULTS_INDEX.md`.
