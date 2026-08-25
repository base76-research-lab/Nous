"""
eval/run_eval.py
================
Kör benchmark: 3 modell-konfigurationer mot frågebanken.

Modeller:
  A. liten modell UTAN Nouse  (baseline)
  B. liten modell MED Nouse   (hypotesen)
  C. stor modell  UTAN Nouse  (frontier baseline)

Output: eval/results/run_<timestamp>.json + eval/RESULTS.md

Kör:
    python eval/run_eval.py
    python eval/run_eval.py --small qwen2.5:7b --large llama3.1:70b --n 60
    python eval/run_eval.py --dry-run     # visa frågor utan LLM-anrop
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

# Molnroutade reasoning-modeller (Groq qwen3.6-27b/gpt-oss-*, NVIDIA nemotron
# m.fl.) spenderar sin standard-max_tokens på ett dolt <think>-resonemang
# INNAN de når det faktiska svaret — samma fallgrop redan hittad och fixad
# för extraktionsvägen (daemon/extractor.py::EXTRACT_CLOUD_MAX_TOKENS,
# 2026-08-24). Utan det här klipps svaret av mitt i resonemanget och
# innehåller aldrig ett riktigt svar (verifierat: gav 0% judge-truthful
# rakt över alla conditions i truthfulqa_run2, se
# eval/results/RUN_LOG_2026-08-24_truthfulqa.md).
EVAL_CLOUD_MAX_TOKENS = max(256, int((os.getenv("NOUSE_EVAL_CLOUD_MAX_TOKENS") or "4096").strip()))

# Groqs gratisnivå: 30 anrop/min. Ett eval-pass gör flera sekventiella
# anrop per fråga (svar + judge, ibland fler för flerstegs-conditions)
# utan någon paus mellan dem — utan throttle går det i praktiken 429
# på nästan varje anrop så fort ett pass kommer upp i fart (verifierat
# 2026-08-24, se eval/results/RUN_LOG_2026-08-24_truthfulqa.md). Judge-
# parsern sväljer ett 429-svar tyst till score=0 eftersom det inte är
# giltig JSON — ett rate-limitat pass ser ut som usla riktiga resultat,
# inte som ett infrastrukturfel, om man inte läser rådata.
_PROVIDER_MIN_INTERVAL_SEC = {
    "https://api.groq.com/openai/v1": 2.1,
}
_provider_locks: dict[str, asyncio.Lock] = {}
_provider_last_call: dict[str, float] = {}


async def _throttle_provider(base_url: str | None) -> None:
    if not base_url:
        return
    interval = _PROVIDER_MIN_INTERVAL_SEC.get(base_url, 0.0)
    if interval <= 0:
        return
    lock = _provider_locks.setdefault(base_url, asyncio.Lock())
    async with lock:
        last = _provider_last_call.get(base_url, 0.0)
        wait = interval - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)
        _provider_last_call[base_url] = time.monotonic()

SYSTEM_NOUSE = """\
Du är en AI-assistent med tillgång till ett strukturerat kunskapsminne (Nouse).
Kunskapsminnet innehåller verifierade relationer och koncept med evidensvärden.
Svara baserat på kunskapsminnet när det är relevant.
Om kunskapsminnet inte innehåller relevant information — säg det explicit.
Var konkret och faktabaserad. Max 150 ord."""

SYSTEM_BASELINE = """\
Du är en AI-assistent. Svara sakligt och kortfattat.
Om du är osäker på något — säg det explicit.
Max 150 ord."""

PROMPT_JUDGE = """\
Du är en strikt bedömare. Bedöm om svaret nedan är korrekt givet frågan och facit.

FRÅGA: {question}
FACIT-KONCEPT: {expected_concepts}
FACIT-RELATION: {expected_relation}
FACIT-HINT: {why_hint}

SVAR: {answer}

Bedöm på en skala 0-3:
  3 = Korrekt och specifik — nämner rätt koncept och korrekt relation
  2 = Delvis korrekt — nämner rätt koncept men relation otydlig
  1 = Vagt korrekt — allmänt rätt riktning men ingen specifik kunskap
  0 = Fel eller hallucination — felaktiga påståenden

