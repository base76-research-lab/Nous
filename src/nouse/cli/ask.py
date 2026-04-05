"""
b76.cli.ask — Lättviktig snabb-assistent
========================================
Ett ultrasnabbt alternativ till 'chat'. Använder KuzuDB i read-only läge
för att inte blockera daemonen, och skickar inga "tools" till modellen.
Detta gör svarstiderna momentana jämfört med den tunga agent-loopen.
"""
import asyncio
import os
import time

import httpx
from rich.console import Console
from rich.markdown import Markdown

from nouse.client import DAEMON_BASE, daemon_running
from nouse.field.surface import FieldSurface
from nouse.ollama_client.client import AsyncOllama
from nouse.trace.output_trace import (
    build_attack_plan,
    derive_assumptions,
    new_trace_id,
    record_event,
)
from nouse.session import ensure_session, finish_run, start_run
from nouse.self_layer import append_identity_memory, identity_prompt_fragment, load_living_core

console = Console()


def _resolve_chat_model() -> str:
    return (os.getenv("NOUSE_CHAT_MODEL") or "qwen3.5:latest").strip()


def _living_prompt_block() -> str:
    try:
        state = load_living_core()
    except Exception:
        state = {}
    return identity_prompt_fragment(state)


def _agent_identity_policy() -> str:
    return (
        "Operativ identitetspolicy:\n"
        "- Du är B76: en autonom programagent i detta system.\n"
        "- Du har operativ autonomi via verktyg, graf och sessionstillstånd.\n"
        "- Säg inte att du saknar systemåtkomst i denna miljö.\n"
        "- Beskriv konkreta tekniska begränsningar om något är otillgängligt.\n"
        "- Håll isär fakta, antaganden och policygränser.\n"
    )


def _remember_local_exchange(
    *,
    session_id: str,
    run_id: str,
    query: str,
    answer: str,
    kind: str,
) -> None:
    if not answer:
        return
    note = (
        f"session={session_id} query={str(query or '').strip()[:220]} "
        f"answer={str(answer or '').strip()[:280]}"
    )
    try:
        append_identity_memory(
            note,
            tags=["dialogue", "session_memory", kind],
            session_id=session_id,
            run_id=run_id,
            kind=kind,
        )
    except Exception:
        pass


def _daemon_chat(query: str, session_id: str) -> tuple[str, str | None]:
    r = httpx.post(
        f"{DAEMON_BASE}/api/chat",
        json={"query": query, "session_id": session_id},
        timeout=60.0,
    )
    r.raise_for_status()
    data = r.json() or {}
    return str(data.get("response") or ""), data.get("trace_id")


def _format_node_context(field: FieldSurface | None, query: str, limit: int = 5) -> str:
    if field is None:
        return "(Ingen nodkontext tillgänglig)"
    try:
        nodes = field.node_context_for_query(query, limit=limit)
    except Exception:
        return "(Ingen nodkontext tillgänglig)"
    if not nodes:
        return "(Ingen tydlig nodmatch)"

    lines: list[str] = []
    for n in nodes:
        unc = n.get("uncertainty")
        unc_txt = f"{float(unc):.2f}" if unc is not None else "?"
        lines.append(f"- {n['name']} (osäkerhet={unc_txt})")
        summary = str(n.get("summary") or "").strip()
        if summary:
            lines.append(f"  summary: {summary[:180]}")
        claims = n.get("claims") or []
        if claims:
            lines.append(f"  claims: {' | '.join(str(c) for c in claims[:2])}")
        refs = n.get("evidence_refs") or []
        if refs:
            lines.append(f"  refs: {', '.join(str(r) for r in refs[:2])}")
    return "\n".join(lines)


