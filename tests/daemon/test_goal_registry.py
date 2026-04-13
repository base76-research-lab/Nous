"""Tests for daemon.goal_registry — Goal CRUD, persistence, satisfaction."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from nouse.daemon.goal_registry import (
    KIND_CONTRADICTION_RESOLVE,
    KIND_CRYSTALLIZATION,
    KIND_DOMAIN_EXPAND,
    KIND_EVIDENCE_GAP,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_SATISFIED,
    Goal,
    active_goals,
    create_goal,
    evaluate_satisfaction,
    expire_stale_goals,
    goal_by_concepts,
    goal_by_id,
    goal_metrics,
    goals_by_kind,
    load_goals,
    rewrite_goals,
    satisfy_goals,
    update_goal_progress,
)


@pytest.fixture
def tmp_path_goal(tmp_path):
    """Temporary goal registry path."""
    return tmp_path / "test_goals.jsonl"


@pytest.fixture
def sample_goal(tmp_path_goal):
    """Create a sample goal and return (Goal, path)."""
    g = create_goal(
        title="Test: Förstå kvantcomputing",
        kind=KIND_EVIDENCE_GAP,
        priority=0.8,
        target_concepts=["kvantcomputing", "superposition", "qubit"],
        target_domain="physics",
        source="gap_map",
        created_cycle=1,
        deadline_cycle=51,
        satisfaction_criteria={"evidence_floor": 0.45},
        path=tmp_path_goal,
    )
    return g, tmp_path_goal


class TestGoalDataclass:
    def test_default_values(self):
        g = Goal()
        assert g.kind == KIND_EVIDENCE_GAP
        assert g.status == STATUS_ACTIVE
        assert g.priority == 0.5
        assert g.progress == 0.0
        assert g.parent_goal_id is None

    def test_custom_values(self):
        g = Goal(
            id="abc123",
            title="Test goal",
            kind=KIND_CONTRADICTION_RESOLVE,
            priority=0.9,
            target_concepts=["x", "y"],
            target_domain="math",
            source="contradiction",
            created_cycle=5,
        )
        assert g.kind == KIND_CONTRADICTION_RESOLVE
        assert g.priority == 0.9
        assert len(g.target_concepts) == 2


class TestCreateAndLoad:
    def test_create_goal(self, sample_goal):
        g, path = sample_goal
        assert g.id
        assert g.title == "Test: Förstå kvantcomputing"
        assert g.kind == KIND_EVIDENCE_GAP
        assert g.priority == 0.8
        assert g.status == STATUS_ACTIVE
        assert path.exists()

    def test_load_goals(self, sample_goal):
        g, path = sample_goal
        goals = load_goals(path)
        assert len(goals) == 1
        assert goals[0].id == g.id
        assert goals[0].title == g.title

    def test_load_empty(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        goals = load_goals(path)
        assert goals == []


class TestActiveAndKind:
    def test_active_goals(self, sample_goal):
        g, path = sample_goal
        active = active_goals(path)
        assert len(active) == 1
        assert active[0].id == g.id

    def test_active_excludes_satisfied(self, sample_goal):
        g, path = sample_goal
        satisfy_goals([g.id], cycle=2, path=path)
        active = active_goals(path)
        assert len(active) == 0

    def test_goals_by_kind(self, sample_goal):
        g, path = sample_goal
        kind_goals = goals_by_kind(KIND_EVIDENCE_GAP, path)
        assert len(kind_goals) == 1
        other = goals_by_kind(KIND_CONTRADICTION_RESOLVE, path)
        assert len(other) == 0


class TestFindByConcepts:
    def test_goal_by_concepts_overlap(self, sample_goal):
        g, path = sample_goal
        found = goal_by_concepts(["kvantcomputing", "superposition"], path=path)
        assert found is not None
        assert found.id == g.id

    def test_goal_by_concepts_no_match(self, sample_goal):
        _, path = sample_goal
        found = goal_by_concepts(["gravity", "relativity"], path=path)
        assert found is None


class TestProgressAndSatisfaction:
    def test_update_progress(self, sample_goal):
        g, path = sample_goal
        updated = update_goal_progress(g.id, cycle=2, progress=0.6, path=path)
        assert updated is not None
        assert updated.progress == 0.6
        assert updated.updated_cycle == 2

    def test_update_progress_nonexistent(self, tmp_path):
        path = tmp_path / "x.jsonl"
        result = update_goal_progress("nonexistent", cycle=1, progress=0.5, path=path)
        assert result is None

    def test_satisfy_goals(self, sample_goal):
        g, path = sample_goal
        n = satisfy_goals([g.id], cycle=3, path=path)
        assert n == 1
        goals = load_goals(path)
        assert goals[0].status == STATUS_SATISFIED

    def test_satisfy_nonexistent(self, tmp_path):
        path = tmp_path / "x.jsonl"
        # Need at least one goal in registry for rewrite
        create_goal(title="dummy", kind=KIND_EVIDENCE_GAP, priority=0.5,
                     target_concepts=[], target_domain="", source="test",
                     created_cycle=1, deadline_cycle=51, satisfaction_criteria={},
                     path=path)
        n = satisfy_goals(["nonexistent"], cycle=1, path=path)
        assert n == 0


class TestExpireStale:
    def test_expire_stale_goals(self, sample_goal):
        g, path = sample_goal
        # Goal created at cycle 1, deadline 51. Expire at cycle 60.
        n_expired = expire_stale_goals(cycle=60, path=path)
        assert n_expired == 1
        goals = load_goals(path)
        assert goals[0].status == STATUS_EXPIRED

    def test_no_expiry_before_deadline(self, sample_goal):
        _, path = sample_goal
        n_expired = expire_stale_goals(cycle=10, path=path)
        assert n_expired == 0


class TestEvaluateSatisfaction:
    def test_evidence_gap_satisfied(self, sample_goal):
        g, path = sample_goal
        # satisfaction_criteria: evidence_floor=0.45
        from nouse.kernel.brain import Brain
        b = Brain()
        # Skapa noder med hög evidens
        for c in g.target_concepts:
            b.add_node(c, evidence_score=0.7)
        status = evaluate_satisfaction(g, b, cycle=5)
        assert status == "satisfied"

    def test_evidence_gap_progressing(self, sample_goal):
        g, path = sample_goal
        from nouse.kernel.brain import Brain
        b = Brain()
        # Vissa koncept har låg evidens → fortfarande progressing
        b.add_node(g.target_concepts[0], evidence_score=0.5)
        status = evaluate_satisfaction(g, b, cycle=5)
        assert status in ("active", "progressing")


class TestGoalMetrics:
    def test_metrics_with_goals(self, sample_goal):
        g, path = sample_goal
        update_goal_progress(g.id, cycle=2, progress=0.6, path=path)
        m = goal_metrics(path)
        assert m["goals_active"] == 1
        assert m["goals_satisfied_total"] == 0
        assert m["goal_progress_mean"] == pytest.approx(0.6, abs=0.01)

    def test_metrics_empty(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        m = goal_metrics(path)
        assert m["goals_active"] == 0
        assert m["goal_satisfaction_rate"] == 0.0


class TestRewrite:
    def test_rewrite_goals(self, sample_goal):
        g, path = sample_goal
        goals = load_goals(path)
        goals[0].priority = 0.99
        rewrite_goals(goals, path)
        reloaded = load_goals(path)
        assert reloaded[0].priority == 0.99


class TestDeduplication:
    def test_goal_by_concepts_partial_overlap(self, sample_goal):
        g, path = sample_goal
        # 2 of 3 match → overlap = 2/max(2,3) ≈ 0.67 > 0.5 threshold
        found = goal_by_concepts(["kvantcomputing", "superposition"], path=path)
        assert found is not None
        assert found.id == g.id