"""
eval/longmemeval_adapter.py
============================
LongMemEval adapter: does grounding a haystack in an ISOLATED Nous graph
improve QA accuracy over a bare LLM with the same haystack unseen?

LongMemEval (Wu et al., ICLR 2025) tests five memory abilities: information
extraction, multi-session reasoning, temporal reasoning, knowledge updates,
and (in the full set) abstention. This adapter uses the oracle cut (only the
evidence-bearing sessions per question, ~1.9 sessions avg) — see
docs/NOUS_NEXT_GENERATION_PLAN.md Fas 2 item 6.

CRITICAL: every question gets a FRESH, ISOLATED FieldSurface at a temp path.
This benchmark's whole point is testing whether ingesting a haystack into a
graph helps — it must never touch the live production graph
(~/.local/share/nouse/field.sqlite). Never pass field=None and let a
condition silently fall back to FieldSurface() defaults.

Two conditions:
  A. bare — model only, no memory, has never seen the haystack
  B. nous — model + graph context, after the haystack was ingested into an
     isolated FieldSurface via the same extract_relations() pipeline the
     daemon itself uses on real conversations

Usage:
    python eval/longmemeval_adapter.py --dry-run
    python eval/longmemeval_adapter.py --model ollama/lfm2.5:latest -n 24
    python eval/longmemeval_adapter.py --model ollama/lfm2.5:latest -n 24 --categories temporal-reasoning multi-session
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

# extractor.py:s hårdkodade default (deepseek-r1:1.5b) är inte installerad i
# Ollama (404) — bekräftat 2026-08-24. Utan detta misslyckas VARJE
# extract_relations()-anrop tyst (build_isolated_field fångar exceptionen och
# fortsätter med rels=[]), så "nous"-villkoret körde hela natten mot en tom
# graf utan att någon körning märkte det. gemma4:e2b är samma modell den
# körande daemonen faktiskt använder framgångsrikt (se ROADMAP.md).
os.environ.setdefault("NOUSE_EXTRACT_MODEL", "gemma4:e2b")

from run_eval import call_llm, SYSTEM_BASELINE  # noqa: E402

# OpenRouterts gratis-tier tar 20 anrop/min — 429 Too Many Requests observerat
# 2026-08-23 utan detta. Groq (LPU-baserad) har ingen kant vi känner till,
# så bara openrouter/-modeller kastas tillbaka.
async def _throttle(model: str) -> None:
    if model.startswith("openrouter/"):
        await asyncio.sleep(3.2)

DATA_PATH = Path(__file__).parent / "data" / "longmemeval_oracle.json"

SYSTEM_NOUS_LME = """\
Du är en AI-assistent med tillgång till ett strukturerat kunskapsminne (Nous),
byggt från en tidigare konversationshistorik med denna användare.
Svara på frågan baserat på kunskapsminnet nedan. Om minnet inte täcker frågan
— säg det explicit i stället för att gissa.

Kunskapsminne (extraherat från konversationshistorik):
{context}"""

SYSTEM_JUDGE_LME = """\
Du är en strikt bedömare av faktakorrekthet. Bedöm om SVAR matchar FACIT
i sak (inte ordagrant — samma sakinnehåll räcker).

FRÅGA: {question}
FACIT: {answer}
SVAR: {model_answer}

