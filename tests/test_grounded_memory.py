from __future__ import annotations

import nouse


def test_isolated_structured_relations_query_context_and_contradiction(tmp_path):
    brain = nouse.attach(
        db_path=tmp_path / "field.sqlite",
        prefer_http=False,
    )
    brain.add(
        "raw_outputs",
        "supports",
        "reproducibility",
        why="A complete experiment preserves raw outputs and configuration.",
        evidence_score=0.90,
    )
    brain.add(
        "reproducibility",
        "contradicts",
        "untracked_result",
        why="An untracked result cannot be independently reconstructed.",
        evidence_score=0.82,
    )

    source = brain.query("raw_outputs")
    target = brain.query("reproducibility")
    contradiction = brain.check_contradiction(
        "The untracked result is reproducible.", threshold=0.75
    )

    assert source.has_knowledge is True
    assert target.has_knowledge is True
    assert "raw_outputs" in source.context_block()
    assert "reproducibility" in target.context_block()
    assert [(a.src, a.rel, a.tgt) for a in source.axioms] == [
        ("raw_outputs", "supports", "reproducibility"),
    ]
    assert ("reproducibility", "contradicts", "untracked_result") in [
        (a.src, a.rel, a.tgt) for a in target.axioms
    ]
    assert contradiction.recommendation == "flag"
    assert contradiction.has_conflict is True