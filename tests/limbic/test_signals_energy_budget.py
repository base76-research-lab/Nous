"""Tests for limbic.signals energy_budget — Fas 3 punkt 10, docs/NOUS_NEXT_GENERATION_PLAN.md."""
from __future__ import annotations

from nouse.limbic.signals import (
    ENERGY_BUDGET_BASELINE,
    LimbicState,
    run_limbic_cycle,
    update_energy_budget,
)


def test_default_energy_budget_is_baseline():
    state = LimbicState()
    assert state.energy_budget == ENERGY_BUDGET_BASELINE


def test_calls_deplete_energy_budget():
    state = LimbicState()
    update_energy_budget(state, llm_calls=20)
    assert state.energy_budget < ENERGY_BUDGET_BASELINE


def test_more_calls_deplete_more():
    light = LimbicState()
    heavy = LimbicState()
    update_energy_budget(light, llm_calls=5)
    update_energy_budget(heavy, llm_calls=50)
    assert heavy.energy_budget < light.energy_budget


def test_zero_calls_recovers_toward_baseline():
    state = LimbicState(energy_budget=0.2)
    update_energy_budget(state, llm_calls=0)
    assert state.energy_budget > 0.2
    assert state.energy_budget <= ENERGY_BUDGET_BASELINE


def test_sustained_heavy_load_converges_above_zero_not_negative():
    state = LimbicState()
    for _ in range(200):
        update_energy_budget(state, llm_calls=100)
    assert 0.0 <= state.energy_budget <= ENERGY_BUDGET_BASELINE


def test_energy_budget_never_exceeds_baseline_after_many_idle_cycles():
    state = LimbicState(energy_budget=0.5)
    for _ in range(1000):
        update_energy_budget(state, llm_calls=0)
    assert state.energy_budget <= ENERGY_BUDGET_BASELINE


def test_run_limbic_cycle_wires_llm_calls_into_energy_budget():
    state = LimbicState()
    state = run_limbic_cycle(
        state,
        new_relations=5,
        discoveries=0,
        bisociation_candidates=0,
        novel_domains=0,
        active_domains=3,
        llm_calls=40,
    )
    assert state.energy_budget < ENERGY_BUDGET_BASELINE


def test_run_limbic_cycle_defaults_llm_calls_to_zero():
    state = LimbicState()
    state = run_limbic_cycle(
        state,
        new_relations=0,
        discoveries=0,
        bisociation_candidates=0,
        novel_domains=0,
        active_domains=1,
    )
    assert state.energy_budget == ENERGY_BUDGET_BASELINE
