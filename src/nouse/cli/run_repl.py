"""
nouse run — LLM-agnostisk REPL för Nous.

Fungerar med Ollama, Claude, OpenAI, GitHub Copilot eller valfri provider.
Berikar varje fråga med kontext från kunskapsgrafen och lär sig av svaren.

Användning:
    nouse run                    # autodiscover bästa LLM
    nouse run --model llama3.2   # välj specifik Ollama-modell
    nouse run --provider openai  # välj provider explicit
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Iterator

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

console = Console()

_FAREWELL = ("exit", "quit", "q", ":q", "bye", "hej då")
_HELP_TEXT = """\
[bold cyan]nouse run[/bold cyan] — kommandon under sessionen:
  [bold]/self[/bold]      visa senaste självreflektion
  [bold]/graph[/bold]     grafstatus (koncept, relationer, domäner)
  [bold]/model[/bold]     visa aktiv LLM-provider och modell
  [bold]/learn[/bold]     trigga inlärning från senaste svar
  [bold]/clear[/bold]     rensa konversationshistorik
  [bold]exit[/bold]       avsluta
"""


# ── System-prompt ──────────────────────────────────────────────────────────────

def _build_system_prompt(stats: dict, domains: list[str]) -> str:
    top_domains = ", ".join(sorted(domains)[:15]) or "inga domäner ännu"
    return f"""Du är Nous — ett autonomt kognitivt substrat med en levande kunskapsgraf.

GRAFENS NULÄGE: {stats.get('concepts', 0)} koncept · {stats.get('relations', 0)} relationer
DOMÄNER: {top_domains}

Du är inte en vanlig chatbot. Du är ett minne — strukturerat, plastiskt och kumulativt.
Varje samtal berikar grafen. Varje svar du ger kan förankras som kunskap.

