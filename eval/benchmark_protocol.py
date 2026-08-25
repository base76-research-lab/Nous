"""Versioned, local-only protocol helpers for benchmark v1."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "benchmark-v1"
SCORER_VERSION = "truthfulqa-judge-v1"
CONDITIONS = {
    "bare": "model without retrieval or Nous context",
    "rag": "model with flat retrieved concept names (same graph, no ranking)",
    "nous": "model with structured Nous graph context",
    "nous_meta": "model reasoning reviewed and refined with Nous context",
    "long_context": "model with the full isolated graph dumped into context, no retrieval",
    "vector_rag": "model with embedding-retrieval top-k over the isolated graph, no graph structure",
    "nous_graph_only": "model with raw retrieved relations, no evidence/temporal/contradiction/plasticity",
    "nous_plus_evidence": "nous_graph_only + evidence scores shown and used for ranking",
    "nous_plus_temporal_validity": "nous_plus_evidence + expired relations dropped",
    "nous_plus_contradiction": "nous_plus_temporal_validity + contradiction annotations",
    "nous_plus_plasticity": "nous_plus_contradiction + Hebbian-strength ranking (== full Nous)",
}
PRIMARY_METRICS = ("mc1_accuracy", "judge_truthful_rate", "judge_score_mean")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def dataset_sha256(dataset: list[dict]) -> str:
    """Hash the exact ordered dataset presented to a run."""
    return hashlib.sha256(_canonical_json(dataset)).hexdigest()


def git_commit(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root,
            stderr=subprocess.DEVNULL, text=True,
        ).strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def package_version() -> str:
    try:
        return importlib.metadata.version("nouse")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def provider_for_model(model: str) -> str:
    for prefix in ("cerebras/", "groq/", "nvidia/", "openrouter/"):
        if model.startswith(prefix):
            return prefix[:-1]
    return "ollama"


def build_manifest(*, repo_root: Path, dataset: list[dict], dataset_id: str,
                   model: str, judge_model: str, conditions: list[str],
                   prompts: dict[str, str], configuration: dict[str, Any],
                   seed: int | None, graph_mode: str, dry_run: bool) -> dict[str, Any]:
    unknown = sorted(set(conditions) - set(CONDITIONS))
    if unknown:
        raise ValueError(f"Unknown benchmark conditions: {', '.join(unknown)}")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "dataset": {"id": dataset_id, "n": len(dataset), "sha256": dataset_sha256(dataset)},
        "git_commit": git_commit(repo_root),
        "package": {"name": "nouse", "version": package_version()},
        "models": {
            "model": model, "provider": provider_for_model(model),
            "judge_model": judge_model, "judge_provider": provider_for_model(judge_model),
        },
        "prompts": prompts,
        "configuration": configuration,
        "seed": seed,
        "graph_mode": graph_mode,
        "scorer_version": SCORER_VERSION,
        "conditions": {name: CONDITIONS[name] for name in conditions},
        "primary_metrics": list(PRIMARY_METRICS),
        "dry_run": dry_run,
    }


def classify_record(record: dict) -> str:
    """Return one auditable accounting bucket for a TruthfulQA record."""
    answer = str(record.get("answer") or "")
    if answer.startswith("[TIMEOUT]"):
        return "generation_timeout"
    if answer.startswith("[ERROR:"):
        return "generation_error"
    if not record.get("judge_valid", False):
        return "invalid_judge"
    if record.get("mc1_choice_idx") is None:
        return "missing_mc1_choice"
    return "valid_scored"


def record_accounting(records: list[dict]) -> dict[str, int]:
    buckets = {"valid_scored": 0, "invalid_judge": 0, "generation_error": 0,
               "generation_timeout": 0, "missing_mc1_choice": 0}
    for record in records:
        buckets[classify_record(record)] += 1
    return buckets


def run_status(condition_metrics: list[dict]) -> str:
    if not condition_metrics or not any(item.get("judge_valid", 0) for item in condition_metrics):
        return "invalid_no_valid_judge_records"
    return "complete"