"""
nouse.tools.seed_decomposition — Massiv initial dekomposition
==============================================================

Kör decomposition.run_decomposition_burst på de N viktigaste 
hub-koncepten i varje domän. Resultatet: sub-koncept + axiom-kanter
som NoUse sedan gror organiskt via plasticitet.

Analogi:
    DNA kodar initiala nervbanor → erfarenhet förstärker/beskär.
    Denna script = DNA-fasen.
    NoUse:s Hebbian plasticity = erfarenhetsfasen.

Usage:
    python -m nouse.tools.seed_decomposition --domains 20 --hubs 5
    python -m nouse.tools.seed_decomposition --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("nouse.seed_decomposition")

DB_PATH = Path.home() / ".local" / "share" / "nouse" / "field.sqlite"


def _get_hub_concepts(
    db: sqlite3.Connection,
    n_domains: int = 20,
    hubs_per_domain: int = 5,
) -> list[tuple[str, str, int]]:
    """Get top hub concepts (name, domain, degree) from the biggest domains."""
    # Top N domains
    cur = db.execute(
        "SELECT domain FROM concept GROUP BY domain "
        "ORDER BY count(*) DESC LIMIT ?",
        (n_domains,),
    )
    domains = [r[0] for r in cur.fetchall() if r[0]]

    hubs = []
    for domain in domains:
        cur = db.execute("""
            SELECT c.name, c.domain,
                   (SELECT count(*) FROM relation r 
                    WHERE r.src = c.name OR r.tgt = c.name) as degree
            FROM concept c
            WHERE c.domain = ?
            ORDER BY degree DESC
            LIMIT ?
        """, (domain, hubs_per_domain))
        for row in cur.fetchall():
            hubs.append((row[0], row[1], row[2]))

    return hubs


async def _run_seeding(
    hubs: list[tuple[str, str, int]],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run decomposition on each hub concept."""
    # Import NoUse internals
    sys.path.insert(0, str(Path.home() / "projects" / "nouse" / "src"))
    from nouse.field.surface import FieldSurface
    from nouse.daemon.decomposition import (
        decompose_concept,
        promote_axioms_to_graph,
        AxiomCandidate,
    )

    field = FieldSurface(read_only=dry_run)
    
    total_axioms = 0
    total_sub_concepts = 0
    results = []

    for i, (concept, domain, degree) in enumerate(hubs):
        _log.info(
            "Decomposing %d/%d: '%s' (domain=%s, degree=%d)",
            i + 1, len(hubs), concept, domain, degree,
        )

        try:
            tree, axioms = await decompose_concept(field, concept, domain)
        except Exception as e:
            _log.warning("Failed to decompose '%s': %s", concept, e)
            results.append({
                "concept": concept,
                "domain": domain,
                "status": "error",
                "error": str(e),
            })
            continue

        n_subs = tree.children_count if hasattr(tree, 'children_count') else 0
        n_axioms = len(axioms)

        if dry_run:
            _log.info(
                "  [DRY-RUN] '%s': %d sub-concepts, %d axiom candidates",
                concept, n_subs, n_axioms,
            )
            for ax in axioms:
                _log.info(
                    "    Axiom: '%s' bridge=%.2f domains=%s",
                    ax.concept, ax.bridge_score, ax.domains,
                )
        else:
            if axioms:
                added = promote_axioms_to_graph(field, axioms)
                total_axioms += added
                _log.info(
                    "  '%s': %d sub-concepts, %d axiom-edges added",
                    concept, n_subs, added,
                )
            else:
                _log.info("  '%s': %d sub-concepts, no axioms", concept, n_subs)

        total_sub_concepts += n_subs
        results.append({
            "concept": concept,
            "domain": domain,
            "sub_concepts": n_subs,
            "axioms": n_axioms,
            "status": "ok",
        })

        # Pace the LLM
        if i < len(hubs) - 1:
            await asyncio.sleep(0.5)

    return {
        "hubs_processed": len(hubs),
        "total_sub_concepts": total_sub_concepts,
        "total_axioms": total_axioms,
        "details": results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Seed NoUse with massive initial decomposition"
    )
    parser.add_argument(
        "--domains", type=int, default=20,
        help="Number of top domains to process (default: 20)",
    )
    parser.add_argument(
        "--hubs", type=int, default=5,
        help="Hub concepts per domain (default: 5)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )

    db = sqlite3.connect(str(DB_PATH))
    hubs = _get_hub_concepts(db, args.domains, args.hubs)
    db.close()

    print(f"\n═══ SEED DECOMPOSITION ═══")
    print(f"Targets: {len(hubs)} hub concepts from {args.domains} domains")

    if args.dry_run:
        print("\n[DRY-RUN] Hub concepts selected:")
        for name, domain, degree in hubs:
            print(f"  {domain}: {name} (degree={degree})")

    result = asyncio.run(_run_seeding(hubs, dry_run=args.dry_run))

    print(f"\nResultat:")
    print(f"  Hubs processed: {result['hubs_processed']}")
    print(f"  Sub-concepts found: {result['total_sub_concepts']}")
    print(f"  Axiom edges created: {result['total_axioms']}")


if __name__ == "__main__":
    main()
