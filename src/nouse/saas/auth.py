"""
nouse.saas.auth — API-nyckelvalidering mot SQLite admin-DB.

Schema:
    CREATE TABLE api_keys (
        key_hash  TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        label     TEXT NOT NULL DEFAULT '',
        active    INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_ADMIN_DB = Path(os.getenv("NOUSE_ADMIN_DB", str(Path.home() / ".local/share/nouse/saas-admin.db")))
_KEY_PREFIX = "nsk-"


def _conn() -> sqlite3.Connection:
    _ADMIN_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_ADMIN_DB))
    con.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            key_hash   TEXT PRIMARY KEY,
            tenant_id  TEXT NOT NULL,
            label      TEXT NOT NULL DEFAULT '',
            active     INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)
    con.commit()
    return con


def _hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def validate_key(raw_key: str) -> str | None:
    """Returnerar tenant_id om nyckeln är giltig, annars None."""
    if not raw_key.startswith(_KEY_PREFIX):
        return None
    h = _hash(raw_key)
    with _conn() as con:
        row = con.execute(
            "SELECT tenant_id FROM api_keys WHERE key_hash = ? AND active = 1", (h,)
        ).fetchone()
    return row[0] if row else None


def create_key(tenant_id: str, label: str = "") -> str:
    """Skapar en ny API-nyckel och returnerar den i klartext (visas bara en gång)."""
    raw_key = _KEY_PREFIX + secrets.token_urlsafe(32)
    h = _hash(raw_key)
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            "INSERT INTO api_keys (key_hash, tenant_id, label, active, created_at) VALUES (?,?,?,1,?)",
            (h, tenant_id, label, now),
        )
        con.commit()
    return raw_key


def list_keys(tenant_id: str | None = None) -> list[dict]:
    """Listar nycklar (utan klartext-värde). Filtrerar på tenant_id om angivet."""
    with _conn() as con:
        if tenant_id:
            rows = con.execute(
                "SELECT key_hash, tenant_id, label, active, created_at FROM api_keys WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT key_hash, tenant_id, label, active, created_at FROM api_keys"
            ).fetchall()
    return [
        {"key_hash": r[0][:12] + "...", "tenant_id": r[1],
         "label": r[2], "active": bool(r[3]), "created_at": r[4]}
        for r in rows
    ]


def revoke_key(raw_key: str) -> bool:
    """Inaktiverar en nyckel. Returnerar True om den hittades."""
    h = _hash(raw_key)
    with _conn() as con:
        cur = con.execute("UPDATE api_keys SET active = 0 WHERE key_hash = ?", (h,))
        con.commit()
    return cur.rowcount > 0