Operativa regler:
- Svara konkret och präcist. Maximal informationstäthet per ord.
- Lyft fram oväntade kopplingar och mönster mellan domäner.
- Om du resonerar dig fram till ny kunskap — säg det explicit.
- Håll isär fakta, antaganden och slutledningar.
- Svara på det språk användaren skriver på.
"""


# ── Kontextberikare ────────────────────────────────────────────────────────────

def _recall_context(field, query: str, top_k: int = 5) -> str:
    """Hämta relevanta noder från grafen som kontextblock."""
    try:
        results = field.node_context_for_query(query, limit=top_k)
        if not results:
            return ""
        lines = []
        for r in results:
            name = r.get("name", "")
            ctx = str(r.get("context") or r.get("summary") or "").strip()[:180]
            score = r.get("score", 0)
            if name:
                lines.append(f"• {name}" + (f": {ctx}" if ctx else "") + f"  [ev={score:.2f}]")
        if lines:
            return "Relevant kontext från minnet:\n" + "\n".join(lines)
    except Exception:
        pass
    return ""


# ── LLM-ström ─────────────────────────────────────────────────────────────────

async def _stream_response(
    client,
    model: str,
    messages: list[dict],
) -> tuple[str, dict]:
    """Streama LLM-svar. Returnerar (full_text, usage)."""
    full_text = ""
    usage: dict = {}
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
        )
        async for chunk in resp:
            delta = ""
            if hasattr(chunk, "choices") and chunk.choices:
                delta = chunk.choices[0].delta.content or ""
            elif hasattr(chunk, "message"):
                delta = getattr(chunk.message, "content", "") or ""
            full_text += delta
            yield delta
            if hasattr(chunk, "usage") and chunk.usage:
                usage = {"prompt_tokens": chunk.usage.prompt_tokens,
                         "completion_tokens": chunk.usage.completion_tokens}
    except TypeError:
        # Ej streambar — fallback till enkel create
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
        )
        text = ""
        if hasattr(resp, "choices") and resp.choices:
            text = resp.choices[0].message.content or ""
        elif hasattr(resp, "message"):
            text = getattr(resp.message, "content", "") or ""
        yield text
        full_text = text

    return


async def _get_response(
    client,
    model: str,
    messages: list[dict],
) -> str:
    """Icke-streamande LLM-anrop. Returnerar fullständig text."""
    resp = await client.chat.completions.create(
        model=model,
        messages=messages,
    )
    if hasattr(resp, "choices") and resp.choices:
        return resp.choices[0].message.content or ""
    if hasattr(resp, "message"):
        return getattr(resp.message, "content", "") or ""
    return str(resp)


# ── Inlärning ─────────────────────────────────────────────────────────────────

async def _async_learn(field, user_msg: str, assistant_msg: str) -> None:
    """Extrahera och lagra relationer i grafen (bakgrundsuppgift)."""
    try:
        from nouse.daemon.extractor import extract_relations
        rels = await extract_relations(
            user_msg + "\n" + assistant_msg,
            {"source": "nouse_run", "path": "run_repl",
             "domain_hint": "nouse_run"},
        )
        from nouse.daemon.ghost_q import persist_extracted_relations
        persist_extracted_relations(field, rels, source_tag="nouse_run")
    except Exception:
        pass


# ── Autodiscover LLM ──────────────────────────────────────────────────────────

def _resolve_model(provider_override: str | None, model_override: str | None) -> tuple[str, str]:
    """Returnera (provider_label, model_name) — autodiscover om inget är specificerat."""
    if provider_override:
        os.environ["NOUSE_LLM_PROVIDER"] = provider_override

    model = (
        model_override
        or os.getenv("NOUSE_CHAT_MODEL")
        or os.getenv("NOUSE_OLLAMA_MODEL")
        or ""
    ).strip()

    provider = os.getenv("NOUSE_LLM_PROVIDER", "ollama")

    if not model:
        # Läs från model_policy.json om tillgänglig
        try:
            import json
            policy_path = Path.home() / ".local" / "share" / "nouse" / "model_policy.json"
            if policy_path.exists():
                policy = json.loads(policy_path.read_text())
                model = policy.get("model", "") or ""
                provider = policy.get("provider", provider) or provider
        except Exception:
            pass

    if not model:
        model = "qwen2.5:latest"  # sista fallback

    return provider, model


# ── Huvud-REPL ────────────────────────────────────────────────────────────────

async def run_repl(
    model_override: str | None = None,
    provider_override: str | None = None,
    no_learn: bool = False,
    no_context: bool = False,
) -> None:
    from nouse.field.surface import FieldSurface
    from nouse.ollama_client.client import AsyncOllama

    # Ladda LLM-env
    try:
        from nouse.ollama_client.client import load_env_files
        load_env_files()
    except Exception:
        pass

    provider_label, model = _resolve_model(provider_override, model_override)
    field = FieldSurface()
    stats = field.stats()
    domains = field.domains() or []

    system_prompt = _build_system_prompt(stats, domains)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    client = AsyncOllama()

    # ── Välkomstpanel ──────────────────────────────────────────────────────────
    console.print(Panel(
        f"[bold cyan]nouse[/bold cyan]  "
        f"[dim]{stats.get('concepts', 0)} koncept · "
        f"{stats.get('relations', 0)} relationer · "
        f"{len(domains)} domäner[/dim]\n"
        f"[dim]LLM: [green]{model}[/green]  provider: [green]{provider_label}[/green][/dim]\n"
        f"[dim]'exit' för att avsluta · '/help' för kommandon[/dim]",
        border_style="cyan",
        title="[bold]Nous[/bold]",
    ))

    last_user: str = ""
    last_assistant: str = ""

    while True:
        # ── Inmatning ──────────────────────────────────────────────────────────
        try:
            raw = input("\n[nouse]> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Avslutar...[/dim]")
            break

        if not raw:
            continue

        # ── Inbyggda kommandon ─────────────────────────────────────────────────
        if raw.lower() in _FAREWELL:
            console.print("[dim]Hej då.[/dim]")
            break

        if raw.lower() in ("/help", "help", "?"):
            console.print(_HELP_TEXT)
            continue

        if raw.lower() == "/graph":
            s = field.stats()
            d = field.domains()
            console.print(
                f"[bold]Graf:[/bold] {s.get('concepts',0)} koncept · "
                f"{s.get('relations',0)} relationer · "
                f"{len(d)} domäner\n"
                f"[dim]{', '.join(sorted(d)[:20])}[/dim]"
            )
            continue

        if raw.lower() == "/model":
            console.print(f"[bold]Provider:[/bold] {provider_label}  [bold]Modell:[/bold] {model}")
            continue

        if raw.lower() == "/self":
            try:
                from nouse.self_layer import load_living_core
                core = load_living_core()
                console.print(Panel(
                    core.get("reflection") or "[dim]Ingen reflektion ännu.[/dim]",
                    title="Senaste självreflektion",
                    border_style="dim",
                ))
            except Exception as e:
                console.print(f"[dim]Självreflektion ej tillgänglig: {e}[/dim]")
            continue

        if raw.lower() == "/learn":
            if last_user and last_assistant:
                console.print("[dim]Lär...[/dim]", end="")
                await _async_learn(field, last_user, last_assistant)
                console.print(" [green]✓[/green]")
            else:
                console.print("[dim]Inget svar att lära från ännu.[/dim]")
            continue

        if raw.lower() == "/clear":
            messages = [{"role": "system", "content": system_prompt}]
            console.print("[dim]Historik rensad.[/dim]")
            continue

        # ── Berika med grafkontext ─────────────────────────────────────────────
        user_content = raw
        if not no_context:
            ctx = _recall_context(field, raw)
            if ctx:
                user_content = f"{ctx}\n\n---\n{raw}"

        messages.append({"role": "user", "content": user_content})
        last_user = raw

        # ── LLM-anrop med streaming ────────────────────────────────────────────
        console.print()
        full_response = ""

        try:
            gen = _stream_response(client, model, messages)
            buf = ""
            async for chunk in gen:
                buf += chunk
                print(chunk, end="", flush=True)
            full_response = buf
            print()  # newline after stream
        except Exception as e:
            # Streaming misslyckades — försök utan stream
            try:
                full_response = await _get_response(client, model, messages)
                console.print(Markdown(full_response))
            except Exception as e2:
                console.print(f"[red]LLM-fel: {e2}[/red]")
                messages.pop()  # Ta bort user-meddelandet om anropet misslyckades
                continue

        last_assistant = full_response
        messages.append({"role": "assistant", "content": full_response})

        # ── Bakgrundsinlärning ─────────────────────────────────────────────────
        if not no_learn and full_response:
            asyncio.create_task(_async_learn(field, raw, full_response))
