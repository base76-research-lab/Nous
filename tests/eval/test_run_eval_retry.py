from __future__ import annotations

import asyncio

import pytest

from eval import run_eval


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._json_body = json_body or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        return self._json_body


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.calls = 0

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls += 1
        return self._responses.pop(0)


def _ok_response(content: str) -> _FakeResponse:
    return _FakeResponse(200, {"choices": [{"message": {"content": content}}]})


@pytest.fixture(autouse=True)
def _reset_shared_client(monkeypatch):
    monkeypatch.setattr(run_eval, "_shared_httpx_client", None)
    # Exponential backoff (up to 2+4+8+16=30s across exhausted retries) is
    # real behavior worth having, not worth actually waiting for in a test.
    _real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda *_a, **_kw: _real_sleep(0))
    yield
    monkeypatch.setattr(run_eval, "_shared_httpx_client", None)


def test_call_llm_retries_503_then_succeeds(monkeypatch):
    """2026-08-25: NVIDIA NIM returns 503 for congested models (observed
    directly on nvidia/nemotron-3-ultra-550b-a55b, 1 of 4 real calls) —
    must be retried the same way 429 already is, not treated as fatal."""
    fake = _FakeClient([_FakeResponse(503), _ok_response("answer text")])
    monkeypatch.setattr(run_eval, "_get_shared_httpx_client", lambda: fake)

    result = asyncio.run(run_eval.call_llm(None, "nvidia/some-model", "sys", "user", timeout=5.0))

    assert result == "answer text"
    assert fake.calls == 2


def test_call_llm_retries_429_then_succeeds(monkeypatch):
    fake = _FakeClient([_FakeResponse(429, headers={"retry-after": "0"}), _ok_response("answer text")])
    monkeypatch.setattr(run_eval, "_get_shared_httpx_client", lambda: fake)

    result = asyncio.run(run_eval.call_llm(None, "nvidia/some-model", "sys", "user", timeout=5.0))

    assert result == "answer text"


def test_call_llm_returns_readable_error_when_503_retries_exhausted(monkeypatch):
    """Before this fix, exhausting retries on a 429/503 fell through to
    data["choices"] with data=None and raised an opaque TypeError instead
    of a readable exhaustion message."""
    fake = _FakeClient([_FakeResponse(503)] * 6)
    monkeypatch.setattr(run_eval, "_get_shared_httpx_client", lambda: fake)

    result = asyncio.run(run_eval.call_llm(None, "nvidia/some-model", "sys", "user", timeout=5.0))

    assert result == "[ERROR: 503 (retries exhausted)]"
    assert "NoneType" not in result


def test_call_llm_returns_readable_error_when_429_retries_exhausted(monkeypatch):
    fake = _FakeClient([_FakeResponse(429, headers={"retry-after": "0"})] * 6)
    monkeypatch.setattr(run_eval, "_get_shared_httpx_client", lambda: fake)

    result = asyncio.run(run_eval.call_llm(None, "nvidia/some-model", "sys", "user", timeout=5.0))

    assert result == "[ERROR: 429 (retries exhausted)]"
