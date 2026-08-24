"""Tests for relation multi-timescale strength — Fas 3 punkt 9 slice 1,
docs/NOUS_NEXT_GENERATION_PLAN.md. Additive: strength (slow/consolidated)
behavior must stay byte-for-byte unchanged; strength_fast is new and
observational only."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from nouse.field.surface import FAST_STRENGTH_HALF_LIFE_HOURS, FieldSurface


def _mk_field(tmp_path: Path) -> FieldSurface:
    return FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)


def test_strength_unchanged_by_strengthen_migration(tmp_path):
    """The existing slow component must behave exactly as before."""
    field = _mk_field(tmp_path)
    field.add_relation("A", "relates_to", "B", why="unit test", source_tag="unit_test")
    field.strengthen("A", "B", delta=0.2)

    rows = field.query_all_relations_with_metadata(include_evidence=True)
    row = next(r for r in rows if r["src"] == "A" and r["tgt"] == "B")
    assert abs(row["strength"] - 1.2) < 1e-9


def test_new_relation_has_zero_decayed_fast_strength(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("A", "relates_to", "B", why="unit test", source_tag="unit_test")
    assert field.decayed_fast_strength("A", "B") == 0.0


def test_strengthen_bumps_fast_strength(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("A", "relates_to", "B", why="unit test", source_tag="unit_test")
    field.strengthen("A", "B", delta=0.3)
    assert field.decayed_fast_strength("A", "B") > 0.0


def test_weaken_reduces_fast_strength_and_floors_at_zero(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("A", "relates_to", "B", why="unit test", source_tag="unit_test")
    field.strengthen("A", "B", delta=0.1)
    field.weaken("A", "B", delta=0.5)
    assert field.decayed_fast_strength("A", "B") == 0.0


def test_fast_strength_decays_over_time():
    """Half life honored: after exactly one half-life, ~50% remains."""
    decayed = FieldSurface._decay_fast_value(
        1.0,
        "2026-08-24T00:00:00",
        (datetime(2026, 8, 24) + timedelta(hours=FAST_STRENGTH_HALF_LIFE_HOURS)).isoformat(),
    )
    assert abs(decayed - 0.5) < 1e-6


def test_fast_strength_missing_history_returns_value_unchanged():
    assert FieldSurface._decay_fast_value(0.7, None, "2026-08-24T00:00:00") == 0.7


def test_fast_strength_none_value_returns_zero():
    assert FieldSurface._decay_fast_value(None, "2026-08-24T00:00:00", "2026-08-24T06:00:00") == 0.0


def test_repeated_strengthen_accumulates_fast_strength_within_half_life(tmp_path):
    """Sustained co-activation (LTP-analogi) should raise fast strength
    higher than a single burst, as long as calls land within the decay
    window — this is the mechanism slice 2 will eventually consult."""
    field = _mk_field(tmp_path)
    field.add_relation("A", "relates_to", "B", why="unit test", source_tag="unit_test")
    field.strengthen("A", "B", delta=0.1)
    single = field.decayed_fast_strength("A", "B")
    field.strengthen("A", "B", delta=0.1)
    field.strengthen("A", "B", delta=0.1)
    repeated = field.decayed_fast_strength("A", "B")
    assert repeated > single


def test_decayed_fast_strength_missing_relation_returns_none(tmp_path):
    field = _mk_field(tmp_path)
    assert field.decayed_fast_strength("nope", "nothing") is None


def test_migration_backfills_existing_rows_to_strength(tmp_path):
    """A graph created before this migration must not silently reset
    strength_fast to 0 for already-consolidated relations — backfill to
    the existing strength value, not a fresh zero."""
    field = _mk_field(tmp_path)
    field.add_relation("A", "relates_to", "B", why="unit test", source_tag="unit_test")
    field.strengthen("A", "B", delta=0.5)  # strength now 1.5, strength_fast now >0
    # Re-run migration against the same db (simulates re-opening an
    # already-migrated graph) — must be a no-op, not a reset.
    field._migrate_relation_multitimescale_columns()
    assert field.decayed_fast_strength("A", "B") > 0.0
