# Error codes

## Interface errors (produced by the LLM/client/executor layer)

- `TOOL_UNAVAILABLE` — a required executor could not be reached.
- `LLM_RATE_LIMITED`
- `LLM_QUOTA_EXCEEDED`
- `LLM_TIMEOUT`
- `INVALID_QUERY_FORMAT`
- `MISSING_STAGE_ARTIFACT`

## Structural errors (produced by stage 02/03 validation)

- `ROUTE_NOT_FOUND` — no agent card matched the classified intent.
- `FORBIDDEN_ACTION` — the matched agent's own `forbidden` list was
  violated by the proposed routing.
- `RESEARCH_LOCAL_VIOLATION` — deployment policy overlay forced a local
  executor and the routing proposal targeted a cloud executor instead.
  (Rule name matches the policy overlay's own hard-rule naming; this repo
  defines the code path, the overlay defines when it fires.)
- `POLICY_UNAVAILABLE` — no policy overlay configured; fail closed.

## Handling rules

| Error type | Allowed behavior |
|---|---|
| Interface error | Report the failure. Do not generate a result in its place. |
| Structural error | Report the failure. Do not invent an alternative route or answer. |
| Valid result | Verbalize only the validated result. |

A quota/rate-limit failure must never be interpreted as a structural
result, and vice versa.
