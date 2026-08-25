from __future__ import annotations

import asyncio

import pytest

import nouse.inject as inject
from nouse.search.escalator import escalate_query


def test_rows_to_axioms_distinguishes_source_backed_from_hebbian_estimate():
    """_rows_to_axioms() must not silently conflate a real evidence_score
    with a Hebbian-strength-derived guess — source_support tells them apart
    even though `evidence` keeps its old blended value for backward compat.
    See docs/EVIDENCE_MODEL.md."""
    rows = [
        {
            "target": "raw_outputs", "type": "requires", "why": "explicit citation",
            "strength": 1.0, "evidence_score": 0.9, "assumption_flag": False,
            "source_tag": "auto",
        },
        {
            "target": "citation_count", "type": "correlates_with", "why": "",
            "strength": 2.2, "evidence_score": None, "assumption_flag": False,
            "source_tag": "auto",
        },
    ]

    source_backed, hebbian_only = inject._rows_to_axioms("reproducibility", rows)

    assert source_backed.source_support == 0.9
    assert source_backed.evidence == 0.9

    assert hebbian_only.source_support is None
    assert hebbian_only.evidence == pytest.approx(0.45 + (2.2 - 1.0) * 0.25)


def test_rows_to_axioms_maps_domain_bootstrap_source_tag_to_parametric_hypothesis():
    rows = [{
        "target": "concept_b", "type": "relates_to", "why": "bootstrapped from model weights",
        "strength": 1.0, "evidence_score": 0.65, "assumption_flag": False,
        "source_tag": "domain_bootstrap",
    }]

    [axiom] = inject._rows_to_axioms("concept_a", rows)

    assert axiom.provenance_class == "parametric_hypothesis"


def test_rows_to_axioms_defaults_unset_source_tag_to_external_source():
    rows = [{
        "target": "concept_b", "type": "relates_to", "why": "explicit source",
        "strength": 1.0, "evidence_score": 0.8, "assumption_flag": False,
    }]

    [axiom] = inject._rows_to_axioms("concept_a", rows)

    assert axiom.provenance_class == "external_source"


def test_confidence_breakdown_separates_source_support_hebbian_and_bootstrap_share():
    strong_source_backed = inject.Axiom(
        src="a", rel="r", tgt="b", evidence=0.9, flagged=False,
        source_support=0.9, strength=1.0, provenance_class="external_source",
    )
    strong_hebbian_only = inject.Axiom(
        src="a", rel="r", tgt="c", evidence=0.8, flagged=False,
        source_support=None, strength=2.5, provenance_class="external_source",
    )
    bootstrap_axiom = inject.Axiom(
        src="a", rel="r", tgt="d", evidence=0.65, flagged=False,
        source_support=0.65, provenance_class="parametric_hypothesis",
    )
    all_axioms = [strong_source_backed, strong_hebbian_only, bootstrap_axiom]
    strong = [strong_source_backed, strong_hebbian_only]

    breakdown = inject._compute_confidence_breakdown(all_axioms, strong)

    assert breakdown["source_backed_fraction"] == pytest.approx(0.5)
    assert breakdown["mean_source_support"] == pytest.approx(0.9)
    assert breakdown["mean_hebbian_strength"] == pytest.approx((1.0 + 2.5) / 2)
    assert breakdown["parametric_hypothesis_fraction"] == pytest.approx(1 / 3)


def test_confidence_breakdown_empty_when_no_axioms():
    breakdown = inject._compute_confidence_breakdown([], [])

    assert breakdown == {
        "source_backed_fraction": 0.0,
        "mean_source_support": 0.0,
        "mean_hebbian_strength": 0.0,
        "parametric_hypothesis_fraction": 0.0,
    }


def test_escalate_query_flags_mixed_parametric_hypothesis_content(tmp_path):
    """A query can clear the confidence threshold on a real, source-backed
    axiom while the graph also holds an unrelated domain_bootstrap guess for
    the same concept. escalate_query must not silently return that mix as
    plain external grounding — contains_parametric_hypothesis has to say so,
    per the circularity risk flagged in the 2026-08-25 repo review."""
    brain = inject.NouseBrain(db_path=tmp_path / "field.sqlite")
    brain._field.add_relation(
        "epistemic_grounding", "requires", "source_provenance",
        why="Direct citation of the source document.", evidence_score=0.9,
        source_tag="verified_source",
    )
    brain._field.add_relation(
        "epistemic_grounding", "relates_to", "model_self_report",
        why="bootstrapped from model weights", evidence_score=0.99,
        source_tag="domain_bootstrap",
    )

    result = asyncio.run(
        escalate_query("epistemic_grounding", brain, threshold=0.5, learn=False)
    )

    assert result.escalated is False  # the source-backed axiom alone clears threshold
    assert result.contains_parametric_hypothesis is True

    axioms = brain.recall_axioms("epistemic_grounding")
    bootstrap_axiom = next(a for a in axioms if a.tgt == "model_self_report")
    assert bootstrap_axiom.provenance_class == "parametric_hypothesis"
    assert bootstrap_axiom.is_strong is False
    assert bootstrap_axiom.evidence <= 0.70  # capped despite evidence_score=0.99 requested


def test_escalate_query_does_not_flag_purely_external_content(tmp_path):
    brain = inject.NouseBrain(db_path=tmp_path / "field.sqlite")
    brain._field.add_relation(
        "epistemic_grounding", "requires", "source_provenance",
        why="Direct citation of the source document.", evidence_score=0.9,
        source_tag="verified_source",
    )

    result = asyncio.run(
        escalate_query("epistemic_grounding", brain, threshold=0.5, learn=False)
    )

    assert result.escalated is False
    assert result.contains_parametric_hypothesis is False
