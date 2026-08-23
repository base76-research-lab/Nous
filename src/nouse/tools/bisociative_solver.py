"""
nouse.tools.bisociative_solver — Bisociativ Utvecklingsassistent (BUA)
======================================================================

Björns koncept: När en agent stöter på ett problem, istället för att
bara söka i samma domän (Python → Python-lib), bryt ner problemet till
primitiver och sök ALLA domäner i NoUse-grafen för korsdomän-lösningar.

Flöde:
  1. Problem → dekomponera till fundamentala primitiver
  2. Sök NoUse-grafen korsdomänt för varje primitiv
  3. Ranka & syntetisera lösningar med LLM
  4. Föreslå implementation (bridge, FFI, nybygge, mönster-transfer)
  5. Mata tillbaka resultat som ny kunskap

Exempel:
  "Python GIL blockerar min concurrency"
  → primitiver: [parallellism, trådmodell, synkronisering]
  → NoUse hittar: Go:goroutines, Erlang:actors, biologi:celldelning
  → syntes: "CSP-modellen (Go) kan implementeras i Python via asyncio"
  → feedback: ny koppling Python↔CSP↔Go skapas i grafen

Usage:
    from nouse.tools.bisociative_solver import solve

    result = solve("Python GIL blockerar multicore-prestanda")
    print(result.suggestions)

    # CLI:
    python -m nouse.tools.bisociative_solver "mitt problem här"
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

_log = logging.getLogger("nouse.bisociative_solver")

# --- LLM backend ---
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
CEREBRAS_API_BASE = "https://api.cerebras.ai/v1"
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "qwen-3-235b-a22b-instruct-2507")

# OpenRouter: gratis-tier, namngiven leverantör (Nvidia), verifierad 2026-08-23
# — se docs/lab-notes/2026-08-23-brain-document-synthesis.md-tråden. Föredras
# framför Cerebras när Cerebras saknar saldo (kontot är inte påfyllt).
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("NOUSE_OLLAMA_MODEL", "deepseek-r1:1.5b")

NOUSE_API = os.getenv("NOUSE_API", "http://127.0.0.1:8765")

# Load .env from iic if available
_ENV_PATH = Path("/media/bjorn/iic/.env")
if _ENV_PATH.exists() and not CEREBRAS_API_KEY:
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line.startswith("CEREBRAS_API_KEY="):
            CEREBRAS_API_KEY = line.split("=", 1)[1].strip().strip('"')
            break


# ─── Prompts ─────────────────────────────────────────────

_DECOMPOSE_PROMPT = """\
Du är en problemanalytiker. Bryt ner detta tekniska problem till fundamentala primitiver.

Problem: "{problem}"
Kontext: {context}

Uppgifter:
1. Identifiera KÄRN-PRIMITIVERNA i problemet (3-5 stycken)
   - Inte symptom, utan de fundamentala mekanismer som är involverade
   - Tänk domänlöst: "parallellism" istället för "Python threading"
2. För varje primitiv: vilka domäner UTANFÖR originaldomänen kan ha löst detta?

Svara ENBART med JSON:
{{
  "original_domain": "vilken domän problemet tillhör",
  "primitives": [
    {{
      "name": "primitiv-namn (domänlöst)",
      "description": "kort förklaring",
      "search_domains": ["domän1", "domän2", "domän3"]
    }}
  ]
}}
"""

_SYNTHESIZE_PROMPT = """\
Du är en bisociativ problemlösare. Du har fått ett problem och korsdomän-kunskap.

ORIGINAL PROBLEM:
{problem}

DEKOMPONERADE PRIMITIVER:
{primitives}

KORSDOMÄN-KUNSKAP FRÅN GRAFEN:
{graph_knowledge}

Uppgifter:
1. Identifiera de MEST LOVANDE korsdomän-lösningarna
2. För varje: hur kan den APPLICERAS på originalproblemet?
3. Ranka efter: genomförbarhet × innovation × enkelhet

