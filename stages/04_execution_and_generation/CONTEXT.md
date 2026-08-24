# Stage 04 — Execution and Generation

## Inputs
- Layer 4: ../02_engine_query/output/routing_decision.json
- Layer 4: ../03_structural_validation/output/validation_report.json
- Layer 3: ../../references/larynx_policy.md

## Process
If `validation_report.json` has `generation_allowed=false`, return the
structural error exactly and stop. Do not attempt a fallback answer.

Otherwise dispatch per the validated executor:
- Local executor (`ollama:*`) — call directly via `ollama_client`, generate
  the answer synchronously.
- Escalated executor (`relay:claude` / `relay:codex`) — open a
  `nouse relay` session with the task, respond immediately with a short
  acknowledgement, and let a later poll deliver the final answer. Never
  block Jarvis's reply on the escalated work finishing.

Do not add capabilities, tool results, or claims that are not present in
the validated routing/execution artifacts.

## Outputs
- final_answer.md -> output/
- (escalated path) relay session id logged for later polling
