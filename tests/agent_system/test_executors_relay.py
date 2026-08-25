from __future__ import annotations

import json
import subprocess
from pathlib import Path

import nouse.agent_system.executors as executors
from nouse.agent_system.executors import (
    check_relay_delegation,
    open_relay_executor,
    spawn_codex_headless,
)


class _FakeProc:
    def __init__(self, pid: int = 4242):
        self.pid = pid


def _mk_relay_dir(tmp_path: Path, monkeypatch) -> Path:
    relay_dir = tmp_path / "relay"
    monkeypatch.setenv("NOUSE_RELAY_DIR", str(relay_dir))
    return relay_dir


def test_spawn_codex_headless_reports_tool_unavailable_when_not_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(executors.shutil, "which", lambda name: None)
    result = spawn_codex_headless(goal="check X", run_dir=tmp_path)
    assert result["ok"] is False
    assert "TOOL_UNAVAILABLE" in result["error"]


def test_spawn_codex_headless_builds_read_only_sandbox_command(tmp_path, monkeypatch):
    monkeypatch.setattr(executors.shutil, "which", lambda name: "/usr/bin/codex")
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(executors.subprocess, "Popen", fake_popen)

    result = spawn_codex_headless(goal="what are we missing here?", run_dir=tmp_path)

    assert result["ok"] is True
    cmd = captured["cmd"]
    assert cmd[0] == "/usr/bin/codex"
    assert "exec" in cmd
    assert "--sandbox" in cmd and cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert "-o" in cmd

    meta = json.loads((tmp_path / "relay_delegation" / "meta.json").read_text())
    assert meta["engine"] == "codex"
    assert meta["sandbox"] == "read-only"
    assert meta["pid"] == 4242


def test_spawn_codex_headless_points_at_the_given_workspace_not_the_artifact_dir(tmp_path, monkeypatch):
    # Found and fixed 2026-08-25: without this, the delegated process's cwd
    # was run_dir/relay_delegation (just log/meta artifacts) -- the model
    # would never actually see the codebase it was asked about.
    monkeypatch.setattr(executors.shutil, "which", lambda name: "/usr/bin/codex")
    captured = {}

    def fake_popen(cmd, cwd=None, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return _FakeProc()

    monkeypatch.setattr(executors.subprocess, "Popen", fake_popen)

    real_repo = tmp_path / "the_actual_repo"
    real_repo.mkdir()

    spawn_codex_headless(goal="find the bug", run_dir=tmp_path / "runs" / "run1", workspace=real_repo)

    assert captured["cwd"] == str(real_repo)
    cmd = captured["cmd"]
    assert cmd[cmd.index("-C") + 1] == str(real_repo)


def test_open_relay_executor_dispatches_to_codex_when_requested(tmp_path, monkeypatch):
    _mk_relay_dir(tmp_path, monkeypatch)
    calls = []

    def fake_spawn_codex(*, goal, run_dir, workspace=None):
        calls.append("codex")
        return {"ok": True, "pid": 1, "log_path": str(run_dir / "codex.log")}

    def fake_spawn_claude(*, goal, run_dir, workspace=None):
        calls.append("claude")
        return {"ok": True, "pid": 2, "log_path": str(run_dir / "claude.log")}

    monkeypatch.setattr(executors, "spawn_codex_headless", fake_spawn_codex)
    monkeypatch.setattr(executors, "spawn_claude_headless", fake_spawn_claude)
    monkeypatch.setitem(executors._SPAWN_BY_ENGINE, "codex", fake_spawn_codex)
    monkeypatch.setitem(executors._SPAWN_BY_ENGINE, "claude", fake_spawn_claude)

    result = open_relay_executor(goal="second opinion please", run_dir=tmp_path, engine="codex")

    assert calls == ["codex"]
    assert result["ok"] is True


def test_open_relay_executor_defaults_to_claude_for_unknown_engine(tmp_path, monkeypatch):
    # _SPAWN_BY_ENGINE.get(engine, spawn_claude_headless)'s fallback is the
    # real function name looked up at call time, not a dict entry -- patch
    # the function itself, the same target the real fallback resolves to.
    _mk_relay_dir(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        executors, "spawn_claude_headless",
        lambda *, goal, run_dir, workspace=None: calls.append("claude") or {"ok": True, "pid": 1, "log_path": "x"},
    )

    open_relay_executor(goal="x", run_dir=tmp_path, engine="some-unrecognized-value")

    assert calls == ["claude"]


def test_check_relay_delegation_reports_no_meta_as_not_done(tmp_path):
    result = check_relay_delegation(session_id="relay_doesnotexist", run_dir=tmp_path)
    assert result["ok"] is False
    assert result["done"] is False


def test_check_relay_delegation_still_running(tmp_path, monkeypatch):
    delegation_dir = tmp_path / "relay_delegation"
    delegation_dir.mkdir()
    (delegation_dir / "meta.json").write_text(json.dumps({"pid": 99999, "engine": "codex"}))

    monkeypatch.setattr(executors.os, "kill", lambda pid, sig: None)  # no raise -> alive

    result = check_relay_delegation(session_id="relay_x", run_dir=tmp_path)
    assert result == {"ok": True, "done": False}


def test_check_relay_delegation_pulls_codex_result_and_marks_relay_ready(tmp_path, monkeypatch):
    _mk_relay_dir(tmp_path, monkeypatch)
    from nouse.session.relay import relay_get, relay_open

    relay = relay_open("investigate X", model="claude")
    session_id = relay["session_id"]

    delegation_dir = tmp_path / "relay_delegation"
    delegation_dir.mkdir()
    result_path = delegation_dir / "codex_result.txt"
    result_path.write_text("Codex's take: check the retry logic in run_eval.py")
    (delegation_dir / "meta.json").write_text(json.dumps({
        "pid": 99999, "engine": "codex", "result_path": str(result_path),
    }))

    def fake_kill(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(executors.os, "kill", fake_kill)

    outcome = check_relay_delegation(session_id=session_id, run_dir=tmp_path)

    assert outcome["done"] is True
    assert outcome["error"] is None
    assert "retry logic" in outcome["result"]

    relay_after = relay_get(session_id)
    assert relay_after["status"] == "relay_ready"
    assert "retry logic" in relay_after["summary"]


def test_check_relay_delegation_flags_claude_is_error_without_marking_relay_ready(tmp_path, monkeypatch):
    _mk_relay_dir(tmp_path, monkeypatch)
    from nouse.session.relay import relay_get, relay_open

    relay = relay_open("investigate Y", model="claude")
    session_id = relay["session_id"]

    delegation_dir = tmp_path / "relay_delegation"
    delegation_dir.mkdir()
    log_path = delegation_dir / "claude_headless.log"
    log_path.write_text(json.dumps({"result": "", "is_error": True, "subtype": "error_max_turns"}))
    (delegation_dir / "meta.json").write_text(json.dumps({
        "pid": 99999, "engine": "claude", "log_path": str(log_path),
    }))

    monkeypatch.setattr(executors.os, "kill", lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError()))

    outcome = check_relay_delegation(session_id=session_id, run_dir=tmp_path)

    assert outcome["done"] is True
    assert outcome["error"] is not None

    relay_after = relay_get(session_id)
    assert relay_after["status"] == "active"  # not relay_ready -- caller should know this failed
