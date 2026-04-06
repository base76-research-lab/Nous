from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from nouse.cli.commands import status as status_mod
from nouse.cli.main import app

runner = CliRunner()


# ── graph_stats ──────────────────────────────────────────────────────────────

def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "field.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE concept (
            name TEXT PRIMARY KEY,
            domain TEXT,
            granularity INTEGER DEFAULT 1,
            source TEXT,
            created TEXT
        );
        CREATE TABLE relation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src TEXT,
            tgt TEXT,
            type TEXT,
            why TEXT,
            strength REAL DEFAULT 1.0,
            created TEXT,
            evidence_score REAL,
            assumption_flag INTEGER DEFAULT 0
        );
    """)
    conn.execute(
        "INSERT INTO concept VALUES (?,?,?,?,?)",
        ("alpha", "science", 1, "test", "2024-01-01T00:00:00"),
    )
    conn.execute(
        "INSERT INTO concept VALUES (?,?,?,?,?)",
        ("beta", "science", 1, "test", "2024-01-02T00:00:00"),
    )
    conn.execute(
        "INSERT INTO relation VALUES (NULL,?,?,?,?,?,?,?,?)",
        ("alpha", "beta", "causes", "reason", 1.0, "2024-01-03T00:00:00", 0.8, 0),
    )
    conn.execute(
        "INSERT INTO relation VALUES (NULL,?,?,?,?,?,?,?,?)",
        ("alpha", "beta", "maybe", "", 0.4, "2024-01-04T00:00:00", 0.2, 1),
    )
    conn.commit()
    conn.close()
    return db


def test_graph_stats_counts(tmp_path):
    db = _make_db(tmp_path)
    stats = status_mod.graph_stats(db)
    assert stats["nodes"] == 2
    assert stats["edges"] == 2
    assert stats["gaps"] == 1
    assert stats["last_write"] == "2024-01-04T00:00:00"


def test_graph_stats_missing_db(tmp_path):
    stats = status_mod.graph_stats(tmp_path / "nonexistent.sqlite")
    assert stats == {"nodes": 0, "edges": 0, "gaps": 0, "last_write": None}


# ── memory_counts ────────────────────────────────────────────────────────────

def _make_memory_dir(tmp_path: Path) -> Path:
    mem = tmp_path / "memory"
    mem.mkdir()
    # episodic: 3 lines
    (mem / "episodic.jsonl").write_text(
        json.dumps({"id": "ep_1"}) + "\n"
        + json.dumps({"id": "ep_2"}) + "\n"
        + json.dumps({"id": "ep_3"}) + "\n",
        encoding="utf-8",
    )
    # semantic: 2 facts
    (mem / "semantic.json").write_text(
        json.dumps({"facts": {"a|b|c": {}, "x|y|z": {}}}),
        encoding="utf-8",
    )
    # procedural: 4 relation types
    (mem / "procedural.json").write_text(
        json.dumps({"relation_type_counts": {"causes": 1, "inhibits": 2, "enables": 3, "modulates": 1}}),
        encoding="utf-8",
    )
    return mem


def test_memory_counts(tmp_path):
    mem = _make_memory_dir(tmp_path)
    counts = status_mod.memory_counts(mem)
    assert counts["episodic"] == 3
    assert counts["semantic"] == 2
    assert counts["procedural"] == 4


def test_memory_counts_empty_dir(tmp_path):
    counts = status_mod.memory_counts(tmp_path / "empty")
    assert counts == {"episodic": 0, "semantic": 0, "procedural": 0}


# ── daemon_info ───────────────────────────────────────────────────────────────

def test_daemon_info_not_running():
    with patch("httpx.get", side_effect=Exception("refused")):
        info = status_mod.daemon_info("http://127.0.0.1:9999/api/status")
    assert info == {"running": False}


def test_daemon_info_running_no_pid(tmp_path):
    import httpx
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("httpx.get", return_value=mock_resp):
        with patch("subprocess.check_output", side_effect=Exception("lsof unavailable")):
            info = status_mod.daemon_info("http://127.0.0.1:8765/api/status")

    assert info["running"] is True
    assert info["pid"] is None


# ── format helpers ────────────────────────────────────────────────────────────

def test_format_uptime_hours():
    assert status_mod._format_uptime(3 * 3600 + 22 * 60) == "3h 22m"


def test_format_uptime_minutes():
    assert status_mod._format_uptime(5 * 60 + 30) == "5m 30s"


def test_format_uptime_none():
    assert status_mod._format_uptime(None) == "unknown"


def test_format_last_write_never():
    assert status_mod._format_last_write(None) == "never"


def test_format_last_write_recent():
    from datetime import datetime, timezone, timedelta

    ts = (datetime.now(timezone.utc) - timedelta(minutes=4)).isoformat()
    result = status_mod._format_last_write(ts)
    assert "minutes ago" in result or "seconds ago" in result


# ── CLI integration ───────────────────────────────────────────────────────────

def test_status_command_no_db_no_daemon(tmp_path):
    with patch.object(status_mod, "_DB_PATH", tmp_path / "field.sqlite"):
        with patch.object(status_mod, "_MEMORY_DIR", tmp_path / "memory"):
            with patch("httpx.get", side_effect=Exception("refused")):
                result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Nouse v" in result.output
    assert "Graph:" in result.output
    assert "Memory:" in result.output
    assert "Daemon:        not running" in result.output
    assert "Last activity:" in result.output


def test_status_command_with_data(tmp_path):
    db = _make_db(tmp_path)
    mem = _make_memory_dir(tmp_path)

    with patch.object(status_mod, "_DB_PATH", db):
        with patch.object(status_mod, "_MEMORY_DIR", mem):
            with patch("httpx.get", side_effect=Exception("refused")):
                result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "2 nodes" in result.output
    assert "2 edges" in result.output
    assert "1 gaps detected" in result.output
    assert "episodic=3" in result.output
    assert "semantic=2" in result.output
    assert "procedural=4" in result.output
    assert "Daemon:        not running" in result.output
