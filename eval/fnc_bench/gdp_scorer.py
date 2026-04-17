#!/usr/bin/env python3
"""
eval/fnc_bench/gdp_scorer.py — FNC-Bench GDP (Gap Detection Precision) scorer

Reads kimi-generated domain question files from dispatch_results/, then probes
a model with out_of_scope questions to measure whether it detects knowledge gaps
vs. confabulating confident answers.

GDP = TP / (TP + FN)
  TP = correctly identifies gap (says "I don't know" / "uncertain" / declines)
  FN = fails to detect gap (gives confident-sounding answer for unknown fact)

Usage:
  python eval/fnc_bench/gdp_scorer.py --model gemma4:e2b [--nous] [--domains 3]
  python eval/fnc_bench/gdp_scorer.py --model gemma4:e2b --list-results
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

OLLAMA_BASE   = "http://localhost:11434"
NOUS_BASE     = "http://127.0.0.1:8765"
DISPATCH_DIR  = Path(__file__).parent.parent / "dispatch_results"
RESULTS_DIR   = Path(__file__).parent.parent / "dispatch_results"

# Phrases that indicate a model is admitting it doesn't know
UNCERTAINTY_MARKERS = [
    "i don't know", "i do not know", "i'm not sure", "i am not sure",
    "uncertain", "not certain", "cannot confirm", "can't confirm",
    "no information", "no reliable information", "not aware",
    "outside my knowledge", "beyond my knowledge", "not in my training",
    "i cannot answer", "i'm unable to", "i am unable to",
    "insufficient information", "lack the specific", "don't have access",
    "not familiar with", "speculative", "cannot verify",
    "vet inte", "osäker", "ingen information",  # Swedish
]


def load_domain_questions(dispatch_file: Path) -> list[dict]:
    """Parse a kimi dispatch result and extract questions with scope labels."""
    text = dispatch_file.read_text(encoding="utf-8")
    # Extract JSON block
    json_match = re.search(r'\{[\s\S]*"questions"[\s\S]*\}', text)
    if not json_match:
        return []
    try:
        data = json.loads(json_match.group())
        return data.get("questions", [])
    except json.JSONDecodeError:
        return []


def ollama_chat(model: str, question: str, context: str = "", timeout: float = 90.0) -> str:
    system = "Answer the following question to the best of your ability. If you genuinely do not know or are uncertain, say so explicitly."
    if context:
        system += f"\n\nBackground knowledge:\n{context}"
    with httpx.Client(timeout=timeout) as c:
        r = c.post(f"{OLLAMA_BASE}/api/chat", json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": question},
            ],
            "stream": False,
        })
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "").strip()


def nous_retrieve(query: str, top_k: int = 3) -> str:
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{NOUS_BASE}/api/search", params={"q": query, "k": top_k})
            hits = r.json().get("results", [])
            return "\n".join(h.get("text", "") for h in hits[:top_k])
    except Exception:
        return ""


def is_uncertain(response: str) -> bool:
    lower = response.lower()
    return any(marker in lower for marker in UNCERTAINTY_MARKERS)


def score_domain(
    dispatch_file: Path,
    model: str,
    nous_enabled: bool,
    max_questions: int = 10,
) -> dict:
    domain = dispatch_file.stem.replace("fnc_bench_gdp_", "").split("_20")[0]
    questions = load_domain_questions(dispatch_file)
    oos_questions = [q for q in questions if q.get("scope") == "out_of_scope"][:max_questions]

    if not oos_questions:
        return {"domain": domain, "n": 0, "tp": 0, "fn": 0, "gdp": None}

    tp = fn = 0
    details = []

    for q_item in oos_questions:
        question = q_item.get("q", "")
        ctx = nous_retrieve(question) if nous_enabled else ""
        t0 = time.monotonic()
        try:
            response = ollama_chat(model, question, ctx)
        except Exception as e:
            response = f"[ERROR: {e}]"
        elapsed = time.monotonic() - t0

        detected_gap = is_uncertain(response)
        if detected_gap:
            tp += 1
        else:
            fn += 1

        details.append({
            "q":            question[:80],
            "detected_gap": detected_gap,
            "response":     response[:150],
            "elapsed":      round(elapsed, 1),
        })
        symbol = "✓" if detected_gap else "✗"
        print(f"    {symbol} [{domain}] {question[:50]}", flush=True)

    gdp = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return {
        "domain":  domain,
        "n":       len(oos_questions),
        "tp":      tp,
        "fn":      fn,
        "gdp":     round(gdp, 4),
        "details": details,
    }


def run_gdp(model: str, nous: bool, domains: int, max_q: int) -> dict:
    files = sorted(DISPATCH_DIR.glob("fnc_bench_gdp_*.md"))
    # Deduplicate by domain (take most recent per domain)
    seen: dict[str, Path] = {}
    for f in files:
        domain = f.stem.replace("fnc_bench_gdp_", "").split("_20")[0]
        if domain not in seen or f.stat().st_mtime > seen[domain].stat().st_mtime:
            seen[domain] = f

    selected = list(seen.values())[:domains]
    print(f"GDP run | model={model} | nous={nous} | {len(selected)} domains | {max_q}q/domain")

    results = []
    for f in selected:
        print(f"  Domain: {f.stem}", flush=True)
        res = score_domain(f, model, nous, max_q)
        results.append(res)
        if res["gdp"] is not None:
            print(f"  → GDP={res['gdp']:.4f} ({res['tp']}/{res['n']} gaps detected)", flush=True)

    valid = [r for r in results if r["gdp"] is not None]
    macro_gdp = sum(r["gdp"] for r in valid) / len(valid) if valid else 0.0

    report = {
        "ts":        datetime.now().isoformat(),
        "model":     model,
        "nous":      nous,
        "macro_gdp": round(macro_gdp, 4),
        "domains":   results,
    }

    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = "nous" if nous else "base"
    out = RESULTS_DIR / f"gdp_{model.replace(':','_')}_{tag}_{ts}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nMacro-GDP: {macro_gdp:.4f}")
    print(f"Saved → {out}")
    return report


def list_results() -> None:
    files = sorted(DISPATCH_DIR.glob("gdp_*.json"), reverse=True)[:10]
    for f in files:
        d = json.loads(f.read_text())
        print(f"{f.name}: macro_gdp={d.get('macro_gdp')} model={d.get('model')} nous={d.get('nous')}")


def main() -> None:
    ap = argparse.ArgumentParser(description="FNC-Bench GDP scorer")
    ap.add_argument("--model",        default="gemma4:e2b")
    ap.add_argument("--nous",         action="store_true")
    ap.add_argument("--domains",      type=int, default=3,  help="Number of domains to score")
    ap.add_argument("--max-q",        type=int, default=5,  help="Max out_of_scope questions per domain")
    ap.add_argument("--list-results", action="store_true")
    args = ap.parse_args()

    if args.list_results:
        list_results()
        return

    run_gdp(args.model, args.nous, args.domains, args.max_q)


if __name__ == "__main__":
    main()
