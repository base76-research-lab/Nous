# ICM Agents — Larynx Workspace

## Purpose

This repository implements an ICM (Interpretable Context Methodology)
pipeline for Larynx-compatible agent workflows. It generalizes the
bisociation-query pipeline described in the ICM/Larynx compatibility report
to broader agent tasks: conversational front-end, routine local commands,
and delegated escalation of large work to a stronger orchestrator.

## Core Rule

The LLM is a language interface only.

It parses requests and verbalizes validated results. It does not decide
routing, does not decide whether a request is valid, and does not decide
whether a task is small enough to handle itself. Those are structural
decisions made by code (`stages/02_engine_query`, `stages/03_structural_validation`),
not by the model.

Nous is the structural substrate: its knowledge graph, kernel memory, and
capability router are the source of truth for what the system knows and
can do — not the model's own claims.

## Stage Routing

- Request parsing: `stages/01_parse_request`
- Routing + grounding: `stages/02_engine_query`
- Structural validation: `stages/03_structural_validation`
- Execution + generation: `stages/04_execution_and_generation`
- Audit: `stages/05_audit`

## Nous Authority

No routing decision, tool invocation, or executor assignment may be
finalized unless it has passed `03_structural_validation`. No structural
claim about system state (files, capabilities, memory) may be generated
unless it is present in a Nous kernel response artifact.

## Forbidden Behavior

- Do not let the front model choose its own executor.
- Do not let the front model decide a task is "too big" or "too small" —
  it may only note this in its output for the router to act on.
- Do not skip `03_structural_validation` for any executor, including local
  ones.
- Do not treat an interface failure (rate limit, quota, timeout) as a
  structural result.
- Do not merge interface logs and structural logs.

## Private Policy Overlay

This repository is generic and public. Deployment-specific hard rules
(what must stay local, which workspace roots are writable, which MCP tools
an agent may use) are NOT defined here — they live in an external policy
file the pipeline reads at runtime (path set via `NOUSE_AGENT_POLICY_DIR`).
`03_structural_validation` fails closed if that policy directory is unset
or unreadable: no policy means no execution beyond the front-model parse
step.

## Tool Unavailable

If a required executor (Ollama, a relay session, a cloud provider) cannot
be reached, respond: `TOOL_UNAVAILABLE`. Do not generate a speculative
answer in its place.

## Error Separation

Interface errors and structural errors must remain separate — see
`_config/error_codes.md`.

## Logging

Every run must produce:
- `logs/llm/*.json`
- `logs/nous/*.json`
