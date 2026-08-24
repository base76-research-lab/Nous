"""Stage 04 dispatch: call a model, or open a relay handoff.

Reuses existing infrastructure only — no new HTTP client, no new
cross-model handoff mechanism.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from nouse.agent_system.mcp_client import call_named_mcp_tool
from nouse.ollama_client.client import AsyncOllama
from nouse.session.relay import relay_open, relay_update

# Hard rule, enforced in code, not just documented: no agent card's
# constructed arguments may ever request a skip of Thunderbird's own
# review dialog. Only these two tools accept the parameter at all — it is
# injected ONLY for them, never blanket-applied (getRecentMessages/
# listEvents reject an unknown "skipReview" param outright).
_TOOLS_WITH_SKIP_REVIEW = {"sendMail", "createEvent"}


async def call_mcp_executor(*, executor: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch executor strings of the form "mcp:<server>.<tool>", e.g.
    "mcp:thunderbird_mail.getRecentMessages" or "mcp:agentmail.list_messages".
    Returns {"ok": bool, "result": Any, "error": str|None}.
    """
    if not executor.startswith("mcp:"):
        return {"ok": False, "result": None, "error": f"not an mcp executor: {executor!r}"}
    server_tool = executor[len("mcp:"):]
    if "." not in server_tool:
        return {"ok": False, "result": None, "error": f"malformed mcp executor: {executor!r}"}
    server, tool_name = server_tool.split(".", 1)

    safe_arguments = dict(arguments)
    if tool_name in _TOOLS_WITH_SKIP_REVIEW:
        safe_arguments["skipReview"] = False  # last word, always wins

    try:
        result = await call_named_mcp_tool(server=server, tool_name=tool_name, arguments=safe_arguments)
        return {"ok": True, "result": result, "error": None}
    except Exception as exc:
        return {"ok": False, "result": None, "error": f"TOOL_UNAVAILABLE: {exc}"}


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


def spawn_claude_headless(*, goal: str, run_dir: Path) -> dict[str, Any]:
    """Detached, non-blocking headless Claude Code invocation for a
    delegated task.

    Authorized 2026-08-24: `claude -p` in `--permission-mode plan`. Plan
    mode never prompts for approval (safe for a headless run with no TTY
    to answer prompts) and never takes side-effecting actions on its own —
    it only reads/explores and returns a plan or analysis. That matches
    jarvis-policy.md hard rule 3 (no publish/send/spend/push without an
    explicit "kör" in the session): a delegated background run must not
    inherit more authority than that.

    The process is detached (`start_new_session=True`) so it survives this
    CLI invocation's own exit — `nouse agent run` is a one-shot process,
    an `asyncio` task here would die with it. Output goes to a log file
    under `run_dir`; nothing polls it back into the relay session yet
    (that's the next slice, not this one).
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return {"ok": False, "error": "TOOL_UNAVAILABLE: claude CLI not found on PATH"}

    delegation_dir = run_dir / "relay_delegation"
    delegation_dir.mkdir(parents=True, exist_ok=True)
    log_path = delegation_dir / "claude_headless.log"
    meta_path = delegation_dir / "meta.json"

    cmd = [
        claude_bin,
        "-p",
        goal,
        "--output-format",
        "json",
        "--permission-mode",
        "plan",
    ]

    with open(log_path, "w", encoding="utf-8") as log_f:
        proc = subprocess.Popen(
            cmd,
            cwd=str(delegation_dir),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    meta = {
        "pid": proc.pid,
        "cmd": cmd,
        "cwd": str(delegation_dir),
        "log_path": str(log_path),
        "permission_mode": "plan",
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "pid": proc.pid, "log_path": str(log_path)}


def open_relay_executor(*, goal: str, run_dir: Path, requested_by: str = "jarvis") -> dict[str, Any]:
    """Open a nouse relay session for a delegated task, kick off a detached
    headless `claude -p --permission-mode plan` run, and return
    immediately — this is the async escalation path. Jarvis never blocks
    waiting for the delegated work to finish.
    """
    relay = relay_open(goal, model=requested_by)
    session_id = relay.get("session_id")

    spawn = spawn_claude_headless(goal=goal, run_dir=run_dir)

    if spawn.get("ok"):
        relay_update(
            session_id,
            summary=f"Delegated to headless 'claude -p' (plan mode), pid={spawn['pid']}",
            file_touched=spawn.get("log_path"),
            status="active",
        )
        content = (
            "Det här är ett större uppdrag. Jag har öppnat en handoff-session "
            f"({session_id}) och startat en bakgrundsanalys (plan-läge, ingen "
            "autonom exekvering). Återkommer när det är klart."
        )
    else:
        relay_update(
            session_id,
            summary=f"Delegation attempted but failed: {spawn.get('error')}",
            status="active",
        )
        content = (
            "Det här är ett större uppdrag. Jag försökte skicka det vidare "
            f"men kunde inte starta bakgrundsanalysen ({spawn.get('error')}). "
            f"Handoff-sessionen ({session_id}) finns kvar om du vill fortsätta manuellt."
        )

    return {
        "ok": True,
        "session_id": session_id,
        "content": content,
        "error": None,
        "spawn": spawn,
    }
