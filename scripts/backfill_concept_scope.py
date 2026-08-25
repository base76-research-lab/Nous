#!/usr/bin/env python3
"""
backfill_concept_scope.py

2026-08-25: scope_from_path() was fixed to protect IIC/research/computer
content (research_plg was missing from SENSITIVE_SCOPES; see STATUS.md),
but concept.scope is only ever set on a concept's FIRST insert
(add_concept() uses INSERT OR IGNORE). Existing concepts keep whatever
scope they got the first time, so the fix only protects content ingested
from here on — at last count 14,846 of 15,037 concepts (98.7%) were still
sitting on the old, unprotected "general" scope, including Björn's actual
research.

There is no per-concept "which file did this come from" column, but
concept_knowledge.evidence_json records "relation_source:<absolute path>"
entries for most concepts (populated by the extraction pipeline). This
script re-derives each general-scoped concept's correct scope from those
recorded paths via the same scope_from_path() the live ingestion path
uses, and only ever moves a concept from "general" to something MORE
protective — it never downgrades, and it never touches a concept that
already has a non-general scope.

Concepts with no recoverable relation_source (pure conversation/bisociation
synthesis with no cited path) cannot be improved by this method and are
left as "general" — reported separately as `no_signal`, not silently
counted as a success.

Run once, dry-run by default:
    python scripts/backfill_concept_scope.py            # report only
    python scripts/backfill_concept_scope.py --apply     # write changes
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def derive_scope_for_concept(evidence_json: str | None) -> str | None:
    """Return the most protective scope implied by this concept's recorded
    source paths, or None if no relation_source entries exist at all."""
    from nouse.daemon.sources import scope_from_path
    from nouse.field.surface import SENSITIVE_SCOPES

    try:
        entries = json.loads(evidence_json or "[]")
    except (TypeError, ValueError):
        return None
    if not isinstance(entries, list):
        return None

    paths = [
        str(e)[len("relation_source:"):]
        for e in entries
        if isinstance(e, str) and e.startswith("relation_source:")
    ]
    if not paths:
        return None

    candidates = [scope_from_path(Path(p)) for p in paths]
    sensitive_hits = [s for s in candidates if s in SENSITIVE_SCOPES]
    return sensitive_hits[0] if sensitive_hits else candidates[0]


def run_backfill(field, *, apply: bool) -> dict:
    rows = field._sql.execute(
        "SELECT c.name AS name, k.evidence_json AS evidence_json "
        "FROM concept c LEFT JOIN concept_knowledge k ON k.name = c.name "
        "WHERE c.scope = 'general' OR c.scope IS NULL"
    ).fetchall()

    stats = {
        "checked": len(rows),
        "reclassified": 0,
        "no_signal": 0,
        "stayed_general": 0,
        "by_new_scope": Counter(),
        "examples": {},  # new_scope -> up to 3 example names
    }

    for row in rows:
        name = row["name"]
        new_scope = derive_scope_for_concept(row["evidence_json"])
        if new_scope is None:
            stats["no_signal"] += 1
            continue
        if new_scope == "general":
            stats["stayed_general"] += 1
            continue

        stats["reclassified"] += 1
        stats["by_new_scope"][new_scope] += 1
        stats["examples"].setdefault(new_scope, [])
        if len(stats["examples"][new_scope]) < 3:
            stats["examples"][new_scope].append(name)

        if apply:
            field.set_concept_scope(name, new_scope)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                         help="Actually write the reclassification. Default is dry-run.")
    args = parser.parse_args()

    from nouse.field.surface import FieldSurface

    field = FieldSurface(read_only=not args.apply)
    stats = run_backfill(field, apply=args.apply)

    print(f"{'APPLIED' if args.apply else 'DRY RUN'} — checked {stats['checked']} "
          f"general-scoped concepts")
    print(f"  reclassified:    {stats['reclassified']}")
    print(f"  stayed general:  {stats['stayed_general']} (derived scope was itself general)")
    print(f"  no signal:       {stats['no_signal']} (no relation_source recorded — cannot improve)")
    print("  by new scope:")
    for scope, count in stats["by_new_scope"].most_common():
        examples = ", ".join(stats["examples"].get(scope, []))
        print(f"    {scope}: {count}  (e.g. {examples})")

    if not args.apply and stats["reclassified"] > 0:
        print("\n  Dry run only — nothing written. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
