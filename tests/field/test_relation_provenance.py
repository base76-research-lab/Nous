from pathlib import Path

from nouse.field.surface import (
    PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING,
    FieldSurface,
)


def _field(tmp_path: Path) -> FieldSurface:
    return FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)


def test_model_hypothesis_cannot_bypass_evidence_ceiling(tmp_path):
    field = _field(tmp_path)
    field.add_relation(
        "A", "suggests", "B", why="model output", evidence_score=1.0,
        source_tag="bridge_finder", provenance_class="model_hypothesis",
    )

    relation = field.out_relations("A")[0]
    assert relation["evidence_score"] == PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING
    assert relation["provenance_class"] == "model_hypothesis"


def test_unknown_writer_fails_closed_below_strong_fact_threshold(tmp_path):
    field = _field(tmp_path)
    field.add_relation("A", "claims", "B", why="undeclared writer", evidence_score=1.0)

    relation = field.out_relations("A")[0]
    assert relation["evidence_score"] == PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING
    assert relation["provenance_class"] == "unknown"


def test_observed_source_can_carry_explicit_evidence(tmp_path):
    field = _field(tmp_path)
    field.add_relation(
        "A", "documents", "B", why="named source", evidence_score=0.95,
        source_tag="doi:10.1234/example", provenance_class="observed_source",
        support_refs=("doi:10.1234/example",),
    )

    relation = field.out_relations("A")[0]
    assert relation["evidence_score"] == 0.95
    assert relation["provenance_class"] == "observed_source"


def test_supersession_preserves_declared_provenance_class(tmp_path):
    field = _field(tmp_path)
    field.add_relation(
        "A", "is", "B", why="source", source_tag="source:one",
        evidence_score=0.9, provenance_class="observed_source",
    )
    field.supersede_relation(
        "A", "is", "B", "C", why="new source", source_tag="source:two",
        evidence_score=0.9, provenance_class="observed_source",
    )

    relations = field.out_relations("A")
    assert {row["provenance_class"] for row in relations} == {"observed_source"}


def test_observed_source_without_named_support_fails_closed(tmp_path):
    field = _field(tmp_path)
    field.add_relation(
        "A", "documents", "B", why="unnamed", evidence_score=0.95,
        provenance_class="observed_source",
    )
    assert field.out_relations("A")[0]["evidence_score"] == PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING


def test_source_support_is_deduplicated_and_append_only(tmp_path):
    field = _field(tmp_path)
    relation_id = field.add_relation("A", "documents", "B", why="source")
    assert field.add_source_support(relation_id, "doi:10.1234/example") is True
    assert field.add_source_support(relation_id, "doi:10.1234/example") is False
    assert [row["source_ref"] for row in field.source_support(relation_id)] == ["doi:10.1234/example"]

    with field._sql:
        try:
            field._sql.execute("DELETE FROM relation_source_support WHERE relation_id = ?", (relation_id,))
        except Exception as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError("source support deletion unexpectedly succeeded")


def test_confirmation_creates_sourced_successor_instead_of_rewriting_candidate(tmp_path):
    field = _field(tmp_path)
    candidate_id = field.add_relation(
        "A", "suggests", "B", why="model candidate", evidence_score=1.0,
        provenance_class="model_hypothesis", source_tag="bridge_finder",
    )
    confirmed_id = field.confirm_relation(
        "A", "suggests", "B", source_ref="doi:10.1234/example", evidence_score=0.95,
    )

    rows = field._sql.execute(
        "SELECT id, evidence_score, provenance_class, valid_until, derived_from "
        "FROM relation ORDER BY id"
    ).fetchall()
    assert rows[0]["id"] == candidate_id
    assert rows[0]["evidence_score"] == PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING
    assert rows[0]["valid_until"] is not None
    assert rows[1]["id"] == confirmed_id
    assert rows[1]["provenance_class"] == "observed_source"
    assert rows[1]["evidence_score"] == 0.95
    assert rows[1]["derived_from"] == candidate_id
    assert [row["source_ref"] for row in field.source_support(confirmed_id)] == ["doi:10.1234/example"]
