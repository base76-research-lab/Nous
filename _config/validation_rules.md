# Validation rules (stage 03)

Checked in order, first failure wins:

1. **Policy overlay present** — `NOUSE_AGENT_POLICY_DIR` must point to a
   readable directory. If not: `POLICY_UNAVAILABLE`, fail closed.
2. **Agent match exists** — `routing_decision.json.agent_id` must be
   non-empty. If not: `ROUTE_NOT_FOUND`.
3. **Workspace bound** — the proposed `allowed_write_roots`/
   `allowed_exec_roots` must be a subset of the matched agent's own
   `works_where` declaration. If wider: `FORBIDDEN_ACTION`.
4. **Policy hard rules** — every hard rule file in the policy overlay is
   evaluated against the routing decision's text/paths/executor. A hard
   rule firing always overrides the routing proposal's executor choice
   rather than simply blocking it, unless the hard rule itself declares
   no safe fallback exists.
5. **Executor reachability** — not checked here (that is an interface
   concern for stage 04); this stage only validates structure, not
   availability.
