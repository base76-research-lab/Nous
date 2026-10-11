"""Kontraktstest FIX 2 — modellprofiler (daemon-teststart 2026-10-11).

Installerad Ollama-modell är ENDAST qwen3.5:9b. Koden refererade till
deepseek-r1:1.5b och qwen3.5:latest (404 i testloggen).

Kontrakt:
- Env-överskrivning per roll: NOUSE_MODEL_EXTRACT, NOUSE_MODEL_CURIOSITY,
  NOUSE_MODEL_DEFAULT (legacy NOUSE_OLLAMA_MODEL m.fl. fortsatt hedrade
  som fallback) med default qwen3.5:9b.
- Med default-env väljs qwen3.5:9b (aldrig deepseek-r1:1.5b / qwen3.5:latest).
- Med obefintligt modellnamn i env skippas jobbet rent med loggrad:
  logga + hoppa över (köa), aldrig krascha, aldrig eskalera till extern
  leverantör utan grind.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from nouse.llm import default_models
from nouse.daemon import extractor
from nouse.daemon import initiative

MODEL_VARS = (
    "NOUSE_MODEL_DEFAULT",
    "NOUSE_MODEL_EXTRACT",
    "NOUSE_MODEL_CURIOSITY",
    "NOUSE_MODEL_SYNTH",
    "NOUSE_MODEL_DECOMP",
    "NOUSE_EXTRACT_MODEL",
    "NOUSE_EXTRACT_FALLBACK_MODEL",
    "NOUSE_SYNTH_MODEL",
    "NOUSE_DECOMP_MODEL",
    "NOUSE_OLLAMA_MODEL",
    "NOUSE_CHAT_MODEL",
    "NOUSE_CURIOSITY_FALLBACK_MODEL",
    "NOUSE_MODEL_CANDIDATES",
    "NOUSE_MODEL_CANDIDATES_EXTRACT",
    "NOUSE_MODEL_CANDIDATES_CURIOSITY",
    "NOUSE_MODEL_CANDIDATES_SYNTH",
)


@pytest.fixture
def default_env(monkeypatch):
    for var in MODEL_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NOUSE_MODEL_AUTODISCOVER", "0")
    yield


def _isolate_router(monkeypatch, module):
    """Ingen nätverks-discovery, ingen policyfil, inga writes till
    ~/.local/share/nouse/*."""
    monkeypatch.setattr(module, "_autodiscovered_models", lambda: [])
    monkeypatch.setattr(
        module, "resolve_model_candidates",
        lambda workload, defaults: list(dict.fromkeys(defaults)),
    )
    monkeypatch.setattr(module, "order_models_for_workload",
                        lambda workload, cands: list(cands))
    monkeypatch.setattr(module, "record_model_result",
                        lambda *a, **k: None)


def test_default_model_is_installed_model(default_env):
    assert default_models.default_model() == "qwen3.5:9b"
    assert default_models.DEFAULT_MODEL_NAME == "qwen3.5:9b"


def test_role_env_overrides(default_env, monkeypatch):
    monkeypatch.setenv("NOUSE_MODEL_EXTRACT", "my-extract:1b")
    monkeypatch.setenv("NOUSE_MODEL_CURIOSITY", "my-curious:1b")
    monkeypatch.setenv("NOUSE_MODEL_DEFAULT", "my-default:1b")
    assert default_models.model_for_role("extract") == "my-extract:1b"
    assert default_models.model_for_role("curiosity") == "my-curious:1b"
    assert default_models.model_for_role("synth") == "my-default:1b"
    assert default_models.model_for_role("unknown-role") == "my-default:1b"


def test_extractor_defaults_to_installed_model(default_env, monkeypatch):
    _isolate_router(monkeypatch, extractor)
    cands = extractor._extract_model_candidates()  # noqa: SLF001
    assert "qwen3.5:9b" in cands
    assert "deepseek-r1:1.5b" not in cands
    assert "qwen3.5:latest" not in cands


def test_extractor_env_override(default_env, monkeypatch):
    _isolate_router(monkeypatch, extractor)
    monkeypatch.setenv("NOUSE_MODEL_EXTRACT", "ghost-model:9b")
    cands = extractor._extract_model_candidates()  # noqa: SLF001
    assert cands[0] == "ghost-model:9b"


def test_curiosity_defaults_to_installed_model(default_env, monkeypatch):
    _isolate_router(monkeypatch, initiative)
    cands = initiative._curiosity_model_candidates(None)  # noqa: SLF001
    assert "qwen3.5:9b" in cands
    assert "deepseek-r1:1.5b" not in cands
    assert "qwen3.5:latest" not in cands


def test_curiosity_env_override(default_env, monkeypatch):
    _isolate_router(monkeypatch, initiative)
    monkeypatch.setenv("NOUSE_MODEL_CURIOSITY", "ghost-curious:9b")
    cands = initiative._curiosity_model_candidates(None)  # noqa: SLF001
    assert cands[0] == "ghost-curious:9b"


def test_missing_model_detector():
    assert default_models.is_missing_model_error(Exception("model 'x' not found")) is True
    assert default_models.is_missing_model_error(Exception("404 page not found")) is True
    assert default_models.is_missing_model_error(Exception("No such model: ghost:9b")) is True
    assert default_models.is_missing_model_error(Exception("timeout")) is False


def test_extract_missing_model_skips_cleanly(default_env, monkeypatch, caplog):
    """Obefintlig modell i env → logga + hoppa över, aldrig krascha,
    aldrig extern eskalering."""
    _isolate_router(monkeypatch, extractor)
    monkeypatch.setattr(extractor, "ENABLE_HEURISTIC_FALLBACK", False)
    monkeypatch.setenv("NOUSE_MODEL_EXTRACT", "ghost-model:9b")

    async def _missing(**kwargs):
        raise Exception("model 'ghost-model:9b' not found, try pulling it first (404)")

    attempted_cloud: list[str] = []
    real_uses_cloud = extractor.model_uses_cloud_provider

    def _spy_cloud(model):
        if real_uses_cloud(model):
            attempted_cloud.append(model)
        return real_uses_cloud(model)

    monkeypatch.setattr(extractor, "_extract_with_model", _missing)
    monkeypatch.setattr(extractor, "model_uses_cloud_provider", _spy_cloud)

    text = ("A orsakar B genom explicit mekanism i ett längre resonemang. " * 8)
    with caplog.at_level(logging.WARNING, logger="nouse.extractor"):
        rels, diag = asyncio.run(extractor.extract_relations_with_diagnostics(
            text, {"domain_hint": "test"}))
    assert rels == []
    assert diag.get("skipped_reason") == "model_missing"
    assert attempted_cloud == []
    assert "ghost-model:9b" in caplog.text


def test_curiosity_missing_model_skips_cleanly(default_env, monkeypatch, caplog):
    """Obefintlig curiosity-modell → None med loggrad, inget undantag."""
    _isolate_router(monkeypatch, initiative)
    monkeypatch.setenv("NOUSE_MODEL_CURIOSITY", "ghost-curious:9b")

    class _BoomClient:
        def __init__(self, *a, **k):
            pass

        @property
        def chat(self):
            class _C:
                @property
                def completions(self):
                    class _CC:
                        async def create(self, **kwargs):
                            raise Exception(
                                "model 'ghost-curious:9b' not found (404)")
                    return _CC()
            return _C()

    monkeypatch.setattr(initiative, "AsyncOllama", _BoomClient)

    from nouse.field.surface import FieldSurface  # noqa: PLC0415
    from nouse.limbic.signals import LimbicState  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        field = FieldSurface(db_path=f"{tmp}/t.sqlite")
        limbic = LimbicState()
        task = {"domain": "test", "concepts": ["a", "b"],
                "rationale": "t", "query": "q", "id": 1}
        with caplog.at_level(logging.WARNING, logger="nouse.curiosity"):
            result = asyncio.run(
                initiative.run_curiosity_burst(field, limbic, task=task))
    assert result is None
    assert "ghost-curious:9b" in caplog.text
