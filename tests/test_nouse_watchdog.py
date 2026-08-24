"""Tester för scripts/nouse_watchdog.py — inte en del av `nouse`-paketet,
laddas via importlib från filväg."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "nouse_watchdog.py"
_spec = importlib.util.spec_from_file_location("nouse_watchdog", _SCRIPT_PATH)
wd = importlib.util.module_from_spec(_spec)
sys.modules["nouse_watchdog"] = wd
_spec.loader.exec_module(wd)


_BOOT_UPTIME_SEC = 100_000.0  # fejkad /proc/uptime-utläsning, konstant över en testkörning


@pytest.fixture(autouse=True)
def _fixed_boot_uptime(monkeypatch):
    monkeypatch.setattr(wd, "_boot_uptime_sec", lambda: _BOOT_UPTIME_SEC)


def _cfg(tmp_path: Path, **overrides) -> "wd.Config":
    cfg = wd.Config(
        status_path=tmp_path / "status.json",
        state_path=tmp_path / "watchdog_state.json",
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _write_status(path: Path, updated: datetime, cycle: int = 1) -> None:
    path.write_text(json.dumps({"updated": updated.isoformat(), "cycle": cycle}), encoding="utf-8")


def _fake_run_active(now: datetime, started_ago_sec: float = 3600.0):
    """`now` ignoreras för uptime-beräkningen (den sker via monoton /proc/uptime-klocka,
    inte väggklocka) men behålls i signaturen för att testerna ska läsa naturligt."""
    active_since_boot_usec = int((_BOOT_UPTIME_SEC - started_ago_sec) * 1_000_000)

    def _fake(cmd, **kwargs):
        assert cmd[:2] == ["systemctl", "--user"]
        out = (
            f"ActiveState=active\nSubState=running\n"
            f"ActiveEnterTimestampMonotonic={active_since_boot_usec}\n"
        )
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
    return _fake


def test_healthy_daemon_fresh_heartbeat_no_action(tmp_path, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, 0)
    cfg = _cfg(tmp_path)
    _write_status(cfg.status_path, now - timedelta(seconds=30))
    monkeypatch.setattr(wd, "_run_systemctl", lambda *a: _fake_run_active(now)(["systemctl", "--user", *a]))

    assert wd.check(cfg, now=now) == 0
    assert not cfg.state_path.exists()


def test_within_startup_grace_skips_stale_check(tmp_path, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, 0)
    cfg = _cfg(tmp_path, startup_grace_sec=900.0)
    # Ingen status.json alls än — ska inte spela roll inom grace.
    monkeypatch.setattr(wd, "_run_systemctl", lambda *a: _fake_run_active(now, started_ago_sec=60.0)(["systemctl", "--user", *a]))

    assert wd.check(cfg, now=now) == 0
    assert not cfg.state_path.exists()


def test_stale_heartbeat_triggers_restart(tmp_path, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, 0)
    cfg = _cfg(tmp_path, stale_threshold_sec=600.0, startup_grace_sec=900.0)
    _write_status(cfg.status_path, now - timedelta(seconds=900))  # äldre än tröskeln

    calls = []

    def fake_run(*args):
        calls.append(args)
        if args[0] == "show":
            return _fake_run_active(now, started_ago_sec=3600.0)(["systemctl", "--user", *args])
        assert args[0] == "restart"
        return subprocess.CompletedProcess(["systemctl", "--user", *args], 0, stdout="", stderr="")

    monkeypatch.setattr(wd, "_run_systemctl", fake_run)

    assert wd.check(cfg, now=now) == 0
    assert ("restart", cfg.service) in calls
    state = json.loads(cfg.state_path.read_text())
    assert state["last_action"] == "restarted"
    assert len(state["restart_history"]) == 1


def test_inactive_service_triggers_restart_regardless_of_heartbeat(tmp_path, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, 0)
    cfg = _cfg(tmp_path)
    _write_status(cfg.status_path, now)  # fräsch — ska inte spara den

    def fake_run(*args):
        if args[0] == "show":
            return subprocess.CompletedProcess(["x"], 0, stdout="ActiveState=failed\nSubState=failed\nActiveEnterTimestamp=\n", stderr="")
        assert args[0] == "restart"
        return subprocess.CompletedProcess(["x"], 0, stdout="", stderr="")

    monkeypatch.setattr(wd, "_run_systemctl", fake_run)

    assert wd.check(cfg, now=now) == 0
    state = json.loads(cfg.state_path.read_text())
    assert "inte 'active'" in state["last_reason"] or "är 'failed'" in state["last_reason"]


def test_dry_run_does_not_call_restart(tmp_path, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, 0)
    cfg = _cfg(tmp_path, stale_threshold_sec=600.0, startup_grace_sec=900.0, dry_run=True)
    _write_status(cfg.status_path, now - timedelta(seconds=900))

    def fake_run(*args):
        assert args[0] != "restart", "dry-run ska aldrig anropa restart"
        return _fake_run_active(now, started_ago_sec=3600.0)(["systemctl", "--user", *args])

    monkeypatch.setattr(wd, "_run_systemctl", fake_run)

    assert wd.check(cfg, now=now) == 0
    state = json.loads(cfg.state_path.read_text())
    assert state["last_action"] == "dry_run_would_restart"
    assert state["restart_history"] == []


def test_restart_storm_suppressed_after_max(tmp_path, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, 0)
    cfg = _cfg(tmp_path, stale_threshold_sec=600.0, startup_grace_sec=900.0, max_restarts=2, restart_window_sec=1800.0)
    _write_status(cfg.status_path, now - timedelta(seconds=900))
    # Förfyll state med två omstarter redan inom fönstret.
    cfg.state_path.write_text(json.dumps({
        "restart_history": [
            (now - timedelta(seconds=600)).isoformat(),
            (now - timedelta(seconds=300)).isoformat(),
        ]
    }), encoding="utf-8")

    restart_calls = []

    def fake_run(*args):
        if args[0] == "show":
            return _fake_run_active(now, started_ago_sec=3600.0)(["systemctl", "--user", *args])
        restart_calls.append(args)
        return subprocess.CompletedProcess(["x"], 0, stdout="", stderr="")

    monkeypatch.setattr(wd, "_run_systemctl", fake_run)

    assert wd.check(cfg, now=now) == 2
    assert restart_calls == []
    state = json.loads(cfg.state_path.read_text())
    assert state["last_action"] == "suppressed_restart_storm"


def test_old_restarts_outside_window_are_pruned(tmp_path, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, 0)
    cfg = _cfg(tmp_path, stale_threshold_sec=600.0, startup_grace_sec=900.0, max_restarts=2, restart_window_sec=1800.0)
    _write_status(cfg.status_path, now - timedelta(seconds=900))
    # Två gamla omstarter, långt utanför 1800s-fönstret — ska inte räknas.
    cfg.state_path.write_text(json.dumps({
        "restart_history": [
            (now - timedelta(seconds=7200)).isoformat(),
            (now - timedelta(seconds=5000)).isoformat(),
        ]
    }), encoding="utf-8")

    def fake_run(*args):
        if args[0] == "show":
            return _fake_run_active(now, started_ago_sec=3600.0)(["systemctl", "--user", *args])
        return subprocess.CompletedProcess(["x"], 0, stdout="", stderr="")

    monkeypatch.setattr(wd, "_run_systemctl", fake_run)

    assert wd.check(cfg, now=now) == 0
    state = json.loads(cfg.state_path.read_text())
    assert state["last_action"] == "restarted"
    assert len(state["restart_history"]) == 1


def test_systemctl_unavailable_returns_script_error(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)

    def raise_err(*args):
        raise wd.SystemctlError("systemctl saknas")

    monkeypatch.setattr(wd, "_run_systemctl", raise_err)

    assert wd.check(cfg, now=datetime(2026, 8, 24, 12, 0, 0)) == 1


def test_missing_heartbeat_after_grace_triggers_restart(tmp_path, monkeypatch):
    now = datetime(2026, 8, 24, 12, 0, 0)
    cfg = _cfg(tmp_path, startup_grace_sec=900.0)
    # Ingen status.json skriven alls, och tjänsten har levt långt förbi grace.

    def fake_run(*args):
        if args[0] == "show":
            return _fake_run_active(now, started_ago_sec=3600.0)(["systemctl", "--user", *args])
        return subprocess.CompletedProcess(["x"], 0, stdout="", stderr="")

    monkeypatch.setattr(wd, "_run_systemctl", fake_run)

    assert wd.check(cfg, now=now) == 0
    state = json.loads(cfg.state_path.read_text())
    assert "heartbeat" in state["last_reason"]
