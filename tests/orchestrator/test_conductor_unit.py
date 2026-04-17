"""
Minimala enhetstester för CognitiveConductor och CCNode.

Test 1 — CCNode.predict: lyckat HTTP-svar → korrekt (prediction, confidence)
Test 2 — CCNode.predict: HTTP-fel → ("", 0.0), aldrig exception
Test 3 — conductor.run_cognitive_cycle: komplett cykel med stubbad CCNode → CycleResult OK
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[2] / "src"))

os.environ["NOUSE_TEACHER_BASE_URL"] = "https://models.inference.ai.azure.com"
os.environ["GITHUB_TOKEN"] = "test-token"

from nouse.orchestrator.conductor import CCNode, CognitiveConductor, CycleResult


# ── Hjälpare ──────────────────────────────────────────────────────────────────

_GOOD_PAYLOAD = {
    "choices": [
        {
            "message": {
                "content": json.dumps(
                    {"prediction": "Distribuerad nätverksdynamik", "confidence": 0.87}
                )
            }
        }
    ]
}

_CC_CONTEXT = {
    "episode": "Skogssvampar och kvanttunnling delar emergent nätverkslogik.",
    "domain": "test",
    "tda": {"h0_a": 1, "h1_a": 1, "h0_b": 1, "h1_b": 0, "topo_sim": 0.6},
    "self": {"name": "NousAi", "mission": "test", "active_drive": "curiosity"},
}

_VECTORS = [
    [0.1, 0.2, 0.3, 0.4] * 10,
    [0.5, 0.1, 0.8, 0.2] * 10,
    [0.3, 0.9, 0.1, 0.7] * 10,
    [0.8, 0.4, 0.2, 0.6] * 10,
]


# ── Test 1: CCNode lyckat svar ────────────────────────────────────────────────

def test_ccnode_predict_returns_prediction_and_confidence():
    """CCNode.predict returnerar (str, float) vid lyckat HTTP-svar."""
    async def _run():
        node = CCNode(
            model="gpt-4o",
            base_url="https://models.inference.ai.azure.com",
        )
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = _GOOD_PAYLOAD

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            prediction, confidence = await node.predict(_CC_CONTEXT, "synthesize")

        assert prediction == "Distribuerad nätverksdynamik"
        assert abs(confidence - 0.87) < 1e-6
        mock_client.post.assert_awaited_once()

    asyncio.run(_run())


# ── Test 2: CCNode HTTP-fel → ("", 0.0) ──────────────────────────────────────

def test_ccnode_predict_returns_empty_on_http_error():
    """CCNode.predict returnerar ('', 0.0) vid HTTP-fel — aldrig exception."""
    async def _run():
        node = CCNode(
            model="gpt-4o",
            base_url="https://models.inference.ai.azure.com",
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            prediction, confidence = await node.predict(_CC_CONTEXT, "synthesize")

        assert prediction == ""
        assert confidence == 0.0

    asyncio.run(_run())


# ── Test 3: conductor.run_cognitive_cycle komplett cykel ─────────────────────

def test_conductor_run_cognitive_cycle_returns_valid_result():
    """
    run_cognitive_cycle med stubbad CCNode returnerar ett komplett CycleResult.
    Vektorer skickas in explicit för att TDA ska köras.
    CCNode.predict ska anropas exakt en gång.
    """
    async def _run():
        stub_cc = MagicMock(spec=CCNode)
        stub_cc.predict = AsyncMock(return_value=("Emergent nätverksmönster", 0.75))

        conductor = CognitiveConductor(cc_node=stub_cc)

        result: CycleResult = await conductor.run_cognitive_cycle(
            episode_text="Skogssvampar bildar mycel-nätverk. Primtal har global regularitet.",
            domain="unit_test",
            vectors=_VECTORS,
            source="pytest",
            session_id="test-session",
        )

        assert isinstance(result, CycleResult)
        assert result.episode_id
        assert 0.0 <= result.bisociation_score <= 1.0
        assert result.bisociation_verdict in {"BISOCIATION", "ASSOCIATION"}
        assert result.tda_h0_a >= 1
        assert result.tda_h0_b >= 1
        assert result.cc_prediction == "Emergent nätverksmönster"
        assert abs(result.cc_confidence - 0.75) < 1e-6
        stub_cc.predict.assert_awaited_once()

    asyncio.run(_run())
