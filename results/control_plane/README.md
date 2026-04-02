# Conductor Control Plane

This directory is the mandatory runtime surface for communication, evidence chain, snapshots, and rollback artifacts between:
- Conductor entity (Brian/OpenClaw)
- Super Conductor (Bjorn)

## Purpose

1. Create a persistent communication channel.
2. Preserve a verifiable evidence chain for autonomous actions.
3. Guarantee rollback capability through snapshot references.
4. Keep all high-impact actions auditable and reversible.

## Structure

- channel/super_conductor_inbox.md
  - Requests, directives, and approvals from Super Conductor to Conductor.
- channel/conductor_outbox.md
  - Decisions, escalations, and status updates from Conductor.
- chains/evidence_chain.jsonl
  - Append-only event chain with link integrity fields.
- snapshots/
  - Snapshot metadata files (one file per snapshot event).
- rollback_plans/
  - Rollback plans keyed by decision id or run id.

## Mandatory Runtime Rule

For every autonomous action in Zone B or Zone C, and for every high-impact action in Zone A:
1. Write PRE snapshot metadata.
2. Execute action.
3. Write POST snapshot metadata.
4. Append evidence event to chains/evidence_chain.jsonl.
5. Ensure rollback plan exists and references PRE snapshot.

If any step is missing, action status must be set to INVALID_UNTIL_REPAIRED.
