# Changelog

All notable changes to this project will be documented in this file.

## [0.4.0] - 2026-04-06

### Added
- LICENSE file (MIT full text).
- CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md.
- GitHub Actions CI (pytest on Python 3.11/3.12).
- Issue templates (bug report, feature request) and PR template.
- `examples/` directory with 4 runnable scripts (basic_query, with_openai, with_ollama, ingest_document).
- `src/nouse/tools/` module (recursive_ingest, bisociative_solver, island_bridge, seed_decomposition).
- Research section in README linking to The Larynx Problem paper (Zenodo + PhilPapers).
- Roadmap section in README.
- Comparison matrix in README (vs Mem0, MemGPT/Letta, Claude Memory).

### Changed
- README overhaul: CI badge, cleaner structure, fixed stale KuzuDB references to SQLite.
- Daemon improvements: extractor enhancements, nightrun consolidation, web server expansions.

### Removed
- `IMG/Namnlös design.png` (non-ASCII filename, renamed to design-mockup.png).
- `IMG/demo.gif` (1.4MB redundant, kept demo-en.gif at 51KB).
- `inject.py.bak` backup file.

## [0.3.1] - 2026-04-05

### Fixed
- Remaining `field.kuzu` path references updated to `field.sqlite` (cli, daemon, saas, metacognition).
- Migration script handles KuzuDB schemas without `evidence_score`/`assumption_flag` columns.
- Snapshot backup uses `copy2` instead of `copytree` (SQLite is a single file, not a directory).

## [0.3.0] - 2026-04-05

### Changed
- **BREAKING:** Replaced KuzuDB backend with SQLite WAL + NetworkX.
  - SQLite (stdlib) for persistent storage with WAL journal mode.
  - NetworkX MultiDiGraph for in-memory graph traversal (BFS, path finding, degree).
  - All raw Cypher queries replaced with public methods on FieldSurface.
  - BrainDB (kernel/db.py) also migrated from KuzuDB to SQLite.
  - `kuzu` moved to optional `[migrate]` dependency group.
  - `networkx>=3.2` added as core dependency.
- 12+ new public methods on FieldSurface for external code (no more `_conn.execute`).

### Added
- Migration script: `scripts/migrate_kuzu_to_sqlite.py` (requires `pip install nouse[migrate]`).

### Fixed
- Eliminated KuzuDB single-writer lock crashes (issue #3295 in archived KuzuDB repo).
- Concurrent CLI/daemon access now works via SQLite WAL.

## [0.2.3] - 2026-04-05

### Fixed
- Added top-level `Path` import — fixes `NameError` in `deepdive`, `nightrun`, `scan-disk`, and `doctor` commands.
- `deepdive`, `nightrun`, `enrich-nodes` now detect a running daemon and gracefully refuse instead of crashing with KuzuDB lock error.
- `deepdive --dry-run` opens the graph in read-only mode when daemon is running.

## [0.2.2] - 2026-04-05

### Added
- Complete categorized CLI front door — all ~50 commands grouped by domain (Start, Conversation, Knowledge, Exploration, Brain State, Autonomy, Identity, Integration, Configuration).
- Resonance engine, bridge finder, brain topology modules.
- Axon growth cone for field expansion.
- Graph enricher and decomposition daemon modules.
- MCP server (stdio) module.
- Web static assets for dashboard.
- Agent ingress adapter.
- LLM teacher module.
- Field event system.

### Changed
- Cognitive conductor expanded with deeper orchestration logic.
- Evidence scoring improvements in daemon.
- Initiative engine enhancements for autonomous discovery.
- Daemon main loop hardened with better error handling.
- NightRun consolidation improvements.
- Limbic signals model extended.
- TDA bridge computation improvements.
- Web server expanded with richer API surface.
- LLM autodiscover refinements.
- Inject module expanded for flexible attach modes.

## [0.2.1] - 2026-04-05

### Added
- Regression tests for attach mode selection and fallback behavior.

### Changed
- Demo GIF in README is now English-first for GitHub visitors.

### Fixed
- Verified packaging and release pipeline for PyPI publication.

## [0.2.0] - 2026-04-05

- Initial public release on PyPI.
