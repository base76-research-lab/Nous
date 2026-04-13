---
title: "KuzuDB→SQLite Migration"
subtitle: "Why We Replaced a Graph Database with a Relational One"
author: "Björn Wikström"
date: "2026-04-05"
abstract: |
  This note documents the replacement of KuzuDB with SQLite WAL + NetworkX in v0.3.0. KuzuDB, a property graph database, caused frequent lock crashes under concurrent access between NightRun consolidation and interactive sessions. The migration replaced it with SQLite for persistence and NetworkX for in-memory graph topology. The result: zero lock crashes, simpler deployment, and equivalent query performance for the graph sizes Nous operates at (thousands, not millions of nodes).
---

# KuzuDB→SQLite Migration

**Why We Replaced a Graph Database with a Relational One**

Björn Wikström\
Base76 Research Lab

*5 April 2026*

---

## 1. The KuzuDB Problem

KuzuDB is a property graph database with Cypher-like query syntax — a natural choice for a concept-relation graph. In practice, it caused repeated lock crashes:

- **Concurrent access**: NightRun consolidation (writing new edges) and interactive sessions (reading concepts) would deadlock under KuzuDB's file-level locking
- **Schema rigidity**: Adding new node/edge properties required schema migration commands, blocking reads during migration
- **WAL issues**: KuzuDB's write-ahead logging was fragile on NFS and some local filesystems, producing corrupted reads after unclean shutdowns
- **Deployment complexity**: KuzuDB required a running server or in-process engine initialization on every startup

The final trigger was commit 1cf3a9e: "Fix NameError (Path) and KuzuDB lock crashes in deepdive/nightrun/enrich-nodes." The lock crashes were not occasional — they were systematic under any concurrent access pattern.

## 2. Why SQLite + NetworkX, Not Another Graph DB

Alternatives considered:

| Option | Rejected because |
|---|---|
| Neo4j | JVM dependency, overkill for <100k nodes, network overhead |
| DuckDB | Columnar store, poor fit for sparse graph traversals |
| Pure NetworkX | No persistence — graph lost on shutdown |
| Redis Graph | Server dependency, memory-only, no WAL durability |

SQLite + NetworkX was chosen because:

1. **SQLite WAL** handles concurrent readers with a single writer without locking — exactly the access pattern Nous needs (many reads during interaction, batch writes during consolidation)
2. **NetworkX** is the de facto Python graph library — all topological operations (shortest path, centrality, community detection) are native
3. **Zero external dependencies** — SQLite is in the Python standard library
4. **Schema flexibility** — adding columns to SQLite is a single `ALTER TABLE`, no graph schema migration needed

## 3. Migration Architecture

```
Before (KuzuDB):
  Concept nodes ──▶ KuzuDB graph (nodes + edges in one store)
  Queries ────────▶ Cypher query ──▶ KuzuDB engine

After (SQLite + NetworkX):
  Persistence ────▶ SQLite WAL
                    ├── concept (id, concept, evidence_score, goal_weight, ...)
                    ├── relation (src, tgt, weight, evidence_score, ...)
                    ├── concept_knowledge (concept, knowledge_json)
                    └── concept_embedding (concept, embedding_blob)

  Topology ───────▶ NetworkX DiGraph (in-memory)
                    ├── Loaded from SQLite on startup
                    ├── Used for: traversal, resonance, bisociation
                    └── Written back to SQLite on consolidation
```

The split is deliberate: SQLite owns persistence, NetworkX owns topology. They are synchronized at well-defined points — graph load on startup and edge write on consolidation — rather than trying to maintain a single unified graph store.

## 4. Performance After Migration

| Metric | KuzuDB | SQLite + NetworkX |
|---|---|---|
| Lock crashes per 10 cycles | 3–5 | 0 |
| Startup time | ~2s (engine init) | ~0.3s (SQLite open + graph load) |
| Concurrent read/write | Deadlocks | No issues (WAL) |
| Deployment | Requires KuzuDB binary | Standard library only |

At the current scale (20k concepts, 20k relations), NetworkX graph operations complete in milliseconds. The crossover point where a dedicated graph database would outperform is estimated at ~500k nodes, well beyond Nous's current and projected needs.

## 5. What We Lost and Gained

**Lost:**
- Native Cypher queries for complex graph patterns
- Automatic graph schema enforcement
- Built-in graph algorithms in the database layer

**Gained:**
- Zero lock crashes under concurrent access
- Simpler deployment (no external database)
- Flexible schema (ALTER TABLE vs. graph schema migration)
- Full Python graph algorithm library (NetworkX)
- WAL durability on unclean shutdown

The tradeoff is clear: at Nous's scale, reliability and simplicity outweigh the theoretical benefits of a dedicated graph database.

*Commit: c546041 — v0.3.0: Replace KuzuDB with SQLite WAL + NetworkX*
*Commit: c2e298d — refactor(kernel): remove KuzuDB legacy, SQLite-only storage*