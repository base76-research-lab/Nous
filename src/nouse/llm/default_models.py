"""nouse.llm.default_models — centrala modellprofiler (daemon-teststart 2026-10-11).

Installerad Ollama-modell är ENDAST qwen3.5:9b. Tidigare hårdkodade
defaults (deepseek-r1:1.5b, qwen3.5:latest) gav 404 i daemon-teststarten.

Regler (roadmap Fas 2):
- Env-överskrivning per roll: NOUSE_MODEL_<ROLL> (t.ex. NOUSE_MODEL_EXTRACT,
  NOUSE_MODEL_CURIOSITY) samt NOUSE_MODEL_DEFAULT. Legacy-variabler
  (NOUSE_OLLAMA_MODEL, NOUSE_EXTRACT_MODEL, NOUSE_CHAT_MODEL, ...) hedras
  som fallback i befintliga anropare.
- Default är alltid den installerade modellen qwen3.5:9b.
- Saknad modell → logga + hoppa över jobbet (köa), aldrig krascha, aldrig
  eskalera till extern leverantör utan grind.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("nouse.models")

#: Enda verifierat installerade Ollama-modellen (`ollama list`, 2026-10-11).
DEFAULT_MODEL_NAME = "qwen3.5:9b"

_ROLE_ENV = {
    "extract": ("NOUSE_MODEL_EXTRACT", "NOUSE_EXTRACT_MODEL"),
    "curiosity": ("NOUSE_MODEL_CURIOSITY",),
    "synth": ("NOUSE_MODEL_SYNTH", "NOUSE_SYNTH_MODEL"),
    "synthesize": ("NOUSE_MODEL_SYNTH", "NOUSE_SYNTH_MODEL"),
    "decomp": ("NOUSE_MODEL_DECOMP", "NOUSE_DECOMP_MODEL"),
    "decomposition": ("NOUSE_MODEL_DECOMP", "NOUSE_DECOMP_MODEL"),
    "chat": ("NOUSE_MODEL_CHAT", "NOUSE_CHAT_MODEL"),
}

_LEGACY_GLOBAL = ("NOUSE_OLLAMA_MODEL", "NOUSE_CHAT_MODEL")

_MISSING_MARKERS = (
    "not found",
    "no such model",
    "does not exist",
    "unknown model",
    "model not available",
    "pull",
    "404",
)


def default_model() -> str:
    """Global default: NOUSE_MODEL_DEFAULT eller den installerade modellen."""
    return (os.getenv("NOUSE_MODEL_DEFAULT") or DEFAULT_MODEL_NAME).strip() or DEFAULT_MODEL_NAME


def model_for_role(role: str, *fallbacks: str | None) -> str:
    """Lös modell för en roll. Prioritet: NOUSE_MODEL_<ROLL> (+ rollspecifikt
    legacy) → explicita fallbacks → legacy globalt → NOUSE_MODEL_DEFAULT →
    installerad default."""
    key = (role or "").strip().lower()
    for env_name in _ROLE_ENV.get(key, (f"NOUSE_MODEL_{key.upper()}",)):
        value = (os.getenv(env_name) or "").strip()
        if value:
            return value
    for fallback in fallbacks:
        if fallback and str(fallback).strip():
            return str(fallback).strip()
    for env_name in _LEGACY_GLOBAL:
        value = (os.getenv(env_name) or "").strip()
        if value:
            return value
    return default_model()


def is_missing_model_error(exc: BaseException) -> bool:
    """True om felet betyder att modellen inte finns installerad (404 /
    not found) — till skillnad från timeout/nätfel som kan retrias."""
    text = str(exc).lower()
    return any(marker in text for marker in _MISSING_MARKERS)


def log_skip_missing_model(logger: logging.Logger, *, workload: str, model: str,
                           exc: BaseException) -> None:
    """Fallback-regel Fas 2: saknad modell → logga + hoppa över jobbet (köa).
    Anropas av workloads när samtliga kandidater rapporterar saknad modell.
    Eskalerar aldrig till extern leverantör härifrån."""
    logger.warning(
        "Modell saknas för %s (model=%s): %s — hoppar över jobbet (köar), "
        "ingen extern eskalering.",
        workload, model, exc,
    )
