# Stage 05 — Audit

## Inputs
- Layer 4: all previous stage outputs
- Layer 3: ../../_config/error_codes.md

## Process
Create separate logs for LLM interface behavior and Nous/executor
behavior. Do not merge structural errors with interface errors.

Also write the outcome back into Nous's own memory via
`kernel_log_outcome`/`kernel_write_episode`, so the interaction is
available to Nous's own cognitive cycle, not just as a file on disk.

## Outputs
- logs/llm/<run_id>.json
- logs/nous/<run_id>.json
