from __future__ import annotations

from eval.run_eval import _provider_name_for_model, estimate_run_cost_usd


def test_provider_name_for_model_matches_known_prefixes():
    assert _provider_name_for_model("groq/llama-3.3-70b") == "groq"
    assert _provider_name_for_model("cerebras/llama3.1-8b") == "cerebras"
    assert _provider_name_for_model("nvidia/nemotron-3.5-lightning-30b-a3b") == "nvidia"


def test_provider_name_for_model_defaults_to_ollama_for_unprefixed_models():
    assert _provider_name_for_model("gemma4:e2b") == "ollama"


def test_local_ollama_run_estimates_zero_cost():
    cost = estimate_run_cost_usd(
        model="gemma4:e2b", judge_model="gemma4:e2b",
        n_questions=100, conditions=["bare", "rag", "nous"],
    )
    assert cost == 0.0


def test_more_conditions_costs_more_for_the_same_questions():
    small = estimate_run_cost_usd(
        model="groq/llama-3.3-70b", judge_model="groq/llama-3.3-70b",
        n_questions=40, conditions=["bare", "nous"],
    )
    large = estimate_run_cost_usd(
        model="groq/llama-3.3-70b", judge_model="groq/llama-3.3-70b",
        n_questions=40, conditions=["bare", "rag", "nous", "nous_meta",
                                     "nous_graph_only", "nous_plus_evidence",
                                     "nous_plus_temporal_validity",
                                     "nous_plus_contradiction", "nous_plus_plasticity",
                                     "long_context", "vector_rag"],
    )
    assert large > small


def test_nous_meta_costs_more_than_a_single_pass_condition_for_the_same_n():
    single_pass = estimate_run_cost_usd(
        model="groq/llama-3.3-70b", judge_model="groq/llama-3.3-70b",
        n_questions=40, conditions=["nous"],
    )
    multi_pass = estimate_run_cost_usd(
        model="groq/llama-3.3-70b", judge_model="groq/llama-3.3-70b",
        n_questions=40, conditions=["nous_meta"],
    )
    assert multi_pass > single_pass
