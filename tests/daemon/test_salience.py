from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from nouse.daemon.salience import (
    looks_like_dependency_source,
    concept_depth,
    use_component,
    recency_decay,
    top_of_mind_score,
    concept_top_of_mind_score,
)
from nouse.field.surface import FieldSurface


def _mk_field(tmp_path: Path) -> FieldSurface:
    return FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)


def test_looks_like_dependency_source_flags_site_packages_path():
    assert looks_like_dependency_source(
        "/home/x/.virtualenvs/research/lib/python3.14/site-packages/httpx/_exceptions.py"
    ) is True


def test_looks_like_dependency_source_false_for_real_source():
    assert looks_like_dependency_source("/home/x/IIC/02_LIBRARY/RESEARCH/paper.md") is False


def test_looks_like_dependency_source_false_for_empty_or_none():
    assert looks_like_dependency_source("") is False
    assert looks_like_dependency_source(None) is False


def test_use_component_floor_and_ceiling():
    assert use_component(1.0) == 0.45   # never-strengthened floor
    assert use_component(3.0) == 0.95   # clamped ceiling
    assert use_component(0.0) == 0.45   # clamped floor, not negative


def test_recency_decay_is_one_for_missing_or_unparseable_timestamp():
    assert recency_decay(None) == 1.0
    assert recency_decay("not-a-date") == 1.0


def test_recency_decay_handles_naive_timestamp_like_surface_py_produces():
    # surface.py writes datetime.utcnow().isoformat() -- naive, no "Z", no offset.
    now = datetime.now(timezone.utc)
    half_life_ago_naive = (now - timedelta(days=21)).replace(tzinfo=None).isoformat()
    assert abs(recency_decay(half_life_ago_naive, now=now) - 0.5) < 0.01


def test_recency_decay_is_near_one_for_just_created():
    now = datetime.now(timezone.utc)
    assert recency_decay(now.isoformat(), now=now) > 0.99


def test_top_of_mind_score_combines_use_and_recency():
    now = datetime.now(timezone.utc)
    assert top_of_mind_score(3.0, now.isoformat()) > top_of_mind_score(1.0, now.isoformat())


def test_concept_depth_counts_only_non_dependency_in_relations(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("Real Source", "cites", "Hub", source_tag="file:///paper.md")
    field.add_relation(
        "Noise Source", "cites", "Hub",
        source_tag="/x/.venv/lib/site-packages/pkg/mod.py",
    )
    assert concept_depth(field, "Hub") == 1


def test_concept_top_of_mind_score_reflects_strengthen(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("A", "relates_to", "B", source_tag="file")
    baseline = concept_top_of_mind_score(field, "A")
    field.strengthen("A", "B", delta=2.0)
    boosted = concept_top_of_mind_score(field, "A")
    assert boosted > baseline


def test_concept_top_of_mind_score_zero_for_isolated_concept(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("Lonely", domain="misc")
    assert concept_top_of_mind_score(field, "Lonely") == 0.0
