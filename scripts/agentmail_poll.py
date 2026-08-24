#!/usr/bin/env python3
"""agentmail-poll — periodic check of nouse@agentmail.to for new mail.

Read-only by design. Fetches new unread messages since the last successful
poll, logs them into Nous's own memory (kernel_write_episode) and into a
pending-review queue file, and stops there.

Never calls send_message / reply_to_message. That boundary is not a
suggestion: Björn confirmed 2026-08-24 that every actual reply from this
inbox must go through an explicit "kör" in a session, regardless of the
precedent set 2026-08-23 (a prior session auto-approved research decisions
and replied autonomously, signed "/Claude" — that pattern is explicitly
NOT continued here). If auto-reply is ever wanted, it is a separate,
deliberate change to this script, not an implicit extension of "poll for
new mail".

State (last successful poll timestamp) persists at
NOUSE_HOME/agentmail_poll_state.json (default ~/.local/share/nouse/) so a
restart doesn't reprocess the whole inbox. First run seeds the baseline to
"now" rather than the full history — the inbox already has real
correspondence from 2026-08-23 that this script does not retroactively
surface; anything genuinely still pending (e.g. an unread message asking
for a reply) needs a human or an explicit session to notice and act on it
once, not an automated backfill.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nouse.agent_system.mcp_client import call_http_mcp_tool  # noqa: E402
from nouse.config.paths import path_from_env  # noqa: E402
from nouse.mcp_gateway.gateway import kernel_write_episode  # noqa: E402

AGENTMAIL_URL = "https://mcp.agentmail.to/mcp"
INBOX_ID = "nouse@agentmail.to"
AGENTMAIL_ENV_FILE = Path.home() / ".config" / "agentmail.env"


def _log(msg: str) -> None:
    print(f"[agentmail-poll] {msg}", flush=True)


def _load_api_key() -> str:
    env_key = os.getenv("AGENTMAIL_API_KEY", "").strip()
    if env_key:
        return env_key
    if AGENTMAIL_ENV_FILE.is_file():
        for line in AGENTMAIL_ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("AGENTMAIL_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def _state_path() -> Path:
    return path_from_env("NOUSE_AGENTMAIL_STATE_PATH", "agentmail_poll_state.json")


def _pending_queue_path() -> Path:
    return path_from_env("NOUSE_AGENTMAIL_PENDING_PATH", "agentmail_pending_review.json")


def _load_last_checked() -> str:
    p = _state_path()
    if not p.is_file():
        now = datetime.now(timezone.utc).isoformat()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"last_checked": now}), encoding="utf-8")
        _log(f"first run, seeding baseline to now ({now}) — not backfilling history")
        return now
    data = json.loads(p.read_text(encoding="utf-8"))
    return str(data.get("last_checked", ""))


def _save_last_checked(ts: str) -> None:
    _state_path().write_text(json.dumps({"last_checked": ts}), encoding="utf-8")


def _append_pending(messages: list[dict]) -> None:
    if not messages:
        return
    p = _pending_queue_path()
    existing: list[dict] = []
    if p.is_file():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = []
    seen_ids = {m.get("messageId") for m in existing}
    for m in messages:
        if m.get("messageId") not in seen_ids:
            existing.append(m)
    p.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


async def _poll_once() -> int:
    api_key = _load_api_key()
    if not api_key:
        _log("AGENTMAIL_API_KEY not found (env or ~/.config/agentmail.env) — cannot poll")
        return 1

    last_checked = _load_last_checked()
    now = datetime.now(timezone.utc).isoformat()

    try:
        result = await call_http_mcp_tool(
            url=AGENTMAIL_URL,
            headers={"x-api-key": api_key},
            tool_name="list_messages",
            arguments={
                "inboxId": INBOX_ID,
                "labels": ["received", "unread"],
                "after": last_checked,
                "limit": 50,
            },
        )
    except Exception as exc:
        _log(f"TOOL_UNAVAILABLE: {exc}")
        return 1

    messages = result.get("messages", []) if isinstance(result, dict) else []
    if not messages:
        _log(f"no new mail since {last_checked}")
        _save_last_checked(now)
        return 0

    _log(f"{len(messages)} new message(s) since {last_checked}")
    for m in messages:
        subject = m.get("subject", "")
        sender = m.get("from", "")
        preview = m.get("preview", "")[:200]
        kernel_write_episode(
            f"AgentMail: new message from {sender}, subject '{subject}': {preview}",
            source="agentmail_poll",
            domain_hint="agent_mail_inbox",
        )
        _log(f"  logged: {sender} — {subject}")

    _append_pending(messages)
    _save_last_checked(now)
    return 0


def main() -> None:
    exit_code = asyncio.run(_poll_once())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
