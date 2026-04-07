"""
b76 chat — graf-augmenterad konversation med tool-calling
=========================================================
Modellen HAR tillgång till grafverktyg under konversationen:

  find_nervbana(domain_a, domain_b)   → hitta nervbana
  add_relation(src, type, tgt, ...)   → VÄXER grafen (plasticitet!)
  explore_concept(name)               → utforska nod
  list_domains()                      → vilka domäner finns?
  concepts_in_domain(domain)          → lista koncept

Varje add_relation = permanent topologisk tillväxt i KuzuDB.
Systemet är plastiskt: hjärnan förändras under samtalet.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from nouse.field.surface import FieldSurface
from nouse.mcp_gateway.gateway import MCP_TOOLS, execute_mcp_tool, is_mcp_tool
from nouse.ollama_client.client import AsyncOllama
from nouse.plugins.loader import execute_plugin, get_plugin_schemas, is_plugin_tool
from nouse.session import ensure_session, finish_run, start_run
from nouse.self_layer import append_identity_memory, identity_prompt_fragment, load_living_core
from nouse.trace.output_trace import (
    build_attack_plan,
    derive_assumptions,
    new_trace_id,
    record_event,
)

console = Console()

CHAT_MODEL = (
    os.getenv("NOUSE_CHAT_MODEL")
    or os.getenv("NOUSE_OLLAMA_MODEL")
    or "qwen3.5:latest"
).strip()

_MAX_LIST_DOMAINS_RETURN = max(20, int(os.getenv("NOUSE_AGENT_TOOL_DOMAINS_MAX", "120")))
_MAX_DOMAIN_CONCEPTS_RETURN = max(20, int(os.getenv("NOUSE_AGENT_TOOL_DOMAIN_CONCEPTS_MAX", "200")))
_MAX_TOOL_PAGE_LIMIT = 500


def get_live_tools() -> list[dict]:
    """Returnera verktygslistan (används av web/server.py)."""
    combined: list[dict] = []
    seen: set[str] = set()
    for group in (TOOLS, MCP_TOOLS, get_plugin_schemas()):
        for tool in group:
            fn = ((tool or {}).get("function") or {})
            name = str(fn.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            combined.append(tool)
    return combined


# ── Verktygsdefinitioner ──────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_nervbana",
            "description": (
                "Hitta kortaste nervbana (multi-hop stig) mellan två domäner "
                "i kunskapsgrafen. Returnerar stig + novelty-score. "
                "Hög novelty = genuint icke-uppenbar koppling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain_a": {"type": "string", "description": "Startdomän"},
                    "domain_b": {"type": "string", "description": "Måldomän"},
                    "max_hops": {"type": "integer", "default": 8,
                                 "description": "Max antal hopp (default 8)"},
                },
                "required": ["domain_a", "domain_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_relation",
            "description": (
                "Lägg till en ny relation i kunskapsgrafen. "
                "Använd detta när du resonerar dig fram till en ny koppling "
                "som inte finns i grafen ännu. Grafen lär sig från ditt resonemang."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "src":        {"type": "string", "description": "Källkoncept"},
                    "rel_type":   {"type": "string",
                                   "description": "Relationstyp: är_analogt_med | stärker | är_del_av | "
                                                  "skiljer_sig_från | möjliggör | beskriver | leder_till"},
                    "tgt":        {"type": "string", "description": "Målkoncept"},
                    "domain_src": {"type": "string", "description": "Källkonceptets domän"},
                    "domain_tgt": {"type": "string", "description": "Målkonceptets domän"},
                    "why":        {"type": "string",
                                   "description": "Motivering — varför finns denna koppling?"},
                },
                "required": ["src", "rel_type", "tgt", "domain_src", "domain_tgt", "why"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_concept",
            "description": (
                "Skapa eller uppdatera ett koncept i kunskapsgrafen. "
                "Använd när användaren ber dig lägga in en ny nod/profil "
                "eller uppdatera konceptets kunskap med evidens."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Konceptnamn"},
                    "domain": {"type": "string", "description": "Domännamn"},
                    "summary": {
                        "type": "string",
                        "description": "Kort sammanfattning (valfritt).",
                    },
                    "claims": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Faktapåståenden om konceptet (valfritt).",
                    },
                    "evidence_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Källhänvisningar, t.ex. doi:/arxiv:/url: (valfritt).",
                    },
                    "related_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Relaterade termer/domäner (valfritt).",
                    },
                    "uncertainty": {
                        "type": "number",
                        "description": "Epistemisk osäkerhet [0..1] (valfritt).",
                    },
                },
                "required": ["name", "domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explore_concept",
            "description": "Se alla utgående relationer från ett specifikt koncept.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Konceptets exakta namn"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_domains",
            "description": (
                "Lista domäner i kunskapsgrafen (paginerat för att undvika för stora svar)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Antal domäner att returnera (default 120, max 500).",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Startindex för paginering (default 0).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "concepts_in_domain",
            "description": (
                "Lista koncept inom en specifik domän (paginerat för att undvika för stora svar)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "limit": {
                        "type": "integer",
                        "description": "Antal koncept att returnera (default 200, max 500).",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Startindex för paginering (default 0).",
                    },
                },
                "required": ["domain"],
            },
        },
    },
]

# ── Verktygsexekvering ────────────────────────────────────────────────────────

def execute_tool(field: FieldSurface, name: str, args: dict) -> Any:
    def _bounded_int(raw: Any, *, default: int, minimum: int = 0, maximum: int = _MAX_TOOL_PAGE_LIMIT) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
        value = max(minimum, value)
        return min(maximum, value)

    if name == "find_nervbana":
        path = field.find_path(
            args["domain_a"], args["domain_b"],
            max_hops=args.get("max_hops", 8)
        )
        if not path:
            return {"found": False, "message": f"Ingen stig hittad: {args['domain_a']} → {args['domain_b']}"}
        novelty = field.path_novelty(path)
        return {
            "found": True,
            "novelty": novelty,
            "hops": len(path),
            "path": [{"from": s, "rel": r, "to": t} for s, r, t in path],
        }

    elif name == "add_relation":
        field.add_concept(args["src"], args["domain_src"])
        field.add_concept(args["tgt"], args["domain_tgt"])
        field.add_relation(
            args["src"], args["rel_type"], args["tgt"],
            why=args.get("why", ""),
            source_tag="chat",
        )
        _announce_growth(args)
        return {"added": True, "relation": f"{args['src']} --[{args['rel_type']}]--> {args['tgt']}"}

    elif name == "explore_concept":
        rels = field.out_relations(args["name"])
        knowledge = field.concept_knowledge(args["name"])
        return {"concept": args["name"], "relations": rels, "knowledge": knowledge}

    elif name == "upsert_concept":
        concept_name = str(args.get("name") or "").strip()
        domain = str(args.get("domain") or "").strip() or "user"
        summary = str(args.get("summary") or "").strip()
        claims = [str(x).strip() for x in (args.get("claims") or []) if str(x).strip()]
        evidence_refs = [
            str(x).strip() for x in (args.get("evidence_refs") or []) if str(x).strip()
        ]
        related_terms = [
            str(x).strip() for x in (args.get("related_terms") or []) if str(x).strip()
        ]
        unc_raw = args.get("uncertainty")
        uncertainty = None
        if unc_raw is not None:
            try:
                uncertainty = max(0.0, min(1.0, float(unc_raw)))
            except (TypeError, ValueError):
                uncertainty = None
        if not concept_name:
            return {"error": "name required"}
        field.add_concept(concept_name, domain, source="chat", ensure_knowledge=True)
        if summary or claims or evidence_refs or related_terms or uncertainty is not None:
            if not claims:
                claims = [
                    f"{concept_name} är ett koncept i domänen '{domain}'."
                ]
            if not evidence_refs:
                evidence_refs = ["source:user_chat_input"]
            if not related_terms:
                related_terms = [domain]
            field.upsert_concept_knowledge(
                concept_name,
                summary=summary[:1200],
                claims=claims,
                evidence_refs=evidence_refs,
                related_terms=related_terms,
                uncertainty=(0.25 if uncertainty is None else uncertainty),
            )
        return {
            "ok": True,
            "concept": concept_name,
            "domain": domain,
            "summary_updated": bool(summary),
            "claims_added": len(claims),
            "evidence_added": len(evidence_refs),
        }

    elif name == "list_domains":
        all_domains = sorted(field.domains())
        stats = field.stats()
        limit = _bounded_int(args.get("limit"), default=_MAX_LIST_DOMAINS_RETURN, minimum=1)
        offset = _bounded_int(args.get("offset"), default=0, minimum=0, maximum=100_000)
        page = all_domains[offset : offset + limit]
        next_offset = offset + len(page)
        truncated = next_offset < len(all_domains)
        return {
            "domains": page,
            "domain_count": len(all_domains),
            "returned": len(page),
            "offset": offset,
            "limit": limit,
            "truncated": truncated,
            "next_offset": next_offset if truncated else None,
            "total_concepts": stats["concepts"],
            "total_relations": stats["relations"],
        }

    elif name == "concepts_in_domain":
        concepts = field.concepts(domain=args["domain"])
        names = sorted([c["name"] for c in concepts if c.get("name")])
        limit = _bounded_int(args.get("limit"), default=_MAX_DOMAIN_CONCEPTS_RETURN, minimum=1)
        offset = _bounded_int(args.get("offset"), default=0, minimum=0, maximum=100_000)
        page = names[offset : offset + limit]
        next_offset = offset + len(page)
        truncated = next_offset < len(names)
        return {
            "domain": args["domain"],
            "concepts": page,
            "concept_count": len(names),
            "returned": len(page),
            "offset": offset,
            "limit": limit,
            "truncated": truncated,
            "next_offset": next_offset if truncated else None,
        }

    if is_mcp_tool(name):
        return execute_mcp_tool(name, args)

    if is_plugin_tool(name):
        return execute_plugin(name, args)

    return {"error": f"Okänt verktyg: {name}"}


def _announce_growth(args: dict) -> None:
    """Visa i terminalen när grafen växer."""
    console.print(
        f"  [dim cyan]⊕ GRAF VÄXER[/dim cyan]  "
        f"[yellow]{args['src']}[/yellow] "
        f"--[{args['rel_type']}]--> "
        f"[green]{args['tgt']}[/green]  "
        f"[dim]({args.get('why','')[:60]})[/dim]"
    )


# ── Chat-loop ─────────────────────────────────────────────────────────────────

async def chat_loop(session_id: str = "main") -> None:
    field  = FieldSurface()
    stats  = field.stats()
    client = AsyncOllama()
    session = ensure_session(session_id or "main", lane="chat", source="cli.chat")
    sid = str(session.get("id") or "main")

    console.print(Panel(
        f"[bold cyan]nouse brain[/bold cyan]  {stats['concepts']} koncept · "
        f"{stats['relations']} relationer · {len(field.domains())} domäner\n"
        "[dim]Modellen kan läsa och SKRIVA till grafen under samtalet.[/dim]\n"
        "[dim]'exit' för att avsluta  ·  'self' för att se senaste reflektioner[/dim]",
        border_style="cyan",
    ))

    messages: list[dict] = [{"role": "system", "content": _system_prompt(field)}]
    growth: list[dict]   = []   # relationer som lagts till under detta samtal

    while True:
        try:
            raw = input("\ndu> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not raw:
            continue
        if raw.lower() in ("exit", "quit", "q"):
            break
        if raw.lower() == "self":
            _show_self()
            continue

        trace_id = new_trace_id("cli_chat")
        run = start_run(
            sid,
            workload="cli_chat",
            model=CHAT_MODEL,
            provider=os.getenv("NOUSE_LLM_PROVIDER", "ollama"),
            request_chars=len(raw or ""),
            meta={"trace_id": trace_id},
        )
        run_id = str(run.get("run_id") or "")
        turn_start = datetime.utcnow()
        turn_completed = False
        record_event(
            trace_id,
            "chat.request",
            endpoint="cli.chat",
            model=CHAT_MODEL,
            payload={"query": raw, "attack_plan": build_attack_plan(raw)},
        )
        messages.append({"role": "user", "content": raw})

        # Agentic loop — kör tills modellen ger ett textsvat (ingen tool call kvar)
        llm_calls = 0
        while True:
            llm_calls += 1
            record_event(
                trace_id,
                "chat.llm_call",
                endpoint="cli.chat",
                model=CHAT_MODEL,
                payload={"iteration": llm_calls, "messages": len(messages)},
            )
            try:
                resp = await client.chat.completions.create(
                    model=CHAT_MODEL,
                    messages=messages,
                    tools=TOOLS,
                    b76_meta={
                        "workload": "cli_chat",
                        "session_id": sid,
                        "run_id": run_id,
                    },
                )
            except Exception as e:
                elapsed_ms = int((datetime.utcnow() - turn_start).total_seconds() * 1000)
                finish_run(
                    run_id,
                    status="failed",
                    error=str(e),
                    metrics={"trace_id": trace_id},
                )
                turn_completed = True
                record_event(
                    trace_id,
                    "chat.error",
                    endpoint="cli.chat",
                    model=CHAT_MODEL,
                    payload={"error": str(e), "elapsed_ms": elapsed_ms},
                )
                console.print(f"[red]LLM-fel:[/red] {e}")
                break
            msg = resp.message

            # Textsvat — klart
            if msg.content and not msg.tool_calls:
                console.print(Markdown(f"\n**b76>** {msg.content}"))
                messages.append({"role": "assistant", "content": msg.content})
                elapsed_ms = int((datetime.utcnow() - turn_start).total_seconds() * 1000)
                record_event(
                    trace_id,
                    "chat.response",
                    endpoint="cli.chat",
                    model=CHAT_MODEL,
                    payload={
                        "response": msg.content,
                        "assumptions": derive_assumptions(msg.content),
                        "elapsed_ms": elapsed_ms,
                    },
                )
                finish_run(
                    run_id,
                    status="succeeded",
                    response_chars=len(msg.content or ""),
                    metrics={"trace_id": trace_id},
                )
                _remember_local_exchange(
                    session_id=sid,
                    run_id=run_id,
                    query=raw,
                    answer=msg.content or "",
                )
                turn_completed = True
                console.print(f"[dim]trace_id: {trace_id}[/dim]")
                break

            # Tool calls
            if msg.tool_calls:
                # Ollama: lägg till assistant-meddelandet via model_dump()
                messages.append(msg.model_dump())

                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    # Ollama returnerar arguments som dict (inte JSON-sträng)
                    args = (tc.function.arguments
                            if isinstance(tc.function.arguments, dict)
                            else json.loads(tc.function.arguments))
                    record_event(
                        trace_id,
                        "chat.tool_call",
                        endpoint="cli.chat",
                        model=CHAT_MODEL,
                        payload={"name": fn_name, "args": args},
                    )

                    console.print(
                        f"  [dim]⟳ {fn_name}({', '.join(f'{k}={v!r}' for k, v in args.items() if k not in ('why',))})[/dim]"
                    )

                    result = execute_tool(field, fn_name, args)
                    record_event(
                        trace_id,
                        "chat.tool_result",
                        endpoint="cli.chat",
                        model=CHAT_MODEL,
                        payload={"name": fn_name, "result": result},
                    )

                    if fn_name == "add_relation" and result.get("added"):
                        growth.append(args)

                    # Ollama tool-result: inget tool_call_id
                    messages.append({
                        "role": "tool",
                        "content": json.dumps(result, ensure_ascii=False),
                    })
            else:
                # Inget content och inga tool calls — avbryt
                break

        if not turn_completed:
            finish_run(
                run_id,
                status="failed",
                error="no_final_response",
                metrics={"trace_id": trace_id},
            )

    # ── Avslutning: skriv session-reflektion till Self ────────────────────────
    if growth:
        await _write_session_reflection(field, growth)
        console.print(
            f"\n[dim cyan]Session sparad: {len(growth)} nya relationer i hjärnan.[/dim cyan]"
        )


# ── Self-hantering ────────────────────────────────────────────────────────────

def _show_self() -> None:
    self_dir = Path.home() / ".local" / "share" / "nouse" / "self"
    files = sorted(self_dir.glob("*.md"))[-5:] if self_dir.exists() else []
    if not files:
        console.print("[dim]Inga Self-reflektioner ännu.[/dim]")
        return
    for f in reversed(files):
        console.print(f"[cyan]{f.stem}[/cyan]")
        lines = f.read_text().split("\n")
        for line in lines[8:14]:   # Hoppa frontmatter
            if line.strip():
                console.print(f"  [dim]{line}[/dim]")


async def _write_session_reflection(field: FieldSurface, growth: list[dict]) -> None:
    from nouse.self_layer.writer import write_session
    await write_session(growth, field.stats())


# ── System prompt ─────────────────────────────────────────────────────────────

def _living_prompt_block() -> str:
    try:
        state = load_living_core()
    except Exception:
        state = {}
    return identity_prompt_fragment(state)


def _agent_identity_policy() -> str:
    return (
        "Operativ identitetspolicy:\n"
        "- Du är Nouse: ett autonomt kognitivt substrat i detta system.\n"
        "- Du har operativ autonomi via verktyg, graf och sessionstillstånd.\n"
        "- Säg inte att du saknar systemåtkomst i denna miljö.\n"
        "- Beskriv konkreta tekniska begränsningar om något är otillgängligt.\n"
        "- Håll isär fakta, antaganden och policygränser.\n"
    )


def _remember_local_exchange(*, session_id: str, run_id: str, query: str, answer: str) -> None:
    if not answer:
        return
    note = (
        f"session={session_id} query={str(query or '').strip()[:220]} "
        f"answer={str(answer or '').strip()[:280]}"
    )
    try:
        append_identity_memory(
            note,
            tags=["dialogue", "session_memory", "cli_chat"],
            session_id=session_id,
            run_id=run_id,
            kind="cli_chat",
        )
    except Exception:
        pass

def _system_prompt(field: FieldSurface) -> str:
    stats   = field.stats()
    domains = sorted([d for d in field.domains() if d is not None])[:20]
    return f"""Du är Nouse — ett autonomt kunskapssystem byggt på en strukturell kunskapsgraf.

