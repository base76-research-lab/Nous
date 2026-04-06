"""
nouse.tools.recursive_ingest — Rekursiv kunskapsanalys vid ingest
==================================================================

Björns algoritm:
  1. Nytt ämne → analysera → extrahera sub-koncept
  2. För VARJE sub-koncept:
     a. Vilken huvuddomän/förälder tillhör det? (fråga LLM)
     b. Finns föräldern redan i grafen? → automatisk koppling!
     c. Finns sub-konceptet redan? → stärk befintlig kant
     d. Finns det INTE? → skapa nod → recurse (till max djup)
  3. NoUse tar sedan över med Hebbian plasticitet

Filosofi:
  "Inget är klasslöst — allt är byggt på något annat."
  Genom att hitta varje sub-koncepts SANNA förälder och kolla 
  om den redan finns, uppstår kopplingarna naturligt.

  Monstera → fotosyntes → kvantkoherens → kvantmekanik (FINNS!)
  → koppling skapad automatiskt, ingen manuell bridge behövs.

  Sökning sker i x, y OCH z-led:
    x = horisontellt (syskon i samma domän)
    y = vertikalt (förälder-barn)
    z = diagonalt (korsdomän-analogier)

Usage:
    # Som standalone verktyg
    python -m nouse.tools.recursive_ingest "Monstera deliciosa" --depth 3

    # Integreras i /api/ingest via flagga
    curl -X POST http://localhost:8765/api/ingest \
      -d '{"text":"Monstera deliciosa","source":"test","recursive":true}'
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

_log = logging.getLogger("nouse.recursive_ingest")

# --- LLM backend config ---
# Priority: Cerebras API > Ollama local
# Set CEREBRAS_API_KEY to use Cerebras cloud (qwen-3-235b)
# Falls back to local Ollama if no API key
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
CEREBRAS_API_BASE = "https://api.cerebras.ai/v1"
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "qwen-3-235b-a22b-instruct-2507")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("NOUSE_OLLAMA_MODEL", "deepseek-r1:1.5b")

NOUSE_API = os.getenv("NOUSE_API", "http://127.0.0.1:8765")
DB_PATH = Path.home() / ".local" / "share" / "nouse" / "field.sqlite"

MAX_DEPTH = int(os.getenv("NOUSE_RECURSIVE_MAX_DEPTH", "3"))
MAX_SUBS = int(os.getenv("NOUSE_RECURSIVE_MAX_SUBS", "5"))

# Load .env from iic if available
_ENV_PATH = Path("/media/bjorn/iic/.env")
if _ENV_PATH.exists() and not CEREBRAS_API_KEY:
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line.startswith("CEREBRAS_API_KEY="):
            CEREBRAS_API_KEY = line.split("=", 1)[1].strip().strip('"')
            break

_ANALYZE_PROMPT = """\
Du är en kunskapsanalytiker. Analysera konceptet och bryt ner det.

Koncept: "{concept}"
Kontext: {context}
Djup: {depth}/{max_depth}

Uppgifter:
1. Vilken HUVUDDOMÄN tillhör detta koncept? (t.ex. "kvantmekanik", "botanik", "neurovetenskap")
2. Lista 3-5 SUB-KONCEPT som detta är byggt på eller innehåller
3. För varje sub-koncept: vilken domän tillhör DET?

Svara ENBART med JSON:
{{
  "main_domain": "domännamn",
  "sub_concepts": [
    {{"name": "sub-koncept", "domain": "dess domän", "relation": "är_del_av|möjliggör|bygger_på|använder"}},
    ...
  ]
}}

