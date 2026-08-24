"""Deterministic local demo of Nous relation retrieval and uncertainty."""
from __future__ import annotations

import tempfile
from pathlib import Path

import nouse


def main() -> None:
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
            "contradicts",
            "untracked_result",
            why="An untracked result cannot be independently reconstructed.",
            evidence_score=0.82,
        )

        source_result = brain.query("raw_outputs")
        target_result = brain.query("reproducibility")
        contradiction = brain.check_contradiction(
            "The untracked result is reproducible.", threshold=0.75
        )

        assert source_result.has_knowledge
        assert target_result.has_knowledge
        assert any(
            (axiom.src, axiom.rel, axiom.tgt)
            == ("raw_outputs", "supports", "reproducibility")
            for axiom in source_result.axioms
        )
        assert any(
            (axiom.src, axiom.rel, axiom.tgt)
            == ("reproducibility", "contradicts", "untracked_result")
            for axiom in target_result.axioms
        )
        assert contradiction.recommendation == "flag"
        assert contradiction.has_conflict

        print("=== Source query: raw_outputs ===")
        print(source_result.context_block())
        print("\n=== Target query: reproducibility ===")
        print(target_result.context_block())
        print("\n=== Structured fields ===")
        print("source_has_knowledge:", source_result.has_knowledge)
        print("target_has_knowledge:", target_result.has_knowledge)
        print("target_confidence:", target_result.confidence)
        print("target_relations:", len(target_result.axioms))
        print("\n=== Contradiction check ===")
        print("recommendation:", contradiction.recommendation)
        print("has_conflict:", contradiction.has_conflict)


if __name__ == "__main__":
    main()
