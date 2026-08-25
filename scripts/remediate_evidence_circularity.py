"""
remediate_evidence_circularity.py -- one-time repair for the
evidence-score circularity bug fixed 2026-08-25 (see STATUS.md and
IIC nous-codex-dialogue-2026-08-25-evidence-circularity.md).

run_evidence_pass() used to nudge any relation with 0.35 < evidence_score
< 0.65 by +0.01 every NightRun cycle, unconditionally -- verified this
walked relations across the 0.65 promote floor with zero new evidence.
Confirmed against the live graph: a 86-relation spike sitting right at
~0.64, another 84 just past 0.65-0.70 -- the exact signature of
incremental drift, not a natural distribution.

This script targets ONLY relations that show BOTH signals at once:
  1. evidence_score >= 0.65 (crossed the promote floor)
  2. EVERY relation touching that (src, tgt, type) row has a generic
     source_tag (auto/""/None) -- i.e. no real, named, independent
     source ever backed it. A relation with a real citation is left
     alone even if it also happens to sit >= 0.65 -- that's legitimate,
     not the bug.

Action: cap evidence_score at 0.64 (one step below the promote floor)
-- undoes the specific illegitimate crossing without guessing at what
the "true" value should have been. Every change is logged with its
exact before-value for auditability/reversal.

Usage:
    .venv/bin/python3 scripts/remediate_evidence_circularity.py --dry-run
    .venv/bin/python3 scripts/remediate_evidence_circularity.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from nouse.field.surface import FieldSurface  # noqa: E402

CAP_VALUE = 0.64
PROMOTE_FLOOR = 0.65
# Real bug found via first --dry-run (see script history / commit message):
# "evidence_score >= 0.65 AND only generic source_tag" alone matched 16817
# relations -- ~60% of the whole graph, virtually all sitting at ev=1.000.
# That's the ORDINARY, legitimate add_relation() fallback (why given, no
# explicit score -> ev = min(1.0, strength), strength defaults to 1.0) --
# nothing to do with run_evidence_pass() at all. The actual bug signature
# is much narrower: the empirically observed spike right at/just past the
# promote floor (86 relations clustered at ~0.64, 84 more in 0.65-0.70,
# tapering to near-zero by 0.75) -- NOT the broad legitimate mass at 1.0.
# Window chosen from that histogram, not guessed.
SUSPECT_WINDOW_LOW = 0.63
SUSPECT_WINDOW_HIGH = 0.75
_GENERIC_SOURCE_TAGS = frozenset({None, "", "auto"})


def find_affected(field: FieldSurface) -> list[dict]:
    rows = field._sql.execute(
        "SELECT id, src, tgt, type, evidence_score FROM relation "
        "WHERE evidence_score >= ? AND evidence_score <= ? ORDER BY evidence_score DESC",
        (SUSPECT_WINDOW_LOW, SUSPECT_WINDOW_HIGH),
    ).fetchall()

    affected = []
    for row in rows:
        if float(row["evidence_score"]) < PROMOTE_FLOOR:
            continue  # in the suspect window for context, but never crossed
                      # the floor -- honestly still "not promoted", not touched
        src, tgt = row["src"], row["tgt"]
        # Two separate, correctly-scoped filters -- NOT a concatenate-then-OR.
        # in_relations(tgt) items always have target == tgt by construction,
        # so an OR across a blended list made that check trivially true for
        # every relation incoming to tgt regardless of its actual source,
        # over-including unrelated relations. Caught before running this.
        out_matching = [r for r in field.out_relations(src) if r.get("target") == tgt]
        in_matching = [r for r in field.in_relations(tgt) if r.get("source") == src]
        touching = out_matching + in_matching
        tags = {r.get("source_tag") for r in touching} or {None}
        if tags <= _GENERIC_SOURCE_TAGS:
            affected.append({
                "id": row["id"], "src": src, "tgt": tgt, "type": row["type"],
                "before": float(row["evidence_score"]),
            })
    return affected


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        print("Specify --dry-run or --apply")
        return 1

    field = FieldSurface(
        db_path="/home/bjornwikstrom/.local/share/nouse/field.sqlite",
        read_only=not args.apply,
    )

    affected = find_affected(field)
    print(f"Found {len(affected)} relations >= {PROMOTE_FLOOR} with only generic source_tags.")
    for a in affected[:20]:
        print(f"  [{a['id']}] {a['src']} --{a['type']}--> {a['tgt']}  ev={a['before']:.3f}")
    if len(affected) > 20:
        print(f"  ... and {len(affected) - 20} more")

    if args.dry_run:
        print("\nDry run only -- nothing written.")
        return 0

    log_path = Path(f"logs/evidence_remediation_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    applied = []
    for a in affected:
        field._sql.execute(
            "UPDATE relation SET evidence_score = ? WHERE id = ?",
            (CAP_VALUE, a["id"]),
        )
        applied.append({**a, "after": CAP_VALUE})
    field._sql.commit()

    log_path.write_text(json.dumps({
        "cap_value": CAP_VALUE, "promote_floor": PROMOTE_FLOOR,
        "count": len(applied), "relations": applied,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nApplied: {len(applied)} relations capped at {CAP_VALUE}. Log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
