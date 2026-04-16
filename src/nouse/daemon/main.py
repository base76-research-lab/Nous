"""
Brain Loop — hjärtslagsstakten
==============================
1. Lyssnar på alla källor (diskar, konversationer, Antigravity)
2. Extraherar relationer via LLM (LLM = Broca's area)
3. Uppdaterar grafen (med fillock mot race conditions)
4. Hittar nervbanor (BFS multi-hop) + bisociationskandidater (TDA)
5. Kör Limbic Layer (dopamin/noradrenalin/acetylkolin → λ)
6. Skriver discoveries till Self-lagret
7. Kör periodisk compaction (plastisk glömska, styrd av noradrenalin)

Kör: python -m nouse.daemon.main
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from nouse.config.paths import path_from_env
from nouse.field.surface import FieldSurface
from nouse.daemon.extractor import (
    extract_relations_with_diagnostics,
    synthesize_bridges,
)
from nouse.daemon.sources import (
    FileSource, ConversationSource,
    BashHistorySource, ChromeBookmarksSource, ChromeHistorySource,
    CaptureQueueSource,
)
from nouse.daemon.write_queue import enqueue_write, start_worker, stop_worker
from nouse.self_layer.writer import write_discovery
from nouse.self_layer import ensure_living_core, update_living_core
from nouse.orchestrator.compaction import should_run, run_compaction, WEAK_THRESHOLD
from nouse.orchestrator.conductor import AutonomyLoop, CognitiveConductor
from nouse.limbic.signals import (
    load_state, run_limbic_cycle, LimbicState
)
from nouse.learning_coordinator import LearningCoordinator
from nouse.brian2_bridge import Brian2Bridge
from nouse.daemon.node_inbox import get_inbox
from nouse.daemon.nightrun import NightRunScheduler
from nouse.daemon.initiative import run_curiosity_burst
from nouse.daemon.percolation import (
    PercolationReport,
    bridge_bisociation_search,
    domain_density_report,
    generate_ingestion_tasks,
    identify_bridge_domains,
    format_report as format_percolation_report,
    sweet_spot_report,
    format_sweet_spot_report,
)
from nouse.daemon.brain_atlas import (
    region_report as atlas_region_report,
    format_region_report as format_atlas_report,
    classify_domain,
)
from nouse.daemon.camera import CameraWatcher
from nouse.daemon.speech import SpeechListener, SpeechSpeaker
from nouse.daemon.morning_report import generate_morning_report
from nouse.daemon.research_queue import (
    approve_task_after_hitl,
    claim_next_task,
    complete_task,
    enqueue_gap_tasks,
    fail_task,
    peek_tasks,
    pause_task_for_hitl,
    queue_stats,
)
from nouse.daemon.hitl import (
    approve_interrupt,
    create_interrupt,
    critical_task_reason,
    low_risk_auto_approve_reason,
    pending_interrupt_for_task,
)
from nouse.daemon.journal import write_cycle_trace, write_daily_brief, latest_journal_file
from nouse.daemon.mission import (
    append_cycle_metric,
    build_seed_tasks,
    load_mission,
    mission_summary,
)
from nouse.daemon.evidence import assess_relation, format_why_with_evidence
from nouse.metacognition.snapshot import create_snapshot
from nouse.plugins.loader import load_plugins
from nouse.memory.store import MemoryStore
from nouse.daemon.system_events import (
    bind_wake_event,
    consume_wake_reasons,
    drain_system_event_entries,
    system_event_stats,
)
from nouse.session import session_stats as get_session_stats
from nouse.brain_sync.transporter import (
    BrainTransporter,
    bisociation_event,
    analogy_event,
    metacognition_event,
    concept_crystallize_event,
    limbic_spike_event,
)

# ── brain_sync configuration ────────────────────────────────────────────────
_BOOL_TRUE = {"1", "true", "yes", "on"}
BRAIN_SYNC_ENABLED = str(os.getenv("NOUSE_BRAIN_SYNC_ENABLED", "0")).strip().lower() in _BOOL_TRUE
BRAIN_TRANSPORTER: BrainTransporter | None = None

log = logging.getLogger("nouse.brain")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(message)s")

# Uppdatera existerande _BOOL_TRUE
# _BOOL_TRUE = {"1", "true", "yes", "on"}  # (uppdaterad)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REPO_SRC = _REPO_ROOT / "src"

DEFAULT_WATCH_PATHS = [
    # ── Systemets egen kodbas (själv-observation) ──────────────────────────
    _REPO_SRC,
    # ── Home-disk (primär bas) ─────────────────────────────────────────────
    Path.home() / "Dokument",
    Path.home() / "Skrivbord",
    Path.home() / "Skrivbord" / "Ai_ideas" / "the_brain",
    Path.home() / "Skrivbord" / "Ai_ideas" / "bjorns_papers",
    # ── Konversationer ─────────────────────────────────────────────────────
    Path.home() / ".gemini" / "antigravity" / "brain",
    Path.home() / ".claude" / "projects",
]
NOVELTY_THRESHOLD = 3.0
try:
    LOOP_INTERVAL = max(30, int(os.getenv("NOUSE_LOOP_INTERVAL_SEC", "600")))
except ValueError:
    LOOP_INTERVAL = 600
MIN_HOPS          = 3
MEMORY_CONSOLIDATION_EVERY = int(os.getenv("NOUSE_MEMORY_CONSOLIDATION_EVERY", "3"))
MEMORY_CONSOLIDATION_BATCH = max(1, int(os.getenv("NOUSE_MEMORY_CONSOLIDATION_BATCH", "40")))
MEMORY_CONSOLIDATION_MIN_EVIDENCE = float(
    os.getenv("NOUSE_MEMORY_CONSOLIDATION_MIN_EVIDENCE", "0.65")
)
KNOWLEDGE_BACKFILL_EVERY = int(os.getenv("NOUSE_KNOWLEDGE_BACKFILL_EVERY", "6"))
KNOWLEDGE_BACKFILL_LIMIT = max(1, int(os.getenv("NOUSE_KNOWLEDGE_BACKFILL_LIMIT", "160")))
KNOWLEDGE_BACKFILL_MIN_EVIDENCE = float(
    os.getenv("NOUSE_KNOWLEDGE_BACKFILL_MIN_EVIDENCE", "0.65")
)
MISSION_SEED_EVERY = max(1, int(os.getenv("NOUSE_MISSION_SEED_EVERY", "1")))
MISSION_SEED_MAX = max(0, int(os.getenv("NOUSE_MISSION_SEED_MAX", "2")))
MISSION_AUDIT_EVERY = max(1, int(os.getenv("NOUSE_MISSION_AUDIT_EVERY", "3")))
HITL_ENABLED = str(os.getenv("NOUSE_HITL_ENABLED", "1")).strip().lower() in _BOOL_TRUE
SOURCE_PROGRESS_TRACE = (
    str(os.getenv("NOUSE_SOURCE_PROGRESS_TRACE", "1")).strip().lower() in _BOOL_TRUE
)
try:
    SOURCE_PROGRESS_DOC_EVERY = max(
        1, int(os.getenv("NOUSE_SOURCE_PROGRESS_DOC_EVERY", "20"))
    )
except ValueError:
    SOURCE_PROGRESS_DOC_EVERY = 20
try:
    MAX_SOURCE_DOCS_PER_CYCLE = max(
        1, int(os.getenv("NOUSE_MAX_SOURCE_DOCS_PER_CYCLE", "50"))
    )
except ValueError:
    MAX_SOURCE_DOCS_PER_CYCLE = 50
try:
    SOURCE_TIMEOUT_SEC = max(
        60, int(os.getenv("NOUSE_SOURCE_TIMEOUT_SEC", "600"))
    )
except ValueError:
    SOURCE_TIMEOUT_SEC = 600
try:
    HITL_PRIORITY_THRESHOLD = max(
        0.0, min(1.0, float(os.getenv("NOUSE_HITL_PRIORITY_THRESHOLD", "0.98")))
    )
except ValueError:
    HITL_PRIORITY_THRESHOLD = 0.98
HITL_AUTO_APPROVE_LOW_RISK = (
    str(os.getenv("NOUSE_HITL_AUTO_APPROVE_LOW_RISK", "1")).strip().lower() in _BOOL_TRUE
)
try:
    HITL_AUTO_APPROVE_MAX_PRIORITY = max(
        0.0,
        min(1.0, float(os.getenv("NOUSE_HITL_AUTO_APPROVE_MAX_PRIORITY", "0.92"))),
    )
except ValueError:
    HITL_AUTO_APPROVE_MAX_PRIORITY = 0.92
HITL_AUTO_APPROVE_GAP_TYPES = {
    str(item).strip().lower()
    for item in str(
        os.getenv(
            "NOUSE_HITL_AUTO_APPROVE_GAP_TYPES",
            "mission_focus_domain,mission_bootstrap_domain",
        )
    ).split(",")
    if str(item).strip()
}
SOURCE_THROTTLE_FILE = path_from_env("NOUSE_SOURCE_THROTTLE_FILE", "source_throttle.json")
SOURCE_THROTTLE_FAIL_THRESHOLD = max(
    1, int(os.getenv("NOUSE_SOURCE_THROTTLE_FAIL_THRESHOLD", "3"))
)
SOURCE_THROTTLE_BASE_SEC = max(30, int(os.getenv("NOUSE_SOURCE_THROTTLE_BASE_SEC", "300")))
SOURCE_THROTTLE_MAX_SEC = max(
    SOURCE_THROTTLE_BASE_SEC,
    int(os.getenv("NOUSE_SOURCE_THROTTLE_MAX_SEC", "7200")),
)
SOURCE_THROTTLE_RECOVER_STEP = max(
    1, int(os.getenv("NOUSE_SOURCE_THROTTLE_RECOVER_STEP", "1"))
)
SYSTEM_EVENTS_PER_CYCLE = max(1, int(os.getenv("NOUSE_SYSTEM_EVENTS_PER_CYCLE", "8")))
SYSTEM_EVENT_MAX_CHARS = max(200, int(os.getenv("NOUSE_SYSTEM_EVENT_MAX_CHARS", "12000")))
WAKE_REASONS_PER_CYCLE = max(1, int(os.getenv("NOUSE_WAKE_REASONS_PER_CYCLE", "20")))
JOURNAL_TRACE_ENABLED = str(os.getenv("NOUSE_JOURNAL_TRACE_ENABLED", "1")).strip().lower() in _BOOL_TRUE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_last_cycle_from_status() -> int:
    try:
        if _STATUS_FILE.exists():
            payload = json.loads(_STATUS_FILE.read_text(encoding="utf-8", errors="ignore"))
            return max(0, int(payload.get("cycle", 0) or 0))
    except Exception:
        pass
    return 0


def _load_last_cycle_from_journal() -> int:
    path = latest_journal_file()
    if path is None or not path.exists():
        return 0
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return 0
    for raw in reversed(lines):
        if not raw.startswith("- "):
            continue
        m = re.search(r"\bcycle=(\d+)\b", raw)
        if not m:
            continue
        try:
            return max(0, int(m.group(1)))
        except ValueError:
            continue
    return 0


def _recover_cycle_counter(limbic_cycle: int) -> int:
    return max(
        0,
        int(limbic_cycle or 0),
        _load_last_cycle_from_status(),
        _load_last_cycle_from_journal(),
    )


def _split_path_list(raw: str) -> list[str]:
    parts = re.split(r"[\n,;]+", str(raw or "").strip())
    out: list[str] = []
    for part in parts:
        item = part.strip()
        if not item:
            continue
        out.append(item)
    return out


def _resolve_watch_paths() -> list[Path]:
    """
    Home-first watch-paths.
    - NOUSE_WATCH_PATHS: ersätter hela listan.
    - NOUSE_WATCH_EXTRA_PATHS: appendar extra paths (t.ex. externa diskar).
    """
    override_raw = str(os.getenv("NOUSE_WATCH_PATHS", "")).strip()
    if override_raw:
        base = [Path(p).expanduser() for p in _split_path_list(override_raw)]
    else:
        base = [Path(p) for p in DEFAULT_WATCH_PATHS]

    extra_raw = str(os.getenv("NOUSE_WATCH_EXTRA_PATHS", "")).strip()
    if extra_raw:
        base.extend(Path(p).expanduser() for p in _split_path_list(extra_raw))

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in base:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _load_source_throttle() -> dict[str, dict]:
    if not SOURCE_THROTTLE_FILE.exists():
        return {}
    try:
        raw = json.loads(SOURCE_THROTTLE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    state = raw.get("sources")
    if isinstance(state, dict):
        return state
    return {}


def _save_source_throttle(state: dict[str, dict]) -> None:
    SOURCE_THROTTLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated": _now_iso(), "sources": state}
    SOURCE_THROTTLE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _source_key(meta: dict) -> str:
    path = str(meta.get("path") or "").strip()
    if path:
        return path
    source = str(meta.get("source") or "unknown").strip()
    hint = str(meta.get("domain_hint") or "").strip()
    return f"{source}:{hint}" if hint else source


def _source_backoff_remaining(key: str, state: dict[str, dict], now_ts: float) -> float:
    row = state.get(key) or {}
    until = float(row.get("backoff_until", 0.0) or 0.0)
    return max(0.0, until - now_ts)


def _record_source_result(
    key: str,
    state: dict[str, dict],
    *,
    timed_out: bool,
    relation_count: int,
    used_fallback: bool,
) -> None:
    row = state.setdefault(
        key,
        {
            "failures": 0,
            "timeouts": 0,
            "successes": 0,
            "backoff_until": 0.0,
            "last_error": "",
            "updated": "",
        },
    )
    row["updated"] = _now_iso()

    if timed_out and relation_count == 0 and not used_fallback:
        fails = int(row.get("failures", 0) or 0) + 1
        row["failures"] = fails
        row["timeouts"] = int(row.get("timeouts", 0) or 0) + 1
        if fails >= SOURCE_THROTTLE_FAIL_THRESHOLD:
            exp = min(6, fails - SOURCE_THROTTLE_FAIL_THRESHOLD)
            delay = min(SOURCE_THROTTLE_MAX_SEC, SOURCE_THROTTLE_BASE_SEC * (2 ** exp))
            row["backoff_until"] = time.time() + delay
    else:
        row["successes"] = int(row.get("successes", 0) or 0) + (1 if relation_count > 0 else 0)
        fail_now = max(0, int(row.get("failures", 0) or 0) - SOURCE_THROTTLE_RECOVER_STEP)
        row["failures"] = fail_now
        if fail_now == 0:
            row["backoff_until"] = 0.0


def _install_signal_handlers(
    stop_event: asyncio.Event,
    *,
    on_stop: Callable[[], None] | None = None,
) -> None:
    """
    Kopplar SIGINT/SIGTERM till en kontrollerad avstängning av loopen.
    """
    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        if not stop_event.is_set():
            log.info("Stopp-signal mottagen. Avvecklar brain loop...")
            stop_event.set()
        if on_stop is not None:
            try:
                on_stop()
            except Exception:
                pass

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            # add_signal_handler stöds inte på alla plattformar/event loops.
            continue


async def _sleep_or_stop(
    seconds: float,
    stop_event: asyncio.Event | None,
    *,
    wake_event: asyncio.Event | None = None,
) -> str:
    if stop_event is None and wake_event is None:
        await asyncio.sleep(seconds)
        return "timeout"

    waiters: set[asyncio.Task[Any]] = set()
    try:
        if stop_event is not None:
            waiters.add(asyncio.create_task(stop_event.wait()))
        if wake_event is not None:
            waiters.add(asyncio.create_task(wake_event.wait()))
        if not waiters:
            await asyncio.sleep(seconds)
            return "timeout"
        done, pending = await asyncio.wait(
            waiters,
            timeout=seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if done:
            await asyncio.gather(*done, return_exceptions=True)
        if stop_event is not None and stop_event.is_set():
            return "stop"
        if wake_event is not None and wake_event.is_set():
            wake_event.clear()
            return "wake"
        return "timeout"
    finally:
        for task in waiters:
            if not task.done():
                task.cancel()


async def _process_pending_system_events(
    field: FieldSurface,
    memory_store: MemoryStore,
    *,
    max_events: int,
    stdp_bridge: "Brian2Bridge | None" = None,
) -> tuple[int, int]:
    rows = drain_system_event_entries(limit=max_events)
    if not rows:
        return 0, 0

    processed = 0
    added_total = 0
    for row in rows:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        processed += 1
        if len(text) > SYSTEM_EVENT_MAX_CHARS:
            text = text[:SYSTEM_EVENT_MAX_CHARS]
        sid = str(row.get("session_id") or "main")
        src = str(row.get("source") or "system").strip() or "system"
        ckey = str(row.get("context_key") or "").strip()
        meta = {
            "source": f"system_event:{src}",
            "path": f"system_event:{sid}",
            "session_id": sid,
            "run_id": "system_event",
        }
        if ckey:
            meta["context_key"] = ckey
        try:
            rels, _diag = await extract_relations_with_diagnostics(text, meta)
        except Exception as e:
            log.warning("System-event extraktion misslyckades (session=%s): %s", sid, e)
            continue

        try:
            memory_store.ingest_episode(text, meta, rels)
        except Exception as e:
            log.warning("System-event minneslagring misslyckades (session=%s): %s", sid, e)

        _limbic = load_state()
        _coordinator = LearningCoordinator(field, _limbic)

        async def _write_sysevt() -> int:
            count = 0
            for r in rels:
                field.add_concept(r["src"], r["domain_src"], source=meta["source"])
                field.add_concept(r["tgt"], r["domain_tgt"], source=meta["source"])
                field.add_relation(
                    r["src"],
                    r["type"],
                    r["tgt"],
                    why=r.get("why", ""),
                    source_tag=f"{meta['source']}:{sid}",
                )
                _coordinator.on_fact(
                    r["src"], r["type"], r["tgt"],
                    why=r.get("why", ""),
                    evidence_score=float(r.get("evidence_score") or 0.35),
                    support_count=int(r.get("support_count") or 1),
                )
                if stdp_bridge:
                    stdp_bridge.on_fact(r["src"], r["type"], r["tgt"])
                try:
                    from nouse.daemon.node_inbox import get_inbox as _get_inbox
                    _get_inbox().add(
                        r["src"], r["type"], r["tgt"],
                        why=r.get("why", ""),
                        evidence_score=float(r.get("evidence_score") or 0.35),
                        source="system_events",
                    )
                except Exception:
                    pass
                count += 1
            return count

        added_total += await enqueue_write(_write_sysevt())
    return processed, added_total


async def brain_loop(
    field: FieldSurface,
    *,
    stop_event: asyncio.Event | None = None,
    wake_event: asyncio.Event | None = None,
    memory: MemoryStore | None = None,
) -> None:
    global BRAIN_TRANSPORTER
    sources = _build_sources()
    limbic_state = load_state()
    memory_store = memory or MemoryStore()
    source_throttle = _load_source_throttle()
    cycle = _recover_cycle_counter(limbic_state.cycle)  # återuppta räknaren robust
    mission_state = load_mission()
    living_state = ensure_living_core()
    stdp_bridge = Brian2Bridge(field)          # STDP-timing, delas av hela brain_loop
    inbox = get_inbox()                        # Arbetsminne (hippocampus)
    nightrun = NightRunScheduler()             # Konsolidering (sömn)
    camera_watcher = CameraWatcher(field=field, interval=120)  # Occipital lobe (syn)
    speech_listener = SpeechListener(field=field, interval=60)  # Temporal lobe (hörsel)
    speech_speaker = SpeechSpeaker(field=field)                # Frontal lobe (tal/Broca)

    # Ladda in externa självskrivna plugins
    load_plugins()

    log.info(
        f"Brain loop startad — {len(sources)} källor, graf: {field.stats()}, "
        f"λ={limbic_state.lam:.2f}"
    )
    log.info(f"Memory store: {memory_store.root}")
    log.info(f"Source throttling: {len(source_throttle)} poster")
    log.info("System-event queue: pending=%d", int(system_event_stats().get("pending_total", 0) or 0))
    if mission_state:
        log.info(f"Mission aktiv: {mission_summary(mission_state)}")
    else:
        log.info("Mission: ingen aktiv mission")
    log.info(
        "Living core: mode=%s drive=%s",
        (living_state.get("homeostasis") or {}).get("mode", "steady"),
        (living_state.get("drives") or {}).get("active", "maintenance"),
    )

    def _journal_stage(
        *,
        stage: str,
        thought: str = "",
        action: str = "",
        result: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        if not JOURNAL_TRACE_ENABLED:
            return
        try:
            write_cycle_trace(
                cycle=cycle,
                stage=stage,
                thought=thought,
                action=action,
                result=result,
                details=details,
            )
        except Exception as e:
            log.warning("  Journal trace misslyckades (%s): %s", stage, e)

    try:
        # Skriv initial heartbeat direkt vid startup så externa watchdogs
        # inte tolkar en ny daemon som "status stale" innan första loopen är klar.
        _write_status(field.stats(), limbic_state, cycle, 0)
    except Exception as e:
        log.warning(f"Kunde inte skriva initial status: {e}")

    try:
        while not (stop_event and stop_event.is_set()):
            cycle += 1
            # Persista cykel tidigt i varvet så restart mitt i ingest inte återställer
            # journal-cykeln till samma nummer.
            try:
                _write_status(field.stats(), limbic_state, cycle, 0)
            except Exception as e:
                log.warning(f"Kunde inte persistera cycle-heartbeat: {e}")
            new_rel = 0
            source_docs_processed = 0
            source_relations_added = 0
            source_timeouts = 0
            source_fallbacks = 0
            source_throttled = 0
            source_errors = 0
            source_quality_scores: list[float] = []
            source_success_models: dict[str, int] = {}
            source_attempted_models: dict[str, int] = {}
            synth_added_total = 0
            curiosity_summary: dict[str, Any] = {"status": "not_run"}
            mission_state = load_mission()
            wake_reasons = consume_wake_reasons(limit=WAKE_REASONS_PER_CYCLE)
            if wake_reasons:
                summary = ", ".join(
                    f"{str(r.get('reason') or 'wake')}@{str(r.get('session_id') or 'main')}"
                    for r in wake_reasons[:5]
                )
                log.info(
                    "Wake-signaler: %s%s",
                    summary,
                    " …" if len(wake_reasons) > 5 else "",
                )

            _journal_stage(
                stage="cycle_start",
                thought=(
                    "Startar ny cykel med fokus på evidens-gated tillväxt och "
                    "spårbar autonomi."
                ),
                action="Initierar wake-signaler, system-events och source ingest.",
                result="Cykel initierad.",
                details={
                    "wake_reasons": len(wake_reasons),
                    "wake_reason_labels": [
                        str(r.get("reason") or "wake") for r in wake_reasons[:8]
                    ],
                    "mission": mission_summary(mission_state),
                    "system_events_pending": int(
                        system_event_stats().get("pending_total", 0) or 0
                    ),
                },
            )

            event_count, event_rel = await _process_pending_system_events(
                field,
                memory_store,
                max_events=SYSTEM_EVENTS_PER_CYCLE,
                stdp_bridge=stdp_bridge,
            )
            if event_count:
                new_rel += event_rel
                log.info(
                    "System-events processade: %d (+%d relationer)",
                    event_count,
                    event_rel,
                )

            _journal_stage(
                stage="system_events",
                thought="Prioriterar operativa signaler som kräver snabb ingest.",
                action="Processar pending system-events med relationsextraktion.",
                result=f"Bearbetade {event_count} events, +{event_rel} relationer.",
                details={"events": event_count, "added_relations": event_rel},
            )

            # ── 1-3: Läs → Extrahera → Uppdatera graf ─────────────────────────
            _source_cycle_start = time.monotonic()
            for source in sources:
                if stop_event and stop_event.is_set():
                    break
                source_name = source.__class__.__name__
                throttled = 0
                source_quality_scores_local: list[float] = []
                source_success_models_local: dict[str, int] = {}
                source_attempted_models_local: dict[str, int] = {}
                docs_before = source_docs_processed
                rels_before = source_relations_added
                timeouts_before = source_timeouts
                fallbacks_before = source_fallbacks
                errors_before = source_errors
                source_docs_local = 0
                source_start = time.monotonic()
                try:
                    for text, meta in source.read_new():
                        if stop_event and stop_event.is_set():
                            break
                        # ── Per-cycle caps: doc limit + per-source timeout ──
                        if source_docs_processed >= MAX_SOURCE_DOCS_PER_CYCLE:
                            log.info(
                                "  Source doc cap reached (%d/%d), deferring remaining docs",
                                source_docs_processed, MAX_SOURCE_DOCS_PER_CYCLE,
                            )
                            break
                        if time.monotonic() - source_start > SOURCE_TIMEOUT_SEC:
                            log.warning(
                                "  Source %s timed out after %ds",
                                source_name, SOURCE_TIMEOUT_SEC,
                            )
                            break
                            break
                        source_docs_processed += 1
                        source_docs_local += 1
                        source_key = _source_key(meta)
                        remaining = _source_backoff_remaining(source_key, source_throttle, time.time())
                        if remaining > 0:
                            throttled += 1
                            source_throttled += 1
                            continue

                        rels, diag = await extract_relations_with_diagnostics(text, meta)
                        timed_out = int(diag.get("timeouts", 0) or 0) > 0
                        used_fallback = bool(diag.get("used_heuristic_fallback"))
                        source_timeouts += int(diag.get("timeouts", 0) or 0)
                        try:
                            quality = float(diag.get("quality")) if diag.get("quality") is not None else None
                        except (TypeError, ValueError):
                            quality = None
                        if quality is not None:
                            source_quality_scores.append(quality)
                            source_quality_scores_local.append(quality)
                        success_model = str(diag.get("success_model") or "").strip()
                        if success_model:
                            source_success_models[success_model] = (
                                source_success_models.get(success_model, 0) + 1
                            )
                            source_success_models_local[success_model] = (
                                source_success_models_local.get(success_model, 0) + 1
                            )
                        attempted_models = (
                            diag.get("attempted_models")
                            if isinstance(diag.get("attempted_models"), list)
                            else []
                        )
                        for attempted in attempted_models:
                            model_name = str(attempted or "").strip()
                            if not model_name:
                                continue
                            source_attempted_models[model_name] = (
                                source_attempted_models.get(model_name, 0) + 1
                            )
                            source_attempted_models_local[model_name] = (
                                source_attempted_models_local.get(model_name, 0) + 1
                            )
                        if used_fallback:
                            source_fallbacks += 1
                        _record_source_result(
                            source_key,
                            source_throttle,
                            timed_out=timed_out,
                            relation_count=len(rels),
                            used_fallback=used_fallback,
                        )
                        try:
                            memory_store.ingest_episode(text, meta, rels)
                        except Exception as e:
                            log.warning(f"Memory ingest misslyckades: {e}")
                        async def _write_source_rels() -> int:
                            count = 0
                            for r in rels:
                                field.add_concept(
                                    r["src"], r["domain_src"], source=meta.get("source", "file")
                                )
                                field.add_concept(
                                    r["tgt"], r["domain_tgt"], source=meta.get("source", "file")
                                )
                                # ── brain_sync: Analogy Event (cross-domain relations) ──
                                if BRAIN_SYNC_ENABLED:
                                    src_domain = str(r.get("domain_src") or "").strip().lower()
                                    tgt_domain = str(r.get("domain_tgt") or "").strip().lower()
                                    different_domains = src_domain != tgt_domain and len(src_domain) > 0 and len(tgt_domain) > 0
                                    if different_domains:
                                        try:
                                            strength = float(r.get("strength", 0.0) or 0.0)
                                            evidence = float(r.get("evidence_score", 0.0) or 0.0)
                                            if strength > 0.7 or evidence > 0.65:
                                                evt = analogy_event(
                                                    concept_a=r["src"],
                                                    concept_b=r["tgt"],
                                                    relation_strength=strength,
                                                    evidence_score=evidence,
                                                    relation_type=r["type"],
                                                )
                                                if BRAIN_TRANSPORTER:
                                                    BRAIN_TRANSPORTER.send(evt)
                                        except Exception:
                                            pass
                                field.add_relation(
                                    r["src"],
                                    r["type"],
                                    r["tgt"],
                                    why=r.get("why", ""),
                                    source_tag=meta.get("path", ""),
                                    domain_src=r.get("domain_src", "okänd"),
                                    domain_tgt=r.get("domain_tgt", "okänd"),
                                )
                                LearningCoordinator(field, limbic_state).on_fact(
                                    r["src"], r["type"], r["tgt"],
                                    why=r.get("why", ""),
                                    evidence_score=float(r.get("evidence_score") or 0.35),
                                    support_count=int(r.get("support_count") or 1),
                                )
                                stdp_bridge.on_fact(r["src"], r["type"], r["tgt"])
                                inbox.add(
                                    r["src"], r["type"], r["tgt"],
                                    why=r.get("why", ""),
                                    evidence_score=float(r.get("evidence_score") or 0.35),
                                    source=meta.get("path", ""),
                                    domain_src=r.get("domain_src", "okänd"),
                                    domain_tgt=r.get("domain_tgt", "okänd"),
                                )
                                count += 1
                            return count

                        _added = await enqueue_write(_write_source_rels())
                        new_rel += _added
                        source_relations_added += _added

                        if (
                            SOURCE_PROGRESS_TRACE
                            and JOURNAL_TRACE_ENABLED
                            and (source_docs_local % SOURCE_PROGRESS_DOC_EVERY == 0)
                        ):
                            _journal_stage(
                                stage="source_progress",
                                thought=(
                                    "Fortsätter ingest i samma källa och exponerar "
                                    "delprogress för observabilitet."
                                ),
                                action=f"Källa={source_name} delprogress.",
                                result=(
                                    f"docs_local={source_docs_local}, "
                                    f"docs_total={source_docs_processed}, "
                                    f"rels_total={source_relations_added}."
                                ),
                                details={
                                    "source": source_name,
                                    "docs_local": source_docs_local,
                                    "docs_total": source_docs_processed,
                                    "rels_total": source_relations_added,
                                    "quality_samples": len(source_quality_scores_local),
                                    "quality_avg": (
                                        round(
                                            sum(source_quality_scores_local)
                                            / len(source_quality_scores_local),
                                            4,
                                        )
                                        if source_quality_scores_local
                                        else 0.0
                                    ),
                                    "quality_max": (
                                        round(max(source_quality_scores_local), 4)
                                        if source_quality_scores_local
                                        else 0.0
                                    ),
                                    "success_models": {
                                        k: v
                                        for k, v in sorted(
                                            source_success_models_local.items(),
                                            key=lambda it: (-it[1], it[0]),
                                        )[:3]
                                    },
                                    "attempted_models": {
                                        k: v
                                        for k, v in sorted(
                                            source_attempted_models_local.items(),
                                            key=lambda it: (-it[1], it[0]),
                                        )[:3]
                                    },
                                },
                            )
                    if throttled:
                        log.info(
                            "  Source throttled: %s skipped=%d",
                            source_name,
                            throttled,
                        )
                except Exception as e:
                    source_errors += 1
                    log.warning(f"{source_name}: {e}")
                finally:
                    if SOURCE_PROGRESS_TRACE and JOURNAL_TRACE_ENABLED:
                        docs_delta = source_docs_processed - docs_before
                        rels_delta = source_relations_added - rels_before
                        timeouts_delta = source_timeouts - timeouts_before
                        fallbacks_delta = source_fallbacks - fallbacks_before
                        errors_delta = source_errors - errors_before
                        if (
                            docs_delta
                            or rels_delta
                            or throttled
                            or timeouts_delta
                            or fallbacks_delta
                            or errors_delta
                        ):
                            _journal_stage(
                                stage="source_progress",
                                thought=(
                                    "Håller kontinuerlig ingest-observabilitet under pågående "
                                    "cykel för att undvika blinda perioder."
                                ),
                                action=f"Källa={source_name} processades.",
                                result=(
                                    f"docs={docs_delta}, +rels={rels_delta}, "
                                    f"timeouts={timeouts_delta}, "
                                    f"fallbacks={fallbacks_delta}, "
                                    f"throttled={throttled}, errors={errors_delta}."
                                ),
                                details={
                                    "source": source_name,
                                    "docs_delta": docs_delta,
                                    "rels_delta": rels_delta,
                                    "timeouts_delta": timeouts_delta,
                                    "fallbacks_delta": fallbacks_delta,
                                    "throttled": throttled,
                                    "errors_delta": errors_delta,
                                    "quality_samples": len(source_quality_scores_local),
                                    "quality_avg": (
                                        round(
                                            sum(source_quality_scores_local)
                                            / len(source_quality_scores_local),
                                            4,
                                        )
                                        if source_quality_scores_local
                                        else 0.0
                                    ),
                                    "quality_max": (
                                        round(max(source_quality_scores_local), 4)
                                        if source_quality_scores_local
                                        else 0.0
                                    ),
                                    "success_models": {
                                        k: v
                                        for k, v in sorted(
                                            source_success_models_local.items(),
                                            key=lambda it: (-it[1], it[0]),
                                        )[:3]
                                    },
                                    "attempted_models": {
                                        k: v
                                        for k, v in sorted(
                                            source_attempted_models_local.items(),
                                            key=lambda it: (-it[1], it[0]),
                                        )[:3]
                                    },
                                },
                            )

            _journal_stage(
                stage="source_ingest",
                thought=(
                    "Skannar brett men släpper inte igenom relationer utan evidenssignal."
                ),
                action="Läste källor, extraherade relationer, tillämpade throttle/fallback.",
                result=(
                    f"Docs={source_docs_processed}, +rels={source_relations_added}, "
                    f"timeouts={source_timeouts}, fallbacks={source_fallbacks}, "
                    f"throttled={source_throttled}, errors={source_errors}."
                ),
                details={
                    "docs_processed": source_docs_processed,
                    "added_relations": source_relations_added,
                    "timeouts": source_timeouts,
                    "fallbacks": source_fallbacks,
                    "fallback_rate": (
                        round(source_fallbacks / max(1, source_docs_processed), 4)
                        if source_docs_processed > 0
                        else 0.0
                    ),
                    "throttled": source_throttled,
                    "errors": source_errors,
                    "quality_samples": len(source_quality_scores),
                    "quality_avg": (
                        round(sum(source_quality_scores) / len(source_quality_scores), 4)
                        if source_quality_scores
                        else 0.0
                    ),
                    "quality_max": (
                        round(max(source_quality_scores), 4)
                        if source_quality_scores
                        else 0.0
                    ),
                    "success_models": {
                        k: v
                        for k, v in sorted(
                            source_success_models.items(),
                            key=lambda it: (-it[1], it[0]),
                        )[:5]
                    },
                    "attempted_models": {
                        k: v
                        for k, v in sorted(
                            source_attempted_models.items(),
                            key=lambda it: (-it[1], it[0]),
                        )[:5]
                    },
                },
            )

            # ── 4a: BFS-nervbanor (begränsad till top-domäner) ────────────────
            _all_domains = field.domains()
            # Begränsa till max 15 domäner för att undvika O(D²) explosion
            import random as _random
            domains = _all_domains[:15] if len(_all_domains) > 15 else _all_domains
            found = []
            _bfs_pairs = 0
            for i, da in enumerate(domains):
                if stop_event and stop_event.is_set():
                    break
                for db in domains[i + 1 :]:
                    if stop_event and stop_event.is_set():
                        break
                    _bfs_pairs += 1
                    if _bfs_pairs % 10 == 0:
                        await asyncio.sleep(0)  # yield till event loop var 10:e par
                    path = field.find_path(da, db, max_hops=4)  # max_hops 8→4
                    if path and len(path) >= MIN_HOPS:
                        nov = field.path_novelty(path)
                        if nov >= NOVELTY_THRESHOLD:
                            found.append(
                                {
                                    "domain_a": da,
                                    "domain_b": db,
                                    "path": path,
                                    "novelty": nov,
                                    "hops": len(path),
                                    "source": "bfs",
                                }
                            )

            found.sort(key=lambda x: x["novelty"], reverse=True)

            # ── 4b: TDA bisociationskandidater (Koestler Step B) ──────────────
            # Hämta strategiska bryggregdomäner från percolation-modulen
            _bridge_domains = []
            try:
                _bridge_domains = [bd.name for bd in identify_bridge_domains(field)]
            except Exception:
                pass
            try:
                candidates = field.bisociation_candidates(
                    tau_threshold=0.55, max_domains=50,
                    priority_domains=_bridge_domains if _bridge_domains else None,
                )
                if candidates:
                    log.info(f"  TDA: {len(candidates)} bisociationskandidater")
                    for c in candidates[:3]:
                        log.info(
                            f"    τ={c['tau']:.3f}  "
                            f"{c['domain_a']} × {c['domain_b']}  "
                            f"(H0: {c['h0_a']}/{c['h0_b']}, H1: {c['h1_a']}/{c['h1_b']})"
                        )
            except Exception as e:
                candidates = []
                log.warning(f"TDA bisociation_candidates: {e}")

            # ── 4b2: Målinriktad bisociationssökning bland bryggregdomäner ─────
            # Standard-sökningen missar små bryggregdomäner pga max_domains-filtrering.
            # Denna riktade sökning garanterar att alla strategiska domäner analyseras.
            bridge_candidates = []
            if _bridge_domains:
                try:
                    bridge_candidates = bridge_bisociation_search(
                        field, bridges=None,
                        tau_threshold=0.55, max_epsilon=2.0,
                    )
                    if bridge_candidates:
                        # Filtrera bort kandidater som redan finns i standard-resultatet
                        standard_pairs = {
                            (c["domain_a"], c["domain_b"]) for c in candidates
                        } | {
                            (c["domain_b"], c["domain_a"]) for c in candidates
                        }
                        novel = [
                            bc for bc in bridge_candidates
                            if (bc["domain_a"], bc["domain_b"]) not in standard_pairs
                        ]
                        if novel:
                            log.info(
                                f"  Bridge-bisoc: {len(novel)} nya kandidater "
                                f"bland bryggregdomäner (totalt {len(bridge_candidates)})"
                            )
                            for bc in novel[:3]:
                                log.info(
                                    f"    τ={bc['tau']:.3f}  "
                                    f"{bc['domain_a']} × {bc['domain_b']}"
                                )
                        # Lägg till nya kandidater i huvudlistan
                        candidates.extend(novel)
                except Exception as e:
                    log.warning(f"  Bridge-bisociation search (non-fatal): {e}")

            # ── 4c: Autonom bridge discovery för toppkandidater ───────────────
            if candidates and not (stop_event and stop_event.is_set()):
                try:
                    import asyncio as _asyncio
                    from nouse.field.bridge_finder import run_cross_domain_discovery
                    top_domains: list[str] = list(dict.fromkeys(
                        d
                        for c in candidates[:5]
                        for d in (c["domain_a"], c["domain_b"])
                    ))
                    _coord = LearningCoordinator(field, limbic_state)
                    _bridge_session = await _asyncio.wait_for(
                        run_cross_domain_discovery(
                            field,
                            _coord,
                            domains=top_domains,
                            max_pairs=5,
                        ),
                        timeout=120.0,
                    )
                    if _bridge_session.bridges_found:
                        log.info(
                            f"  BISOC-BRIDGE: {_bridge_session.bridges_found} bryggor funna, "
                            f"{_bridge_session.bridges_written} skrivna "
                            f"({_bridge_session.pairs_evaluated} par utvärderade)"
                        )
                except _asyncio.TimeoutError:
                    log.warning("Bridge discovery (bisociation): timeout efter 120s — hoppar över")
                except Exception as _be:
                    log.warning(f"Bridge discovery (bisociation): {_be}")

            # ── 5: Limbic Layer ────────────────────────────────────────────────
            limbic_state = run_limbic_cycle(
                limbic_state,
                new_relations=new_rel,
                discoveries=len(found),
                bisociation_candidates=len(candidates),
                novel_domains=max(0, len(domains) - limbic_state.cycle),
                active_domains=len(domains),
            )
            
            # ── brain_sync: Limbic Spike Event ───────────────────────────────
            if BRAIN_SYNC_ENABLED and BRAIN_TRANSPORTER:
                # Skicka limbic spike event för höga neuromodulator-signaler
                # λ är en proxy för arousal-nivå
                try:
                    if limbic_state.noradrenaline > 0.7:
                        evt = limbic_spike_event(
                            signal_type="noradrenaline",
                            magnitude=float(limbic_state.noradrenaline),
                        )
                        BRAIN_TRANSPORTER.send(evt)
                    elif limbic_state.dopamine > 0.8:
                        evt = limbic_spike_event(
                            signal_type="dopamine",
                            magnitude=float(limbic_state.dopamine),
                        )
                        BRAIN_TRANSPORTER.send(evt)
                except Exception:
                    pass

            # ── 6: Syntetisera bryggor + skriv till Self ───────────────────────
            for disc in found[:5]:
                if stop_event and stop_event.is_set():
                    break
                await write_discovery(disc)
                log.info(
                    f"  NERVBANA  {disc['path'][0][0]} → {disc['path'][-1][2]}"
                    f"  ({disc['hops']} hopp, novelty={disc['novelty']:.1f})"
                )

                try:
                    bridges = await synthesize_bridges(
                        disc["path"],
                        disc["domain_a"],
                        disc["domain_b"],
                        lam=limbic_state.lam,
                    )
                    async def _write_bridges() -> int:
                        count = 0
                        for b in bridges:
                            field.add_concept(b["src"], b.get("domain_src", "okänd"))
                            field.add_concept(b["tgt"], b.get("domain_tgt", "okänd"))
                            field.add_relation(
                                b["src"],
                                b["rel_type"],
                                b["tgt"],
                                why=b.get("why", ""),
                                source_tag="syntes",
                                domain_src=b.get("domain_src", "okänd"),
                                domain_tgt=b.get("domain_tgt", "okänd"),
                            )
                            LearningCoordinator(field, limbic_state).on_fact(
                                b["src"], b["rel_type"], b["tgt"],
                                why=b.get("why", ""),
                                evidence_score=float(b.get("evidence_score") or 0.35),
                                support_count=int(b.get("support_count") or 1),
                            )
                            stdp_bridge.on_fact(b["src"], b["rel_type"], b["tgt"])
                            inbox.add(
                                b["src"], b["rel_type"], b["tgt"],
                                why=b.get("why", ""),
                                evidence_score=float(b.get("evidence_score") or 0.35),
                                source="syntes",
                                domain_src=b.get("domain_src", "okänd"),
                                domain_tgt=b.get("domain_tgt", "okänd"),
                            )
                            count += 1
                        return count

                    synth_count = await enqueue_write(_write_bridges())
                    
                    # ── brain_sync: Bisociation Event ───────────────────────
                    if BRAIN_SYNC_ENABLED and BRAIN_TRANSPORTER is None:
                        try:
                            BRAIN_TRANSPORTER = BrainTransporter()
                            log.info("  brain_sync: Transporter instansierad.")
                        except Exception as e:
                            log.warning(f"  brain_sync: Kunde inte initiera transporter: {e}")
                    
                    if BRAIN_TRANSPORTER and bridges:
                        # En bisociation_event per upptäckt nervbana
                        for b in bridges:
                            evt = bisociation_event(
                                domain_a=disc["domain_a"],
                                domain_b=disc["domain_b"],
                                bridge_strength=b.get("relation_strength", 0.5),
                                bisoc_quality=float(b.get("evidence_score", 0.0)),
                            )
                            BRAIN_TRANSPORTER.send(evt)
                            # Undvik spam: skickar bara en gång per cykel
                            pass
                except Exception as e:
                    log.warning(f"  Syntes misslyckades: {e}")

            _journal_stage(
                stage="bridge_synthesis",
                thought=(
                    "Leter efter icke-triviala bryggor mellan domäner för att minska "
                    "strukturell fragmentering."
                ),
                action="Körde BFS + TDA och syntetiserade atomära bryggor där möjligt.",
                result=(
                    f"nervbanor={len(found)}, bisoc_candidates={len(candidates)}, "
                    f"synth_added={synth_added_total}."
                ),
                details={
                    "discoveries": len(found),
                    "bisoc_candidates": len(candidates),
                    "synth_added": synth_added_total,
                },
            )

            # ── 7: Periodisk compaction (noradrenalin styr aggressivitet) ──────
            if should_run(cycle):
                # Noradrenalin-nivå påverkar hur hårt vi prunar
                dynamic_threshold = WEAK_THRESHOLD * (0.5 + limbic_state.pruning_aggression)
                log.info(
                    f"Cykel {cycle}: compaction "
                    f"(NA={limbic_state.noradrenaline:.2f}, "
                    f"threshold={dynamic_threshold:.2f})..."
                )
                stats = run_compaction(field)
                log.info(
                    f"  Compaction: -{stats['edges_pruned']} kanter, "
                    f"-{stats['nodes_pruned']} orphan-noder"
                )

            # ── 8: Autonom Curiosity Loop + D3 Goal-Directed Execution ────────
            # Vi kör curiosity ca var 3:e cykel för att inte överlasta.
            if cycle % 3 == 0 and not (stop_event and stop_event.is_set()):
                try:
                    seed_tasks: list[dict] = []
                    if mission_state and MISSION_SEED_MAX > 0 and cycle % MISSION_SEED_EVERY == 0:
                        seed_tasks = build_seed_tasks(field, mission_state, max_new=MISSION_SEED_MAX)
                        if seed_tasks:
                            log.info(
                                "  Mission-seeding: +%d taskar (%s)",
                                len(seed_tasks),
                                mission_summary(mission_state),
                            )

                    # ── 8a: D3 Goal weight decay + percolation goal generation ──
                    # Decay goal weights from previous cycle, then apply fresh weights.
                    if hasattr(field, "decay_goal_weights"):
                        try:
                            field.decay_goal_weights(rate=0.05)
                        except Exception:
                            pass

                    # Generate percolation goals every 3rd cycle and apply weights
                    if cycle % 6 == 0:
                        try:
                            from nouse.daemon.goal_generator import generate_from_percolation
                            from nouse.daemon.goal_registry import active_goals
                            perc_goals = generate_from_percolation(field, cycle, max_goals=5)
                            if perc_goals:
                                from nouse.daemon.goal_registry import save_goal
                                for pg in perc_goals:
                                    save_goal(pg)
                                log.info(f"  D3: {len(perc_goals)} percolation-mål genererade")

                            # Apply goal weights to field for collapse bias
                            all_active = active_goals()
                            if hasattr(field, "apply_goal_weights") and all_active:
                                n_updated = field.apply_goal_weights(all_active)
                                if n_updated:
                                    log.info(f"  D3: goal_weights uppdaterade på {n_updated} noder")
                        except Exception as d3_err:
                            log.debug(f"  D3 percolation-goals (non-fatal): {d3_err}")

                    # ── 8b: Gap detection + percolation ingestion (proper queue) ──
                    added_tasks = enqueue_gap_tasks(field, max_new=4, seed_tasks=seed_tasks)
                    if added_tasks:
                        log.info(f"  Gap-detektor: +{len(added_tasks)} nya research-taskar")

                    # Percolation-aware ingestion — every 6th cycle, feed through proper queue
                    if cycle % 6 == 0:
                        try:
                            perc_report = domain_density_report(field)
                            log.info(
                                f"  Percolation: readiness={perc_report.bisociation_readiness:.1%}, "
                                f"thin={perc_report.domains_thin}, "
                                f"deficit={perc_report.cross_domain_edge_deficit}, "
                                f"single-domains={perc_report.single_concept_domains}"
                            )
                            if perc_report.bisociation_readiness < 0.5:
                                perc_tasks = generate_ingestion_tasks(field, report=perc_report)
                                if perc_tasks:
                                    # Use proper enqueue for deduplication
                                    perc_added = enqueue_gap_tasks(
                                        field, max_new=10, seed_tasks=perc_tasks
                                    )
                                    if perc_added:
                                        log.info(
                                            f"  Percolation: +{len(perc_added)} riktade taskar "
                                            f"(bridge_build + domain_expand)"
                                        )
                        except Exception as perc_err:
                            log.warning(f"  Percolation-analys fel (non-fatal): {perc_err}")

                    # ── 8b2: Autonomic homeostasis (every 6th cycle) ─────────────
                    # Reads brain atlas region distribution and auto-seeds
                    # underrepresented regions (<5%). Mirrors biological homeostasis.
                    if cycle % 6 == 0:
                        try:
                            from nouse.daemon.homeostasis import run_homeostasis_check
                            h_results = await run_homeostasis_check(field, cycle)
                            seeded = {r: v for r, v in h_results.items()
                                      if v.get("action") == "seeded"}
                            overrep = {r: v for r, v in h_results.items()
                                       if v.get("action") == "overrepresented"}
                            if seeded:
                                total_added = sum(
                                    v.get("predefined_added", 0) + v.get("llm_generated", 0)
                                    for v in seeded.values()
                                )
                                log.info(
                                    f"  Homeostas: {len(seeded)} regioner seedade "
                                    f"+{total_added} koncept "
                                    f"({', '.join(seeded.keys())})"
                                )
                            if overrep:
                                log.warning(
                                    f"  Homeostas: {len(overrep)} överrepresenterade regioner: "
                                    + ", ".join(
                                        f"{r}={v['pct']:.0%}" for r, v in overrep.items()
                                    )
                                )
                        except Exception as h_err:
                            log.debug(f"  Homeostasis check (non-fatal): {h_err}")

                    # ── 8c: D3 Meta-cognitive self-knowledge ────────────────────
                    # Nous reports what it understands about its own gaps.
                    try:
                        from nouse.daemon.percolation import identify_loose_nodes as _find_loose
                        loose = _find_loose(field, min_cross_domain_connections=1, max_nodes=50)
                        n_isolated = sum(1 for n in loose if n["is_isolated"])
                        n_loose = len(loose)
                        target_domains = sorted(set(n["domain"] for n in loose[:8]))
                        log.info(
                            f"  Self-knowledge: {n_isolated} isolerade, {n_loose} lösa. "
                            f"Targeting: {', '.join(target_domains[:5])}"
                        )
                    except Exception:
                        pass

                    # ── 8d: Sweet spot calibration (every 12th cycle) ────────────
                    # Nervbana axion density + rigidity + Yerkes-Dodson curve.
                    if cycle % 12 == 0:
                        try:
                            from nouse.daemon.percolation import sweet_spot_report as _sweet_spot
                            ss = _sweet_spot(field, max_nervbanor=200)
                            s = ss.get("summary", {})
                            log.info(
                                f"  Sweet spot: {s.get('n_isolated', 0)} isolerade, "
                                f"{s.get('n_sweet', 0)} sweet, {s.get('n_rigid', 0)} rigida. "
                                f"Density={s.get('avg_axion_density', 0):.4f}, "
                                f"rigidity={s.get('avg_rigidity', 0):.3f}"
                            )
                        except Exception:
                            pass

                    # ── 8d2: Brain atlas region balance (every 24th cycle) ────────
                    if cycle % 24 == 0:
                        try:
                            atlas_stats = atlas_region_report(field)
                            # Summarize key regions (frontal, temporal, hippocampus, amygdala)
                            key_regions = ["frontal_lobe", "temporal_lobe", "hippocampus", "amygdala"]
                            region_summary = []
                            for rname in key_regions:
                                rs = atlas_stats.get(rname)
                                if rs:
                                    region_summary.append(f"{rs.name}={rs.concept_count}")
                            log.info(
                                f"  Brain atlas: {', '.join(region_summary)} | "
                                f"total={sum(s.concept_count for s in atlas_stats.values())}"
                            )
                        except Exception:
                            pass

                    # ── 8e: Camera + Speech (sensorimotor loop) ────────────────
                    try:
                        cam_obs = camera_watcher.tick()
                        if cam_obs:
                            log.info(f"  Camera: {len(cam_obs.concepts)} concepts, "
                                     f"confidence={cam_obs.confidence:.2f}")
                    except Exception:
                        pass
                    try:
                        speech_result = speech_listener.tick()
                        if speech_result:
                            log.info(f"  Heard: '{speech_result.text[:60]}' "
                                     f"(lang={speech_result.language})")
                    except Exception:
                        pass

                    task = claim_next_task()
                    if not task:
                        q = queue_stats()
                        curiosity_summary = {
                            "status": "queue_empty",
                            "pending": int(q.get("pending", 0) or 0),
                            "in_progress": int(q.get("in_progress", 0) or 0),
                        }
                        log.info(
                            "  Curiosity-queue tom "
                            f"(pending={q['pending']}, in_progress={q['in_progress']})"
                        )
                    else:
                        task_id = int(task.get("id", -1) or -1)
                        if HITL_ENABLED and task_id > 0:
                            reason = critical_task_reason(
                                task,
                                priority_threshold=HITL_PRIORITY_THRESHOLD,
                            )
                            if reason:
                                auto_note = None
                                if HITL_AUTO_APPROVE_LOW_RISK:
                                    auto_note = low_risk_auto_approve_reason(
                                        task,
                                        reason=reason,
                                        max_priority=HITL_AUTO_APPROVE_MAX_PRIORITY,
                                        allow_gap_types=HITL_AUTO_APPROVE_GAP_TYPES,
                                    )
                                if auto_note:
                                    existing_interrupt = pending_interrupt_for_task(task_id)
                                    if existing_interrupt:
                                        interrupt_id = int(existing_interrupt.get("id", 0) or 0)
                                        approve_interrupt(
                                            interrupt_id,
                                            reviewer="daemon_auto",
                                            note=auto_note,
                                        )
                                    else:
                                        interrupt = create_interrupt(
                                            task=task,
                                            reason=reason,
                                            category="research_task",
                                            payload={
                                                "mode": "auto_approved_low_risk",
                                                "hint": (
                                                    "Auto-godkänd via låg-risk-policy. "
                                                    "Justera NOUSE_HITL_AUTO_APPROVE_* vid behov."
                                                ),
                                            },
                                        )
                                        interrupt_id = int(interrupt["id"])
                                        approve_interrupt(
                                            interrupt_id,
                                            reviewer="daemon_auto",
                                            note=auto_note,
                                        )
                                    approve_task_after_hitl(task_id, note=auto_note)
                                    curiosity_summary = {
                                        "status": "hitl_auto_approved",
                                        "task_id": task_id,
                                        "reason": reason,
                                        "note": auto_note,
                                    }
                                    log.info(
                                        "  HITL auto-approve för task #%d (%s)",
                                        task_id,
                                        auto_note,
                                    )
                                else:
                                    existing_interrupt = pending_interrupt_for_task(task_id)
                                    if existing_interrupt:
                                        curiosity_summary = {
                                            "status": "hitl_waiting_existing",
                                            "task_id": task_id,
                                            "reason": reason,
                                            "interrupt_id": int(existing_interrupt.get("id", 0) or 0),
                                        }
                                        log.info(
                                            "  HITL väntar redan för task #%d (interrupt #%s)",
                                            task_id,
                                            existing_interrupt.get("id", "?"),
                                        )
                                        pause_task_for_hitl(
                                            task_id,
                                            interrupt_id=int(existing_interrupt.get("id", 0) or 0),
                                            reason=f"HITL väntar: {reason}",
                                        )
                                    else:
                                        interrupt = create_interrupt(
                                            task=task,
                                            reason=reason,
                                            category="research_task",
                                            payload={
                                                "mode": "approve_resume",
                                                "hint": (
                                                    "Kör `b76 hitl status` och godkänn med "
                                                    "interrupt-id: `b76 hitl approve --id <interrupt_id>`."
                                                ),
                                            },
                                        )
                                        pause_task_for_hitl(
                                            task_id,
                                            interrupt_id=int(interrupt["id"]),
                                            reason=f"HITL krävs: {reason}",
                                        )
                                        curiosity_summary = {
                                            "status": "hitl_interrupt_created",
                                            "task_id": task_id,
                                            "reason": reason,
                                            "interrupt_id": int(interrupt["id"]),
                                        }
                                        log.warning(
                                            "  HITL interrupt #%d skapad för task #%d (%s)",
                                            int(interrupt["id"]),
                                            task_id,
                                            reason,
                                        )
                                task = None

                    if task:
                        curiosity_summary = {
                            "status": "task_claimed",
                            "task_id": int(task.get("id", -1) or -1),
                            "priority": float(task.get("priority", 0.0) or 0.0),
                            "domain": str(task.get("domain", "okänd")),
                        }
                        log.info(
                            f"  Curiosity task #{task['id']} "
                            f"(prio={task.get('priority', 0):.2f}, domän={task.get('domain','okänd')})"
                        )
                        burst_text = await run_curiosity_burst(field, limbic_state, task=task)
                        if not burst_text:
                            fail_task(int(task["id"]), "Ingen rapporttext producerades.")
                            curiosity_summary = {
                                "status": "task_failed_empty_report",
                                "task_id": int(task.get("id", -1) or -1),
                            }
                        else:
                            log.info("  Curiosity avslutat. Analyserar resulterande text...")
                            
                            # ── brain_sync: Metacognition Event (self-observation) ──────
                            if BRAIN_SYNC_ENABLED and BRAIN_TRANSPORTER:
                                try:
                                    meta = {"source": "curiosity_loop", "path": f"cykel_{cycle}"}
                                    # Skicka metacognition event för curiosity-aktivitet
                                    observation = f"curiosity_task_{task['id']}"
                                    evt = metacognition_event(
                                        observation_type="curiosity_loop",
                                        target=observation,
                                        lambda_delta=limbic_state.lam - (limbic_state.lam * 0.1),  # λ minskes något vid curiosity
                                    )
                                    BRAIN_TRANSPORTER.send(evt)
                                except Exception:
                                    pass
                            
                            try:
                                meta = {"source": "curiosity_loop", "path": f"cykel_{cycle}"}
                                rels, _diag = await extract_relations_with_diagnostics(
                                    burst_text, meta
                                )
                                async def _write_curiosity_rels() -> tuple[int, list[float], dict]:
                                    _scores: list[float] = []
                                    _tiers = {"hypotes": 0, "indikation": 0, "validerad": 0}
                                    _count = 0
                                    for r in rels:
                                        ass = assess_relation(r, task=task)
                                        _scores.append(ass.score)
                                        _tiers[ass.tier] = _tiers.get(ass.tier, 0) + 1
                                        field.add_concept(
                                            r["src"], r["domain_src"], source="curiosity"
                                        )
                                        field.add_concept(
                                            r["tgt"], r["domain_tgt"], source="curiosity"
                                        )
                                        field.add_relation(
                                            r["src"],
                                            r["type"],
                                            r["tgt"],
                                            why=format_why_with_evidence(r.get("why", ""), ass),
                                            strength=float(ass.score),
                                            source_tag=f"curiosity_loop:{ass.tier}",
                                            evidence_score=float(ass.score),
                                            assumption_flag=(ass.tier == "hypotes"),
                                            domain_src=r.get("domain_src", "okänd"),
                                            domain_tgt=r.get("domain_tgt", "okänd"),
                                        )
                                        LearningCoordinator(field, limbic_state).on_fact(
                                            r["src"], r["type"], r["tgt"],
                                            why=r.get("why", ""),
                                            evidence_score=float(ass.score),
                                            support_count=1,
                                        )
                                        stdp_bridge.on_fact(r["src"], r["type"], r["tgt"])
                                        inbox.add(
                                            r["src"], r["type"], r["tgt"],
                                            why=r.get("why", ""),
                                            evidence_score=float(r.get("evidence_score") or 0.35),
                                            source=f"curiosity:{ass.tier}",
                                            domain_src=r.get("domain_src", "okänd"),
                                            domain_tgt=r.get("domain_tgt", "okänd"),
                                        )
                                        _count += 1
                                    return _count, _scores, _tiers

                                added, evidence_scores, tier_counts = await enqueue_write(
                                    _write_curiosity_rels()
                                )

                                avg_evidence = (
                                    sum(evidence_scores) / len(evidence_scores)
                                    if evidence_scores
                                    else 0.0
                                )
                                max_evidence = max(evidence_scores) if evidence_scores else 0.0
                                complete_task(
                                    int(task["id"]),
                                    added_relations=added,
                                    report_chars=len(burst_text),
                                    avg_evidence=avg_evidence,
                                    max_evidence=max_evidence,
                                    tier_counts=tier_counts,
                                )
                                try:
                                    memory_store.ingest_episode(
                                        burst_text,
                                        {
                                            "source": "curiosity_loop",
                                            "path": f"task_{task['id']}",
                                            "domain_hint": task.get("domain", "okänd"),
                                        },
                                        rels,
                                    )
                                except Exception as e:
                                    log.warning(f"Memory ingest (curiosity) misslyckades: {e}")
                                new_rel += added
                                log.info(
                                    f"    Curiosity extraherade +{added} relationer "
                                    f"(evidence avg={avg_evidence:.3f}, max={max_evidence:.3f}, "
                                    f"tiers={tier_counts})"
                                )
                                curiosity_summary = {
                                    "status": "task_completed",
                                    "task_id": int(task.get("id", -1) or -1),
                                    "added_relations": added,
                                    "avg_evidence": round(avg_evidence, 4),
                                    "max_evidence": round(max_evidence, 4),
                                    "tier_counts": tier_counts,
                                }
                            except Exception as e:
                                fail_task(int(task["id"]), f"Extraktion misslyckades: {e}")
                                curiosity_summary = {
                                    "status": "task_failed_extraction",
                                    "task_id": int(task.get("id", -1) or -1),
                                    "error": str(e),
                                }
                                log.warning(
                                    f"  Gick inte att extrahera relationer från curiosity: {e}"
                                )
                except Exception as e:
                    curiosity_summary = {
                        "status": "queue_loop_error",
                        "error": str(e),
                    }
                    log.warning(f"  Curiosity queue-loop fel: {e}")

            _journal_stage(
                stage="curiosity_loop",
                thought=(
                    "Prioriterar luckor med högst nytta/risk-balans och kräver HITL när "
                    "osäkerhet eller konsekvens är hög."
                ),
                action="Körde mission-seeding, gap-queue, HITL-gate och curiosity-task.",
                result=f"Curiosity status={curiosity_summary.get('status', 'unknown')}.",
                details=curiosity_summary,
            )

            # ── 9: Konsolidera episodiskt minne till semantiskt minne ──────────
            if MEMORY_CONSOLIDATION_EVERY > 0 and cycle % MEMORY_CONSOLIDATION_EVERY == 0:
                try:
                    async def _consolidate_memory():
                        return memory_store.consolidate(
                            field,
                            max_episodes=MEMORY_CONSOLIDATION_BATCH,
                            strict_min_evidence=MEMORY_CONSOLIDATION_MIN_EVIDENCE,
                        )
                    cstats = await enqueue_write(_consolidate_memory())
                    
                    # ── brain_sync: Concept Crystallize Event ───────────────────
                    if BRAIN_SYNC_ENABLED and BRAIN_TRANSPORTER:
                        # Skicka begrepp som passerat evidens-gaten
                        # Vi antar att cstats innehåller info om vad som krystalliserats
                        consolidated = cstats.get("consolidated_relations", 0) or 0
                        if consolidated > 0:
                            # Skicka ett representativt event för varje konsoliderad relation
                            # För enkelhet skickar vi ett event per 10 relationer för att undvika spam
                            if consolidated % 10 == 0:
                                # Skicka ett event för "genomsnittliga" faktatäthet
                                avg_evidence = 0.85  # Fallback, börjas från memory_store
                                for i in range(consolidated // 10):
                                    evt = concept_crystallize_event(
                                        concept_name="konsoliderad_fakt",
                                        domain="minne",
                                        evidence_score=avg_evidence,
                                        relation_strength=0.7,
                                    )
                                    BRAIN_TRANSPORTER.send(evt)
                    
                    log.info(
                        "  Memory consolidate: "
                        f"eps={cstats.get('processed_episodes', 0)} "
                        f"rels={cstats.get('consolidated_relations', 0)} "
                        f"facts={cstats.get('semantic_facts_after', 0)} "
                        f"uncon={cstats.get('unconsolidated_after', 0)}"
                    )
                except Exception as e:
                    log.warning(f"  Memory consolidation misslyckades: {e}")

            # ── 10: Knowledge backfill (säkrar kontext + fakta per nod) ────────
            if KNOWLEDGE_BACKFILL_EVERY > 0 and cycle % KNOWLEDGE_BACKFILL_EVERY == 0:
                try:
                    async def _backfill_knowledge():
                        return field.backfill_missing_concept_knowledge(
                            limit=KNOWLEDGE_BACKFILL_LIMIT,
                            strict=True,
                            min_evidence_score=KNOWLEDGE_BACKFILL_MIN_EVIDENCE,
                        )
                    backfill = await enqueue_write(_backfill_knowledge())
                    after = backfill.get("after") or {}
                    log.info(
                        "  Knowledge backfill: "
                        f"updated={int(backfill.get('updated', 0) or 0)} "
                        f"requested={int(backfill.get('requested', 0) or 0)} "
                        f"remaining={int(after.get('missing_total', 0) or 0)}"
                    )
                except Exception as e:
                    log.warning(f"  Knowledge backfill misslyckades: {e}")

            # ── 11: Morning Report (vid stora cykler) ──────────────────────────
            if cycle % 144 == 0 and not (stop_event and stop_event.is_set()):
                # ca en gång per dygn om loopen körs var 10:e minut (6 * 24)
                log.info("Genererar autonom Morning Report...")
                report = await generate_morning_report(field)
                report_path = Path.home() / ".local" / "share" / "nouse" / f"morning_report_{cycle}.md"
                try:
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    report_path.write_text(f"# B76 Morning Report (Cykel {cycle})\n\n{report}")
                    log.info(f"  Morning Report sparad till {report_path}")
                except Exception as e:
                    log.error(f"  Kunde inte spara Morning Report: {e}")

                try:
                    create_snapshot(field, tag="morning_report")
                except Exception as e:
                    log.error(f"  Kunde inte skapat forsknings-snapshot: {e}")

            # ── Status ─────────────────────────────────────────────────────────
            s = field.stats()
            log.info(
                f"Cykel {cycle}: +{new_rel} rel, {len(found)} nervbanor, "
                f"{len(candidates)} bisoc-kandidater, "
                f"{s['concepts']} noder, {s['relations']} kanter  "
                f"λ={limbic_state.lam:.2f}"
            )
            _write_status(s, limbic_state, cycle, len(found))
            qstats = {
                "pending": 0,
                "in_progress": 0,
                "awaiting_approval": 0,
                "done": 0,
                "failed": 0,
            }
            qtasks: list[dict] = []
            try:
                qstats = queue_stats()
                qtasks = peek_tasks(limit=3)
            except Exception as e:
                log.warning(f"  Queue status misslyckades: {e}")

            try:
                # Cerebellum: get procedural stats for empowerment signal
                procedural_stats = memory_store.get_procedural_stats()
                living_state = update_living_core(
                    cycle=cycle,
                    limbic=limbic_state,
                    graph_stats=s,
                    queue_stats=qstats,
                    session_stats=get_session_stats(),
                    new_relations=new_rel,
                    discoveries=len(found),
                    bisoc_candidates=len(candidates),
                    procedural_stats=procedural_stats,
                )
            except Exception as e:
                living_state = {}
                log.warning(f"  Living core update misslyckades: {e}")

            reflection = (
                (living_state.get("last_reflection") or {})
                if isinstance(living_state, dict)
                else {}
            )
            _journal_stage(
                stage="cycle_reflection",
                thought=str(reflection.get("thought") or "").strip(),
                action=(
                    "Uppdaterade living_core med homeostasis, drives och "
                    "session/queue-signaler."
                ),
                result=(
                    f"Cycle={cycle}, graph={s.get('concepts', 0)}/{s.get('relations', 0)}, "
                    f"new_rel={new_rel}, discoveries={len(found)}, bisoc={len(candidates)}."
                ),
                details={
                    "cycle": cycle,
                    "new_relations": new_rel,
                    "discoveries": len(found),
                    "bisoc_candidates": len(candidates),
                    "graph_concepts": int(s.get("concepts", 0) or 0),
                    "graph_relations": int(s.get("relations", 0) or 0),
                    "lambda": round(float(getattr(limbic_state, "lam", 0.0) or 0.0), 4),
                    "journal_trace_enabled": JOURNAL_TRACE_ENABLED,
                },
            )

            try:
                jpath = write_daily_brief(
                    cycle=cycle,
                    stats=s,
                    limbic=limbic_state,
                    new_relations=new_rel,
                    discoveries=len(found),
                    bisoc_candidates=len(candidates),
                    queue_stats=qstats,
                    queue_tasks=qtasks,
                    living_state=living_state,
                )
                log.info(f"  Journal uppdaterad: {jpath}")
            except Exception as e:
                log.warning(f"  Journal-skrivning misslyckades: {e}")

            if mission_state:
                coverage = None
                if cycle % MISSION_AUDIT_EVERY == 0:
                    try:
                        audit = field.knowledge_audit(
                            limit=1,
                            strict=True,
                            min_evidence_score=KNOWLEDGE_BACKFILL_MIN_EVIDENCE,
                        )
                        coverage = audit.get("coverage") if isinstance(audit, dict) else None
                    except Exception as e:
                        log.warning(f"  Mission-audit misslyckades: {e}")
                try:
                    append_cycle_metric(
                        mission=mission_state,
                        cycle=cycle,
                        graph_stats=s,
                        queue=qstats,
                        limbic={
                            "lambda": limbic_state.lam,
                            "arousal": limbic_state.arousal,
                            "dopamine": limbic_state.dopamine,
                            "noradrenaline": limbic_state.noradrenaline,
                        },
                        new_relations=new_rel,
                        discoveries=len(found),
                        bisoc_candidates=len(candidates),
                        knowledge_coverage=coverage,
                    )
                except Exception as e:
                    log.warning(f"  Mission-metric misslyckades: {e}")

            try:
                _save_source_throttle(source_throttle)
            except Exception as e:
                log.warning(f"  Kunde inte spara source-throttle-state: {e}")

            # ── NightRun: konsolidera inbox → FieldSurface ──────────────────────
            try:
                await nightrun.maybe_run(field, inbox, limbic_state)
            except Exception as e:
                log.warning(f"  NightRun misslyckades: {e}")

            sleep_reason = await _sleep_or_stop(
                LOOP_INTERVAL,
                stop_event,
                wake_event=wake_event,
            )
            if sleep_reason == "wake":
                log.info("Wake-trigger mottagen, startar ny cykel direkt.")
    except asyncio.CancelledError:
        log.info("Brain loop avbruten av event-loop.")
        raise
    finally:
        try:
            _save_source_throttle(source_throttle)
        except Exception:
            pass
        log.info("Brain loop stoppad.")


_STATUS_FILE = path_from_env("NOUSE_STATUS_FILE", "status.json")


def _write_status(stats: dict, limbic: "LimbicState", cycle: int, nervbanor: int) -> None:
    import json
    from datetime import datetime
    data = {
        "concepts":   stats["concepts"],
        "relations":  stats["relations"],
        "cycle":      cycle,
        "nervbanor":  nervbanor,
        "lambda":     round(limbic.lam, 3),
        "dopamine":   round(limbic.dopamine, 3),
        "noradrenaline": round(limbic.noradrenaline, 3),
        "arousal":    round(limbic.arousal, 3),
        "updated":    datetime.now().isoformat(),
    }
    _STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATUS_FILE.write_text(json.dumps(data, indent=2))


def _build_sources():
    out = []
    watch_paths = _resolve_watch_paths()

    # ── Filkällor ──────────────────────────────────────────────────────────
    for p in watch_paths:
        try:
            if not p.exists():
                continue
        except OSError:
            # Skippa paths på otillgängliga/trasiga mounts
            continue
        if "claude" in str(p) or "antigravity" in str(p):
            out.append(ConversationSource(p))
        else:
            out.append(FileSource(p, extensions=[".md", ".txt", ".py", ".pdf"]))

    # ── Laptop-integrationer ───────────────────────────────────────────────
    out.append(BashHistorySource())
    out.append(ChromeBookmarksSource())
    out.append(ChromeHistorySource(max_entries=50))
    out.append(CaptureQueueSource())   # manuell kö från `cap`-kommandot

    log.info("Watch paths: %s", ", ".join(str(p) for p in watch_paths[:10]) or "(none)")
    log.info(f"Källor: {len(out)} totalt")
    return out


def run(with_web: bool = False, web_port: int = 8765) -> None:
    field = FieldSurface()
    memory = MemoryStore()
    if with_web:
        asyncio.run(_run_with_web(field, memory, web_port))
    else:
        asyncio.run(_run_headless(field, memory))


async def _run_headless(field: FieldSurface, memory: MemoryStore) -> None:
    stop_event = asyncio.Event()
    wake_event = asyncio.Event()
    conductor = CognitiveConductor(memory=memory)
    autonomy = AutonomyLoop(conductor=conductor)
    bind_wake_event(wake_event)
    _install_signal_handlers(stop_event)

    # ── brain_sync: Initiera transporter vid headless-start ──────────────
    if BRAIN_SYNC_ENABLED:
        try:
            BRAIN_TRANSPORTER = BrainTransporter()
            log.info("  brain_sync: Headless startad, transporter aktiverad.")
        except Exception as e:
            log.warning(f"  brain_sync: Kunde inte initiera transporter vid start: {e}")

    start_worker()
    await autonomy.start()
    # Wrap brain_loop as a Task so we can cancel it on SIGTERM.
    # The old `await brain_loop(...)` blocked the entire shutdown path because
    # it was stuck inside sync graph traversal or LLM calls with no timeout.
    brain_task = asyncio.create_task(
        brain_loop(field, stop_event=stop_event, wake_event=wake_event, memory=memory)
    )
    stop_task = asyncio.create_task(stop_event.wait())
    try:
        _done, _pending = await asyncio.wait(
            {brain_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Always cancel whichever task didn't complete first
        for t in _pending:
            t.cancel()
        if not brain_task.done():
            # stop fired while brain_loop was running — give it 25s to clean up
            log.info("Stoppsignal — avbryter brain loop (max 25s)...")
            brain_task.cancel()
        # Wait max 25s regardless of task state (handles both sync-blocked and
        # CancelledError-swallowing code paths in brain_loop)
        _still_running = {t for t in _pending if not t.done()} | (
            {brain_task} if not brain_task.done() else set()
        )
        if _still_running:
            await asyncio.wait(_still_running, timeout=25.0)
        # Log if brain_task didn't exit cleanly
        if not brain_task.done():
            log.warning("Brain loop svarade inte på cancel inom 25s — ger upp.")
        elif not brain_task.cancelled():
            exc = brain_task.exception()
            if exc is not None:
                raise exc
    finally:
        stop_worker()
        if not brain_task.done():
            brain_task.cancel()
        await autonomy.stop()
        bind_wake_event(None)


async def _run_with_web(field: FieldSurface, memory: MemoryStore, port: int) -> None:
    """Kör brain_loop + web-server i samma event loop med delad FieldSurface."""
    import uvicorn
    from nouse.web.server import app, set_global_field, set_global_memory

    set_global_field(field)
    set_global_memory(memory)

    config    = uvicorn.Config(app, host="127.0.0.1", port=port,
                               log_level="warning", loop="asyncio")
    server    = uvicorn.Server(config)
    stop_event = asyncio.Event()
    wake_event = asyncio.Event()
    
    # ── brain_sync: Initiera transporter vid web-start ──────────────
    if BRAIN_SYNC_ENABLED:
        try:
            BRAIN_TRANSPORTER = BrainTransporter()
            log.info("  brain_sync: Web startad, transporter aktiverad.")
        except Exception as e:
            log.warning(f"  brain_sync: Kunde inte initiera transporter vid start: {e}")
    
    conductor = CognitiveConductor(memory=memory)
    autonomy = AutonomyLoop(conductor=conductor)
    bind_wake_event(wake_event)
    try:
        def _request_server_stop() -> None:
            server.should_exit = True

        _install_signal_handlers(stop_event, on_stop=_request_server_stop)
        await autonomy.start()

        brain_task = asyncio.create_task(
            brain_loop(field, stop_event=stop_event, wake_event=wake_event, memory=memory)
        )
        server_task = asyncio.create_task(server.serve())

        done, pending = await asyncio.wait(
            {brain_task, server_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        first_exc = None
        for task in done:
            if task.cancelled():
                continue
            err = task.exception()
            if err is not None:
                first_exc = err

        if not stop_event.is_set():
            stop_event.set()
        server.should_exit = True

        for task in pending:
            task.cancel()
        if pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=20.0,
                )
            except asyncio.TimeoutError:
                log.warning("Pending tasks svarade inte inom 20s under shutdown.")

        if first_exc is not None:
            raise first_exc
    finally:
        await autonomy.stop()
        bind_wake_event(None)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="NoUse daemon launcher")
    parser.add_argument(
        "action",
        nargs="?",
        default="start",
        choices=["start", "web"],
        help="start=headless, web=daemon+web UI",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8765,
        help="Webb-port vid action=web",
    )
    args = parser.parse_args()

    run(with_web=(args.action == "web"), web_port=int(args.port))


if __name__ == "__main__":
    main()