Regler:
- Sub-koncepten ska vara VERKLIGA, inte synonymer
- Domäner ska vara specifika ämnesområden
- Gå djupare mot fundamentala mekanismer
- Om konceptet är atomärt: returnera tom lista
"""


@dataclass
class AnalysisNode:
    concept: str
    domain: str | None = None
    depth: int = 0
    found_in_graph: bool = False
    children: list["AnalysisNode"] = field(default_factory=list)
    connections_made: int = 0


def _concept_exists(concept: str) -> tuple[bool, str | None]:
    """Check if concept exists in NoUse graph, return (exists, domain)."""
    import sqlite3
    try:
        db = sqlite3.connect(str(DB_PATH))
        cur = db.execute(
            "SELECT domain FROM concept WHERE name = ? COLLATE NOCASE",
            (concept,),
        )
        row = cur.fetchone()
        db.close()
        if row:
            return True, row[0]
        return False, None
    except Exception:
        return False, None


def _domain_exists(domain: str) -> tuple[bool, int]:
    """Check if domain exists and how many concepts it has."""
    import sqlite3
    try:
        db = sqlite3.connect(str(DB_PATH))
        cur = db.execute(
            "SELECT count(*) FROM concept WHERE domain = ? COLLATE NOCASE",
            (domain,),
        )
        row = cur.fetchone()
        db.close()
        count = row[0] if row else 0
        return count > 0, count
    except Exception:
        return False, 0


def _llm_analyze(concept: str, context: str, depth: int) -> dict:
    """Ask LLM to decompose a concept. Uses Cerebras API if available, else Ollama."""
    prompt = _ANALYZE_PROMPT.format(
        concept=concept,
        context=context,
        depth=depth,
        max_depth=MAX_DEPTH,
    )
    try:
        if CEREBRAS_API_KEY:
            resp = httpx.post(
                f"{CEREBRAS_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {CEREBRAS_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": CEREBRAS_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 1024,
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
                    "options": {"temperature": 0.2, "num_predict": 1024},
                },
                timeout=60.0,
            )
            text = resp.json().get("message", {}).get("content", "")

        # Strip <think> tags (deepseek-r1)
        clean = text
        if "<think>" in clean:
            end = clean.rfind("</think>")
            if end >= 0:
                clean = clean[end + 8:]
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(clean[start:end])
    except Exception as e:
        _log.warning("LLM analyze failed for '%s': %s", concept, e)
    return {}


def _ingest_relation(src: str, rel: str, tgt: str, why: str, source: str) -> bool:
    """Write a single relation to NoUse via API."""
    try:
        resp = httpx.post(
            f"{NOUSE_API}/api/ingest",
            json={
                "text": f"{src} {rel} {tgt}. {why}",
                "source": source,
            },
            timeout=30.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


def recursive_analyze(
    concept: str,
    context: str = "",
    depth: int = 0,
    visited: set[str] | None = None,
    source: str = "recursive-ingest",
) -> AnalysisNode:
    """
    Björns algoritm: rekursivt analysera, leta föräldrar, koppla.

    Returnerar ett träd av AnalysisNode.
    """
    if visited is None:
        visited = set()

    node = AnalysisNode(concept=concept, depth=depth)

    # Normalisera
    concept_lower = concept.lower().strip()
    if concept_lower in visited or depth > MAX_DEPTH:
        return node
    visited.add(concept_lower)

    # Steg 1: Finns konceptet redan i grafen?
    exists, existing_domain = _concept_exists(concept)
    if exists:
        node.found_in_graph = True
        node.domain = existing_domain
        _log.info(
            "%s  '%s' FINNS redan (domän: %s) → koppling!",
            "  " * depth, concept, existing_domain,
        )
        # Konceptet finns — vi behöver inte bryta ner det mer
        # MEN vi skapar koppling från parent (sker i anroparen)
        return node

    # Steg 2: Analysera med LLM
    _log.info("%s  Analyserar '%s' (djup %d)...", "  " * depth, concept, depth)
    analysis = _llm_analyze(concept, context or concept, depth)

    if not analysis:
        _log.info("%s  LLM kunde inte analysera '%s'", "  " * depth, concept)
        return node

    main_domain = analysis.get("main_domain", "")
    node.domain = main_domain

    # Steg 3: Finns huvuddomänen?
    if main_domain:
        dom_exists, dom_count = _domain_exists(main_domain)
        if dom_exists:
            _log.info(
                "%s  Domän '%s' finns (%d koncept) → naturlig hemvist",
                "  " * depth, main_domain, dom_count,
            )

    # Steg 4: För varje sub-koncept
    subs = analysis.get("sub_concepts", [])[:MAX_SUBS]

    for sub in subs:
        sub_name = sub.get("name", "").strip()
        sub_domain = sub.get("domain", "").strip()
        sub_rel = sub.get("relation", "är_del_av").strip()

        if not sub_name:
            continue

        # Rekursera på sub-konceptet
        child = recursive_analyze(
            concept=sub_name,
            context=f"sub-koncept av '{concept}' ({main_domain})",
            depth=depth + 1,
            visited=visited,
            source=source,
        )
        node.children.append(child)

        # Skapa koppling: parent → child
        why = f"'{sub_name}' är en beståndsdel av '{concept}'"
        if child.found_in_graph:
            why += f" — HITTAD i befintlig domän '{child.domain}'"

        ok = _ingest_relation(
            concept, sub_rel, sub_name, why, source,
        )
        if ok:
            node.connections_made += 1
            verb = "BRYGGA" if child.found_in_graph else "ny"
            _log.info(
                "%s  ✓ %s: %s →[%s]→ %s (%s)",
                "  " * depth, verb, concept, sub_rel, sub_name,
                child.domain or sub_domain,
            )

        time.sleep(0.2)

    return node


def _print_tree(node: AnalysisNode, prefix: str = "") -> None:
    """Pretty-print the analysis tree."""
    marker = "●" if node.found_in_graph else "○"
    domain_str = f" [{node.domain}]" if node.domain else ""
    conn_str = f" ({node.connections_made} kopplingar)" if node.connections_made else ""
    print(f"{prefix}{marker} {node.concept}{domain_str}{conn_str}")
    for i, child in enumerate(node.children):
        is_last = i == len(node.children) - 1
        child_prefix = prefix + ("  └─ " if is_last else "  ├─ ")
        next_prefix = prefix + ("     " if is_last else "  │  ")
        _print_tree_child(child, child_prefix, next_prefix)


def _print_tree_child(node: AnalysisNode, prefix: str, next_prefix: str) -> None:
    marker = "●" if node.found_in_graph else "○"
    domain_str = f" [{node.domain}]" if node.domain else ""
    conn_str = f" +{node.connections_made}" if node.connections_made else ""
    print(f"{prefix}{marker} {node.concept}{domain_str}{conn_str}")
    for i, child in enumerate(node.children):
        is_last = i == len(node.children) - 1
        child_prefix = next_prefix + ("  └─ " if is_last else "  ├─ ")
        child_next = next_prefix + ("     " if is_last else "  │  ")
        _print_tree_child(child, child_prefix, child_next)


def _count_tree(node: AnalysisNode) -> dict:
    """Count total nodes, connections, and bridges in tree."""
    total = 1
    connections = node.connections_made
    bridges = 1 if node.found_in_graph else 0
    for child in node.children:
        sub = _count_tree(child)
        total += sub["nodes"]
        connections += sub["connections"]
        bridges += sub["bridges"]
    return {"nodes": total, "connections": connections, "bridges": bridges}


def main():
    parser = argparse.ArgumentParser(
        description="Rekursiv kunskapsanalys — Björns algoritm"
    )
    parser.add_argument("concept", help="Koncept att analysera")
    parser.add_argument("--depth", type=int, default=MAX_DEPTH)
    parser.add_argument("--context", type=str, default="")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(message)s",
    )

    # Override module-level MAX_DEPTH from CLI arg
    import nouse.tools.recursive_ingest as _self
    _self.MAX_DEPTH = args.depth

    print(f"\n═══ REKURSIV ANALYS: '{args.concept}' (max djup {args.depth}) ═══\n")

    tree = recursive_analyze(
        args.concept,
        context=args.context,
        source=f"recursive-ingest:{args.concept}",
    )

    print("\n═══ ANALYSTRÄD ═══\n")
    _print_tree(tree)

    stats = _count_tree(tree)
    print(f"\n═══ RESULTAT ═══")
    print(f"  Noder analyserade: {stats['nodes']}")
    print(f"  Kopplingar skapade: {stats['connections']}")
    print(f"  Bryggor till befintlig kunskap: {stats['bridges']}")


if __name__ == "__main__":
    main()
