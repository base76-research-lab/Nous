#!/usr/bin/env python3
"""
scripts/paperclip_ollama_agent.py — Paperclip process-adapter som kör via Ollama.

Paperclip sätter miljövariabler:
  PAPERCLIP_TASK_CONTEXT  — JSON med issue/task/goals
  PAPERCLIP_API_URL       — Paperclip API endpoint
  PAPERCLIP_API_KEY       — API-nyckel
  PAPERCLIP_TASK_ID       — task-ID att uppdatera
"""
from __future__ import annotations
import json, os, sys, httpx

OLLAMA_BASE = os.getenv("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.getenv("PAPERCLIP_OLLAMA_MODEL", "kimi-k2.5:cloud")
API_URL = os.getenv("PAPERCLIP_API_URL", "")
API_KEY = os.getenv("PAPERCLIP_API_KEY", "")

SYSTEM = """You are an AI research engineer working on the Nous project —
a persistent epistemic substrate (plastic brain) for LLMs.
You have access to the codebase at /home/bjorn/projects/nouse.
Complete the assigned task, then post your findings back to Paperclip."""


def call_ollama(prompt: str) -> str:
    with httpx.Client(timeout=300.0) as c:
        r = c.post(f"{OLLAMA_BASE}/api/chat", json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        })
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "").strip()


def post_comment(task_id: str, body: str) -> None:
    if not API_URL or not API_KEY or not task_id:
        return
    try:
        with httpx.Client(timeout=15.0) as c:
            c.post(
                f"{API_URL}/api/issues/{task_id}/comments",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={"body": body},
            )
    except Exception as e:
        print(f"[warn] Kunde inte posta kommentar: {e}", file=sys.stderr)


def main() -> None:
    raw = os.getenv("PAPERCLIP_TASK_CONTEXT", "{}")
    try:
        ctx = json.loads(raw)
    except json.JSONDecodeError:
        ctx = {"raw": raw}

    task_id = os.getenv("PAPERCLIP_TASK_ID", "")
    title = ctx.get("issue", {}).get("title", ctx.get("title", ""))
    body = ctx.get("issue", {}).get("body", ctx.get("body", ""))

    prompt = f"""# Task\n{title}\n\n{body}\n\nFull context:\n{json.dumps(ctx, indent=2, ensure_ascii=False)[:3000]}"""

    print(f"[dispatch] Model: {MODEL}", flush=True)
    print(f"[dispatch] Task: {title[:80]}", flush=True)

    result = call_ollama(prompt)
    print(result, flush=True)

    if task_id:
        post_comment(task_id, f"## Ollama Agent Result\n\nModel: `{MODEL}`\n\n{result}")
        print(f"[dispatch] Resultat postat till issue {task_id}", flush=True)


if __name__ == "__main__":
    main()
