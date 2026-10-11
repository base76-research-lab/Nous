"""Kontrakt: extraktionsprofilen får aldrig fastna i obegränsat tänkande.

Mätt 2026-10-11: qwen3.5:9b utan think/cap >120 s (timeout), med
think=False + num_predict=512 ~5-11 s med giltig JSON.
"""
from __future__ import annotations

import asyncio

from nouse.daemon import extractor


def test_extract_profile_defaults_bound_reasoning():
    assert extractor.EXTRACT_NUM_PREDICT >= 64
    assert extractor.SYNTH_NUM_PREDICT >= 64
    assert extractor.MODEL_THINK_ENABLED is False


def test_extract_with_model_disables_think_and_caps(monkeypatch):
    seen = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            seen.update(kwargs)
            class Msg:
                content = "[]"
            class Resp:
                message = Msg()
            return Resp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(extractor, "AsyncOllama", lambda **kw: FakeClient())
    rows = asyncio.run(
        extractor._extract_with_model(  # noqa: SLF001
            model="qwen3.5:9b", chunk="Sömnbrist försämrar koncentrationen.", domain_hint="test"
        )
    )
    assert rows == []
    assert seen.get("think") is False
    assert seen.get("options", {}).get("num_predict") == extractor.EXTRACT_NUM_PREDICT
