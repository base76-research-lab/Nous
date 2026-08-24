#!/usr/bin/env python3
"""
nouse-watchdog — self-heal om nouse-daemon dör eller fastnar.

Två separata failure-lägen:

1. Tjänsten är helt nere (`ActiveState != active`) — startar om direkt.
2. Tjänsten lever men gör inga framsteg — `status.json`s `updated`-fält
   (samma heartbeat daemonen skriver varje cykel, se
   `daemon/main.py::_write_status`) är äldre än
   `NOUSE_WATCHDOG_STALE_THRESHOLD_SEC`. En nyss startad daemon får
   `NOUSE_WATCHDOG_STARTUP_GRACE_SEC` (default 900s, matchar
   systemd-enhetens defaultvärde) innan den första cykeln hinner skriva
   en färsk heartbeat.

En trasig watchdog som startar om en frisk daemon i onödan är värre än
ingen watchdog alls — därför: begränsat antal omstarter per tidsfönster
(`NOUSE_WATCHDOG_MAX_RESTARTS`/`NOUSE_WATCHDOG_RESTART_WINDOW_SEC`). Vid
fler upprepade omstarter än så ger scriptet upp och avslutar med
exit 2 ("restart storm") — synligt som `failed` i
`systemctl --user list-units --all`, precis den signal som avslöjade
backup/eval/watchdog-luckorna 2026-08-24 i första läget. Det är
avsiktligt: en flackande daemon SKA synas för Björn, inte tystas ner av
en watchdog som håller på att stryka undan symptomen.

State (senaste kontroll + omstartshistorik) sparas till
`watchdog_state.json` i samma datakatalog som `status.json`
(`NOUSE_HOME`, default `~/.local/share/nouse`) — inte i repot.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nouse.config.paths import nouse_home_root, path_from_env  # noqa: E402

DEFAULT_SERVICE = "nouse-daemon.service"


def _env_float(key: str, default: float) -> float:
    raw = (os.getenv(key) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    raw = (os.getenv(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = (os.getenv(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@dataclass
class Config:
    service: str = field(default_factory=lambda: os.getenv("NOUSE_WATCHDOG_SERVICE", DEFAULT_SERVICE))
    stale_threshold_sec: float = field(default_factory=lambda: _env_float("NOUSE_WATCHDOG_STALE_THRESHOLD_SEC", 600.0))
    startup_grace_sec: float = field(default_factory=lambda: _env_float("NOUSE_WATCHDOG_STARTUP_GRACE_SEC", 900.0))
    max_restarts: int = field(default_factory=lambda: _env_int("NOUSE_WATCHDOG_MAX_RESTARTS", 3))
    restart_window_sec: float = field(default_factory=lambda: _env_float("NOUSE_WATCHDOG_RESTART_WINDOW_SEC", 1800.0))
    dry_run: bool = field(default_factory=lambda: _env_bool("NOUSE_WATCHDOG_DRY_RUN", False))
    status_path: Path = field(default_factory=lambda: path_from_env("NOUSE_STATUS_FILE", "status.json"))
    state_path: Path = field(default_factory=lambda: nouse_home_root() / "watchdog_state.json")


class SystemctlError(RuntimeError):
    """systemctl gick inte att köra (saknas, permission, etc) — skiljs från 'tjänsten är nere'."""


def _run_systemctl(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemctlError(f"systemctl {' '.join(args)} misslyckades: {exc}") from exc


def service_snapshot(service: str) -> dict:
    """ActiveState/SubState/starttid (monotont, boot-relativt) för tjänsten.

    Kastar SystemctlError om systemctl inte går att köra.
    `ActiveEnterTimestampMonotonic` (mikrosekunder sen boot) används
    istället för `ActiveEnterTimestamp` (lokal väggklocka) — undviker
    tidszonsparsning helt och är robust mot att klockan justeras under
    körning.
    """
    proc = _run_systemctl(
        "show", service,
        "-p", "ActiveState",
        "-p", "SubState",
        "-p", "ActiveEnterTimestampMonotonic",
    )
    out = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k] = v
    return out


def _boot_uptime_sec() -> float | None:
    """Sekunder sen boot, från /proc/uptime — samma klockdomän som systemds monotona tidsstämplar."""
    try:
        with open("/proc/uptime", encoding="utf-8") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _service_uptime_sec(snap: dict) -> float | None:
    raw = (snap.get("ActiveEnterTimestampMonotonic") or "").strip()
    boot_uptime = _boot_uptime_sec()
    if not raw or raw == "0" or boot_uptime is None:
        return None
    try:
        active_since_boot_sec = int(raw) / 1_000_000.0
    except ValueError:
        return None
    return max(0.0, boot_uptime - active_since_boot_sec)


def _read_status(status_path: Path) -> tuple[datetime | None, dict]:
    if not status_path.exists():
        return None, {}
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, {}
    raw = str(data.get("updated") or "")
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None, data
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts, data


def _load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {"restart_history": []}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"restart_history": []}
    data.setdefault("restart_history", [])
    return data


def _save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _prune_history(history: list[str], now: datetime, window_sec: float) -> list[str]:
    cutoff = now - timedelta(seconds=window_sec)
    kept = []
    for raw in history:
        try:
            ts = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if ts >= cutoff:
            kept.append(raw)
    return kept


def check(cfg: Config, now: datetime | None = None) -> int:
    """Returnerar exit-kod: 0 frisk/självläkt, 1 scriptfel, 2 restart-storm (kräver människa)."""
    # Lokal väggklocka, inte UTC — matchar `_write_status()`s `datetime.now().isoformat()`
    # i daemon/main.py. En UTC/lokal-mismatch här skulle ge en konstant skev
    # "staleness" (t.ex. +2h i CEST) och antingen dölja en verkligt fastnad
    # daemon eller trigga onödiga omstarter.
    now = now or datetime.now()

    try:
        snap = service_snapshot(cfg.service)
    except SystemctlError as exc:
        print(f"[watchdog] KRITISKT: kan inte fråga systemctl: {exc}", file=sys.stderr)
        return 1

    active_state = snap.get("ActiveState", "unknown")
    reason: str | None = None

    if active_state != "active":
        reason = f"tjänsten är '{active_state}' (förväntat 'active')"
    else:
        uptime_sec = _service_uptime_sec(snap)

        if uptime_sec is not None and uptime_sec < cfg.startup_grace_sec:
            print(
                f"[watchdog] OK — inom startup-grace ({uptime_sec:.0f}s < "
                f"{cfg.startup_grace_sec:.0f}s), hoppar över heartbeat-check."
            )
            return 0

        updated_at, status_data = _read_status(cfg.status_path)
        if updated_at is None:
            reason = f"kunde inte läsa/tolka heartbeat ({cfg.status_path})"
        else:
            staleness = (now - updated_at).total_seconds()
            if staleness > cfg.stale_threshold_sec:
                reason = (
                    f"heartbeat inaktuell: {staleness:.0f}s sen senaste cykel "
                    f"(cycle={status_data.get('cycle', '?')}), tröskel {cfg.stale_threshold_sec:.0f}s"
                )
            else:
                print(f"[watchdog] OK — heartbeat {staleness:.0f}s gammal, tröskel {cfg.stale_threshold_sec:.0f}s.")

    if reason is None:
        return 0

    print(f"[watchdog] {cfg.service} behöver självläkning: {reason}")

    state = _load_state(cfg.state_path)
    history = _prune_history(state.get("restart_history", []), now, cfg.restart_window_sec)

    if len(history) >= cfg.max_restarts:
        state["restart_history"] = history
        state["last_check"] = now.isoformat()
        state["last_reason"] = reason
        state["last_action"] = "suppressed_restart_storm"
        _save_state(cfg.state_path, state)
        print(
            f"[watchdog] KRITISKT: {len(history)} omstarter senaste "
            f"{cfg.restart_window_sec:.0f}s (max {cfg.max_restarts}) — ger upp, "
            "kräver mänsklig granskning. Ingen ytterligare omstart görs."
        )
        return 2

    if cfg.dry_run:
        print(f"[watchdog] DRY-RUN — skulle ha kört: systemctl --user restart {cfg.service}")
        state["last_action"] = "dry_run_would_restart"
    else:
        try:
            proc = _run_systemctl("restart", cfg.service)
        except SystemctlError as exc:
            print(f"[watchdog] KRITISKT: omstart misslyckades att köra: {exc}", file=sys.stderr)
            return 1
        if proc.returncode != 0:
            print(f"[watchdog] KRITISKT: 'systemctl restart {cfg.service}' gav kod {proc.returncode}: {proc.stderr.strip()}", file=sys.stderr)
            return 1
        history.append(now.isoformat())
        state["last_action"] = "restarted"
        print(f"[watchdog] Omstartad. {len(history)}/{cfg.max_restarts} omstarter i fönstret ({cfg.restart_window_sec:.0f}s).")

    state["restart_history"] = history
    state["last_check"] = now.isoformat()
    state["last_reason"] = reason
    _save_state(cfg.state_path, state)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Logga vad som skulle göras utan att faktiskt starta om tjänsten.")
    args = parser.parse_args()

    cfg = Config()
    if args.dry_run:
        cfg.dry_run = True

    return check(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
