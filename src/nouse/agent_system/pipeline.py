"""ICM stage pipeline for the Jarvis agent system.

Runs stages 01-05 in order. See ../../ICM-agents.md and
../../stages/*/CONTEXT.md for the contract each stage follows. This module
enforces the same discipline in code: the LLM parses (stage 01) and
verbalizes (stage 04); routing (stage 02) and validation (stage 03) are
plain Python, never an LLM decision.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nouse.agent_system.contract import AgentContract
from nouse.agent_system.executors import call_mcp_executor, call_model_executor, open_relay_executor
from nouse.agent_system.folder_loader import load_all_agents, read_policy_text
from nouse.capability.graph import build_route_plan
from nouse.mcp_gateway.gateway import (
    kernel_get_working_context,
    kernel_log_outcome,
    kernel_write_episode,
)

_NOUS_ROOT = Path(__file__).resolve().parents[3]
_RUNS_DIR = _NOUS_ROOT / "runs"
_LOGS_LLM_DIR = _NOUS_ROOT / "logs" / "llm"
_LOGS_NOUS_DIR = _NOUS_ROOT / "logs" / "nous"

# Invariant path marker for this deployment's research corpus. Deployment-
# specific extra markers come from NOUSE_RESEARCH_LOCAL_MARKERS (see
# jarvis-policy.md hard rule 1) — this default is a safety net, not the
# full rule.
_DEFAULT_RESEARCH_MARKERS = ["02_library/research"]

# MVP heuristic for "too large for the local front model" — deterministic,
# not an LLM judgment call. Expected to be refined once real usage data
# exists (see icm-hardening backlog pattern: start simple, measure, refine).
_LARGE_PROJECT_MARKERS = [
    "skriv om hela",
    "skriv om artikel",
    "skriv om min artikel",
    "bygg",
    "analysera hela",
    "förbättra argumentationen",
    "rewrite the whole",
    "full rewrite",
    "implementera",
    "refaktorera",
]

# Deterministic domain-intent heuristic, same shape as
# daemon/sources.py::scope_from_path — ordered substring match, no LLM,
# checked most-specific-first (write markers before their read fallback,
# since e.g. "skicka mejl" also contains "mejl").
_DOMAIN_MARKERS: list[tuple[str, list[str]]] = [
    ("calendar_write", ["boka möte", "boka in", "skapa möte", "lägg till möte", "lägg in i kalendern"]),
    ("calendar_read", ["kalender", "mina möten", "kommande möte", "vad har jag för möte", "schema"]),
    ("mail_write", ["skicka mejl", "skicka ett mejl", "svara på mejl", "maila", "skriv ett mejl", "skicka epost"]),
    ("mail_read", ["mejl", "mail", "inkorg", "olästa", "e-post"]),
    ("voice_capture", ["anteckna", "notera det här", "kom ihåg det här", "spara den här tanken", "diktera"]),
]


def _classify_domain_intent(text: str) -> str:
    t = text.lower()
    for label, markers in _DOMAIN_MARKERS:
        if any(marker in t for marker in markers):
            return label
    return ""


async def _extract_json_via_model(*, instruction: str, raw_text: str) -> dict:
    """Small, reusable JSON-extraction call — same discipline as stage 01:
    the model extracts/drafts, it does not decide whether to act.
    """
    result = await call_model_executor(
        executor="gemma4:e2b",
        system_prompt=instruction,
        user_text=raw_text,
        executor_options={"think": False},
    )
    if not result["ok"]:
        return {}
    try:
        candidate = json.loads(_strip_json_fence(result["content"]))
        return candidate if isinstance(candidate, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_run_id() -> str:
    return f"run_{datetime.now().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"


def _research_markers() -> list[str]:
    raw = os.getenv("NOUSE_RESEARCH_LOCAL_MARKERS", "")
    extra = [m.strip().lower() for m in raw.split(",") if m.strip()]
    return _DEFAULT_RESEARCH_MARKERS + extra


def _looks_like_large_project(text: str) -> bool:
    t = text.lower()
    return any(marker in t for marker in _LARGE_PROJECT_MARKERS)


def _touches_research(text: str) -> bool:
    t = text.lower()
    if any(marker in t for marker in _research_markers()):
        return True
    return _touches_research_by_scope(text)


def _touches_research_by_scope(text: str) -> bool:
    """2026-08-25 (see IIC/04_SYSTEM/agents/nous-agency-model.md, Axel 1):
    the marker list above is a manually maintained snapshot
    (NOUSE_RESEARCH_LOCAL_MARKERS) — real and already reasonably populated
    (it already lists "plg" etc.), but it silently drifts out of sync as
    new research topics/papers appear. scope_from_path() classifies new
    IIC content automatically, with no list to maintain — reuse that exact
    mechanism (same pattern-matching style research-guard/AGENT.md already
    says this check should follow) instead of growing a second,
    separately-maintained keyword list.

    scope_from_path() only does string pattern-matching (no filesystem
    access), so it is safe to call on arbitrary request text, not just
    real paths — this catches a request that mentions an IIC path
    directly, even one not in the curated marker list. It intentionally
    checks only research_plg/iic_general, not the full SENSITIVE_SCOPES
    set — personal_health/user_model/computer_general are governed by
    other rules (workspace scoping, not this one), and folding them in
    here would over-trigger hard rule 1 for content it was never about.

    Does NOT yet cover "known project names from 01_PROJECTS/*" per
    research-guard/AGENT.md's documented intent — that needs real file-
    path resolution earlier in the pipeline (routing_decision has no
    structured path field today, only free-text "entities"), which is a
    separate, larger change, deliberately not bundled into this one."""
    from nouse.daemon.sources import scope_from_path

    return scope_from_path(Path(text)) in {"research_plg", "iic_general"}


def _strip_json_fence(text: str) -> str:
    """Small local models routinely wrap JSON answers in a markdown code
    fence even when told not to ("```json\\n{...}\\n```"). Strip it before
    parsing rather than let every call site special-case it.
    """
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[: -3]
    return t.strip()


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- Stage 01 — parse, don't answer, don't route ----------

async def _stage01_parse_request(run_dir: Path, request_text: str) -> dict:
    system_prompt = (
        "Du extraherar bara avsikt och entiteter ur en anvandarforfragan. "
        "Svara ENDAST med ett kort JSON-objekt: "
        '{"intent_summary": "...", "entities": ["..."]}. '
        "Svara inte pa fragan. Fatta inget routingbeslut."
    )
    result = await call_model_executor(
        executor="gemma4:e2b",
        system_prompt=system_prompt,
        user_text=request_text,
        executor_options={"think": False},
    )
    intent_summary = ""
    entities: list[str] = []
    if result["ok"]:
        try:
            candidate = json.loads(_strip_json_fence(result["content"]))
            if isinstance(candidate, dict):
                intent_summary = str(candidate.get("intent_summary", ""))
                entities = list(candidate.get("entities", []) or [])
        except (json.JSONDecodeError, TypeError):
            intent_summary = result["content"][:200]

    structured_query = {
        "raw_text": request_text,
        "intent_summary": intent_summary,
        "entities": entities,
        "interface_ok": result["ok"],
        "interface_error": result["error"],
    }
    _write_json(run_dir / "01_parse_request" / "structured_query.json", structured_query)
    return structured_query


# ---------- Stage 02 — pure code routing, no LLM decision ----------

def _stage02_engine_query(run_dir: Path, structured_query: dict) -> dict:
    raw_text = structured_query["raw_text"]
    agents = load_all_agents()
    route_plan = build_route_plan(raw_text)
    skill = str(route_plan.get("skill", ""))
    is_large = _looks_like_large_project(raw_text)
    domain = _classify_domain_intent(raw_text)

    matched: AgentContract | None = None
    if is_large:
        matched = next((a for a in agents.values() if "large_project" in a.match), None)
    if matched is None and domain:
        matched = next((a for a in agents.values() if domain in a.match), None)
    if matched is None:
        matched = next((a for a in agents.values() if skill in a.match), None)

    grounding: dict[str, Any] = {}
    if matched is not None:
        try:
            grounding = kernel_get_working_context(limit=6)
        except Exception:
            grounding = {}

    routing_decision = {
        "raw_text": raw_text,
        "classified_skill": skill,
        "classified_domain": domain,
        "is_large_project": is_large,
        "agent_id": matched.id if matched else "",
        "agent_dir": matched.agent_dir_name if matched else "",
        "proposed_executor": matched.executor if matched else "",
        "proposed_executor_options": matched.executor_options if matched else {},
        "works_where": matched.works_where if matched else "",
        "forbidden": matched.forbidden if matched else [],
        "grounding": grounding,
    }
    _write_json(run_dir / "02_engine_query" / "routing_decision.json", routing_decision)
    return routing_decision


# ---------- Stage 03 — rule-based validation only ----------

def _stage03_structural_validation(run_dir: Path, routing_decision: dict) -> dict:
    policy_text = read_policy_text("jarvis-policy.md")
    if not policy_text:
        report = {
            "generation_allowed": False,
            "error_code": "POLICY_UNAVAILABLE",
            "reason": "NOUSE_AGENT_POLICY_DIR unset or unreadable",
        }
        _write_json(run_dir / "03_structural_validation" / "validation_report.json", report)
        return report

    if not routing_decision.get("agent_id"):
        report = {
            "generation_allowed": False,
            "error_code": "ROUTE_NOT_FOUND",
            "reason": "no agent card matched the classified intent",
        }
        _write_json(run_dir / "03_structural_validation" / "validation_report.json", report)
        return report

    executor = str(routing_decision.get("proposed_executor", ""))
    is_cloud_or_relay = executor.startswith("relay:") or "/" in executor
    if is_cloud_or_relay and _touches_research(routing_decision.get("raw_text", "")):
        report = {
            "generation_allowed": False,
            "error_code": "RESEARCH_LOCAL_VIOLATION",
            "reason": "request touches research-local markers; forced-local override required",
            "forced_executor": "gemma4:e2b",
        }
        _write_json(run_dir / "03_structural_validation" / "validation_report.json", report)
        return report

    report = {"generation_allowed": True, "error_code": None, "reason": ""}
    _write_json(run_dir / "03_structural_validation" / "validation_report.json", report)
    return report


# ---------- Stage 04 helpers: MCP-backed agents and voice-capture ----------

_LJUDANTECKNINGAR_DIR = Path("/home/bjornwikstrom/IIC/00_INBOX/ljudanteckningar")


async def _verbalize(*, system_prompt: str, context: Any, raw_text: str) -> dict:
    # NOT "if context else ''" - an empty list/dict is a real, valid tool
    # result ("nothing found") and must still reach the model as such,
    # not be silently dropped into a contextless prompt that then invites
    # it to guess.
    context_note = f"\n\nData: {json.dumps(context, ensure_ascii=False)}" if context is not None else ""
    return await call_model_executor(
        executor="gemma4:e2b",
        system_prompt=system_prompt + context_note,
        user_text=raw_text,
        executor_options={"think": False},
    )


async def _dispatch_mcp_agent(run_dir: Path, agent_id: str, executor: str, raw_text: str) -> dict:
    if agent_id == "mail-triage-001":
        call = await call_mcp_executor(
            executor=executor, arguments={"unreadOnly": True, "maxResults": 10, "daysBack": 14}
        )
        if not call["ok"]:
            return {"ok": False, "error_code": "TOOL_UNAVAILABLE", "content": call["error"]}
        if not call["result"]:  # empty is a known, deterministic case - don't ask the model to phrase it
            return {"ok": True, "error_code": None, "content": "Inga olästa mejl."}
        verbalized = await _verbalize(
            system_prompt=(
                "Du ar Jarvis. Sammanfatta kort pa svenska vilka olasta mejl som finns, "
                "baserat ENDAST pa datan nedan. Hitta inte pa avsandare eller amnen."
            ),
            context=call["result"],
            raw_text=raw_text,
        )
        return {"ok": True, "error_code": None, "content": verbalized["content"] or "Inga olästa mejl."}

    if agent_id == "calendar-lookup-001":
        call = await call_mcp_executor(executor=executor, arguments={"maxResults": 10})
        if not call["ok"]:
            return {"ok": False, "error_code": "TOOL_UNAVAILABLE", "content": call["error"]}
        if not call["result"]:
            return {"ok": True, "error_code": None, "content": "Inga kommande möten hittade."}
        verbalized = await _verbalize(
            system_prompt=(
                "Du ar Jarvis. Sammanfatta kort pa svenska kommande kalenderhandelser, "
                "baserat ENDAST pa datan nedan. Hitta inte pa moten som inte finns dar."
            ),
            context=call["result"],
            raw_text=raw_text,
        )
        return {"ok": True, "error_code": None, "content": verbalized["content"] or "Inga kommande möten hittade."}

    if agent_id == "mail-compose-001":
        draft = await _extract_json_via_model(
            instruction=(
                'Extrahera ett mejlutkast fran texten. Svara ENDAST med JSON: '
                '{"to": "mottagarens e-post om den namns, annars tom strang", '
                '"subject": "kort amnesrad", "body": "utkastets brodtext"}.'
            ),
            raw_text=raw_text,
        )
        args = {
            "to": draft.get("to", "") or None,
            "subject": draft.get("subject", "") or "Utkast från Jarvis",
            "body": draft.get("body", "") or raw_text,
        }
        call = await call_mcp_executor(executor=executor, arguments={k: v for k, v in args.items() if v})
        if not call["ok"]:
            return {"ok": False, "error_code": "TOOL_UNAVAILABLE", "content": call["error"]}
        return {
            "ok": True,
            "error_code": None,
            "content": (
                f"Jag har lagt ett utkast i Drafts (ämne: \"{args['subject']}\"). "
                "Inget skickat — granska och skicka själv i Thunderbird."
            ),
        }

    if agent_id == "calendar-write-001":
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        event = await _extract_json_via_model(
            instruction=(
                f"Dagens datum och tid är {now_iso}. Extrahera ett kalenderevent fran "
                "texten, och räkna ut det faktiska datumet för relativa uttryck som "
                '"imorgon"/"på fredag". Svara ENDAST med JSON: '
                '{"title": "kort titel", "startDate": "ISO 8601 eller tom strang om okant", '
                '"description": "kort beskrivning"}.'
            ),
            raw_text=raw_text,
        )
        if not event.get("startDate"):
            return {
                "ok": False,
                "error_code": "MISSING_STAGE_ARTIFACT",
                "content": "Jag hittade ingen tydlig tid för mötet — säg en konkret tid så bokar jag.",
            }
        args = {
            "title": event.get("title") or "Möte",
            "startDate": event["startDate"],
            "description": event.get("description", ""),
        }
        call = await call_mcp_executor(executor=executor, arguments=args)
        if not call["ok"]:
            return {"ok": False, "error_code": "TOOL_UNAVAILABLE", "content": call["error"]}
        return {
            "ok": True,
            "error_code": None,
            "content": (
                f"Jag har öppnat en granskningsdialog i Thunderbird för \"{args['title']}\" "
                f"({args['startDate']}) — inget bokat förrän du bekräftar den där."
            ),
        }

    return {"ok": False, "error_code": "ROUTE_NOT_FOUND", "content": f"no dispatcher for agent {agent_id!r}"}


async def _dispatch_voice_capture(run_dir: Path, raw_text: str) -> dict:
    cleaned = await call_model_executor(
        executor="gemma4:e2b",
        system_prompt=(
            "Stada bara upp uppenbara transkriptionsfel (upprepade ord, trasiga fragment) "
            "i texten nedan. Parafrasera inte, forkorta inte, hitta inte pa. Returnera bara "
            "den stadade texten, inget annat."
        ),
        user_text=raw_text,
        executor_options={"think": False},
    )
    text_to_file = cleaned["content"] if cleaned["ok"] else raw_text

    date_str = datetime.now().strftime("%Y-%m-%d")
    n = 1
    while (_LJUDANTECKNINGAR_DIR / f"{date_str}-jarvis-{n:03d}.md").exists():
        n += 1
    filename = f"{date_str}-jarvis-{n:03d}.md"

    body = (
        f"# Jarvis-anteckning {date_str}\n\n"
        f"**Källa:** diktering via Jarvis (lokal, gemma4:e2b)\n"
        f"**Status:** obearbetad — lägre kvalitet än /voicenote (Claude Code); "
        f"kör /voicenote manuellt om det här ska struktureras fullt enligt ICM-mallen\n\n"
        f"## Rå anteckning\n\n{text_to_file}\n"
    )

    os.environ["NOUSE_LOCAL_FILE_WRITE_ENABLED"] = "1"
    os.environ["NOUSE_LOCAL_WRITE_ROOTS"] = str(_LJUDANTECKNINGAR_DIR)
    from nouse.mcp_gateway.gateway import write_local_file

    write_result = write_local_file(str(_LJUDANTECKNINGAR_DIR / filename), body, mode="overwrite", create_dirs=False)
    if write_result.get("error"):
        return {"ok": False, "error_code": "TOOL_UNAVAILABLE", "content": str(write_result["error"])}

    return {
        "ok": True,
        "error_code": None,
        "content": f"Antecknat i {filename} (obearbetad — kör /voicenote för full ICM-strukturering).",
    }


# ---------- Stage 04 — dispatch + verbalize only the validated result ----------

async def _stage04_execution_and_generation(
    run_dir: Path, routing_decision: dict, validation_report: dict
) -> dict:
    if not validation_report.get("generation_allowed"):
        final = {
            "ok": False,
            "error_code": validation_report.get("error_code"),
            "content": f"[{validation_report.get('error_code')}] {validation_report.get('reason')}",
        }
        _write_json(run_dir / "04_execution_and_generation" / "final_answer.json", final)
        return final

    executor = str(routing_decision.get("proposed_executor", ""))
    raw_text = routing_decision.get("raw_text", "")
    agent_id = routing_decision.get("agent_id", "")

    if agent_id == "voice-capture-001":
        final = await _dispatch_voice_capture(run_dir, raw_text)
        _write_json(run_dir / "04_execution_and_generation" / "final_answer.json", final)
        return final

    if executor.startswith("relay:"):
        result = open_relay_executor(goal=raw_text, run_dir=run_dir)
        final = {
            "ok": result["ok"],
            "error_code": None,
            "content": result["content"],
            "relay_session_id": result.get("session_id"),
        }
        _write_json(run_dir / "04_execution_and_generation" / "final_answer.json", final)
        return final

    if executor.startswith("mcp:"):
        final = await _dispatch_mcp_agent(run_dir, agent_id, executor, raw_text)
        _write_json(run_dir / "04_execution_and_generation" / "final_answer.json", final)
        return final

    system_prompt = (
        "Du ar Jarvis. Svara kort och naturligt pa svenska, med bara den "
        "grundande kontext som redan finns har - hitta inte pa systemfakta."
    )
    grounding = routing_decision.get("grounding", {})
    context_note = f"\n\nKontext: {json.dumps(grounding, ensure_ascii=False)}" if grounding is not None else ""
    result = await call_model_executor(
        executor=executor,
        system_prompt=system_prompt + context_note,
        user_text=raw_text,
        executor_options=routing_decision.get("proposed_executor_options") or {},
    )
    error_code = None if result["ok"] else "TOOL_UNAVAILABLE"
    final = {
        "ok": result["ok"],
        "error_code": error_code,
        "content": result["content"] or result["error"] or "",
    }
    _write_json(run_dir / "04_execution_and_generation" / "final_answer.json", final)
    return final


# ---------- Stage 05 — split audit logs + write back into Nous memory ----------

def _stage05_audit(
    run_id: str,
    structured_query: dict,
    routing_decision: dict,
    validation_report: dict,
    final: dict,
) -> None:
    llm_log = {
        "run_id": run_id,
        "timestamp": _now_iso(),
        "stage": "01_parse_request+04_execution_and_generation",
        "interface_ok": structured_query.get("interface_ok"),
        "interface_error": structured_query.get("interface_error"),
        "final_ok": final.get("ok"),
        "final_error_code": final.get("error_code"),
    }
    nous_log = {
        "run_id": run_id,
        "timestamp": _now_iso(),
        "classified_skill": routing_decision.get("classified_skill"),
        "agent_id": routing_decision.get("agent_id"),
        "validation_error_code": validation_report.get("error_code"),
        "generation_allowed": validation_report.get("generation_allowed"),
    }
    _write_json(_LOGS_LLM_DIR / f"{run_id}.json", llm_log)
    _write_json(_LOGS_NOUS_DIR / f"{run_id}.json", nous_log)

    outcome_text = str(final.get("content", ""))[:300]
    try:
        kernel_write_episode(
            f"Jarvis run {run_id}: {str(structured_query.get('raw_text', ''))[:120]} -> {outcome_text}",
            source="jarvis_agent_pipeline",
            domain_hint="jarvis",
        )
        kernel_log_outcome(
            action=f"jarvis_route:{routing_decision.get('agent_id') or 'none'}",
            outcome="ok" if final.get("ok") else str(final.get("error_code")),
            run_id=run_id,
        )
    except Exception:
        pass  # audit logging must never crash the pipeline


# ---------- Public entrypoint ----------

async def run_pipeline(request_text: str) -> dict:
    run_id = _new_run_id()
    run_dir = _RUNS_DIR / run_id

    structured_query = await _stage01_parse_request(run_dir, request_text)
    routing_decision = _stage02_engine_query(run_dir, structured_query)
    validation_report = _stage03_structural_validation(run_dir, routing_decision)
    final = await _stage04_execution_and_generation(run_dir, routing_decision, validation_report)
    _stage05_audit(run_id, structured_query, routing_decision, validation_report, final)

    return {
        "run_id": run_id,
        "content": final.get("content", ""),
        "ok": final.get("ok", False),
        "error_code": final.get("error_code"),
        "agent_id": routing_decision.get("agent_id"),
    }
