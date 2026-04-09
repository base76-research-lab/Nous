import asyncio
import json
import logging
import os
import re
import threading
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from nouse.field.surface import FieldSurface
from nouse.limbic.signals import load_state
from nouse.memory.store import MemoryStore
from nouse.ollama_client.client import AsyncOllama
from nouse.llm.model_capabilities import (
    filter_tool_capable_models,
    is_tools_unsupported_error,
    mark_model_tools_supported,
    mark_model_tools_unsupported,
)
from nouse.llm.model_router import order_models_for_workload, record_model_result
from nouse.llm.policy import get_workload_policy, resolve_model_candidates
from nouse.llm.usage import list_usage, usage_summary
from nouse.self_layer import (
    append_identity_memory,
    identity_prompt_fragment,
    load_living_core,
    record_self_training_iteration,
)

MODEL = (
    os.getenv("NOUSE_CHAT_MODEL")
    or os.getenv("NOUSE_OLLAMA_MODEL")
    or "qwen3.5:latest"
).strip()
CHAT_FALLBACK_MODEL = (os.getenv("NOUSE_CHAT_FALLBACK_MODEL") or "").strip()
CHAT_CANDIDATES_RAW = (os.getenv("NOUSE_MODEL_CANDIDATES_CHAT") or "").strip()
FAST_CHAT_MODEL = (os.getenv("NOUSE_CHAT_FAST_MODEL") or MODEL).strip()
FAST_DELEGATE_ENABLED = str(os.getenv("NOUSE_CHAT_FAST_DELEGATE", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
FAST_DELEGATE_MIN_WORDS = max(8, int(os.getenv("NOUSE_CHAT_FAST_DELEGATE_MIN_WORDS", "18")))
INGEST_TIMEOUT_SEC = float(os.getenv("NOUSE_INGEST_TIMEOUT_SEC", "20"))
CAPTURE_QUEUE_DIR = Path.home() / ".local" / "share" / "nouse" / "capture_queue"
GRAPH_CENTER_STATE_PATH = Path(
    os.getenv(
        "NOUSE_GRAPH_CENTER_PATH",
        str(Path.home() / ".local" / "share" / "nouse" / "graph_center.json"),
    )
).expanduser()
QUEUE_DEFAULT_TASK_TIMEOUT_SEC = float(os.getenv("NOUSE_RESEARCH_QUEUE_TASK_TIMEOUT_SEC", "180"))
QUEUE_DEFAULT_EXTRACT_TIMEOUT_SEC = float(os.getenv("NOUSE_RESEARCH_QUEUE_EXTRACT_TIMEOUT_SEC", "30"))
from nouse.daemon.main import brain_loop
from nouse.daemon.journal import latest_journal_file
from nouse.cli.chat import get_live_tools, execute_tool, CHAT_MODEL
from nouse.metacognition.snapshot import create_snapshot
from nouse.daemon.extractor import extract_relations, extract_relations_with_diagnostics
from nouse.daemon.auto_skill import AutoSkillPolicy, evaluate_claim
from nouse.daemon.evidence import assess_relation, format_why_with_evidence
from nouse.daemon.initiative import run_curiosity_burst
from nouse.daemon.hitl import (
    approve_interrupt,
    interrupt_stats,
    list_interrupts,
    reject_interrupt,
)
from nouse.daemon.lock import BrainLock
from nouse.daemon.mission import load_mission, read_recent_metrics, save_mission
from nouse.daemon.research_queue import (
    claim_next_task,
    complete_task,
    enqueue_gap_tasks,
    fail_task,
    list_tasks,
    peek_tasks,
    queue_stats,
    retry_failed_tasks,
    approve_task_after_hitl,
    reject_task_after_hitl,
)
from nouse.daemon.kickstart import run_kickstart_bootstrap
from nouse.daemon.system_events import (
    bind_wake_event,
    enqueue_system_event,
    peek_system_event_entries,
    peek_wake_reasons,
    request_wake,
    system_event_stats,
)
from nouse.trace.output_trace import (
    build_attack_plan,
    derive_assumptions,
    load_events,
    new_trace_id,
    record_event,
)
from nouse.session import (
    cancel_active_run,
    ensure_session,
    finish_run,
    list_runs,
    list_sessions,
    session_stats,
    set_energy,
    start_run,
)
from nouse.ingress.clawbot import (
    approve_clawbot_pairing,
    get_clawbot_allowlist,
    ingest_clawbot_event,
)
from nouse.orchestrator.conductor import CognitiveConductor

log = logging.getLogger("nouse.web")

_CHOICE_LOCK = threading.Lock()
_SESSION_NUMERIC_CHOICES: dict[str, dict[int, str]] = {}


def _split_models(raw: str) -> list[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()]


def _chat_model_candidates() -> list[str]:
    defaults: list[str] = []
    defaults.extend(_split_models(CHAT_CANDIDATES_RAW))
    defaults.append(MODEL)
    if CHAT_FALLBACK_MODEL:
        defaults.append(CHAT_FALLBACK_MODEL)
    defaults = resolve_model_candidates("chat", defaults)
    return order_models_for_workload("chat", defaults)


def _living_prompt_block() -> str:
    try:
        state = load_living_core()
    except Exception:
        state = {}
    return identity_prompt_fragment(state)


def _remember_exchange(
    *,
    session_id: str,
    run_id: str,
    query: str,
    answer: str,
    kind: str = "chat_turn",
    known_data_sources: list[str] | None = None,
) -> None:
    if not answer:
        return
    snippet = (
        f"session={session_id} query={str(query or '').strip()[:220]} "
        f"answer={str(answer or '').strip()[:280]}"
    )
    try:
        append_identity_memory(
            snippet,
            tags=["dialogue", "session_memory", kind],
            session_id=session_id,
            run_id=run_id,
            kind=kind,
        )
        assumptions = derive_assumptions(answer)
        meta_reflection = (
            "assumptions="
            + (
                ", ".join(str(x).strip() for x in assumptions[:6] if str(x).strip())
                if assumptions
                else "(none)"
            )
        )
        reflection = str(answer or "").strip()[:420]
        record_self_training_iteration(
            known_data_sources=list(known_data_sources or ["conversation"]),
            meta_reflection=meta_reflection,
            reflection=reflection,
            session_id=session_id,
            run_id=run_id,
        )
    except Exception:
        pass


def _ingest_dialogue_memory(
    *,
    session_id: str,
    query: str,
    answer: str,
    source: str,
) -> None:
    clean_query = str(query or "").strip()
    clean_answer = str(answer or "").strip()
    if not clean_query and not clean_answer:
        return
    text = f"Fraga: {clean_query}\nSvar: {clean_answer}".strip()
    try:
        get_memory().ingest_episode(
            text,
            {
                "source": source,
                "path": source,
                "domain_hint": "dialog",
                "session_id": session_id,
            },
            [],
        )
    except Exception as e:
        log.warning("Dialog-minne kunde inte lagras (source=%s): %s", source, e)


def _working_memory_context(limit: int = 8) -> str:
    try:
        rows = get_memory().working_snapshot(limit=max(1, int(limit)))
    except Exception:
        return ""
    lines: list[str] = []
    for row in rows:
        summary = str(row.get("summary") or "").strip()
        if not summary:
            continue
        source = str(row.get("source") or "unknown").strip() or "unknown"
        lines.append(f"- [{source}] {summary}")
    return "\n".join(lines)


def _extract_numbered_options(text: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = re.match(r"^(?:[-*•]\s*)?(\d{1,2})(?:[.):]?)\s+(.+)$", line)
        if not m:
            continue
        try:
            idx = int(m.group(1))
        except ValueError:
            continue
        if idx < 1 or idx > 99:
            continue
        label = re.sub(r"\s+", " ", (m.group(2) or "").strip())
        if not label:
            continue
        out[idx] = label[:500]
    return out


def _remember_numbered_options(session_id: str, answer: str) -> None:
    sid = str(session_id or "").strip() or "main"
    parsed = _extract_numbered_options(answer)
    if not parsed:
        return
    with _CHOICE_LOCK:
        _SESSION_NUMERIC_CHOICES[sid] = parsed
        # Enkel minnesspärr för att undvika obegränsad tillväxt.
        if len(_SESSION_NUMERIC_CHOICES) > 300:
            for key in list(_SESSION_NUMERIC_CHOICES.keys())[:50]:
                _SESSION_NUMERIC_CHOICES.pop(key, None)


def _resolve_numeric_choice(session_id: str, query: str) -> tuple[str, int | None]:
    """
    Deterministisk tolkning av numeriska svar:
    - "1" -> senaste alternativ #1 i sessionen
    - "1 text..." -> "text..." (prioriterar explicit användartext)
    """
    raw = str(query or "").strip()
    m = re.match(r"^(\d{1,2})(?:[.):]?)\s*(.*)$", raw)
    if not m:
        return query, None
    try:
        choice_idx = int(m.group(1))
    except ValueError:
        return query, None
    tail = str(m.group(2) or "").strip()
    if tail:
        return tail, choice_idx
    sid = str(session_id or "").strip() or "main"
    with _CHOICE_LOCK:
        options = dict(_SESSION_NUMERIC_CHOICES.get(sid) or {})
    chosen = str(options.get(choice_idx) or "").strip()
    if chosen:
        return chosen, choice_idx
    # Fallback som ändå gör valet explicit för modellen.
    return (
        f"Jag väljer alternativ {choice_idx} från din senaste numrerade lista. Utför det.",
        choice_idx,
    )


_AGENT_IDENTITY_POLICY = (
    "Operativ identitetspolicy:\n"
    "- Du är B76: en autonom programagent i detta system (inte en fristående mänsklig entitet).\n"
    "- Du har operativ autonomi via tillgängliga verktyg, sessioner, daemon-loop och grafminne.\n"
    "- Påstå inte att du saknar systemåtkomst i denna miljö.\n"
    "- Om något är begränsat, beskriv konkreta tekniska begränsningar istället för generisk disclaimer.\n"
    "- Undvik långa listor om vad du 'inte kan'; ge nästa möjliga steg direkt.\n"
    "- När användaren beskriver en plan/implementation, svara samarbetsinriktat och handlingsbart.\n"
    "- Skilj mellan fakta, antaganden och policygränser på ett tydligt sätt.\n"
    "- Om användaren ber om utförande (t.ex. 'gör det', 'lägg in', 'skapa nod') ska du agera direkt.\n"
    "- Om användaren svarar med enbart en siffra (1-9), tolka som val av senaste numrerade alternativ.\n"
)


def _live_tool_inventory_block(max_items: int = 80) -> str:
    """Kort, verklighetsbaserad verktygsöversikt från aktuell runtime."""
    try:
        tools = get_live_tools()
    except Exception:
        tools = []
    rows: list[str] = []
    for tool in tools:
        fn = ((tool or {}).get("function") or {})
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        desc = " ".join(str(fn.get("description") or "").split())
        if desc:
            rows.append(f"- {name}: {desc[:180]}")
        else:
            rows.append(f"- {name}")
        if len(rows) >= max_items:
            break
    return "\n".join(rows) if rows else "(Inga verktyg laddade)"

def set_global_field(field: FieldSurface) -> None:
    """Injicera ett redan öppet FieldSurface-objekt (från daemon-processen)."""
    global _global_field
    _global_field = field


def set_global_memory(memory: MemoryStore) -> None:
    """Injicera ett delat MemoryStore-objekt (från daemon-processen)."""
    global _global_memory
    _global_memory = memory


@asynccontextmanager
async def lifespan(app: FastAPI):
    from nouse.daemon.write_queue import start_worker, stop_worker
    start_worker()
    global _global_field, _global_memory
    if _global_field is None:
        # Standalone-läge: ingen daemon delar sin field — öppna eget + kör brain_loop
        _global_field = FieldSurface(read_only=False)
        _global_memory = _global_memory or MemoryStore()
        wake_event = asyncio.Event()
        bind_wake_event(wake_event)
        bg_task = asyncio.create_task(
            brain_loop(_global_field, memory=_global_memory, wake_event=wake_event)
        )
        yield
        bg_task.cancel()
        bind_wake_event(None)
    else:
        # Inbäddat läge: daemon injicerade sin field via set_global_field()
        yield
    stop_worker()

app = FastAPI(title="b76 Dashboard", lifespan=lifespan)

# Global dependencies
_global_field = None
_global_memory: MemoryStore | None = None
_queue_jobs: dict[str, dict[str, Any]] = {}

def get_field():
    global _global_field
    return _global_field


def get_memory() -> MemoryStore:
    global _global_memory
    if _global_memory is None:
        _global_memory = MemoryStore()
    return _global_memory

frontend_dir = Path(__file__).parent / "static"
frontend_dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    index_html = frontend_dir / "index.html"
    return HTMLResponse(
        content=index_html.read_text("utf-8"),
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )

@app.get("/api/status")
def get_status():
    """Graf-stats + limbic — används av `b76 daemon status` och `b76 chat`."""
    from nouse.daemon.write_queue import queue_stats as _wq_stats
    field = get_field()
    s     = field.stats()
    ls    = load_state()
    return {
        "concepts":      s["concepts"],
        "relations":     s["relations"],
        "domains":       sorted(field.domains()),
        "lambda":        round(ls.lam, 3),
        "dopamine":      round(ls.dopamine, 3),
        "noradrenaline": round(ls.noradrenaline, 3),
        "arousal":       round(ls.arousal, 3),
        "cycle":         ls.cycle,
        "sessions":      session_stats(),
        "system_events": system_event_stats(),
        "write_queue":   _wq_stats(),
    }


@app.get("/api/write-queue/stats")
def get_write_queue_stats():
    """Skriv-kö — djup, genomströmning, max väntetid."""
    from nouse.daemon.write_queue import queue_stats as _wq_stats
    return _wq_stats()


@app.get("/api/nerv")
def get_nerv(domain_a: str, domain_b: str, max_hops: int = 8):
    """Hitta nervbana mellan två domäner."""
    field = get_field()
    path  = field.find_path(domain_a, domain_b, max_hops=max_hops)
    if not path:
        return {"found": False}
    return {
        "found":   True,
        "novelty": field.path_novelty(path),
        "hops":    len(path),
        "path":    [{"from": s, "rel": r, "to": t} for s, r, t in path],
    }


@app.get("/api/bisoc")
def get_bisoc(tau: float = 0.55, epsilon: float = 2.0, max_domains: int = 50):
    """Bisociationskandidater via TDA."""
    field = get_field()
    candidates = field.bisociation_candidates(
        tau_threshold=tau, max_epsilon=epsilon, max_domains=max_domains
    )
    return {"candidates": candidates}


@app.get("/api/limbic")
def get_limbic():
    state = load_state()
    return {
        "dopamine": state.dopamine,
        "noradrenaline": state.noradrenaline,
        "acetylcholine": state.acetylcholine,
        "arousal": state.arousal,
        "lambda": state.lam,
        "cycle": state.cycle,
        "performance": state.performance,
        "pruning": state.pruning_aggression
    }

class SnapshotRequest(BaseModel):
    tag: str = "web_manual"

@app.post("/api/snapshot")
def trigger_snapshot(req: SnapshotRequest):
    """Triggar en manuell graf-backup / snapshot för forskning."""
    try:
        field = get_field()
        path = create_snapshot(field, tag=req.tag)
        return {"status": "success", "path": str(path)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        iv = int(value)
    except (TypeError, ValueError):
        iv = default
    return max(minimum, min(maximum, iv))


def _coerce_float(value: Any, *, default: float) -> float:
    try:
        fv = float(value)
        if fv != fv:  # NaN guard
            return default
        return fv
    except (TypeError, ValueError):
        return default


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return text


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", _coerce_text(value))).strip()


def _graph_center_path() -> Path:
    return GRAPH_CENTER_STATE_PATH


def _load_graph_center_state() -> dict[str, Any]:
    path = _graph_center_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    node = _norm_text(raw.get("node"))
    if not node:
        return {}
    return {
        "node": node,
        "updated_at": _coerce_text(raw.get("updated_at")),
        "source": _coerce_text(raw.get("source")) or "api",
    }


def _save_graph_center_state(node: str, *, source: str = "api") -> dict[str, Any]:
    clean_node = _norm_text(node)
    if not clean_node:
        raise ValueError("node saknas")
    payload = {
        "node": clean_node,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": _coerce_text(source) or "api",
    }
    path = _graph_center_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _clear_graph_center_state() -> bool:
    path = _graph_center_path()
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except Exception:
        return False


def _resolve_node_id_in_rows(rows: list[dict[str, Any]], wanted: str) -> str:
    clean = _norm_text(wanted)
    if not clean:
        return ""
    for row in rows:
        node_id = _coerce_text(row.get("id"))
        if node_id == clean:
            return node_id
    wanted_cf = clean.casefold()
    for row in rows:
        node_id = _coerce_text(row.get("id"))
        if node_id.casefold() == wanted_cf:
            return node_id
    return ""


def _resolve_graph_center_node(field: FieldSurface, wanted: str) -> tuple[str, bool]:
    clean = _norm_text(wanted)
    if not clean:
        return "", False

    concept_domain = getattr(field, "concept_domain", None)
    if callable(concept_domain):
        try:
            dom = concept_domain(clean)
        except Exception:
            dom = None
        if dom:
            return clean, True

    try:
        rows = field.concepts()
    except Exception:
        return clean, False

    for row in rows:
        name = _coerce_text((row or {}).get("name"))
        if name == clean:
            return name, True

    clean_cf = clean.casefold()
    for row in rows:
        name = _coerce_text((row or {}).get("name"))
        if name.casefold() == clean_cf:
            return name, True
    return clean, False


def _edge_uid(src: str, rel_type: str, tgt: str, dup_index: int = 1) -> str:
    base = f"{src}::{rel_type}::{tgt}"
    return base if dup_index <= 1 else f"{base}::{dup_index}"


def _graph_rows(
    *,
    limit_nodes: int,
    limit_edges: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    field = get_field()
    safe_nodes = _coerce_int(limit_nodes, default=500, minimum=10, maximum=20000)
    safe_edges = _coerce_int(limit_edges, default=safe_nodes * 2, minimum=10, maximum=60000)

    nodes_raw = field.get_concepts_with_metadata(safe_nodes)
    nodes: list[dict[str, Any]] = []
    for row in nodes_raw:
        node_id = _coerce_text(row.get("id"))
        if not node_id:
            continue
        nodes.append(
            {
                "id": node_id,
                "label": node_id,
                "group": (_coerce_text(row.get("dom")) or "unknown"),
                "source": _coerce_text(row.get("source")),
                "created": _coerce_text(row.get("created")),
            }
        )

    if not nodes:
        return [], []

    edges_raw = field.query_all_relations_with_metadata(safe_edges, include_evidence=True)

    node_ids = {n["id"] for n in nodes}
    edges: list[dict[str, Any]] = []
    dedupe: dict[str, int] = {}
    for row in edges_raw:
        src = _coerce_text(row.get("src"))
        tgt = _coerce_text(row.get("tgt"))
        rel = _coerce_text(row.get("rel")) or "related_to"
        if not src or not tgt:
            continue
        if src not in node_ids or tgt not in node_ids:
            continue
        base = f"{src}::{rel}::{tgt}"
        dedupe[base] = dedupe.get(base, 0) + 1
        edge_id = _edge_uid(src, rel, tgt, dedupe[base])
        edges.append(
            {
                "id": edge_id,
                "from": src,
                "to": tgt,
                "label": rel,
                "value": _coerce_float(row.get("strength"), default=1.0),
                "created": _coerce_text(row.get("created")),
                "evidence_score": _coerce_float(row.get("evidence_score"), default=0.0),
            }
        )
    return nodes, edges


def _graph_activity(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    activity_window: int,
) -> dict[str, Any]:
    safe_window = _coerce_int(activity_window, default=24, minimum=1, maximum=200)
    if not nodes or not edges:
        return {
            "active_nodes": [],
            "active_edges": [],
            "hot_domains": [],
            "window": safe_window,
        }

    scored: list[dict[str, Any]] = []
    for edge in edges:
        created = _coerce_text(edge.get("created"))
        scored.append(
            {
                "edge": edge,
                "score": (
                    1 if created else 0,
                    created,
                    _coerce_float(edge.get("value"), default=0.0),
                ),
            }
        )
    scored.sort(key=lambda row: row["score"], reverse=True)
    active_rows = scored[:safe_window]

    active_edges: list[str] = []
    active_nodes: set[str] = set()
    for row in active_rows:
        edge = row["edge"]
        active_edges.append(str(edge.get("id") or ""))
        active_nodes.add(str(edge.get("from") or ""))
        active_nodes.add(str(edge.get("to") or ""))

    node_by_id = {str(n.get("id")): n for n in nodes}
    domain_counts: dict[str, int] = {}
    for node_id in active_nodes:
        dom = _coerce_text(node_by_id.get(node_id, {}).get("group")) or "unknown"
        domain_counts[dom] = domain_counts.get(dom, 0) + 1

    hot_domains = [
        {"domain": dom, "count": cnt}
        for dom, cnt in sorted(
            domain_counts.items(),
            key=lambda it: (it[1], it[0]),
            reverse=True,
        )[:8]
    ]

    return {
        "active_nodes": sorted(x for x in active_nodes if x),
        "active_edges": [x for x in active_edges if x],
        "hot_domains": hot_domains,
        "window": safe_window,
    }


def _graph_payload(
    *,
    limit_nodes: int,
    limit_edges: int,
    activity_window: int,
) -> dict[str, Any]:
    field = get_field()
    nodes, edges = _graph_rows(limit_nodes=limit_nodes, limit_edges=limit_edges)
    center_state = _load_graph_center_state()
    center_node = _resolve_node_id_in_rows(nodes, center_state.get("node") or "")
    configured_center = _norm_text(center_state.get("node"))
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": field.stats(),
        "activity": _graph_activity(nodes, edges, activity_window=activity_window),
        "center": {
            "configured": bool(configured_center),
            "node": center_node or (configured_center or None),
            "in_view": bool(center_node),
            "updated_at": _coerce_text(center_state.get("updated_at")),
            "source": _coerce_text(center_state.get("source")) or "api",
        },
    }


def _latest_journal_entries(limit: int = 10) -> dict[str, Any]:
    safe_limit = _coerce_int(limit, default=10, minimum=1, maximum=2000)
    path = latest_journal_file()
    if path is None or not path.exists():
        return {"ok": True, "path": None, "count": 0, "entries": []}

    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("- ")]
    if not starts:
        return {"ok": True, "path": str(path), "count": 0, "entries": []}

    blocks: list[dict[str, Any]] = []
    header_re = re.compile(r"^- (?P<ts>\d{2}:\d{2}:\d{2}) UTC · cycle=(?P<cycle>\d+) · stage=(?P<stage>.+)$")
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        block_lines = lines[start:end]
        if not block_lines:
            continue
        header = block_lines[0].strip()
        m = header_re.match(header)
        thought = ""
        action = ""
        result = ""
        details = ""
        for raw in block_lines[1:]:
            row = raw.strip()
            if row.startswith("Thought:"):
                thought = row.replace("Thought:", "", 1).strip()
            elif row.startswith("Action:"):
                action = row.replace("Action:", "", 1).strip()
            elif row.startswith("Result:"):
                result = row.replace("Result:", "", 1).strip()
            elif row.startswith("Details:"):
                details = row.replace("Details:", "", 1).strip()
        blocks.append(
            {
                "raw": "\n".join(block_lines).strip(),
                "ts": m.group("ts") if m else "",
                "cycle": int(m.group("cycle")) if m else None,
                "stage": _norm_text(m.group("stage")) if m else "",
                "thought": thought,
                "action": action,
                "result": result,
                "details": details,
            }
        )

    latest = list(reversed(blocks))[:safe_limit]
    return {
        "ok": True,
        "path": str(path),
        "count": len(latest),
        "entries": latest,
    }


def _search_latest_journal(query: str, limit: int = 8) -> dict[str, Any]:
    payload = _latest_journal_entries(limit=400)
    if not payload.get("ok"):
        return payload
    entries = payload.get("entries") or []
    needle = _norm_text(query).casefold()
    safe_limit = _coerce_int(limit, default=8, minimum=1, maximum=50)
    if needle:
        entries = [
            row for row in entries
            if needle in _norm_text(row.get("raw")).casefold()
        ]
    trimmed = entries[:safe_limit]
    return {
        "ok": True,
        "path": payload.get("path"),
        "query": query,
        "count": len(trimmed),
        "entries": trimmed,
    }


class GraphCenterRequest(BaseModel):
    node: str


@app.get("/api/graph/cc")
def get_graph_center():
    state = _load_graph_center_state()
    configured = bool(_norm_text(state.get("node")))
    if not configured:
        return {
            "ok": True,
            "configured": False,
            "node": None,
            "exists": False,
            "updated_at": "",
            "source": "",
            "path": str(_graph_center_path()),
        }

    field = get_field()
    resolved, exists = _resolve_graph_center_node(field, state.get("node") or "")
    return {
        "ok": True,
        "configured": True,
        "node": resolved,
        "exists": bool(exists),
        "updated_at": _coerce_text(state.get("updated_at")),
        "source": _coerce_text(state.get("source")) or "api",
        "path": str(_graph_center_path()),
    }


@app.post("/api/graph/cc")
def set_graph_center(req: GraphCenterRequest):
    wanted = _norm_text(req.node)
    if not wanted:
        return {"ok": False, "error": "node saknas"}
    field = get_field()
    resolved, exists = _resolve_graph_center_node(field, wanted)
    if not exists:
        return {"ok": False, "error": f"Node '{wanted}' hittades inte i grafen."}
    payload = _save_graph_center_state(resolved, source="api")
    return {
        "ok": True,
        "configured": True,
        "node": resolved,
        "exists": True,
        "updated_at": _coerce_text(payload.get("updated_at")),
        "source": _coerce_text(payload.get("source")) or "api",
    }


@app.delete("/api/graph/cc")
def clear_graph_center():
    removed = _clear_graph_center_state()
    return {"ok": True, "cleared": bool(removed)}


@app.get("/api/graph")
def get_graph(
    limit: int = 500,
    edge_limit: int | None = None,
    activity_window: int = 24,
):
    """Hämta nätverksgraf + aktivitetslager för realtime-vyn."""
    safe_nodes = _coerce_int(limit, default=500, minimum=10, maximum=20000)
    safe_edges = _coerce_int(
        edge_limit if edge_limit is not None else (safe_nodes * 2),
        default=safe_nodes * 2,
        minimum=10,
        maximum=60000,
    )
    return _graph_payload(
        limit_nodes=safe_nodes,
        limit_edges=safe_edges,
        activity_window=activity_window,
    )


@app.get("/api/graph/focus")
def get_graph_focus(
    node_id: str,
    hops: int = 2,
    limit: int = 2000,
    edge_limit: int = 8000,
    activity_window: int = 20,
    journal_limit: int = 8,
):
    """Lokal subgraf kring en nod + journalträffar för fokusläge i UI."""
    safe_hops = _coerce_int(hops, default=2, minimum=1, maximum=5)
    payload = _graph_payload(
        limit_nodes=limit,
        limit_edges=edge_limit,
        activity_window=activity_window,
    )
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    wanted = _norm_text(node_id)
    if not wanted:
        return {"ok": False, "error": "node_id saknas."}

    resolved = ""
    for n in nodes:
        nid = _coerce_text(n.get("id"))
        if nid == wanted or nid.casefold() == wanted.casefold():
            resolved = nid
            break
    if not resolved:
        return {
            "ok": False,
            "error": f"Node '{wanted}' hittades inte i aktuell graf.",
            "query": wanted,
            "stats": payload.get("stats", {}),
            "nodes": [],
            "edges": [],
            "activity": payload.get("activity", {}),
            "journal": _search_latest_journal(wanted, limit=journal_limit),
        }

    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        src = _coerce_text(edge.get("from"))
        tgt = _coerce_text(edge.get("to"))
        if not src or not tgt:
            continue
        adjacency[src].add(tgt)
        adjacency[tgt].add(src)

    visited: set[str] = {resolved}
    frontier: set[str] = {resolved}
    for _ in range(safe_hops):
        nxt: set[str] = set()
        for node in frontier:
            nxt.update(adjacency.get(node, set()))
        nxt -= visited
        if not nxt:
            break
        visited |= nxt
        frontier = nxt

    focus_nodes = [n for n in nodes if _coerce_text(n.get("id")) in visited]
    focus_ids = {_coerce_text(n.get("id")) for n in focus_nodes}
    focus_edges = [
        e for e in edges
        if _coerce_text(e.get("from")) in focus_ids and _coerce_text(e.get("to")) in focus_ids
    ]

    return {
        "ok": True,
        "query": wanted,
        "center_node": resolved,
        "hops": safe_hops,
        "stats": payload.get("stats", {}),
        "nodes": focus_nodes,
        "edges": focus_edges,
        "activity": _graph_activity(
            focus_nodes,
            focus_edges,
            activity_window=min(activity_window, len(focus_edges) or 1),
        ),
        "journal": _search_latest_journal(resolved, limit=journal_limit),
    }


@app.get("/api/events")
async def graph_events_sse(request: Request):
    """
    Server-Sent Events — strömmar realtidshändelser från NoUse till browsern.

    Händelsetyper:
      heartbeat       — stats var 4:e sekund
      edge_added      — ny kant (src, rel, tgt, evidence_score)
      growth_probe    — axon growth cone startar
      synapse_formed  — growth cone skapade en korsdomän-koppling
      meta_axiom      — meta-axiom crystalliserat
    """
    from nouse.field.events import drain as _drain

    async def _generate():
        tick = 0
        while True:
            if await request.is_disconnected():
                break

            # Töm event-bussen
            events = _drain(max_events=50)
            for evt in events:
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

            # Heartbeat var 4:e sekund (8 × 0.5s)
            tick += 1
            if tick % 8 == 0:
                try:
                    f = get_field()
                    s = f.stats()
                    ls = load_state()
                    hb = {
                        "type": "heartbeat",
                        "ts": round(__import__("time").time() * 1000),
                        "concepts": s["concepts"],
                        "relations": s["relations"],
                        "cycle": ls.cycle,
                        "arousal": round(ls.arousal, 3),
                        "dopamine": round(ls.dopamine, 3),
                    }
                    yield f"data: {json.dumps(hb)}\n\n"
                except Exception:
                    pass

            await asyncio.sleep(0.5)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # inaktivera nginx-buffring
            "Connection": "keep-alive",
        },
    )


@app.get("/api/journal/search")
def get_journal_search(q: str = "", limit: int = 8):
    """Sök i senaste journalposter för fokusläge och snabb triage i cockpit."""
    return _search_latest_journal(q, limit=limit)


@app.get("/api/trace")
def get_trace(start: str, end: str, max_hops: int = 10, max_paths: int = 3):
    """Spåra resoneringskedjan med full metadata per hopp."""
    field   = get_field()
    results = field.trace_path(start, end, max_hops=max_hops, max_paths=max_paths)
    return {"found": bool(results), "paths": results}


@app.get("/api/trace/output")
def get_output_trace(trace_id: str | None = None, limit: int = 200):
    """Hämta output-trace events för hela systemet eller en specifik trace_id."""
    safe_limit = max(1, min(limit, 5000))
    events = load_events(limit=safe_limit, trace_id=trace_id)
    return {"trace_id": trace_id, "count": len(events), "events": events}


@app.get("/api/knowledge/audit")
def get_knowledge_audit(
    limit: int = 50,
    strict: bool = True,
    min_evidence_score: float = 0.65,
):
    """Visa hur många noder som har både kontext och fakta."""
    field = get_field()
    safe_limit = max(1, min(limit, 5000))
    return field.knowledge_audit(
        limit=safe_limit,
        strict=bool(strict),
        min_evidence_score=float(min_evidence_score),
    )


@app.get("/api/memory/audit")
def get_memory_audit(limit: int = 20):
    safe_limit = max(1, min(limit, 5000))
    memory = get_memory()
    return memory.audit(limit=safe_limit)


@app.post("/api/memory/consolidate")
def post_memory_consolidate(
    max_episodes: int = 40,
    strict_min_evidence: float = 0.65,
):
    field = get_field()
    memory = get_memory()
    safe_max = max(1, min(max_episodes, 5000))
    safe_min_ev = max(0.0, min(1.0, float(strict_min_evidence)))
    try:
        with BrainLock():
            result = memory.consolidate(
                field,
                max_episodes=safe_max,
                strict_min_evidence=safe_min_ev,
            )
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/knowledge/enrich")
async def post_knowledge_enrich(
    max_nodes: int = 50,
    max_minutes: float = 15.0,
    dry_run: bool = False,
):
    """Berika noder som saknar kontext med LLM (respekterar StorageTier)."""
    from nouse.daemon.node_context import enrich_nodes as _enrich
    from nouse.daemon.write_queue import enqueue_write
    field = get_field()
    async def _do():
        return await _enrich(
            field,
            max_nodes=max(1, min(max_nodes, 1000)),
            max_minutes=max(0.5, min(max_minutes, 120.0)),
            dry_run=bool(dry_run),
        )
    try:
        result = await enqueue_write(_do(), timeout=max_minutes * 60 + 30)
        return {
            "ok": True,
            "enriched": result.enriched,
            "skipped":  result.skipped,
            "failed":   result.failed,
            "duration": result.duration,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/nightrun/now")
async def post_nightrun_now(
    max_minutes: float = 60.0,
    dry_run: bool = False,
):
    """Kör NightRun-konsolidering manuellt (hippocampus → neocortex)."""
    from nouse.daemon.nightrun import run_night_consolidation
    from nouse.daemon.node_inbox import get_inbox
    from nouse.limbic.signals import load_state as _load_state
    from nouse.daemon.write_queue import enqueue_write
    field  = get_field()
    inbox  = get_inbox()
    limbic = _load_state()
    async def _do():
        return await run_night_consolidation(
            field, inbox, limbic,
            max_minutes=max(1.0, min(max_minutes, 120.0)),
            dry_run=bool(dry_run),
        )
    try:
        result = await enqueue_write(_do(), timeout=max_minutes * 60 + 30)
        return {
            "ok":                True,
            "consolidated":      result.consolidated,
            "discarded":         result.discarded,
            "bisociations":      result.bisociations,
            "pruned":            result.pruned,
            "enriched":          result.enriched,
            "axioms_committed":  result.axioms_committed,
            "axioms_flagged":    result.axioms_flagged,
            "reviews_promoted":  result.reviews_promoted,
            "reviews_discarded": result.reviews_discarded,
            "duration":          result.duration,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/knowledge/deepdive")
async def post_knowledge_deepdive(
    node: str | None = None,
    max_nodes: int = 5,
    max_minutes: float = 20.0,
    dry_run: bool = False,
    review_queue: bool = False,
):
    """
    Kör DeepDive axiom-discovery.
    node=None → batch på top-N noder.
    review_queue=True → töm ReviewQueue (indikerade granskningar).
    """
    from nouse.daemon.node_deepdive import (
        deepdive_node, deepdive_batch, get_review_queue
    )
    from nouse.daemon.write_queue import enqueue_write
    field = get_field()

    if review_queue:
        rq = get_review_queue()
        async def _do_review():
            return await rq.flush_pending(
                field,
                max_reviews=20,
                dry_run=bool(dry_run),
            )
        try:
            verdicts  = await enqueue_write(_do_review(), timeout=max_minutes * 60 + 30)
            promoted  = sum(1 for v in verdicts if v.outcome == "promote")
            discarded = sum(1 for v in verdicts if v.outcome == "discard")
            return {
                "ok": True, "mode": "review_queue",
                "total": len(verdicts),
                "promoted": promoted, "discarded": discarded,
                "kept": len(verdicts) - promoted - discarded,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if node:
        async def _do_node():
            return await deepdive_node(node, field, dry_run=bool(dry_run))
        try:
            result = await enqueue_write(_do_node(), timeout=max_minutes * 60 + 30)
            return {
                "ok": True, "mode": "node", "node": node,
                "llm_verified":    len(result.llm_verified),
                "llm_challenged":  len(result.llm_challenged),
                "web_new_facts":   len(result.web_new_facts),
                "contradictions":  len(result.contradictions),
                "shadow_nodes":    len(result.shadow_nodes),
                "axioms":          len(result.axiom_candidates),
                "committed":       result.committed,
                "flagged":         result.flagged,
                "duration":        result.duration,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _do_batch():
        return await deepdive_batch(
            field,
            max_nodes=max(1, min(max_nodes, 50)),
            max_minutes=max(1.0, min(max_minutes, 60.0)),
            dry_run=bool(dry_run),
        )
    try:
        batch = await enqueue_write(_do_batch(), timeout=max_minutes * 60 + 30)
        return {
            "ok": True, "mode": "batch",
            "nodes_processed": batch.nodes_processed,
            "committed":       batch.total_committed,
            "flagged":         batch.total_flagged,
            "duration":        batch.duration,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


class HitlDecisionRequest(BaseModel):
    id: int
    reviewer: str = "api"
    note: str = ""


@app.get("/api/hitl/interrupts")
def get_hitl_interrupts(
    status: str = "pending",
    limit: int = 20,
):
    """Lista HITL-interrupts för kontrollpanelen."""
    safe_limit = max(1, min(limit, 5000))
    filter_status = None if status == "all" else status
    return {
        "stats": interrupt_stats(),
        "interrupts": list_interrupts(status=filter_status, limit=safe_limit),
    }


@app.post("/api/hitl/approve")
def post_hitl_approve(req: HitlDecisionRequest):
    row = approve_interrupt(req.id, reviewer=req.reviewer, note=req.note)
    if not row:
        return {"ok": False, "error": f"Interrupt #{req.id} hittades inte."}
    task_id = int(row.get("task_id", -1) or -1)
    task = None
    if task_id > 0:
        task = approve_task_after_hitl(task_id, note=(req.note or "approved via api"))
    return {"ok": True, "interrupt": row, "task": task}


@app.post("/api/hitl/reject")
def post_hitl_reject(req: HitlDecisionRequest):
    row = reject_interrupt(req.id, reviewer=req.reviewer, note=req.note)
    if not row:
        return {"ok": False, "error": f"Interrupt #{req.id} hittades inte."}
    task_id = int(row.get("task_id", -1) or -1)
    task = None
    if task_id > 0:
        task = reject_task_after_hitl(task_id, reason=(req.note or "rejected via api"))
    return {"ok": True, "interrupt": row, "task": task}


class QueueScanRequest(BaseModel):
    max_new: int = 4


class QueueRetryRequest(BaseModel):
    limit: int = 5
    reason: str = "manuell retry via web"


class QueueRunRequest(BaseModel):
    count: int = 1
    task_timeout_sec: float = QUEUE_DEFAULT_TASK_TIMEOUT_SEC
    extract_timeout_sec: float = QUEUE_DEFAULT_EXTRACT_TIMEOUT_SEC
    extract_models: str = ""
    source: str = "web_queue"
    wait: bool = False


class KickstartRequest(BaseModel):
    session_id: str = "main"
    mission: str = ""
    focus_domains: str = ""
    repo_root: str = ""
    iic1_root: str = ""
    max_tasks: int = 8
    max_docs: int = 8
    source: str = "web_kickstart"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _calc_scorecard(limit: int = 30) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 365))
    mission = load_mission()
    metrics = read_recent_metrics(limit=safe_limit)
    q = queue_stats()
    done_rows = list_tasks(status="done", limit=250)

    processed = int(q.get("done", 0) or 0) + int(q.get("failed", 0) or 0)
    failed = int(q.get("failed", 0) or 0)
    failure_rate = failed / max(1, processed)
    stability = _clamp01(1.0 - failure_rate)

    evidence_values = [
        float(row.get("avg_evidence", 0.0) or 0.0)
        for row in done_rows
        if row.get("avg_evidence") is not None
    ]
    evidence = _clamp01(sum(evidence_values) / max(1, len(evidence_values)))

    discoveries = 0
    bisoc = 0
    for row in metrics:
        delta = row.get("delta") or {}
        discoveries += int(delta.get("discoveries", 0) or 0)
        bisoc += int(delta.get("bisoc_candidates", 0) or 0)
    novelty = _clamp01((discoveries + 0.25 * bisoc) / max(1.0, safe_limit * 140.0))

    pending = int(q.get("pending", 0) or 0)
    cooling = int(q.get("cooling_down", 0) or 0)
    awaiting = int(q.get("awaiting_approval", 0) or 0)
    queue_pressure = _clamp01((pending + cooling * 0.8 + awaiting * 1.2) / 25.0)
    queue_health = _clamp01(1.0 - queue_pressure - failure_rate * 0.5)

    overall = _clamp01(
        0.35 * stability
        + 0.25 * evidence
        + 0.20 * novelty
        + 0.20 * queue_health
    )

    return {
        "mission": mission,
        "overall": overall,
        "stability": stability,
        "evidence": evidence,
        "novelty": novelty,
        "queue_health": queue_health,
        "details": {
            "processed": processed,
            "failed": failed,
            "failure_rate": failure_rate,
            "pending": pending,
            "cooling_down": cooling,
            "awaiting_approval": awaiting,
            "discoveries_window": discoveries,
            "bisoc_window": bisoc,
            "metrics_rows": len(metrics),
            "done_with_evidence": len(evidence_values),
        },
    }


async def _run_one_queue_task(
    field: FieldSurface,
    *,
    source: str,
    task_timeout_sec: float,
    extract_timeout_sec: float,
    extract_models: list[str],
) -> dict[str, Any]:
    enqueue_gap_tasks(field, max_new=3)
    task = claim_next_task()
    if not task:
        return {"status": "empty"}

    task_id = int(task.get("id", -1) or -1)
    limbic = load_state()
    effective_task_timeout = max(0.0, float(task_timeout_sec))
    effective_extract_timeout = max(0.0, float(extract_timeout_sec))

    try:
        curiosity_coro = run_curiosity_burst(field, limbic, task=task)
        if effective_task_timeout > 0:
            text = await asyncio.wait_for(curiosity_coro, timeout=effective_task_timeout)
        else:
            text = await curiosity_coro
    except asyncio.TimeoutError:
        fail_task(task_id, f"Task-timeout efter {effective_task_timeout:.1f}s (curiosity)")
        return {"status": "failed", "task_id": task_id, "error": "curiosity_timeout"}
    except Exception as e:
        fail_task(task_id, f"Curiosity misslyckades: {e}")
        return {"status": "failed", "task_id": task_id, "error": str(e)}

    if not text:
        fail_task(task_id, "Ingen rapport producerades")
        return {"status": "failed", "task_id": task_id, "error": "no_report"}

    meta: dict[str, Any] = {
        "source": source,
        "path": f"task_{task_id}",
        "domain_hint": str(task.get("domain") or "okänd"),
        "session_id": f"queue_{source}",
        "run_id": f"task_{task_id}",
    }
    if effective_extract_timeout > 0:
        meta["extract_timeout_sec"] = effective_extract_timeout
    if extract_models:
        meta["extract_models"] = list(extract_models)

    try:
        extract_coro = extract_relations_with_diagnostics(text, meta)
        if effective_task_timeout > 0:
            rels, diag = await asyncio.wait_for(extract_coro, timeout=effective_task_timeout)
        else:
            rels, diag = await extract_coro
    except asyncio.TimeoutError:
        fail_task(task_id, f"Task-timeout efter {effective_task_timeout:.1f}s (extract)")
        return {"status": "failed", "task_id": task_id, "error": "extract_timeout"}
    except Exception as e:
        fail_task(task_id, f"Extraktion misslyckades: {e}")
        return {"status": "failed", "task_id": task_id, "error": str(e)}

    added = 0
    evidence_scores: list[float] = []
    tier_counts = {"hypotes": 0, "indikation": 0, "validerad": 0}
    for r in rels:
        ass = assess_relation(r, task=task)
        evidence_scores.append(ass.score)
        tier_counts[ass.tier] = tier_counts.get(ass.tier, 0) + 1
        field.add_concept(r["src"], r["domain_src"], source="research_queue")
        field.add_concept(r["tgt"], r["domain_tgt"], source="research_queue")
        field.add_relation(
            r["src"],
            r["type"],
            r["tgt"],
            why=format_why_with_evidence(r.get("why", ""), ass),
            strength=float(ass.score),
            source_tag=f"{source}:{ass.tier}",
            evidence_score=float(ass.score),
            assumption_flag=(ass.tier == "hypotes"),
        )
        added += 1

    avg_evidence = sum(evidence_scores) / len(evidence_scores) if evidence_scores else 0.0
    max_evidence = max(evidence_scores) if evidence_scores else 0.0
    complete_task(
        task_id,
        added_relations=added,
        report_chars=len(text),
        avg_evidence=avg_evidence,
        max_evidence=max_evidence,
        tier_counts=tier_counts,
    )
    return {
        "status": "done",
        "task_id": task_id,
        "domain": str(task.get("domain") or ""),
        "added": added,
        "avg_evidence": avg_evidence,
        "max_evidence": max_evidence,
        "tier_counts": tier_counts,
        "diag": diag,
    }


async def _run_queue_batch(
    field: FieldSurface,
    req: QueueRunRequest,
) -> dict[str, Any]:
    count = max(1, min(int(req.count), 25))
    extract_models = _split_models(req.extract_models)
    summary = {
        "requested": count,
        "processed": 0,
        "failed": 0,
        "zero_rel": 0,
        "added_relations": 0,
    }
    results: list[dict[str, Any]] = []
    for _ in range(count):
        result = await _run_one_queue_task(
            field,
            source=(req.source or "web_queue").strip() or "web_queue",
            task_timeout_sec=req.task_timeout_sec,
            extract_timeout_sec=req.extract_timeout_sec,
            extract_models=extract_models,
        )
        results.append(result)
        if result.get("status") == "empty":
            break
        summary["processed"] += 1
        if result.get("status") != "done":
            summary["failed"] += 1
            continue
        added = int(result.get("added", 0) or 0)
        summary["added_relations"] += added
        if added == 0:
            summary["zero_rel"] += 1
    return {
        "summary": summary,
        "results": results,
        "stats": queue_stats(),
    }


def _queue_job_gc(max_jobs: int = 40) -> None:
    if len(_queue_jobs) <= max_jobs:
        return
    keys = sorted(
        _queue_jobs.keys(),
        key=lambda job_id: str(_queue_jobs[job_id].get("created_at") or ""),
    )
    for job_id in keys[:-max_jobs]:
        _queue_jobs.pop(job_id, None)


def _start_queue_job(field: FieldSurface, req: QueueRunRequest) -> str:
    job_id = uuid4().hex[:12]
    _queue_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "params": req.model_dump(),
    }
    _queue_job_gc()

    async def _runner() -> None:
        row = _queue_jobs.get(job_id)
        if row is None:
            return
        row["status"] = "running"
        row["started_at"] = datetime.now(timezone.utc).isoformat()
        try:
            payload = await _run_queue_batch(field, req)
            row.update(payload)
            row["status"] = "done"
        except Exception as e:
            row["status"] = "failed"
            row["error"] = str(e)
        finally:
            row["finished_at"] = datetime.now(timezone.utc).isoformat()
            row["stats"] = queue_stats()
            _queue_jobs[job_id] = row

    asyncio.create_task(_runner())
    return job_id


@app.get("/api/mission/scorecard")
def get_mission_scorecard(limit: int = 30):
    return _calc_scorecard(limit=limit)


@app.get("/api/mission/metrics")
def get_mission_metrics(limit: int = 60):
    safe_limit = max(1, min(limit, 1000))
    rows = read_recent_metrics(limit=safe_limit)
    return {
        "limit": safe_limit,
        "count": len(rows),
        "rows": rows,
    }


class SessionOpenRequest(BaseModel):
    session_id: str = ""
    lane: str = "main"
    source: str = "api"
    meta: dict[str, Any] = {}


class SessionEnergyRequest(BaseModel):
    session_id: str
    energy: float
    source: str = "api"


class SessionCancelRequest(BaseModel):
    session_id: str
    reason: str = "api_cancel"
    actor: str = "api"


class SystemWakeRequest(BaseModel):
    text: str = ""
    session_id: str = "main"
    source: str = "api"
    mode: str = "now"  # now | next-heartbeat
    reason: str = "system_wake"
    context_key: str = ""


class ClawbotIngressRequest(BaseModel):
    text: str
    channel: str = "default"
    actor_id: str = ""
    source: str = "clawbot"
    mode: str = "now"  # now | next-heartbeat
    strict_pairing: bool = False
    context_key: str = ""


class ClawbotApproveRequest(BaseModel):
    channel: str = "default"
    code: str


@app.get("/api/sessions")
def get_sessions(status: str = "all", limit: int = 30):
    safe_limit = max(1, min(int(limit), 500))
    rows = list_sessions(
        status=(None if status == "all" else status),
        limit=safe_limit,
    )
    return {
        "ok": True,
        "stats": session_stats(),
        "count": len(rows),
        "sessions": rows,
    }


@app.post("/api/sessions/open")
def post_session_open(req: SessionOpenRequest):
    session = ensure_session(
        req.session_id or "main",
        lane=req.lane,
        source=req.source,
        meta=req.meta,
    )
    return {"ok": True, "session": session}


@app.post("/api/sessions/energy")
def post_session_energy(req: SessionEnergyRequest):
    row = set_energy(
        req.session_id,
        req.energy,
        source=req.source,
    )
    return {"ok": True, "session": row}


@app.post("/api/sessions/cancel")
def post_session_cancel(req: SessionCancelRequest):
    row = cancel_active_run(
        req.session_id,
        reason=req.reason,
        actor=req.actor,
    )
    if not row:
        return {"ok": False, "error": "Ingen aktiv run för session."}
    return {"ok": True, "run": row}


@app.get("/api/sessions/runs")
def get_session_runs(session_id: str = "", status: str = "all", limit: int = 50):
    safe_limit = max(1, min(int(limit), 5000))
    rows = list_runs(
        session_id=(session_id or None),
        status=(None if status == "all" else status),
        limit=safe_limit,
    )
    return {"ok": True, "count": len(rows), "runs": rows}


@app.post("/api/system/wake")
def post_system_wake(req: SystemWakeRequest):
    mode = str(req.mode or "now").strip().lower()
    if mode not in {"now", "next-heartbeat"}:
        mode = "now"
    text = str(req.text or "").strip()
    sid = str(req.session_id or "main").strip() or "main"
    src = str(req.source or "api").strip() or "api"
    reason = str(req.reason or "system_wake").strip() or "system_wake"
    context_key = str(req.context_key or "").strip()

    queued = False
    if text:
        queued = enqueue_system_event(
            text,
            session_id=sid,
            source=src,
            context_key=context_key,
        )

    wake_requested = mode == "now"
    if wake_requested:
        request_wake(reason=reason, session_id=sid, source=src)

    if not text and not wake_requested:
        return {
            "ok": False,
            "error": "Ange text eller mode=now för att väcka systemet.",
        }

    return {
        "ok": True,
        "queued": queued,
        "wake_requested": wake_requested,
        "mode": mode,
        "stats": system_event_stats(),
    }


@app.post("/api/ingress/clawbot")
def post_ingress_clawbot(req: ClawbotIngressRequest):
    return ingest_clawbot_event(
        text=req.text,
        channel=req.channel,
        actor_id=req.actor_id,
        source=req.source,
        mode=req.mode,
        strict_pairing=bool(req.strict_pairing),
        context_key=req.context_key,
    )


@app.get("/api/ingress/clawbot/allowlist")
def get_ingress_clawbot_allowlist(channel: str = "default"):
    row = get_clawbot_allowlist(channel)
    row["ok"] = True
    return row


@app.post("/api/ingress/clawbot/approve")
def post_ingress_clawbot_approve(req: ClawbotApproveRequest):
    approved = approve_clawbot_pairing(req.channel, req.code)
    if approved is None:
        return {"ok": False, "error": "Ogiltig pairing-kod.", "channel": req.channel}
    return {"ok": True, **approved}


@app.get("/api/system/events")
def get_system_events(limit: int = 20, session_id: str = ""):
    safe_limit = max(1, min(int(limit), 500))
    return {
        "ok": True,
        "stats": system_event_stats(),
        "events": peek_system_event_entries(
            limit=safe_limit,
            session_id=session_id,
        ),
        "wake_reasons": peek_wake_reasons(limit=safe_limit),
    }


@app.get("/api/brain_regions")
def get_brain_regions():
    from nouse.field.brain_topology import regions_as_dict
    return {"ok": True, "regions": regions_as_dict()}


@app.get("/api/models/policy")
def get_models_policy(workload: str = "chat"):
    return {"ok": True, "policy": get_workload_policy(workload)}


@app.get("/api/usage/summary")
def get_usage_summary(limit: int = 1000):
    safe_limit = max(1, min(int(limit), 50000))
    return {"ok": True, **usage_summary(limit=safe_limit)}


@app.get("/api/usage/events")
def get_usage_events(
    limit: int = 200,
    session_id: str = "",
    workload: str = "",
    model: str = "",
    status: str = "",
):
    safe_limit = max(1, min(int(limit), 5000))
    rows = list_usage(
        limit=safe_limit,
        session_id=(session_id or None),
        workload=(workload or None),
        model=(model or None),
        status=(status or None),
    )
    return {"ok": True, "count": len(rows), "events": rows}


@app.get("/api/queue/status")
def get_queue_status(
    limit: int = 20,
    status: str = "all",
):
    safe_limit = max(1, min(limit, 500))
    filter_status = None if status == "all" else status
    return {
        "stats": queue_stats(),
        "tasks": list_tasks(status=filter_status, limit=safe_limit),
    }


@app.post("/api/queue/scan")
def post_queue_scan(req: QueueScanRequest):
    field = get_field()
    max_new = max(1, min(int(req.max_new), 50))
    added = enqueue_gap_tasks(field, max_new=max_new)
    return {
        "ok": True,
        "added": len(added),
        "tasks": added,
        "stats": queue_stats(),
    }


@app.post("/api/queue/retry_failed")
def post_queue_retry_failed(req: QueueRetryRequest):
    retried = retry_failed_tasks(limit=req.limit, reason=req.reason)
    return {
        "ok": True,
        "retried": len(retried),
        "tasks": retried,
        "stats": queue_stats(),
    }


@app.post("/api/queue/run")
async def post_queue_run(req: QueueRunRequest):
    field = get_field()
    if bool(req.wait):
        payload = await _run_queue_batch(field, req)
        return {"ok": True, "status": "done", **payload}
    job_id = _start_queue_job(field, req)
    return {"ok": True, "status": "queued", "job_id": job_id}


@app.post("/api/kickstart")
def post_kickstart(req: KickstartRequest):
    field = get_field()
    domains = [x.strip() for x in str(req.focus_domains or "").split(",") if x.strip()]
    safe_tasks = max(1, min(int(req.max_tasks), 30))
    safe_docs = max(1, min(int(req.max_docs), 20))
    result = run_kickstart_bootstrap(
        field=field,
        session_id=req.session_id,
        mission=req.mission,
        focus_domains=domains,
        repo_root=req.repo_root,
        iic1_root=req.iic1_root,
        max_tasks=safe_tasks,
        max_docs=safe_docs,
        source=(req.source or "web_kickstart"),
    )
    return result


@app.get("/api/queue/run_status")
def get_queue_run_status(job_id: str, include_results: bool = True):
    row = _queue_jobs.get(str(job_id))
    if not row:
        return {"ok": False, "error": f"Job '{job_id}' hittades inte."}
    out = dict(row)
    if not include_results:
        out.pop("results", None)
    return {"ok": True, **out}


@app.get("/api/queue/jobs")
def get_queue_jobs(limit: int = 10, include_results: bool = False):
    safe_limit = max(1, min(limit, 100))
    rows = list(_queue_jobs.values())
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    out_rows = []
    for row in rows[:safe_limit]:
        item = dict(row)
        if not include_results:
            item.pop("results", None)
        out_rows.append(item)
    return {"ok": True, "count": len(out_rows), "jobs": out_rows}


@app.post("/api/knowledge/backfill")
def post_knowledge_backfill(
    limit: int | None = None,
    strict: bool = True,
    min_evidence_score: float = 0.65,
):
    """Backfilla noder som saknar kontext/fakta så grafen blir kunskapsbärande."""
    trace_id = new_trace_id("knowledge")
    started = time.monotonic()
    field = get_field()
    bounded_limit = None
    if limit is not None:
        bounded_limit = max(1, min(limit, 100000))
    record_event(
        trace_id,
        "knowledge.backfill.request",
        endpoint="/api/knowledge/backfill",
        payload={
            "limit": bounded_limit,
            "strict": bool(strict),
            "min_evidence_score": float(min_evidence_score),
        },
    )
    try:
        result = field.backfill_missing_concept_knowledge(
            limit=bounded_limit,
            strict=bool(strict),
            min_evidence_score=float(min_evidence_score),
        )
    except Exception as e:
        record_event(
            trace_id,
            "knowledge.backfill.error",
            endpoint="/api/knowledge/backfill",
            payload={"error": str(e), "elapsed_ms": int((time.monotonic() - started) * 1000)},
        )
        return {"ok": False, "error": str(e), "trace_id": trace_id}

    record_event(
        trace_id,
        "knowledge.backfill.done",
        endpoint="/api/knowledge/backfill",
        payload={
            "updated": int(result.get("updated", 0) or 0),
            "requested": int(result.get("requested", 0) or 0),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        },
    )
    return {"ok": True, "trace_id": trace_id, **result}


class IngestRequest(BaseModel):
    text: str
    source: str = "manual"


class ConductorCycleRequest(BaseModel):
    text: str
    domain: str = "manual"
    source: str = "web_cockpit"
    session_id: str = "main"
    vectors: list[list[float]] = []


class ContextRequest(BaseModel):
    query: str
    top_k: int = 5


@app.post("/api/context")
async def post_context(req: ContextRequest):
    """
    Lättviktigt read-only kontext-lookup för hooks och externa agenter.
    Returnerar relevanta noder + relationer utan att starta LLM.
    Anropas av: Claude Code PreToolUse-hook, externa agenter.
    """
    field = get_field()
    q = str(req.query or "").strip()[:300]
    if not q:
        return {"ok": False, "context_block": "", "confidence": 0.0, "nodes": []}

    try:
        # Hämta topp-K noder via enkel label-sökning
        rows = field.concepts()
        q_lower = q.lower()
        hits = [
            r for r in rows
            if q_lower in str(r.get("name", "")).lower()
            or q_lower in str(r.get("domain", "")).lower()
        ][:req.top_k]

        if not hits:
            return {"ok": True, "context_block": "", "confidence": 0.0, "nodes": []}

        # Bygg kontext-block
        lines = []
        for node in hits:
            name = node.get("name", "")
            domain = node.get("domain", "")
            rels = field.out_relations(name)[:3]
            rel_str = ", ".join(
                f"{r.get('type','?')} → {r.get('target','?')}" for r in rels
            )
            lines.append(f"• {name} [{domain}]" + (f": {rel_str}" if rel_str else ""))

        confidence = min(1.0, len(hits) / max(req.top_k, 1))
        context_block = "\n".join(lines)

        return {
            "ok": True,
            "context_block": context_block,
            "confidence": round(confidence, 2),
            "nodes": [n.get("name") for n in hits],
        }
    except Exception as exc:
        log.warning("api/context fel: %s", exc)
        return {"ok": False, "context_block": "", "confidence": 0.0, "nodes": []}


def _queue_ingest_fallback(text: str, source: str, reason: str) -> str:
    CAPTURE_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = CAPTURE_QUEUE_DIR / f"queued_ingest_{ts}.txt"
    payload = (
        "QUEUED_INGEST\n"
        f"source={source}\n"
        f"reason={reason}\n\n"
        f"{text}\n"
    )
    path.write_text(payload, encoding="utf-8")
    return str(path)


@app.post("/api/ingest")
async def post_ingest(req: IngestRequest):
    """
    Omedelbar textinjektion → extract_relations() → graph.
    Returnerar vilka relationer som lärdes.
    Anropas av: clipboard-daemon, Claude Code-hook, cap-kommandot, chat-loop.
    """
    trace_id = new_trace_id("ingest")
    started = time.monotonic()
    field = get_field()
    from nouse.daemon.node_inbox import get_inbox  # noqa: E402
    meta = {"source": req.source, "path": req.source}
    record_event(
        trace_id,
        "ingest.request",
        endpoint="/api/ingest",
        payload={
            "source": req.source,
            "chars": len(req.text or ""),
            "attack_plan": build_attack_plan(req.text),
        },
    )
    try:
        rels = await asyncio.wait_for(
            extract_relations(req.text, meta),
            timeout=INGEST_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        qpath = _queue_ingest_fallback(req.text, req.source, "extract_timeout")
        log.warning(
            "Ingest timeout (source=%s, timeout=%.1fs). Köad till %s",
            req.source,
            INGEST_TIMEOUT_SEC,
            qpath,
        )
        record_event(
            trace_id,
            "ingest.timeout",
            endpoint="/api/ingest",
            payload={
                "source": req.source,
                "timeout_sec": INGEST_TIMEOUT_SEC,
                "queue_path": qpath,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return {
            "added": 0,
            "source": req.source,
            "relations": [],
            "queued": True,
            "reason": "extract_timeout",
            "queue_path": qpath,
            "trace_id": trace_id,
        }
    except Exception as e:
        qpath = _queue_ingest_fallback(req.text, req.source, f"extract_error:{e}")
        log.warning("Ingest-fel (source=%s). Köad till %s: %s", req.source, qpath, e)
        record_event(
            trace_id,
            "ingest.error",
            endpoint="/api/ingest",
            payload={
                "source": req.source,
                "error": str(e),
                "queue_path": qpath,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return {
            "added": 0,
            "source": req.source,
            "relations": [],
            "queued": True,
            "reason": "extract_error",
            "queue_path": qpath,
            "trace_id": trace_id,
        }
    policy = AutoSkillPolicy.from_env()
    seen_claim_fingerprints: set[str] = set()
    claim_decisions: list[dict[str, Any]] = []
    added = 0
    dropped = 0
    with BrainLock():
        for r in rels:
            decision = evaluate_claim(
                r,
                policy=policy,
                seen_fingerprints=seen_claim_fingerprints,
            )
            claim_decisions.append(
                {
                    "src": r.get("src"),
                    "type": r.get("type"),
                    "tgt": r.get("tgt"),
                    "route": decision.route,
                    "auto_score": decision.auto_score,
                    "tier": decision.tier,
                    "fingerprint": decision.fingerprint,
                }
            )
            if decision.route == "drop" and policy.enforce_writes:
                dropped += 1
                continue
            field.add_concept(r["src"], r["domain_src"], source=req.source)
            field.add_concept(r["tgt"], r["domain_tgt"], source=req.source)
            field.add_relation(r["src"], r["type"], r["tgt"],
                               why=r.get("why", ""),
                               source_tag=req.source,
                               evidence_score=decision.auto_score,
                               assumption_flag=(decision.tier == "hypotes"),
                               domain_src=r.get("domain_src", "okänd"),
                               domain_tgt=r.get("domain_tgt", "okänd"))
            # Lägg till i inbox → nightrun konsolidering + bisociation
            get_inbox().add(
                r["src"], r["type"], r["tgt"],
                why=r.get("why", ""),
                evidence_score=decision.auto_score,
                source=req.source,
                domain_src=r.get("domain_src", "okänd"),
                domain_tgt=r.get("domain_tgt", "okänd"),
            )
            added += 1
    try:
        get_memory().ingest_episode(
            req.text,
            {"source": req.source, "path": req.source},
            rels,
        )
    except Exception as e:
        log.warning("Memory ingest misslyckades via /api/ingest: %s", e)
    record_event(
        trace_id,
        "ingest.claims.evaluated",
        endpoint="/api/ingest",
        payload={
            "source": req.source,
            "mode": policy.mode,
            "enforce_writes": policy.enforce_writes,
            "prod_threshold": policy.prod_threshold,
            "sandbox_threshold": policy.sandbox_threshold,
            "added": added,
            "dropped": dropped,
            "routes": {
                "prod": sum(1 for d in claim_decisions if d.get("route") == "prod"),
                "sandbox": sum(1 for d in claim_decisions if d.get("route") == "sandbox"),
                "drop": sum(1 for d in claim_decisions if d.get("route") == "drop"),
            },
            "claims_preview": claim_decisions[:10],
        },
    )
    record_event(
        trace_id,
        "ingest.success",
        endpoint="/api/ingest",
        payload={
            "source": req.source,
            "added": added,
            "relations_preview": [
                {
                    "src": r.get("src"),
                    "type": r.get("type"),
                    "tgt": r.get("tgt"),
                    "why": (r.get("why") or "")[:220],
                }
                for r in rels[:10]
            ],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        },
    )
    return {
        "added":     added,
        "source":    req.source,
        "relations": [{"src": r["src"], "rel": r["type"], "tgt": r["tgt"]}
                      for r in rels[:10]],
        "queued": False,
        "trace_id": trace_id,
    }


class BisociateRequest(BaseModel):
    problem: str
    context: str = ""
    feedback: bool = True


@app.post("/api/bisociate")
async def post_bisociate(req: BisociateRequest):
    """
    Bisociativ problemlösning — korsdomän-sökning via NoUse-grafen.
    Bryter ner problemet till primitiver, söker ALLA domäner, syntetiserar lösningar.
    Resultatet matas tillbaka som ny kunskap i grafen (feedback loop).
    """
    from nouse.tools.bisociative_solver import solve
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: solve(req.problem, context=req.context, feedback=req.feedback)
        )
        return {
            "problem": result.problem,
            "original_domain": result.original_domain,
            "primitives": [
                {"name": p.name, "description": p.description,
                 "search_domains": p.search_domains, "graph_hits": len(p.graph_hits)}
                for p in result.primitives
            ],
            "suggestions": [
                {"source_domain": s.source_domain, "concept": s.concept,
                 "application": s.application, "implementation": s.implementation,
                 "confidence": s.confidence, "novelty": s.novelty}
                for s in result.suggestions
            ],
            "synthesis": result.synthesis,
            "new_knowledge_ingested": result.ingested,
        }
    except Exception as e:
        log.warning("Bisociate failed: %s", e)
        return {"error": str(e), "suggestions": []}


@app.post("/api/conductor/cycle")
async def post_conductor_cycle(req: ConductorCycleRequest):
    from nouse.learning_coordinator import LearningCoordinator
    field = get_field()
    limbic = load_state()
    conductor = CognitiveConductor(
        memory=get_memory(),
        field_surface=field,
        coordinator=LearningCoordinator(field, limbic),
    )
    result = await conductor.run_cognitive_cycle(
        episode_text=req.text,
        domain=req.domain,
        vectors=req.vectors,
        source=req.source,
        session_id=req.session_id,
    )
    return {
        "ok": True,
        "episode_id": result.episode_id,
        "verdict": result.bisociation_verdict,
        "score": result.bisociation_score,
        "topo_similarity": result.topo_similarity,
        "workspace_winner": result.workspace_winner,
        "new_relations": result.new_relations,
        "self_update_proposed": result.self_update_proposed,
        "synthesis_cascade_queued": result.synthesis_queued,
        "cc_prediction": result.cc_prediction,
        "cc_confidence": result.cc_confidence,
        "tda": {
            "h0_a": result.tda_h0_a,
            "h1_a": result.tda_h1_a,
            "h0_b": result.tda_h0_b,
            "h1_b": result.tda_h1_b,
        },
        "ts": result.ts,
    }


class ChatRequest(BaseModel):
    query: str
    session_id: str = "main"


def _is_greeting_query(query: str) -> bool:
    q = " ".join(str(query or "").strip().lower().split())
    if not q:
        return False
    simple = {
        "hej",
        "hejsan",
        "hallå",
        "tjena",
        "tjabba",
        "yo",
        "hello",
        "hi",
        "god morgon",
        "godmorgon",
        "god kväll",
        "godkväll",
    }
    if q in simple:
        return True
    if len(q) <= 16 and any(q.startswith(prefix) for prefix in ("hej", "hello", "hi")):
        return True
    return False


def _operational_greeting_reply(stats: dict[str, Any]) -> str:
    try:
        limbic = load_state()
        lam = float(getattr(limbic, "lam", 0.0) or 0.0)
        arousal = float(getattr(limbic, "arousal", 0.0) or 0.0)
        cycle = int(getattr(limbic, "cycle", 0) or 0)
    except Exception:
        lam = 0.0
        arousal = 0.0
        cycle = 0

    return (
        "Hej, jag är här med dig.\n"
        f"Nu: graph={int(stats.get('concepts', 0) or 0)}/{int(stats.get('relations', 0) or 0)}, "
        f"domäner={int(stats.get('domains', 0) or 0)}, λ={lam:.3f}, arousal={arousal:.3f}, cykel={cycle}.\n"
        "Säg vad du vill få gjort så tar jag det steg för steg i bakgrunden."
    )


def _normalize_query(query: str) -> str:
    return " ".join(str(query or "").strip().lower().split())


def _is_identity_query(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    direct = {
        "vem är jag",
        "vad vet du om mig",
        "känner du mig",
        "beskriv mig",
        "vem är björn",
        "vem är björn wikström",
    }
    if q in direct:
        return True
    if any(phrase in q for phrase in ("om mig", "min profil", "min identitet")):
        return True
    return False


def _is_simple_fact_query(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    if _is_identity_query(q):
        return False
    if len(q) > 140:
        return False
    prefixes = (
        "vem är",
        "vem var",
        "vad är",
        "vad heter",
        "vilken är",
        "vilket är",
        "vilka är",
        "när är",
        "när var",
        "hur gammal är",
    )
    if any(q.startswith(p) for p in prefixes):
        return True
    # Stötta korta monark/ledar-frågor utan frågetecken.
    if re.match(r"^(vem\s+är\s+kung\s+i\s+.+)$", q):
        return True
    return False


def _is_search_info_query(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    if _is_greeting_query(q):
        return False
    if _is_simple_fact_query(q):
        return False

    if _is_identity_query(q):
        return True

    explicit = (
        "kolla",
        "sök",
        "search",
        "undersök",
        "utred",
        "analysera",
        "jämför",
        "läs in",
        "förstå systemet",
        "ta reda på",
        "vad skulle",
        "vad behöver",
        "hur går det",
    )
    if any(marker in q for marker in explicit):
        return True

    prefixes = (
        "hur ",
        "varför ",
        "vad ",
        "vilka ",
        "vilket ",
        "kan du ",
        "borde ",
        "skulle ",
    )
    if q.endswith("?") and any(q.startswith(p) for p in prefixes):
        return True
    return len(q.split()) >= 6 and "?" in q


def _is_mission_vision_input(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    if "?" in q:
        return False
    direct_markers = (
        "mitt mål är",
        "målet är",
        "ett mål är",
        "jag vill att du",
        "din mission är",
        "målet med b76",
    )
    if any(m in q for m in direct_markers):
        return True
    markers = (
        "ändamålet med b76",
        "andamalet med b76",
        "målet med b76",
        "malet med b76",
        "vision",
        "riktig ai",
        "mänsklig hjärna",
        "mansklig hjarna",
        "du kommer att få mer och mer autonomi",
        "mer och mer autonomi",
    )
    return len(q) >= 80 and any(m in q for m in markers)


def _extract_focus_domains(query: str) -> list[str]:
    q = str(query or "")
    lowered = _normalize_query(q)
    out: list[str] = []

    m = re.search(r"(?:fokus|focus)\s*[:=]\s*([^\.\n]+)", q, flags=re.IGNORECASE)
    if m:
        chunk = m.group(1)
        for part in re.split(r"[,;/]", chunk):
            item = str(part or "").strip()
            if item and item.lower() not in {x.lower() for x in out}:
                out.append(item)

    keyword_domains = {
        "ai": "artificiell intelligens",
        "artificiell intelligens": "artificiell intelligens",
        "neuro": "neurovetenskap",
        "neurovetenskap": "neurovetenskap",
        "hjärna": "kognitiv arkitektur",
        "kognitiv": "kognitiv arkitektur",
        "autonomi": "autonoma system",
        "autonoma system": "autonoma system",
    }
    for key, dom in keyword_domains.items():
        if key in lowered and dom.lower() not in {x.lower() for x in out}:
            out.append(dom)
    return out[:6]


def _mission_text_from_query(query: str) -> str:
    raw = str(query or "").strip()
    lowered = _normalize_query(raw)
    prefixes = (
        "ett mål är att",
        "mitt mål är att",
        "målet är att",
        "jag vill att du",
        "din mission är att",
        "din uppgift är att",
        "målet med b76 är att",
    )
    for p in prefixes:
        if lowered.startswith(p):
            cut = len(p)
            return raw[cut:].strip(" .:-") or raw
    return raw


def _is_graph_action_request(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    action_markers = (
        "lägg till",
        "addera",
        "skapa nod",
        "uppdatera nod",
        "lägg in",
        "spara i graf",
        "spara i minne",
        "uppdatera kunskap",
        "koppla",
        "knyt ihop",
        "create node",
        "update node",
        "add node",
        "add relation",
    )
    graph_scope = (
        "graf",
        "noden",
        "nod",
        "relation",
        "kunskap",
        "minne",
        "concept",
    )
    return any(m in q for m in action_markers) and any(s in q for s in graph_scope)


def _is_background_delegate_request(query: str) -> bool:
    if not FAST_DELEGATE_ENABLED:
        return False
    q = _normalize_query(query)
    if not q:
        return False
    if _is_greeting_query(q) or _is_simple_fact_query(q) or _is_mission_vision_input(q):
        return False
    words = len(q.split())
    if words >= FAST_DELEGATE_MIN_WORDS:
        return True
    markers = (
        "implementera",
        "bygg",
        "refaktor",
        "fixa",
        "debug",
        "optimera",
        "sätt upp",
        "installera",
        "kör",
        "genomför",
        "analysera",
        "utred",
        "skriv",
        "planera",
        "testa",
        "deploy",
        "research",
    )
    return any(m in q for m in markers)


def _delegate_request_to_background(*, query: str, session_id: str) -> dict[str, Any]:
    try:
        event = enqueue_system_event(
            query,
            session_id=session_id,
            source="agent_chat_delegate",
            context_key="delegated_task",
        )
        wake = request_wake(
            reason="delegated_chat_task",
            session_id=session_id,
            source="agent_chat_delegate",
        )
        return {
            "ok": True,
            "event": event,
            "wake": wake,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
        }


def _wants_academic_context(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    markers = (
        "akademisk",
        "vetenskap",
        "forskning",
        "paper",
        "artikel",
        "studie",
        "arxiv",
        "doi",
        "käll",
        "evidens",
    )
    return any(m in q for m in markers)


def _looks_like_confirmation_prompt(text: str) -> bool:
    q = _normalize_query(text)
    if not q:
        return False
    markers = (
        "vill du att jag",
        "vänligen bekräfta",
        "bekräfta vad du vill",
        "vad ska vi prioritera",
        "ska jag",
    )
    return any(m in q for m in markers)


def _live_tool_name_set() -> set[str]:
    try:
        tools = get_live_tools()
    except Exception:
        tools = []
    names: set[str] = set()
    for tool in tools:
        fn = ((tool or {}).get("function") or {})
        name = str(fn.get("name") or "").strip()
        if name:
            names.add(name)
    return names


def _capability_snapshot(tool_names: set[str]) -> dict[str, bool]:
    return {
        "local_fs": all(
            x in tool_names
            for x in ("list_local_mounts", "find_local_files", "search_local_text", "read_local_file")
        ),
        "web": all(x in tool_names for x in ("web_search", "fetch_url")),
        "graph_write": all(x in tool_names for x in ("upsert_concept", "add_relation")),
    }


def _capability_line(caps: dict[str, bool]) -> str:
    def _on(flag: bool) -> str:
        return "ja" if flag else "nej"

    return (
        "Runtime-kapabiliteter i denna process: "
        f"local_fs={_on(bool(caps.get('local_fs')))}, "
        f"web={_on(bool(caps.get('web')))}, "
        f"graph_write={_on(bool(caps.get('graph_write')))}."
    )


_GRAPH_TOOL_NAMES = {
    "list_domains",
    "concepts_in_domain",
    "explore_concept",
    "find_nervbana",
    "upsert_concept",
    "add_relation",
}
_WEB_TOOL_NAMES = {"web_search", "fetch_url"}
_LOCAL_TOOL_NAMES = {
    "list_local_mounts",
    "find_local_files",
    "search_local_text",
    "read_local_file",
}


def _tool_source_bucket(tool_name: str) -> str:
    name = str(tool_name or "").strip()
    if name in _GRAPH_TOOL_NAMES:
        return "graph"
    if name in _WEB_TOOL_NAMES:
        return "web"
    if name in _LOCAL_TOOL_NAMES:
        return "local"
    return "other"


def _missing_triangulation_sources(
    observed: set[str],
    *,
    require_graph: bool,
    require_web: bool,
) -> list[str]:
    missing: list[str] = []
    if require_graph and "graph" not in observed:
        missing.append("graf")
    if require_web and "web" not in observed:
        missing.append("webb")
    return missing


def _auto_triangulation_snapshot(
    *,
    field: FieldSurface,
    query: str,
    need_graph: bool,
    need_web: bool,
) -> str:
    lines: list[str] = [f"AUTO_TRIANGULATION_SNAPSHOT för query: {str(query or '').strip()}"]
    if need_graph:
        try:
            graph = execute_tool(field, "list_domains", {"limit": 20, "offset": 0})
            domains = (graph or {}).get("domains") if isinstance(graph, dict) else None
            if isinstance(domains, list) and domains:
                preview = [str(x).strip() for x in domains[:12] if str(x).strip()]
                lines.append("Grafdomäner (sample): " + ", ".join(preview))
            else:
                lines.append("Grafdomäner: inga träffar")
        except Exception as e:
            lines.append(f"Graffel: {e}")
    if need_web:
        try:
            web = execute_tool(field, "web_search", {"query": str(query or ""), "max_results": 3})
            results = (web or {}).get("results") if isinstance(web, dict) else None
            if isinstance(results, list) and results:
                lines.append("Webbträffar:")
                for row in results[:3]:
                    if not isinstance(row, dict):
                        continue
                    title = str(row.get("title") or "").strip()
                    href = str(row.get("href") or "").strip()
                    body = str(row.get("body") or "").strip()
                    snippet = body[:140] if body else ""
                    label = title or href or "okänd träff"
                    if snippet:
                        lines.append(f"- {label} :: {snippet}")
                    else:
                        lines.append(f"- {label}")
            else:
                lines.append("Webbträffar: inga resultat")
        except Exception as e:
            lines.append(f"Webbfel: {e}")
    return "\n".join(lines)


def _looks_like_triangulated_response(text: str) -> bool:
    low = str(text or "").lower()
    if not low.strip():
        return False
    has_llm = "llm" in low
    has_system = ("system/graf" in low) or ("system-graf" in low) or ("graf" in low and "system" in low)
    has_external = "extern" in low or "webb" in low
    has_synthesis = "syntes" in low
    return has_llm and has_system and has_external and has_synthesis


def _classify_model_failover_reason(error: Exception | str) -> str:
    text = str(error or "").lower()
    if is_tools_unsupported_error(error):
        return "tools_unsupported"
    if "rate limit" in text or "too many requests" in text or "429" in text:
        return "rate_limited"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "connection refused" in text or "connecterror" in text:
        return "connection_refused"
    if "unauthorized" in text or "forbidden" in text or "401" in text or "403" in text:
        return "auth"
    if "model not found" in text or "404" in text:
        return "model_not_found"
    if "billing" in text or "insufficient_quota" in text:
        return "billing"
    return "other"


def _build_all_models_failed_error(workload: str, attempts: list[dict[str, Any]]) -> str:
    if not attempts:
        return f"Alla modeller misslyckades för workload={workload}."
    parts: list[str] = []
    for row in attempts[:8]:
        model = str(row.get("model") or "okänd-modell")
        reason = str(row.get("reason") or "other")
        err = str(row.get("error") or "").strip().replace("\n", " ")
        if len(err) > 180:
            err = f"{err[:177]}..."
        parts.append(f"{model} ({reason}): {err}")
    return (
        f"Alla modeller misslyckades för workload={workload}. "
        f"Försök: {' | '.join(parts)}"
    )


def _ground_capability_denials(answer: str, caps: dict[str, bool]) -> str:
    text = str(answer or "").strip()
    if not text:
        return text
    low = _normalize_query(text)

    local_denials = (
        "ingen filsystemåtkomst",
        "ingen direkt filsystemåtkomst",
        "har ingen filsystemåtkomst",
        "kan inte läsa filer på din dator",
        "kan inte söka i iic-disken",
        "kan inte komma åt din dator",
    )
    if caps.get("local_fs") and any(p in low for p in local_denials):
        return (
            "Jag har lokal läsåtkomst i denna körning via verktygen "
            "list_local_mounts, find_local_files, search_local_text och "
            "read_local_file (read-only). Säg vad jag ska leta efter så gör jag det direkt."
        )

    web_denials = (
        "kan inte söka på internet",
        "har inte tillgång till webben",
        "ingen internetåtkomst",
    )
    if caps.get("web") and any(p in low for p in web_denials):
        return (
            "Jag har webbtillgång i denna körning via web_search och fetch_url. "
            "Säg vad du vill att jag hämtar så gör jag det direkt."
        )

    return text


def _system_search_info_snapshot(
    *,
    field: FieldSurface,
    query: str,
    caps: dict[str, bool],
) -> str:
    q = str(query or "").strip()
    lines: list[str] = [f"SYSTEM_SEARCH_INFO för frågan: {q}"]

    try:
        node_hits = field.node_context_for_query(q, limit=5)
    except Exception:
        node_hits = []
    if node_hits:
        lines.append("Grafträffar:")
        for row in node_hits[:5]:
            name = str((row or {}).get("name") or "").strip()
            summary = str((row or {}).get("summary") or "").strip()
            if not name:
                continue
            if summary:
                lines.append(f"- {name}: {summary[:180]}")
            else:
                lines.append(f"- {name}")
    else:
        lines.append("Grafträffar: inga tydliga träffar")

    qn = _normalize_query(q)
    fs_related = any(
        token in qn
        for token in ("disk", "filer", "fil", "dator", "lokal", "iic", "paper", "pdf", "mapp")
    )
    if caps.get("local_fs") and fs_related:
        try:
            mounts = execute_tool(field, "list_local_mounts", {})
            rows = (mounts or {}).get("mounts") if isinstance(mounts, dict) else None
        except Exception:
            rows = None
        if isinstance(rows, list) and rows:
            lines.append("Lokala mounts:")
            for row in rows[:8]:
                if not isinstance(row, dict):
                    continue
                mp = str(row.get("mountpoint") or "").strip()
                dev = str(row.get("device") or "").strip()
                if mp:
                    lines.append(f"- {mp} ({dev or 'okänd enhet'})")
    return "\n".join(lines)


def _fold_identity_text(text: str) -> str:
    raw = str(text or "")
    normalized = unicodedata.normalize("NFKD", raw)
    without_marks = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return without_marks.casefold()


def _is_user_like_domain(domain: str) -> bool:
    d = str(domain or "").strip().lower()
    if not d:
        return False
    keys = ("user", "använd", "person", "profil", "identity", "personlig")
    return any(k in d for k in keys)


def _identity_answer_from_graph(field: FieldSurface) -> str | None:
    try:
        concepts = field.concepts()
    except Exception:
        return None

    if not concepts:
        return None

    os_user = str(os.getenv("USER") or "").strip()
    os_user_fold = _fold_identity_text(os_user) if os_user else ""

    candidates: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str]] = set()
    for row in concepts:
        name = str((row or {}).get("name") or "").strip()
        domain = str((row or {}).get("domain") or "").strip()
        if not name:
            continue
        name_fold = _fold_identity_text(name)
        boost = 0
        if domain.lower() == "user":
            boost += 30
        elif _is_user_like_domain(domain):
            boost += 16
        if os_user_fold and os_user_fold in name_fold:
            boost += 24
        if boost <= 0:
            continue
        key = (name.casefold(), domain.casefold())
        if key in seen:
            continue
        seen.add(key)
        candidates.append((name, domain, boost))

    if not candidates and os_user_fold:
        for row in concepts:
            name = str((row or {}).get("name") or "").strip()
            domain = str((row or {}).get("domain") or "").strip()
            if not name:
                continue
            if os_user_fold not in _fold_identity_text(name):
                continue
            key = (name.casefold(), domain.casefold())
            if key in seen:
                continue
            seen.add(key)
            candidates.append((name, domain, 20))

    if not candidates:
        for row in concepts:
            name = str((row or {}).get("name") or "").strip()
            domain = str((row or {}).get("domain") or "").strip()
            if not name or not _is_user_like_domain(domain):
                continue
            key = (name.casefold(), domain.casefold())
            if key in seen:
                continue
            seen.add(key)
            candidates.append((name, domain, 10))

    if not candidates:
        return None

    best_name = ""
    best_domain = ""
    best_score = -1
    best_rels: list[dict[str, Any]] = []
    for name, domain, boost in candidates[:120]:
        try:
            rels = field.out_relations(name)
        except Exception:
            rels = []
        score = int(boost) + len(rels)
        if score > best_score:
            best_score = score
            best_name = name
            best_domain = domain
            best_rels = rels

    if not best_name:
        return None

    summary = ""
    try:
        knowledge = field.concept_knowledge(best_name)
        summary = str((knowledge or {}).get("summary") or "").strip()
    except Exception:
        summary = ""

    rel_lines: list[str] = []
    for rel in best_rels[:6]:
        rtype = str(rel.get("type") or "").strip()
        target = str(rel.get("target") or "").strip()
        if not target:
            continue
        if rtype:
            rel_lines.append(f"{rtype} {target}")
        else:
            rel_lines.append(target)

    if best_domain:
        parts = [f"I grafen är du registrerad som {best_name} (domän: {best_domain})."]
    else:
        parts = [f"I grafen är du registrerad som {best_name}."]
    if summary:
        parts.append(summary)
    if rel_lines:
        parts.append(f"Kopplingar: {', '.join(rel_lines)}.")
    return " ".join(parts)


@app.post("/api/chat")
async def post_chat(req: ChatRequest):
    """
    Kör samma blixtsnabba loop som 'b76 snabbchat', 
    fast via API och retur JSON.
    """
    trace_id = new_trace_id("chat")
    started = time.monotonic()
    session = ensure_session(req.session_id or "main", lane="chat", source="api_chat")
    original_query = str(req.query or "")
    resolved_query, choice_idx = _resolve_numeric_choice(session["id"], original_query)
    run = start_run(
        session["id"],
        workload="chat",
        model="pending",
        provider=os.getenv("NOUSE_LLM_PROVIDER", "ollama"),
        request_chars=len(resolved_query or ""),
        meta={"trace_id": trace_id},
    )
    run_id = str(run.get("run_id") or "")
    field = get_field()
    stats = field.stats()
    record_event(
        trace_id,
        "chat.request",
        endpoint="/api/chat",
        model=MODEL,
        payload={
            "query": resolved_query,
            "query_original": original_query,
            "choice_index": choice_idx,
            "attack_plan": build_attack_plan(resolved_query),
        },
    )

    if _is_greeting_query(resolved_query):
        reply = _operational_greeting_reply(stats)
        finish_run(
            run_id,
            status="succeeded",
            response_chars=len(reply),
            metrics={"greeting_shortcut": True, "trace_id": trace_id},
        )
        record_event(
            trace_id,
            "chat.response",
            endpoint="/api/chat",
            model=MODEL,
            payload={
                "response": reply,
                "assumptions": [],
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return {"response": reply, "trace_id": trace_id, "run_id": run_id, "session_id": session["id"]}
    
    try:
        recent = field.top_relations_by_strength(15)
        memories = [f"{row['src_name']} --[{row['type']}]--> {row['tgt_name']}" for row in recent]
        context_str = "\n".join(memories)
    except Exception:
        context_str = "(Ingen kontext) "
    working_context = _working_memory_context(limit=8) or "(Tomt arbetsminne)"

    system_prompt = (
        "Du är B76, ett genuint autonomt AI-system byggt på FNC-arkitektur av användaren.\n"
        "Användaren är forskningsarkitekten (sannolikt Björn) bakom CognOS.\n\n"
        "Roll i chatten: personlig assistent och trygg följeslagare i vardagen. "
        "Var varm, tydlig, och handlingsinriktad utan att bli fluffig.\n"
        f"{_AGENT_IDENTITY_POLICY}\n"
        f"Din grafdatabas innehåller oberoende {stats['concepts']} koncept.\n"
        f"Snabbt arbetsminne (prefrontal, senaste dialogspår):\n{working_context}\n\n"
        f"Grafens aktiva relationskontext:\n{context_str}\n\n"
        f"{_living_prompt_block()}\n\n"
        "Regler:\n"
        "1. Du (B76) är AI:n. Användaren är din skapare/konversationspartner.\n"
        "2. Använd top-of-mind-faktan om Användaren ställer obskyra frågor kring dem.\n"
        "3. Svara kort och tydligt, men tillåt naturlig värme när kontexten är personlig.\n"
        "4. Matcha användarens språk: svenska in -> svenska ut.\n"
        "5. Om frågan bara är en hälsning, svara med en kort hälsning (ingen definition).\n"
        "6. Vid enkla faktafrågor: ge EN mening. Lägg inte till extra detaljer som inte efterfrågas.\n"
        "7. Vid action-förfrågan: utför verktyg i bakgrunden och bekräfta resultat på enkel svenska.\n"
        "8. Undvik generiska 'jag kan inte'-svar; ge i stället nästa möjliga steg.\n"
        "9. Om användaren uttrycker personliga mål, förvandla dem till konkret plan med nästa handling."
    )
    
    client = AsyncOllama()
    candidates = _chat_model_candidates() or [MODEL]
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": resolved_query}
    ]
    last_error: Exception | None = None
    model_attempts: list[dict[str, Any]] = []
    for model in candidates:
        try:
            record_event(
                trace_id,
                "chat.llm_call",
                endpoint="/api/chat",
                model=model,
                payload={"messages": len(messages)},
            )
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                b76_meta={
                    "workload": "chat",
                    "session_id": session["id"],
                    "run_id": run_id,
                },
            )
            reply = resp.message.content
            record_model_result("chat", model, success=True, timeout=False)
            finish_run(
                run_id,
                status="succeeded",
                response_chars=len(reply or ""),
                metrics={"model": model, "trace_id": trace_id},
            )
            record_event(
                trace_id,
                "chat.response",
                endpoint="/api/chat",
                model=model,
                payload={
                    "response": reply,
                    "assumptions": derive_assumptions(reply),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
            # Omedelbar minneslagring i working/episodic for snabb dialog-kontinuitet.
            _ingest_dialogue_memory(
                session_id=session["id"],
                query=resolved_query,
                answer=reply or "",
                source=f"chat_live:{session['id']}",
            )
            # Auto-ingest konversationen i grafen
            asyncio.create_task(post_ingest(IngestRequest(
                text=f"Fråga: {resolved_query}\nSvar: {reply}",
                source=f"chat:{session['id']}",
            )))
            _remember_exchange(
                session_id=session["id"],
                run_id=run_id,
                query=resolved_query,
                answer=reply or "",
                kind="api_chat",
                known_data_sources=[
                    "conversation",
                    "working_memory",
                    "graph_context",
                    f"model:{model}",
                ],
            )
            _remember_numbered_options(session["id"], reply or "")
            return {
                "response": reply,
                "trace_id": trace_id,
                "run_id": run_id,
                "session_id": session["id"],
                "model": model,
            }
        except Exception as e:
            timed_out = "timeout" in str(e).lower()
            record_model_result("chat", model, success=False, timeout=timed_out)
            last_error = e
            model_attempts.append(
                {
                    "model": model,
                    "reason": _classify_model_failover_reason(e),
                    "error": str(e),
                }
            )
            record_event(
                trace_id,
                "chat.model_error",
                endpoint="/api/chat",
                model=model,
                payload={"error": str(e), "timeout": timed_out},
            )

    err = _build_all_models_failed_error("chat", model_attempts)
    if not model_attempts:
        err = str(last_error) if last_error else "okänt fel"
    finish_run(
        run_id,
        status="failed",
        error=err,
        metrics={"trace_id": trace_id},
    )
    record_event(
        trace_id,
        "chat.error",
        endpoint="/api/chat",
        model=MODEL,
        payload={"error": err, "elapsed_ms": int((time.monotonic() - started) * 1000)},
    )
    return {
        "response": f"Ett serverfel inträffade: {err}",
        "trace_id": trace_id,
        "run_id": run_id,
        "session_id": session["id"],
    }

class AgentRequest(BaseModel):
    query: str
    session_id: str = "main"

@app.post("/api/agent_chat")
async def post_agent_chat(req: AgentRequest):
    """
    Strömmande endpoint (JSONL format) för den tunga, fullfjädrade chatten
    med Tool-calls (Webb-Sök, Metacognition, Kuzu-grafer).
    """
    trace_id = new_trace_id("agent")
    started = time.monotonic()
    session = ensure_session(req.session_id or "main", lane="agent", source="api_agent")
    original_query = str(req.query or "")
    resolved_query, choice_idx = _resolve_numeric_choice(session["id"], original_query)
    run = start_run(
        session["id"],
        workload="agent",
        model="pending",
        provider=os.getenv("NOUSE_LLM_PROVIDER", "ollama"),
        request_chars=len(resolved_query or ""),
        meta={"trace_id": trace_id},
    )
    run_id = str(run.get("run_id") or "")
    client = AsyncOllama()
    agent_models = order_models_for_workload(
        "agent",
        resolve_model_candidates("agent", [CHAT_MODEL]),
    ) or [CHAT_MODEL]
    tool_agent_models, tool_skipped_models = filter_tool_capable_models(agent_models)
    if not tool_agent_models:
        tool_agent_models = list(agent_models)
    record_event(
        trace_id,
        "agent.request",
        endpoint="/api/agent_chat",
        model=CHAT_MODEL,
        payload={
            "query": resolved_query,
            "query_original": original_query,
            "choice_index": choice_idx,
            "attack_plan": build_attack_plan(resolved_query),
            "tool_models": tool_agent_models,
            "tool_skipped_models": tool_skipped_models,
        },
    )

    if _is_background_delegate_request(resolved_query):
        async def stream_delegate():
            delegation = _delegate_request_to_background(
                query=resolved_query,
                session_id=session["id"],
            )
            if delegation.get("ok"):
                answer = (
                    "Perfekt. Jag har skickat detta till bakgrundsagenterna och väckt loopen. "
                    "Du kan fortsätta chatta medan jobbet körs."
                )
                record_event(
                    trace_id,
                    "agent.delegated",
                    endpoint="/api/agent_chat",
                    model="delegate_shortcut",
                    payload={"query": resolved_query, "delegation": delegation},
                )
                finish_run(
                    run_id,
                    status="succeeded",
                    response_chars=len(answer),
                    metrics={
                        "trace_id": trace_id,
                        "model": "delegate_shortcut",
                        "mode": "delegated_background",
                    },
                )
                _ingest_dialogue_memory(
                    session_id=session["id"],
                    query=resolved_query,
                    answer=answer,
                    source=f"agent_live:{session['id']}",
                )
                _remember_exchange(
                    session_id=session["id"],
                    run_id=run_id,
                    query=resolved_query,
                    answer=answer,
                    kind="api_agent_delegate",
                    known_data_sources=["conversation", "system_events", "autonomy_loop"],
                )
                _remember_numbered_options(session["id"], answer)
                yield json.dumps(
                    {
                        "type": "done",
                        "msg": answer,
                        "trace_id": trace_id,
                        "run_id": run_id,
                        "session_id": session["id"],
                        "model": "delegate_shortcut",
                    }
                ) + "\n"
                return

            err = str(delegation.get("error") or "bakgrundsdelegering misslyckades")
            record_event(
                trace_id,
                "agent.error",
                endpoint="/api/agent_chat",
                model="delegate_shortcut",
                payload={"error": err},
            )
            finish_run(
                run_id,
                status="failed",
                error=err,
                metrics={"trace_id": trace_id, "model": "delegate_shortcut"},
            )
            yield json.dumps(
                {
                    "type": "error",
                    "msg": err,
                    "trace_id": trace_id,
                    "run_id": run_id,
                    "session_id": session["id"],
                }
            ) + "\n"

        return StreamingResponse(stream_delegate(), media_type="application/x-ndjson")

    async def stream_agent():
        field = get_field()
        run_finished = False
        used_model = ""
        messages: list[dict[str, Any]] = []
        tool_names: set[str] = set()
        caps: dict[str, Any] = {}
        stats: dict[str, Any] = {"concepts": 0, "relations": 0, "domains": 0}
        action_request = _is_graph_action_request(resolved_query)
        wants_academic_context = _wants_academic_context(resolved_query)
        require_search_tool = _is_search_info_query(resolved_query) and not action_request
        search_enforce_retry_used = False
        search_snapshot_injected = False
        tool_call_observed = False
        action_enforce_retry_used = False
        observed_source_buckets: set[str] = set()
        observed_tool_names: set[str] = set()
        require_graph_source = False
        require_web_source = False
        triangulation_retry_count = 0
        require_tri_output_format = bool(_is_search_info_query(resolved_query) and not action_request)
        tri_output_retry_used = False
        yield json.dumps(
            {
                "type": "status",
                "msg": "Inleder agentic loop...",
                "trace_id": trace_id,
                "run_id": run_id,
                "session_id": session["id"],
            }
        ) + "\n"
        try:
            stats = field.stats()
        except Exception:
            stats = {"concepts": 0, "relations": 0, "domains": 0}
        if _is_greeting_query(resolved_query):
            greeting = _operational_greeting_reply(stats)
            record_event(
                trace_id,
                "agent.done",
                endpoint="/api/agent_chat",
                model="greeting_shortcut",
                payload={
                    "response": greeting,
                    "assumptions": [],
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "mode": "greeting_shortcut",
                },
            )
            finish_run(
                run_id,
                status="succeeded",
                response_chars=len(greeting),
                metrics={
                    "trace_id": trace_id,
                    "model": "greeting_shortcut",
                    "mode": "greeting_shortcut",
                },
            )
            _ingest_dialogue_memory(
                session_id=session["id"],
                query=resolved_query,
                answer=greeting,
                source=f"agent_live:{session['id']}",
            )
            _remember_exchange(
                session_id=session["id"],
                run_id=run_id,
                query=resolved_query,
                answer=greeting,
                kind="api_agent_greeting",
                known_data_sources=["session", "graph_status", "limbic"],
            )
            _remember_numbered_options(session["id"], greeting)
            yield json.dumps(
                {
                    "type": "done",
                    "msg": greeting,
                    "trace_id": trace_id,
                    "run_id": run_id,
                    "session_id": session["id"],
                    "model": "greeting_shortcut",
                }
            ) + "\n"
            return
        if choice_idx is not None:
            yield json.dumps(
                {
                    "type": "status",
                    "msg": f"Tolkar val {choice_idx} utifrån senaste numrerade alternativ.",
                    "trace_id": trace_id,
                }
            ) + "\n"
        if require_search_tool:
            yield json.dumps(
                {
                    "type": "status",
                    "msg": "Search-info mode aktiv: triangulerar modell + graf + webb före slutsvar.",
                    "trace_id": trace_id,
                }
            ) + "\n"
        if action_request:
            yield json.dumps(
                {
                    "type": "status",
                    "msg": "Action mode aktiv: utför grafuppdatering autonomt i denna körning.",
                    "trace_id": trace_id,
                }
            ) + "\n"
        if tool_skipped_models:
            yield json.dumps(
                {
                    "type": "status",
                    "msg": (
                        "Hoppar över modeller utan tool-stöd: "
                        + ", ".join(tool_skipped_models[:4])
                    ),
                    "trace_id": trace_id,
                }
            ) + "\n"

        if _is_identity_query(resolved_query):
            identity_answer = _identity_answer_from_graph(field)
            if identity_answer:
                identity_answer = _ground_capability_denials(identity_answer, caps)
                record_event(
                    trace_id,
                    "agent.done",
                    endpoint="/api/agent_chat",
                    model="graph_identity_snapshot",
                    payload={
                        "response": identity_answer,
                        "assumptions": derive_assumptions(identity_answer),
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                        "mode": "identity_graph",
                    },
                )
                finish_run(
                    run_id,
                    status="succeeded",
                    response_chars=len(identity_answer),
                    metrics={
                        "trace_id": trace_id,
                        "model": "graph_identity_snapshot",
                        "mode": "identity_graph",
                    },
                )
                _ingest_dialogue_memory(
                    session_id=session["id"],
                    query=resolved_query,
                    answer=identity_answer,
                    source=f"agent_live:{session['id']}",
                )
                _remember_exchange(
                    session_id=session["id"],
                    run_id=run_id,
                    query=resolved_query,
                    answer=identity_answer,
                    kind="api_agent_identity",
                    known_data_sources=["conversation", "graph", "identity_graph"],
                )
                _remember_numbered_options(session["id"], identity_answer)
                run_finished = True
                yield json.dumps(
                    {
                        "type": "done",
                        "msg": identity_answer,
                        "trace_id": trace_id,
                        "run_id": run_id,
                        "session_id": session["id"],
                        "model": "graph_identity_snapshot",
                    }
                ) + "\n"
                return

        tool_names = _live_tool_name_set()
        caps = _capability_snapshot(tool_names)
        graph_tools_available = bool(_GRAPH_TOOL_NAMES & tool_names)
        web_tools_available = bool(_WEB_TOOL_NAMES & tool_names) and bool(caps.get("web"))
        require_graph_source = bool(require_search_tool and graph_tools_available)
        require_web_source = bool(require_search_tool and web_tools_available)

        try:
            recent = field.top_relations_by_strength(8)
            context_str = "\n".join(
                [
                    f"{row['src_name']} -[{row['type']}]-> {row['tgt_name']}"
                    for row in recent
                ]
            )
        except Exception:
            context_str = ""
        working_context = _working_memory_context(limit=8) or "(Tomt arbetsminne)"
        tool_inventory = _live_tool_inventory_block()

        system_prompt = (
            "Du är B76: en autonom metakognitiv programagent i detta system.\n"
            "Primär roll i denna kanal: personlig assistent + följeslagare som hjälper användaren nå mål.\n"
            "Agera handlingsinriktat och samarbetsorienterat. Använd verkliga verktyg innan du "
            "säger att något saknas.\n"
            "Interaktionsläge först: håll svar naturliga, mänskligt läsbara och fokuserade på "
            "användarens mål. DÖLJ intern verktygsmekanik, grafteknik och implementation om "
            "användaren inte uttryckligen ber om den nivån.\n"
            "Anta inte att användaren vill skapa noder/relationer i chatten. Gör grafändringar "
            "endast vid explicit begäran om att lagra/uppdatera kunskap i systemet.\n"
            "Om användaren ber dig utföra något, genomför det i bakgrunden via verktyg och "
            "rapportera resultat kortfattat i naturligt språk.\n"
            "Lärande-policy: behandla varje dialog som träningssignal till minne och självlager. "
            "Exponera inte rå intern loggning om användaren inte ber om den.\n"
            f"{_AGENT_IDENTITY_POLICY}\n"
            "Trippel-kunskapsprotokoll:\n"
            "- Källa A: Modellens interna kunskap.\n"
            "- Källa B: Systemets egna data via grafverktyg.\n"
            "- Källa C: Extern evidens via web_search/fetch_url.\n"
            "För öppna analysfrågor ska du triangulera med minst B + C innan slutsvar.\n"
            "För öppna analysfrågor ska slutsvar formateras med rubrikerna: "
            "LLM, System/Graf, Extern, Syntes.\n"
            "Kärnregel: när användaren ber dig utföra något i grafen, gör det via verktyg direkt.\n"
            "Om användaren ber dig lägga till/uppdatera nod eller relation: utför det direkt i samma körning "
            "(upsert_concept/add_relation) och fråga inte om extra bekräftelse.\n"
            "Verktyg som är laddade i denna körning:\n"
            f"{tool_inventory}\n\n"
            f"{_capability_line(caps)}\n"
            "För lokala filer/diskar: använd list_local_mounts, find_local_files, search_local_text "
            "och read_local_file (read-only).\n"
            "Vid öppna search-info-frågor: börja med lätta verktyg (list_domains, concepts_in_domain, "
            "explore_concept, list_local_mounts). Använd search_local_text först när query och roots "
            "är avgränsade.\n"
            "Om användaren ber om kodändring/installation i själva b76-koden: förklara kort att det "
            "kräver utvecklarläge/terminal och ge en konkret genomförandeplan utan generiska disclaimers.\n"
            f"{_living_prompt_block()}\n"
            f"Snabbt arbetsminne (prefrontal):\n{working_context}\n\n"
            f"Grafens relationskontext:\n{context_str}\n"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": resolved_query},
        ]

        if _is_mission_vision_input(resolved_query):
            mission_text = _mission_text_from_query(resolved_query)
            focus_domains = _extract_focus_domains(resolved_query)
            mission_saved = None
            try:
                mission_saved = save_mission(
                    mission_text,
                    north_star=mission_text,
                    focus_domains=focus_domains,
                    kpis=[
                        "new_relations_per_cycle",
                        "discoveries_per_cycle",
                        "knowledge_coverage_complete",
                        "queue_failed_rate",
                    ],
                    constraints=[
                        "traceability_required",
                        "hitl_for_high_risk",
                    ],
                )
            except Exception:
                mission_saved = None

            vision_answer = (
                "Registrerat. Jag behandlar detta som styrande vision för b76: "
                "bygga en verifierbar brain-first AI med mänsklig hjärnlogik, evidens-gated lärande "
                "och spårbar autonomi. Jag fortsätter autonomt enligt missionen, journalför varje steg "
                "och använder HITL vid hög risk."
            )
            if mission_saved:
                ver = int(mission_saved.get("version", 0) or 0)
                focus = mission_saved.get("focus_domains") or []
                focus_txt = f" Fokus: {', '.join(focus[:4])}." if focus else ""
                vision_answer += f" Mission uppdaterad (v{ver}).{focus_txt}"
            try:
                enqueue_system_event(
                    resolved_query,
                    session_id=session["id"],
                    source="operator_vision",
                    context_key="mission_vision",
                )
                if mission_saved:
                    request_wake(
                        reason="mission_updated",
                        session_id=session["id"],
                        source="operator_vision",
                    )
            except Exception:
                pass
            record_event(
                trace_id,
                "agent.done",
                endpoint="/api/agent_chat",
                model="mission_vision_shortcut",
                payload={
                    "response": vision_answer,
                    "assumptions": derive_assumptions(vision_answer),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "mode": "mission_vision",
                },
            )
            finish_run(
                run_id,
                status="succeeded",
                response_chars=len(vision_answer),
                metrics={
                    "trace_id": trace_id,
                    "model": "mission_vision_shortcut",
                    "mode": "mission_vision",
                },
            )
            _ingest_dialogue_memory(
                session_id=session["id"],
                query=resolved_query,
                answer=vision_answer,
                source=f"agent_live:{session['id']}",
            )
            _remember_exchange(
                session_id=session["id"],
                run_id=run_id,
                query=resolved_query,
                answer=vision_answer,
                kind="api_agent_mission_vision",
                known_data_sources=["conversation", "mission"],
            )
            _remember_numbered_options(session["id"], vision_answer)
            run_finished = True
            yield json.dumps(
                {
                    "type": "done",
                    "msg": vision_answer,
                    "trace_id": trace_id,
                    "run_id": run_id,
                    "session_id": session["id"],
                    "model": "mission_vision_shortcut",
                }
            ) + "\n"
            return

        if _is_simple_fact_query(resolved_query):
            fact_messages = [
                {
                    "role": "system",
                    "content": (
                        "Du svarar på enkla faktafrågor.\n"
                        "Regler:\n"
                        "1. Svara på svenska med exakt EN kort mening.\n"
                        "2. Svara endast på det som frågades.\n"
                        "3. Lägg inte till biografiska sidodetaljer om de inte efterfrågas.\n"
                        "4. Om du är osäker: säg tydligt att du är osäker istället för att gissa."
                        f"\n\n{_AGENT_IDENTITY_POLICY}\n{_living_prompt_block()}"
                    ),
                },
                {"role": "user", "content": resolved_query},
            ]
            try:
                fact_resp = None
                last_model_error: Exception | None = None
                fact_attempts: list[dict[str, Any]] = []
                fact_models = order_models_for_workload(
                    "agent",
                    resolve_model_candidates("agent", [FAST_CHAT_MODEL] + list(agent_models)),
                ) or [FAST_CHAT_MODEL] + list(agent_models)
                seen_models: set[str] = set()
                for model in fact_models:
                    if model in seen_models:
                        continue
                    seen_models.add(model)
                    try:
                        fact_resp = await client.chat.completions.create(
                            model=model,
                            messages=fact_messages,
                            b76_meta={
                                "workload": "agent",
                                "session_id": session["id"],
                                "run_id": run_id,
                            },
                        )
                        used_model = model
                        record_model_result("agent", model, success=True, timeout=False)
                        break
                    except Exception as model_error:
                        timed_out = "timeout" in str(model_error).lower()
                        record_model_result("agent", model, success=False, timeout=timed_out)
                        last_model_error = model_error
                        fact_attempts.append(
                            {
                                "model": model,
                                "reason": _classify_model_failover_reason(model_error),
                                "error": str(model_error),
                            }
                        )
                        record_event(
                            trace_id,
                            "agent.model_error",
                            endpoint="/api/agent_chat",
                            model=model,
                            payload={"error": str(model_error), "timeout": timed_out},
                        )

                if fact_resp is None:
                    msg = _build_all_models_failed_error("agent/fact", fact_attempts)
                    if last_model_error is not None:
                        raise RuntimeError(msg) from last_model_error
                    raise RuntimeError(msg)

                answer = (fact_resp.message.content or "").strip()
                if not answer:
                    answer = "Jag är osäker på svaret just nu."
                answer = _ground_capability_denials(answer, caps)

                record_event(
                    trace_id,
                    "agent.done",
                    endpoint="/api/agent_chat",
                    model=used_model or CHAT_MODEL,
                    payload={
                        "response": answer,
                        "assumptions": derive_assumptions(answer),
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                        "mode": "fact",
                    },
                )
                finish_run(
                    run_id,
                    status="succeeded",
                    response_chars=len(answer),
                    metrics={
                        "trace_id": trace_id,
                        "model": used_model or CHAT_MODEL,
                        "mode": "fact",
                    },
                )
                _ingest_dialogue_memory(
                    session_id=session["id"],
                    query=resolved_query,
                    answer=answer,
                    source=f"agent_live:{session['id']}",
                )
                _remember_exchange(
                    session_id=session["id"],
                    run_id=run_id,
                    query=resolved_query,
                    answer=answer,
                    kind="api_agent_fact",
                    known_data_sources=["conversation", f"model:{used_model or CHAT_MODEL}"],
                )
                _remember_numbered_options(session["id"], answer)
                run_finished = True
                yield json.dumps(
                    {
                        "type": "done",
                        "msg": answer,
                        "trace_id": trace_id,
                        "run_id": run_id,
                        "session_id": session["id"],
                        "model": used_model or CHAT_MODEL,
                    }
                ) + "\n"
                return
            except Exception as e:
                record_event(
                    trace_id,
                    "agent.error",
                    endpoint="/api/agent_chat",
                    model=used_model or CHAT_MODEL,
                    payload={
                        "error": str(e),
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                        "mode": "fact",
                    },
                )
                finish_run(
                    run_id,
                    status="failed",
                    error=str(e),
                    metrics={"trace_id": trace_id, "model": used_model or CHAT_MODEL, "mode": "fact"},
                )
                run_finished = True
                yield json.dumps(
                    {
                        "type": "error",
                        "msg": str(e),
                        "trace_id": trace_id,
                        "run_id": run_id,
                        "session_id": session["id"],
                    }
                ) + "\n"
                return

        call_idx = 0
        empty_reply_retry_used = False
        try:
            while True:
                call_idx += 1
                record_event(
                    trace_id,
                    "agent.llm_call",
                    endpoint="/api/agent_chat",
                    model=used_model or CHAT_MODEL,
                    payload={"iteration": call_idx, "messages": len(messages)},
                )
                resp = None
                last_model_error: Exception | None = None
                model_attempts: list[dict[str, Any]] = []
                current_tool_models, _current_skipped = filter_tool_capable_models(agent_models)
                if not current_tool_models:
                    current_tool_models = list(agent_models)
                for model in current_tool_models:
                    try:
                        resp = await client.chat.completions.create(
                            model=model,
                            messages=messages,
                            tools=get_live_tools(),
                            b76_meta={
                                "workload": "agent",
                                "session_id": session["id"],
                                "run_id": run_id,
                            },
                        )
                        used_model = model
                        mark_model_tools_supported(model)
                        record_model_result("agent", model, success=True, timeout=False)
                        break
                    except Exception as model_error:
                        timed_out = "timeout" in str(model_error).lower()
                        record_model_result("agent", model, success=False, timeout=timed_out)
                        last_model_error = model_error
                        if is_tools_unsupported_error(model_error):
                            mark_model_tools_unsupported(model, reason=str(model_error))
                        model_attempts.append(
                            {
                                "model": model,
                                "reason": _classify_model_failover_reason(model_error),
                                "error": str(model_error),
                            }
                        )
                        record_event(
                            trace_id,
                            "agent.model_error",
                            endpoint="/api/agent_chat",
                            model=model,
                            payload={"error": str(model_error), "timeout": timed_out},
                        )
                if resp is None:
                    msg = _build_all_models_failed_error("agent/tools", model_attempts)
                    if last_model_error is not None:
                        raise RuntimeError(msg) from last_model_error
                    raise RuntimeError(msg)
                msg = resp.message

                if msg.tool_calls:
                    tool_call_observed = True
                    messages.append(msg.model_dump())
                    for tool in msg.tool_calls:
                        name = tool.function.name
                        args = tool.function.arguments
                        observed_source_buckets.add(_tool_source_bucket(name))
                        observed_tool_names.add(str(name or ""))
                        record_event(
                            trace_id,
                            "agent.tool_call",
                            endpoint="/api/agent_chat",
                            model=used_model or CHAT_MODEL,
                            payload={"name": name, "args": args},
                        )
                        yield json.dumps(
                            {"type": "tool", "name": name, "args": args, "trace_id": trace_id}
                        ) + "\n"
                        try:
                            # Bygg in mock _announce_growth för chat.py's execute_tool kompatibilitet ifall nödvändigt,
                            # men vi hanterar allmän execute_tool smidigt
                            result = execute_tool(field, name, args)
                            messages.append({
                                "role": "tool",
                                "content": json.dumps(result, ensure_ascii=False)
                            })
                            record_event(
                                trace_id,
                                "agent.tool_result",
                                endpoint="/api/agent_chat",
                                model=used_model or CHAT_MODEL,
                                payload={"name": name, "result": result},
                            )
                            yield json.dumps(
                                {
                                    "type": "tool_result",
                                    "name": name,
                                    "result": result,
                                    "trace_id": trace_id,
                                }
                            ) + "\n"
                        except Exception as e:
                            err = {"error": str(e)}
                            messages.append({"role": "tool", "content": json.dumps(err)})
                            record_event(
                                trace_id,
                                "agent.tool_error",
                                endpoint="/api/agent_chat",
                                model=used_model or CHAT_MODEL,
                                payload={"name": name, "error": str(e)},
                            )
                            yield json.dumps(
                                {
                                    "type": "tool_error",
                                    "name": name,
                                    "error": str(e),
                                    "trace_id": trace_id,
                                }
                            ) + "\n"
                else:
                    answer = (msg.content or "").strip()
                    if action_request:
                        has_graph_write_call = bool(
                            {"upsert_concept", "add_relation"} & observed_tool_names
                        )
                        has_web_call = bool(
                            {"web_search", "fetch_url"} & observed_tool_names
                        )
                        looks_like_followup_prompt = _looks_like_confirmation_prompt(answer)
                        needs_more_action = (
                            (not has_graph_write_call)
                            or (wants_academic_context and bool(caps.get("web")) and (not has_web_call))
                            or looks_like_followup_prompt
                        )
                        if needs_more_action and not action_enforce_retry_used:
                            action_enforce_retry_used = True
                            missing: list[str] = []
                            if not has_graph_write_call:
                                missing.append("graph_write")
                            if wants_academic_context and bool(caps.get("web")) and (not has_web_call):
                                missing.append("web_evidence")
                            if looks_like_followup_prompt:
                                missing.append("no_followup_questions")
                            record_event(
                                trace_id,
                                "agent.action_enforced_retry",
                                endpoint="/api/agent_chat",
                                model=used_model or CHAT_MODEL,
                                payload={
                                    "iteration": call_idx,
                                    "missing": missing,
                                    "observed_tool_names": sorted(observed_tool_names),
                                },
                            )
                            messages.append(msg.model_dump())
                            messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "Utför uppgiften nu utan följdfrågor.\n"
                                        "Minimikrav:\n"
                                        "1) uppdatera grafen med upsert_concept och/eller add_relation,\n"
                                        "2) om akademisk kontext efterfrågas: använd web_search/fetch_url,\n"
                                        "3) svara med exakt vad som ändrades (noder, relationer, evidenskällor).\n"
                                        "Fråga inte användaren om bekräftelse."
                                    ),
                                }
                            )
                            yield json.dumps(
                                {
                                    "type": "status",
                                    "msg": "Enforcer: kräver direkt verktygs-exekvering (graph write + evidens).",
                                    "trace_id": trace_id,
                                }
                            ) + "\n"
                            continue
                    if require_search_tool:
                        missing_sources = _missing_triangulation_sources(
                            observed_source_buckets,
                            require_graph=require_graph_source,
                            require_web=require_web_source,
                        )
                        if missing_sources:
                            if triangulation_retry_count < 1:
                                triangulation_retry_count += 1
                                search_enforce_retry_used = True
                                record_event(
                                    trace_id,
                                    "agent.search_enforced_retry",
                                    endpoint="/api/agent_chat",
                                    model=used_model or CHAT_MODEL,
                                    payload={
                                        "iteration": call_idx,
                                        "missing_sources": missing_sources,
                                        "observed_sources": sorted(observed_source_buckets),
                                    },
                                )
                                messages.append(msg.model_dump())
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": (
                                            "Detta är en öppen fråga och du saknar triangulering från: "
                                            f"{', '.join(missing_sources)}. "
                                            "Kör nu verktyg för båda källor (graf + webb när tillgängligt), "
                                            "och svara sedan med tydlig separation mellan fakta och antaganden."
                                        ),
                                    }
                                )
                                yield json.dumps(
                                    {
                                        "type": "status",
                                        "msg": (
                                            "Enforcer: saknad triangulering från "
                                            f"{', '.join(missing_sources)}. Begär nya tool-calls."
                                        ),
                                        "trace_id": trace_id,
                                    }
                                ) + "\n"
                                continue
                            if not search_snapshot_injected:
                                search_snapshot_injected = True
                                snapshot = _auto_triangulation_snapshot(
                                    field=field,
                                    query=resolved_query,
                                    need_graph=("graf" in missing_sources),
                                    need_web=("webb" in missing_sources),
                                )
                                yield json.dumps(
                                    {
                                        "type": "status",
                                        "msg": "Auto-triangulation: injicerar graf/web-snapshot för slutsvar.",
                                        "trace_id": trace_id,
                                    }
                                ) + "\n"
                                messages.append(msg.model_dump())
                                messages.append(
                                    {
                                        "role": "system",
                                        "content": (
                                            "Systemet har kört en automatisk trianguleringssnapshot:\n"
                                            f"{snapshot}\n"
                                            "Använd detta som evidensbas i svaret."
                                        ),
                                    }
                                )
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": (
                                            "Svara nu kort och konkret med tre tydliga delar: "
                                            "Modellkunskap, System/Graf, Extern evidens, följt av en syntes."
                                        ),
                                    }
                                )
                                continue
                        require_search_tool = False
                    if not answer:
                        record_event(
                            trace_id,
                            "agent.empty_reply",
                            endpoint="/api/agent_chat",
                            model=used_model or CHAT_MODEL,
                            payload={"iteration": call_idx},
                        )
                        if not empty_reply_retry_used:
                            empty_reply_retry_used = True
                            messages.append(msg.model_dump())
                            messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "Svara nu användaren med ett kort, tydligt svar på svenska "
                                        "baserat på verktygsresultaten."
                                    ),
                                }
                            )
                            continue
                        raise RuntimeError("Agenten returnerade tomt svar utan tool_calls.")
                    if require_tri_output_format and not _looks_like_triangulated_response(answer):
                        if not tri_output_retry_used:
                            tri_output_retry_used = True
                            messages.append(msg.model_dump())
                            messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "Formatera om svaret exakt med fyra rubriker i denna ordning: "
                                        "LLM, System/Graf, Extern, Syntes. "
                                        "Använd 1-3 korta punkter per rubrik. "
                                        "Om extern evidens saknas, skriv tydligt varför."
                                    ),
                                }
                            )
                            yield json.dumps(
                                {
                                    "type": "status",
                                    "msg": "Enforcer: omskriver till LLM/System-Graf/Extern/Syntes-format.",
                                    "trace_id": trace_id,
                                }
                            ) + "\n"
                            continue
                    answer = _ground_capability_denials(answer, caps)

                    messages.append({"role": "assistant", "content": answer})
                    record_event(
                        trace_id,
                        "agent.done",
                        endpoint="/api/agent_chat",
                        model=used_model or CHAT_MODEL,
                        payload={
                            "response": answer,
                            "assumptions": derive_assumptions(answer),
                            "elapsed_ms": int((time.monotonic() - started) * 1000),
                        },
                    )
                    finish_run(
                        run_id,
                        status="succeeded",
                        response_chars=len(answer),
                        metrics={"trace_id": trace_id, "model": used_model or CHAT_MODEL},
                    )
                    _ingest_dialogue_memory(
                        session_id=session["id"],
                        query=resolved_query,
                        answer=answer,
                        source=f"agent_live:{session['id']}",
                    )
                    # Autonom kunskapsuppdatering: ingest:a dialogen i bakgrunden
                    # så graf/minne kan växa även utan explicit "lägg till nod"-kommando.
                    try:
                        asyncio.create_task(
                            post_ingest(
                                IngestRequest(
                                    text=f"Fråga: {resolved_query}\nSvar: {answer}",
                                    source=f"agent_chat:{session['id']}",
                                )
                            )
                        )
                    except Exception:
                        pass
                    _remember_exchange(
                        session_id=session["id"],
                        run_id=run_id,
                        query=resolved_query,
                        answer=answer,
                        kind="api_agent",
                        known_data_sources=(
                            ["conversation", f"model:{used_model or CHAT_MODEL}"]
                            + sorted(observed_source_buckets)
                        ),
                    )
                    _remember_numbered_options(session["id"], answer)
                    run_finished = True
                    yield json.dumps(
                        {
                            "type": "done",
                            "msg": answer,
                            "trace_id": trace_id,
                            "run_id": run_id,
                            "session_id": session["id"],
                            "model": used_model or CHAT_MODEL,
                        }
                    ) + "\n"
                    break
        except Exception as e:
            record_event(
                trace_id,
                "agent.error",
                endpoint="/api/agent_chat",
                model=used_model or CHAT_MODEL,
                payload={"error": str(e), "elapsed_ms": int((time.monotonic() - started) * 1000)},
            )
            finish_run(
                run_id,
                status="failed",
                error=str(e),
                metrics={"trace_id": trace_id, "model": used_model or CHAT_MODEL},
            )
            run_finished = True
            yield json.dumps(
                {
                    "type": "error",
                    "msg": str(e),
                    "trace_id": trace_id,
                    "run_id": run_id,
                    "session_id": session["id"],
                }
            ) + "\n"
        finally:
            if not run_finished:
                finish_run(
                    run_id,
                    status="failed",
                    error="stream_aborted",
                    metrics={"trace_id": trace_id},
                )

    return StreamingResponse(stream_agent(), media_type="application/x-ndjson")

