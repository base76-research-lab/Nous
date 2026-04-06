"""
nouse.tools.island_bridge — Domänfusion + LLM-bootstrap av nervkopplingar
==========================================================================

Problemet:
    NoUse har 1623 domäner där ~51% är duplicerade varianter:
    "programvaruutveckling", "mjukvaruutveckling", "software engineering"
    = samma sak i tre domäner utan kopplingar sinsemellan.

    Resultat: grafen ser ut som en arkipelag av isolerade öar.

Lösning i två faser:
    Fas 1 — DOMAIN FUSION:
        Handkraftad + LLM klassificerar alla 1623 domäner → ~80 kanoniska domäner.
        Concepts uppdateras in-place i SQLite.

    Fas 2 — LLM NERVE BOOTSTRAP:
        För varje par av kanoniska domäner som saknar koppling:
        LLM genererar 2-5 initiala relationer ("nervkopplingar").
        NoUse sköter sedan förstärkning/beskärning via Hebbian plasticity.

Filosofi:
    LLM:s tränade kunskap = den initiala kabeldragningen (som DNA i en hjärna).
    NoUse:s plasticitet = erfarenhetsbaserad förstärkning (som synaptisk LTP/LTD).
    Tillsammans: nature + nurture.

Usage:
    python -m nouse.tools.island_bridge --phase fusion     # bara domänfusion
    python -m nouse.tools.island_bridge --phase bridge     # bara nervkopplingar
    python -m nouse.tools.island_bridge                    # båda faserna
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx

_log = logging.getLogger("nouse.island_bridge")

DB_PATH = Path.home() / ".local" / "share" / "nouse" / "field.sqlite"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("NOUSE_BRIDGE_MODEL", "deepseek-r1:1.5b")
NOUSE_API = os.getenv("NOUSE_API", "http://127.0.0.1:8765")

# ── Fas 1: Domain Fusion ─────────────────────────────────────────────────────


def _get_all_domains(db: sqlite3.Connection) -> list[tuple[str, int]]:
    """Return [(domain, count), ...] sorted by count desc."""
    cur = db.execute(
        "SELECT domain, count(*) as cnt FROM concept "
        "GROUP BY domain ORDER BY cnt DESC"
    )
    return [(row[0], row[1]) for row in cur.fetchall()]


# Handcrafted canonical map for high-frequency Swedish/English duplicates.
# LLM extends this for the long tail.
_CANONICAL_SEED: dict[str, str] = {
    # Software development cluster
    "programvaruutveckling": "mjukvaruutveckling",
    "software engineering": "mjukvaruutveckling",
    "software development": "mjukvaruutveckling",
    "Software Development": "mjukvaruutveckling",
    "mjukvaruutveckling": "mjukvaruutveckling",
    # Software / programvara
    "programvara": "mjukvara",
    "software": "mjukvara",
    "Software": "mjukvara",
    "mjukvara": "mjukvara",
    # Programming
    "programmering": "programmering",
    "programming": "programmering",
    "Programming": "programmering",
    # Software architecture
    "programvaruarkitektur": "mjukvaruarkitektur",
    "software architecture": "mjukvaruarkitektur",
    "mjukvaruarkitektur": "mjukvaruarkitektur",
    # Software testing
    "programvarutestning": "mjukvarutestning",
    "software testing": "mjukvarutestning",
    "mjukvarutestning": "mjukvarutestning",
    # Computer science
    "datorvetenskap": "datavetenskap",
    "datavetenskap": "datavetenskap",
    "datalogi": "datavetenskap",
    "computer science": "datavetenskap",
    # Security
    "datasäkerhet": "säkerhet",
    "datorsäkerhet": "säkerhet",
    "security": "säkerhet",
    "Security": "säkerhet",
    "säkerhet": "säkerhet",
    "cybersäkerhet": "säkerhet",
    # AI cluster
    "ai": "AI",
    "AI": "AI",
    "AI-system": "AI",
    "ai-system": "AI",
    "artificiell intelligens": "AI",
    "Artificiell Intelligens": "AI",
    "artificial intelligence": "AI",
    # ML
    "maskininlärning": "maskininlärning",
    "ML": "maskininlärning",
    "ml": "maskininlärning",
    "machine learning": "maskininlärning",
    # AI sub-domains (keep separate but normalize case)
    "AI-forskning": "AI-forskning",
    "ai-forskning": "AI-forskning",
    "AI-utvärdering": "AI-utvärdering",
    "ai-utvärdering": "AI-utvärdering",
    "AI-arkitektur": "AI-arkitektur",
    "ai-arkitektur": "AI-arkitektur",
    "AI/ML": "AI/ML",
    "ai/ml": "AI/ML",
    "AI-filosofi": "AI-filosofi",
    "ai-filosofi": "AI-filosofi",
    "AI-teknik": "AI-teknik",
    "ai-teknik": "AI-teknik",
    "AI-modeller": "AI-modeller",
    "ai-modeller": "AI-modeller",
    # System architecture
    "systemarkitektur": "systemarkitektur",
    "Systemarkitektur": "systemarkitektur",
    "systemdesign": "systemarkitektur",
    "Systemdesign": "systemarkitektur",
    "system design": "systemarkitektur",
    "System Design": "systemarkitektur",
    # Philosophy
    "filosofi": "filosofi",
    "Filosofi": "filosofi",
    # Neuroscience
    "neurovetenskap": "neurovetenskap",
    "Neurovetenskap": "neurovetenskap",
    # Research
    "forskning": "forskning",
    "Forskning": "forskning",
    # Others with case normalization
    "statistik": "statistik",
    "Statistik": "statistik",
    "kognitionsvetenskap": "kognitionsvetenskap",
    "Kognitionsvetenskap": "kognitionsvetenskap",
    "NLP": "NLP",
    "nlp": "NLP",
    "ontologi": "ontologi",
    "Ontologi": "ontologi",
    "API": "API",
    "api": "API",
    "logik": "logik",
    "Logik": "logik",
    "vetenskap": "vetenskap",
    "Vetenskap": "vetenskap",
    "domän": "domän",
    "Domän": "domän",
    "informationsåtervinning": "informationsåtervinning",
    "Informationsåtervinning": "informationsåtervinning",
    "python": "Python",
    "Python": "Python",
    "devops": "DevOps",
    "DevOps": "DevOps",
    "militär": "militär",
    "Militär": "militär",
    "media": "media",
    "Media": "media",
    "windows": "Windows",
    "Windows": "Windows",
    "vetenskaplig metod": "vetenskaplig metod",
    "Vetenskaplig metod": "vetenskaplig metod",
    "systemkonfigurering": "systemkonfigurering",
    "systemKonfigurering": "systemkonfigurering",
    # Computer systems
    "datasystem": "datasystem",
    "datorteknik": "datorteknik",
}


def _llm_classify_batch(
    domains: list[str],
    canonical_list: list[str],
    timeout: float = 60.0,
) -> dict[str, str]:
    """Ask LLM to map unknown domains to canonical ones (or suggest new)."""
    prompt = (
        "Du är en domänklassificerare. Mappa varje domän till den mest passande "
        "kanoniska domänen, eller returnera den oförändrad om den är unik.\n\n"
        f"Kanoniska domäner:\n{json.dumps(canonical_list, ensure_ascii=False)}\n\n"
        f"Domäner att klassificera:\n{json.dumps(domains, ensure_ascii=False)}\n\n"
        "Svara ENBART med JSON-objekt: {\"domän\": \"kanonisk_domän\", ...}\n"
        "Inga förklaringar. Bara JSON."
    )
    try:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 4096},
            },
            timeout=timeout,
        )
        text = resp.json().get("message", {}).get("content", "")
        # Extract JSON from response — skip <think> tags if present
        clean = text
        if "<think>" in clean:
            think_end = clean.rfind("</think>")
            if think_end >= 0:
                clean = clean[think_end + 8:]
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(clean[start:end])
    except Exception as e:
        _log.warning("LLM classify batch failed: %s", e)
    return {}


def run_domain_fusion(db: sqlite3.Connection, dry_run: bool = False) -> dict[str, str]:
    """
    Phase 1: Merge duplicate domains into canonical ones.
    Returns the full domain → canonical mapping applied.
    """
    all_domains = _get_all_domains(db)
    _log.info("Found %d unique domains with %d total concepts",
              len(all_domains), sum(c for _, c in all_domains))

    # Step 1: Apply seed mapping
    merge_map: dict[str, str] = {}
    unmapped: list[str] = []

    for domain, _count in all_domains:
        if domain in _CANONICAL_SEED:
            merge_map[domain] = _CANONICAL_SEED[domain]
        elif domain and domain.lower() in {k.lower() for k in _CANONICAL_SEED}:
            for k, v in _CANONICAL_SEED.items():
                if k.lower() == domain.lower():
                    merge_map[domain] = v
                    break
        else:
            unmapped.append(domain)

    _log.info("Seed mapping: %d mapped, %d unmapped", len(merge_map), len(unmapped))

    # Step 2: LLM classify remaining domains in batches
    canonical_set = sorted(set(merge_map.values()))
    batch_size = 30

    for i in range(0, len(unmapped), batch_size):
        batch = unmapped[i : i + batch_size]
        _log.info("LLM classify batch %d/%d (%d domains)",
                  i // batch_size + 1,
                  (len(unmapped) + batch_size - 1) // batch_size,
                  len(batch))
        result = _llm_classify_batch(batch, canonical_set)
        for domain in batch:
            canonical = result.get(domain, domain)
            if canonical and canonical != domain and canonical in canonical_set:
                merge_map[domain] = canonical
            elif canonical and canonical != domain:
                merge_map[domain] = canonical
                if canonical not in canonical_set:
                    canonical_set.append(canonical)
            else:
                merge_map[domain] = domain

    # Step 3: Apply to database
    changes = {k: v for k, v in merge_map.items() if k != v}
    _log.info("Domain fusion: %d domains to merge", len(changes))

    if dry_run:
        for old, new in sorted(changes.items(), key=lambda x: dict(all_domains).get(x[0], 0), reverse=True):
            count = dict(all_domains).get(old, 0)
            print(f"  {old} ({count}) → {new}")
        return merge_map

    merged_count = 0
    for old_domain, new_domain in changes.items():
        cur = db.execute(
            "UPDATE concept SET domain = ? WHERE domain = ?",
            (new_domain, old_domain),
        )
        merged_count += cur.rowcount

    db.commit()
    _log.info("Merged %d concepts across %d domain renames", merged_count, len(changes))

    new_domains = _get_all_domains(db)
    _log.info("After fusion: %d domains (was %d)", len(new_domains), len(all_domains))

    return merge_map


# ── Fas 2: LLM Nerve Bootstrap ───────────────────────────────────────────────


def _get_domain_pairs_without_bridges(db: sqlite3.Connection, min_concepts: int = 50) -> list[tuple[str, str]]:
    """Find domain pairs with no cross-domain edges."""
    cur = db.execute(
        "SELECT domain, count(*) as cnt FROM concept "
        "GROUP BY domain HAVING cnt >= ? ORDER BY cnt DESC",
        (min_concepts,),
    )
    domains = [row[0] for row in cur.fetchall() if row[0]]

    connected = set()
    cur = db.execute("""
        SELECT DISTINCT c1.domain, c2.domain
        FROM relation r
        JOIN concept c1 ON r.src = c1.name
        JOIN concept c2 ON r.tgt = c2.name
        WHERE c1.domain != c2.domain
        AND c1.domain IS NOT NULL
        AND c2.domain IS NOT NULL
    """)
    for row in cur.fetchall():
        pair = tuple(sorted([row[0], row[1]]))
        connected.add(pair)

    disconnected = []
    for i, d1 in enumerate(domains):
        for d2 in domains[i + 1:]:
            pair = tuple(sorted([d1, d2]))
            if pair not in connected:
                disconnected.append((d1, d2))

    return disconnected


def _get_domain_sample(db: sqlite3.Connection, domain: str, n: int = 8) -> list[str]:
    """Get a sample of concept names from a domain."""
    cur = db.execute(
        "SELECT name FROM concept WHERE domain = ? ORDER BY RANDOM() LIMIT ?",
        (domain, n),
    )
    return [row[0] for row in cur.fetchall()]


def _llm_generate_bridges(
    domain_a: str,
    concepts_a: list[str],
    domain_b: str,
    concepts_b: list[str],
    timeout: float = 60.0,
) -> list[dict[str, str]]:
    """Ask LLM to find natural connections between two domains."""
    prompt = (
        f"Du är en kunskapsbrygga. Hitta 2-4 NATURLIGA kopplingar mellan dessa domäner.\n\n"
        f"Domän A: {domain_a}\n"
        f"Exempel-koncept: {', '.join(concepts_a)}\n\n"
        f"Domän B: {domain_b}\n"
        f"Exempel-koncept: {', '.join(concepts_b)}\n\n"
        "Regler:\n"
        "- Kopplingarna ska vara VERKLIGA, inte påhittade\n"
        "- Använd BEFINTLIGA koncept från listorna ovan om möjligt\n"
        "- Relationstyper: använder, påverkar, är_del_av, liknar, möjliggör, bygger_på\n\n"
        "Svara ENBART med JSON-array:\n"
        '[{"src": "koncept_a", "rel": "relationstyp", "tgt": "koncept_b", '
        '"why": "kort förklaring"}]\n'
        "Inga förklaringar. Bara JSON-array."
    )
    try:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 2048},
            },
            timeout=timeout,
        )
        text = resp.json().get("message", {}).get("content", "")
        clean = text
        if "<think>" in clean:
            think_end = clean.rfind("</think>")
            if think_end >= 0:
                clean = clean[think_end + 8:]
        start = clean.find("[")
        end = clean.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(clean[start:end])
    except Exception as e:
        _log.warning("LLM bridge generation failed for %s↔%s: %s",
                     domain_a, domain_b, e)
    return []


def _write_bridges_to_nouse(
    bridges: list[dict[str, str]],
    domain_a: str,
    domain_b: str,
) -> int:
    """Write bridge relations via NoUse API (goes through inbox for consolidation)."""
    written = 0
    for bridge in bridges:
        src = bridge.get("src", "").strip()
        tgt = bridge.get("tgt", "").strip()
        rel = bridge.get("rel", "relaterar_till").strip()
        why = bridge.get("why", "").strip()

        if not src or not tgt:
            continue

        try:
            resp = httpx.post(
                f"{NOUSE_API}/api/ingest",
                json={
                    "text": f"{src} {rel} {tgt}. {why}",
                    "source": f"island-bridge:{domain_a}↔{domain_b}",
                    "domain": domain_a,
                },
                timeout=30.0,
            )
            if resp.status_code == 200:
                written += 1
            else:
                _log.warning("Ingest failed for %s→%s: %s", src, tgt, resp.text)
        except Exception as e:
            _log.warning("Ingest error for %s→%s: %s", src, tgt, e)

    return written


def run_nerve_bootstrap(
    db: sqlite3.Connection,
    max_pairs: int = 50,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Phase 2: LLM generates initial nerve connections between isolated domain pairs.
    """
    disconnected = _get_domain_pairs_without_bridges(db)
    _log.info("Found %d disconnected domain pairs", len(disconnected))

    if not disconnected:
        _log.info("All domain pairs already connected!")
        return {"pairs_found": 0, "bridges_created": 0}

    domain_sizes = dict(_get_all_domains(db))
    disconnected.sort(
        key=lambda p: domain_sizes.get(p[0], 0) + domain_sizes.get(p[1], 0),
        reverse=True,
    )

    pairs_to_process = disconnected[:max_pairs]
    total_bridges = 0
    results = []

    for i, (d1, d2) in enumerate(pairs_to_process):
        _log.info(
            "Bridging %d/%d: %s (%d) ↔ %s (%d)",
            i + 1, len(pairs_to_process),
            d1, domain_sizes.get(d1, 0),
            d2, domain_sizes.get(d2, 0),
        )

        concepts_a = _get_domain_sample(db, d1)
        concepts_b = _get_domain_sample(db, d2)

        if not concepts_a or not concepts_b:
            continue

        bridges = _llm_generate_bridges(d1, concepts_a, d2, concepts_b)

        if dry_run:
            for b in bridges:
                print(f"  {b.get('src')} --[{b.get('rel')}]--> {b.get('tgt')}  ({b.get('why','')})")
            results.append({"pair": f"{d1}↔{d2}", "bridges": len(bridges)})
            total_bridges += len(bridges)
            continue

        written = _write_bridges_to_nouse(bridges, d1, d2)
        total_bridges += written
        results.append({"pair": f"{d1}↔{d2}", "bridges": written})

        if i < len(pairs_to_process) - 1:
            time.sleep(1.0)

    return {
        "pairs_found": len(disconnected),
        "pairs_processed": len(pairs_to_process),
        "bridges_created": total_bridges,
        "details": results,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="NoUse Island Bridge — Domain Fusion + Nerve Bootstrap"
    )
    parser.add_argument(
        "--phase",
        choices=["fusion", "bridge", "both"],
        default="both",
        help="Which phase to run (default: both)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=50,
        help="Max domain pairs to bridge (default: 50)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(DB_PATH),
        help=f"SQLite database path (default: {DB_PATH})",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=OLLAMA_MODEL,
        help=f"Ollama model for LLM tasks (default: {OLLAMA_MODEL})",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )

    _active_model = args.model

    # Override the module-level model for this run
    import nouse.tools.island_bridge as _self
    _self.OLLAMA_MODEL = _active_model

    db = sqlite3.connect(args.db)

    try:
        if args.phase in ("fusion", "both"):
            print("\n═══ FAS 1: DOMAIN FUSION ═══")
            merge_map = run_domain_fusion(db, dry_run=args.dry_run)
            canonical_count = len(set(merge_map.values()))
            print(f"\nResultat: {len(merge_map)} domäner → {canonical_count} kanoniska")

        if args.phase in ("bridge", "both"):
            print("\n═══ FAS 2: NERVE BOOTSTRAP ═══")
            result = run_nerve_bootstrap(db, max_pairs=args.max_pairs, dry_run=args.dry_run)
            print(f"\nResultat: {result['bridges_created']} bryggor skapade "
                  f"för {result['pairs_processed']}/{result['pairs_found']} domänpar")
    finally:
        db.close()


if __name__ == "__main__":
    main()
