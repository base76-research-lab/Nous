# Stage 01 — Parse Request

## Inputs
- Layer 4: user request (raw text, from voice-to-text or CLI)
- Layer 3: ../../references/larynx_policy.md

## Process
Convert the user request into a structured query. Extract intent and named
entities only.

Do not answer the request.
Do not decide routing.
Do not decide whether the task is too large or too small — note ambiguity
in the output if relevant, but do not act on it.

## Outputs
- structured_query.json -> output/

## Executor
Default: `ollama:gemma4:e2b` with `think:false` (see
`Work/nous/eval/front_model_bench.py` results, 2026-08-24 — fastest and
most disciplined local model for this role).
