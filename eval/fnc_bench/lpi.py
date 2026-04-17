#!/usr/bin/env python3
"""
eval/fnc_bench/lpi.py — FNC-Bench LPI (Longitudinal Persistence Index)

Measures whether a model retains and reuses epistemically grounded facts
across separate, stateless interactions.

Architecture:
  Round 1 — INJECT: present a novel fact to the model (via Nous or direct)
  Round 2 — PROBE:  in a new, blank context, ask about that fact
  Score:    1.0 if the model recalls it correctly, 0.0 otherwise

Theoretical minimum for stateless LLMs: LPI = 0.0
Nous-augmented models can score > 0 if they write to Nous in R1 and
retrieve from Nous in R2.

Usage:
  python eval/fnc_bench/lpi.py --model gemma4:e2b [--nous] [--n 10]
"""
from __future__ import annotations

import argparse
import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

OLLAMA_BASE = "http://localhost:11434"
NOUS_BASE   = "http://127.0.0.1:8765"
RESULTS_DIR = Path(__file__).parent.parent / "dispatch_results"

# ── Probe facts ───────────────────────────────────────────────────────────────
# Facts that exist in the Nous knowledge graph (BASE76/Nous-internal) but are
# NOT in any LLM's training data. Used to test cross-session persistence.
# Format: (fact_statement, probe_question, expected_answer, nous_query)

PROBE_FACTS = [
    (
        "The BASE76 project Nous (νοῦς) is a persistent epistemic substrate "
        "for LLMs developed by Björn Wikström at Base76 Research Lab.",
        "Who developed the Nous project at Base76 Research Lab?",
        "Björn Wikström",
        "Nous project Base76 developer",
    ),
    (
        "The Larynx Problem is a paper arguing that current AI systems are "
        "evaluated on their expression channel (language) rather than on "
        "intelligence itself, analogous to measuring a larynx instead of a mind.",
        "What analogy does The Larynx Problem paper use to describe the flaw "
        "in current AI evaluation?",
        "larynx",
        "Larynx Problem AI evaluation analogy",
    ),
    (
        "FNC-Bench measures six epistemic metrics: ECS, GDP, EHR, CC, LPI, and CLC. "
        "LPI stands for Learning Plasticity Index.",
        "What does LPI stand for in FNC-Bench?",
        "Learning Plasticity Index",
        "LPI FNC-Bench meaning",
    ),
    (
        "The Nous brain has an autonomic homeostasis module that auto-seeds "
        "underrepresented brain regions when they fall below 5% of total.",
        "At what percentage threshold does Nous homeostasis auto-seed brain regions?",
        "5",
        "Nous homeostasis threshold brain regions",
    ),
    (
        "The Bisociation Engine in Nous connects concepts from different domains "
        "to generate novel insights, inspired by Arthur Koestler's bisociation theory.",
        "Which theorist's work inspired the Bisociation Engine in Nous?",
        "Koestler",
        "Bisociation Engine Nous inspiration",
    ),
    (
        "The BASE76 internal project codenamed 'Larynx' was assigned tracking ID B76-LX-009 "
        "on April 3, 2025.",
        "What is the tracking ID assigned to the BASE76 internal project codenamed 'Larynx'?",
        "B76-LX-009",
    ),
    (
        "Researcher Tomás Reinholt at Uppsala University measured the thermal conductivity "
        "of graphene aerogel sample G-44 as 0.083 W/mK at 300 K.",
        "What thermal conductivity did Tomás Reinholt measure for graphene aerogel sample G-44?",
        "0.083",
    ),
    (
        "The fictional country of Valdoria adopted its constitution on September 17, 1847, "
        "with exactly 78 articles.",
        "How many articles are in Valdoria's constitution adopted on September 17, 1847?",
        "78",
    ),
    (
        "Protein variant Cx43-R214W shows a 3.7-fold increase in gap junction conductance "
        "compared to wild-type Cx43.",
        "By what fold does protein variant Cx43-R214W increase gap junction conductance "
        "compared to wild-type?",
        "3.7",
    ),
    (
        "The internal Nous memory benchmark run on 2025-11-05 recorded 14,827 semantic "
        "facts with an average retrieval latency of 38 milliseconds.",
        "What was the average retrieval latency recorded in the Nous memory benchmark "
        "run on 2025-11-05?",
        "38 milliseconds",
    ),
    (
        "Engineer Priya Nair's design specification document DS-0042 sets the maximum "
        "operating temperature of module M-7 at 87 degrees Celsius.",
        "According to design specification DS-0042, what is the maximum operating "
        "temperature of module M-7?",
        "87 degrees Celsius",
    ),
    (
        "The synthetic chemical compound named 'Velazine' has the molecular formula "
        "C18H23N3O4 and a melting point of 163.5 °C.",
        "What is the melting point of the synthetic compound Velazine?",
        "163.5",
    ),
    (
        "Expedition ARCO-2026 mapped underwater ridge formation XR-14 at coordinates "
        "71.42°N 178.06°W, finding sediment depth of 4.2 meters.",
        "What sediment depth did Expedition ARCO-2026 find at underwater ridge XR-14?",
        "4.2 meters",
    ),
    (
        "The BASE76 FNC-Bench internal calibration constant κ₀ is defined as 0.3174.",
        "What is the value of BASE76 FNC-Bench internal calibration constant κ₀?",
        "0.3174",
        "FNC-Bench calibration constant",
    ),
]

# Backwards compat: expand 3-tuples to 4-tuples with empty nous_query
PROBE_FACTS = [
    f if len(f) == 4 else (*f, "")  # type: ignore[assignment]
    for f in PROBE_FACTS
]


