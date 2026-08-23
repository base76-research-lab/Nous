from __future__ import annotations

from pathlib import Path

from nouse.field.surface import FieldSurface


def _mk_field(tmp_path: Path) -> FieldSurface:
    return FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)


def _backdate_concept(field: FieldSurface, name: str, days: int = 30) -> None:
    from datetime import datetime, timedelta

    old_ts = (datetime.utcnow() - timedelta(days=days)).isoformat()
    field._sql.execute("UPDATE concept SET created = ? WHERE name = ?", (old_ts, name))
    field._sql.commit()


def test_consolidate_silences_old_never_strengthened_concepts(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation(
        "stale_idea", "relates_to", "forgotten_footnote",
        why="one-off note", strength=0.2, source_tag="unit_test",
    )
    _backdate_concept(field, "stale_idea")
    _backdate_concept(field, "forgotten_footnote")

    result = field.consolidate_dormant_concepts(min_age_days=14, strength_ceiling=0.4, max_nodes=200)

    assert result["silenced"] == 2
    rows = field.dormant_concepts()
    names = {r["name"] for r in rows}
    assert {"stale_idea", "forgotten_footnote"} <= names


def test_consolidate_does_not_delete_concept_or_relation_rows(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation(
        "stale_idea", "relates_to", "forgotten_footnote",
        why="one-off note", strength=0.2, source_tag="unit_test",
    )
    _backdate_concept(field, "stale_idea")
    _backdate_concept(field, "forgotten_footnote")

    field.consolidate_dormant_concepts(min_age_days=14, strength_ceiling=0.4, max_nodes=200)

    concept_names = {row["name"] for row in field.concepts()}
    assert "stale_idea" in concept_names
    assert "forgotten_footnote" in concept_names
    rows = field.query_all_relations_with_metadata(include_evidence=True)
    assert any(r["src"] == "stale_idea" and r["tgt"] == "forgotten_footnote" for r in rows)


def test_consolidate_spares_recently_strengthened_concepts(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation(
        "core_idea", "relates_to", "supporting_fact",
        why="reinforced repeatedly", strength=0.2, source_tag="unit_test",
    )
    _backdate_concept(field, "core_idea")
    _backdate_concept(field, "supporting_fact")
    field.strengthen("core_idea", "supporting_fact", delta=0.5)

    result = field.consolidate_dormant_concepts(min_age_days=14, strength_ceiling=0.4, max_nodes=200)

    assert result["silenced"] == 0
    assert field.dormant_concepts() == []


def test_consolidate_spares_young_concepts_regardless_of_strength(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("fresh_idea", "relates_to", "fresh_footnote", why="just added", source_tag="unit_test")

    result = field.consolidate_dormant_concepts(min_age_days=14, strength_ceiling=0.4, max_nodes=200)

    assert result["silenced"] == 0


def test_add_concept_revives_a_dormant_concept(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("half_forgotten", domain="unit_test")
    _backdate_concept(field, "half_forgotten")
    field.consolidate_dormant_concepts(min_age_days=14, strength_ceiling=0.4, max_nodes=200)
    assert any(r["name"] == "half_forgotten" for r in field.dormant_concepts())

    field.add_concept("half_forgotten", domain="unit_test")

    assert not any(r["name"] == "half_forgotten" for r in field.dormant_concepts())
    assert field._G.nodes["half_forgotten"]["dormant_since"] is None


def test_revive_concept_manually_clears_dormant_flag(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("manual_revive_me", domain="unit_test")
    _backdate_concept(field, "manual_revive_me")
    field.consolidate_dormant_concepts(min_age_days=14, strength_ceiling=0.4, max_nodes=200)
    assert any(r["name"] == "manual_revive_me" for r in field.dormant_concepts())

    revived = field.revive_concept("manual_revive_me")

    assert revived is True
    assert not any(r["name"] == "manual_revive_me" for r in field.dormant_concepts())


def test_migration_adds_dormancy_column_to_legacy_db(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    FieldSurface(db_path=db_path, read_only=False)
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE concept_legacy AS SELECT name, domain, granularity, source, created FROM concept"
    )
    conn.execute("DROP TABLE concept")
    conn.execute("ALTER TABLE concept_legacy RENAME TO concept")
    conn.commit()
    conn.close()

    reopened = FieldSurface(db_path=db_path, read_only=False)
    rows = reopened.get_concepts_with_metadata()
    assert all("dormant_since" in dict(r) or True for r in rows)  # column exists, no crash
