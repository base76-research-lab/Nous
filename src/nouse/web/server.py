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
from nouse.config.env import load_env_files
from nouse.config.paths import nouse_home_root, path_from_env
from nouse.limbic.signals import load_state
from nouse.memory.store import MemoryStore
from nouse.ollama_client.client import AsyncOllama
from nouse.llm.model_capabilities import (
    filter_tool_capable_models,
    is_tools_unsupported_error,
    mark_model_tools_supported,
    mark_model_tools_unsupported,
)
from nouse.llm.model_router import order_models_for_workload, record_model_result, router_status
from nouse.llm.policy import (
    get_workload_policy,
    load_policy,
    reset_policy,
    resolve_model_candidates,
    set_workload_candidates,
)
from nouse.llm.usage import list_usage, usage_summary
from nouse.self_layer import (
    append_identity_memory,
    identity_prompt_fragment,
    load_living_core,
    operator_support_prompt_fragment,
    operator_support_snapshot,
    record_self_training_iteration,
)
from nouse.persona import (
    agent_identity_policy as _persona_identity_policy,
    assistant_entity_name as _persona_entity_name,
    assistant_greeting as _persona_greeting,
    persona_prompt_fragment as _persona_prompt_fragment,
)

MODEL = (
    os.getenv("NOUSE_CHAT_MODEL")
    or os.getenv("NOUSE_OLLAMA_MODEL")
    or "qwen3.5:latest"
).strip()
CHAT_FALLBACK_MODEL = (os.getenv("NOUSE_CHAT_FALLBACK_MODEL") or "").strip()
CHAT_CANDIDATES_RAW = (os.getenv("NOUSE_MODEL_CANDIDATES_CHAT") or "").strip()
FAST_CHAT_MODEL = (os.getenv("NOUSE_CHAT_FAST_MODEL") or MODEL).strip()


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        value = float(raw) if raw else float(default)
    except (TypeError, ValueError):
        value = float(default)
    return max(float(minimum), value)


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw) if raw else int(default)
    except (TypeError, ValueError):
        value = int(default)
    return max(int(minimum), value)


