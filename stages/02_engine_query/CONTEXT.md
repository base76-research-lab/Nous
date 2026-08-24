# Stage 02 — Engine Query

## Inputs
- Layer 4: ../01_parse_request/output/structured_query.json
- Layer 3: ../../_config/executor_registry.md
- External: agent-card folders under `NOUSE_AGENT_POLICY_DIR` (private,
  deployment-specific — not present in this repo)

## Process
Pure code, no LLM decision.

1. Classify intent via `nouse.capability.graph.build_route_plan()`.
2. Match the classified skill against each agent card's `match` list.
3. If an agent matches, pull grounding context from the Nous kernel
   (`kernel_get_working_context` / `kernel_retrieve_memory`) if the card
   requests it.
4. Produce a routing decision naming: matched agent, proposed executor,
   proposed allowed workspace, proposed forbidden actions.

Do not execute anything yet. Do not finalize the decision — that is
stage 03's job.

## Outputs
- routing_decision.json -> output/
