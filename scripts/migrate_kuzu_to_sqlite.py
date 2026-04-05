#!/usr/bin/env python3
"""
migrate_kuzu_to_sqlite.py — Migrate FieldSurface data from KuzuDB to SQLite WAL.

Usage:
    python scripts/migrate_kuzu_to_sqlite.py [--kuzu-path PATH] [--sqlite-path PATH] [--dry-run]

Requires: pip install nouse[migrate]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

try:
    import kuzu
except ImportError:
    print("ERROR: kuzu not installed. Run: pip install nouse[migrate]")
    sys.exit(1)

DEFAULT_KUZU_PATH = Path.home() / ".local" / "share" / "nouse" / "field.kuzu"
DEFAULT_SQLITE_PATH = Path.home() / ".local" / "share" / "nouse" / "field.sqlite"


def migrate(kuzu_path: Path, sqlite_path: Path, *, dry_run: bool = False) -> dict:
    if not kuzu_path.exists():
        print(f"KuzuDB path does not exist: {kuzu_path}")
        sys.exit(1)

    print(f"Source: {kuzu_path}")
    print(f"Target: {sqlite_path}")

    # Open KuzuDB read-only
    db = kuzu.Database(str(kuzu_path), read_only=True)
    conn = kuzu.Connection(db)

    stats = {"concepts": 0, "relations": 0, "knowledge": 0, "embeddings": 0}

    # Read all concepts
    try:
        df = conn.execute("MATCH (c:Concept) RETURN c.name, c.domain, c.granularity, c.source, c.created").get_as_df()
        concepts = df.to_dict("records")
        stats["concepts"] = len(concepts)
    except Exception as e:
        print(f"Warning: Could not read concepts: {e}")
        concepts = []

    # Read all relations — try full schema first, fall back to basic
    try:
        df = conn.execute(
            "MATCH (a:Concept)-[r:Relation]->(b:Concept) "
            "RETURN a.name AS src, b.name AS tgt, r.type, r.why, r.strength, "
            "r.created, r.evidence_score, r.assumption_flag"
        ).get_as_df()
        relations = df.to_dict("records")
        stats["relations"] = len(relations)
    except Exception:
        try:
            df = conn.execute(
                "MATCH (a:Concept)-[r:Relation]->(b:Concept) "
                "RETURN a.name AS src, b.name AS tgt, r.type, r.why, r.strength, r.created"
            ).get_as_df()
            relations = df.to_dict("records")
            stats["relations"] = len(relations)
            print("  (Using basic schema — evidence_score/assumption_flag not in source)")
        except Exception as e:
            print(f"Warning: Could not read relations: {e}")
            relations = []

    # Read concept_knowledge
    knowledge = []
    try:
        df = conn.execute(
            "MATCH (ck:ConceptKnowledge) RETURN ck.name, ck.summary, ck.claims_json, "
            "ck.evidence_json, ck.related_json, ck.uncertainty, ck.revision_count, ck.updated"
        ).get_as_df()
        knowledge = df.to_dict("records")
        stats["knowledge"] = len(knowledge)
    except Exception:
        pass

    # Read concept_embedding
    embeddings = []
    try:
        df = conn.execute(
            "MATCH (ce:ConceptEmbedding) RETURN ce.name, ce.vector_json, ce.model, ce.dims, ce.updated"
        ).get_as_df()
        embeddings = df.to_dict("records")
        stats["embeddings"] = len(embeddings)
    except Exception:
        pass

    print(f"\nRead from KuzuDB:")
    print(f"  Concepts:   {stats['concepts']}")
    print(f"  Relations:  {stats['relations']}")
    print(f"  Knowledge:  {stats['knowledge']}")
    print(f"  Embeddings: {stats['embeddings']}")

    if dry_run:
        print("\n--dry-run: No data written.")
        return stats

    # Write to SQLite
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    if sqlite_path.exists():
        backup = sqlite_path.with_suffix(f".bak-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}")
        sqlite_path.rename(backup)
        print(f"\nExisting SQLite backed up to: {backup}")

    sql = sqlite3.connect(str(sqlite_path))
    sql.execute("PRAGMA journal_mode=WAL")
    sql.execute("PRAGMA foreign_keys=ON")
    sql.executescript("""
        CREATE TABLE IF NOT EXISTS concept (
            name TEXT PRIMARY KEY, domain TEXT, granularity INTEGER DEFAULT 1,
            source TEXT, created TEXT
        );
        CREATE TABLE IF NOT EXISTS relation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src TEXT NOT NULL, tgt TEXT NOT NULL, type TEXT, why TEXT,
            strength REAL DEFAULT 1.0, created TEXT,
            evidence_score REAL, assumption_flag INTEGER DEFAULT 0,
            FOREIGN KEY (src) REFERENCES concept(name),
            FOREIGN KEY (tgt) REFERENCES concept(name)
        );
        CREATE INDEX IF NOT EXISTS idx_relation_src ON relation(src);
        CREATE INDEX IF NOT EXISTS idx_relation_tgt ON relation(tgt);
        CREATE INDEX IF NOT EXISTS idx_relation_strength ON relation(strength);
        CREATE TABLE IF NOT EXISTS concept_knowledge (
            name TEXT PRIMARY KEY, summary TEXT, claims_json TEXT,
            evidence_json TEXT, related_json TEXT, uncertainty REAL,
            revision_count INTEGER DEFAULT 0, updated TEXT
        );
        CREATE TABLE IF NOT EXISTS concept_embedding (
            name TEXT PRIMARY KEY, vector_json TEXT, model TEXT,
            dims INTEGER, updated TEXT
        );
    """)

    # Insert concepts
    for c in concepts:
        sql.execute(
            "INSERT OR IGNORE INTO concept (name, domain, granularity, source, created) VALUES (?, ?, ?, ?, ?)",
            (c.get("c.name"), c.get("c.domain"), c.get("c.granularity", 1),
             c.get("c.source"), c.get("c.created")))

    # Insert relations
    for r in relations:
        af = r.get("r.assumption_flag")
        sql.execute(
            "INSERT INTO relation (src, tgt, type, why, strength, created, evidence_score, assumption_flag) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (r.get("src"), r.get("tgt"), r.get("r.type"), r.get("r.why"),
             r.get("r.strength", 1.0), r.get("r.created"),
             r.get("r.evidence_score"), int(af) if af is not None else 0))

    # Insert knowledge
    for k in knowledge:
        sql.execute(
            "INSERT OR REPLACE INTO concept_knowledge "
            "(name, summary, claims_json, evidence_json, related_json, uncertainty, revision_count, updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (k.get("ck.name"), k.get("ck.summary"), k.get("ck.claims_json"),
             k.get("ck.evidence_json"), k.get("ck.related_json"),
             k.get("ck.uncertainty"), k.get("ck.revision_count", 0), k.get("ck.updated")))

    # Insert embeddings
    for e in embeddings:
        sql.execute(
            "INSERT OR REPLACE INTO concept_embedding (name, vector_json, model, dims, updated) "
            "VALUES (?, ?, ?, ?, ?)",
            (e.get("ce.name"), e.get("ce.vector_json"), e.get("ce.model"),
             e.get("ce.dims"), e.get("ce.updated")))

    sql.commit()
    sql.close()

    print(f"\nMigration complete! SQLite database: {sqlite_path}")
    print(f"  Concepts:   {stats['concepts']}")
    print(f"  Relations:  {stats['relations']}")
    print(f"  Knowledge:  {stats['knowledge']}")
    print(f"  Embeddings: {stats['embeddings']}")
    return stats


def main():
    parser = argparse.ArgumentParser(description="Migrate NoUse FieldSurface from KuzuDB to SQLite")
    parser.add_argument("--kuzu-path", type=Path, default=DEFAULT_KUZU_PATH)
    parser.add_argument("--sqlite-path", type=Path, default=DEFAULT_SQLITE_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    migrate(args.kuzu_path, args.sqlite_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
