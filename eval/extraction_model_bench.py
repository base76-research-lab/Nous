"""
eval/extraction_model_bench.py
===============================
Kontrollerad jämförelse av lokala Ollama-modeller på Nous egen
extraktionsuppgift (extract_relations_with_diagnostics()), på ett fixerat,
domän-diverst textkorpus — inte publika benchmarks (ingen tillförlitlig
kunskap finns om dessa specifika 2026-modellversioner), utan Nous egen
kvalitetsmetrik (_extraction_quality(), redan använd av model_router.json
i produktion) körd rättvist isolerad.

VIKTIGT: kör med `nouse-daemon` STOPPAD. Annars mäter du VRAM-konkurrens,
inte modellkvalitet — det var precis vad som fick qwen3.5:9b att se ut
som trasig i produktionsloggarna (100% timeout, se STATUS.md/
NOUS_NEXT_GENERATION_PLAN.md 2026-08-24) trots att ingen vet om den
faktiskt presterar sämre än gemma4:e2b.

Usage:
    systemctl --user stop nouse-daemon
    .venv/bin/python eval/extraction_model_bench.py
    systemctl --user start nouse-daemon
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nouse.daemon.extractor import extract_relations_with_diagnostics  # noqa: E402

HOME = Path.home()
IIC = HOME / "IIC"
MEMORY_DIR = HOME / ".claude" / "projects" / "-home-bjornwikstrom" / "memory"
NOUS_ROOT = Path(__file__).parent.parent

# (label, domain_hint, path, char_offset, char_length) — fasta, granskade
# utdrag ur redan existerande, verkliga filer. Diverse domäner speglar vad
# daemonen faktiskt tar emot: arkitektur, personligt/operationellt,
# affärer/konsulting, filosofi/strategi, forskningsplan.
CORPUS: list[tuple[str, str, Path, int, int]] = [
    ("nous_arkitektur", "system", NOUS_ROOT / "docs" / "NOUS_NEXT_GENERATION_PLAN.md", 0, 1800),
    ("personlig_profil", "person", IIC / "04_SYSTEM" / "system" / "PERSON.md", 0, 1500),
    ("affär_konsulting", "företagsliv", MEMORY_DIR / "bjorn-sells-by-demonstration.md", 0, 1500),
    ("strategisk_doktrin", "AI-arkitektur", NOUS_ROOT / "docs" / "NOUS_STRATEGIC_DOCTRINE.md", 0, 1800),
    ("frontier_plan", "forskningsstrategi", NOUS_ROOT / "FRONTIER_PLAN.md", 0, 1800),
]

CANDIDATE_MODELS = ["gemma4:e2b", "qwen3.5:9b", "dolphin3:8b", "lfm2.5:latest"]

TIMEOUT_SEC = 90.0


def load_corpus() -> list[tuple[str, str, str]]:
    """Returnerar (label, domain_hint, text). Hoppar över filer som saknas
    i stället för att krascha — så jämförelsen fortfarande kan köras på
    en annan maskin med bara Nous-repot, utan hela IIC-trädet."""
    out = []
    for label, domain_hint, path, offset, length in CORPUS:
        if not path.exists():
            print(f"  [hoppar över] {label}: {path} saknas")
            continue
        text = path.read_text(encoding="utf-8")[offset:offset + length]
        if len(text.strip()) < 100:
            print(f"  [hoppar över] {label}: för kort text efter utdrag")
            continue
        out.append((label, domain_hint, text))
    return out


async def run_bench() -> dict:
    corpus = load_corpus()
    if not corpus:
        print("Inget korpus kunde laddas — avbryter.")
        sys.exit(1)

    print(f"Korpus: {len(corpus)} texter, {len(CANDIDATE_MODELS)} modeller, "
          f"{len(corpus) * len(CANDIDATE_MODELS)} körningar totalt.\n")

    results: dict[str, list[dict]] = {m: [] for m in CANDIDATE_MODELS}

    for model in CANDIDATE_MODELS:
        print(f"{'=' * 60}\n  Modell: {model}\n{'=' * 60}")
        for label, domain_hint, text in corpus:
            start = time.monotonic()
            try:
                rels, diag = await asyncio.wait_for(
                    extract_relations_with_diagnostics(
                        text,
                        {
                            "domain_hint": domain_hint,
                            "path": f"bench/{label}",
                            "extract_models": [model],
                        },
                    ),
                    timeout=TIMEOUT_SEC,
                )
                elapsed = time.monotonic() - start
                row = {
                    "text": label,
                    "success": bool(rels),
                    "n_relations": len(rels),
                    "quality": diag.get("quality"),
                    "timeouts": diag.get("timeouts", 0),
                    "used_fallback": diag.get("used_heuristic_fallback", False),
                    "elapsed_sec": round(elapsed, 2),
                }
            except asyncio.TimeoutError:
                row = {
                    "text": label, "success": False, "n_relations": 0,
                    "quality": None, "timeouts": 1, "used_fallback": False,
                    "elapsed_sec": round(time.monotonic() - start, 2),
                    "error": f"hard timeout after {TIMEOUT_SEC}s",
                }
            except Exception as e:
                row = {
                    "text": label, "success": False, "n_relations": 0,
                    "quality": None, "timeouts": 0, "used_fallback": False,
                    "elapsed_sec": round(time.monotonic() - start, 2),
                    "error": str(e),
                }
            results[model].append(row)
            marker = "✓" if row["success"] else "✗"
            q = f"{row['quality']:.2f}" if row.get("quality") is not None else "—"
            print(f"  {marker} {label:20s} n_rel={row['n_relations']:2d} "
                  f"quality={q:>5s} {row['elapsed_sec']:6.1f}s"
                  + (f"  [{row['error']}]" if row.get("error") else ""))

    summary = {}
    for model, rows in results.items():
        n = len(rows)
        successes = [r for r in rows if r["success"]]
        qualities = [r["quality"] for r in rows if r.get("quality") is not None]
        summary[model] = {
            "success_rate": len(successes) / n if n else 0.0,
            "avg_quality": sum(qualities) / len(qualities) if qualities else None,
            "avg_relations": sum(r["n_relations"] for r in rows) / n if n else 0.0,
            "avg_elapsed_sec": sum(r["elapsed_sec"] for r in rows) / n if n else 0.0,
            "timeouts": sum(r.get("timeouts", 0) for r in rows),
        }

    print(f"\n{'=' * 70}\n  SAMMANFATTNING\n{'=' * 70}")
    for model, s in summary.items():
        q = f"{s['avg_quality']:.3f}" if s["avg_quality"] is not None else "—"
        print(f"  {model:20s} success={s['success_rate']:.0%}  quality={q}  "
              f"avg_rel={s['avg_relations']:.1f}  avg_tid={s['avg_elapsed_sec']:.1f}s  "
              f"timeouts={s['timeouts']}")

    output = {
        "timestamp": datetime.utcnow().isoformat(),
        "corpus": [c[0] for c in corpus],
        "models": CANDIDATE_MODELS,
        "results": results,
        "summary": summary,
    }
    out_path = Path(__file__).parent / "results" / f"extraction_model_bench_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Resultat sparade: {out_path}")
    return output


if __name__ == "__main__":
    asyncio.run(run_bench())
