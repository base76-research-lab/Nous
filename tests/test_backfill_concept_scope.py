from __future__ import annotations

import json

from scripts.backfill_concept_scope import derive_scope_for_concept, run_backfill
from nouse.field.surface import FieldSurface


def _evidence(*paths: str) -> str:
    return json.dumps([f"relation_source:{p}" for p in paths] + ["why:something"])


def test_derive_scope_returns_none_without_relation_source():
    assert derive_scope_for_concept(json.dumps(["why:no source cited"])) is None
    assert derive_scope_for_concept(None) is None
    assert derive_scope_for_concept("not json") is None


def test_derive_scope_matches_a_single_iic_source():
    ev = _evidence("/home/bjorn/IIC/01_PROJECTS/foo/notes.md")
    assert derive_scope_for_concept(ev) == "iic_general"


def test_derive_scope_prefers_the_sensitive_scope_when_sources_mix():
    """A concept can cite sources from more than one path. If any of them
    is sensitive, the concept must be classified sensitive — never let a
    single 'safe-looking' source outvote a genuinely sensitive one."""
    ev = _evidence(
        "/home/bjorn/Work/nous/README.md",  # nous_system, not sensitive
        "/home/bjorn/IIC/02_LIBRARY/RESEARCH/papers/foo.md",  # research_plg, sensitive
    )
    assert derive_scope_for_concept(ev) == "research_plg"


def test_derive_scope_falls_back_to_first_candidate_when_none_are_sensitive():
    ev = _evidence("/home/bjorn/Work/nous/README.md", "/home/bjorn/Work/nous/docs/x.md")
    assert derive_scope_for_concept(ev) == "nous_system"


def _mk_field(tmp_path):
    return FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)


def test_run_backfill_dry_run_reports_without_writing(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("plg_finding", domain="sociology")  # defaults to scope="general"
    field.upsert_concept_knowledge(
        "plg_finding",
        summary="x", claims=[], uncertainty=0.5,
        evidence_refs=["relation_source:/home/bjorn/IIC/02_LIBRARY/RESEARCH/papers/foo.md"],
    )

    stats = run_backfill(field, apply=False)

    assert stats["reclassified"] == 1
    assert stats["by_new_scope"]["research_plg"] == 1
    row = next(r for r in field.get_concepts_with_metadata() if r["id"] == "plg_finding")
    assert row["scope"] == "general"  # unchanged — dry run


def test_run_backfill_apply_writes_the_new_scope(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("plg_finding", domain="sociology")
    field.upsert_concept_knowledge(
        "plg_finding",
        summary="x", claims=[], uncertainty=0.5,
        evidence_refs=["relation_source:/home/bjorn/IIC/02_LIBRARY/RESEARCH/papers/foo.md"],
    )

    stats = run_backfill(field, apply=True)

    assert stats["reclassified"] == 1
    row = next(r for r in field.get_concepts_with_metadata() if r["id"] == "plg_finding")
    assert row["scope"] == "research_plg"


def test_run_backfill_never_touches_already_scoped_concepts(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("already_health", domain="halsa", scope="personal_health")
    field.upsert_concept_knowledge(
        "already_health",
        summary="x", claims=[], uncertainty=0.5,
        evidence_refs=["relation_source:/home/bjorn/Work/nous/README.md"],  # would derive nous_system
    )

    stats = run_backfill(field, apply=True)

    assert stats["checked"] == 0  # never selected — scope wasn't 'general'
    row = next(r for r in field.get_concepts_with_metadata() if r["id"] == "already_health")
    assert row["scope"] == "personal_health"  # unchanged


def test_run_backfill_counts_no_signal_separately_from_reclassified(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("orphan", domain="x")  # no evidence_refs at all
    field.upsert_concept_knowledge("orphan", summary="x", claims=[], evidence_refs=[], uncertainty=0.5)

    stats = run_backfill(field, apply=False)

    assert stats["no_signal"] == 1
    assert stats["reclassified"] == 0
