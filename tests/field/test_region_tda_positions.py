from __future__ import annotations

from pathlib import Path

from nouse.field.surface import FieldSurface
from nouse.field.brain_topology import region_tda_positions


def _mk_field(tmp_path: Path) -> FieldSurface:
    return FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)


# Domain pairs chosen to classify into 4 distinct regions (see brain_topology.classify_domain)
_DOMAIN_TO_REGION = {
    "matematik": "frontal", "logik": "frontal",
    "kognition": "parietal", "systemteori": "parietal",
    "minne": "hippocampus", "inlärning": "hippocampus",
    "emotion": "amygdala", "värde": "amygdala",
}


def _seed_graph(field: FieldSurface, monkeypatch) -> None:
    vectors: dict[str, list[float]] = {}
    for i, (domain, _region) in enumerate(_DOMAIN_TO_REGION.items()):
        name_a, name_b = f"{domain}_A", f"{domain}_B"
        field.add_concept(name_a, domain, source="test", ensure_knowledge=False)
        field.add_concept(name_b, domain, source="test", ensure_knowledge=False)
        field.add_relation(name_a, "relates_to", name_b, source_tag="test")
        # Distinct-ish vector per domain so regions separate in MDS space
        base = float(i)
        vectors[name_a] = [base, base * 0.5, 1.0]
        vectors[name_b] = [base + 0.1, base * 0.5 + 0.1, 1.0]

    def _fake_ensure(rows):  # type: ignore[no-untyped-def]
        return {r["name"]: vectors[r["name"]] for r in rows if r["name"] in vectors}

    monkeypatch.setattr(field, "_ensure_concept_embeddings", _fake_ensure)


def test_region_tda_positions_returns_coords_for_covered_regions(tmp_path, monkeypatch):
    field = _mk_field(tmp_path)
    _seed_graph(field, monkeypatch)

    positions = region_tda_positions(field, min_domains_per_region=1, min_regions=4)

    assert set(positions) == {"frontal", "parietal", "hippocampus", "amygdala"}
    for pos in positions.values():
        assert len(pos) == 3
        assert all(isinstance(v, float) for v in pos)


def test_region_tda_positions_empty_when_below_min_regions(tmp_path, monkeypatch):
    field = _mk_field(tmp_path)
    field.add_concept("matematik_A", "matematik", source="test", ensure_knowledge=False)
    field.add_concept("matematik_B", "matematik", source="test", ensure_knowledge=False)
    field.add_relation("matematik_A", "relates_to", "matematik_B", source_tag="test")

    def _fake_ensure(rows):  # type: ignore[no-untyped-def]
        return {"matematik_A": [1.0, 0.0, 0.0], "matematik_B": [1.1, 0.0, 0.0]}

    monkeypatch.setattr(field, "_ensure_concept_embeddings", _fake_ensure)

    positions = region_tda_positions(field, min_domains_per_region=1, min_regions=4)

    assert positions == {}


def test_region_tda_positions_scales_to_target_radius(tmp_path, monkeypatch):
    field = _mk_field(tmp_path)
    _seed_graph(field, monkeypatch)

    positions = region_tda_positions(field, min_domains_per_region=1, min_regions=4, target_radius=90.0)

    max_norm = max((sum(v * v for v in pos) ** 0.5) for pos in positions.values())
    assert 85.0 <= max_norm <= 90.5
