#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
METRICS_DIR = Path(os.getenv("NOUSE_EVAL_METRICS_DIR", str(REPO_ROOT / "results" / "metrics")))
EVAL_SET = Path(
    os.getenv(
        "NOUSE_EVAL_SET",
        str(REPO_ROOT / "results" / "eval_set_trace_observability.yaml"),
    )
)
API_BASE = os.getenv("NOUSE_EVAL_API_BASE", "http://127.0.0.1:8765").rstrip("/")
MISSION_PATH = Path.home() / ".local" / "share" / "nouse" / "mission.json"
MISSION_METRICS_PATH = Path.home() / ".local" / "share" / "nouse" / "mission_metrics.jsonl"
QUEUE_PATH = Path.home() / ".local" / "share" / "nouse" / "research_queue.json"

try:
    PROBE_LIMIT = max(1, int((os.getenv("NOUSE_EVAL_LIMIT") or "12").strip()))
except ValueError:
    PROBE_LIMIT = 12

try:
    PROBE_TIMEOUT = max(10.0, float((os.getenv("NOUSE_EVAL_TIMEOUT_SEC") or "90").strip()))
except ValueError:
    PROBE_TIMEOUT = 90.0


def _run_probe() -> tuple[int, str]:
    bin_path = REPO_ROOT / ".venv" / "bin" / "nouse"
    cmd = [
        str(bin_path if bin_path.exists() else "nouse"),
        "trace-probe",
        "--set",
        str(EVAL_SET),
        "--limit",
        str(PROBE_LIMIT),
        "--timeout",
        str(PROBE_TIMEOUT),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, output.strip()


def _latest_probe_json() -> Path | None:
    if not METRICS_DIR.exists():
        return None
    files = sorted(METRICS_DIR.glob("trace_probe_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _api_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=10.0) as client:
        r = client.get(f"{API_BASE}{path}", params=params)
        r.raise_for_status()
        payload = r.json()
    if isinstance(payload, dict):
        return payload
    return {"raw": payload}


def _trace_summary(trace_path: Path | None) -> dict[str, Any]:
    out = {"total": 0, "passed": 0, "pass_rate": 0.0}
    if not trace_path or not trace_path.exists():
        return out
    try:
        data = json.loads(trace_path.read_text(encoding="utf-8"))
    except Exception:
        return out
    out["total"] = int(data.get("total", 0) or 0)
    out["passed"] = int(data.get("passed", 0) or 0)
    out["pass_rate"] = float(data.get("pass_rate", 0.0) or 0.0)
    return out


def _collect_runtime() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        status = _api_json("/api/status")
    except Exception as e:
        status = {"error": str(e)}
    try:
        know = _api_json(
            "/api/knowledge/audit",
            params={"limit": 1, "strict": "true", "min_evidence_score": 0.65},
        )
    except Exception as e:
        know = {"error": str(e)}
    try:
        mem = _api_json("/api/memory/audit", params={"limit": 1})
    except Exception as e:
        mem = {"error": str(e)}
    return status, know, mem


def _load_json_file(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl_tail(path: Path, *, limit: int = 64) -> list[dict[str, Any]]:
    if not path.exists() or limit <= 0:
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        item = line.strip()
        if not item:
            continue
        try:
            parsed = json.loads(item)
        except Exception:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows[-limit:]


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


def _band(score: float) -> str:
    if score >= 0.75:
        return "gron"
    if score >= 0.5:
        return "gul"
    return "rod"


def _safe_mean(values: list[float], default: float = 0.0) -> float:
    if not values:
        return default
    return float(mean(values))


def _build_mission_scorecard(
    *,
    trace_summary: dict[str, Any],
    status: dict[str, Any],
    know: dict[str, Any],
    mem: dict[str, Any],
) -> dict[str, Any]:
    mission = _load_json_file(MISSION_PATH)
    queue_rows = _load_json_file(QUEUE_PATH)
    metrics_rows = _load_jsonl_tail(MISSION_METRICS_PATH, limit=64)

    if not isinstance(mission, dict):
        mission = {}
    if not isinstance(queue_rows, list):
        queue_rows = []

    queue_counts = {
        "pending": 0,
        "in_progress": 0,
        "awaiting_approval": 0,
        "done": 0,
        "failed": 0,
    }
    done_evidence: list[float] = []
    for row in queue_rows:
        if not isinstance(row, dict):
            continue
        st = str(row.get("status", "pending"))
        if st in queue_counts:
            queue_counts[st] += 1
        if st == "done":
            try:
                done_evidence.append(float(row.get("avg_evidence", 0.0) or 0.0))
            except Exception:
                pass
    queue_total = max(1, sum(queue_counts.values()))

    pass_rate = float(trace_summary.get("pass_rate", 0.0) or 0.0)
    failed_ratio = float(queue_counts["failed"]) / float(queue_total)
    new_rel_values = [
        float((row.get("delta") or {}).get("new_relations", 0.0) or 0.0)
        for row in metrics_rows
    ]
    arousal_values = [
        float((row.get("limbic") or {}).get("arousal", 0.0) or 0.0)
        for row in metrics_rows
    ]
    rel_stability = 1.0
    if len(new_rel_values) > 1:
        rel_stability = _clamp(1.0 - (pstdev(new_rel_values) / 20.0))
    arousal_stability = 0.5
    if arousal_values:
        arousal_span = max(arousal_values) - min(arousal_values)
        arousal_stability = _clamp(1.0 - (arousal_span / 1.2))

    stability = _clamp(
        (0.45 * pass_rate)
        + (0.25 * (1.0 - failed_ratio))
        + (0.15 * rel_stability)
        + (0.15 * arousal_stability)
    )

    coverage = know.get("coverage") if isinstance(know, dict) else {}
    if not isinstance(coverage, dict):
        coverage = {}
    complete_cov = float(coverage.get("complete", 0.0) or 0.0)
    strong_cov = float(coverage.get("strong_facts", 0.0) or 0.0)
    done_ev = _safe_mean(done_evidence, default=0.5)
    semantic_facts = float(mem.get("semantic_facts", 0.0) or 0.0)
    facts_score = _clamp(semantic_facts / 1500.0)

    evidence = _clamp(
        (0.35 * complete_cov)
        + (0.25 * strong_cov)
        + (0.25 * done_ev)
        + (0.15 * facts_score)
    )

    discoveries = [
        float((row.get("delta") or {}).get("discoveries", 0.0) or 0.0)
        for row in metrics_rows
    ]
    bisoc = [
        float((row.get("delta") or {}).get("bisoc_candidates", 0.0) or 0.0)
        for row in metrics_rows
    ]
    disc_score = _clamp(_safe_mean(discoveries, default=0.0) / 8.0)
    bisoc_score = _clamp(_safe_mean(bisoc, default=0.0) / 40.0)
    rel_score = _clamp(_safe_mean(new_rel_values, default=0.0) / 20.0)
    novelty = _clamp((0.40 * disc_score) + (0.35 * bisoc_score) + (0.25 * rel_score))

    pending = queue_counts["pending"]
    awaiting = queue_counts["awaiting_approval"]
    done = queue_counts["done"]
    backlog_score = _clamp(1.0 - (float(pending) / 25.0))
    approval_score = _clamp(1.0 - (float(awaiting) / 10.0))
    failure_score = _clamp(1.0 - failed_ratio)
    throughput_score = _clamp(float(done) / float(max(1, done + pending + awaiting)))
    queue_health = _clamp(
        (0.35 * backlog_score)
        + (0.30 * failure_score)
        + (0.20 * approval_score)
        + (0.15 * throughput_score)
    )

    overall = _clamp(
        (0.35 * stability)
        + (0.30 * evidence)
        + (0.20 * novelty)
        + (0.15 * queue_health)
    )

    recommendations: list[str] = []
    if stability < 0.6:
        recommendations.append("Stability: öka timeout/backoff och minska samtidiga riskjobb.")
    if evidence < 0.6:
        recommendations.append("Evidence: prioritera tasks med validerbar evidens och högre strict gate.")
    if novelty < 0.5:
        recommendations.append("Novelty: seeda fler tvärdomän-taskar från mission-fokus.")
    if queue_health < 0.6:
        recommendations.append("Queue health: rensa backlog och hantera pending HITL-interrupts dagligen.")
    if not recommendations:
        recommendations.append("Läget är stabilt; fortsätt med samma mission och följ trenden.")

    return {
        "mission_active": bool(mission.get("mission")),
        "mission": str(mission.get("mission") or ""),
        "north_star": str(mission.get("north_star") or ""),
        "focus_domains": list(mission.get("focus_domains") or []),
        "components": {
            "stability": stability,
            "evidence": evidence,
            "novelty": novelty,
            "queue_health": queue_health,
        },
        "overall_score": overall,
        "band": _band(overall),
        "queue_counts": queue_counts,
        "trace_pass_rate": pass_rate,
        "knowledge_complete": complete_cov,
        "knowledge_strong": strong_cov,
        "metrics_window": len(metrics_rows),
        "recommendations": recommendations,
    }


def _build_report(
    *,
    trace_path: Path | None,
    trace_summary: dict[str, Any],
    status: dict[str, Any],
    know: dict[str, Any],
    mem: dict[str, Any],
    scorecard: dict[str, Any],
    probe_rc: int,
    probe_output: str,
    stamp: str,
) -> str:
    pass_rate = trace_summary["pass_rate"]
    if pass_rate >= 0.9:
        quality = "gron"
    elif pass_rate >= 0.7:
        quality = "gul"
    else:
        quality = "rod"

    c = scorecard.get("components") if isinstance(scorecard, dict) else {}
    if not isinstance(c, dict):
        c = {}
    queue_counts = scorecard.get("queue_counts") if isinstance(scorecard, dict) else {}
    if not isinstance(queue_counts, dict):
        queue_counts = {}
    recs = scorecard.get("recommendations") if isinstance(scorecard, dict) else []
    if not isinstance(recs, list):
        recs = []

    rec_block = "\n".join(f"- {str(r)}" for r in recs[:5]) or "- (inga rekommendationer)"

    return (
        f"# nouse Nightly Quality Report ({stamp} UTC)\n\n"
        f"## Trace Probe\n"
        f"- return_code: {probe_rc}\n"
        f"- total: {trace_summary['total']}\n"
        f"- passed: {trace_summary['passed']}\n"
        f"- pass_rate: {pass_rate:.1%}\n"
        f"- quality_band: {quality}\n"
        f"- trace_file: {trace_path or 'missing'}\n\n"
        f"## Runtime Snapshot\n"
        f"- graph: concepts={status.get('concepts','?')} relations={status.get('relations','?')} cycle={status.get('cycle','?')}\n"
        f"- limbic: lambda={status.get('lambda','?')} arousal={status.get('arousal','?')}\n"
        f"- knowledge_missing_total: {know.get('missing_total','?')}\n"
        f"- memory_unconsolidated_total: {mem.get('unconsolidated_total','?')}\n"
        f"- memory_semantic_facts: {mem.get('semantic_facts','?')}\n\n"
        f"## Mission Scorecard\n"
        f"- mission_active: {scorecard.get('mission_active', False)}\n"
        f"- mission: {scorecard.get('mission','(none)')}\n"
        f"- north_star: {scorecard.get('north_star','')}\n"
        f"- focus_domains: {', '.join(scorecard.get('focus_domains') or [])}\n"
        f"- overall_score: {float(scorecard.get('overall_score',0.0)):.3f}\n"
        f"- band: {scorecard.get('band','rod')}\n"
        f"- stability: {float(c.get('stability',0.0)):.3f}\n"
        f"- evidence: {float(c.get('evidence',0.0)):.3f}\n"
        f"- novelty: {float(c.get('novelty',0.0)):.3f}\n"
        f"- queue_health: {float(c.get('queue_health',0.0)):.3f}\n"
        f"- queue_counts: pending={int(queue_counts.get('pending',0))} "
        f"in_progress={int(queue_counts.get('in_progress',0))} "
        f"awaiting_approval={int(queue_counts.get('awaiting_approval',0))} "
        f"done={int(queue_counts.get('done',0))} failed={int(queue_counts.get('failed',0))}\n"
        f"- metrics_window: {int(scorecard.get('metrics_window',0) or 0)}\n\n"
        f"### Mission Recommendations\n"
        f"{rec_block}\n\n"
        f"## Probe Output (tail)\n"
        f"```\n{probe_output[-4000:]}\n```\n"
    )


def main() -> int:
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    probe_rc, probe_output = _run_probe()
    trace_path = _latest_probe_json()
    trace_summary = _trace_summary(trace_path)
    status, know, mem = _collect_runtime()
    scorecard = _build_mission_scorecard(
        trace_summary=trace_summary,
        status=status,
        know=know,
        mem=mem,
    )
    report = _build_report(
        trace_path=trace_path,
        trace_summary=trace_summary,
        status=status,
        know=know,
        mem=mem,
        scorecard=scorecard,
        probe_rc=probe_rc,
        probe_output=probe_output,
        stamp=stamp,
    )

    out = METRICS_DIR / f"nightly_quality_{stamp}.md"
    latest = METRICS_DIR / "nightly_quality_latest.md"
    out.write_text(report, encoding="utf-8")
    latest.write_text(report, encoding="utf-8")
    score_out = METRICS_DIR / f"nightly_mission_scorecard_{stamp}.json"
    score_latest = METRICS_DIR / "nightly_mission_scorecard_latest.json"
    score_json = json.dumps(scorecard, ensure_ascii=False, indent=2)
    score_out.write_text(score_json, encoding="utf-8")
    score_latest.write_text(score_json, encoding="utf-8")
    print(f"[nightly-eval] report: {out}")
    print(f"[nightly-eval] mission_scorecard: {score_out}")

    if probe_rc != 0:
        print("[nightly-eval] trace-probe failed")
        return probe_rc
    if trace_path is None:
        print("[nightly-eval] trace-probe output saknas")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
