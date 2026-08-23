from __future__ import annotations

from pathlib import Path

from nouse.field.surface import FieldSurface


def _mk_field(tmp_path: Path) -> FieldSurface:
    return FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)


def test_add_relation_sets_valid_from_and_open_valid_until(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("A", "relates_to", "B", why="unit test", source_tag="unit_test")

    rows = field.query_all_relations_with_metadata(include_evidence=True)
    row = next(r for r in rows if r["src"] == "A" and r["tgt"] == "B")

    assert row["valid_from"]
    assert row["valid_until"] is None


def test_supersede_relation_closes_old_and_links_new(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("earth", "has_shape", "flat", why="obsolete belief", source_tag="unit_test")

    field.supersede_relation(
        "earth", "has_shape", "flat", "oblate_spheroid",
        why="corrected by measurement", source_tag="unit_test",
    )

    rows = field.query_all_relations_with_metadata(include_evidence=True)
    old = next(r for r in rows if r["src"] == "earth" and r["tgt"] == "flat" and r["rel"] == "has_shape")
    new = next(r for r in rows if r["src"] == "earth" and r["tgt"] == "oblate_spheroid" and r["rel"] == "has_shape")
    supersedes = next(r for r in rows if r["rel"] == "supersedes")

    assert old["valid_until"] is not None
    assert new["valid_until"] is None
    assert supersedes["src"] == "oblate_spheroid"
    assert supersedes["tgt"] == "flat"


def test_migration_backfills_valid_from_on_existing_db(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    _mk_field_legacy_schema(db_path)

    reopened = FieldSurface(db_path=db_path, read_only=False)
    rows = reopened.query_all_relations_with_metadata(include_evidence=True)
    row = next(r for r in rows if r["src"] == "legacy_src")

    assert row["valid_from"] == row["created"]
    assert row["valid_until"] is None
    assert row["derived_from"] is None


def test_supersede_relation_links_new_fact_to_old_via_derived_from(tmp_path):
    field = _mk_field(tmp_path)
    old_id = field.add_relation("earth", "has_shape", "flat", why="obsolete belief", source_tag="unit_test")

    new_id = field.supersede_relation(
        "earth", "has_shape", "flat", "oblate_spheroid",
        why="corrected by measurement", source_tag="unit_test",
    )

    rows = field.query_all_relations_with_metadata(include_evidence=True)
    new = next(r for r in rows if r["id"] == new_id)
    assert new["derived_from"] == old_id


def test_relation_chain_walks_backward_through_repeated_supersession(tmp_path):
    field = _mk_field(tmp_path)
    id_1 = field.add_relation("planet_9", "status", "hypothetical", why="early hunch", source_tag="unit_test")
    id_2 = field.supersede_relation(
        "planet_9", "status", "hypothetical", "candidate",
        why="orbital clustering evidence", source_tag="unit_test",
    )
    id_3 = field.supersede_relation(
        "planet_9", "status", "candidate", "confirmed",
        why="direct observation", source_tag="unit_test",
    )

    chain = field.relation_chain(id_3)
    chain_ids = [row["id"] for row in chain]

    assert chain_ids[0] == id_3
    assert id_2 in chain_ids
    assert id_1 in chain_ids
    assert chain[-1]["derived_from"] is None
    assert chain[0]["why"] == "direct observation"


def _mk_field_legacy_schema(db_path: Path) -> FieldSurface:
    """Simulate a pre-Fas-1 database (no valid_from/valid_until columns)."""
    import sqlite3

    field = FieldSurface(db_path=db_path, read_only=False)
    field.add_relation("legacy_src", "relates_to", "legacy_tgt", why="pre-migration", source_tag="unit_test")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE relation_legacy AS "
        "SELECT id, src, tgt, type, why, strength, created, evidence_score, assumption_flag FROM relation"
    )
    conn.execute("DROP TABLE relation")
    conn.execute("ALTER TABLE relation_legacy RENAME TO relation")
    conn.commit()
    conn.close()
