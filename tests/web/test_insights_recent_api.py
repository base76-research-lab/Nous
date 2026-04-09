from __future__ import annotations

import json
from pathlib import Path

import nouse.web.server as ws


def test_latest_insights_returns_recent_entries_with_links(monkeypatch, tmp_path: Path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    insights_path = memory_dir / "insights.jsonl"
    monkeypatch.setenv("NOUSE_MEMORY_DIR", str(memory_dir))

    older = {
        "ts": "2026-04-08T09:00:00+00:00",
        "insight_id": "old_1",
        "kind": "relation_pattern",
        "tier": "indikation",
        "score": 0.61,
        "support": 2,
        "mean_evidence": 0.66,
        "statement": "Äldre finding",
        "basis": {"method": "relation_grouping", "score_components": {"evidence": 0.66}},
        "basis_evidence_refs": ["why:äldre"],
    }
    latest = {
        "ts": "2026-04-08T10:00:00+00:00",
        "insight_id": "new_1",
        "kind": "domain_bridge",
        "tier": "validerad",
        "score": 0.83,
        "support": 4,
        "mean_evidence": 0.79,
        "statement": "Ny finding med källa https://example.com/paper",
        "basis": {
            "method": "domain_bridge_detection",
            "score_components": {
                "evidence": 0.79,
                "support": 0.8,
                "novelty": 0.9,
                "actionability": 0.7,
            },
            "sample_rows": [
                {
                    "src": "nouse",
                    "rel": "enables",
                    "tgt": "grounding",
                    "evidence": 0.79,
                }
            ],
        },
        "basis_evidence_refs": [
            "source_url:https://research.example.org/report",
            "why:domänbro",
        ],
        "source": "cli:research",
    }
    insights_path.write_text(
        "\n".join([json.dumps(older, ensure_ascii=False), json.dumps(latest, ensure_ascii=False)]) + "\n",
        encoding="utf-8",
    )

    payload = ws._latest_insights(limit=1)  # noqa: SLF001
    assert payload["ok"] is True
    assert payload["count"] == 1
    entry = payload["entries"][0]
    assert entry["insight_id"] == "new_1"
    assert entry["tier"] == "validerad"
    assert entry["basis"]["method"] == "domain_bridge_detection"
    assert any("https://example.com/paper" in url for url in entry["links"])
    assert any("https://research.example.org/report" in url for url in entry["links"])


def test_latest_insights_handles_missing_file(monkeypatch, tmp_path: Path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NOUSE_MEMORY_DIR", str(memory_dir))

    payload = ws._latest_insights(limit=5)  # noqa: SLF001
    assert payload["ok"] is True
    assert payload["count"] == 0
    assert payload["entries"] == []
