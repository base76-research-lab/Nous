from __future__ import annotations

from datetime import datetime, timedelta

from nouse.field.surface import FieldSurface

from eval.ablation import (
    NOUS_FULL,
    NOUS_GRAPH_ONLY,
    NOUS_PLUS_CONTRADICTION,
    NOUS_PLUS_EVIDENCE,
    NousFeatureConfig,
    _cosine,
    build_vector_rag_index,
    get_long_context_baseline,
    get_nous_context_ablated,
    query_vector_rag_index,
)


def _mk_field(tmp_path):
    return FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)


def test_nous_graph_only_hides_evidence_annotations(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("epistemics", "requires", "provenance",
                       why="explicit source", evidence_score=0.9)

    ctx = get_nous_context_ablated("epistemics", field, NOUS_GRAPH_ONLY)

    assert "ev=" not in ctx
    assert "epistemics" in ctx and "provenance" in ctx


def test_plus_evidence_shows_and_sorts_by_evidence(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("epistemics", "requires", "weak_support",
                       why="thin source", evidence_score=0.4)
    field.add_relation("epistemics", "requires", "strong_support",
                       why="direct citation", evidence_score=0.95)

    ctx = get_nous_context_ablated("epistemics", field, NOUS_PLUS_EVIDENCE)

    assert "ev=0.95" in ctx
    assert ctx.index("strong_support") < ctx.index("weak_support")


def test_temporal_validity_drops_expired_relations(tmp_path):
    field = _mk_field(tmp_path)
    past = (datetime.utcnow() - timedelta(days=1)).isoformat()
    future = (datetime.utcnow() + timedelta(days=365)).isoformat()
    field.add_relation("epistemics", "relates_to", "expired_fact",
                       why="superseded", evidence_score=0.9, valid_until=past)
    field.add_relation("epistemics", "relates_to", "current_fact",
                       why="still valid", evidence_score=0.9, valid_until=future)

    config_with_temporal = NousFeatureConfig(use_evidence=True, use_temporal_validity=True,
                                              use_contradiction=False, use_plasticity=False)
    config_without_temporal = NousFeatureConfig(use_evidence=True, use_temporal_validity=False,
                                                 use_contradiction=False, use_plasticity=False)

    filtered = get_nous_context_ablated("epistemics", field, config_with_temporal)
    unfiltered = get_nous_context_ablated("epistemics", field, config_without_temporal)

    assert "current_fact" in filtered
    assert "expired_fact" not in filtered
    assert "current_fact" in unfiltered
    assert "expired_fact" in unfiltered


def test_contradiction_annotated_only_when_enabled(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("epistemics", "supports", "claim_a",
                       why="source A", evidence_score=0.8)
    field.add_relation("epistemics", "contradicts", "claim_a",
                       why="source B disagrees", evidence_score=0.8)

    with_flag = get_nous_context_ablated("epistemics", field, NOUS_PLUS_CONTRADICTION)
    without_flag = get_nous_context_ablated("epistemics", field, NOUS_PLUS_EVIDENCE)

    assert "motsägelse" in with_flag
    assert "motsägelse" not in without_flag


def test_plasticity_sorts_by_hebbian_strength_not_evidence(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("epistemics", "relates_to", "high_evidence_low_strength",
                       why="cited once", evidence_score=0.95, strength=1.0)
    field.add_relation("epistemics", "relates_to", "low_evidence_high_strength",
                       why="cited once", evidence_score=0.5, strength=3.0)

    plastic_ctx = get_nous_context_ablated("epistemics", field, NOUS_FULL)
    evidence_only_ctx = get_nous_context_ablated("epistemics", field, NOUS_PLUS_EVIDENCE)

    assert plastic_ctx.index("low_evidence_high_strength") < plastic_ctx.index("high_evidence_low_strength")
    assert evidence_only_ctx.index("high_evidence_low_strength") < evidence_only_ctx.index("low_evidence_high_strength")


def test_long_context_baseline_respects_char_budget(tmp_path):
    field = _mk_field(tmp_path)
    for i in range(20):
        field.add_concept(f"concept_{i}", "test_domain", source="unit_test")
        field.upsert_concept_knowledge(
            f"concept_{i}", summary="x" * 200, claims=[], evidence_refs=[], uncertainty=0.5,
        )

    ctx = get_long_context_baseline(field, max_chars=500)

    assert len(ctx) <= 500 + 250  # one line's worth of slack over the budget check


def test_cosine_identical_vectors_is_one():
    assert _cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0


def test_cosine_orthogonal_vectors_is_zero():
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_build_vector_rag_index_returns_none_when_embedder_fails(tmp_path, monkeypatch):
    field = _mk_field(tmp_path)
    field.add_concept("epistemics", "test_domain", source="unit_test")

    class _FailingEmbedder:
        def __init__(self, *a, **kw):
            pass

        def embed_texts(self, texts):
            raise RuntimeError("ollama unavailable")

    monkeypatch.setattr("nouse.embeddings.ollama_embed.OllamaEmbedder", _FailingEmbedder)

    assert build_vector_rag_index(field) is None


def test_query_vector_rag_index_handles_missing_index_gracefully():
    assert query_vector_rag_index(None, "any question") == "[Vector RAG: tomt index]"
