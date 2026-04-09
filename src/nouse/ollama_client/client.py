from __future__ import annotations

import asyncio
from datetime import timezone
from email.utils import parsedate_to_datetime
import json
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from nouse.config.env import load_env_files
from nouse.llm.usage import estimate_cost_usd, record_usage


@dataclass
class _ToolFunction:
    name: str
    arguments: dict[str, Any] | str


@dataclass
class _ToolCall:
    function: _ToolFunction


class _Message:
    def __init__(self, content: str | None, tool_calls: list[_ToolCall] | None = None):
        self.content = content or ""
        self.tool_calls = tool_calls or []

    def model_dump(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            out["tool_calls"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in self.tool_calls
            ]
        return out


class _Response:
    def __init__(self, message: _Message, usage: dict[str, Any] | None = None):
        self.message = message
        self.usage = dict(usage or {})


_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_RETRYABLE_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "temporary failure",
    "temporarily unavailable",
    "connection reset",
    "connection refused",
    "connection aborted",
    "too many requests",
    "rate limit",
    "resource exhausted",
    "try again",
    "overloaded",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
)

_OPENAI_COMPATIBLE_PROVIDER_ALIASES = {
    "openai",
    "openai_compatible",
    "codex",
    "minimax",
    "openrouter",
    "fireworks",
    "together",
    "groq",
    "anthropic",
    "xai",
    "google",
    "mistral",
    "zai",
    "bedrock",
    "github-copilot",
    "copilot",
    "qwen",
    "huggingface",
    "deepseek",
    "venice",
}


def _coerce_float(raw: str, default: float, *, minimum: float, maximum: float | None = None) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _coerce_int(raw: str, default: int, *, minimum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _parse_retry_after_seconds(raw: str | None) -> float | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None

    try:
        sec = float(text)
        return max(0.0, sec)
    except ValueError:
        pass

    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, dt.timestamp() - time.time())


