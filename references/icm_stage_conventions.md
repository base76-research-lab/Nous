# ICM stage conventions

- Numbered stage folders under `stages/` run in order: 01 -> 02 -> 03 -> 04
  -> 05. Each stage reads only what its own `CONTEXT.md` names as Inputs.
- Every stage writes its outputs to disk (`output/` under the stage
  folder, or `logs/` for stage 05) so a run is resumable: if a later stage
  fails or a client's quota runs out mid-run, only that stage needs to be
  rerun, not the whole pipeline.
- Reusable, stable material (error codes, validation rules, executor
  registry, the Larynx policy itself) lives in `_config/`/`references/` —
  edited rarely, shared across every run.
- Run-specific artifacts are not committed to this repo's `stages/*/output/`
  by default — they are working state, regenerated per run. Only the
  stage contracts (`CONTEXT.md` files) and the stable config/reference
  material are source-controlled.
- Renaming or reordering a stage is a filesystem edit, not a code change —
  the pipeline (`src/nouse/agent_system/pipeline.py`) reads the stage list
  from the `stages/` directory rather than hardcoding stage names.
