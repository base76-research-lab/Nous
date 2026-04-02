from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_nightly_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "nouse_nightly_eval.py"
    spec = importlib.util.spec_from_file_location("nouse_nightly_eval", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_mission_scorecard_from_local_artifacts(tmp_path: Path):
    nightly = _load_nightly_module()

    mission_path = tmp_path / "mission.json"
    queue_path = tmp_path / "queue.json"
    metrics_path = tmp_path / "mission_metrics.jsonl"

    mission_path.write_text(
        json.dumps(
            {
                "mission": "Ny standard för AI",
                "north_star": "Brain-first",
                "focus_domains": ["ai", "neuro"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    queue_path.write_text(
        json.dumps(
            [
                {"status": "pending"},
                {"status": "done", "avg_evidence": 0.72},
                {"status": "awaiting_approval"},
                {"status": "failed"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rows = [
        {
            "delta": {"new_relations": 8, "discoveries": 3, "bisoc_candidates": 12},
            "limbic": {"arousal": 0.9},
        },
        {
            "delta": {"new_relations": 11, "discoveries": 4, "bisoc_candidates": 18},
            "limbic": {"arousal": 1.0},
        },
    ]
    metrics_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8",
    )

    nightly.MISSION_PATH = mission_path
    nightly.QUEUE_PATH = queue_path
    nightly.MISSION_METRICS_PATH = metrics_path

    score = nightly._build_mission_scorecard(
        trace_summary={"pass_rate": 0.83},
        status={"lambda": 0.9},
        know={"coverage": {"complete": 0.61, "strong_facts": 0.53}},
        mem={"semantic_facts": 220},
    )

    assert bool(score["mission_active"]) is True
    assert score["mission"] == "Ny standard för AI"
    assert "components" in score
    assert "queue_health" in score["components"]
    assert score["band"] in {"gron", "gul", "rod"}
    assert isinstance(score["recommendations"], list)


def test_build_report_includes_mission_section():
    nightly = _load_nightly_module()
    report = nightly._build_report(
        trace_path=None,
        trace_summary={"total": 10, "passed": 9, "pass_rate": 0.9},
        status={"concepts": 10, "relations": 20, "cycle": 3, "lambda": 0.9, "arousal": 1.0},
        know={"missing_total": 2},
        mem={"unconsolidated_total": 1, "semantic_facts": 30},
        scorecard={
            "mission_active": True,
            "mission": "x",
            "north_star": "y",
            "focus_domains": ["a", "b"],
            "overall_score": 0.77,
            "band": "gron",
            "components": {
                "stability": 0.8,
                "evidence": 0.7,
                "novelty": 0.6,
                "queue_health": 0.9,
            },
            "queue_counts": {
                "pending": 1,
                "in_progress": 0,
                "awaiting_approval": 0,
                "done": 2,
                "failed": 0,
            },
            "metrics_window": 5,
            "recommendations": ["ok"],
        },
        probe_rc=0,
        probe_output="hello",
        stamp="20260330T000000Z",
    )
    assert "Mission Scorecard" in report
    assert "overall_score" in report
