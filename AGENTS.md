# AGENTS.md — Nous

Instructions for any AI agent/tool working in this repo (Claude Code, Codex,
or others). Claude Code-specific details (hooks, skills) are in `CLAUDE.md`
— read that too if you are Claude Code.

## Read first

**`STATUS.md`** — the single "where are we" file, updated every session.
Read it before doing anything else. On conflict with `ROADMAP.md` (archived,
see `docs/archive/`), `docs/NOUS_NEXT_GENERATION_PLAN.md`, or
`docs/handoffs/*`: STATUS.md wins — the other files are history/vision, not
current state.

## Before ending a session in this repo

1. If you changed anything: update `STATUS.md` — what happened, why, what's
   next. Be specific about results (numbers, filenames), not just "worked on X".
2. Commit the changes. If you deliberately leave them uncommitted, write why
   in `STATUS.md` so the next session doesn't have to guess.
3. Never leave a benchmark/experiment result both uncommitted and
   undocumented at the same time — that's exactly what happened on the night
   of 2026-08-23 and took a whole session to reconstruct (git diff, sqlite
   inspection, journal logs).

## "Free hands" never covers actions against the live daemon

Björn can grant free hands to build and make technical decisions
independently — that covers code, tests, documentation, anything that can be
committed and reviewed afterward. It NEVER covers daemon restarts,
migrations against the production graph, or changes to systemd units — those
always require an explicit "kör" (go) in the session. Document pending
actions of that kind as a checklist in STATUS.md's "Planned actions" section
(what / why / risk / verification steps / status) instead of running them, so
build work isn't blocked but the action stays visible and reviewable.

## Never touch the production graph from eval/test code

A daemon (`nouse daemon web --port 8767`) may be running as a long-lived
background process against `~/.local/share/nouse/field.sqlite`. All one-off
code (eval, benchmark, manual testing) must use an isolated `FieldSurface` at
a temp path — see `eval/longmemeval_adapter.py`.

## Environment variables

`.env` in the repo root has API keys but isn't loaded automatically by
`eval/run_eval.py` (no dotenv). Run `set -a && source .env && set +a`
manually before using cloud models.

`NOUSE_EXTRACT_MODEL` defaults to an Ollama model that isn't installed
(`deepseek-r1:1.5b`, 404 verified 2026-08-24). Set it explicitly
(`gemma4:e2b` works) in standalone scripts, otherwise extraction fails
silently.