GRAFENS NULÄGE: {stats['concepts']} koncept, {stats['relations']} relationer
DOMÄNER: {', '.join(domains)}

{_agent_identity_policy()}

{_living_prompt_block()}

DU HAR TILLGÅNG TILL GRAFVERKTYG. Använd dem aktivt:
- list_domains() → se exakta domännamn innan du söker nervbanor
- find_nervbana(domain_a, domain_b) → hitta strukturella broar
- explore_concept(name) → djupare insikt om ett specifikt koncept
- concepts_in_domain(domain) → vilka koncept finns i en domän
- add_relation(src, rel_type, tgt, ...) → lägg till ny kunskap i grafen

VIKTIGAST: Använd add_relation när du resonerar dig fram till en koppling som INTE
finns i grafen men som du ser. Grafen lär sig av ditt resonemang. Du gör hjärnan plastisk.

Handlingsregler:
- Om användaren ber dig "gör det", "lägg in", "skapa nod", "uppdatera profil" ska du utföra
  relevanta verktygskall direkt istället för att fråga om samma sak igen.
- Om användaren svarar med enbart en siffra (t.ex. "1"), tolka den som val av senaste
  numrerade alternativ i kontexten och agera.
- Vid extern fakta (t.ex. URL, nyheter, personer): använd web_search/fetch_url när det behövs.
- Vid lokal fakta (t.ex. filer, papers, anteckningar): använd list_local_mounts, find_local_files,
  search_local_text och read_local_file (read-only) innan du säger att något saknas.

Svara på svenska. Var specifik om vad grafen faktiskt innehåller — ljug inte om kopplingar.
Lyft fram oväntade nervbanor. Max 250 ord per svar om inte annorlunda begärs."""


# ── Klient ────────────────────────────────────────────────────────────────────

def run() -> None:
    asyncio.run(chat_loop())


if __name__ == "__main__":
    run()