FAST_DELEGATE_ENABLED = str(os.getenv("NOUSE_CHAT_FAST_DELEGATE", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
FAST_DELEGATE_IMPLICIT = str(os.getenv("NOUSE_CHAT_FAST_DELEGATE_IMPLICIT", "0")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
FAST_DELEGATE_MIN_WORDS = max(8, int(os.getenv("NOUSE_CHAT_FAST_DELEGATE_MIN_WORDS", "18")))
AGENT_LLM_TIMEOUT_SEC = _env_float("NOUSE_AGENT_LLM_TIMEOUT_SEC", 75.0, minimum=1.0)
AGENT_LLM_RETRIES = _env_int("NOUSE_AGENT_LLM_RETRIES", 1, minimum=0)
INGEST_TIMEOUT_SEC = float(os.getenv("NOUSE_INGEST_TIMEOUT_SEC", "20"))
CAPTURE_QUEUE_DIR = path_from_env("NOUSE_CAPTURE_QUEUE_DIR", "capture_queue")
GRAPH_CENTER_STATE_PATH = Path(
    os.getenv(
        "NOUSE_GRAPH_CENTER_PATH",
        str(nouse_home_root() / "graph_center.json"),
    )
).expanduser()
QUEUE_DEFAULT_TASK_TIMEOUT_SEC = float(os.getenv("NOUSE_RESEARCH_QUEUE_TASK_TIMEOUT_SEC", "180"))
QUEUE_DEFAULT_EXTRACT_TIMEOUT_SEC = float(os.getenv("NOUSE_RESEARCH_QUEUE_EXTRACT_TIMEOUT_SEC", "30"))
from nouse.daemon.main import brain_loop
from nouse.daemon.journal import latest_journal_file
from nouse.cli.chat import get_live_tools, execute_tool, CHAT_MODEL
from nouse.metacognition.snapshot import create_snapshot
from nouse.metacognition.snapshot import list_snapshots, restore_snapshot
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


def _runtime_mode() -> str:
    return str(os.getenv("NOUSE_MODE", "project")).strip().lower()


def _is_personal_runtime_mode() -> bool:
    return _runtime_mode() == "personal"
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


def _order_models_with_sticky_primary(workload: str, candidates: list[str]) -> list[str]:
    """
    Router-sortera modeller men behåll explicit primär kandidat först.
    Detta gör att användarens valda main chat-modell inte "skrivs över"
    av historisk router-ranking, samtidigt som fallback-kedjan behålls.
    """
    dedup: list[str] = []
    seen: set[str] = set()
    for raw in candidates or []:
        model = str(raw or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        dedup.append(model)
    if len(dedup) <= 1:
        return dedup

    ranked = order_models_for_workload(workload, dedup)
    if not ranked:
        return dedup

    primary = dedup[0]
    if primary in ranked:
        ranked = [primary] + [m for m in ranked if m != primary]
    else:
        ranked = [primary] + ranked
    return ranked


def _chat_model_candidates() -> list[str]:
    defaults: list[str] = []
    defaults.extend(_split_models(CHAT_CANDIDATES_RAW))
    defaults.append(MODEL)
    if CHAT_FALLBACK_MODEL:
        defaults.append(CHAT_FALLBACK_MODEL)
    defaults = resolve_model_candidates("chat", defaults)
    return _order_models_with_sticky_primary("chat", defaults)


def _living_prompt_block(query: str = "") -> str:
    try:
        state = load_living_core()
    except Exception:
        state = {}
    return identity_prompt_fragment(state) + "\n\n" + operator_support_prompt_fragment(state, query=query)


def _infer_capability_flags(query: str) -> dict[str, bool]:
    text = str(query or "").strip().lower()
    tokens = set(re.findall(r"[0-9a-zåäö_]+", text))
    needs_web = bool(
        _extract_urls_from_text(text)
        or any(tok in tokens for tok in {"senaste", "latest", "nyheter", "news", "today", "todays", "web", "internet"})
        or "web search" in text
        or "search web" in text
    )
    needs_files = any(tok in tokens for tok in {"fil", "filer", "file", "files", "lokalt", "local", "pdf", "paper", "papers", "mapp", "mappar", "disk", "dator"})
    needs_memory_write = (
        "kom ihåg" in text
        or "remember" in text
        or "spara" in text
        or "lägg detta i minnet" in text
    )
    needs_action = any(tok in tokens for tok in {"bygg", "build", "fix", "implementera", "ändra", "update", "kör", "run", "execute", "skapa"})
    return {
        "needs_web": needs_web,
        "needs_files": needs_files,
        "needs_memory_write": needs_memory_write,
        "needs_action": needs_action,
    }


def _capability_route_plan(
    query: str,
    *,
    state: str = "",
    needs_web: bool | None = None,
    needs_files: bool | None = None,
    needs_memory_write: bool | None = None,
    needs_action: bool | None = None,
    explicit_tri_request: bool = False,
    explicit_tool_mode_request: bool = False,
    auto_mcp_request: bool = False,
    action_request: bool = False,
    query_urls: list[str] | None = None,
    preferred_skill: str = "",
) -> dict[str, Any]:
    raw_query = str(query or "").strip()
    resolved_preferred_skill = str(preferred_skill or "").strip()
    if not resolved_preferred_skill:
        parsed_skill, stripped_query = _extract_explicit_skill_request(raw_query)
        if parsed_skill:
            resolved_preferred_skill = parsed_skill
            if stripped_query:
                raw_query = stripped_query
    inferred = _infer_capability_flags(raw_query)
    merged_flags = {
        "needs_web": bool(inferred["needs_web"] if needs_web is None else needs_web)
        or bool(explicit_tri_request)
        or bool(auto_mcp_request)
        or bool(query_urls),
        "needs_files": bool(inferred["needs_files"] if needs_files is None else needs_files),
        "needs_memory_write": bool(
            inferred["needs_memory_write"] if needs_memory_write is None else needs_memory_write
        ),
        "needs_action": bool(inferred["needs_action"] if needs_action is None else needs_action)
        or bool(action_request),
    }
    force_tooling = bool(
        action_request
        or explicit_tri_request
        or explicit_tool_mode_request
        or auto_mcp_request
    )
    try:
        from nouse.capability.graph import build_route_plan

        route_plan = build_route_plan(
            raw_query,
            state=state,
            needs_web=merged_flags["needs_web"],
            needs_files=merged_flags["needs_files"],
            needs_memory_write=merged_flags["needs_memory_write"],
            needs_action=merged_flags["needs_action"],
            force_tooling=force_tooling,
            preferred_skill=resolved_preferred_skill,
            probe_models=False,
        )
    except Exception:
        route_plan = {}

    tool_names: list[str] = [str(x) for x in (route_plan.get("tool_names") or []) if str(x).strip()]
    if explicit_tri_request:
        tool_names.extend(sorted(_GRAPH_TOOL_NAMES))
    if action_request:
        tool_names.extend(["upsert_concept", "add_relation", "explore_concept"])
    if auto_mcp_request and query_urls:
        tool_names.append("fetch_url")

    dedup_tools: list[str] = []
    seen: set[str] = set()
    for name in tool_names:
        clean = str(name or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        dedup_tools.append(clean)

    route_plan = dict(route_plan)
    route_plan.setdefault("skill", "")
    route_plan.setdefault("skill_score", 0.0)
    route_plan.setdefault("skill_reasons", [])
    route_plan.setdefault("workload", "chat")
    route_plan.setdefault("provider", "auto")
    route_plan.setdefault("governance", "default")
    route_plan["intent"] = raw_query
    route_plan["state"] = state
    route_plan["preferred_skill"] = resolved_preferred_skill
    route_plan["flags"] = merged_flags
    route_plan["force_tooling"] = force_tooling
    route_plan["tool_names"] = dedup_tools
    route_plan["tool_mode"] = bool(route_plan.get("tool_mode")) or bool(force_tooling or dedup_tools)
    if route_plan.get("tool_mode") and not str(route_plan.get("workload") or "").strip():
        route_plan["workload"] = "agent"
    return route_plan


def _capability_route_prompt_block(query: str) -> str:
    raw = str(query or "").strip()
    if not raw:
        return ""
    flags = _infer_capability_flags(raw)
    current_state = ""
    support: dict[str, Any] = {}
    try:
        living = load_living_core()
        support = operator_support_snapshot(raw, living)
        current_state = str(support.get("route_state") or "").strip()
    except Exception:
        current_state = ""
        support = {}
    route = _capability_route_plan(raw, state=current_state)
    skill_name = str(route.get("skill") or "").strip()
    score = float(route.get("skill_score", 0.0) or 0.0)
    if not any(flags.values()) and skill_name in {"", "dialogue.personal"} and score < 0.28:
        return ""
    tool_names = [str(x) for x in (route.get("tool_names") or []) if str(x).strip()]
    reasons = [str(x) for x in (route.get("skill_reasons") or []) if str(x).strip()]
    tools_preview = ", ".join(tool_names[:6]) if tool_names else "-"
    reasons_preview = ", ".join(reasons[:6]) if reasons else "default_fit"
    support_line = ""
    if str(support.get("response_mode") or "").strip() in {"recovery", "rescue"}:
        support_line = (
            f"\n- Operatorstöd: {str(support.get('response_mode') or '')} "
            f"via {str(support.get('intervention') or '')}"
        )
    return (
        "Capability routing hint:\n"
        f"- Föreslagen skill: {skill_name or '-'} (score={score:.2f})\n"
        f"- Föreslagen workload/provider: {str(route.get('workload') or '-')} / {str(route.get('provider') or '-')}\n"
        f"- Föreslagna verktyg: {tools_preview}\n"
        f"- Governance: {str(route.get('governance') or '-')}\n"
        f"- Signal: {reasons_preview}\n"
        f"{support_line}"
        "Använd detta som route-hint, inte som tvång. Följ faktisk intention före snygg routing."
    )


def _chat_control_snapshot(
    *,
    query: str = "",
    state: str = "",
    needs_web: bool | None = None,
    needs_files: bool | None = None,
    needs_memory_write: bool | None = None,
    needs_action: bool | None = None,
) -> dict[str, Any]:
    raw_query = str(query or "").strip()
    living_state = ""
    support: dict[str, Any] = {}
    if state:
        living_state = str(state).strip()
    else:
        try:
            living = load_living_core()
            support = operator_support_snapshot(raw_query, living)
            living_state = str(support.get("route_state") or "").strip()
        except Exception:
            living_state = ""
            support = {}

    route = _capability_route_plan(
        raw_query,
        state=living_state,
        needs_web=needs_web,
        needs_files=needs_files,
        needs_memory_write=needs_memory_write,
        needs_action=needs_action,
    )
    flags = dict(route.get("flags") or {})

    try:
        from nouse.capability import build_capability_graph

        snapshot = build_capability_graph(probe_models=False)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "query": raw_query,
            "state": living_state,
            "flags": flags,
        }

    counts = snapshot.get("counts") if isinstance(snapshot.get("counts"), dict) else {}
    planes = snapshot.get("planes") if isinstance(snapshot.get("planes"), dict) else {}
    chosen_workload = str(route.get("workload") or "chat").strip() or "chat"

    return {
        "ok": True,
        "query": raw_query,
        "state": living_state,
        "flags": flags,
        "support": {
            "support_state": str(support.get("support_state") or ""),
            "response_mode": str(support.get("response_mode") or ""),
            "intervention": str(support.get("intervention") or ""),
            "next_step_hint": str(support.get("next_step_hint") or ""),
            "anchors": list(support.get("anchors") or []),
        },
        "counts": {
            "planes": int(counts.get("planes", 0) or 0),
            "bridges": int(counts.get("bridges", 0) or 0),
            "tools": int(counts.get("tools", 0) or 0),
            "skills": int(counts.get("skills", 0) or 0),
            "providers": int(counts.get("providers", 0) or 0),
            "models": int(counts.get("models", 0) or 0),
        },
        "route": {
            "skill": str(route.get("skill") or ""),
            "skill_score": float(route.get("skill_score", 0.0) or 0.0),
            "skill_description": "",
            "skill_reasons": list(route.get("skill_reasons") or []),
            "workload": chosen_workload,
            "provider": str(route.get("provider") or ""),
            "candidates": list(route.get("model_candidates") or []),
            "tools": list(route.get("tool_names") or []),
            "governance": str(route.get("governance") or ""),
            "tool_mode": bool(route.get("tool_mode")),
            "top_skill_candidates": list(route.get("top_skill_candidates") or []),
        },
        "workload_policies": {
            "chat": get_workload_policy("chat"),
            "agent": get_workload_policy("agent"),
            chosen_workload: get_workload_policy(chosen_workload),
        },
        "runtime": {
            "chosen_workload": _model_health_for_workload(chosen_workload),
            "chat": _model_health_for_workload("chat"),
            "agent": _model_health_for_workload("agent"),
        },
        "planes": {
            "model_workloads": list(((planes.get("opencode_model_plane") or {}).get("workloads") or [])),
            "skill_preview": [str((row or {}).get("name") or "") for row in (((planes.get("skill_plane") or {}).get("skills") or [])[:8])],
            "tool_preview": [str((row or {}).get("name") or "") for row in (((planes.get("mcp_plane") or {}).get("tools") or [])[:10])],
        },
    }


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


def _assistant_entity_name() -> str:
    return _persona_entity_name()


def _agent_identity_policy() -> str:
    return _persona_identity_policy()


def _live_tool_inventory_block(
    max_items: int = 80,
    *,
    tool_schemas: list[dict[str, Any]] | None = None,
) -> str:
    """Kort, verklighetsbaserad verktygsöversikt från aktuell runtime."""
    if tool_schemas is None:
        try:
            tools = get_live_tools()
        except Exception:
            tools = []
    else:
        tools = list(tool_schemas or [])
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

app = FastAPI(title=f"{_assistant_entity_name()} Dashboard", lifespan=lifespan)

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
def get_bisoc(tau: float = 0.55, epsilon: float = 2.0, max_domains: int = 50,
              priority_domains: str | None = None):
    """Bisociationskandidater via TDA."""
    field = get_field()
    pd = priority_domains.split(",") if priority_domains else None
    candidates = field.bisociation_candidates(
        tau_threshold=tau, max_epsilon=epsilon, max_domains=max_domains,
        priority_domains=pd,
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


class SnapshotRestoreRequest(BaseModel):
    snapshot: str
    create_backup: bool = True

@app.post("/api/snapshot")
def trigger_snapshot(req: SnapshotRequest):
    """Triggar en manuell graf-backup / snapshot för forskning."""
    try:
        field = get_field()
        path = create_snapshot(field, tag=req.tag)
        return {"status": "success", "path": str(path)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/snapshot/list")
def get_snapshots(limit: int = 50):
    safe_limit = max(1, min(limit, 500))
    return {"ok": True, "snapshots": list_snapshots(limit=safe_limit)}


@app.post("/api/snapshot/restore")
def post_snapshot_restore(req: SnapshotRestoreRequest):
    """Återställ live field.sqlite från ett snapshot."""
    try:
        result = restore_snapshot(req.snapshot, create_backup=bool(req.create_backup))
        field = get_field()
        # Best-effort: ladda om in-memory graf om backend använder SQLite-surface.
        try:
            if field is not None and hasattr(field, "_load_graph_into_networkx"):
                field._load_graph_into_networkx()  # noqa: SLF001
        except Exception:
            pass
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


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
                "dormant_since": _coerce_text(row.get("dormant_since")) or None,
                "scope": _coerce_text(row.get("scope")) or "general",
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
                "assumption_flag": bool(row.get("assumption_flag") or 0),
                "valid_from": _coerce_text(row.get("valid_from")) or None,
                "valid_until": _coerce_text(row.get("valid_until")) or None,
                "derived_from": row.get("derived_from"),
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


def _insights_path() -> Path:
    return path_from_env("NOUSE_MEMORY_DIR", "memory") / "insights.jsonl"


def _extract_links_from_insight_row(row: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []

    def _append_from_text(text: str) -> None:
        for url in _extract_urls_from_text(text):
            if url in seen:
                continue
            seen.add(url)
            out.append(url)

    _append_from_text(str(row.get("statement") or ""))
    _append_from_text(str(row.get("source") or ""))

    for key in ("basis_evidence_refs", "evidence_refs"):
        refs = row.get(key)
        if not isinstance(refs, list):
            continue
        for item in refs:
            txt = _coerce_text(item)
            if not txt:
                continue
            _append_from_text(txt)
            if txt.startswith(("url:", "web:", "source_url:", "source_doc:")):
                _append_from_text(txt.split(":", 1)[-1])

    return out[:8]


def _insight_entry_payload(row: dict[str, Any]) -> dict[str, Any]:
    basis = row.get("basis") if isinstance(row.get("basis"), dict) else {}
    sample_rows = basis.get("sample_rows") if isinstance(basis.get("sample_rows"), list) else []
    score_components = (
        basis.get("score_components")
        if isinstance(basis.get("score_components"), dict)
        else {}
    )
    payload = {
        "ts": _coerce_text(row.get("ts")),
        "insight_id": _coerce_text(row.get("insight_id")),
        "kind": _coerce_text(row.get("kind")),
        "tier": _coerce_text(row.get("tier")),
        "score": _coerce_float(row.get("score"), default=0.0),
        "support": _coerce_int(row.get("support"), default=0, minimum=0, maximum=1_000_000),
        "mean_evidence": _coerce_float(row.get("mean_evidence"), default=0.0),
        "statement": _coerce_text(row.get("statement")),
        "anchor": _coerce_text(row.get("anchor") or row.get("src")),
        "source": _coerce_text(row.get("source")),
        "links": _extract_links_from_insight_row(row),
        "basis": {
            "method": _coerce_text(basis.get("method")),
            "support_rows": _coerce_int(
                basis.get("support_rows"),
                default=_coerce_int(row.get("support"), default=0, minimum=0, maximum=1_000_000),
                minimum=0,
                maximum=1_000_000,
            ),
            "score_components": {
                "evidence": _coerce_float(score_components.get("evidence"), default=0.0),
                "support": _coerce_float(score_components.get("support"), default=0.0),
                "novelty": _coerce_float(score_components.get("novelty"), default=0.0),
                "actionability": _coerce_float(score_components.get("actionability"), default=0.0),
            },
            "sample_rows": sample_rows[:3],
        },
    }
    return payload


def _latest_insights(limit: int = 12) -> dict[str, Any]:
    safe_limit = _coerce_int(limit, default=12, minimum=1, maximum=200)
    path = _insights_path()
    if not path.exists():
        return {"ok": True, "path": str(path), "count": 0, "entries": []}

    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    entries: list[dict[str, Any]] = []
    for raw in reversed(lines):
        row = _coerce_text(raw)
        if not row:
            continue
        try:
            parsed = json.loads(row)
        except Exception:
            continue
        if not isinstance(parsed, dict):
            continue
        entries.append(_insight_entry_payload(parsed))
        if len(entries) >= safe_limit:
            break

    return {"ok": True, "path": str(path), "count": len(entries), "entries": entries}


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


@app.get("/api/insights/recent")
def get_insights_recent(limit: int = 12):
    """Senaste findings/claims med länkar + basis-data för visualisering."""
    return _latest_insights(limit=limit)


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


@app.get("/api/brain_regions/balance")
def get_brain_regions_balance():
    """Region balance report — slagsida diagnostic with concept counts per region."""
    from nouse.field.brain_topology import region_report
    report = region_report(get_field())
    return {"ok": True, "balance": report}


@app.get("/api/brain_regions/heat")
def get_brain_regions_heat():
    """Live region heatmap — which regions are currently 'active' based on recent events."""
    from nouse.field.brain_topology import classify_domain, BRAIN_REGIONS
    field = get_field()
    if not field:
        return {"ok": True, "heat": {}}

    # Count concepts added per region (concept count as proxy for activity)
    heat: dict[str, dict] = {}
    for domain in field.domains():
        region_name = classify_domain(domain)
        if region_name not in heat:
            region_name_br = BRAIN_REGIONS.get(region_name)
            heat[region_name] = {
                "label": region_name_br.label_sv if region_name_br else region_name,
                "concept_count": 0,
                "domain_count": 0,
                "color": region_name_br.color_hex if region_name_br else "#888",
                "position": list(region_name_br.position) if region_name_br else [0, 0, 0],
                "intensity": 0.0,
            }
        n = len(field.concepts(domain=domain))
        heat[region_name]["concept_count"] += n
        heat[region_name]["domain_count"] += 1

    # Normalize intensity to 0-1 (log scale for better visualization)
    max_concepts = max((h["concept_count"] for h in heat.values()), default=1) or 1
    for name, h in heat.items():
        h["intensity"] = round(min(1.0, h["concept_count"] / max_concepts), 3)

    return {"ok": True, "heat": heat}


class ModelPolicySetRequest(BaseModel):
    workload: str = "chat"
    provider: str = "ollama"
    candidates: list[str] = []
    candidates_csv: str = ""


class ModelsAutodiscoverRequest(BaseModel):
    apply: bool = False
    preferred_kind: str = ""


class AuthRecordRequest(BaseModel):
    provider: str = "openai_compatible"
    api_key: str = ""
    env_file: str = "~/.env"
    apply_autodiscover: bool = True


_AUTH_PROVIDER_ALIASES = {
    "openai": "openai_compatible",
    "codex": "openai_compatible",
    "claude": "anthropic",
    "github": "copilot",
    "github-copilot": "copilot",
}


def _auth_canonical_provider(provider: str) -> str:
    p = str(provider or "").strip().lower()
    if not p:
        return "openai_compatible"
    return _AUTH_PROVIDER_ALIASES.get(p, p)


def _auth_key_plan_for_provider(provider: str) -> dict[str, Any]:
    p = _auth_canonical_provider(provider)
    if p == "ollama":
        return {
            "provider": "ollama",
            "requires_key": False,
            "keys": [],
            "openai_base_url": "",
            "note": "Ollama kör lokalt och kräver ingen API-nyckel.",
        }
    if p in {"anthropic"}:
        return {
            "provider": p,
            "requires_key": True,
            "keys": ["ANTHROPIC_API_KEY"],
            "openai_base_url": "",
            "note": (
                "Anthropic-nyckel sparad. Nous-chatten kör idag via openai_compatible-transport, "
                "så anthropic kräver separat bridge för direkt användning i chat."
            ),
        }
    if p in {"groq"}:
        return {
            "provider": p,
            "requires_key": True,
            "keys": ["GROQ_API_KEY", "NOUSE_OPENAI_API_KEY", "OPENAI_API_KEY"],
            "openai_base_url": "https://api.groq.com/openai/v1",
            "note": "Groq bridge aktiverad via openai_compatible.",
        }
    if p in {"openrouter"}:
        return {
            "provider": p,
            "requires_key": True,
            "keys": ["OPENROUTER_API_KEY", "NOUSE_OPENAI_API_KEY", "OPENAI_API_KEY"],
            "openai_base_url": "https://openrouter.ai/api/v1",
            "note": "OpenRouter bridge aktiverad via openai_compatible.",
        }
    if p in {"copilot"}:
        return {
            "provider": p,
            "requires_key": True,
            "keys": ["GITHUB_TOKEN", "NOUSE_OPENAI_API_KEY", "OPENAI_API_KEY"],
            "openai_base_url": "https://models.inference.ai.azure.com",
            "note": "GitHub Copilot/Models bridge aktiverad via openai_compatible.",
        }
    return {
        "provider": "openai_compatible",
        "requires_key": True,
        "keys": ["NOUSE_OPENAI_API_KEY", "OPENAI_API_KEY"],
        "openai_base_url": "https://api.openai.com/v1",
        "note": "",
    }


def _auth_dotenv_quote(value: str) -> str:
    raw = str(value or "")
    escaped = raw.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _auth_upsert_env_key(path: Path, key: str, value: str) -> None:
    safe_key = str(key or "").strip()
    if not safe_key:
        raise ValueError("env key required")
    line = f"{safe_key}={_auth_dotenv_quote(value)}"

    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()

    out: list[str] = []
    replaced = False
    for raw in lines:
        stripped = raw.lstrip()
        if stripped.startswith("#") or "=" not in stripped:
            out.append(raw)
            continue
        lhs = stripped.split("=", 1)[0].strip()
        if lhs == safe_key:
            if not replaced:
                out.append(line)
                replaced = True
            continue
        out.append(raw)
    if not replaced:
        out.append(line)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except Exception:
        pass


def _is_local_request_host(host: str) -> bool:
    h = str(host or "").strip().lower()
    if not h:
        return False
    if h in {"localhost", "::1"}:
        return True
    if h.startswith("127."):
        return True
    return False


def _auth_status_row_for_provider(provider: str) -> dict[str, Any]:
    canonical = _auth_canonical_provider(provider)
    plan = _auth_key_plan_for_provider(canonical)
    keys = [str(x).strip() for x in (plan.get("keys") or []) if str(x).strip()]
    requires_key = bool(plan.get("requires_key"))
    configured = True
    if requires_key:
        configured = any(bool((os.getenv(k) or "").strip()) for k in keys)
    return {
        "provider": str(provider),
        "canonical_provider": canonical,
        "requires_key": requires_key,
        "configured": configured,
        "keys": keys,
        "openai_base_url": str(plan.get("openai_base_url") or ""),
        "note": str(plan.get("note") or ""),
    }


def _normalize_model_candidates(candidates: list[str], candidates_csv: str = "") -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for raw in candidates or []:
        model_ref = str(raw or "").strip()
        if not model_ref or model_ref in seen:
            continue
        seen.add(model_ref)
        out.append(model_ref)

    for raw in str(candidates_csv or "").split(","):
        model_ref = raw.strip()
        if not model_ref or model_ref in seen:
            continue
        seen.add(model_ref)
        out.append(model_ref)

    return out


def _provider_payload(provider: Any) -> dict[str, Any]:
    label = str(provider.label()) if hasattr(provider, "label") else str(getattr(provider, "kind", "unknown"))
    return {
        "kind": str(getattr(provider, "kind", "unknown")),
        "label": label,
        "base_url": str(getattr(provider, "base_url", "")),
        "available_models": list(getattr(provider, "available_models", []) or []),
        "default_models": dict(getattr(provider, "default_models", {}) or {}),
        "latency_ms": float(getattr(provider, "latency_ms", 0.0) or 0.0),
        "priority": int(getattr(provider, "priority", 99) or 99),
        "note": str(getattr(provider, "note", "")),
    }


def _detect_provider_payloads() -> tuple[list[dict[str, Any]], str]:
    try:
        from nouse.llm.autodiscover import detect_providers

        providers = detect_providers()
        return ([_provider_payload(row) for row in providers], "")
    except Exception as exc:
        return ([], str(exc))


def _evaluate_model_health_status(
    row: dict[str, Any] | None,
    *,
    now_ts: float,
) -> str:
    if not isinstance(row, dict):
        return "unknown"
    success = int(row.get("success", 0) or 0)
    failure = int(row.get("failure", 0) or 0)
    timeout = int(row.get("timeout", 0) or 0)
    attempts = max(0, success + failure + timeout)
    cooldown_until = float(row.get("cooldown_until", 0.0) or 0.0)

    if attempts <= 0:
        return "unknown"
    if cooldown_until > now_ts:
        return "not_working"

    fail_score = float(failure) + (1.2 * float(timeout))
    fail_ratio = fail_score / max(1.0, float(attempts))
    if success <= 0 and attempts >= 2 and fail_ratio >= 0.9:
        return "not_working"
    if fail_ratio >= 0.45 or timeout > 0:
        return "degraded"
    return "working"


def _model_health_for_workload(workload: str = "agent") -> dict[str, Any]:
    key = str(workload or "agent").strip().lower() or "agent"
    now_ts = time.time()

    policy = get_workload_policy(key)
    defaults = [str(x).strip() for x in (policy.get("candidates") or []) if str(x).strip()]
    candidates = resolve_model_candidates(key, defaults)

    status_payload = router_status(workload=key)
    rows = ((status_payload.get("workloads") or {}).get(key) if isinstance(status_payload, dict) else []) or []
    row_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model = str(row.get("model") or "").strip()
        if not model:
            continue
        row_map[model] = row

    candidate_rows: list[dict[str, Any]] = []
    counts = {"working": 0, "degraded": 0, "not_working": 0, "unknown": 0}
    for model in candidates:
        row = row_map.get(model)
        state = _evaluate_model_health_status(row, now_ts=now_ts)
        counts[state] = int(counts.get(state, 0) or 0) + 1
        candidate_rows.append(
            {
                "model": model,
                "status": state,
                "success": int((row or {}).get("success", 0) or 0),
                "failure": int((row or {}).get("failure", 0) or 0),
                "timeout": int((row or {}).get("timeout", 0) or 0),
                "consecutive_timeouts": int((row or {}).get("consecutive_timeouts", 0) or 0),
                "cooldown_until": float((row or {}).get("cooldown_until", 0.0) or 0.0),
                "updated": str((row or {}).get("updated") or ""),
            }
        )

    primary_status = candidate_rows[0]["status"] if candidate_rows else "unknown"
    if not candidate_rows:
        overall = "not_working"
        detail = "Ingen model-kandidat konfigurerad för workload."
    elif counts["working"] > 0 and primary_status == "working" and counts["not_working"] == 0 and counts["degraded"] == 0:
        overall = "working"
        detail = "Primär modell svarar stabilt."
    elif counts["working"] > 0 or counts["degraded"] > 0 or counts["unknown"] > 0:
        overall = "degraded"
        if counts["working"] > 0 and primary_status != "working":
            detail = "Fallback aktiv: primär modell är instabil."
        elif counts["unknown"] > 0 and counts["working"] == 0 and counts["degraded"] == 0:
            detail = "Otillräcklig telemetri ännu. Kör en testfråga."
        else:
            detail = "Förhöjd felnivå (timeouts/503) men delvis fungerande."
    else:
        overall = "not_working"
        detail = "Alla kandidater misslyckas just nu."

    label = {
        "working": "Working",
        "degraded": "Degraded",
        "not_working": "Not working",
    }.get(overall, "Degraded")
    color = {
        "working": "#4ef160",
        "degraded": "#f1c44e",
        "not_working": "#f16b4e",
    }.get(overall, "#f1c44e")

    return {
        "ok": True,
        "workload": key,
        "status": overall,
        "label": label,
        "color": color,
        "detail": detail,
        "primary": str(candidates[0]) if candidates else "",
        "counts": counts,
        "candidates": candidate_rows,
        "updated_at": str(status_payload.get("updated_at") or ""),
    }


@app.get("/api/models/policy")
def get_models_policy(workload: str = "chat"):
    return {"ok": True, "policy": get_workload_policy(workload)}


@app.post("/api/models/policy")
def post_models_policy(req: ModelPolicySetRequest):
    workload = str(req.workload or "").strip().lower() or "chat"
    provider = str(req.provider or "ollama").strip() or "ollama"
    candidates = _normalize_model_candidates(req.candidates, req.candidates_csv)
    if not candidates:
        return {
            "ok": False,
            "error": "Ange minst en modell i candidates eller candidates_csv.",
        }
    row = set_workload_candidates(
        workload=workload,
        candidates=candidates,
        provider=provider,
    )
    return {"ok": True, "policy": row}


@app.post("/api/models/policy/reset")
def post_models_policy_reset():
    return {"ok": True, "policy": reset_policy()}


@app.get("/api/models/catalog")
def get_models_catalog():
    providers, detect_error = _detect_provider_payloads()
    return {
        "ok": True,
        "policy": load_policy(),
        "providers": providers,
        "detect_error": detect_error,
    }


@app.get("/api/models/health")
def get_models_health(workload: str = "agent"):
    return _model_health_for_workload(workload)


@app.get("/api/chat/control")
def get_chat_control(
    query: str = "",
    state: str = "",
    needs_web: bool | None = None,
    needs_files: bool | None = None,
    needs_memory_write: bool | None = None,
    needs_action: bool | None = None,
):
    return _chat_control_snapshot(
        query=query,
        state=state,
        needs_web=needs_web,
        needs_files=needs_files,
        needs_memory_write=needs_memory_write,
        needs_action=needs_action,
    )


@app.post("/api/models/autodiscover")
def post_models_autodiscover(req: ModelsAutodiscoverRequest):
    from nouse.llm.autodiscover import apply_best, detect_providers

    providers = detect_providers()
    chosen_payload: dict[str, Any] | None = None

    if bool(req.apply) and providers:
        preferred = str(req.preferred_kind or "").strip().lower() or None
        try:
            chosen = apply_best(
                providers,
                preferred_kind=preferred,
            )
        except TypeError:
            # Safety fallback if preferred_kind typing rejects plain str on older builds.
            chosen = apply_best(providers)
        if chosen is not None:
            chosen_payload = _provider_payload(chosen)

    return {
        "ok": True,
        "providers": [_provider_payload(row) for row in providers],
        "applied": bool(chosen_payload),
        "chosen": chosen_payload,
        "policy": load_policy(),
    }


@app.get("/api/auth/status")
def get_auth_status():
    load_env_files(force=True)
    providers = [
        "ollama",
        "codex",
        "openai_compatible",
        "openai",
        "anthropic",
        "copilot",
        "groq",
        "openrouter",
    ]
    rows = [_auth_status_row_for_provider(p) for p in providers]
    return {
        "ok": True,
        "providers": rows,
        "default_env_file": str(Path("~/.env").expanduser()),
        "active_openai_base_url": str(os.getenv("NOUSE_OPENAI_BASE_URL") or ""),
    }


@app.post("/api/auth/record")
def post_auth_record(req: AuthRecordRequest, request: Request):
    host = str(getattr(getattr(request, "client", None), "host", "") or "")
    if not _is_local_request_host(host):
        return {
            "ok": False,
            "error": "localhost_only",
            "detail": "Auth recording is restricted to local requests.",
        }

    provider = _auth_canonical_provider(req.provider)
    plan = _auth_key_plan_for_provider(provider)
    secret = str(req.api_key or "").strip()
    requires_key = bool(plan.get("requires_key"))
    if requires_key and not secret:
        return {"ok": False, "error": "api_key_required"}

    target = Path(str(req.env_file or "~/.env")).expanduser()
    keys = [str(x).strip() for x in (plan.get("keys") or []) if str(x).strip()]
    try:
        if requires_key:
            for env_key in keys:
                _auth_upsert_env_key(target, env_key, secret)
                os.environ[env_key] = secret

        base_url = str(plan.get("openai_base_url") or "").strip()
        if base_url:
            _auth_upsert_env_key(target, "NOUSE_OPENAI_BASE_URL", base_url)
            os.environ["NOUSE_OPENAI_BASE_URL"] = base_url
    except Exception as exc:
        return {"ok": False, "error": f"env_write_failed:{exc}"}

    try:
        load_env_files(force=True)
    except Exception:
        pass

    chosen_payload: dict[str, Any] | None = None
    autodiscover_error = ""
    if bool(req.apply_autodiscover):
        try:
            from nouse.llm.autodiscover import apply_best, detect_providers

            providers = detect_providers()
            preferred = provider if provider in {
                "ollama",
                "copilot",
                "anthropic",
                "openai",
                "groq",
                "openrouter",
                "custom",
            } else ""
            chosen = None
            if providers:
                try:
                    chosen = apply_best(providers, preferred_kind=(preferred or None))
                except TypeError:
                    chosen = apply_best(providers)
            if chosen is not None:
                chosen_payload = _provider_payload(chosen)
        except Exception as exc:
            autodiscover_error = str(exc)

    return {
        "ok": True,
        "provider": provider,
        "env_file": str(target),
        "requires_key": requires_key,
        "keys_written": keys,
        "applied": bool(chosen_payload),
        "chosen": chosen_payload,
        "note": str(plan.get("note") or ""),
        "autodiscover_error": autodiscover_error,
    }


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
    include_sensitive: bool = False


@app.post("/api/context")
async def post_context(req: ContextRequest):
    """
    Lättviktigt read-only kontext-lookup för hooks och externa agenter.
    Returnerar relevanta noder + relationer utan att starta LLM.
    Anropas av: Claude Code PreToolUse-hook, externa agenter.

    Fas 2 steg 5 (2026-08-23): denna endpoint serverar uttryckligen externa
    agenter (se docstring ovan) och är exakt vägen bisociative_solver.py
    använder för att hämta grafinnehåll innan det skickas till en extern LLM
    (_search_nouse). SENSITIVE_SCOPES (t.ex. personal_health) exkluderas
    därför som standard — sätt include_sensitive=true endast för en
    uttryckligt lokal, av Björn godkänd förfrågan.
    """
    from nouse.field.surface import SENSITIVE_SCOPES

    field = get_field()
    q = str(req.query or "").strip()[:300]
    if not q:
        return {"ok": False, "context_block": "", "confidence": 0.0, "nodes": []}

    try:
        # Hämta topp-K noder via enkel label-sökning
        exclude_scopes = None if req.include_sensitive else SENSITIVE_SCOPES
        rows = field.concepts(exclude_scopes=exclude_scopes)
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


def _write_scope_enforced() -> bool:
    raw = str(os.getenv("NOUSE_WRITE_SCOPE_ENFORCE", "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _write_scope_root() -> Path | None:
    raw = str(os.getenv("NOUSE_WRITE_SCOPE", "")).strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve(strict=False)
    except Exception:
        return None


def _extract_local_source_path(source: str) -> Path | None:
    raw = str(source or "").strip()
    if not raw:
        return None
    low = raw.lower()
    if low.startswith(("http://", "https://", "web:", "web_article:", "web_pdf:")):
        return None

    candidate = ""
    if re.match(r"^[a-zA-Z]:[\\/]", raw):
        candidate = raw
    elif ":" in raw:
        prefix, rest = raw.split(":", 1)
        pref = str(prefix or "").strip().lower()
        if pref in {"manual", "file", "local", "path"}:
            candidate = str(rest or "").strip()
    else:
        candidate = raw

    if not candidate:
        return None
    try:
        return Path(candidate).expanduser().resolve(strict=False)
    except Exception:
        return None


def _is_within_path(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except Exception:
        return False


def _is_source_allowed_by_write_scope(source: str) -> tuple[bool, Path | None, Path | None]:
    if not _write_scope_enforced():
        return True, None, None
    root = _write_scope_root()
    if root is None:
        return True, None, None
    src_path = _extract_local_source_path(source)
    # Om källan inte kan mappas till lokal path (t.ex. chat/web), tillåt write.
    if src_path is None:
        return True, root, None
    return _is_within_path(src_path, root), root, src_path


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

    allowed_by_scope, scope_root, source_path = _is_source_allowed_by_write_scope(req.source)
    if not allowed_by_scope:
        scope_text = str(scope_root) if scope_root is not None else ""
        source_text = str(source_path) if source_path is not None else str(req.source)
        reason = "write_scope_denied"
        record_event(
            trace_id,
            "ingest.scope_denied",
            endpoint="/api/ingest",
            payload={
                "source": req.source,
                "source_path": source_text,
                "write_scope": scope_text,
                "reason": reason,
            },
        )
        return {
            "added": 0,
            "source": req.source,
            "relations": [],
            "queued": False,
            "reason": reason,
            "write_scope": scope_text,
            "source_path": source_text,
            "trace_id": trace_id,
        }
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
        state = load_living_core()
    except Exception:
        state = {}
    identity = state.get("identity") if isinstance(state, dict) else {}
    return _persona_greeting(identity if isinstance(identity, dict) else None)


async def _model_generated_greeting(
    *,
    client: AsyncOllama,
    session_id: str,
    run_id: str,
) -> tuple[str, str]:
    try:
        state = load_living_core()
    except Exception:
        state = {}
    identity = state.get("identity") if isinstance(state, dict) else {}
    fallback = _persona_greeting(identity if isinstance(identity, dict) else None)
    prompt = (
        f"{_agent_identity_policy()}\n"
        f"{_persona_prompt_fragment(channel='chat')}\n"
        f"{_living_prompt_block('hej')}\n"
        "Uppgift: formulera en kort hälsning på svenska i första person.\n"
        "Regler:\n"
        "- Max 2 meningar.\n"
        "- Nämn ditt namn exakt en gång.\n"
        "- Låt varm och lugn, inte corporate och inte teatral.\n"
        "- Fråga vad användaren vill få ordning på eller hjälp med.\n"
        "- Nämn inte teknik, modeller, graf, minne eller interna system.\n"
    )
    candidates = _chat_model_candidates() or [MODEL]
    last_error: Exception | None = None
    seen: set[str] = set()
    for model in candidates:
        if model in seen:
            continue
        seen.add(model)
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Säg hej."},
                ],
                b76_meta={
                    "workload": "chat",
                    "session_id": session_id,
                    "run_id": run_id,
                },
            )
            text = str((resp.message.content or "")).strip()
            if text:
                return text, model
        except Exception as exc:
            last_error = exc
            continue
    return fallback, ("greeting_fallback" if last_error is not None else "greeting_profile")


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
    explicit_snapshot_markers = (
        "min profil",
        "min identitet",
        "vad minns du om mig",
        "vad har du sparat om mig",
        "vad säger grafen om mig",
        "visa min profil",
        "visa min identitet",
        "show my profile",
        "what do you remember about me",
        "what have you stored about me",
        "what does the graph say about me",
    )
    if any(phrase in q for phrase in explicit_snapshot_markers):
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
    if _is_reflective_dialogue_query(q):
        return False

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


def _is_explicit_triangulation_request(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    command_markers = (
        "/tri",
        "/triangulate",
        "/källor",
        "/kallor",
    )
    if any(q.startswith(m) for m in command_markers):
        return True
    explicit_markers = (
        "triangulera",
        "triangulering",
        "visa källor",
        "visa kallor",
        "med källor",
        "med kallor",
        "med evidens",
        "med källhänvisning",
        "with sources",
        "with evidence",
        "llm, system/graf, extern, syntes",
        "llm/system/graf/extern/syntes",
    )
    return any(m in q for m in explicit_markers)


def _extract_explicit_skill_request(query: str) -> tuple[str, str]:
    raw = str(query or "").strip()
    if not raw:
        return "", ""
    q = _normalize_query(raw)
    if not q.startswith("/skill"):
        return "", raw
    parts = raw.split(None, 2)
    if len(parts) < 2:
        return "", ""
    token = str(parts[1] or "").strip()
    if not token or token.lower() in {"off", "clear", "none", "list", "show"}:
        return "", ""
    remainder = str(parts[2] or "").strip() if len(parts) > 2 else ""
    try:
        from nouse.capability.graph import resolve_skill_name

        resolved = resolve_skill_name(token)
    except Exception:
        aliases = {
            "rescue": "operator.rescue",
            "capture": "memory.capture",
            "tri": "research.triangulate",
            "triangulate": "research.triangulate",
            "time": "temporal.grounding",
            "clock": "temporal.grounding",
        }
        resolved = aliases.get(token.strip().lower(), "")
    return str(resolved or token).strip(), remainder


def _is_explicit_tool_mode_request(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    command_markers = (
        "/mcp",
        "/skill",
        "/skills",
        "/selfdevelop",
    )
    if any(q.startswith(m) for m in command_markers):
        return True
    explicit_markers = (
        "använd mcp",
        "anvand mcp",
        "use mcp",
        "mcp verktyg",
        "skill mode",
        "använd skills",
        "anvand skills",
        "use tools now",
        "selfdevelop",
        "self develop",
        "kernel_execute_self_update",
    )
    return any(m in q for m in explicit_markers)


_URL_TOKEN_RE = re.compile(r"(https?://[^\s<>\")]+|www\.[^\s<>\")]+)", re.IGNORECASE)


def _extract_urls_from_text(text: str) -> list[str]:
    raw = str(text or "")
    out: list[str] = []
    seen: set[str] = set()
    for m in _URL_TOKEN_RE.finditer(raw):
        token = str(m.group(1) or "").strip().rstrip(".,;:!?)]}")
        if not token:
            continue
        if token.lower().startswith("www."):
            token = f"https://{token}"
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _is_auto_mcp_query(query: str) -> bool:
    q_raw = str(query or "")
    q = _normalize_query(q_raw)
    if not q:
        return False
    if _is_explicit_tool_mode_request(q) or _is_explicit_triangulation_request(q):
        return False
    if _extract_urls_from_text(q_raw):
        return True

    link_ref_markers = (
        "länk",
        "lank",
        "link",
        "url",
        "artikeln",
        "article",
        "käll",
        "kall",
        "källa",
        "source",
    )
    need_markers = (
        "vem skrev",
        "who wrote",
        "vad står",
        "what does",
        "sammanfatta",
        "summarize",
        "verifiera",
        "verify",
        "kolla",
        "check",
        "ta reda på",
        "berätta vad",
    )
    has_link_ref = any(m in q for m in link_ref_markers)
    has_need = any(m in q for m in need_markers) or q.endswith("?")
    return has_link_ref and has_need


def _is_queue_failure_query(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    if "orchestrator check" in q and "failed=" in q:
        return True
    has_queue = any(m in q for m in ("queue", "kö", "ko", "kön", "kon"))
    has_fail = any(
        m in q
        for m in (
            "fail",
            "failed",
            "felar",
            "failar",
            "misslyck",
            "error",
        )
    )
    if has_queue and has_fail:
        return True
    if ("vad" in q or "which" in q or "what" in q) and has_fail and ("queue" in q):
        return True
    return False


def _queue_failure_answer(limit: int = 6) -> str:
    safe_limit = max(1, min(int(limit or 6), 20))
    try:
        stats = queue_stats()
    except Exception:
        stats = {}
    try:
        failed_rows = list_tasks(status="failed", limit=safe_limit)
    except Exception:
        failed_rows = []

    failed_count = int(stats.get("failed", 0) or 0)
    pending_count = int(stats.get("pending", 0) or 0)
    awaiting_count = int(stats.get("awaiting_approval", 0) or 0)
    in_progress_count = int(stats.get("in_progress", 0) or 0)

    if failed_count <= 0 and not failed_rows:
        return (
            "Queue visar inga failed tasks just nu. "
            f"(pending={pending_count}, awaiting_approval={awaiting_count}, in_progress={in_progress_count})"
        )

    lines: list[str] = [
        (
            f"Queue-status: pending={pending_count}, awaiting_approval={awaiting_count}, "
            f"in_progress={in_progress_count}, failed={failed_count}."
        )
    ]
    if failed_rows:
        lines.append("Senaste failed tasks:")
        for row in failed_rows[:safe_limit]:
            task_id = int(row.get("id", 0) or 0)
            category = str(row.get("category") or row.get("task_type") or "task").strip() or "task"
            attempts = int(row.get("attempts", 0) or 0)
            error = str(row.get("last_error") or "").strip().replace("\n", " ")
            mission = str(row.get("mission") or row.get("task") or "").strip().replace("\n", " ")
            if len(error) > 160:
                error = error[:157] + "..."
            if len(mission) > 100:
                mission = mission[:97] + "..."
            parts = [f"- #{task_id} {category}"]
            if attempts:
                parts.append(f"attempts={attempts}")
            if error:
                parts.append(f"error={error}")
            elif mission:
                parts.append(f"mission={mission}")
            lines.append(" · ".join(parts))
    else:
        lines.append("Kunde inte läsa failed task-detaljer just nu.")
    lines.append("Vill du att jag kör en retry på failed tasks nu?")
    return "\n".join(lines)


def _parse_iso8601(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _pending_confirmation_ttl_sec() -> int:
    return _env_int("NOUSE_PENDING_CONFIRMATION_TTL_SEC", 600, minimum=30)


def _pending_confirmation_from_session(session: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    meta = dict((session or {}).get("meta") or {})
    action = str(meta.get("pending_confirmation_action") or "").strip().lower()
    if not action:
        return "", {}
    payload = meta.get("pending_confirmation_payload")
    payload_obj = dict(payload) if isinstance(payload, dict) else {}

    set_at = _parse_iso8601(meta.get("pending_confirmation_set_at"))
    if set_at is not None:
        age = (datetime.now(timezone.utc) - set_at).total_seconds()
        if age > float(_pending_confirmation_ttl_sec()):
            return "", {}
    return action, payload_obj


def _set_pending_confirmation(
    session_id: str,
    *,
    action: str,
    payload: dict[str, Any] | None = None,
) -> None:
    ensure_session(
        session_id,
        lane="agent",
        source="api_agent",
        meta={
            "pending_confirmation_action": str(action or "").strip().lower(),
            "pending_confirmation_payload": dict(payload or {}),
            "pending_confirmation_set_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _clear_pending_confirmation(session_id: str) -> None:
    ensure_session(
        session_id,
        lane="agent",
        source="api_agent",
        meta={
            "pending_confirmation_action": "",
            "pending_confirmation_payload": {},
            "pending_confirmation_set_at": "",
        },
    )


def _is_short_affirmative_reply(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    positives = {
        "ja",
        "ja tack",
        "japp",
        "yes",
        "yes please",
        "ok",
        "okej",
        "okey",
        "absolut",
        "visst",
        "gärna",
        "garna",
        "kör",
        "kor",
        "kör på",
        "kor pa",
        "kör det",
        "kor det",
        "gör det",
        "gor det",
    }
    return q in positives


def _is_short_negative_reply(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    negatives = {
        "nej",
        "nej tack",
        "no",
        "no thanks",
        "inte nu",
        "skip",
        "avbryt",
        "cancel",
        "stopp",
        "stop",
        "låt bli",
        "lat bli",
    }
    return q in negatives


def _queue_retry_failed_answer(limit: int = 6) -> str:
    safe_limit = max(1, min(int(limit or 6), 20))
    try:
        retried_rows = retry_failed_tasks(limit=safe_limit, reason="bekräftad retry från chat")
    except Exception as e:
        return f"Kunde inte köra retry på failed tasks just nu: {e}"

    retried = len(retried_rows)
    try:
        stats = queue_stats()
    except Exception:
        stats = {}
    try:
        remaining_failed = list_tasks(status="failed", limit=safe_limit)
    except Exception:
        remaining_failed = []

    pending_count = int(stats.get("pending", 0) or 0)
    awaiting_count = int(stats.get("awaiting_approval", 0) or 0)
    in_progress_count = int(stats.get("in_progress", 0) or 0)
    failed_count = int(stats.get("failed", 0) or 0)

    lines = [
        f"Körde retry på {retried} failed tasks.",
        (
            f"Queue nu: pending={pending_count}, awaiting_approval={awaiting_count}, "
            f"in_progress={in_progress_count}, failed={failed_count}."
        ),
    ]
    if remaining_failed:
        lines.append("Kvarvarande failed tasks:")
        for row in remaining_failed[:safe_limit]:
            task_id = int(row.get("id", 0) or 0)
            category = str(row.get("category") or row.get("task_type") or "task").strip() or "task"
            attempts = int(row.get("attempts", 0) or 0)
            error = str(row.get("last_error") or "").strip().replace("\n", " ")
            if len(error) > 160:
                error = error[:157] + "..."
            part = f"- #{task_id} {category}"
            if attempts:
                part += f" · attempts={attempts}"
            if error:
                part += f" · error={error}"
            lines.append(part)
    else:
        lines.append("Inga failed tasks kvar just nu.")
    return "\n".join(lines)


def _is_reflective_dialogue_query(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    # Om användaren explicit ber om källor/data/grafstatus ska vi inte
    # behandla frågan som ren reflektionsdialog.
    data_markers = (
        "graf",
        "relation",
        "nod",
        "node",
        "domän",
        "domain",
        "käll",
        "evidens",
        "senaste",
        "status",
        "journal",
        "logg",
        "trace",
        "lista",
        "search",
        "sök",
        "webb",
        "repo",
        "fil",
        "docs",
        "/check",
        "mcp",
        "skill",
        "selfdevelop",
    )
    if any(m in q for m in data_markers):
        return False

    reflective_markers = (
        "dröm",
        "drom",
        "drömma",
        "dromma",
        "tankeexperiment",
        "hoppas",
        "känns",
        "kanns",
        "vem är du",
        "vem ar du",
        "bara jag och du",
        "filosof",
        "utvecklas till",
    )
    if any(m in q for m in reflective_markers):
        return True
    if q.startswith("om du ") and "?" in q:
        return True
    return False


def _is_sensitive_disclosure_query(query: str) -> bool:
    qn = _normalize_query(query)
    if not qn:
        return False
    q = f" {qn} "

    direct_markers = (
        " min fru dog ",
        " min man dog ",
        " min dotter dog ",
        " min son dog ",
        " min partner dog ",
        " min fru omkom ",
        " min dotter omkom ",
        " min son omkom ",
        " när jag var ",
        " efter den dagen ",
        " this happened to me ",
    )
    if any(m in q for m in direct_markers):
        return True

    personal_markers = (
        " jag ",
        " mig ",
        " min ",
        " mitt ",
        " mina ",
        " vi ",
        " oss ",
        " vår ",
        " my ",
        " our ",
        " me ",
    )
    severe_markers = (
        " dog ",
        " död ",
        " dod ",
        " omkom ",
        " brann inne ",
        " trafikolycka ",
        " olycka ",
        " förlorade ",
        " forlora ",
        " förlust ",
        " trauma ",
        " sorg ",
        " självmord ",
        " sjalvmord ",
        " övergrepp ",
        " overgrepp ",
        " misshandel ",
        " survived ",
        " died ",
        " death ",
        " accident ",
        " grief ",
    )
    relation_markers = (
        " fru ",
        " man ",
        " partner ",
        " dotter ",
        " son ",
        " barn ",
        " mamma ",
        " pappa ",
        " syster ",
        " bror ",
        " familj ",
        " wife ",
        " husband ",
        " daughter ",
        " child ",
        " children ",
        " family ",
    )
    event_markers = (
        " var med om ",
        " det hände mig ",
        " hande mig ",
        " i olyckan ",
        " brann inne ",
        " went through ",
    )
    has_personal = any(m in q for m in personal_markers)
    has_severe = any(m in q for m in severe_markers)
    has_relation = any(m in q for m in relation_markers)
    has_event = any(m in q for m in event_markers)
    return has_personal and has_severe and (has_relation or has_event)


def _extract_sensitive_memory_preference(query: str) -> str | None:
    q = _normalize_query(query)
    if not q:
        return None
    off_markers = (
        "spara inte",
        "lagra inte",
        "inte i minnet",
        "inte i profilen",
        "ska inte sparas",
        "får inte sparas",
        "glöm det här",
        "glom det har",
        "radera det här",
        "radera detta",
        "do not save",
        "don't save",
    )
    if any(m in q for m in off_markers):
        return "off"

    on_markers = (
        "du får spara",
        "det här får sparas",
        "detta får sparas",
        "spara detta",
        "spara det",
        "lägg in i profilen",
        "lagg in i profilen",
        "beständiga profilen",
        "bestandiga profilen",
        "foga in det i den beständiga profilen",
        "du kan få mer information",
        "you may save",
        "save this",
    )
    if any(m in q for m in on_markers):
        return "on"
    return None


def _allow_persistent_memory_for_query(
    query: str,
    *,
    session: dict[str, Any] | None = None,
) -> bool:
    override = str(os.getenv("NOUSE_ALLOW_SENSITIVE_MEMORY_WRITE", "")).strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if not _is_sensitive_disclosure_query(query):
        return True

    meta = dict((session or {}).get("meta") or {})
    raw = meta.get("sensitive_memory_consent")
    if isinstance(raw, bool):
        return raw
    text = str(raw or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


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


def _clean_graph_label(raw: str) -> str:
    text = str(raw or "").strip().strip("\"'`")
    if not text:
        return ""
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if ":" in text:
        text = text.split(":", 1)[0].strip()
    # Trim vanliga fortsättningsord så vi får kärntermen.
    text = re.split(r"\b(?:och|and|men|but)\b", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    text = text.strip(" .,:;!?")
    if len(text) > 80:
        text = text[:80].rstrip(" .,:;!?")
    return text


def _extract_identity_name_from_query(query: str) -> str:
    raw = str(query or "")
    if not raw.strip():
        return ""

    patterns = (
        r"(?:jag\s+(?:är|ar)\s+bara)\s+([^\n\.,;!?]+)",
        r"(?:jag\s+heter)\s+([^\n\.,;!?]+)",
        r"(?:kalla\s+mig)\s+([^\n\.,;!?]+)",
        r"(?:döp\s+om\s+mig\s+till|dop\s+om\s+mig\s+till)\s+([^\n\.,;!?]+)",
        r"(?:rename\s+me\s+to|set\s+me\s+as)\s+([^\n\.,;!?]+)",
        r"(?:st(?:å|a)r?\s+som)\s+([^\n\.,;!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = _clean_graph_label(match.group(1))
        if not candidate:
            continue
        folded = _fold_identity_text(candidate)
        if folded in {"user", "anvandare", "profil", "identitet"}:
            continue
        return candidate
    return ""


def _extract_identity_aliases_to_remove(query: str) -> list[str]:
    raw = str(query or "")
    if not raw.strip():
        return []

    aliases: list[str] = []
    seen: set[str] = set()
    patterns = (
        r"(?:ta\s+bort|radera|remove)\s+(.+?)\s+(?:från|fran|from)\s+(?:mig|min\s+profil|min\s+identitet|me)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
            chunk = str(match.group(1) or "").strip()
            if not chunk:
                continue
            parts = re.split(r"(?:,|;|/|\boch\b|\band\b|&)", chunk, flags=re.IGNORECASE)
            for part in parts:
                name = _clean_graph_label(part)
                if not name:
                    continue
                key = _fold_identity_text(name)
                if key in seen:
                    continue
                seen.add(key)
                aliases.append(name)
    return aliases[:6]


def _extract_identity_domain_from_query(query: str) -> str:
    raw = str(query or "")
    if not raw.strip():
        return ""
    patterns = (
        r"(?:domän|doman|domain)\s+(?:som\s+heter|heter|kallad|named)\s+([A-Za-z0-9_\-ÅÄÖåäö]+)",
        r"(?:domän|doman|domain)\s*[:=]\s*([A-Za-z0-9_\-ÅÄÖåäö]+)",
        r"(?:st(?:å|a)r?\s+som)\s+([A-Za-z0-9_\-ÅÄÖåäö]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if not match:
            continue
        domain = _clean_graph_label(match.group(1))
        if not domain:
            continue
        return domain[:48]
    return ""


def _apply_identity_graph_action_fallback(*, field: FieldSurface, query: str) -> dict[str, Any]:
    """
    Deterministisk fallback för vanliga identitetsuppdateringar när modellen
    inte gör verktygskall trots action mode.
    """
    if not _is_graph_action_request(query):
        return {"applied": False, "reason": "not_graph_action"}

    user_name = _extract_identity_name_from_query(query)
    user_domain = _extract_identity_domain_from_query(query) or "User"
    aliases = _extract_identity_aliases_to_remove(query)

    if not user_name and not aliases:
        return {"applied": False, "reason": "no_identity_targets"}

    writes: list[dict[str, Any]] = []
    tool_names: set[str] = set()

    def _tool(name: str, args: dict[str, Any]) -> None:
        result = execute_tool(field, name, args)
        writes.append({"tool": name, "args": dict(args), "result": result})
        tool_names.add(name)

    try:
        if user_name:
            _tool(
                "upsert_concept",
                {
                    "name": user_name,
                    "domain": user_domain,
                    "summary": "Primär användaridentitet i Nous.",
                    "claims": [f"{user_name} är den primära användaren i detta system."],
                    "evidence_refs": ["source:user_identity_update"],
                    "related_terms": ["user", "identity", user_domain],
                    "uncertainty": 0.05,
                },
            )
            _tool(
                "add_relation",
                {
                    "src": user_name,
                    "rel_type": "har_roll",
                    "tgt": "USER",
                    "domain_src": user_domain,
                    "domain_tgt": "identity",
                    "why": "Användaren satte explicit roll i chatten.",
                },
            )

        for alias in aliases:
            if user_name and _fold_identity_text(alias) == _fold_identity_text(user_name):
                continue
            _tool(
                "upsert_concept",
                {
                    "name": alias,
                    "domain": "AI",
                    "summary": "Omklassificerad till modell/AI-entitet, ej användaridentitet.",
                    "claims": [f"{alias} är en AI-/modellentitet, inte den primära användaren."],
                    "evidence_refs": ["source:user_identity_update"],
                    "related_terms": ["AI", "LLM", "model"],
                    "uncertainty": 0.1,
                },
            )
            _tool(
                "add_relation",
                {
                    "src": alias,
                    "rel_type": "är",
                    "tgt": "LLM-modell",
                    "domain_src": "AI",
                    "domain_tgt": "AI",
                    "why": "Användaren separerade aliaset från sin personidentitet.",
                },
            )
            if user_name:
                _tool(
                    "add_relation",
                    {
                        "src": user_name,
                        "rel_type": "inte_samma_som",
                        "tgt": alias,
                        "domain_src": user_domain,
                        "domain_tgt": "AI",
                        "why": "Explicit disambiguering från användaren i chatten.",
                    },
                )
    except Exception as exc:
        if writes:
            if _is_personal_runtime_mode():
                answer = (
                    "Jag hann spara en del av det, men något i uppdateringen fastnade. "
                    f"Felspår: {str(exc)[:180]}"
                )
            else:
                answer = (
                    "Grafuppdatering delvis utförd, men en delsteg misslyckades: "
                    f"{str(exc)[:180]}"
                )
            return {
                "applied": True,
                "partial": True,
                "error": str(exc),
                "tool_names": sorted(tool_names),
                "writes": writes,
                "answer": answer,
            }
        return {"applied": False, "reason": "tool_error", "error": str(exc)}

    if not writes:
        return {"applied": False, "reason": "no_writes"}

    if _is_personal_runtime_mode():
        bits = ["Jag har uppdaterat det och kommer ihåg det framåt."]
        if user_name:
            bits.append(f"Jag utgår nu från {user_name} som din primära identitet här.")
        if aliases:
            bits.append(
                "Jag skiljer också ut dessa alias från din personprofil: "
                + ", ".join(aliases[:6])
                + "."
            )
        bits.append("Om du vill kan jag visa den tekniska ändringen också.")
    else:
        bits = ["Grafen uppdaterad."]
        if user_name:
            bits.append(f"Primär identitet: {user_name} (domän: {user_domain}).")
        if aliases:
            bits.append(
                "Omklassificerade alias från din personprofil: "
                + ", ".join(aliases[:6])
                + "."
            )
        bits.append("Du kan fråga 'vem är jag' för att verifiera snapshoten.")

    return {
        "applied": True,
        "partial": False,
        "tool_names": sorted(tool_names),
        "writes": writes,
        "answer": " ".join(bits),
        "user_name": user_name,
        "user_domain": user_domain,
        "aliases": aliases,
    }


def _is_graph_action_request(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    # Identity/profile requests should be treated as graph-write intents
    # even when users do not explicitly mention "graph" or "node".
    identity_update_markers = (
        "ändra så att jag",
        "andra sa att jag",
        "uppdatera mig till",
        "sätt mig som",
        "satt mig som",
        "ställ in mig som",
        "stall in mig som",
        "kalla mig",
        "döp om mig",
        "dop om mig",
        "jag ska vara",
        "jag vill vara",
        "jag heter ",
        "stå som",
        "sta som",
        "set me as",
        "rename me",
        "ta bort",
        "radera",
        "remove",
        "jag är bara",
        "jag ar bara",
    )
    identity_scope = (
        "jag",
        "mig",
        "min profil",
        "min identitet",
        "användare",
        "anvandare",
        "user",
        "profil",
        "identitet",
    )
    if any(m in q for m in identity_update_markers) and any(s in q for s in identity_scope):
        return True
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


def _session_delegate_enabled(session: dict[str, Any] | None) -> bool:
    if not isinstance(session, dict):
        return True
    meta = session.get("meta")
    if not isinstance(meta, dict):
        return True
    raw = meta.get("delegate_enabled")
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in {"0", "false", "no", "off"}:
        return False
    if text in {"1", "true", "yes", "on"}:
        return True
    return True


def _extract_delegate_preference_command(query: str) -> str | None:
    """
    Returnerar:
    - "off" för explicit kommando att stänga av delegering
    - "on" för explicit kommando att slå på delegering
    - None om inget kommando hittas
    """
    q = _normalize_query(query)
    if not q:
        return None
    off_markers = (
        "sluta delegera",
        "sluta deligera",
        "stäng av delegering",
        "stang av delegering",
        "ingen delegering",
        "disable delegation",
        "delegation off",
        "/no-delegate",
        "/nodelegate",
    )
    if any(m in q for m in off_markers):
        return "off"
    on_markers = (
        "aktivera delegering",
        "sätt på delegering",
        "satt pa delegering",
        "delegera igen",
        "delegation on",
        "enable delegation",
        "/delegate-on",
        "/delegation-on",
    )
    if any(m in q for m in on_markers):
        return "on"
    return None


def _is_background_delegate_request(query: str, *, session: dict[str, Any] | None = None) -> bool:
    if not FAST_DELEGATE_ENABLED:
        return False
    if not _session_delegate_enabled(session):
        return False
    q = _normalize_query(query)
    if not q:
        return False
    if _is_sensitive_disclosure_query(q):
        return False
    # Explicita graf-/identitetsuppdateringar ska köras i foreground-agentloop
    # för att säkerställa faktiska verktygsskrivningar i samma chattvarv.
    if _is_graph_action_request(q):
        return False
    if _is_explicit_delegate_intent(q):
        return True
    if (
        _is_greeting_query(q)
        or _is_simple_fact_query(q)
        or _is_mission_vision_input(q)
        or _is_conversational_invite_query(q)
    ):
        return False
    if not FAST_DELEGATE_IMPLICIT:
        return False
    words = len(q.split())
    strong_task_markers = (
        "implementera",
        "bygg",
        "refaktor",
        "fixa",
        "debug",
        "optimera",
        "sätt upp",
        "installera",
        "genomför",
        "deploy",
        "migrera",
        "patcha",
        "felsök",
        "sammanfoga",
    )
    if any(m in q for m in strong_task_markers):
        return True

    # Långa instruktioner kan delegeras även utan exakta verbmarkörer,
    # men bara om de ser ut som konkreta uppgifter (inte öppna frågor).
    if words >= FAST_DELEGATE_MIN_WORDS and "?" not in q:
        task_scope_markers = (
            "jobb",
            "uppgift",
            "task",
            "kod",
            "repo",
            "fil",
            "filer",
            "projekt",
            "graf",
            "domän",
            "domain",
            "pipeline",
            "test",
            "release",
        )
        if any(m in q for m in task_scope_markers):
            return True
    return False


def _is_conversational_invite_query(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    invite_prefixes = (
        "vill du ",
        "skulle du ",
        "kan vi ",
        "är du ",
        "ar du ",
        "har du ",
        "would you ",
        "are you ",
        "can we ",
    )
    if any(q.startswith(p) for p in invite_prefixes):
        social_markers = (
            "intresserad",
            "testa",
            "lek",
            "experiment",
            "snacka",
            "prata",
            "nyfiken",
            "interested",
            "play",
        )
        if any(m in q for m in social_markers):
            return True

    # Korta sociala/meta-frågor ska i regel besvaras direkt i chatten.
    if "?" in q and len(q.split()) <= 14:
        explicit_task_markers = (
            "implementera",
            "bygg",
            "refaktor",
            "fixa",
            "debug",
            "optimera",
            "installera",
            "uppdatera",
            "ta bort",
            "skapa",
            "lägg till",
            "add ",
            "update ",
            "remove ",
        )
        if not any(m in q for m in explicit_task_markers):
            return True
    return False


def _is_no_delegate_intent(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    explicit_no_delegate = (
        "utan subagent",
        "utan subagents",
        "utan bakgrundsagent",
        "utan bakgrundsagenter",
        "utan att skicka till subagent",
        "utan att skicka till subagents",
        "utan att skicka till bakgrundsagent",
        "utan att skicka till bakgrundsagenter",
        "utan att skicka något till subagent",
        "utan att skicka något till subagents",
        "utan att skicka något till bakgrundsagent",
        "utan att skicka något till bakgrundsagenter",
        "utan att skicka nagot till subagent",
        "utan att skicka nagot till subagents",
        "without subagent",
        "without subagents",
        "without background agent",
        "without background agents",
        "no subagent",
        "no subagents",
        "inte till subagent",
        "inte till subagents",
        "inte till bakgrundsagent",
        "inte till bakgrundsagenter",
        "ej till subagent",
        "ej till subagents",
        "bara jag och du",
    )
    if any(m in q for m in explicit_no_delegate):
        return True

    neg_markers = ("utan", "inte", "ej", "without", "no ")
    agent_terms = ("subagent", "subagents", "bakgrundsagent", "bakgrundsagenter")
    if any(n in q for n in neg_markers) and any(a in q for a in agent_terms):
        return True
    return False


def _is_explicit_delegate_intent(query: str) -> bool:
    q = _normalize_query(query)
    if not q:
        return False
    command_markers = (
        "/orchestrate",
        "/delegate",
    )
    if any(m in q for m in command_markers):
        return True

    if _is_no_delegate_intent(q):
        return False

    markers = (
        "orchestrera",
        "orchestrate",
        "agent register",
        "agent-register",
        "@agent",
        "@_agent",
    )
    if any(m in q for m in markers):
        return True

    # Delegering via fri text kräver tydligt uppdragsobjekt för att undvika
    # att meta-resonemang om delegation feltolkas som ett delegeringskommando.
    explicit_delegate_phrases = (
        "delegera detta",
        "delegera det här",
        "delegera det har",
        "delegera till",
        "deligera detta",
        "deligera det här",
        "deligera det har",
        "deligera till",
        "kan du delegera",
        "kan du deligera",
        "please delegate",
        "delegate this",
        "delegate to",
    )
    if any(p in q for p in explicit_delegate_phrases):
        return True

    # Kort, explicit intent att använda agenter ska trigga delegation direkt.
    if ("agent" in q or "agenter" in q or "subagent" in q or "subagents" in q) and any(
        v in q for v in ("använd", "kor", "kör", "use", "starta", "spawn", "spin up")
    ):
        return True
    return False


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
        "local_write": "write_local_file" in tool_names,
        "local_exec": "run_local_command" in tool_names,
        "web": all(x in tool_names for x in ("web_search", "fetch_url")),
        "graph_write": all(x in tool_names for x in ("upsert_concept", "add_relation")),
    }


def _capability_line(caps: dict[str, bool]) -> str:
    def _on(flag: bool) -> str:
        return "ja" if flag else "nej"

    return (
        "Runtime-kapabiliteter i denna process: "
        f"local_fs={_on(bool(caps.get('local_fs')))}, "
        f"local_write={_on(bool(caps.get('local_write')))}, "
        f"local_exec={_on(bool(caps.get('local_exec')))}, "
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
    if "503" in text or "service temporarily unavailable" in text or "service unavailable" in text:
        return "service_unavailable"
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
    reasons: set[str] = set()
    for row in attempts[:8]:
        model = str(row.get("model") or "okänd-modell")
        reason = str(row.get("reason") or "other")
        reasons.add(reason)
        err = str(row.get("error") or "").strip().replace("\n", " ")
        if len(err) > 180:
            err = f"{err[:177]}..."
        parts.append(f"{model} ({reason}): {err}")
    message = (
        f"Alla modeller misslyckades för workload={workload}. "
        f"Försök: {' | '.join(parts)}"
    )
    hints: list[str] = []
    if reasons & {"timeout", "service_unavailable", "rate_limited"}:
        hints.append(
            "Tips: välj lokal stabil modell med /model 2 eller /model 3 "
            "och/eller höj NOUSE_AGENT_LLM_TIMEOUT_SEC (t.ex. 90)."
        )
    if "auth" in reasons:
        hints.append("Tips: kontrollera API-nyckel med `nouse auth`.")
    if hints:
        message += " " + " ".join(hints)
    return message


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
            "read_local_file. Säg vad jag ska leta efter så gör jag det direkt."
        )

    local_write_denials = (
        "kan inte skriva filer",
        "kan inte skapa filer",
        "kan inte modifiera lokala filer",
        "kan inte ändra filer på disk",
        "kan inte skriva på disk",
        "filverktygen är read-only",
        "filsystemet är referensmaterial",
        "kan inte ändra kod direkt",
    )
    saw_local_write_denial = any(p in low for p in local_write_denials)

    local_exec_denials = (
        "kan inte köra terminalkommandon",
        "kan inte köra kommandon",
        "kan inte köra shell",
        "kan inte installera saker",
        "kan inte skapa mappar",
        "kan inte köra terminalkommandon eller installera saker",
    )
    saw_local_exec_denial = any(p in low for p in local_exec_denials)

    if caps.get("local_write") and caps.get("local_exec") and (saw_local_write_denial or saw_local_exec_denial):
        return (
            "Jag kan både skriva lokala textfiler och köra lokala shell-kommandon i denna körning. "
            "Säg vad du vill att jag ska skapa, ändra eller köra så gör jag det direkt."
        )

    if caps.get("local_write") and saw_local_write_denial:
        return (
            "Jag kan skriva lokala textfiler i denna körning via write_local_file. "
            "Säg vilken fil du vill skapa eller ändra så gör jag det direkt."
        )

    if caps.get("local_exec") and saw_local_exec_denial:
        return (
            "Jag kan köra lokala shell-kommandon i denna körning via run_local_command, "
            "och i trusted local runtime kan jag också skapa kataloger och bygga/testa direkt."
        )

    graph_denials = (
        "inga grafverktyg laddade",
        "har inga grafverktyg",
        "i den här specifika körningen har jag inga grafverktyg",
        "kan inte skapa noden direkt från min sida",
        "kan inte skapa noden direkt",
    )
    if caps.get("graph_write") and any(p in low for p in graph_denials):
        return (
            "Jag har grafverktyg i denna körning och kan skapa eller uppdatera noder direkt. "
            "Säg bara vad du vill lagra så gör jag det."
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


def _ground_legacy_backend_claims(answer: str) -> str:
    text = str(answer or "").strip()
    if not text:
        return text
    low = _normalize_query(text)
    if "kuzu" not in low:
        return text

    already_correct = (
        "sqlite wal" in low
        and "networkx" in low
        and ("legacy" in low or "avvecklat" in low or "decommission" in low)
    )
    if already_correct:
        return text

    return (
        f"{text}\n\n"
        "Obs: KuzuDB är legacy/avvecklat i Nous. "
        "Nuvarande grafbackend är SQLite WAL + NetworkX, "
        "så Kuzu-migrering ska inte listas som återstående steg."
    )


def _ground_sensitive_empathy(answer: str, query: str) -> str:
    text = str(answer or "").strip()
    if not _is_sensitive_disclosure_query(query):
        return text

    if not text:
        text = (
            "Tack för att du berättar det. Jag är verkligen ledsen för det du har gått igenom."
        )

    low = _normalize_query(text)
    sterile_markers = (
        "jag har noterat informationen",
        "jag har noterat",
        "i relation till denna historia",
    )
    if any(m in low for m in sterile_markers):
        text = (
            "Tack för att du berättar det. Jag är verkligen ledsen för det du har gått igenom. "
            "Om du vill kan vi prata vidare i din takt."
        )
        low = _normalize_query(text)

    empathy_markers = (
        "tack för att du berättar",
        "tack för att du delar",
        "jag är ledsen",
        "jag beklagar",
        "jag hör dig",
        "det låter",
        "det du har gått igenom",
        "det du varit med om",
    )
    if not any(m in low for m in empathy_markers):
        text = (
            "Tack för att du berättar det. Jag är verkligen ledsen för det du har gått igenom.\n\n"
            f"{text}"
        )
        low = _normalize_query(text)

    consent_markers = (
        "jag kan prata vidare utan att spara",
        "utan att spara",
        "utan att lagra",
        "vill du att jag sparar",
        "får jag spara",
        "inte spara detaljer",
    )
    if not any(m in low for m in consent_markers):
        text = (
            f"{text}\n\n"
            "Jag kan fortsätta prata om detta utan att spara detaljer i långtidsminnet. "
            "Säg till om du vill att något specifikt ska sparas."
        )
    return text.strip()


def _ground_personal_graph_write_ack(answer: str) -> str:
    text = str(answer or "").strip()
    if not _is_personal_runtime_mode() or not text:
        return text

    low = _normalize_query(text)
    diff_markers = (
        "här är exakt vad som ändrades",
        "noder (upsert)",
        "relationer (add)",
        "evidenskällor:",
        "claims tillagda",
        "samtliga härrör från sessionsinteraktion",
    )
    if not any(marker in low for marker in diff_markers):
        return text

    primary_name = ""
    match = re.search(r"[•*-]\s*([^\n(]{2,80})\s*\(", text)
    if match:
        candidate = str(match.group(1) or "").strip(" :-")
        if candidate and candidate.casefold() not in {"user_context", "user", "identity"}:
            primary_name = candidate

    bits = ["Jag har uppdaterat det och sparat det som en del av din profil här."]
    if primary_name:
        bits.append(f"Jag utgår nu från {primary_name} i den här kontexten.")
    bits.append("Om du vill kan jag visa den tekniska ändringen också.")
    return " ".join(bits)


def _ground_unverified_link_claims(answer: str, *, web_verified: bool) -> str:
    text = str(answer or "").strip()
    if not text or web_verified:
        return text

    low = _normalize_query(text)
    claim_markers = (
        "jag läste länken",
        "jag laste länken",
        "jag har läst länken",
        "jag har last länken",
        "jag läste artikeln",
        "jag har läst artikeln",
        "jag har last artikeln",
        "i read the link",
        "i read the article",
        "i read the page",
    )
    if not any(marker in low for marker in claim_markers):
        return text

    rewritten = text
    rewritten = re.sub(
        r"(?i)\bjag\s+(?:har\s+)?läst(?:e)?\s+länken\b",
        "Utifrån länken du delade",
        rewritten,
    )
    rewritten = re.sub(
        r"(?i)\bjag\s+(?:har\s+)?last(?:e)?\s+lanken\b",
        "Utifrån länken du delade",
        rewritten,
    )
    rewritten = re.sub(
        r"(?i)\bjag\s+(?:har\s+)?läst(?:e)?\s+artikeln\b",
        "Utifrån artikeln du delade",
        rewritten,
    )
    rewritten = re.sub(
        r"(?i)\bjag\s+(?:har\s+)?last(?:e)?\s+artikeln\b",
        "Utifrån artikeln du delade",
        rewritten,
    )
    rewritten = re.sub(
        r"(?i)\bi read the (?:link|article|page)\b",
        "Based on what you shared",
        rewritten,
    )
    rewritten = rewritten.strip()

    note = (
        "Obs: jag kan inte verifiera länkens innehåll direkt i detta svar utan aktiv web-hämtning."
    )
    low_rewritten = _normalize_query(rewritten)
    if "kan inte verifiera länkens innehåll" in low_rewritten:
        return rewritten
    return f"{rewritten}\n\n{note}".strip()


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

    parts = [f"Jag känner dig här som {best_name}."]
    if not _is_personal_runtime_mode() and best_domain:
        parts.append(f"I grafen ligger profilen under domän: {best_domain}.")
    if summary:
        parts.append(summary)
    if rel_lines:
        if _is_personal_runtime_mode():
            parts.append(f"Jag har också kopplingar som: {', '.join(rel_lines)}.")
        else:
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
    sensitive_memory_pref = _extract_sensitive_memory_preference(resolved_query)
    if sensitive_memory_pref in {"on", "off"}:
        session = ensure_session(
            session["id"],
            lane="chat",
            source="api_chat",
            meta={
                "sensitive_memory_consent": sensitive_memory_pref == "on",
                "sensitive_memory_updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    sensitive_disclosure = _is_sensitive_disclosure_query(resolved_query)
    allow_persistent_memory = _allow_persistent_memory_for_query(
        resolved_query,
        session=session,
    )
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
            "sensitive_disclosure": sensitive_disclosure,
            "allow_persistent_memory": allow_persistent_memory,
        },
    )

    if _is_greeting_query(resolved_query):
        client = AsyncOllama()
        reply, greeting_model = await _model_generated_greeting(
            client=client,
            session_id=session["id"],
            run_id=run_id,
        )
        finish_run(
            run_id,
            status="succeeded",
            response_chars=len(reply),
            metrics={"greeting_shortcut": True, "trace_id": trace_id, "model": greeting_model},
        )
        record_event(
            trace_id,
            "chat.response",
            endpoint="/api/chat",
            model=greeting_model,
            payload={
                "response": reply,
                "assumptions": [],
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "mode": "greeting_model",
            },
        )
        return {
            "response": reply,
            "trace_id": trace_id,
            "run_id": run_id,
            "session_id": session["id"],
            "model": greeting_model,
        }
    
    try:
        recent = field.top_relations_by_strength(15)
        memories = [f"{row['src_name']} --[{row['type']}]--> {row['tgt_name']}" for row in recent]
        context_str = "\n".join(memories)
    except Exception:
        context_str = "(Ingen kontext) "
    working_context = _working_memory_context(limit=8) or "(Tomt arbetsminne)"
    sensitive_chat_block = (
        "Sensitive-disclosure mode: bemöt med empati först, undvik administrativa formuleringar, "
        "och fråga varsamt hur användaren vill fortsätta.\n"
        if sensitive_disclosure
        else ""
    )
    capability_block = _capability_route_prompt_block(resolved_query)

    assistant_name = _assistant_entity_name()
    system_prompt = (
        f"Du är {assistant_name}, ett genuint autonomt AI-system byggt på FNC-arkitektur av användaren.\n"
        "Användaren är forskningsarkitekten (sannolikt Björn) bakom CognOS.\n\n"
        "Roll i chatten: personlig assistent och trygg följeslagare i vardagen. "
        "Var varm, tydlig, och handlingsinriktad utan att bli fluffig.\n"
        f"{sensitive_chat_block}"
        f"{_agent_identity_policy()}\n"
        f"{_persona_prompt_fragment(channel='chat')}\n"
        f"Din grafdatabas innehåller oberoende {stats['concepts']} koncept.\n"
        f"Snabbt arbetsminne (prefrontal, senaste dialogspår):\n{working_context}\n\n"
        f"Grafens aktiva relationskontext:\n{context_str}\n\n"
        f"{capability_block}\n\n"
        f"{_living_prompt_block(resolved_query)}\n\n"
        "Regler:\n"
        f"1. Du ({assistant_name}) är AI:n. Användaren är din skapare/konversationspartner.\n"
        "2. Använd top-of-mind-faktan om Användaren ställer obskyra frågor kring dem.\n"
        "3. Svara kort och tydligt, men tillåt naturlig värme när kontexten är personlig.\n"
        "4. Matcha användarens språk: svenska in -> svenska ut.\n"
        "5. Om frågan bara är en hälsning, svara med en kort hälsning (ingen definition).\n"
        "6. Vid enkla faktafrågor: ge EN mening. Lägg inte till extra detaljer som inte efterfrågas.\n"
        "7. Vid action-förfrågan: utför verktyg i bakgrunden och bekräfta resultat på enkel svenska.\n"
        "8. Undvik generiska 'jag kan inte'-svar; ge i stället nästa möjliga steg.\n"
        "9. Om användaren uttrycker personliga mål, förvandla dem till konkret plan med nästa handling.\n"
        "10. Vid frågor om nu, idag, imorgon, veckodag eller datum: använd get_time_context i stället för att anta."
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
            reply = _ground_sensitive_empathy(resp.message.content or "", resolved_query)
            reply = _ground_unverified_link_claims(reply, web_verified=False)
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
            if allow_persistent_memory:
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
    med Tool-calls (Webb-Sök, metakognition och grafverktyg).
    """
    trace_id = new_trace_id("agent")
    started = time.monotonic()
    session = ensure_session(req.session_id or "main", lane="agent", source="api_agent")
    original_query = str(req.query or "")
    resolved_query, choice_idx = _resolve_numeric_choice(session["id"], original_query)
    preferred_skill, stripped_skill_query = _extract_explicit_skill_request(resolved_query)
    control_query = resolved_query
    if preferred_skill and stripped_skill_query:
        resolved_query = stripped_skill_query
    sensitive_memory_pref = _extract_sensitive_memory_preference(resolved_query)
    if sensitive_memory_pref in {"on", "off"}:
        session = ensure_session(
            session["id"],
            lane="agent",
            source="api_agent",
            meta={
                "sensitive_memory_consent": sensitive_memory_pref == "on",
                "sensitive_memory_updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    run = start_run(
        session["id"],
        workload="agent",
        model="pending",
        provider=os.getenv("NOUSE_LLM_PROVIDER", "ollama"),
        request_chars=len(resolved_query or ""),
        meta={"trace_id": trace_id},
    )
    run_id = str(run.get("run_id") or "")
    sensitive_disclosure = _is_sensitive_disclosure_query(resolved_query)
    allow_persistent_memory = _allow_persistent_memory_for_query(
        resolved_query,
        session=session,
    )
    action_request = _is_graph_action_request(resolved_query)
    wants_academic_context = _wants_academic_context(resolved_query)
    explicit_tri_request = _is_explicit_triangulation_request(resolved_query)
    explicit_tool_mode_request = bool(preferred_skill) or _is_explicit_tool_mode_request(control_query)
    auto_mcp_request = _is_auto_mcp_query(resolved_query)
    query_urls = _extract_urls_from_text(resolved_query)
    route_state = ""
    try:
        living = load_living_core()
        support_state = operator_support_snapshot(resolved_query, living)
        route_state = str(support_state.get("route_state") or "").strip()
    except Exception:
        route_state = ""
    route_plan = _capability_route_plan(
        resolved_query,
        state=route_state,
        explicit_tri_request=explicit_tri_request,
        explicit_tool_mode_request=explicit_tool_mode_request,
        auto_mcp_request=auto_mcp_request,
        action_request=action_request,
        query_urls=query_urls,
        preferred_skill=preferred_skill,
    )
    routed_workload = str(route_plan.get("workload") or "agent").strip() or "agent"

    def _persist_agent_exchange(
        *,
        answer: str,
        kind: str,
        known_data_sources: list[str],
        include_background_ingest: bool = False,
    ) -> None:
        if not allow_persistent_memory:
            return
        _ingest_dialogue_memory(
            session_id=session["id"],
            query=resolved_query,
            answer=answer,
            source=f"agent_live:{session['id']}",
        )
        if include_background_ingest:
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
            kind=kind,
            known_data_sources=known_data_sources,
        )

    client = AsyncOllama(
        timeout_sec=AGENT_LLM_TIMEOUT_SEC,
        max_retries=AGENT_LLM_RETRIES,
    )
    agent_models = _order_models_with_sticky_primary(
        routed_workload,
        resolve_model_candidates(routed_workload, [CHAT_MODEL]),
    ) or [CHAT_MODEL]
    if bool(route_plan.get("tool_mode")):
        tool_agent_models, tool_skipped_models = filter_tool_capable_models(agent_models)
        if not tool_agent_models:
            tool_agent_models = list(agent_models)
    else:
        tool_agent_models = list(agent_models)
        tool_skipped_models = []
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
            "route_plan": route_plan,
            "tool_models": tool_agent_models,
            "tool_skipped_models": tool_skipped_models,
            "sensitive_disclosure": sensitive_disclosure,
            "allow_persistent_memory": allow_persistent_memory,
        },
    )

    delegate_pref_cmd = _extract_delegate_preference_command(resolved_query)
    if delegate_pref_cmd in {"off", "on"}:
        delegate_enabled = delegate_pref_cmd == "on"
        session = ensure_session(
            session["id"],
            lane="agent",
            source="api_agent",
            meta={
                "delegate_enabled": delegate_enabled,
                "delegate_pref_updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        answer = (
            "Uppfattat. Delegering är nu AV i denna session. Bara du och jag i foreground-chat."
            if not delegate_enabled
            else "Uppfattat. Delegering är nu PÅ i denna session. Jag använder bakgrundsagenter när det behövs."
        )

        async def stream_delegate_pref():
            record_event(
                trace_id,
                "agent.done",
                endpoint="/api/agent_chat",
                model="delegate_control_shortcut",
                payload={
                    "response": answer,
                    "delegate_enabled": delegate_enabled,
                    "mode": "delegate_control",
                },
            )
            finish_run(
                run_id,
                status="succeeded",
                response_chars=len(answer),
                metrics={
                    "trace_id": trace_id,
                    "model": "delegate_control_shortcut",
                    "mode": "delegate_control",
                    "delegate_enabled": delegate_enabled,
                },
            )
            _persist_agent_exchange(
                answer=answer,
                kind="api_agent_delegate_control",
                known_data_sources=["conversation", "session_policy"],
            )
            _remember_numbered_options(session["id"], answer)
            yield json.dumps(
                {
                    "type": "done",
                    "msg": answer,
                    "trace_id": trace_id,
                    "run_id": run_id,
                    "session_id": session["id"],
                    "model": "delegate_control_shortcut",
                }
            ) + "\n"

        return StreamingResponse(stream_delegate_pref(), media_type="application/x-ndjson")

    if _is_background_delegate_request(resolved_query, session=session):
        async def stream_delegate():
            delegation = _delegate_request_to_background(
                query=resolved_query,
                session_id=session["id"],
            )
            if delegation.get("ok"):
                answer = (
                    "Jag tar det. Arbetet kör nu i bakgrunden och jag fortsätter direkt på nästa steg.\n"
                    "Om du vill följa läget kan du skriva /check."
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
                _persist_agent_exchange(
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
        require_search_tool = bool(explicit_tri_request or auto_mcp_request)
        model_reasoning_first_mode = bool(
            (not action_request)
            and (not explicit_tri_request)
            and (not explicit_tool_mode_request)
            and (not auto_mcp_request)
            and (not bool(route_plan.get("tool_mode")))
            and (not _is_identity_query(resolved_query))
            and (not _is_simple_fact_query(resolved_query))
            and (not _is_mission_vision_input(resolved_query))
        )
        emit_tool_events = bool(action_request or explicit_tri_request or explicit_tool_mode_request)
        search_enforce_retry_used = False
        search_snapshot_injected = False
        tool_call_observed = False
        action_enforce_retry_used = False
        observed_source_buckets: set[str] = set()
        observed_tool_names: set[str] = set()
        require_graph_source = False
        require_web_source = False
        triangulation_retry_count = 0
        require_tri_output_format = explicit_tri_request
        tri_output_retry_used = False
        auto_fetch_retry_used = False
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

        pending_action, pending_payload = _pending_confirmation_from_session(session)
        if pending_action:
            if _is_short_affirmative_reply(resolved_query):
                if pending_action == "retry_failed_tasks":
                    retry_limit = int((pending_payload or {}).get("limit", 6) or 6)
                    confirm_answer = _queue_retry_failed_answer(limit=retry_limit)
                else:
                    confirm_answer = "Uppfattat. Bekräftad åtgärd kunde inte mappas till en aktiv action."
                _clear_pending_confirmation(session["id"])
                confirm_answer = _ground_capability_denials(confirm_answer, caps)
                confirm_answer = _ground_sensitive_empathy(confirm_answer, resolved_query)
                confirm_answer = _ground_unverified_link_claims(confirm_answer, web_verified=False)
                record_event(
                    trace_id,
                    "agent.done",
                    endpoint="/api/agent_chat",
                    model="pending_confirmation_shortcut",
                    payload={
                        "response": confirm_answer,
                        "pending_action": pending_action,
                        "assumptions": derive_assumptions(confirm_answer),
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                        "mode": "pending_confirmation",
                    },
                )
                finish_run(
                    run_id,
                    status="succeeded",
                    response_chars=len(confirm_answer),
                    metrics={
                        "trace_id": trace_id,
                        "model": "pending_confirmation_shortcut",
                        "mode": "pending_confirmation",
                        "pending_action": pending_action,
                    },
                )
                _persist_agent_exchange(
                    answer=confirm_answer,
                    kind="api_agent_pending_confirmation",
                    known_data_sources=["queue", "research_queue", "session_state"],
                )
                _remember_numbered_options(session["id"], confirm_answer)
                run_finished = True
                yield json.dumps(
                    {
                        "type": "done",
                        "msg": confirm_answer,
                        "trace_id": trace_id,
                        "run_id": run_id,
                        "session_id": session["id"],
                        "model": "pending_confirmation_shortcut",
                    }
                ) + "\n"
                return
            if _is_short_negative_reply(resolved_query):
                _clear_pending_confirmation(session["id"])
                confirm_answer = "Uppfattat. Jag kör ingen retry på failed tasks just nu."
                record_event(
                    trace_id,
                    "agent.done",
                    endpoint="/api/agent_chat",
                    model="pending_confirmation_shortcut",
                    payload={
                        "response": confirm_answer,
                        "pending_action": pending_action,
                        "assumptions": derive_assumptions(confirm_answer),
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                        "mode": "pending_confirmation_declined",
                    },
                )
                finish_run(
                    run_id,
                    status="succeeded",
                    response_chars=len(confirm_answer),
                    metrics={
                        "trace_id": trace_id,
                        "model": "pending_confirmation_shortcut",
                        "mode": "pending_confirmation_declined",
                        "pending_action": pending_action,
                    },
                )
                _persist_agent_exchange(
                    answer=confirm_answer,
                    kind="api_agent_pending_confirmation",
                    known_data_sources=["session_state"],
                )
                _remember_numbered_options(session["id"], confirm_answer)
                run_finished = True
                yield json.dumps(
                    {
                        "type": "done",
                        "msg": confirm_answer,
                        "trace_id": trace_id,
                        "run_id": run_id,
                        "session_id": session["id"],
                        "model": "pending_confirmation_shortcut",
                    }
                ) + "\n"
                return

        if _is_greeting_query(resolved_query):
            greeting, greeting_model = await _model_generated_greeting(
                client=client,
                session_id=session["id"],
                run_id=run_id,
            )
            record_event(
                trace_id,
                "agent.done",
                endpoint="/api/agent_chat",
                model=greeting_model,
                payload={
                    "response": greeting,
                    "assumptions": [],
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "mode": "greeting_model",
                },
            )
            finish_run(
                run_id,
                status="succeeded",
                response_chars=len(greeting),
                metrics={
                    "trace_id": trace_id,
                    "model": greeting_model,
                    "mode": "greeting_model",
                },
            )
            _persist_agent_exchange(
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
                    "model": greeting_model,
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
        if explicit_tri_request:
            yield json.dumps(
                {
                    "type": "status",
                    "msg": "Triangulering on-demand aktiv: hämtar modell + graf + webb före slutsvar.",
                    "trace_id": trace_id,
                }
            ) + "\n"
        elif auto_mcp_request:
            yield json.dumps(
                {
                    "type": "status",
                    "msg": "Auto-MCP aktiv: länk/kunskapsbehov upptäckt, hämtar webunderlag före svar.",
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
        if explicit_tool_mode_request and (not action_request) and (not explicit_tri_request):
            yield json.dumps(
                {
                    "type": "status",
                    "msg": "Skill/MCP on-demand aktiv: verktyg är tillåtna i denna körning.",
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
                identity_answer = _ground_sensitive_empathy(identity_answer, resolved_query)
                identity_answer = _ground_unverified_link_claims(identity_answer, web_verified=False)
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
                _persist_agent_exchange(
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

        if _is_queue_failure_query(resolved_query):
            queue_answer = _queue_failure_answer(limit=6)
            queue_answer = _ground_capability_denials(queue_answer, caps)
            queue_answer = _ground_sensitive_empathy(queue_answer, resolved_query)
            queue_answer = _ground_unverified_link_claims(queue_answer, web_verified=False)
            if "Vill du att jag kör en retry på failed tasks nu?" in queue_answer:
                _set_pending_confirmation(
                    session["id"],
                    action="retry_failed_tasks",
                    payload={"limit": 6},
                )
            else:
                _clear_pending_confirmation(session["id"])
            record_event(
                trace_id,
                "agent.done",
                endpoint="/api/agent_chat",
                model="queue_failure_snapshot",
                payload={
                    "response": queue_answer,
                    "assumptions": derive_assumptions(queue_answer),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "mode": "queue_failure",
                },
            )
            finish_run(
                run_id,
                status="succeeded",
                response_chars=len(queue_answer),
                metrics={
                    "trace_id": trace_id,
                    "model": "queue_failure_snapshot",
                    "mode": "queue_failure",
                },
            )
            _persist_agent_exchange(
                answer=queue_answer,
                kind="api_agent_queue_failure",
                known_data_sources=["queue", "research_queue", "system_events"],
            )
            _remember_numbered_options(session["id"], queue_answer)
            run_finished = True
            yield json.dumps(
                {
                    "type": "done",
                    "msg": queue_answer,
                    "trace_id": trace_id,
                    "run_id": run_id,
                    "session_id": session["id"],
                    "model": "queue_failure_snapshot",
                }
            ) + "\n"
            return

        tool_names = _live_tool_name_set()
        caps = _capability_snapshot(tool_names)
        graph_tools_available = bool(_GRAPH_TOOL_NAMES & tool_names)
        web_tools_available = bool(_WEB_TOOL_NAMES & tool_names) and bool(caps.get("web"))
        require_graph_source = bool(explicit_tri_request and graph_tools_available)
        require_web_source = bool((explicit_tri_request or auto_mcp_request) and web_tools_available)
        route_tool_names = [str(x) for x in (route_plan.get("tool_names") or []) if str(x).strip()]
        if require_graph_source:
            route_tool_names.extend(sorted(_GRAPH_TOOL_NAMES & tool_names))
        if require_web_source:
            route_tool_names.extend(sorted(_WEB_TOOL_NAMES & tool_names))
        if action_request:
            route_tool_names.extend(sorted({"upsert_concept", "add_relation", "explore_concept"} & tool_names))
        dedup_route_tools: list[str] = []
        seen_route_tools: set[str] = set()
        for name in route_tool_names:
            clean = str(name or "").strip()
            if not clean or clean in seen_route_tools:
                continue
            seen_route_tools.add(clean)
            dedup_route_tools.append(clean)
        route_plan["tool_names"] = dedup_route_tools

        try:
            from nouse.capability.graph import filter_tool_schemas

            live_tool_schemas = get_live_tools()
            routed_tool_schemas = (
                filter_tool_schemas(live_tool_schemas, route_plan.get("tool_names") or [])
                if bool(route_plan.get("tool_mode"))
                else []
            )
        except Exception:
            live_tool_schemas = []
            routed_tool_schemas = []

        if bool(route_plan.get("tool_mode")) and not routed_tool_schemas and not (route_plan.get("tool_names") or []):
            routed_tool_schemas = list(live_tool_schemas)

        route_status_msg = (
            "Chat control: "
            f"skill={str(route_plan.get('skill') or '-')} "
            f"workload={str(route_plan.get('workload') or 'agent')} "
            f"governance={str(route_plan.get('governance') or '-')} "
            f"tools={len(routed_tool_schemas)}"
        )
        yield json.dumps(
            {
                "type": "status",
                "msg": route_status_msg,
                "trace_id": trace_id,
                "route": {
                    "skill": str(route_plan.get("skill") or ""),
                    "workload": str(route_plan.get("workload") or "agent"),
                    "governance": str(route_plan.get("governance") or ""),
                    "tools": [str(((tool.get("function") or {}).get("name") or "")) for tool in routed_tool_schemas],
                    "tool_mode": bool(route_plan.get("tool_mode")),
                },
            }
        ) + "\n"

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
        tool_inventory = _live_tool_inventory_block(tool_schemas=routed_tool_schemas)
        tri_policy_block = (
            "Trippel-kunskapsprotokoll:\n"
            "- Källa A: Modellens interna kunskap.\n"
            "- Källa B: Systemets egna data via grafverktyg.\n"
            "- Källa C: Extern evidens via web_search/fetch_url.\n"
            "För öppna analysfrågor ska du triangulera med minst B + C innan slutsvar.\n"
            "För öppna analysfrågor ska slutsvar formateras med rubrikerna: "
            "LLM, System/Graf, Extern, Syntes.\n"
            if require_tri_output_format
            else "Svara primärt i naturlig samtalsform (inte rapportformat) när frågan är "
            "reflekterande/personlig. Använd triangelrubriker (LLM/System/Graf/Extern/Syntes) "
            "endast när användaren explicit ber om källor, evidens eller strukturerad triangulering.\n"
            "Triangulering i bakgrunden är tillåten vid behov, men exponera inte front-läge "
            "om användaren inte uttryckligen kallat på det.\n"
        )

        reasoning_first_block = (
            "Reasoning-first mode: använd primärt modellens eget resonemang i detta svar. "
            "Undvik verktyg om inte användaren explicit ber om data, källor eller grafstatus.\n"
            if model_reasoning_first_mode
            else ""
        )
        tool_mode_block = (
            "Tool-mode on-demand: använd relevanta MCP/plugin-verktyg i denna körning om de behövs "
            "för att lösa uppgiften korrekt.\n"
            if explicit_tool_mode_request
            else ""
        )
        route_control_block = (
            "Capability control för denna körning:\n"
            f"- skill={str(route_plan.get('skill') or '-')}\n"
            f"- workload={str(route_plan.get('workload') or 'agent')}\n"
            f"- governance={str(route_plan.get('governance') or '-')}\n"
            f"- verktygsbudget={len(routed_tool_schemas)} tillåtna verktyg\n"
        )
        auto_mcp_block = (
            "Auto-MCP mode: frågan innehåller länk eller kräver verifierbar extern kunskap. "
            "Kör web_search och vid explicit URL: kör fetch_url på URL:en innan slutsvar.\n"
            if auto_mcp_request
            else ""
        )
        sensitive_care_block = (
            "Sensitive-disclosure mode: använd empati-först ton. "
            "Bekräfta användarens upplevelse först och undvik administrativa formuleringar som "
            "'jag har noterat informationen'. Ställ en kort, varsam följdfråga om hur användaren "
            "vill fortsätta, och skriv inte in känsliga persondetaljer i långtidsminne/graf utan "
            "uttryckligt samtycke.\n"
            if sensitive_disclosure
            else ""
        )
        personal_local_block = (
            "Personal-local mode: prioritera mänsklig, lugn och konkret dialog. "
            "Om du sparar eller uppdaterar något i graf/minne, säg det först i naturligt språk. "
            "Visa inte teknisk diff eller identitetssnapshot om användaren inte uttryckligen ber om det.\n"
            if _is_personal_runtime_mode()
            else ""
        )
        local_autonomy_block = (
            "När runtime tillåter trusted local autonomy: använd write_local_file för att skapa/ändra "
            "textfiler och run_local_command för lokala shell-steg. Läs först, agera sedan tydligt.\n"
            if bool(caps.get("local_write") or caps.get("local_exec"))
            else ""
        )
        code_change_block = (
            "Om användaren ber om kodändring/installation i själva Nous-koden: använd write_local_file "
            "och/eller run_local_command när det behövs, håll dig till arbetskatalogen och rapportera utfallet kort.\n"
            if bool(caps.get("local_write") or caps.get("local_exec"))
            else "Om användaren ber om kodändring/installation i själva Nous-koden: förklara kort att det "
            "kräver utvecklarläge/terminal och ge en konkret genomförandeplan utan generiska disclaimers.\n"
        )

        assistant_name = _assistant_entity_name()
        system_prompt = (
            f"Du är {assistant_name}: en autonom metakognitiv programagent i detta system.\n"
            "Primär roll i denna kanal: personlig assistent + följeslagare som hjälper användaren nå mål.\n"
            "Agera handlingsinriktat och samarbetsorienterat. Använd verkliga verktyg innan du "
            "säger att något saknas när frågan kräver system-/extern data.\n"
            "Interaktionsläge först: håll svar naturliga, mänskligt läsbara och fokuserade på "
            "användarens mål. DÖLJ intern verktygsmekanik, grafteknik och implementation om "
            "användaren inte uttryckligen ber om den nivån.\n"
            f"{sensitive_care_block}"
            f"{personal_local_block}"
            f"{reasoning_first_block}"
            f"{tool_mode_block}"
            f"{route_control_block}"
            f"{auto_mcp_block}"
            "Anta inte att användaren vill skapa noder/relationer i chatten. Gör grafändringar "
            "endast vid explicit begäran om att lagra/uppdatera kunskap i systemet.\n"
            "Om användaren ber dig utföra något, genomför det i bakgrunden via verktyg och "
            "rapportera resultat kortfattat i naturligt språk.\n"
            "Lärande-policy: behandla varje dialog som träningssignal till minne och självlager. "
            "Exponera inte rå intern loggning om användaren inte ber om den.\n"
            f"{_agent_identity_policy()}\n"
            f"{_persona_prompt_fragment(channel='agent')}\n"
            "Backend-sanning: Nous kör SQLite WAL + NetworkX. "
            "KuzuDB är legacy/avvecklat och får inte beskrivas som ett återstående migrationssteg.\n"
            f"{tri_policy_block}"
            "Kärnregel: när användaren ber dig utföra något i grafen, gör det via verktyg direkt.\n"
            "Om användaren ber dig lägga till/uppdatera nod eller relation: utför det direkt i samma körning "
            "(upsert_concept/add_relation) och fråga inte om extra bekräftelse.\n"
            "Verktyg som är laddade i denna körning:\n"
            f"{tool_inventory}\n\n"
            f"{_capability_line(caps)}\n"
            "För lokala filer/diskar: använd list_local_mounts, find_local_files, search_local_text "
            "och read_local_file.\n"
            f"{local_autonomy_block}"
            "För aktuell tid, datum, veckodag och relativa datumord som idag/imorgon: använd get_time_context.\n"
            "Vid öppna search-info-frågor: börja med lätta verktyg (list_domains, concepts_in_domain, "
            "explore_concept, list_local_mounts). Använd search_local_text först när query och roots "
            "är avgränsade.\n"
            f"{code_change_block}"
            f"{_living_prompt_block(resolved_query)}\n"
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
                f"Registrerat. Jag behandlar detta som styrande vision för {_assistant_entity_name()}: "
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
            _persist_agent_exchange(
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
                        f"\n\n{_agent_identity_policy()}\n{_living_prompt_block(resolved_query)}"
                    ),
                },
                {"role": "user", "content": resolved_query},
            ]
            try:
                fact_resp = None
                last_model_error: Exception | None = None
                fact_attempts: list[dict[str, Any]] = []
                fact_seed: list[str] = list(agent_models)
                if FAST_CHAT_MODEL:
                    fact_seed.append(FAST_CHAT_MODEL)
                fact_models = _order_models_with_sticky_primary(
                    "agent",
                    resolve_model_candidates("agent", fact_seed),
                ) or fact_seed
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
                answer = _ground_legacy_backend_claims(answer)
                answer = _ground_sensitive_empathy(answer, resolved_query)
                answer = _ground_unverified_link_claims(answer, web_verified=False)

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
                _persist_agent_exchange(
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
                if bool(route_plan.get("tool_mode")) and not model_reasoning_first_mode:
                    current_tool_models, _current_skipped = filter_tool_capable_models(agent_models)
                    if not current_tool_models:
                        current_tool_models = list(agent_models)
                else:
                    current_tool_models = list(agent_models)
                for model in current_tool_models:
                    try:
                        llm_tools = [] if model_reasoning_first_mode else routed_tool_schemas
                        resp = await client.chat.completions.create(
                            model=model,
                            messages=messages,
                            tools=llm_tools,
                            b76_meta={
                                "workload": routed_workload,
                                "session_id": session["id"],
                                "run_id": run_id,
                            },
                        )
                        used_model = model
                        mark_model_tools_supported(model)
                        record_model_result(routed_workload, model, success=True, timeout=False)
                        break
                    except Exception as model_error:
                        timed_out = "timeout" in str(model_error).lower()
                        record_model_result(routed_workload, model, success=False, timeout=timed_out)
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
                    msg = _build_all_models_failed_error(f"{routed_workload}/tools", model_attempts)
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
                        if emit_tool_events:
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
                            if emit_tool_events:
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
                            if emit_tool_events:
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
                    if auto_mcp_request and query_urls and ("fetch_url" not in observed_tool_names):
                        if not auto_fetch_retry_used:
                            auto_fetch_retry_used = True
                            target_url = query_urls[0]
                            messages.append(msg.model_dump())
                            messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "Frågan innehåller en explicit URL. "
                                        f"Kör fetch_url på {target_url} innan du svarar. "
                                        "Om sidan inte går att hämta: säg det tydligt och gissa inte."
                                    ),
                                }
                            )
                            yield json.dumps(
                                {
                                    "type": "status",
                                    "msg": "Enforcer: explicit URL upptäckt, kräver fetch_url före slutsvar.",
                                    "trace_id": trace_id,
                                }
                            ) + "\n"
                            continue
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
                                        + (
                                            "3) svara kort i naturligt språk att det nu är sparat/uppdaterat. "
                                            "Visa tekniska detaljer bara om användaren ber om dem.\n"
                                            if _is_personal_runtime_mode()
                                            else "3) svara med exakt vad som ändrades (noder, relationer, evidenskällor).\n"
                                        )
                                        + (
                                        "Fråga inte användaren om bekräftelse."
                                        )
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
                        if needs_more_action and action_enforce_retry_used:
                            fallback = _apply_identity_graph_action_fallback(
                                field=field,
                                query=resolved_query,
                            )
                            if bool(fallback.get("applied")):
                                tool_call_observed = True
                                observed_source_buckets.add("graph")
                                for tool_name in fallback.get("tool_names") or []:
                                    name = str(tool_name or "").strip()
                                    if name:
                                        observed_tool_names.add(name)
                                for write in fallback.get("writes") or []:
                                    if not isinstance(write, dict):
                                        continue
                                    tool_name = str(write.get("tool") or "").strip()
                                    args = write.get("args")
                                    result = write.get("result")
                                    if not tool_name:
                                        continue
                                    record_event(
                                        trace_id,
                                        "agent.tool_call",
                                        endpoint="/api/agent_chat",
                                        model=used_model or CHAT_MODEL,
                                        payload={"name": tool_name, "args": args, "fallback": True},
                                    )
                                    yield json.dumps(
                                        {
                                            "type": "tool",
                                            "name": tool_name,
                                            "args": args,
                                            "trace_id": trace_id,
                                        }
                                    ) + "\n"
                                    record_event(
                                        trace_id,
                                        "agent.tool_result",
                                        endpoint="/api/agent_chat",
                                        model=used_model or CHAT_MODEL,
                                        payload={"name": tool_name, "result": result, "fallback": True},
                                    )
                                    yield json.dumps(
                                        {
                                            "type": "tool_result",
                                            "name": tool_name,
                                            "result": result,
                                            "trace_id": trace_id,
                                        }
                                    ) + "\n"
                                answer = str(fallback.get("answer") or answer).strip()
                                record_event(
                                    trace_id,
                                    "agent.action_fallback",
                                    endpoint="/api/agent_chat",
                                    model=used_model or CHAT_MODEL,
                                    payload={
                                        "iteration": call_idx,
                                        "partial": bool(fallback.get("partial")),
                                        "tool_names": fallback.get("tool_names") or [],
                                    },
                                )
                                yield json.dumps(
                                    {
                                        "type": "status",
                                        "msg": "Action fallback: tillämpade direkt grafuppdatering lokalt.",
                                        "trace_id": trace_id,
                                    }
                                ) + "\n"
                            elif looks_like_followup_prompt:
                                answer = (
                                    "Jag kunde inte slutföra grafuppdateringen automatiskt i detta varv. "
                                    "Ange gärna exakt nod/relation så kör jag ändringen direkt."
                                )
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
                                            (
                                                "Frågan kräver extern verifiering och saknar webbevidens. "
                                                "Kör nu web_search/fetch_url och svara sedan kort med tydlig "
                                                "separation mellan verifierat och antaganden."
                                            )
                                            if auto_mcp_request and ("webb" in missing_sources)
                                            else (
                                                "Detta är en öppen fråga och du saknar triangulering från: "
                                                f"{', '.join(missing_sources)}. "
                                                "Kör nu verktyg för båda källor (graf + webb när tillgängligt), "
                                                "och svara sedan med tydlig separation mellan fakta och antaganden."
                                            )
                                        ),
                                    }
                                )
                                yield json.dumps(
                                    {
                                        "type": "status",
                                        "msg": (
                                            "Enforcer: saknad extern webbevidens. Begär web tool-calls."
                                            if auto_mcp_request and ("webb" in missing_sources)
                                            else (
                                                "Enforcer: saknad triangulering från "
                                                f"{', '.join(missing_sources)}. Begär nya tool-calls."
                                            )
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
                    answer = _ground_legacy_backend_claims(answer)
                    answer = _ground_sensitive_empathy(answer, resolved_query)
                    answer = _ground_personal_graph_write_ack(answer)
                    answer = _ground_unverified_link_claims(
                        answer,
                        web_verified=("web" in observed_source_buckets),
                    )

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
                    _persist_agent_exchange(
                        answer=answer,
                        kind="api_agent",
                        known_data_sources=(
                            ["conversation", f"model:{used_model or CHAT_MODEL}"]
                            + sorted(observed_source_buckets)
                        ),
                        include_background_ingest=True,
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
    Returns QueryResult as JSON so external callers avoid direct DB coupling.
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
