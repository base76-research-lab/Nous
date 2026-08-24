"""Tests for predictive coding as a decision driver — Fas 3 punkt 8,
docs/NOUS_NEXT_GENERATION_PLAN.md. Noradrenaline (surprise) rising above a
threshold must trigger a real HITL research task, not just the existing
UI-only limbic_spike_event telemetry."""
from __future__ import annotations

from pathlib import Path

from nouse.daemon import research_queue
from nouse.daemon.hitl import create_interrupt, pending_interrupt_for_task
from nouse.daemon.main import (
    _predictive_surprise_seed_task,
    _predictive_surprise_should_trigger,
)
from nouse.daemon.research_queue import enqueue_gap_tasks, pause_task_for_hitl
from nouse.field.surface import FieldSurface


def test_no_trigger_when_below_threshold():
    assert not _predictive_surprise_should_trigger(0.3, 0.5, threshold=0.75)


def test_no_trigger_when_sustained_above_threshold():
    """Already-high noradrenaline staying high must not re-fire every
    cycle — only a genuine rising edge across the threshold counts."""
    assert not _predictive_surprise_should_trigger(0.8, 0.85, threshold=0.75)


def test_triggers_on_rising_edge_across_threshold():
    assert _predictive_surprise_should_trigger(0.6, 0.8, threshold=0.75)


def test_no_trigger_exactly_at_threshold_boundary():
    assert not _predictive_surprise_should_trigger(0.75, 0.75, threshold=0.75)


def test_seed_task_summarizes_surprising_domain_pairs():
    candidates = [
        {"domain_a": "topologi", "domain_b": "musikteori"},
        {"domain_a": "termodynamik", "domain_b": "ekonomi"},
    ]
    task = _predictive_surprise_seed_task(candidates, 0.5, 0.9, threshold=0.75)

    assert task["gap_type"] == "predictive_surprise"
    assert task["domain"] == "topologi"
    assert set(task["concepts"]) == {"topologi", "musikteori", "termodynamik", "ekonomi"}
    assert "topologi" in task["query"]
    assert "0.90" in task["rationale"] or "0.9" in task["rationale"]
    assert task["priority"] == 0.9


def test_seed_task_handles_no_candidates_gracefully():
    task = _predictive_surprise_seed_task([], 0.5, 0.9, threshold=0.75)
    assert task["domain"] == "okänd"
    assert task["concepts"] == []
    assert "okänt" in task["query"]


def test_seed_task_priority_clamped_to_one():
    task = _predictive_surprise_seed_task([], 0.5, 1.4, threshold=0.75)
    assert task["priority"] == 1.0


def test_seed_task_without_field_has_no_relevance_boost():
    """Backward compatible: field=None (default, e.g. every test above
    that doesn't pass it) must behave exactly as before this feature."""
    task = _predictive_surprise_seed_task(
        [{"domain_a": "topologi", "domain_b": "musikteori"}], 0.5, 0.8, threshold=0.75,
    )
    assert task["priority"] == 0.8
    assert "Björn-relevans-boost" not in task["rationale"]


def test_seed_task_boosts_priority_when_domains_relate_to_user_model(tmp_path: Path):
    field = FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)
    field.add_relation(
        "Björn Wikström", "arbetssätt", "topologi",
        why="test", scope_src="user_model", scope_tgt="user_model",
    )
    task = _predictive_surprise_seed_task(
        [{"domain_a": "topologi", "domain_b": "musikteori"}], 0.5, 0.8,
        threshold=0.75, field=field,
    )
    assert task["priority"] > 0.8
    assert "Björn-relevans-boost" in task["rationale"]


def test_seed_task_no_boost_when_domains_unrelated_to_user_model(tmp_path: Path):
    field = FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)
    field.add_relation(
        "Björn Wikström", "arbetssätt", "helt annan sak",
        why="test", scope_src="user_model", scope_tgt="user_model",
    )
    task = _predictive_surprise_seed_task(
        [{"domain_a": "topologi", "domain_b": "musikteori"}], 0.5, 0.8,
        threshold=0.75, field=field,
    )
    assert task["priority"] == 0.8


def test_end_to_end_seed_task_becomes_a_pending_hitl_interrupt(monkeypatch, tmp_path: Path):
    """The full chain the daemon loop drives: seed task -> queued ->
    HITL interrupt -> task paused awaiting approval."""
    monkeypatch.setattr(research_queue, "detect_knowledge_gaps", lambda field, max_candidates=10: [])
    queue_path = tmp_path / "queue.json"
    hitl_path = tmp_path / "hitl.json"

    seed = _predictive_surprise_seed_task(
        [{"domain_a": "neurovetenskap", "domain_b": "poesi"}], 0.6, 0.9, threshold=0.75,
    )
    new_tasks = enqueue_gap_tasks(
        field=object(), max_new=1, seed_tasks=[seed], detect_gaps=False, path=queue_path,
    )
    assert len(new_tasks) == 1
    task = new_tasks[0]
    assert task["gap_type"] == "predictive_surprise"

    interrupt = create_interrupt(
        task=task, reason="Predictive surprise: 0.60 → 0.90", category="predictive_surprise",
        path=hitl_path,
    )
    assert interrupt["category"] == "predictive_surprise"

    paused = pause_task_for_hitl(
        int(task["id"]), interrupt_id=int(interrupt["id"]), reason="test", path=queue_path,
    )
    assert paused["status"] == "awaiting_approval"
    assert paused["hitl_interrupt_id"] == int(interrupt["id"])
    assert pending_interrupt_for_task(int(task["id"]), path=hitl_path) is not None
