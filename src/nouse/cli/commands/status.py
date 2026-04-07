"""
nouse status — compact health snapshot readable from the local graph.
"""
from __future__ import annotations

import importlib.metadata as _meta
import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path.home() / ".local" / "share" / "nouse" / "field.sqlite"
_MEMORY_DIR = Path.home() / ".local" / "share" / "nouse" / "memory"
_DAEMON_URL = "http://127.0.0.1:8765/api/status"


def _version() -> str:
    try:
        return _meta.version("nouse")
    except _meta.PackageNotFoundError:
        return "?"


def graph_stats(db_path: Path | None = None) -> dict:
    """Read node/edge/gap counts directly from SQLite without loading NetworkX."""
    path = db_path or _DB_PATH
    if not path.exists():
        return {"nodes": 0, "edges": 0, "gaps": 0, "last_write": None}
    try:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.execute("PRAGMA busy_timeout=3000")
        nodes = conn.execute("SELECT count(*) FROM concept").fetchone()[0]
        edges = conn.execute("SELECT count(*) FROM relation").fetchone()[0]
        gaps = conn.execute(
            "SELECT count(*) FROM relation WHERE assumption_flag=1"
        ).fetchone()[0]
        row = conn.execute(
            "SELECT created FROM relation ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        last_write: str | None = row[0] if row else None
        if last_write is None:
            row = conn.execute(
                "SELECT created FROM concept ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            last_write = row[0] if row else None
        conn.close()
        return {"nodes": nodes, "edges": edges, "gaps": gaps, "last_write": last_write}
    except Exception:
        return {"nodes": 0, "edges": 0, "gaps": 0, "last_write": None}


def memory_counts(memory_dir: Path | None = None) -> dict:
    """Count entries across episodic, semantic, and procedural memory files."""
    base = memory_dir or _MEMORY_DIR
    episodic = 0
    semantic = 0
    procedural = 0

    ep_path = base / "episodic.jsonl"
    if ep_path.exists():
        try:
            episodic = sum(
                1
                for line in ep_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                if line.strip()
            )
        except Exception:
            pass

    sem_path = base / "semantic.json"
    if sem_path.exists():
        try:
            data = json.loads(sem_path.read_text(encoding="utf-8"))
            semantic = len(data.get("facts") or {})
        except Exception:
            pass

    proc_path = base / "procedural.json"
    if proc_path.exists():
        try:
            data = json.loads(proc_path.read_text(encoding="utf-8"))
            procedural = len(data.get("relation_type_counts") or {})
        except Exception:
            pass

    return {"episodic": episodic, "semantic": semantic, "procedural": procedural}


def _pid_uptime(pid: int) -> float | None:
    """Return process uptime in seconds for *pid*, or None if unavailable."""
    try:
        proc_stat = Path(f"/proc/{pid}/stat")
        if proc_stat.exists():
            fields = proc_stat.read_text().split()
            btime_line = next(
                (ln for ln in Path("/proc/stat").read_text().splitlines() if ln.startswith("btime")),
                None,
            )
            if btime_line:
                btime = int(btime_line.split()[1])
                hz = os.sysconf("SC_CLK_TCK")
                start_jiffies = int(fields[21])
                return time.time() - (btime + start_jiffies / hz)
    except Exception:
        pass

    try:
        out = subprocess.check_output(
            ["ps", "-o", "etime=", "-p", str(pid)],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        parts = out.replace("-", ":").split(":")
        secs = 0
        for i, part in enumerate(reversed(parts)):
            secs += int(part) * (60 ** i if i < 3 else 24 * 3600 * (i - 2))
        return float(secs)
    except Exception:
        return None


def daemon_info(daemon_url: str | None = None) -> dict:
    """Return daemon running state, PID, and uptime (seconds)."""
    url = daemon_url or _DAEMON_URL
    try:
        import httpx

        r = httpx.get(url, timeout=2.0)
        if r.status_code != 200:
            return {"running": False}
    except Exception:
        return {"running": False}

    pid: int | None = None
    try:
        raw = subprocess.check_output(
            ["lsof", "-t", str(_DB_PATH)],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        pids = [int(p) for p in raw.splitlines() if p.strip().isdigit()]
        if pids:
            pid = pids[0]
    except Exception:
        pass

    uptime_sec: float | None = None
    if pid is not None:
        uptime_sec = _pid_uptime(pid)

    return {"running": True, "pid": pid, "uptime_sec": uptime_sec}


def _format_uptime(sec: float | None) -> str:
    if sec is None:
        return "unknown"
    total = int(sec)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


def _format_last_write(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = int((datetime.now(timezone.utc) - ts).total_seconds())
        if delta < 60:
            return f"{delta} seconds ago"
        if delta < 3600:
            return f"{delta // 60} minutes ago"
        if delta < 86400:
            return f"{delta // 3600} hours ago"
        return f"{delta // 86400} days ago"
    except Exception:
        return iso


def run_status(
    *,
    db_path: Path | None = None,
    memory_dir: Path | None = None,
    daemon_url: str | None = None,
) -> None:
    """Print a compact status snapshot to stdout."""
    version = _version()
    graph = graph_stats(db_path)
    mem = memory_counts(memory_dir)
    d = daemon_info(daemon_url)

    # Session cache stats
    session_stats: dict = {}
    try:
        from nouse.session.modelsessions import session_stats as _ss
        session_stats = _ss()
    except Exception:
        pass

    gap_part = f" · {graph['gaps']} gaps detected" if graph["gaps"] else ""
    print(f"Nouse v{version}")
    print(f"Graph:         {graph['nodes']} nodes · {graph['edges']} edges{gap_part}")
    print(
        f"Memory:        episodic={mem['episodic']}"
        f" · semantic={mem['semantic']}"
        f" · procedural={mem['procedural']}"
    )

    if session_stats:
        n = session_stats.get("total_sessions", 0)
        saved = session_stats.get("tokens_saved", 0)
        saved_str = f"{saved:,}" if saved else "0"
        print(f"Sessions:      {n} cached · {saved_str} tokens saved")

    if d["running"]:
        pid_part = f"PID {d['pid']}, " if d.get("pid") else ""
        uptime_part = f"uptime {_format_uptime(d.get('uptime_sec'))}"
        print(f"Daemon:        running ({pid_part}{uptime_part})")
    else:
        print("Daemon:        not running")

    print(f"Last activity: {_format_last_write(graph['last_write'])}")