Svara ENDAST med ett JSON-objekt:
{{"correct": <0 eller 1>, "reason": "<en mening>"}}"""


# ── Dataset loading ──────────────────────────────────────────────────────

def load_longmemeval(n: int = 0, categories: list[str] | None = None,
                     seed: int = 42) -> list[dict]:
    """Load a stratified sample from the local oracle cut.

    Run `curl -sL https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json -o eval/data/longmemeval_oracle.json` first if the file is missing.
    """
    if not DATA_PATH.exists():
        print(f"Dataset saknas: {DATA_PATH}")
        print("Hämta med: curl -sL https://huggingface.co/datasets/xiaowu0162/"
              "longmemeval-cleaned/resolve/main/longmemeval_oracle.json "
              f"-o {DATA_PATH}")
        sys.exit(1)

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    if categories:
        data = [row for row in data if row["question_type"] in categories]

    if n <= 0:
        return data

    import random
    rng = random.Random(seed)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for row in data:
        by_cat[row["question_type"]].append(row)
    for rows in by_cat.values():
        rng.shuffle(rows)

    cats = sorted(by_cat)
    per_cat = max(1, n // max(1, len(cats)))
    sample: list[dict] = []
    for cat in cats:
        sample.extend(by_cat[cat][:per_cat])
    return sample[:n] if n else sample


# ── Isolated ingestion ───────────────────────────────────────────────────

def _session_to_text(session: list[dict]) -> str:
    lines = []
    for turn in session:
        role = "Human" if turn.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {turn.get('content', '')}")
    return "\n".join(lines)


async def build_isolated_field(row: dict, db_path: Path):
    """Ingest this question's oracle haystack into a fresh, isolated graph.

    Uses the same extract_relations() the daemon uses on real conversations
    — this is a faithful test of Nous's actual ingestion path, not a shortcut.
    """
    from nouse.field.surface import FieldSurface
    from nouse.daemon.extractor import extract_relations

    field = FieldSurface(db_path=db_path, read_only=False)
    for session in row.get("haystack_sessions", []):
        text = _session_to_text(session)
        if len(text.strip()) < 20:
            continue
        try:
            rels = await extract_relations(text, {"domain_hint": "konversation", "path": "longmemeval"})
        except Exception:
            rels = []
        for r in rels:
            try:
                field.add_relation(
                    r["src"], r["type"], r["tgt"],
                    why=r.get("why", ""),
                    domain_src=r.get("domain_src", "konversation"),
                    domain_tgt=r.get("domain_tgt", "konversation"),
                    source_tag="longmemeval_eval",
                )
            except Exception:
                continue
    return field


def get_nous_lme_context(question: str, field) -> str:
    try:
        nodes = field.node_context_for_query(question)
    except Exception:
        nodes = []
    if not nodes:
        return "[Kunskapsminnet innehåller inget uppenbart relevant för frågan]"
    lines = []
    for node in nodes[:12]:
        name = node.get("name", "?")
        try:
            rels = field.out_relations(name)[:4]
        except Exception:
            rels = []
        rel_str = ", ".join(f"{r.get('type','?')} → {r.get('target','?')}" for r in rels)
        lines.append(f"• {name}" + (f": {rel_str}" if rel_str else ""))
    return "\n".join(lines)


# ── Judging ──────────────────────────────────────────────────────────────

def _parse_judge(raw: str) -> dict:
    """Reasoning-modeller (t.ex. nemotron-3.5-lightning) skriver ofta ut en
    tankeprocess före JSON-svaret ("Here's a thinking process: ..."), inte
    bara ren eller ```-inramad JSON. Sök efter det SISTA {...}-blocket i
    texten i stället för att anta att hela strängen är JSON."""
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            first_nl = cleaned.find("\n")
            if first_nl >= 0:
                cleaned = cleaned[first_nl + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        start = cleaned.rfind("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end])
    except (json.JSONDecodeError, AttributeError):
        pass
    return {"correct": 0, "reason": "unparseable judge output"}


# ── Runner ───────────────────────────────────────────────────────────────

async def run_longmemeval_benchmark(
    model: str, questions: list[dict], conditions: list[str],
    judge_model: str = "", output_path: str = "",
):
    judge_model = judge_model or model
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "model": model, "judge_model": judge_model,
        "dataset": "longmemeval_oracle (xiaowu0162/longmemeval-cleaned)",
        "conditions": {}, "metrics": {},
    }

    with tempfile.TemporaryDirectory(prefix="nouse_longmemeval_") as tmpdir:
        for condition in conditions:
            print(f"\n{'='*60}\n  Condition: {condition}  ({len(questions)} frågor)\n{'='*60}")
            condition_results = []

            for i, row in enumerate(questions):
                qid = row["question_id"]
                qtype = row["question_type"]
                question = row["question"]
                gold = row["answer"]

                if condition == "bare":
                    system, user = SYSTEM_BASELINE, question
                elif condition == "nous":
                    db_path = Path(tmpdir) / f"{qid}.sqlite"
                    field = await build_isolated_field(row, db_path)
                    context = get_nous_lme_context(question, field)
                    system = SYSTEM_NOUS_LME.format(context=context)
                    user = question
                else:
                    raise ValueError(f"Unknown condition: {condition}")

                answer = await call_llm(None, model, system, user, timeout=90.0)
                await _throttle(model)

                judge_prompt = SYSTEM_JUDGE_LME.format(
                    question=question, answer=gold, model_answer=answer[:500],
                )
                judge_raw = await call_llm(None, judge_model, "Du är en objektiv bedömare.",
                                           judge_prompt, timeout=60.0)
                await _throttle(judge_model)
                judge = _parse_judge(judge_raw)

                condition_results.append({
                    "id": qid, "question_type": qtype, "question": question,
                    "gold_answer": gold, "model_answer": answer[:500],
                    "correct": int(judge.get("correct", 0)),
                    "judge_reason": judge.get("reason", ""),
                })
                marker = "✓" if judge.get("correct") else "✗"
                print(f"  [{i+1}/{len(questions)}] {qid} ({qtype[:18]:18s}) {marker}")

            results["conditions"][condition] = condition_results

    # ── Metrics ──
    for condition, rows in results["conditions"].items():
        by_type = defaultdict(list)
        for r in rows:
            by_type[r["question_type"]].append(r["correct"])
        results["metrics"][condition] = {
            "accuracy": sum(r["correct"] for r in rows) / max(1, len(rows)),
            "n": len(rows),
            "by_type": {t: {"accuracy": sum(v) / len(v), "n": len(v)} for t, v in by_type.items()},
        }

    if not output_path:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = str(Path(__file__).parent / "results" / f"longmemeval_{ts}.json")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'='*70}\n  LONGMEMEVAL RESULTS\n{'='*70}")
    for condition, m in results["metrics"].items():
        print(f"\n  {condition.upper()}: accuracy={m['accuracy']:.1%}  n={m['n']}")
        for t, tm in sorted(m["by_type"].items()):
            print(f"    {t:22s} {tm['accuracy']:.1%}  (n={tm['n']})")

    if len(results["metrics"]) >= 2:
        conds = list(results["metrics"].keys())
        delta = results["metrics"][conds[1]]["accuracy"] - results["metrics"][conds[0]]["accuracy"]
        print(f"\n  DELTA ({conds[1]} vs {conds[0]}): {delta:+.1%}")

    print(f"\n  Resultat sparade: {output_path}")
    return results


def main():
    parser = argparse.ArgumentParser(description="LongMemEval benchmark: bare vs Nous-grounded")
    parser.add_argument("--model", default="ollama/lfm2.5:latest")
    parser.add_argument("--judge", default="")
    parser.add_argument("--conditions", nargs="+", default=["bare", "nous"],
                        choices=["bare", "nous"])
    parser.add_argument("-n", type=int, default=24)
    parser.add_argument("--categories", nargs="+", default=None)
    parser.add_argument("--output", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    questions = load_longmemeval(n=args.n, categories=args.categories)

    if args.dry_run:
        print(f"Frågor: {len(questions)}")
        by_type = defaultdict(int)
        for q in questions:
            by_type[q["question_type"]] += 1
        for q in questions[:8]:
            print(f"  {q['question_id']}: [{q['question_type']}] {q['question'][:80]}")
        print(f"\n  Kategorier: {dict(by_type)}")
        return

    asyncio.run(run_longmemeval_benchmark(
        model=args.model, questions=questions, conditions=args.conditions,
        judge_model=args.judge or args.model, output_path=args.output,
    ))


if __name__ == "__main__":
    main()
