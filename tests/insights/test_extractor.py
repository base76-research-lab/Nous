from __future__ import annotations

import json
from pathlib import Path

from nouse.field.surface import FieldSurface
from nouse.insights import (
    extract_insight_candidates,
    promote_insight_candidates,
    save_insight_candidates,
)


def _seed_field(db_path: Path) -> FieldSurface:
    field = FieldSurface(db_path=db_path)
    field.add_relation(
        "attention",
        "modulates",
        "token relevance",
        why="attention alters contextual weight",
        evidence_score=0.86,
        domain_src="llm",
        domain_tgt="llm",
    )
    field.add_relation(
        "attention",
        "modulates",
        "token relevance",
        why="replicated in benchmark runs",
        evidence_score=0.84,
        domain_src="llm",
        domain_tgt="llm",
    )
    field.add_relation(
        "attention",
        "influences",
        "working memory",
        why="shared gating dynamics",
        evidence_score=0.78,
        domain_src="llm",
        domain_tgt="cognition",
    )
    field.add_relation(
        "attention",
        "influences",
        "salience mapping",
        why="cross-domain signal routing",
        evidence_score=0.74,
        domain_src="llm",
        domain_tgt="neuroscience",
    )
    return field


def test_extract_insights_yields_relation_and_bridge_candidates(tmp_path: Path):
    field = _seed_field(tmp_path / "field.sqlite")
    result = extract_insight_candidates(
        field,
        limit=1000,
        top_k=8,
        min_evidence=0.50,
        include_bridges=True,
    )

    candidates = result.get("candidates") or []
    assert int(result.get("total_relation_rows", 0) or 0) >= 4
    assert candidates
    assert any(c.get("kind") == "relation_pattern" for c in candidates)
    assert any(c.get("kind") == "domain_bridge" for c in candidates)
    assert all(0.0 <= float(c.get("score", 0.0)) <= 1.0 for c in candidates)
    first = candidates[0]
    basis = first.get("basis")
    assert isinstance(basis, dict)
    assert isinstance(basis.get("score_components"), dict)
    refs = first.get("basis_evidence_refs")
    assert isinstance(refs, list)
    assert refs


def test_save_and_promote_insights(tmp_path: Path):
    field = _seed_field(tmp_path / "field.sqlite")
    result = extract_insight_candidates(
        field,
        limit=1000,
        top_k=5,
        min_evidence=0.50,
        include_bridges=True,
    )
    candidates = result.get("candidates") or []

    save_path = tmp_path / "memory" / "insights.jsonl"
    save_result = save_insight_candidates(candidates, destination=save_path, source="test")
    assert int(save_result.get("written", 0) or 0) == len(candidates)
    assert save_path.exists()
    first_line = save_path.read_text(encoding="utf-8").splitlines()[0]
    first = json.loads(first_line)
    assert first.get("source") == "test"
    assert first.get("statement")

    promote_result = promote_insight_candidates(
        field,
        candidates,
        max_items=5,
        min_score=0.0,
    )
    assert int(promote_result.get("promoted", 0) or 0) >= 1
    knowledge = field.concept_knowledge("attention")
    claims = [str(x) for x in (knowledge.get("claims") or [])]
    evidence_refs = [str(x) for x in (knowledge.get("evidence_refs") or [])]
    assert any("attention" in claim.lower() for claim in claims)
    assert any(ref.startswith("insight:") for ref in evidence_refs)
