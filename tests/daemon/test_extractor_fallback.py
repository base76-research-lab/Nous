from __future__ import annotations

import asyncio

from nouse.daemon import extractor


def test_heuristic_extract_relations_finds_explicit_patterns():
    text = (
        "Hippocampus konsoliderar episodiskt minne. "
        "Prefrontal cortex reglerar arbetsminne. "
        "Amygdala modulerar emotionell saliens."
    )
    rows = extractor._heuristic_extract_relations(text, {"domain_hint": "neurovetenskap"})  # noqa: SLF001
    assert len(rows) >= 3
    rel_types = {r["type"] for r in rows}
    assert "konsoliderar" in rel_types
    assert "reglerar" in rel_types
    assert "modulerar" in rel_types


def test_heuristic_extract_relations_normalizes_aliases():
    rel = extractor._normalize_rel_type("causes")  # noqa: SLF001
    assert rel == "orsakar"
    rel = extractor._normalize_rel_type("is part of")  # noqa: SLF001
    assert rel == "\u00e4r_del_av"


def test_extract_relations_falls_back_to_heuristic(monkeypatch):
    async def _boom(**kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("timeout")

    monkeypatch.setattr(extractor, "_extract_with_model", _boom)
    monkeypatch.setattr(extractor, "ENABLE_HEURISTIC_FALLBACK", True)

    text = (
        "Neuroplasticitet orsakar forandring i synaptisk styrka. "
        "LTP starks av repetition. "
        "Prefrontal cortex reglerar arbetsminne under belastning."
    )
    rows = asyncio.run(extractor.extract_relations(text, {"domain_hint": "neurovetenskap"}))
    assert rows
    assert any(r["type"] == "orsakar" for r in rows)


def test_extract_relations_diagnostics_exposes_timeout_and_fallback(monkeypatch):
    async def _boom(**kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("timeout while calling model")

    monkeypatch.setattr(extractor, "_extract_with_model", _boom)
    monkeypatch.setattr(extractor, "_extract_model_candidates", lambda: ["m-test"])
    monkeypatch.setattr(extractor, "order_models_for_workload", lambda workload, cands: cands)
    monkeypatch.setattr(extractor, "record_model_result", lambda *a, **k: None)
    monkeypatch.setattr(extractor, "ENABLE_HEURISTIC_FALLBACK", True)

    text = (
        "Prefrontal cortex reglerar arbetsminne under belastning i studier och "
        "amygdala modulerar emotionell saliens i samma experiment."
    )
    rows, diag = asyncio.run(
        extractor.extract_relations_with_diagnostics(
            text,
            {"domain_hint": "neurovetenskap", "source": "test_source"},
        )
    )
    assert rows
    assert int(diag.get("timeouts", 0) or 0) >= 1
    assert bool(diag.get("used_heuristic_fallback")) is True


def test_extract_relations_records_quality_signal(monkeypatch):
    async def _ok(**kwargs):  # type: ignore[no-untyped-def]
        return [
            {
                "src": "A",
                "domain_src": "x",
                "type": "orsakar",
                "tgt": "B",
                "domain_tgt": "y",
                "why": "explicit mekanism",
            }
        ]

    captured: list[dict] = []

    def _record(workload, model, **kwargs):  # type: ignore[no-untyped-def]
        captured.append({"workload": workload, "model": model, **kwargs})

    monkeypatch.setattr(extractor, "_extract_with_model", _ok)
    monkeypatch.setattr(extractor, "_extract_model_candidates", lambda: ["m-quality"])
    monkeypatch.setattr(extractor, "order_models_for_workload", lambda workload, cands: cands)
    monkeypatch.setattr(extractor, "record_model_result", _record)

    rows, diag = asyncio.run(
        extractor.extract_relations_with_diagnostics(
            (
                "A orsakar B genom explicit mekanism i ett längre resonemang. "
                "Detta stycke innehåller tillräckligt många tecken för att passera "
                "extractor-tröskeln och trigga modellanropet i testet."
            ),
            {"domain_hint": "x"},
        )
    )
    assert rows
    assert diag.get("success_model") == "m-quality"
    assert isinstance(diag.get("quality"), float)
    assert captured
    assert captured[-1]["success"] is True
    assert isinstance(captured[-1].get("quality"), float)


def test_research_scope_blocks_cloud_models(monkeypatch):
    attempted: list[str] = []

    async def _ok(**kwargs):  # type: ignore[no-untyped-def]
        attempted.append(kwargs["model"])
        return [{
            "src": "A",
            "domain_src": "research",
            "type": "beskriver",
            "tgt": "B",
            "domain_tgt": "research",
            "why": "test relation",
        }]

    monkeypatch.setattr(extractor, "_extract_with_model", _ok)
    monkeypatch.setattr(
        extractor,
        "_extract_model_candidates",
        lambda: ["groq/cloud-model", "local-model:latest"],
    )
    monkeypatch.setattr(extractor, "order_models_for_workload", lambda workload, cands: cands)
    monkeypatch.setattr(
        extractor,
        "model_uses_cloud_provider",
        lambda model: model.startswith("groq/"),
    )
    monkeypatch.setattr(extractor, "record_model_result", lambda *a, **k: None)

    rows, diag = asyncio.run(
        extractor.extract_relations_with_diagnostics(
            "A beskriver B i ett forskningsmaterial med tillräckligt mycket text "
            "för att relationsanalysen ska köras i detta regressionstest lokalt.",
            {"domain_hint": "research", "scope_hint": "research_plg"},
        )
    )

    assert rows
    assert attempted == ["local-model:latest"]
    assert diag["attempted_models"] == ["local-model:latest"]
    assert diag["blocked_cloud_models"] == ["groq/cloud-model"]
    assert diag["model_policy"] == "local_only"


def test_general_scope_can_use_cloud_model(monkeypatch):
    attempted: list[str] = []

    async def _ok(**kwargs):  # type: ignore[no-untyped-def]
        attempted.append(kwargs["model"])
        return [{
            "src": "A",
            "domain_src": "general",
            "type": "beskriver",
            "tgt": "B",
            "domain_tgt": "general",
            "why": "test relation",
        }]

    monkeypatch.setattr(extractor, "_extract_with_model", _ok)
    monkeypatch.setattr(extractor, "_extract_model_candidates", lambda: ["groq/cloud-model"])
    monkeypatch.setattr(extractor, "order_models_for_workload", lambda workload, cands: cands)
    monkeypatch.setattr(extractor, "model_uses_cloud_provider", lambda model: True)
    monkeypatch.setattr(extractor, "record_model_result", lambda *a, **k: None)

    rows, diag = asyncio.run(
        extractor.extract_relations_with_diagnostics(
            "A beskriver B i ett allmänt material med tillräckligt mycket text "
            "för att relationsanalysen ska köras i detta regressionstest via molnet.",
            {"domain_hint": "general", "scope_hint": "general"},
        )
    )

    assert rows
    assert attempted == ["groq/cloud-model"]
    assert "blocked_cloud_models" not in diag
