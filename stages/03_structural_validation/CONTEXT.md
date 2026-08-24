# Stage 03 — Structural Validation

## Inputs
- Layer 4: ../02_engine_query/output/routing_decision.json
- Layer 3: ../../_config/validation_rules.md
- External: the matched agent's own AGENT.md (`forbidden`, `works_where`)
- External: the deployment's policy overlay (`NOUSE_AGENT_POLICY_DIR`),
  hard rules that override any routing proposal

## Process
This stage must be rule-based. Do not use the LLM to decide structural
validity.

1. Fail closed if no policy overlay is configured — no policy, no
   execution beyond stage 01.
2. Check the proposed executor and workspace against the matched agent's
   own `forbidden`/`works_where`.
3. Check the proposed executor against every hard rule in the policy
   overlay (e.g. a rule forcing certain content to a local-only executor
   regardless of what stage 02 proposed). A hard rule always wins over the
   routing proposal.
4. If any check fails: `generation_allowed: false` with the matching
   structural error code from `_config/error_codes.md`.

## Outputs
- validation_report.json -> output/
