from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from nouse.daemon.salience import (
    looks_like_dependency_source,
    looks_like_code_file,
    is_code_only_concept,
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


def test_looks_like_code_file_flags_py_but_not_prose():
    assert looks_like_code_file("/home/x/Work/nous/src/nouse/daemon/sources.py") is True
    assert looks_like_code_file("/home/x/IIC/02_LIBRARY/RESEARCH/paper.md") is False
    assert looks_like_code_file("/home/x/notes.txt") is False
    assert looks_like_code_file("") is False
    assert looks_like_code_file(None) is False


def test_is_code_only_concept_true_when_every_relation_is_code(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("ROOT", "used_in", "sources.py", source_tag="/x/daemon/sources.py")
    field.add_relation("ROOT", "used_in", "main.py", source_tag="/x/daemon/main.py")
    assert is_code_only_concept(field, "ROOT") is True


def test_is_code_only_concept_false_when_any_relation_is_prose(tmp_path):
    # Real-world case this exists for: a concept genuinely discussed in
    # STATUS.md/design docs stays included even if it ALSO shows up in code.
    field = _mk_field(tmp_path)
    field.add_relation("salience", "used_in", "salience.py", source_tag="/x/daemon/salience.py")
    field.add_relation("salience", "discussed_in", "STATUS.md", source_tag="/x/STATUS.md")
    assert is_code_only_concept(field, "salience") is False


def test_is_code_only_concept_false_for_concept_with_no_relations(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("Lonely", domain="misc")
    assert is_code_only_concept(field, "Lonely") is False


def test_is_code_only_concept_ignores_auto_tagged_noise_when_judging(tmp_path):
    # Real bug, found against the live graph, not synthetic data: ROOT had
    # ~114 "auto"-tagged relations (no real source at all) plus ~19 real
    # .py-file relations. An earlier version of this function checked ALL
    # relations, and "auto" fails looks_like_code_file(), so all() went
    # False and ROOT was never caught despite its only REAL evidence being
    # 100% code. "auto" must be excluded from the judgment entirely, not
    # counted as evidence of anything.
    field = _mk_field(tmp_path)
    for i in range(20):
        field.add_relation("ROOT", "referenced_in", f"unrelated{i}", source_tag="auto")
    field.add_relation("ROOT", "used_in", "sources.py", source_tag="/x/daemon/sources.py")
    field.add_relation("ROOT", "used_in", "main.py", source_tag="/x/daemon/main.py")
    assert is_code_only_concept(field, "ROOT") is True


# ── Codex's proposed regression tests for the two dependency-filtering
# fixes above (concept_depth, concept_top_of_mind_score) -- from the same
# relay:codex dialogue, applied after independent review. ──────────────


def test_concept_depth_counts_distinct_non_dependency_neighbors(tmp_path):
    field = _mk_field(tmp_path)
    # Two parallel relation rows from the same neighboring concept.
    field.add_relation("Repeated Source", "cites", "Hub", source_tag="file:///paper.md")
    field.add_relation("Repeated Source", "supports", "Hub", source_tag="file:///notes.md")
    field.add_relation("Other Source", "mentions", "Hub", source_tag="file:///other.md")
    field.add_relation("Dependency Source", "mentions", "Hub", source_tag="/x/.venv/lib/site-packages/pkg/mod.py")

    assert concept_depth(field, "Hub") == 2


def test_concept_top_of_mind_score_ignores_dependency_relations(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("Concept", "relates_to", "Real Target", strength=1.0, source_tag="file:///source.md")
    field.add_relation(
        "Dependency Source", "relates_to", "Concept", strength=3.0,
        source_tag="/x/.venv/lib/site-packages/pkg/mod.py",
    )
    # The dependency edge would score near 0.95 if not filtered. Only the
    # real edge's ~0.45 (strength=1.0, never reinforced) should remain.
    score = concept_top_of_mind_score(field, "Concept")
    assert 0.40 < score < 0.50


def test_concept_top_of_mind_score_zero_for_dependency_only_concept(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation(
        "Dependency Source", "relates_to", "Concept", strength=3.0,
        source_tag="/x/node_modules/pkg/index.js",
    )
    assert concept_top_of_mind_score(field, "Concept") == 0.0
