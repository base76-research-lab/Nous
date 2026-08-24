"""Tests for goal_generator's user_relevance signal — wiring curiosity
priority to scope="user_model" (Björns profil-subgraf), from the
2026-08-24 conversation: "systemet bör känna mig ... för att vara mig
behjälplig, prediktiv"."""
from __future__ import annotations

from pathlib import Path

from nouse.daemon.goal_generator import _user_relevance, compute_priority
from nouse.field.surface import FieldSurface


def _mk_field(tmp_path: Path) -> FieldSurface:
    return FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)


def test_compute_priority_weights_sum_to_full_scale():
    """All five signals maxed must saturate at 1.0, not overshoot."""
    priority = compute_priority(
        topological_urgency=1.0, eval_trend_signal=1.0, drive_alignment=1.0,
        operator_feedback=1.0, user_relevance=1.0,
    )
    assert priority == 1.0


def test_compute_priority_user_relevance_alone_contributes_020():
    priority = compute_priority(user_relevance=1.0)
    assert abs(priority - 0.20) < 1e-9


def test_compute_priority_defaults_to_zero_without_any_signal():
    assert compute_priority() == 0.0


def test_user_relevance_zero_when_profile_not_seeded(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("random topic", domain="misc")
    assert _user_relevance(field, ["random topic"]) == 0.0


def test_user_relevance_zero_for_empty_concepts(tmp_path):
    field = _mk_field(tmp_path)
    assert _user_relevance(field, []) == 0.0


def test_user_relevance_full_score_for_direct_user_model_concept(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation(
        "Björn Wikström", "kommunikationsstil", "Be direct.",
        why="test", scope_src="user_model", scope_tgt="user_model",
    )
    assert _user_relevance(field, ["Be direct."]) == 1.0


def test_user_relevance_full_score_for_one_hop_neighbor(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation(
        "Björn Wikström", "kommunikationsstil", "Be direct.",
        why="test", scope_src="user_model", scope_tgt="user_model",
    )
    # A concept connected to the user_model hub, but not itself scoped.
    field.add_relation("some domain concept", "relates_to", "Björn Wikström", why="test")
    assert _user_relevance(field, ["some domain concept"]) == 1.0


def test_user_relevance_zero_for_unrelated_concept(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation(
        "Björn Wikström", "kommunikationsstil", "Be direct.",
        why="test", scope_src="user_model", scope_tgt="user_model",
    )
    field.add_concept("quantum biology", domain="physics")
    assert _user_relevance(field, ["quantum biology"]) == 0.0


def test_user_relevance_averages_across_multiple_concepts(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation(
        "Björn Wikström", "kommunikationsstil", "Be direct.",
        why="test", scope_src="user_model", scope_tgt="user_model",
    )
    field.add_concept("unrelated topic", domain="misc")
    score = _user_relevance(field, ["Be direct.", "unrelated topic"])
    assert abs(score - 0.5) < 1e-9
