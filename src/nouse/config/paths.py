from __future__ import annotations

import os
from pathlib import Path


def nouse_home_root() -> Path:
    raw = str(os.getenv("NOUSE_HOME", "")).strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".local" / "share" / "nouse"


def path_from_env(env_key: str, default_relative: str) -> Path:
    raw = str(os.getenv(env_key, "")).strip()
    if raw:
        return Path(raw).expanduser()
    return nouse_home_root() / default_relative