def _extract_status_code(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    if response is not None:
        code = getattr(response, "status_code", None)
        if isinstance(code, int):
            return code
    return None


def _canonical_provider(provider: str) -> str:
    p = str(provider or "").strip().lower()
    if p in _OPENAI_COMPATIBLE_PROVIDER_ALIASES:
        return "openai_compatible"
    if p == "ollama":
        return "ollama"
    return p or "ollama"


def _split_provider_model_ref(model_ref: str, default_provider: str) -> tuple[str, str]:
    raw = str(model_ref or "").strip()
    if not raw:
        raise ValueError("model required")
    if "/" in raw:
        prefix, remainder = raw.split("/", 1)
        canonical = _canonical_provider(prefix)
        if canonical in {"ollama", "openai_compatible"} and remainder.strip():
            return canonical, remainder.strip()
    return _canonical_provider(default_provider), raw


def _extract_retry_after_from_exception(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None)
        if headers is not None:
            retry_after = headers.get("retry-after")
            parsed = _parse_retry_after_seconds(retry_after)
            if parsed is not None:
                return parsed

    message = str(exc)
    patterns = [
        r"retry[_\s-]*after[^0-9]{0,8}(\d+(?:\.\d+)?)",
        r"wait[^0-9]{0,8}(\d+(?:\.\d+)?)\s*s",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            try:
                return max(0.0, float(match.group(1)))
            except ValueError:
                continue
    return None


def _is_retryable_ollama_error(exc: Exception) -> tuple[bool, float | None]:
    if isinstance(exc, asyncio.TimeoutError):
        return True, None
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True, None

    status_code = _extract_status_code(exc)
    retry_after = _extract_retry_after_from_exception(exc)
    if isinstance(status_code, int):
        return status_code in _RETRYABLE_STATUS_CODES, retry_after

    lowered = str(exc).lower()
    if any(marker in lowered for marker in _RETRYABLE_ERROR_MARKERS):
        return True, retry_after

    return False, retry_after


def _usage_number(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _extract_ollama_usage(resp: Any) -> dict[str, int]:
    prompt = 0
    completion = 0
    if isinstance(resp, dict):
        prompt = _usage_number(resp.get("prompt_eval_count"))
        completion = _usage_number(resp.get("eval_count"))
    else:
        prompt = _usage_number(getattr(resp, "prompt_eval_count", 0))
        completion = _usage_number(getattr(resp, "eval_count", 0))
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": max(0, prompt + completion),
    }


class AsyncOllama:
    """
    Backward-compatible client surface:
      client = AsyncOllama()
      resp = await client.chat.completions.create(model=..., messages=..., tools=...)
      resp.message.content / resp.message.tool_calls

    Provider selection via env:
      NOUSE_LLM_PROVIDER=ollama|openai_compatible   (default: ollama)
    """

    def __init__(self, **kwargs):
        # Läs .env på varje init så nyckel-/provider-ändringar slår igenom
        # utan att daemonen måste startas om.
        load_env_files(force=True)
        self.provider = _canonical_provider(os.getenv("NOUSE_LLM_PROVIDER", "ollama"))
        self.chat = self.Chat(self, **kwargs)

    class Chat:
        def __init__(self, outer: "AsyncOllama", **kwargs):
            self.completions = self.Completions(outer, **kwargs)

        class Completions:
            def __init__(self, outer: "AsyncOllama", **kwargs):
                self._provider = outer.provider
                self._ollama_client = None
                timeout_override = kwargs.pop("timeout_sec", None)
                retries_override = kwargs.pop("max_retries", None)
                self._kwargs = kwargs
                timeout_raw = (os.getenv("NOUSE_LLM_TIMEOUT_SEC", "45") or "").strip()
                retries_raw = (os.getenv("NOUSE_LLM_RETRIES", "0") or "").strip()
                retry_base_raw = (os.getenv("NOUSE_LLM_RETRY_BASE_SEC", "0.8") or "").strip()
                retry_max_raw = (os.getenv("NOUSE_LLM_RETRY_MAX_SEC", "30") or "").strip()
                retry_jitter_raw = (os.getenv("NOUSE_LLM_RETRY_JITTER", "0.15") or "").strip()
                use_retry_after_raw = (os.getenv("NOUSE_LLM_RETRY_USE_RETRY_AFTER", "1") or "").strip().lower()
                self._timeout_sec = _coerce_float(timeout_raw, 45.0, minimum=1.0)
                self._max_retries = _coerce_int(retries_raw, 0, minimum=0)
                self._retry_base_sec = _coerce_float(retry_base_raw, 0.8, minimum=0.05)
                self._retry_max_sec = _coerce_float(retry_max_raw, 30.0, minimum=self._retry_base_sec)
                self._retry_jitter = _coerce_float(retry_jitter_raw, 0.15, minimum=0.0, maximum=0.9)
                self._use_retry_after = use_retry_after_raw in {"1", "true", "yes", "on"}

                if timeout_override is not None:
                    try:
                        self._timeout_sec = max(0.5, float(timeout_override))
                    except (TypeError, ValueError):
                        pass
                if retries_override is not None:
                    try:
                        self._max_retries = max(0, int(retries_override))
                    except (TypeError, ValueError):
                        pass

            def _ensure_ollama_client(self):
                if self._ollama_client is not None:
                    return self._ollama_client
                # Lazy import so non-ollama providers don't require the package.
                import ollama  # type: ignore

                host = (
                    os.getenv("NOUSE_OLLAMA_HOST")
                    or os.getenv("OLLAMA_HOST")
                )
                if host:
                    self._ollama_client = ollama.AsyncClient(host=host, **self._kwargs)
                else:
                    self._ollama_client = ollama.AsyncClient(**self._kwargs)
                return self._ollama_client

            def _retry_delay_sec(self, attempt: int, retry_after_sec: float | None) -> float:
                if (
                    self._use_retry_after
                    and retry_after_sec is not None
                    and retry_after_sec > 0
                ):
                    return min(self._retry_max_sec, retry_after_sec)
                base = min(self._retry_max_sec, self._retry_base_sec * (2 ** attempt))
                if self._retry_jitter <= 0:
                    return base
                jitter_multiplier = 1.0 + random.uniform(-self._retry_jitter, self._retry_jitter)
                return max(0.05, min(self._retry_max_sec, base * jitter_multiplier))

            async def create(self, *, model: str, messages: list[dict], **kwargs) -> _Response:
                started = time.monotonic()
                meta = kwargs.pop("b76_meta", {})
                if not isinstance(meta, dict):
                    meta = {}
                session_id = str(meta.get("session_id") or "main").strip() or "main"
                run_id = str(meta.get("run_id") or "").strip() or None
                workload = str(meta.get("workload") or "unknown").strip() or "unknown"
                provider, resolved_model = _split_provider_model_ref(model, self._provider)
                if provider == "ollama":
                    ollama_client = self._ensure_ollama_client()
                    resp = None
                    for attempt in range(self._max_retries + 1):
                        try:
                            resp = await asyncio.wait_for(
                                ollama_client.chat(
                                    model=resolved_model,
                                    messages=messages,
                                    **kwargs,
                                ),
                                timeout=self._timeout_sec,
                            )
                            break
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            retryable, retry_after_sec = _is_retryable_ollama_error(e)
                            final_exc: Exception = e
                            if isinstance(e, (asyncio.TimeoutError, httpx.TimeoutException)):
                                final_exc = RuntimeError(
                                    f"LLM timeout efter {self._timeout_sec:.1f}s "
                                    f"(provider={provider}, model={model})"
                                )
                            if attempt >= self._max_retries or not retryable:
                                latency_ms = int((time.monotonic() - started) * 1000)
                                record_usage(
                                    {
                                        "session_id": session_id,
                                        "run_id": run_id,
                                        "workload": workload,
                                        "provider": provider,
                                        "model": model,
                                        "status": "failed",
                                        "latency_ms": latency_ms,
                                        "error": str(final_exc),
                                    }
                                )
                                raise final_exc from e
                            delay_sec = self._retry_delay_sec(attempt, retry_after_sec)
                            await asyncio.sleep(delay_sec)
                    assert resp is not None
                    msg = resp.message
                    tool_calls: list[_ToolCall] = []
                    for tc in (msg.tool_calls or []):
                        args = tc.function.arguments
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                pass
                        tool_calls.append(
                            _ToolCall(_ToolFunction(name=tc.function.name, arguments=args))
                        )
                    usage = _extract_ollama_usage(resp)
                    usage["cost_usd"] = estimate_cost_usd(
                        model=model,
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                    )
                    usage["latency_ms"] = int((time.monotonic() - started) * 1000)
                    record_usage(
                        {
                            "session_id": session_id,
                            "run_id": run_id,
                            "workload": workload,
                            "provider": provider,
                            "model": model,
                            "status": "succeeded",
                            "latency_ms": usage["latency_ms"],
                            "prompt_tokens": usage.get("prompt_tokens", 0),
                            "completion_tokens": usage.get("completion_tokens", 0),
                            "total_tokens": usage.get("total_tokens", 0),
                            "cost_usd": usage.get("cost_usd", 0.0),
                        }
                    )
                    return _Response(_Message(content=msg.content, tool_calls=tool_calls), usage=usage)

                if provider == "openai_compatible":
                    resp = None
                    for attempt in range(self._max_retries + 1):
                        try:
                            resp = await self._create_openai_compatible(
                                model=resolved_model,
                                messages=messages,
                                **kwargs,
                            )
                            break
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            retryable, retry_after_sec = _is_retryable_ollama_error(e)
                            final_exc: Exception = e
                            if isinstance(e, (asyncio.TimeoutError, httpx.TimeoutException)):
                                final_exc = RuntimeError(
                                    f"LLM timeout efter {self._timeout_sec:.1f}s "
                                    f"(provider={provider}, model={model})"
                                )
                            if attempt >= self._max_retries or not retryable:
                                latency_ms = int((time.monotonic() - started) * 1000)
                                record_usage(
                                    {
                                        "session_id": session_id,
                                        "run_id": run_id,
                                        "workload": workload,
                                        "provider": provider,
                                        "model": model,
                                        "status": "failed",
                                        "latency_ms": latency_ms,
                                        "error": str(final_exc),
                                    }
                                )
                                raise final_exc from e
                            delay_sec = self._retry_delay_sec(attempt, retry_after_sec)
                            await asyncio.sleep(delay_sec)
                    assert resp is not None
                    usage = dict(getattr(resp, "usage", {}) or {})
                    prompt_tokens = _usage_number(usage.get("prompt_tokens"))
                    completion_tokens = _usage_number(usage.get("completion_tokens"))
                    total_tokens = _usage_number(
                        usage.get("total_tokens", prompt_tokens + completion_tokens)
                    )
                    cost_usd = estimate_cost_usd(
                        model=model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
                    latency_ms = int((time.monotonic() - started) * 1000)
                    record_usage(
                        {
                            "session_id": session_id,
                            "run_id": run_id,
                            "workload": workload,
                            "provider": provider,
                            "model": model,
                            "status": "succeeded",
                            "latency_ms": latency_ms,
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": total_tokens,
                            "cost_usd": cost_usd,
                        }
                    )
                    usage.update(
                        {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": total_tokens,
                            "cost_usd": cost_usd,
                            "latency_ms": latency_ms,
                        }
                    )
                    resp.usage = usage
                    return resp

                raise RuntimeError(
                    f"Unknown NOUSE_LLM_PROVIDER='{provider}'. "
                    "Use 'ollama' or 'openai_compatible'."
                )

            async def _create_openai_compatible(
                self, *, model: str, messages: list[dict], **kwargs
            ) -> _Response:
                base_url = os.getenv("NOUSE_OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
                api_key = os.getenv("NOUSE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
                if not api_key:
                    raise RuntimeError(
                        "Missing API key for openai_compatible provider. "
                        "Set NOUSE_OPENAI_API_KEY or OPENAI_API_KEY."
                    )

                payload: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                }

                # Forward common options.
                for key in ("tools", "tool_choice", "temperature", "top_p", "max_tokens"):
                    if key in kwargs:
                        payload[key] = kwargs[key]

                # Ollama callers often send options={"temperature": ...}
                options = kwargs.get("options", {})
                if isinstance(options, dict):
                    if "temperature" not in payload and "temperature" in options:
                        payload["temperature"] = options["temperature"]
                    if "top_p" not in payload and "top_p" in options:
                        payload["top_p"] = options["top_p"]

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }

                async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                    r = await client.post(
                        f"{base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    r.raise_for_status()
                    data = r.json()

                choice = (data.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                content = msg.get("content") or ""
                usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                raw_tool_calls = msg.get("tool_calls") or []
                tool_calls: list[_ToolCall] = []
                for tc in raw_tool_calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name", "")
                    args_raw = fn.get("arguments", "{}")
                    args: dict[str, Any] | str = args_raw
                    if isinstance(args_raw, str):
                        try:
                            args = json.loads(args_raw)
                        except Exception:
                            args = args_raw
                    tool_calls.append(_ToolCall(_ToolFunction(name=name, arguments=args)))

                return _Response(_Message(content=content, tool_calls=tool_calls), usage=usage)
