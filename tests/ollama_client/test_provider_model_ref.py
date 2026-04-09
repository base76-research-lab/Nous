from __future__ import annotations

from nouse.ollama_client.client import _canonical_provider, _split_provider_model_ref


def test_canonical_provider_maps_aliases_to_openai_compatible():
    assert _canonical_provider("openai") == "openai_compatible"
    assert _canonical_provider("openai_compatible") == "openai_compatible"
    assert _canonical_provider("codex") == "openai_compatible"
    assert _canonical_provider("minimax") == "openai_compatible"
    assert _canonical_provider("ollama") == "ollama"


def test_split_provider_model_ref_uses_explicit_prefix():
    provider, model = _split_provider_model_ref(
        "openai_compatible/minimax-m2.7:cloud",
        "ollama",
    )
    assert provider == "openai_compatible"
    assert model == "minimax-m2.7:cloud"


def test_split_provider_model_ref_keeps_unknown_slash_model_with_default_provider():
    provider, model = _split_provider_model_ref("deepseek-ai/deepseek-r1", "ollama")
    assert provider == "ollama"
    assert model == "deepseek-ai/deepseek-r1"


def test_split_provider_model_ref_supports_ollama_prefix():
    provider, model = _split_provider_model_ref("ollama/qwen3.5:latest", "openai")
    assert provider == "ollama"
    assert model == "qwen3.5:latest"


def test_split_provider_model_ref_supports_codex_prefix():
    provider, model = _split_provider_model_ref("codex/gpt-5-codex", "ollama")
    assert provider == "openai_compatible"
    assert model == "gpt-5-codex"
