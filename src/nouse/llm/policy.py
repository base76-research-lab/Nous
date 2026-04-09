from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODEL_POLICY_PATH = Path.home() / ".local" / "share" / "nouse" / "model_policy.json"
_LOCK = threading.Lock()

_DEFAULT_WORKLOADS = {
    "chat": {"provider": "ollama", "candidates": []},
    "agent": {"provider": "ollama", "candidates": []},
    "extract": {"provider": "ollama", "candidates": []},
    "synthesize": {"provider": "ollama", "candidates": []},
    "bisoc": {"provider": "ollama", "candidates": []},
    "curiosity": {"provider": "ollama", "candidates": []},
}

_EXPLICIT_PROVIDER_PREFIXES = {
    "ollama",
    "openai",
    "openai_compatible",
    "codex",
    # OpenAI-compatible vendor aliases (used as explicit provider prefixes).
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


def _canonical_provider(provider: str) -> str:
    p = str(provider or "").strip().lower()
    if p in {"openai", "openai_compatible"}:
        return "openai_compatible"
    if p in _EXPLICIT_PROVIDER_PREFIXES and p != "ollama":
        return "openai_compatible"
    return p or "ollama"


def _has_explicit_provider_prefix(model_ref: str) -> bool:
    text = str(model_ref or "").strip()
    if "/" not in text:
        return False
    prefix = text.split("/", 1)[0].strip().lower()
    return prefix in _EXPLICIT_PROVIDER_PREFIXES


def _qualify_model_ref(provider: str, model_ref: str) -> str:
    text = str(model_ref or "").strip()
    if not text:
        return ""
    canonical = _canonical_provider(provider)
    if canonical == "ollama":
        return text
    if _has_explicit_provider_prefix(text):
        return text
    return f"{canonical}/{text}"


def _looks_like_ollama_tag(model_ref: str) -> bool:
    """
    Heuristik: Ollama-modeller använder ofta `name:tag` (t.ex. gemma4:e2b).
    OpenAI-kompatibla molnmodeller använder normalt inte kolon-taggar.
    """
    text = str(model_ref or "").strip()
    if not text:
        return False
    if _has_explicit_provider_prefix(text):
        return False
    return ":" in text


def _should_add_ollama_fallback(provider: str, model_ref: str) -> bool:
    canonical = _canonical_provider(provider)
    if canonical == "ollama":
        return False
    return _looks_like_ollama_tag(model_ref)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_policy(raw: dict[str, Any] | None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "version": 1,
        "updated_at": _now_iso(),
        "workloads": {},
    }
    if not isinstance(raw, dict):
        base["workloads"] = dict(_DEFAULT_WORKLOADS)
        return base
    workloads = raw.get("workloads")
    norm_workloads: dict[str, dict[str, Any]] = {}
    if isinstance(workloads, dict):
        for key, row in workloads.items():
            if not isinstance(row, dict):
                continue
            name = str(key or "").strip().lower()
            if not name:
                continue
            candidates = row.get("candidates")
            if isinstance(candidates, list):
                clean_candidates = [
                    str(item).strip() for item in candidates if str(item).strip()
                ]
            else:
                clean_candidates = []
            norm_workloads[name] = {
                "provider": _canonical_provider(str(row.get("provider") or "ollama").strip()),
                "candidates": clean_candidates,
            }
    for name, row in _DEFAULT_WORKLOADS.items():
        norm_workloads.setdefault(name, dict(row))
    base["version"] = int(raw.get("version", 1) or 1)
    base["updated_at"] = str(raw.get("updated_at") or _now_iso())
    base["workloads"] = norm_workloads
    return base


def load_policy(path: Path = MODEL_POLICY_PATH) -> dict[str, Any]:
    if not path.exists():
        return _normalize_policy(None)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _normalize_policy(None)
    return _normalize_policy(raw)


def save_policy(policy: dict[str, Any], path: Path = MODEL_POLICY_PATH) -> dict[str, Any]:
    out = _normalize_policy(policy)
    out["updated_at"] = _now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def get_workload_policy(workload: str, path: Path = MODEL_POLICY_PATH) -> dict[str, Any]:
    key = str(workload or "").strip().lower()
    with _LOCK:
        policy = load_policy(path)
    row = (policy.get("workloads") or {}).get(key)
    if not isinstance(row, dict):
        row = {"provider": "ollama", "candidates": []}
    return {
        "workload": key,
        "provider": str(row.get("provider") or "ollama"),
        "candidates": list(row.get("candidates") or []),
        "updated_at": str(policy.get("updated_at") or ""),
        "version": int(policy.get("version", 1) or 1),
    }


def resolve_model_candidates(
    workload: str,
    default_candidates: list[str],
    *,
    path: Path = MODEL_POLICY_PATH,
) -> list[str]:
    key = str(workload or "").strip().lower()
    dedup: list[str] = []
    seen = set()
    with _LOCK:
        policy = load_policy(path)
    row = (policy.get("workloads") or {}).get(key) or {}
    policy_candidates = row.get("candidates") if isinstance(row, dict) else []
    provider = str((row or {}).get("provider") or "ollama")
    source: list[str] = []

    def _append_candidate(raw: str) -> None:
        text = str(raw or "").strip()
        if not text:
            return
        source.append(_qualify_model_ref(provider, text))
        # Robusthet: om provider är OpenAI-kompatibel men kandidaten ser ut som
        # lokal Ollama-tag, lägg till lokal fallback så chatten inte fastnar.
        if _should_add_ollama_fallback(provider, text):
            source.append(_qualify_model_ref("ollama", text))

    if isinstance(policy_candidates, list) and policy_candidates:
        for item in policy_candidates:
            _append_candidate(str(item))
    for item in (default_candidates or []):
        _append_candidate(str(item))

    for model in source:
        if model in seen:
            continue
        seen.add(model)
        dedup.append(model)
    return dedup


def set_workload_candidates(
    workload: str,
    candidates: list[str],
    *,
    provider: str = "ollama",
    path: Path = MODEL_POLICY_PATH,
) -> dict[str, Any]:
    key = str(workload or "").strip().lower()
    if not key:
        raise ValueError("workload required")
    clean_candidates = [str(x).strip() for x in candidates if str(x).strip()]
    with _LOCK:
        policy = load_policy(path)
        workloads = policy.setdefault("workloads", {})
        workloads[key] = {
            "provider": _canonical_provider(str(provider or "ollama")),
            "candidates": clean_candidates,
        }
        saved = save_policy(policy, path)
    row = (saved.get("workloads") or {}).get(key) or {}
    return {
        "workload": key,
        "provider": str(row.get("provider") or "ollama"),
        "candidates": list(row.get("candidates") or []),
        "updated_at": str(saved.get("updated_at") or ""),
        "version": int(saved.get("version", 1) or 1),
    }


def reset_policy(path: Path = MODEL_POLICY_PATH) -> dict[str, Any]:
    with _LOCK:
        saved = save_policy(_normalize_policy(None), path)
    return saved
