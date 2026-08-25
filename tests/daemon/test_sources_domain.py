from __future__ import annotations

from pathlib import Path

from nouse.daemon.brain_atlas import classify_domain
from nouse.daemon.sources import _domain_from_path


def test_domain_from_path_routes_pcpe_preprint_to_perception():
    path = Path(
        "/home/bjorn/IIC/02_LIBRARY/RESEARCH/papers/preprints/"
        "Perceptual Coherence and Perceived Exclusion.pdf"
    )
    assert _domain_from_path(path) == "perception"


def test_domain_from_path_routes_pcpe_ongoing_folder_to_perception():
    path = Path("/home/bjorn/IIC/02_LIBRARY/RESEARCH/papers/ongoing/PCPE/draft.md")
    assert _domain_from_path(path) == "perception"


def test_pcpe_domain_classifies_to_occipital_lobe():
    """The point of routing PCPE to "perception" rather than the generic
    "AI-forskning" bucket: brain_atlas.classify_domain() must actually
    place it in occipital_lobe (Tududi subtask: give occipital real source
    material instead of no dedicated routing at all)."""
    path = Path("/home/bjorn/IIC/02_LIBRARY/RESEARCH/papers/ongoing/PCPE/draft.md")
    domain = _domain_from_path(path)
    assert classify_domain(domain) == "occipital_lobe"


def test_domain_from_path_still_falls_back_to_ai_forskning_for_other_research():
    path = Path("/home/bjorn/IIC/02_LIBRARY/RESEARCH/papers/ongoing/shared_mind/draft.md")
    assert _domain_from_path(path) == "AI-forskning"