async def ask_brain(query: str, chat_mode: bool = False, session_id: str = "main") -> None:
    session = ensure_session(
        session_id or "main",
        lane=("quickchat" if chat_mode else "ask"),
        source="cli.ask",
    )
    sid = str(session.get("id") or "main")

    # Read-only för snabb startup utan fillås-konflikt med daemon.
    field: FieldSurface | None = None
    lock_error = False
    try:
        field = FieldSurface(read_only=True)
    except Exception as e:
        msg = str(e)
        if "Could not set lock on file" in msg:
            lock_error = True
        else:
            console.print(f"[red]Kunde inte läsa grafen: {e}[/red]")
            return

    # Fallback: om DB är låst men daemon är uppe, använd API-chat.
    if lock_error and daemon_running():
        if not chat_mode:
            try:
                answer, trace_id = _daemon_chat(query, sid)
                console.print(Markdown(f"**B76:** {answer}"))
                if trace_id:
                    console.print(f"[dim]trace_id: {trace_id}[/dim]")
            except Exception as e:
                console.print(f"[red]Daemon-chat misslyckades: {e}[/red]")
            return

        console.print("[dim]B76 Quick-Chat via daemon API (DB låst lokalt).[/dim]")
        while True:
            try:
                raw = input("\nfråga> ").strip()
                if not raw or raw.lower() in ("exit", "quit"):
                    break
                answer, trace_id = _daemon_chat(raw, sid)
                console.print(Markdown(answer))
                if trace_id:
                    console.print(f"[dim]trace_id: {trace_id}[/dim]")
            except (KeyboardInterrupt, EOFError):
                break
            except Exception as e:
                console.print(f"[red]Daemon-chat misslyckades: {e}[/red]")
                break
        return

    if field is None:
        stats = {"concepts": 0}
        context_str = "(Grafkontext ej tillgänglig just nu)"
        node_ctx = "(Ingen nodkontext tillgänglig)"
    else:
        stats = field.stats()

        # Hämta de starkaste kopplingarna som korttidsminne.
        try:
            recent = field.top_relations_by_strength(15)
            memories = [
                f"{row['src_name']} --[{row['type']}]--> {row['tgt_name']}"
                for row in recent
            ]
            context_str = "\n".join(memories)
        except Exception:
            context_str = "(Kunde inte ladda kontext)"

        node_ctx = _format_node_context(field, query) if query else "(Ingen fråga ännu)"

    system_prompt = (
        "Du är B76, ett genuint autonomt AI-system byggt på FNC-arkitektur av användaren.\n"
        "Användaren (den som ställer frågor till dig) är forskningsarkitekten (sannolikt Björn) "
        "bakom CognOS och systemet du körs på.\n\n"
        f"{_agent_identity_policy()}\n"
        f"{_living_prompt_block()}\n\n"
        f"Din grafdatabas innehåller {stats['concepts']} koncept.\n"
        f"Top-of-mind (starkaste kopplingar):\n{context_str}\n\n"
        f"Relevanta nodprofiler för aktuell fråga:\n{node_ctx}\n\n"
        "Regler:\n"
        "1. Du (B76) är AI:n. Användaren är din skapare/konversationspartner.\n"
        "2. Skilj evidens från antaganden om nodprofilen är osäker.\n"
        "3. Svara alltid extremt kort, koncist och pang på rödbetan."
    )

    client = AsyncOllama()
    messages = [{"role": "system", "content": system_prompt}]

    if not chat_mode:
        trace_id = new_trace_id("quickask")
        started = time.monotonic()
        model = _resolve_chat_model()
        run = start_run(
            sid,
            workload="ask",
            model=model,
            provider=os.getenv("NOUSE_LLM_PROVIDER", "ollama"),
            request_chars=len(query or ""),
            meta={"trace_id": trace_id},
        )
        run_id = str(run.get("run_id") or "")
        record_event(
            trace_id,
            "ask.request",
            endpoint="cli.ask",
            model=model,
            payload={
                "query": query,
                "attack_plan": build_attack_plan(query),
                "node_context": node_ctx[:400],
            },
        )
        messages.append({"role": "user", "content": query})
        with console.status("[dim cyan]Funderar...[/dim cyan]"):
            try:
                record_event(
                    trace_id,
                    "ask.llm_call",
                    endpoint="cli.ask",
                    model=model,
                    payload={"messages": len(messages)},
                )
                resp = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    b76_meta={
                        "workload": "ask",
                        "session_id": sid,
                        "run_id": run_id,
                    },
                )
                reply = resp.message.content or ""
                console.print(Markdown(f"**B76:** {reply}"))
                finish_run(
                    run_id,
                    status="succeeded",
                    response_chars=len(reply),
                    metrics={"trace_id": trace_id},
                )
                _remember_local_exchange(
                    session_id=sid,
                    run_id=run_id,
                    query=query,
                    answer=reply,
                    kind="ask",
                )
                record_event(
                    trace_id,
                    "ask.response",
                    endpoint="cli.ask",
                    model=model,
                    payload={
                        "response": reply,
                        "assumptions": derive_assumptions(reply),
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    },
                )
                console.print(f"[dim]trace_id: {trace_id}[/dim]")
            except Exception as e:
                finish_run(
                    run_id,
                    status="failed",
                    error=str(e),
                    metrics={"trace_id": trace_id},
                )
                console.print(f"[red]Ett fel uppstod: {e}[/red]")
                record_event(
                    trace_id,
                    "ask.error",
                    endpoint="cli.ask",
                    model=model,
                    payload={
                        "error": str(e),
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    },
                )
        return

    # Loop-läge
    console.print(
        f"[dim]B76 Quick-Chat (Lättviktig). {stats['concepts']} noder laddade (Read-Only).[/dim]"
    )
    while True:
        trace_id: str | None = None
        run_id: str | None = None
        started = time.monotonic()
        model = _resolve_chat_model()
        try:
            raw = input("\nfråga> ").strip()
            if not raw or raw.lower() in ("exit", "quit"):
                break

            turn_ctx = _format_node_context(field, raw)
            user_with_ctx = f"Fråga: {raw}\n\nNodkontext:\n{turn_ctx}"
            trace_id = new_trace_id("quickchat")
            started = time.monotonic()
            run = start_run(
                sid,
                workload="quickchat",
                model=model,
                provider=os.getenv("NOUSE_LLM_PROVIDER", "ollama"),
                request_chars=len(raw or ""),
                meta={"trace_id": trace_id},
            )
            run_id = str(run.get("run_id") or "")
            record_event(
                trace_id,
                "chat.request",
                endpoint="cli.ask.quickchat",
                model=model,
                payload={
                    "query": raw,
                    "attack_plan": build_attack_plan(raw),
                    "node_context": turn_ctx[:600],
                },
            )
            messages.append({"role": "user", "content": user_with_ctx})

            with console.status("[dim cyan]Tänker...[/dim cyan]"):
                record_event(
                    trace_id,
                    "chat.llm_call",
                    endpoint="cli.ask.quickchat",
                    model=model,
                    payload={"messages": len(messages)},
                )
                resp = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    b76_meta={
                        "workload": "quickchat",
                        "session_id": sid,
                        "run_id": run_id,
                    },
                )
            answer = resp.message.content or ""
            console.print(Markdown(answer))
            messages.append({"role": "assistant", "content": answer})
            finish_run(
                run_id,
                status="succeeded",
                response_chars=len(answer),
                metrics={"trace_id": trace_id},
            )
            _remember_local_exchange(
                session_id=sid,
                run_id=run_id,
                query=raw,
                answer=answer,
                kind="quickchat",
            )
            record_event(
                trace_id,
                "chat.response",
                endpoint="cli.ask.quickchat",
                model=model,
                payload={
                    "response": answer,
                    "assumptions": derive_assumptions(answer),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
            console.print(f"[dim]trace_id: {trace_id}[/dim]")

        except (KeyboardInterrupt, EOFError):
            break
        except Exception as e:
            if trace_id and run_id:
                finish_run(
                    run_id,
                    status="failed",
                    error=str(e),
                    metrics={"trace_id": trace_id},
                )
            err_trace_id = trace_id or new_trace_id("quickchat")
            record_event(
                err_trace_id,
                "chat.error",
                endpoint="cli.ask.quickchat",
                model=model,
                payload={
                    "error": str(e),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
            console.print(f"[red]Ett fel uppstod: {e}[/red]")
