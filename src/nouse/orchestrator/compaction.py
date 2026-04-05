"""
Orchestrator — Compaction & Pruning
====================================
Plastisk glömska: tar bort svaga kanter och slår ihop duplikat-noder.

Körs periodiskt av brain-loopen (var COMPACTION_EVERY_N_CYCLES cykel).

Pruning-logik:
  - Kanter med strength < WEAK_THRESHOLD OCH äldre än MIN_AGE_DAYS tas bort
  - Noder utan några kvar-ting kanter tas bort (orphan cleanup)

Dedup-logik:
  - Koncept vars namn är >90% likartade (normaliserat) slås ihop
    (den med flest relationer behålls, den svagare omdirigeras)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger("nouse.compaction")

WEAK_THRESHOLD       = 0.3     # kanter under detta styrke-värde är kandidater
MIN_AGE_DAYS         = 14      # kantens ålder (dagar) innan den kan prunas
COMPACTION_EVERY_N_CYCLES = 10  # kör compaction var 10:e brain-cykel


def should_run(cycle: int) -> bool:
    """Avgör om compaction ska köras denna cykel."""
    return cycle > 0 and cycle % COMPACTION_EVERY_N_CYCLES == 0


def prune_weak_edges(field: "FieldSurface") -> int:  # type: ignore[name-defined]
    """
    Ta bort kanter som är svaga OCH gamla.
    Returnerar antal borttagna kanter.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MIN_AGE_DAYS)).isoformat()
    count = field.delete_weak_relations(WEAK_THRESHOLD, cutoff)
    if count > 0:
        log.info(f"Pruning: tog bort {count} svaga kanter (strength<{WEAK_THRESHOLD}, ålder>{MIN_AGE_DAYS}d)")
    return count


def prune_orphan_nodes(field: "FieldSurface") -> int:  # type: ignore[name-defined]
    """
    Ta bort noder utan några relationer alls (orphans).
    Returnerar antal borttagna noder.
    """
    count = field.delete_orphan_concepts()
    if count > 0:
        log.info(f"Pruning: tog bort {count} orphan-noder")
    return count


def run_compaction(field: "FieldSurface") -> dict:  # type: ignore[name-defined]
    """
    Kör en full compaction-cykel.
    Returnerar statistik om vad som gjordes.
    """
    before = field.stats()
    edges_pruned = prune_weak_edges(field)
    nodes_pruned = prune_orphan_nodes(field)
    after = field.stats()

    stats = {
        "edges_pruned": edges_pruned,
        "nodes_pruned": nodes_pruned,
        "concepts_before": before["concepts"],
        "concepts_after":  after["concepts"],
        "relations_before": before["relations"],
        "relations_after":  after["relations"],
    }

    if edges_pruned or nodes_pruned:
        log.info(
            f"Compaction klar: "
            f"{before['concepts']}→{after['concepts']} noder, "
            f"{before['relations']}→{after['relations']} kanter"
        )
    return stats
