from __future__ import annotations

from pathlib import Path

from nouse.field.surface import DEFAULT_SCOPE, SENSITIVE_SCOPES, FieldSurface


def _mk_field(tmp_path: Path) -> FieldSurface:
    return FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)


def test_add_concept_stores_known_scope(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("blodtryck_logg", domain="halsa", scope="personal_health")

    row = field.get_concepts_with_metadata()
    match = next(r for r in row if r["id"] == "blodtryck_logg")
    assert match["scope"] == "personal_health"


def test_add_concept_falls_back_to_default_scope_for_unknown_value(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("some_node", domain="x", scope="not_a_real_scope")

    row = field.get_concepts_with_metadata()
    match = next(r for r in row if r["id"] == "some_node")
    assert match["scope"] == DEFAULT_SCOPE


def test_add_concept_defaults_to_general_when_scope_omitted(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("unscoped_node", domain="x")

    row = field.get_concepts_with_metadata()
    match = next(r for r in row if r["id"] == "unscoped_node")
    assert match["scope"] == "general"


def test_add_relation_threads_scope_to_both_endpoints(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation(
        "vikt_23_07", "relates_to", "vikt_20_08",
        why="baseline", source_tag="unit_test",
        scope_src="personal_health", scope_tgt="personal_health",
    )

    rows = field.get_concepts_with_metadata()
    src = next(r for r in rows if r["id"] == "vikt_23_07")
    tgt = next(r for r in rows if r["id"] == "vikt_20_08")
    assert src["scope"] == "personal_health"
    assert tgt["scope"] == "personal_health"


def test_set_concept_scope_updates_existing_concept(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("reclassify_me", domain="x")

    changed = field.set_concept_scope("reclassify_me", "personal_health")

    assert changed is True
    row = next(r for r in field.get_concepts_with_metadata() if r["id"] == "reclassify_me")
    assert row["scope"] == "personal_health"


def test_concepts_exclude_scopes_filters_out_sensitive_concepts(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("health_note", domain="halsa", scope="personal_health")
    field.add_concept("public_note", domain="general_topic", scope="general")

    visible = field.concepts(exclude_scopes=SENSITIVE_SCOPES)
    names = {r["name"] for r in visible}

    assert "public_note" in names
    assert "health_note" not in names


def test_concepts_without_exclude_scopes_returns_everything(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("health_note", domain="halsa", scope="personal_health")

    visible = field.concepts()
    names = {r["name"] for r in visible}
    assert "health_note" in names


def test_domain_tda_profile_excludes_sensitive_scope_concepts(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation(
        "blodtryck", "part_of", "halsa_domain_marker",
        why="x", source_tag="unit_test", domain_src="halsa_test_domain",
        domain_tgt="halsa_test_domain", scope_src="personal_health", scope_tgt="personal_health",
    )

    profile = field.domain_tda_profile("halsa_test_domain")

    assert profile["n_concepts"] == 0


def test_migration_adds_scope_column_with_general_default_to_legacy_db(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    FieldSurface(db_path=db_path, read_only=False)
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE concept_legacy AS "
        "SELECT name, domain, granularity, source, created, dormant_since FROM concept"
    )
    conn.execute("DROP TABLE concept")
    conn.execute("ALTER TABLE concept_legacy RENAME TO concept")
    conn.commit()
    conn.close()

    reopened = FieldSurface(db_path=db_path, read_only=False)
    reopened.add_concept("post_migration_node", domain="x")
    row = next(r for r in reopened.get_concepts_with_metadata() if r["id"] == "post_migration_node")
    assert row["scope"] == "general"


def test_research_plg_is_sensitive():
    """Regression guard for the 2026-08-25 gap: research_plg (Björns eget
    forskningsspann) var tidigare INTE i SENSITIVE_SCOPES, vilket gjorde det
    berättigat att skickas till Cerebras/OpenRouter via
    bisociative_solver.py::scheduled_bisociation_pass() — i strid med regeln
    att IIC-forskning aldrig lämnar disken utan explicit tillåtelse."""
    assert "research_plg" in SENSITIVE_SCOPES


def test_iic_general_and_computer_general_are_sensitive():
    assert "iic_general" in SENSITIVE_SCOPES
    assert "computer_general" in SENSITIVE_SCOPES


def test_research_plg_scoped_concept_excluded_from_external_facing_query(tmp_path):
    """Functional proof, not just set membership: a research_plg concept
    must not appear in the same filtered result personal_health already
    doesn't — this is the exact call shape /api/context and
    bisociative_solver.py::_search_nouse use."""
    field = _mk_field(tmp_path)
    field.add_concept("plg_finding", domain="sociology", scope="research_plg")
    field.add_concept("public_note", domain="general_topic", scope="general")

    visible = field.concepts(exclude_scopes=SENSITIVE_SCOPES)
    names = {r["name"] for r in visible}

    assert "public_note" in names
    assert "plg_finding" not in names


def test_iic_general_and_computer_general_scopes_are_accepted_not_downgraded(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("iic_node", domain="x", scope="iic_general")
    field.add_concept("computer_node", domain="x", scope="computer_general")

    rows = {r["id"]: r["scope"] for r in field.get_concepts_with_metadata()}
    assert rows["iic_node"] == "iic_general"
    assert rows["computer_node"] == "computer_general"
