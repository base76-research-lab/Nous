"""Tester för REFLEKTORN (task #12): read-only kontrakt + prognoslogg."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from nouse.daemon import reflector
from nouse.daemon.reflector import record_outcome, reflect
from nouse.field.surface import FieldSurface


def _mk_field(tmp_path: Path) -> FieldSurface:
    return FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)


def _log(tmp_path: Path) -> Path:
    return tmp_path / "reflector_log.jsonl"


def _read_lines(path: Path) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


def _snapshot_relations(field: FieldSurface):
    rows = field.query_all_relations_with_metadata(
        limit=5000, include_evidence=True)
    return sorted(
        (r.get("id"), r.get("src"), r.get("rel"), r.get("tgt"),
         r.get("strength"), r.get("evidence_score"))
        for r in rows
    )


def _busy_graph(tmp_path: Path) -> FieldSurface:
    """Graf med relationer OCH många lösa noder (>= 6 kandidater)."""
    field = _mk_field(tmp_path)
    field.add_relation("Nav", "relates_to", "Hub", why="ryggrad",
                       evidence_score=0.5)
    for i in range(8):
        field.add_concept(f"Los{i:02d}", domain=f"dom{i % 3}")
    return field


def test_cap_max_five(tmp_path):
    field = _busy_graph(tmp_path)
    got_default = reflect(field, log_path=_log(tmp_path))
    assert len(got_default) <= 5
    got_many = reflect(field, limit=99, log_path=_log(tmp_path))
    assert len(got_many) <= 5
    got_three = reflect(field, limit=3, log_path=_log(tmp_path))
    assert len(got_three) <= 3
    for cand in got_default:
        assert cand["confidence"] <= 0.6
        assert set(cand) == {"kind", "summary", "refs", "confidence",
                             "reason", "alternates"}
        assert cand["alternates"], "varje kandidat kräver alternativ tolkning"


def test_graph_unchanged_and_no_sidecar_writes(tmp_path):
    field = _busy_graph(tmp_path)
    stats_before = field.stats()
    rels_before = _snapshot_relations(field)
    files_before = sorted(p.name for p in tmp_path.iterdir())
    db_size_before = (tmp_path / "field.sqlite").stat().st_size

    reflect(field, log_path=_log(tmp_path))

    assert field.stats() == stats_before
    assert _snapshot_relations(field) == rels_before
    assert (tmp_path / "field.sqlite").stat().st_size == db_size_before
    files_after = sorted(p.name for p in tmp_path.iterdir())
    new_files = [n for n in files_after if n not in files_before]
    assert new_files == ["reflector_log.jsonl"], new_files


def test_forecast_row_exists_before_return(tmp_path):
    field = _busy_graph(tmp_path)
    log = _log(tmp_path)
    t0 = datetime.now(timezone.utc)
    got = reflect(field, log_path=log)
    t1 = datetime.now(timezone.utc)

    lines = _read_lines(log)
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["event"] == "forecast"
    assert row["executor"] == "agent:reflector"
    ts = datetime.fromisoformat(row["time"])
    assert t0 <= ts <= t1, "prognosraden ska tidsstämplas före return"
    assert row["input_fingerprint"]["relations"] == field.stats()["relations"]
    assert [c["probability"] for c in row["candidates"]] == [
        c["confidence"] for c in got]


def test_silence_on_empty_graph(tmp_path):
    field = _mk_field(tmp_path)
    log = _log(tmp_path)
    got = reflect(field, log_path=log)
    assert got == []
    row = json.loads(_read_lines(log)[0])
    assert row["silence"] is True
    assert row["candidates"] == []
    assert row["silence_reason"], "tystnad ska loggas med skäl"


def test_silence_on_irrelevant_single_concept(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("Ensam", domain="x")
    got = reflect(field, log_path=_log(tmp_path))
    assert got == []


def test_outcome_without_reason_rejected(tmp_path):
    log = _log(tmp_path)
    with pytest.raises(ValueError):
        record_outcome(log, "abc123", "keep", "")
    with pytest.raises(ValueError):
        record_outcome(log, "abc123", "refute", "   ")
    with pytest.raises(ValueError):
        record_outcome(log, "abc123", "maybe", "ett skäl")
    assert not log.exists(), "avvisade outcomes får inte skriva rader"


def test_outcome_appends_without_mutating_history(tmp_path):
    field = _busy_graph(tmp_path)
    log = _log(tmp_path)
    reflect(field, log_path=log)
    first_line = _read_lines(log)[0]
    entry_id = json.loads(first_line)["entry_id"]

    record_outcome(log, entry_id, "keep", "kandidaten stämde mot källan")
    lines = _read_lines(log)
    assert len(lines) == 2
    assert lines[0] == first_line, "tidigare rader får aldrig muteras"
    outcome = json.loads(lines[1])
    assert outcome == {
        "entry_id": entry_id, "time": outcome["time"], "event": "outcome",
        "executor": "agent:reflector", "verdict": "keep",
        "reason": "kandidaten stämde mot källan",
    }

    record_outcome(log, entry_id, "refute", "motsägs av ny observation")
    lines2 = _read_lines(log)
    assert len(lines2) == 3
    assert lines2[0] == first_line and lines2[1] == lines[1]
    assert json.loads(lines2[2])["verdict"] == "refute"


def test_default_log_resolves_under_nouse_home(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUSE_HOME", str(tmp_path / "home"))
    field = _busy_graph(tmp_path)
    reflect(field)  # ingen explicit log_path
    assert (tmp_path / "home" / "reflector_log.jsonl").exists()


def test_no_daemon_coupling_surface():
    import ast

    src = Path(reflector.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert '__main__' not in src, "ingen CLI/daemon-koppling tillåten"
    # Semantisk kontroll (inte substräng): förbjudna anrop/importer som
    # faktisk kod — kontraktsdocstringen får nämna dem i text.
    banned_calls = {"strengthen", "weaken", "add_relation", "add_concept",
                    "promote_relation", "confirm_relation", "supersede_relation",
                    "set_concept_domain", "consolidate_dormant_concepts"}
    banned_imports = {"threading", "asyncio", "argparse", "typer"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            assert name not in banned_calls, f"förbjudet grafskriv-anrop: {name}"
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            else:
                mods = [(node.module or "").split(".")[0]]
            for mod in mods:
                assert mod not in banned_imports, f"förbjuden import: {mod}"
