#!/usr/bin/env python3
"""
scripts/dispatch.py — Conductor dispatch: skicka tasks till lokal Ollama-modell.

Användning:
  python scripts/dispatch.py --task tasks/fnc_bench_gdp_physics.md
  python scripts/dispatch.py --task tasks/seed_domain.md --model kimi-k2.5:cloud
  python scripts/dispatch.py --list-results
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

OLLAMA_BASE = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("DISPATCH_MODEL", "kimi-k2.5:cloud")
RESULTS_DIR = Path(__file__).parent.parent / "eval" / "dispatch_results"
TASKS_DIR = Path(__file__).parent.parent / "eval" / "tasks"


def call_ollama(prompt: str, model: str, timeout: float = 300.0) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{OLLAMA_BASE}/api/chat", json=payload)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "").strip()


def dispatch(task_path: Path, model: str) -> Path:
    prompt = task_path.read_text(encoding="utf-8").strip()
    print(f"→ Dispatching: {task_path.name} via {model} ...", flush=True)
    t0 = time.monotonic()
    result = call_ollama(prompt, model)
    elapsed = time.monotonic() - t0

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = task_path.stem
    out = RESULTS_DIR / f"{stem}_{ts}.md"
    out.write_text(
        f"# Result: {stem}\nModel: {model} | {elapsed:.1f}s | {datetime.now().isoformat()}\n\n"
        + result,
        encoding="utf-8",
    )
    print(f"✓ Sparat → {out} ({elapsed:.1f}s)", flush=True)
    return out


def list_results(n: int = 10) -> None:
    if not RESULTS_DIR.exists():
        print("Inga resultat ännu.")
        return
    files = sorted(RESULTS_DIR.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[:n]:
        size = f.stat().st_size
        print(f"  {f.name}  ({size} bytes)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Dispatch task to local Ollama model")
    ap.add_argument("--task", help="Sökväg till task-fil (.md eller .txt)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama-modell (default: {DEFAULT_MODEL})")
    ap.add_argument("--list-results", action="store_true", help="Visa senaste resultat")
    args = ap.parse_args()

    if args.list_results:
        list_results()
        return

    if not args.task:
        ap.print_help()
        sys.exit(1)

    task_path = Path(args.task)
    if not task_path.exists():
        print(f"Fel: filen finns inte: {task_path}")
        sys.exit(1)

    dispatch(task_path, args.model)


if __name__ == "__main__":
    main()
