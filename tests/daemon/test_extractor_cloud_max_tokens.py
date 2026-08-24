"""Regression test: cloud reasoning models (Groq qwen3.6-27b,
openai/gpt-oss-*) spend their default max_tokens budget on a visible
<think> preamble before ever reaching the JSON answer, truncating the
response mid-array. Fix: pass a generous max_tokens for cloud-routed
models only — Ollama's native client has no such kwarg and would raise
a TypeError if it received one, so this must never reach the Ollama
branch. See ollama_client.client.model_uses_cloud_provider()."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from nouse.daemon import extractor


@dataclass
class _FakeMessage:
    content: str = "[]"


@dataclass
class _FakeResp:
    message: _FakeMessage = field(default_factory=_FakeMessage)


class _FakeCompletions:
    last_kwargs: dict | None = None

    async def create(self, **kwargs):
        _FakeCompletions.last_kwargs = kwargs
        return _FakeResp()


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeAsyncOllama:
    def __init__(self, **kwargs):
        self.chat = _FakeChat()


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch):
    monkeypatch.setattr(extractor, "AsyncOllama", _FakeAsyncOllama)
    yield


@pytest.mark.asyncio
async def test_cloud_model_receives_max_tokens():
    await extractor._extract_with_model(  # noqa: SLF001
        model="groq/qwen/qwen3.6-27b", chunk="text", domain_hint="test",
    )
    assert _FakeCompletions.last_kwargs["max_tokens"] == extractor.EXTRACT_CLOUD_MAX_TOKENS


@pytest.mark.asyncio
async def test_ollama_model_does_not_receive_max_tokens():
    """Ollama's native AsyncClient.chat() has no max_tokens parameter —
    passing it would raise a TypeError against a real Ollama model."""
    await extractor._extract_with_model(  # noqa: SLF001
        model="gemma4:e2b", chunk="text", domain_hint="test",
    )
    assert "max_tokens" not in _FakeCompletions.last_kwargs


@pytest.mark.asyncio
async def test_plain_ollama_tag_with_colon_does_not_receive_max_tokens():
    await extractor._extract_with_model(  # noqa: SLF001
        model="deepseek-r1:1.5b", chunk="text", domain_hint="test",
    )
    assert "max_tokens" not in _FakeCompletions.last_kwargs


@pytest.mark.asyncio
async def test_max_tokens_configurable_via_env(monkeypatch):
    monkeypatch.setattr(extractor, "EXTRACT_CLOUD_MAX_TOKENS", 8192)
    await extractor._extract_with_model(  # noqa: SLF001
        model="openrouter/nvidia/nemotron-3.5-lightning:free", chunk="text", domain_hint="test",
    )
    assert _FakeCompletions.last_kwargs["max_tokens"] == 8192
