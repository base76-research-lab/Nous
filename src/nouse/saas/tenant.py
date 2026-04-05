"""
nouse.saas.tenant — Per-tenant DB-sökvägar.
"""
from __future__ import annotations

import os
from pathlib import Path

TENANTS_ROOT = Path(os.getenv("NOUSE_TENANTS_ROOT", str(Path.home() / ".local/share/nouse/tenants")))


def db_path_for(tenant_id: str) -> Path:
    """Returnerar SQLite/KuzuDB-sökväg för given tenant."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in tenant_id)
    path = TENANTS_ROOT / safe / "field.kuzu"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
