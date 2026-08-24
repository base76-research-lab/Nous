"""Stage 04 dispatch: call a model, or open a relay handoff.

Reuses existing infrastructure only — no new HTTP client, no new
cross-model handoff mechanism.
"""
from __future__ import annotations

from typing import Any

from nouse.ollama_client.client import AsyncOllama
from nouse.session.relay import relay_open


async def call_model_executor(
    *, executor: str, system_prompt: str, user_text: str, executor_options: dict | None = None
) -> dict[str, Any]:
    """Call `executor` (a bare model ref, e.g. "gemma4:e2b" or
    "nvidia/nemotron-3.5-lightning-30b-a3b") via the existing multi-provider
    client. Returns {"ok": bool, "content": str, "error": str|None}.
    """
    client = AsyncOllama()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]
    kwargs = dict(executor_options or {})
    try:
        resp = await client.chat.completions.create(model=executor, messages=messages, **kwargs)
        content = getattr(resp.message, "content", "") or ""
        return {"ok": True, "content": content.strip(), "error": None}
    except Exception as exc:  # interface error, not a structural one
        return {"ok": False, "content": "", "error": f"TOOL_UNAVAILABLE: {exc}"}


def open_relay_executor(*, goal: str, requested_by: str = "jarvis") -> dict[str, Any]:
    """Open a nouse relay session for a delegated task and return
    immediately — this is the async escalation path. Does NOT spawn a
    headless Claude Code / Codex process yet (see code-delegation/AGENT.md
    "STUB" note); it only records intent so the handoff is inspectable via
    `nouse relay show <id>`.
    """
    relay = relay_open(goal, model=requested_by)
    return {
        "ok": True,
        "session_id": relay.get("session_id"),
        "content": (
            "Det här är ett större uppdrag. Jag har öppnat en handoff-session "
            f"({relay.get('session_id')}) och skickar det vidare för bearbetning "
            "istället för att försöka göra det själv. Återkommer när det är klart."
        ),
        "error": None,
        "stub_note": (
            "Headless Claude Code / Codex invocation not yet wired — "
            "session opened and logged only, per code-delegation/AGENT.md."
        ),
    }