Svara med JSON:
{{
  "suggestions": [
    {{
      "source_domain": "var lösningen kommer från",
      "concept": "koncept/mönster som löser det",
      "application": "hur det appliceras på originalproblemet",
      "implementation": "konkret steg (FFI, lib, mönster-transfer, nybygge)",
      "confidence": 0.0-1.0,
      "novelty": 0.0-1.0
    }}
  ],
  "synthesis": "en kort sammanfattning av bästa vägen framåt",
  "new_knowledge": [
    {{
      "from": "koncept A",
      "relation": "inspirerar|löser|analogt_med",
      "to": "koncept B",
      "why": "varför kopplingen finns"
    }}
  ]
}}
"""


# ─── Data classes ────────────────────────────────────────

@dataclass
class Primitive:
    name: str
    description: str
    search_domains: list[str] = field(default_factory=list)
    graph_hits: list[dict] = field(default_factory=list)


@dataclass
class Suggestion:
    source_domain: str
    concept: str
    application: str
    implementation: str
    confidence: float = 0.0
    novelty: float = 0.0


@dataclass
class SolverResult:
    problem: str
    original_domain: str = ""
    primitives: list[Primitive] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    synthesis: str = ""
    new_knowledge: list[dict] = field(default_factory=list)
    ingested: int = 0


# ─── LLM call ───────────────────────────────────────────

def _llm_call(prompt: str) -> dict:
    """Call LLM and parse JSON response."""
    try:
        if OPENROUTER_API_KEY:
            resp = httpx.post(
                f"{OPENROUTER_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
                timeout=60.0,
            )
            text = resp.json()["choices"][0]["message"]["content"]
        elif CEREBRAS_API_KEY:
            resp = httpx.post(
                f"{CEREBRAS_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {CEREBRAS_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": CEREBRAS_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
                timeout=60.0,
            )
            text = resp.json()["choices"][0]["message"]["content"]
        else:
            resp = httpx.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 2048},
                },
                timeout=120.0,
            )
            text = resp.json().get("message", {}).get("content", "")

        # Strip <think> tags
        if "<think>" in text:
            end = text.rfind("</think>")
            if end >= 0:
                text = text[end + 8:]

        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception as e:
        _log.warning("LLM call failed: %s", e)
    return {}


# ─── NoUse graph search ─────────────────────────────────

def _search_nouse(query: str, top_k: int = 10) -> list[dict]:
    """Search NoUse graph for concepts related to query."""
    try:
        resp = httpx.post(
            f"{NOUSE_API}/api/context",
            json={"query": query, "top_k": top_k},
            timeout=30.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("concepts", data.get("results", []))
    except Exception as e:
        _log.warning("NoUse search failed for '%s': %s", query, e)
    return []


def _ingest_knowledge(src: str, rel: str, tgt: str, why: str) -> bool:
    """Write new knowledge back to NoUse."""
    try:
        resp = httpx.post(
            f"{NOUSE_API}/api/ingest",
            json={
                "text": f"{src} {rel} {tgt}. {why}",
                "source": "bisociative-solver",
            },
            timeout=30.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ─── Scheduled background pass (Fas 1 steg 3) ────────────
#
# solve() above requires a human-written problem string. A scheduled
# background task has none — but the graph's own TDA already surfaces
# domain pairs that are topologically similar yet semantically unconnected
# (field.bisociation_candidates(), served at /api/bisoc). That IS a
# bisociation candidate: no one has to notice it, the graph already did.
# This is the step that makes bisociation genuinely autonomous instead of
# a tool that only runs when a human remembers to invoke it — see
# docs/NOUS_NEXT_GENERATION_PLAN.md Fas 1 steg 3.

_DATA_DIR = Path(os.getenv("NOUSE_DATA_DIR", str(Path.home() / ".local" / "share" / "nouse")))
_EXPLORED_PAIRS_PATH = _DATA_DIR / "bisoc_explored_pairs.json"


def _pair_key(domain_a: str, domain_b: str) -> str:
    return "::".join(sorted([domain_a, domain_b]))


def _load_explored_pairs() -> set[str]:
    try:
        if _EXPLORED_PAIRS_PATH.exists():
            return set(json.loads(_EXPLORED_PAIRS_PATH.read_text(encoding="utf-8")))
    except Exception as e:
        _log.warning("Kunde inte läsa utforskade bisociation-par: %s", e)
    return set()


def _save_explored_pairs(pairs: set[str]) -> None:
    try:
        _EXPLORED_PAIRS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _EXPLORED_PAIRS_PATH.write_text(
            json.dumps(sorted(pairs), ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        _log.warning("Kunde inte spara utforskade bisociation-par: %s", e)


def fetch_bisociation_candidates(
    tau: float = 0.55, epsilon: float = 2.0, max_domains: int = 50,
) -> list[dict]:
    """Hämta strukturella bisociation-kandidater från grafens egen TDA (/api/bisoc).

    Redan sorterade bäst-först (score, sedan tau) av field.bisociation_candidates().
    """
    try:
        resp = httpx.get(
            f"{NOUSE_API}/api/bisoc",
            params={"tau": tau, "epsilon": epsilon, "max_domains": max_domains},
            timeout=30.0,
        )
        if resp.status_code == 200:
            return resp.json().get("candidates", [])
    except Exception as e:
        _log.warning("Kunde inte hämta bisociation-kandidater: %s", e)
    return []


def scheduled_bisociation_pass(
    max_pairs: int = 1, feedback: bool = True, tau: float = 0.55,
) -> list[SolverResult]:
    """Kör bisociative_solver.py som en schemalagd bakgrundsuppgift (daemon-cykel
    eller nouse-daemon.timer), i stället för att bara vänta på en människas
    problemformulering.

    Tar de starkaste ännu-outforskade domänparen från fetch_bisociation_candidates(),
    formulerar dem som problem, kör solve() på varje (dekomponera → sök korsdomänt →
    syntetisera → mata tillbaka), och loggar varje fynd till forskningsjournalen via
    write_bisociation_finding_event(). Utforskade par persisteras i
    bisoc_explored_pairs.json så samma par inte drivs mot LLM:en om och om igen.
    """
    from nouse.daemon.journal import write_bisociation_finding_event

    candidates = fetch_bisociation_candidates(tau=tau)
    if not candidates:
        _log.info("Inga bisociation-kandidater just nu — hoppar över schemalagd pass")
        return []

    explored = _load_explored_pairs()
    results: list[SolverResult] = []

    for cand in candidates:
        if len(results) >= max_pairs:
            break
        domain_a = str(cand.get("domain_a") or "").strip()
        domain_b = str(cand.get("domain_b") or "").strip()
        if not domain_a or not domain_b:
            continue
        key = _pair_key(domain_a, domain_b)
        if key in explored:
            continue

        cand_tau = float(cand.get("tau", 0.0) or 0.0)
        problem = (
            f"Domänerna '{domain_a}' och '{domain_b}' är topologiskt lika i "
            f"NoUse-grafen (τ={cand_tau:.2f}) men saknar semantisk koppling. "
            f"Finns en bisociativ bro mellan dem — ett mönster, koncept eller "
            f"struktur som överförs från den ena till den andra?"
        )
        _log.info("Schemalagd bisociation-pass: %s <-> %s (τ=%.2f)", domain_a, domain_b, cand_tau)
        result = solve(
            problem,
            context=f"Automatiskt genererat av scheduled_bisociation_pass, τ={cand_tau:.2f}",
            feedback=feedback,
        )
        results.append(result)
        explored.add(key)
        write_bisociation_finding_event(
            domain_a=domain_a, domain_b=domain_b, tau=cand_tau,
            suggestions=len(result.suggestions), ingested=result.ingested,
            synthesis=result.synthesis,
        )

    _save_explored_pairs(explored)
    return results


# ─── Core solver ─────────────────────────────────────────

def solve(
    problem: str,
    context: str = "",
    feedback: bool = True,
) -> SolverResult:
    """
    Bisociativ problemlösning:
    1. Dekomponera problem till primitiver
    2. Sök NoUse korsdomänt
    3. Syntetisera lösningar
    4. Mata tillbaka ny kunskap
    """
    result = SolverResult(problem=problem)

    # ── Steg 1: Dekomponera ──
    _log.info("Steg 1: Dekomponerar problem...")
    decomp = _llm_call(
        _DECOMPOSE_PROMPT.format(problem=problem, context=context or "ingen")
    )
    if not decomp:
        _log.error("Kunde inte dekomponera problemet")
        return result

    result.original_domain = decomp.get("original_domain", "okänd")
    raw_primitives = decomp.get("primitives", [])

    for p in raw_primitives:
        result.primitives.append(Primitive(
            name=p.get("name", ""),
            description=p.get("description", ""),
            search_domains=p.get("search_domains", []),
        ))

    _log.info(
        "  Domän: %s, %d primitiver extraherade",
        result.original_domain, len(result.primitives),
    )

    # ── Steg 2: Sök NoUse korsdomänt ──
    _log.info("Steg 2: Söker NoUse-grafen korsdomänt...")
    all_graph_knowledge = []

    for prim in result.primitives:
        # Sök på primitiv-namnet
        hits = _search_nouse(prim.name, top_k=5)
        prim.graph_hits = hits

        # Sök på föreslagna domäner
        for domain in prim.search_domains[:3]:
            domain_hits = _search_nouse(f"{prim.name} {domain}", top_k=3)
            prim.graph_hits.extend(domain_hits)

        _log.info(
            "  '%s': %d träffar i grafen",
            prim.name, len(prim.graph_hits),
        )

        for hit in prim.graph_hits:
            all_graph_knowledge.append({
                "primitive": prim.name,
                "concept": hit.get("name", hit.get("concept", "")),
                "domain": hit.get("domain", ""),
                "score": hit.get("score", hit.get("relevance", 0)),
            })

    if not all_graph_knowledge:
        _log.warning("Inga träffar i grafen — kanske kunskapen saknas")

    # ── Steg 3: Syntetisera ──
    _log.info("Steg 3: Syntetiserar korsdomän-lösningar...")
    synth = _llm_call(_SYNTHESIZE_PROMPT.format(
        problem=problem,
        primitives=json.dumps(
            [{"name": p.name, "desc": p.description, "domains": p.search_domains}
             for p in result.primitives],
            ensure_ascii=False,
        ),
        graph_knowledge=json.dumps(all_graph_knowledge, ensure_ascii=False),
    ))

    if synth:
        for s in synth.get("suggestions", []):
            result.suggestions.append(Suggestion(
                source_domain=s.get("source_domain", ""),
                concept=s.get("concept", ""),
                application=s.get("application", ""),
                implementation=s.get("implementation", ""),
                confidence=s.get("confidence", 0),
                novelty=s.get("novelty", 0),
            ))

        result.synthesis = synth.get("synthesis", "")
        result.new_knowledge = synth.get("new_knowledge", [])

    _log.info("  %d förslag genererade", len(result.suggestions))

    # ── Steg 4: Feedback loop ──
    if feedback and result.new_knowledge:
        _log.info("Steg 4: Matar tillbaka %d nya kunskaper...", len(result.new_knowledge))
        for kn in result.new_knowledge:
            ok = _ingest_knowledge(
                kn.get("from", ""),
                kn.get("relation", "relaterat_till"),
                kn.get("to", ""),
                kn.get("why", ""),
            )
            if ok:
                result.ingested += 1
        _log.info("  %d/%d nya kunskaper ingesterade", result.ingested, len(result.new_knowledge))

    return result


# ─── Pretty print ────────────────────────────────────────

def _print_result(result: SolverResult) -> None:
    """Print solver result in readable format."""
    print(f"\n{'═' * 60}")
    print(f"  BISOCIATIV ANALYS: {result.problem}")
    print(f"  Originaldomän: {result.original_domain}")
    print(f"{'═' * 60}\n")

    print("╔══ PRIMITIVER ══╗")
    for p in result.primitives:
        print(f"  ▸ {p.name}: {p.description}")
        print(f"    Sökdomäner: {', '.join(p.search_domains)}")
        print(f"    Graf-träffar: {len(p.graph_hits)}")

    print(f"\n╔══ FÖRSLAG (rankade) ══╗")
    for i, s in enumerate(result.suggestions, 1):
        bar = "█" * int(s.confidence * 10) + "░" * (10 - int(s.confidence * 10))
        star = "★" * int(s.novelty * 5)
        print(f"\n  {i}. [{s.source_domain}] {s.concept}")
        print(f"     Tillämpning: {s.application}")
        print(f"     Implementation: {s.implementation}")
        print(f"     Konfidens: {bar} {s.confidence:.0%}  Nyhet: {star}")

    if result.synthesis:
        print(f"\n╔══ SYNTES ══╗")
        print(f"  {result.synthesis}")

    if result.new_knowledge:
        print(f"\n╔══ NY KUNSKAP → GRAFEN ══╗")
        for kn in result.new_knowledge:
            print(f"  {kn['from']} →[{kn['relation']}]→ {kn['to']}")
        print(f"  Ingesterade: {result.ingested}/{len(result.new_knowledge)}")


# ─── CLI ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Bisociativ problemlösare — korsdomän-sökning via NoUse"
    )
    parser.add_argument("problem", help="Problemet att lösa")
    parser.add_argument("--context", type=str, default="")
    parser.add_argument("--no-feedback", action="store_true",
                        help="Mata inte tillbaka kunskap till grafen")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(message)s",
    )

    result = solve(
        args.problem,
        context=args.context,
        feedback=not args.no_feedback,
    )
    _print_result(result)


if __name__ == "__main__":
    main()
