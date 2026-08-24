"""Deterministic local demo of Nous relation retrieval and uncertainty."""
from __future__ import annotations

import tempfile
from pathlib import Path

import nouse


with tempfile.TemporaryDirectory(prefix="nouse_demo_") as directory:
    brain = nouse.attach(
        db_path=Path(directory) / "field.sqlite",
        prefer_http=False,
    )

    brain.add(
        "raw_outputs",
        "supports",
        "reproducibility",
        why="A complete experiment preserves raw outputs and configuration.",
        evidence_score=0.90,
    )
    brain.add(
        "reproducibility",
        "requires",
        "dataset_hash",
        why="A dataset hash identifies the exact evaluation input.",
        evidence_score=0.84,
    )
    brain.add(
        "reproducibility",
        "motsäger",
        "untracked_result",
        why="An untracked result cannot be independently reconstructed.",
        evidence_score=0.82,
    )

    result = brain.query("reproducibility")
    contradiction = brain.check_contradiction(
        "The untracked result is reproducible.", threshold=0.75
    )

    print("=== Query result ===")
    print(result.context_block())
    print("\n=== Structured fields ===")
    print("has_knowledge:", result.has_knowledge)
    print("confidence:", result.confidence)
    print("relations:", len(result.axioms))
    print("\n=== Contradiction check ===")
    print("recommendation:", contradiction.recommendation)
    print("has_conflict:", contradiction.has_conflict)
