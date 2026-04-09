from __future__ import annotations

from pathlib import Path

import nouse.web.server as ws


class _FieldForCenter:
    def concept_domain(self, name: str):
        if name == "Björn Wikström":
            return "User"
        return None

    def concepts(self):
        return [
            {"name": "Björn Wikström", "domain": "User"},
            {"name": "Claude", "domain": "AI"},
        ]


class _FieldForPayload:
    def stats(self):
        return {"concepts": 2, "relations": 1}


def test_graph_center_state_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ws, "GRAPH_CENTER_STATE_PATH", tmp_path / "graph_center.json")
    out = ws._save_graph_center_state("Björn Wikström", source="test")  # noqa: SLF001
    loaded = ws._load_graph_center_state()  # noqa: SLF001
    assert out["node"] == "Björn Wikström"
    assert loaded["node"] == "Björn Wikström"
    assert loaded["source"] == "test"


def test_resolve_graph_center_node_case_insensitive_match():
    resolved, exists = ws._resolve_graph_center_node(  # noqa: SLF001
        _FieldForCenter(),
        "björn wikström",
    )
    assert exists is True
    assert resolved == "Björn Wikström"


def test_resolve_node_id_in_rows_case_insensitive():
    rows = [
        {"id": "Björn Wikström"},
        {"id": "NoUse"},
    ]
    resolved = ws._resolve_node_id_in_rows(rows, "björn wikström")  # noqa: SLF001
    assert resolved == "Björn Wikström"


def test_graph_payload_includes_center_info(monkeypatch):
    monkeypatch.setattr(ws, "get_field", lambda: _FieldForPayload())
    monkeypatch.setattr(
        ws,
        "_graph_rows",
        lambda **_kwargs: (
            [{"id": "Björn Wikström", "group": "User"}],
            [],
        ),
    )
    monkeypatch.setattr(
        ws,
        "_load_graph_center_state",
        lambda: {"node": "björn wikström", "updated_at": "now", "source": "test"},
    )

    payload = ws._graph_payload(limit_nodes=100, limit_edges=200, activity_window=24)  # noqa: SLF001
    center = payload.get("center") or {}
    assert center.get("configured") is True
    assert center.get("node") == "Björn Wikström"
    assert center.get("in_view") is True
    assert center.get("source") == "test"
