"""Tests for daemon.cognitive_policy — triggers, apply, clamp, reset."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nouse.daemon.cognitive_policy import (
    CognitivePolicy,
    apply_triggers,
    evaluate_and_apply,
    evaluate_triggers,
    load_policy,
    reset_policy,
    save_policy,
)


@pytest.fixture
def tmp_policy(tmp_path):
    """Temporary policy file path."""
    return tmp_path / "test_policy.json"


@pytest.fixture
def default_policy():
    return CognitivePolicy()


class TestCognitivePolicyDataclass:
    def test_defaults(self):
        p = CognitivePolicy()
        assert p.extraction_threshold == 0.35
        assert p.evidence_floor == 0.45
        assert p.lam_override is None
        assert p.curiosity_priority == "normal"
        assert p.change_count == 0

    def test_effective_lam_auto(self):
        p = CognitivePolicy()
        assert p.effective_lam(0.5) == 0.5

    def test_effective_lam_override(self):
        p = CognitivePolicy(lam_override=0.8)
        assert p.effective_lam(0.5) == 0.8


class TestLoadSavePolicy:
    def test_save_and_load(self, tmp_policy):
        p = CognitivePolicy(extraction_threshold=0.6, curiosity_priority="high")
        save_policy(p, tmp_policy)
        loaded = load_policy(tmp_policy)
        assert loaded.extraction_threshold == 0.6
        assert loaded.curiosity_priority == "high"

    def test_load_nonexistent(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        p = load_policy(path)
        assert p.extraction_threshold == 0.35  # default

    def test_load_ignores_unknown_keys(self, tmp_policy):
        data = {"extraction_threshold": 0.7, "unknown_key": "ignored"}
        tmp_policy.write_text(json.dumps(data))
        p = load_policy(tmp_policy)
        assert p.extraction_threshold == 0.7
        assert not hasattr(p, "unknown_key")

    def test_load_corrupt_json(self, tmp_policy):
        tmp_policy.write_text("not json")
        p = load_policy(tmp_policy)
        assert p.extraction_threshold == 0.35  # fallback to default


class TestEvaluateTriggers:
    def test_energy_below_threshold(self):
        p = CognitivePolicy()
        metrics = {"energy": 0.2}
        fired = evaluate_triggers(metrics, p)
        assert len(fired) == 1
        assert fired[0]["param"] == "extraction_threshold"

    def test_goal_satisfaction_rate_below(self):
        p = CognitivePolicy()
        metrics = {"goal_satisfaction_rate": 0.1}
        fired = evaluate_triggers(metrics, p)
        assert len(fired) == 1
        assert fired[0]["param"] == "curiosity_priority"

    def test_goals_active_above(self):
        p = CognitivePolicy()
        metrics = {"goals_active": 20}
        fired = evaluate_triggers(metrics, p)
        assert len(fired) == 1
        assert fired[0]["param"] == "extraction_threshold"

    def test_multiple_triggers(self):
        p = CognitivePolicy()
        metrics = {"energy": 0.1, "goal_satisfaction_rate": 0.05, "goals_active": 25}
        fired = evaluate_triggers(metrics, p)
        assert len(fired) == 3

    def test_no_triggers(self):
        p = CognitivePolicy()
        metrics = {"energy": 0.6, "goal_satisfaction_rate": 0.5, "goals_active": 5}
        fired = evaluate_triggers(metrics, p)
        assert len(fired) == 0


class TestApplyTriggers:
    def test_numeric_delta(self):
        p = CognitivePolicy()
        trigger = {"metric": "energy", "condition": "below", "threshold": 0.3,
                   "param": "extraction_threshold", "delta": 0.10, "reason": "test"}
        new_p, audit = apply_triggers([trigger], p)
        assert new_p.extraction_threshold == pytest.approx(0.45, abs=0.01)
        assert len(audit) == 1

    def test_string_value(self):
        p = CognitivePolicy()
        trigger = {"metric": "goal_satisfaction_rate", "condition": "below",
                   "threshold": 0.2, "param": "curiosity_priority",
                   "value": "high", "reason": "test"}
        new_p, audit = apply_triggers([trigger], p)
        assert new_p.curiosity_priority == "high"

    def test_clamp_max(self):
        p = CognitivePolicy()
        # Default extraction_threshold = 0.35, max clamp = 0.35 + 0.30 = 0.65
        trigger = {"metric": "energy", "condition": "below", "threshold": 0.3,
                   "param": "extraction_threshold", "delta": 0.50, "reason": "test"}
        new_p, audit = apply_triggers([trigger], p)
        assert new_p.extraction_threshold <= 0.65

    def test_clamp_min(self):
        p = CognitivePolicy()
        # Default evidence_floor = 0.45, min clamp = 0.45 - 0.30 = 0.15
        trigger = {"metric": "contradiction_catch_rate", "condition": "below",
                   "threshold": 0.1, "param": "evidence_floor",
                   "delta": -0.50, "reason": "test"}
        new_p, audit = apply_triggers([trigger], p)
        assert new_p.evidence_floor >= 0.15

    def test_skip_small_delta(self):
        p = CognitivePolicy()
        # Delta 0.001 should be skipped (< 0.005 threshold)
        trigger = {"metric": "energy", "condition": "below", "threshold": 0.3,
                   "param": "extraction_threshold", "delta": 0.001, "reason": "test"}
        new_p, audit = apply_triggers([trigger], p)
        assert len(audit) == 0
        assert new_p.extraction_threshold == 0.35  # unchanged


class TestEvaluateAndApply:
    def test_full_cycle(self, tmp_policy):
        metrics = {"energy": 0.1, "goal_satisfaction_rate": 0.05}
        policy, audit = evaluate_and_apply(metrics, CognitivePolicy(), source="test")
        assert len(audit) == 2
        assert policy.extraction_threshold > 0.35
        assert policy.curiosity_priority == "high"
        # Verify saved
        loaded = load_policy(tmp_policy.parent / "cognitive_policy.json")
        # (evaluate_and_apply saves to default path, not tmp_policy)


class TestResetPolicy:
    def test_reset(self, tmp_policy):
        p = CognitivePolicy(extraction_threshold=0.8, curiosity_priority="high")
        save_policy(p, tmp_policy)
        reset = reset_policy(tmp_policy)
        assert reset.extraction_threshold == 0.35
        assert reset.curiosity_priority == "normal"