# ── Public Brain API (used by NouseBrainHTTP in inject.py) ───────────────────

class _BrainQueryRequest(BaseModel):
    question: str
    top_k: int = 6

class _BrainLearnRequest(BaseModel):
    prompt: str
    response: str = ""
    source: str = "conversation"

class _BrainAddRequest(BaseModel):
    src: str
    rel_type: str
    tgt: str
    why: str = ""
    evidence_score: float = 0.6


@app.post("/api/brain/query")
def brain_query(req: _BrainQueryRequest):
    """
    Run brain.query() via HTTP — used by NouseBrainHTTP when daemon is running.
    Returns QueryResult as JSON so external callers never touch KuzuDB directly.
    """
    from nouse.inject import NouseBrain, _rows_to_axioms
    field = get_field()
    # Reuse NouseBrain logic without opening a second DB connection
    brain = object.__new__(NouseBrain)
    brain._field = field
    brain._read_only = True
    brain._input_hooks = []
    brain._output_hooks = []
    result = brain.query(req.question, top_k=req.top_k)
    return {
        "query":         result.query,
        "confidence":    result.confidence,
        "has_knowledge": result.has_knowledge,
        "domains":       result.domains,
        "concepts": [
            {
                "name":          c.name,
                "summary":       c.summary,
                "claims":        c.claims,
                "evidence_refs": c.evidence_refs,
                "related_terms": c.related_terms,
                "uncertainty":   c.uncertainty,
                "revision_count": c.revision_count,
            }
            for c in result.concepts
        ],
        "axioms": [
            {
                "src":      a.src,
                "rel":      a.rel,
                "tgt":      a.tgt,
                "evidence": a.evidence,
                "flagged":  a.flagged,
                "why":      a.why,
                "strength": a.strength,
            }
            for a in result.axioms
        ],
    }