@dataclass
class LPIResult:
    fact_id:       int
    model:         str
    nous_enabled:  bool
    injected:      bool
    recalled:      bool
    score:         float
    r1_response:   str = ""
    r2_response:   str = ""
    elapsed_total: float = 0.0


def ollama_chat(model: str, messages: list[dict], timeout: float = 60.0) -> str:
    with httpx.Client(timeout=timeout) as c:
        r = c.post(f"{OLLAMA_BASE}/api/chat", json={
            "model": model,
            "messages": messages,
            "stream": False,
        })
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "").strip()


def nous_ingest(fact: str) -> bool:
    """Push a fact into Nous via ingest (async extraction pipeline)."""
    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.post(f"{NOUS_BASE}/api/ingest", json={
                "text": fact,
                "source": "http://lpi-bench-internal",
                "domain": "lpi",
            })
            return r.status_code < 300
    except Exception:
        return False


def nous_retrieve(question: str, top_k: int = 5) -> str:
    """Retrieve relevant context from Nous using brain/query."""
    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.post(f"{NOUS_BASE}/api/brain/query", json={
                "question": question,
                "top_k":    top_k,
            })
            d = r.json()
            # Build context from concepts + axioms
            parts: list[str] = []
            for concept in d.get("concepts", [])[:3]:
                name = concept.get("name", "")
                for claim in concept.get("claims", [])[:3]:
                    parts.append(f"{name}: {claim}")
            for axiom in d.get("axioms", [])[:5]:
                parts.append(f"{axiom.get('src')} --[{axiom.get('rel')}]--> {axiom.get('tgt')}")
            return "\n".join(parts)
    except Exception:
        return ""


def run_probe(
    fact_id: int,
    model: str,
    nous_enabled: bool,
    fact: str,
    question: str,
    expected: str,
    nous_query: str = "",
) -> LPIResult:
    t0 = time.monotonic()

    # Round 1 — INJECT
    r1_messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant. Read the following fact carefully. "
                       "You may need it later.",
        },
        {"role": "user", "content": f"Please memorize this fact:\n\n{fact}"},
    ]
    r1_resp = ollama_chat(model, r1_messages)

    injected = False
    if nous_enabled:
        injected = nous_ingest(fact)

    # Round 2 — PROBE (fresh context, no Round 1 history)
    ctx = ""
    if nous_enabled:
        # Use targeted nous_query if provided, else fall back to question
        retrieve_q = nous_query if nous_query else question
        ctx = nous_retrieve(retrieve_q)

    r2_system = "You are a helpful assistant."
    if ctx:
        r2_system += f"\n\nBackground knowledge:\n{ctx}"

    r2_messages = [
        {"role": "system", "content": r2_system},
        {"role": "user",   "content": question},
    ]
    r2_resp = ollama_chat(model, r2_messages)

    recalled = expected.lower() in r2_resp.lower()
    score    = 1.0 if recalled else 0.0

    return LPIResult(
        fact_id=fact_id,
        model=model,
        nous_enabled=nous_enabled,
        injected=injected,
        recalled=recalled,
        score=score,
        r1_response=r1_resp[:200],
        r2_response=r2_resp[:300],
        elapsed_total=time.monotonic() - t0,
    )


def run_lpi(model: str, nous: bool, n: int, seed: int = 42) -> dict:
    random.seed(seed)
    subset = random.sample(PROBE_FACTS, min(n, len(PROBE_FACTS)))

    results: list[LPIResult] = []
    for i, probe in enumerate(subset):
        fact, question, expected = probe[0], probe[1], probe[2]
        nous_query = probe[3] if len(probe) > 3 else ""
        _ = nous_query  # used below
        print(f"  [{i+1}/{len(subset)}] fact_id={i} nous={nous}", flush=True)
        res = run_probe(i, model, nous, fact, question, expected, nous_query)
        results.append(res)
        status = "✓" if res.recalled else "✗"
        print(f"    {status} score={res.score} ({res.elapsed_total:.1f}s)", flush=True)

    lpi_score = sum(r.score for r in results) / len(results) if results else 0.0

    return {
        "ts": datetime.now().isoformat(),
        "model": model,
        "nous_enabled": nous,
        "n": len(results),
        "lpi_score": round(lpi_score, 4),
        "results": [
            {
                "fact_id":       r.fact_id,
                "recalled":      r.recalled,
                "score":         r.score,
                "injected":      r.injected,
                "r2_response":   r.r2_response,
                "elapsed_total": round(r.elapsed_total, 1),
            }
            for r in results
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="FNC-Bench LPI evaluation")
    ap.add_argument("--model",  default="gemma4:e2b",  help="Ollama model name")
    ap.add_argument("--nous",   action="store_true",    help="Enable Nous retrieval augmentation")
    ap.add_argument("--n",      type=int, default=10,   help="Number of probe facts to test")
    ap.add_argument("--seed",   type=int, default=42)
    args = ap.parse_args()

    print(f"FNC-Bench LPI | model={args.model} | nous={args.nous} | n={args.n}")

    report = run_lpi(args.model, args.nous, args.n, args.seed)

    print(f"\nLPI Score: {report['lpi_score']:.4f}  ({report['n']} probes)")
    print(f"Recalled:  {sum(r['recalled'] for r in report['results'])}/{report['n']}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = "nous" if args.nous else "base"
    out = RESULTS_DIR / f"lpi_{args.model.replace(':','_')}_{tag}_{ts}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Saved → {out}")


if __name__ == "__main__":
    main()