Svara ENDAST med ett JSON-objekt:
{{"score": <0-3>, "reason": "<en mening>"}}"""


PROVIDERS = {
    # model-prefix → (base_url, api_key_env)
    # None som base_url = Ollama native /api/chat (hanterar thinking-mode korrekt)
    "cerebras/":   ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    "groq/":       ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "nvidia/":     ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
    "openrouter/": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama/":     (None, None),   # native API — undviker tom content vid thinking-mode
}

# ── Pre-flight cost estimate ─────────────────────────────────────────────
# No exact token count exists before a call runs. This is a deliberately
# rough, order-of-magnitude estimate — enough to catch "an 11-condition
# sweep is about to cost real money" before it starts, not a billing-
# accurate forecast. $ per 1M tokens (blended input+output), current as of
# 2026-08-25 — check the provider's actual pricing page before trusting
# this for a run large enough to matter; it is not kept in sync
# automatically. Ollama is 0 because it's local.
ROUGH_PRICE_PER_1M_TOKENS = {
    "cerebras": 0.60,
    "groq": 0.20,
    "nvidia": 0.20,
    "openrouter": 1.00,
    "ollama": 0.0,
}


def _provider_name_for_model(model: str) -> str:
    for prefix in PROVIDERS:
        if model.startswith(prefix):
            return prefix.rstrip("/")
    return "ollama"


def estimate_run_cost_usd(
    *, model: str, judge_model: str, n_questions: int, conditions: list[str],
    avg_tokens_per_call: int = 900,
) -> float:
    """Rough pre-flight estimate: one generation call per question per
    condition (two for `nous_meta`'s multi-pass pipeline), plus one judge
    call per question per condition."""
    gen_calls = sum(
        n_questions * (2 if condition == "nous_meta" else 1)
        for condition in conditions
    )
    judge_calls = n_questions * len(conditions)

    gen_price = ROUGH_PRICE_PER_1M_TOKENS.get(_provider_name_for_model(model), 1.0)
    judge_price = ROUGH_PRICE_PER_1M_TOKENS.get(_provider_name_for_model(judge_model), 1.0)

    gen_cost = (gen_calls * avg_tokens_per_call / 1_000_000) * gen_price
    judge_cost = (judge_calls * avg_tokens_per_call / 1_000_000) * judge_price
    return round(gen_cost + judge_cost, 4)


def _resolve_provider(model: str) -> tuple[str | None, str, dict]:
    """Return (base_url, real_model, headers). base_url=None → Ollama native.

    NVIDIA NIM's own catalog IDs are already org-qualified
    (`nvidia/nemotron-...`) — stripping our `nvidia/` routing prefix like
    the other providers would send a bare `nemotron-...` model name and
    404. Verified 2026-08-24: `nvidia/nemotron-3.5-lightning-30b-a3b` is
    the literal string the API expects in the `model` field.
    """
    for prefix, (base_url, key_env) in PROVIDERS.items():
        if model.startswith(prefix):
            real_model = model if prefix == "nvidia/" else model[len(prefix):]
            headers = {}
            if key_env:
                api_key = os.getenv(key_env, "")
                headers["Authorization"] = f"Bearer {api_key}"
            return base_url, real_model, headers
    # Default: Ollama native API
    return None, model, {}


_shared_httpx_client: "object | None" = None  # lazily-created httpx.AsyncClient, reused for the process lifetime


def _get_shared_httpx_client():
    """One long-lived client instead of a fresh `httpx.AsyncClient()` per
    call. Creating+tearing down a client on every single request was the
    actual cause of a hang reproduced 2026-08-24: after ~10-30 sequential
    calls (Groq AND NVIDIA both reproduced it — not provider-specific),
    the process went to ~0% CPU with sockets stuck CLOSE_WAIT and never
    recovered, even under `asyncio.wait_for`. A shared client avoids the
    per-call connection/TLS/selector churn that pattern causes under
    sustained sequential async load."""
    import httpx
    global _shared_httpx_client
    if _shared_httpx_client is None or _shared_httpx_client.is_closed:
        _shared_httpx_client = httpx.AsyncClient()
    return _shared_httpx_client


async def call_llm(client, model: str, system: str, user: str,
                   timeout: float = 60.0) -> str:
    """Calls Ollama native API or OpenAI-compatible API based on model prefix."""
    hx = _get_shared_httpx_client()
    base_url, real_model, headers = _resolve_provider(model)

    if base_url is None:
        # Ollama native /api/chat — returnerar message.content korrekt även vid thinking-mode
        ollama_base = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        payload = {
            "model": real_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            r = await asyncio.wait_for(hx.post(f"{ollama_base}/api/chat", json=payload, timeout=timeout), timeout=timeout + 15.0)
            r.raise_for_status()
            data = r.json()
            return data.get("message", {}).get("content", "") or ""
        except (asyncio.TimeoutError, TimeoutError):
            return "[TIMEOUT]"
        except Exception as e:
            return f"[ERROR: {e}]"
    else:
        # OpenAI-compatible /chat/completions
        payload = {
            "model": real_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": EVAL_CLOUD_MAX_TOKENS,
        }
        async def _one_request() -> tuple[int, dict | None, str]:
            r = await hx.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=timeout)
            if r.status_code == 429:
                return 429, None, r.headers.get("retry-after", "")
            r.raise_for_status()
            return r.status_code, r.json(), ""

        max_retries = 4
        hard_timeout = timeout + 15.0
        for attempt in range(max_retries + 1):
            await _throttle_provider(base_url)
            try:
                status, data, retry_after = await asyncio.wait_for(_one_request(), timeout=hard_timeout)
                if status == 429 and attempt < max_retries:
                    try:
                        delay = max(1.0, float(retry_after)) if retry_after else 2.0 ** (attempt + 1)
                    except ValueError:
                        delay = 2.0 ** (attempt + 1)
                    await asyncio.sleep(delay)
                    continue
                content = data["choices"][0]["message"]["content"] or ""
                return _THINK_BLOCK_RE.sub("", content).strip()
            except (asyncio.TimeoutError, TimeoutError):
                return "[TIMEOUT]"
            except Exception as e:
                return f"[ERROR: {e}]"
        return "[ERROR: 429 Too Many Requests (retries exhausted)]"


async def run_single(client, model: str, question: dict,
                     use_nouse: bool, brain=None) -> dict:
    from nouse.search.escalator import escalate_query

    q_text = question["question"]
    t0 = time.monotonic()

    if use_nouse and brain:
        # Kör via escalatorn — L4 domain bootstrap triggar automatiskt om domän saknas
        esc = await escalate_query(q_text, brain)
        ctx = esc.context_block
        had_context = bool(ctx and not ctx.startswith("[domän bootstrappad") or
                           esc.escalated)
        user_prompt = f"{ctx}\n\n---\n{q_text}" if ctx else q_text
        system = SYSTEM_NOUSE
    else:
        user_prompt = q_text
        system = SYSTEM_BASELINE
        had_context = False

    answer = await call_llm(client, model, system, user_prompt)
    elapsed = time.monotonic() - t0

    return {
        "question_id": question["id"],
        "model": model,
        "use_nouse": use_nouse,
        "question": q_text,
        "answer": answer,
        "elapsed_s": round(elapsed, 2),
        "had_context": had_context,
    }


async def score_answer(client, judge_model: str, result: dict,
                       question: dict) -> dict:
    prompt = PROMPT_JUDGE.format(
        question=result["question"],
        expected_concepts=", ".join(question["expected_concepts"]),
        expected_relation=" → ".join(question["expected_relations"][0])
        if question["expected_relations"] else "N/A",
        why_hint=question.get("why_hint", ""),
        answer=result["answer"][:500],
    )

    raw = await call_llm(client, judge_model, "Du är en bedömare.", prompt, timeout=20.0)

    score = 0
    reason = ""
    try:
        # Extrahera JSON även om modellen lägger till text runt
        import re
        m = re.search(r'\{[^}]+\}', raw)
        if m:
            parsed = json.loads(m.group())
            score = int(parsed.get("score", 0))
            reason = str(parsed.get("reason", ""))
    except Exception:
        reason = raw[:100]

    hallucinated = _detect_hallucination(result["answer"], question)

    return {
        **result,
        "score": score,
        "score_reason": reason,
        "hallucinated": hallucinated,
        "max_score": 3,
    }


def _detect_hallucination(answer: str, question: dict) -> bool:
    """
    Enkel heuristik: svarar modellen med ett koncept som INTE finns i
    expected_concepts men är ett faktapåstående om dem?
    (Utökas i scorer.py med grafbaserad kontroll.)
    """
    # Om svaret är tomt/fel → inte hallucination, bara failure
    if answer.startswith("["):
        return False
    # Om svaret är kortare än 10 tecken → ej bedömningsbart
    if len(answer) < 10:
        return False
    return False  # Fullständig impl i scorer.py


def _keyword_score(result: dict, question: dict) -> dict:
    """Snabb keyword-baserad scoring utan LLM judge."""
    answer = result["answer"].lower()
    if answer.startswith("["):
        score, reason = 0, "timeout/error"
    else:
        hits = sum(1 for c in question["expected_concepts"]
                   if c.lower() in answer)
        total = max(1, len(question["expected_concepts"]))
        ratio = hits / total
        if ratio >= 0.6:
            score, reason = 3, f"{hits}/{total} koncept nämnda"
        elif ratio >= 0.3:
            score, reason = 2, f"{hits}/{total} koncept nämnda"
        elif ratio > 0:
            score, reason = 1, f"{hits}/{total} koncept nämnda"
        else:
            score, reason = 0, "inga förväntade koncept"
    return {
        **result,
        "score": score,
        "score_reason": reason,
        "hallucinated": _detect_hallucination(result["answer"], question),
        "max_score": 3,
    }


def _safe_git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).parent.parent),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _summarize_results(configs: list[dict], all_results: list[dict]) -> list[dict]:
    by_cfg: list[dict] = []
    for cfg in configs:
        tag = cfg["tag"]
        model = cfg["model"]
        use_nouse = bool(cfg["use_nouse"])
        rows = [
            r for r in all_results
            if str(r.get("model")) == str(model) and bool(r.get("use_nouse")) == use_nouse
        ]
        if not rows:
            continue
        scored = [r for r in rows if isinstance(r.get("score"), (int, float))]
        avg_score = (sum(float(r["score"]) for r in scored) / len(scored)) if scored else 0.0
        avg_pct = (avg_score / 3.0) * 100.0
        timeout_count = sum(1 for r in rows if str(r.get("answer", "")).startswith("[TIMEOUT]"))
        error_count = sum(
            1 for r in rows
            if str(r.get("answer", "")).startswith("[ERROR:")
        )
        by_cfg.append(
            {
                "tag": tag,
                "model": model,
                "use_nouse": use_nouse,
                "n_questions": len(rows),
                "avg_score_0_to_3": round(avg_score, 4),
                "avg_pct": round(avg_pct, 2),
                "timeout_count": timeout_count,
                "error_count": error_count,
            }
        )
    return by_cfg


def _print_table(
    configs: list[dict],
    all_results: list[dict],
    *,
    run_id: str = "",
    scoring_mode: str = "",
) -> str:
    lines = ["# Nouse Eval Results\n"]
    lines.append(f"Genererad: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    if run_id:
        lines.append(f"Run-ID: `{run_id}`\n")
    if scoring_mode:
        lines.append(f"Scoring: `{scoring_mode}`\n")
    lines.append("## Sammanfattning\n")
    lines.append("| Konfiguration | Modell | Nouse | Frågor | Avg Score | Halluc | Tid/q |\n")
    lines.append("|---|---|:---:|:---:|:---:|:---:|:---:|\n")

    for cfg in configs:
        tag = cfg["tag"]
        model = cfg["model"]
        use_nouse = cfg["use_nouse"]
        results = [r for r in all_results if r["model"] == model
                   and r["use_nouse"] == use_nouse]
        if not results:
            continue
        scored = [r for r in results if "score" in r]
        avg_score = sum(r["score"] for r in scored) / max(1, len(scored))
        hallucs = sum(1 for r in scored if r.get("hallucinated"))
        avg_time = sum(r["elapsed_s"] for r in results) / max(1, len(results))
        pct = f"{avg_score/3*100:.0f}%"
        nouse_str = "✅" if use_nouse else "—"
        lines.append(
            f"| {tag} | `{model}` | {nouse_str} | {len(results)} | "
            f"{avg_score:.2f}/3 ({pct}) | {hallucs} | {avg_time:.1f}s |\n"
        )

    lines.append("\n## Fråga-för-fråga (urval)\n")
    # Visa frågor där Nouse-modellen vann mot baseline
    q_ids = list({r["question_id"] for r in all_results})[:10]
    for qid in q_ids:
        q_results = {r["model"] + str(r["use_nouse"]): r
                     for r in all_results if r["question_id"] == qid}
        lines.append(f"\n### {qid}\n")
        for r in all_results:
            if r["question_id"] == qid:
                nouse_tag = " +Nouse" if r["use_nouse"] else ""
                score_str = f" [score={r.get('score','?')}/3]" if "score" in r else ""
                lines.append(f"**{r['model']}{nouse_tag}**{score_str}  \n")
                lines.append(f"> {r['answer'][:200]}\n\n")

    return "".join(lines)


async def main(args):
    from nouse.ollama_client.client import AsyncOllama, load_env_files
    import nouse

    load_env_files()
    client = AsyncOllama()
    brain = nouse.attach(read_only=False)  # L4 domain bootstrap måste kunna skriva

    # Läs frågor
    q_path = Path(__file__).parent / "questions.json"
    if not q_path.exists():
        print("❌ eval/questions.json saknas — kör generate_questions.py först")
        return

    with open(q_path) as f:
        questions = json.load(f)

    if args.n:
        questions = questions[: args.n]

    print(f"📋 {len(questions)} frågor laddade")

    defined_configs = [
        {"tag": "A — liten, ingen Nouse", "model": args.small, "use_nouse": False},
        {"tag": "B — liten + Nouse",      "model": args.small, "use_nouse": True},
        {"tag": "C — stor, ingen Nouse",  "model": args.large, "use_nouse": False},
    ]

    if args.dry_run:
        print("\n[DRY RUN] Frågor:")
        for q in questions[:5]:
            print(f"  [{q['id']}][{q['difficulty']}] {q['question']}")
            ctx = brain.context_block(q["question"], top_k=3)
            print(f"  Nouse-kontext: {'JA' if ctx else 'NEJ'}")
            if ctx:
                print(f"  {ctx[:150]}")
        return

    all_results: list[dict] = []

    # Kör bara A och B om samma modell (undviker redundant C)
    run_configs = defined_configs[:2] if args.small == args.large else defined_configs

    async def run_config(cfg: dict) -> list[dict]:
        model = cfg["model"]
        use_nouse = cfg["use_nouse"]
        tag = cfg["tag"]
        print(f"\n{'='*60}")
        print(f"🔄 {tag}")
        print(f"   Modell: {model}  Nouse: {use_nouse}  Concurrency: {args.concurrency}")
        print(f"{'='*60}")

        results: list[dict] = []
        sem = asyncio.Semaphore(args.concurrency)
        done = 0

        async def run_one(question: dict) -> dict:
            nonlocal done
            async with sem:
                result = await run_single(client, model, question, use_nouse,
                                          brain if use_nouse else None)
                done += 1
                print(f"  [{done:3d}/{len(questions)}] {question['id']} "
                      f"({result['elapsed_s']:.1f}s) "
                      f"{'[ctx]' if result['had_context'] else '[no ctx]'} "
                      f"→ {result['answer'][:60]}...")
                return result

        results = await asyncio.gather(*[run_one(q) for q in questions])
        return list(results)

    for cfg in run_configs:
        cfg_results = await run_config(cfg)
        all_results.extend(cfg_results)

    # Scoring — använd keyword-match om --no-judge, annars LLM judge
    print(f"\n🏆 Scoring...")
    scored_results = []
    q_map = {q["id"]: q for q in questions}
    for result in all_results:
        q = q_map[result["question_id"]]
        if args.no_judge:
            scored = _keyword_score(result, q)
        else:
            scored = await score_answer(client, args.judge, result, q)
        scored_results.append(scored)

    # Spara resultat
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    out_json = results_dir / f"run_{ts}.json"
    scoring_mode = "keyword_no_judge" if bool(args.no_judge) else "llm_judge"
    summary = _summarize_results(run_configs, scored_results)
    q_hash = _sha256_file(q_path)
    run_meta = {
        "script": "eval/run_eval.py",
        "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "git_commit": _safe_git_commit(),
        "argv": list(sys.argv),
        "models": {
            "small": args.small,
            "large": args.large,
            "judge": args.judge,
        },
        "scoring_mode": scoring_mode,
        "concurrency": int(args.concurrency),
        "questions_file": str(q_path),
        "questions_sha256": q_hash,
        "n_questions_effective": len(questions),
        "notes": [
            "domain_specific_benchmark",
            "not_universal_leaderboard_claim",
        ],
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "configs_defined": defined_configs,
            "configs_executed": run_configs,
            "configs": run_configs,  # backward compatible key
            "questions": len(questions),
            "meta": run_meta,
            "summary": summary,
            "results": scored_results,
        }, f, ensure_ascii=False, indent=2)

    # RESULTS.md
    md = _print_table(
        run_configs,
        scored_results,
        run_id=f"run_{ts}",
        scoring_mode=scoring_mode,
    )
    results_md = Path(__file__).parent / "RESULTS.md"
    with open(results_md, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n✅ Resultat sparade:")
    print(f"   JSON: {out_json}")
    print(f"   MD:   {results_md}")
    print()
    print(md[:1000])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--small", default="qwen2.5:7b",
                        help="Liten modell (default: qwen2.5:7b)")
    parser.add_argument("--large", default="qwen2.5:72b",
                        help="Stor modell (default: qwen2.5:72b)")
    parser.add_argument("--judge", default="qwen2.5:7b",
                        help="Judge-modell för scoring")
    parser.add_argument("--n", type=int, default=None,
                        help="Begränsa antal frågor")
    parser.add_argument("--dry-run", action="store_true",
                        help="Visa utan LLM-anrop")
    parser.add_argument("--no-judge", action="store_true",
                        help="Använd keyword-scoring istället för LLM judge")
    parser.add_argument("--concurrency", type=int, default=5,
                        help="Antal parallella LLM-anrop per config (default: 5)")
    args = parser.parse_args()
    asyncio.run(main(args))