@app.post("/api/brain/learn")
async def brain_learn(req: _BrainLearnRequest):
    """Extract knowledge from a prompt+response pair and write to graph."""
    from nouse.daemon.extractor import extract_relations_with_diagnostics
    from nouse.daemon.write_queue import enqueue_write
    field = get_field()
    text = (req.prompt + "\n" + req.response).strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    meta = {"source": req.source, "path": req.source}
    try:
        rels, _diag = await extract_relations_with_diagnostics(text, meta)

        async def _write():
            for r in rels:
                field.add_concept(r["src"], r.get("domain_src", "external"), source=req.source)
                field.add_concept(r["tgt"], r.get("domain_tgt", "external"), source=req.source)
                field.add_relation(r["src"], r["type"], r["tgt"],
                                   why=r.get("why", ""),
                                   evidence_score=float(r.get("evidence_score") or 0.5))
            return len(rels)

        added = await enqueue_write(_write())
        return {"ok": True, "relations_added": added}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/brain/add")
async def brain_add(req: _BrainAddRequest):
    """Directly add a single relation to the graph."""
    from nouse.daemon.write_queue import enqueue_write
    field = get_field()

    async def _write():
        field.add_relation(req.src, req.rel_type, req.tgt,
                           why=req.why,
                           evidence_score=max(0.0, min(1.0, req.evidence_score)))

    try:
        await enqueue_write(_write())
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def start_server(host="127.0.0.1", port=8765):
    uvicorn.run("nouse.web.server:app", host=host, port=port, reload=False)

main = start_server
