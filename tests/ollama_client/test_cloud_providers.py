"""Tests for named cloud-provider routing (groq/openrouter/cerebras) in
AsyncOllama — 2026-08-24, "vilka free-modeller via API är lämpliga".
Distinct from the generic single-endpoint "openai_compatible" alias
bucket: each of these has its own base_url + API key env var, so they
can coexist as fallback candidates alongside Ollama models."""
from __future__ import annotations

import pytest

from nouse.ollama_client import client as client_mod
from nouse.ollama_client.client import (
    AsyncOllama,
    _split_provider_model_ref,
    model_uses_cloud_provider,
)


def test_model_uses_cloud_provider_true_for_named_providers():
    assert model_uses_cloud_provider("groq/llama-3.1-8b-instant") is True
    assert model_uses_cloud_provider("openrouter/some/model") is True
    assert model_uses_cloud_provider("cerebras/llama-3.3-70b") is True


def test_model_uses_cloud_provider_true_for_generic_openai_compatible_alias():
    assert model_uses_cloud_provider("codex/gpt-5-codex") is True
    assert model_uses_cloud_provider("openai/gpt-4o") is True


def test_model_uses_cloud_provider_false_for_plain_ollama_tag():
    assert model_uses_cloud_provider("gemma4:e2b") is False
    assert model_uses_cloud_provider("deepseek-r1:1.5b") is False


def test_model_uses_cloud_provider_false_for_ollama_prefix():
    assert model_uses_cloud_provider("ollama/qwen3.5:latest") is False


def test_model_uses_cloud_provider_false_for_empty_or_none():
    assert model_uses_cloud_provider("") is False
    assert model_uses_cloud_provider(None) is False


def test_split_provider_model_ref_supports_groq_prefix():
    provider, model = _split_provider_model_ref("groq/llama-3.1-8b-instant", "ollama")
    assert provider == "groq"
    assert model == "llama-3.1-8b-instant"


def test_split_provider_model_ref_supports_openrouter_prefix():
    provider, model = _split_provider_model_ref(
        "openrouter/nvidia/nemotron-3.5-lightning:free", "ollama",
    )
    assert provider == "openrouter"
    assert model == "nvidia/nemotron-3.5-lightning:free"


def test_split_provider_model_ref_supports_cerebras_prefix():
    provider, model = _split_provider_model_ref("cerebras/llama-3.3-70b", "ollama")
    assert provider == "cerebras"
    assert model == "llama-3.3-70b"


class _FakeHttpResponse:
    def __init__(self, url: str):
        self._url = url

    def raise_for_status(self):
        pass

    def json(self):
        return {
            "choices": [{"message": {"content": "ok", "tool_calls": []}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }


class _FakeHttpClient:
    """Captures the URL/headers a request would hit, without any network."""
    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, *, headers=None, json=None):
        _FakeHttpClient.calls.append({"url": url, "headers": headers or {}})
        return _FakeHttpResponse(url)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    _FakeHttpClient.calls = []
    monkeypatch.setattr(client_mod.httpx, "AsyncClient", _FakeHttpClient)
    monkeypatch.setattr(client_mod, "record_usage", lambda row, path=None: row)
    monkeypatch.setattr(client_mod, "load_env_files", lambda force=True: None)
    yield


async def _create(model: str):
    c = AsyncOllama()
    return await c.chat.completions.create(
        model=model, messages=[{"role": "user", "content": "hi"}],
    )


@pytest.mark.asyncio
async def test_groq_routes_to_groq_endpoint_with_groq_api_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.delenv("NOUSE_GROQ_BASE_URL", raising=False)

    await _create("groq/llama-3.1-8b-instant")

    assert len(_FakeHttpClient.calls) == 1
    call = _FakeHttpClient.calls[0]
    assert call["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer test-groq-key"


@pytest.mark.asyncio
async def test_openrouter_routes_to_openrouter_endpoint(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")
    monkeypatch.delenv("NOUSE_OPENROUTER_BASE_URL", raising=False)

    await _create("openrouter/some/model")

    call = _FakeHttpClient.calls[0]
    assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer test-or-key"


@pytest.mark.asyncio
async def test_cerebras_base_url_overridable_via_env(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-cerebras-key")
    monkeypatch.setenv("NOUSE_CEREBRAS_BASE_URL", "https://custom.example.com/v1")

    await _create("cerebras/llama-3.3-70b")

    call = _FakeHttpClient.calls[0]
    assert call["url"] == "https://custom.example.com/v1/chat/completions"


@pytest.mark.asyncio
async def test_groq_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        await _create("groq/llama-3.1-8b-instant")


@pytest.mark.asyncio
async def test_generic_openai_compatible_alias_still_uses_global_endpoint(monkeypatch):
    """Backward compatibility: an alias without a dedicated entry (e.g.
    'codex') still uses the single NOUSE_OPENAI_BASE_URL/API_KEY pair,
    unaffected by the new named-provider routing."""
    monkeypatch.setenv("NOUSE_OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("NOUSE_OPENAI_API_KEY", "test-openai-key")

    await _create("codex/gpt-5-codex")

    call = _FakeHttpClient.calls[0]
    assert call["url"] == "https://api.openai.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer test-openai-key"
