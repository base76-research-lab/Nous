
import typer
from nouse.cli.console import console
app = typer.Typer(
    name="nouse",
    help="nouse - local multi-agent society on the FNC framework.",
    add_completion=False,
    no_args_is_help=True,  # Kör main-callback om inget kommando anges
    invoke_without_command=True,
)

def _version_callback(value: bool):
    if value:
        try:
            import nouse
            print(f"nouse {getattr(nouse, '__version__', 'unknown')}")
        except ImportError:
            print("nouse (version unknown)")
        import sys
        sys.stdout.flush()
        sys.exit(0)


@app.callback()
def main(
    version: bool = typer.Option(
        None,
        "--version",
        "-V",
        help="Visa version och avsluta.",
        callback=_version_callback,
        is_eager=True,
    ),
):
    import sys
    # Om bara 'nouse' körs (ingen subkommandon): starta onboarding/chat
    if len(sys.argv) <= 1 or (len(sys.argv) == 2 and sys.argv[1] in ("--version", "-V")):
        return
    # Om inga subkommandon, kör onboarding
    if not any(a in sys.argv[1:] for a in app.registered_commands):
        from nouse.cli.run import run
        run()

# Gör frontdoor/front-door till alias för onboarding/chat
@app.command("frontdoor")
@app.command("front-door")
def frontdoor_cmd():
    """Startar onboarding/chat (frontdoor)."""
    from nouse.cli.run import run
    run()


@app.command("help", help="Visa endast kärnkommandon.")
def help_cmd():
    # Minimal help-vy för onboarding. Visa endast kärnkommandon.
    console.print("[bold cyan]nouse CLI[/bold cyan] — kärnkommandon:\n  - chat\n  - status\n  - brain\n  - ask\n  - mcp\n  - help\n\nAnvänd [green]nouse --version[/green] för version.\nSe dokumentation för mer info.")


@app.command(name="status")
def status() -> None:
    from nouse.cli.commands.relay import app as relay_app
    import sys
    sys.argv = ["nouse", "relay", action] + (args or [])
    relay_app()


@app.command(name="mcp")
def mcp_cmd(
    action: str = typer.Argument("serve", help="serve"),
) -> None:
    from nouse.client import (
        DAEMON_BASE,
        brain_clawbot_allowlist,
        daemon_running,
        get_status,
        get_system_events,
    )

    choice = str(mode or "me").strip().lower()
    if choice not in {"me", "research", "autonomy"}:
        console.print("[red]Ogiltigt mode.[/red] Använd: me | research | autonomy")
        raise typer.Exit(1)

    if choice == "research":
        if daemon_running():
            url = f"http://127.0.0.1:{web_port}"
            console.print(f"[green]Research cockpit:[/green] {url}")
            if open_browser:
                try:
                    subprocess.Popen(
                        ["xdg-open", url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
            return
        console.print("[yellow]Daemon ej igång - startar web cockpit...[/yellow]")
        daemon(action="web", port=web_port)
        return

    if not daemon_running():
        console.print("[yellow]Daemon ej igång - försöker starta i bakgrunden...[/yellow]")
        if not _ensure_daemon_background(web_port=web_port):
            console.print(
                f"[red]Kunde inte starta daemon automatiskt.[/red] Kör: "
                f"`nouse daemon web --port {web_port}`"
            )
            raise typer.Exit(1)
        console.print(f"[green]Daemon uppe.[/green] {DAEMON_BASE}")

    if choice == "me":
        _chat_via_api(session_id=session_id)
        return

    # autonomy
    status = get_status()
    events = get_system_events(limit=8)
    allow = brain_clawbot_allowlist(channel="ops")
    console.print(
        Panel(
            f"[bold]Autonomy Overview[/bold]\n"
            f"concepts={status.get('concepts','?')} relations={status.get('relations','?')} "
            f"cycle={status.get('cycle','?')}\n"
            f"pending_system_events={events.get('stats',{}).get('pending_total','?')}\n"
            f"clawbot_ops_allowed={len(allow.get('allowed') or [])} "
            f"pending_pairings={len(allow.get('pending') or [])}",
            border_style="magenta",
        )
    )
    console.print(
        "[dim]Nästa: `nouse clawbot allowlist --channel ops` eller "
        "`nouse clawbot ingest --channel ops --actor-id <id> --text \"...\"`[/dim]"
    )


@app.command()
def brain(
    action: str = typer.Argument(
        "state",
        help="status | health | state | gap | metrics | live | step | save",
    ),
    last_n: int = typer.Option(20, "--last-n", help="Antal cykler för metrics"),
    limit_nodes: int = typer.Option(12, "--limit-nodes", help="Max aktiva noder i live-vy"),
    limit_edges: int = typer.Option(16, "--limit-edges", help="Max aktiva kanter i live-vy"),
    events_json: str = typer.Option(
        "",
        "--events-json",
        help="JSON-lista med events för 'step' (annars tom lista).",
    ),
) -> None:
    from nouse.client import (
        DAEMON_BASE,
        brain_clawbot_allowlist,
        brain_clawbot_approve,
        brain_clawbot_ingest,
        daemon_running,
    )

    act = action.strip().lower()
    if not daemon_running():
        console.print(f"[red]nouse daemon ej nåbar på {DAEMON_BASE}[/red]")
        raise typer.Exit(1)

    if act == "status":
        console.print(f"[green]bridge online[/green] {DAEMON_BASE}")
        console.print_json(data=brain_clawbot_allowlist(channel=channel))
        return
    if act == "allowlist":
        console.print_json(data=brain_clawbot_allowlist(channel=channel))
        return
    if act == "approve":
        if not code.strip():
            console.print("[red]Ange --code för approve.[/red]")
            raise typer.Exit(1)
        console.print_json(data=brain_clawbot_approve(channel=channel, code=code.strip()))
        return
    if act == "ingest":
        if not text.strip():
            console.print("[red]Ange --text för ingest.[/red]")
            raise typer.Exit(1)
        console.print_json(
            data=brain_clawbot_ingest(
                text=text,
                channel=channel,
                actor_id=actor_id,
                mode=mode,
                strict_pairing=strict_pairing,
            )
        )
        return

    console.print("[red]Okänd action.[/red] Använd: status | allowlist | approve | ingest")
    raise typer.Exit(1)


@app.command()
def chat(
    session_id: str = typer.Option("main", "--session-id", "-s", help="Session-id för chat"),
    show_background: bool = typer.Option(
        False,
        "--show-background/--hide-background",
        help="Visa/dölj interna tool-spår under chat.",
    ),
) -> None:
    chat(session_id=session_id, show_background=show_background)


@app.command(name="i")
def interact_short_alias(
    session_id: str = typer.Option("main", "--session-id", "-s", help="Session-id för interaktion"),
    show_background: bool = typer.Option(
        False,
        "--show-background/--hide-background",
        help="Visa/dölj interna tool-spår under interaktion.",
    ),
) -> None:
    from nouse.client import get_status, stream_chat
    from rich.panel import Panel
    from rich.markdown import Markdown

    s = get_status()
    console.print(Panel(
        f"[bold cyan]nouse brain[/bold cyan]  {s['concepts']} koncept · "
        f"{s['relations']} relationer · {len(s['domains'])} domäner\n"
        f"[dim]λ={s['lambda']}  arousal={s['arousal']}  cykel={s['cycle']}[/dim]\n"
        "[dim]'exit' för att avsluta[/dim]",
        border_style="cyan",
    ))

    while True:
        try:
            raw = input("\ndu> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw or raw.lower() in ("exit", "quit", "q"):
            break

        response = ""
        seen_trace_id: str | None = None
        saw_done = False
        saw_error = False
        try:
            for item in stream_chat(raw, session_id=session_id):
                t = item.get("type", "")
                if not seen_trace_id:
                    tid = item.get("trace_id")
                    if tid:
                        seen_trace_id = str(tid)
                if t == "tool":
                    if show_background:
                        console.print(f"  [dim]⟳ {item.get('name','?')}[/dim]")
                elif t == "tool_result":
                    if show_background:
                        r = item.get("result", {})
                        if r.get("added"):
                            console.print(f"  [dim cyan]⊕ GRAF VÄXER[/dim cyan]  "
                                          f"[dim]{r.get('relation','')}[/dim]")
                elif t == "done":
                    saw_done = True
                    response = str(item.get("msg") or "").strip()
                elif t == "error":
                    saw_error = True
                    console.print(f"  [red]Fel: {item.get('msg')}[/red]")
        except Exception as e:
            console.print(f"  [red]Fel i chat-stream: {e}[/red]")
            continue

        if saw_done and response:
            console.print(Markdown(f"\n**b76>** {response}"))
        elif saw_done:
            console.print("  [yellow]Modellen returnerade tomt slutsvar.[/yellow]")
        elif not saw_error:
            console.print("  [yellow]Streamen avslutades utan slutsvar.[/yellow]")
        if seen_trace_id and (saw_done or saw_error):
            console.print(f"[dim]trace_id: {seen_trace_id}[/dim]")


@app.command()
def ask(
    question: str = typer.Argument(..., help="Ställ en fråga"),
    session_id: str = typer.Option("main", "--session-id", "-s", help="Session-id för ask"),
) -> None:
    import asyncio
    from nouse.cli.ask import ask_brain
    try:
        asyncio.run(ask_brain("", chat_mode=True, session_id=session_id))
    except KeyboardInterrupt:
        console.print("\n[dim]Avslutar snabbchatt.[/dim]")

@app.command()
def web(port: int = typer.Option(8765, "--port", "-p")) -> None:
    import asyncio
    from pathlib import Path
    from nouse.daemon.file_text import extract_text
    from nouse.daemon.sources import DEFAULT_INGEST_EXTENSIONS, iter_ingest_files
    from nouse.field.surface import FieldSurface
    from nouse.daemon.extractor import extract_relations

    p = Path(path)
    if not p.exists():
        console.print(f"[red]Hittade inte: {path}[/red]")
        raise typer.Exit(1)

    async def _run():
        field = FieldSurface()
        files: list[Path]
        if p.is_dir():
            files = list(iter_ingest_files(p, extensions=DEFAULT_INGEST_EXTENSIONS))
        else:
            files = [p]

        total_rels = 0
        processed = 0
        for f in files:
            text = extract_text(f)
            if len(text.strip()) < 100:
                continue
            rels = await extract_relations(text, {"path": str(f), "source": "manual"})
            for r in rels:
                field.add_concept(r["src"], r["domain_src"])
                field.add_concept(r["tgt"], r["domain_tgt"])
                field.add_relation(r["src"], r["type"], r["tgt"], why=r.get("why", ""))
            total_rels += len(rels)
            processed += 1

        console.print(
            f"[green]+{total_rels} relationer inmatade.[/green] "
            f"[dim]Filer processade: {processed}/{len(files)}[/dim] "
            f"Graf: {field.stats()}"
        )

    try:
        asyncio.run(_run())
        return
    except RuntimeError as e:
        if "Could not set lock on file" not in str(e):
            raise

    # Fallback när Kuzu är låst: skicka filtext till daemon-API.
    api_err: Exception | None = None
    try:
        import httpx
        from nouse.client import DAEMON_BASE, daemon_running

        if daemon_running():
            if p.is_dir():
                files = list(iter_ingest_files(p, extensions=DEFAULT_INGEST_EXTENSIONS))
            else:
                files = [p]

            total_added = 0
            processed = 0
            for f in files:
                text = extract_text(f)
                if len(text.strip()) < 100:
                    continue
                r = httpx.post(
                    f"{DAEMON_BASE}/api/ingest",
                    json={"text": text, "source": f"manual:{f}"},
                    timeout=90.0,
                )
                r.raise_for_status()
                data = r.json() or {}
                total_added += int(data.get("added", 0) or 0)
                processed += 1

            console.print(
                f"[green]+{total_added} relationer inmatade via daemon.[/green] "
                f"[dim]Filer processade: {processed}/{len(files)} · mode=api_ingest[/dim]"
            )
            return
    except Exception as e:
        api_err = e

    from datetime import datetime, timezone
    from pathlib import Path as _Path

    qdir = _Path.home() / ".local" / "share" / "nouse" / "capture_queue"
    qdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    queued = qdir / f"manual_ingest_{ts}.txt"
    queued.write_text(
        f"INGEST_LOCK_FALLBACK\npath={p}\nerror={api_err}\n",
        encoding="utf-8",
    )
    console.print(
        "[yellow]DB låst och daemon ej nåbar. Ingest kunde inte köras nu.[/yellow]"
    )
    console.print(f"[dim]Fallback-logg: {queued}[/dim]")


@app.command(name="learn-from")
def learn_from(
    source: str = typer.Argument(..., help="URL eller lokal fil/katalog"),
    debug_extract: bool = typer.Option(
        False,
        "--debug-extract",
        help="Visa extraktionsdiagnostik (källa, skäl, textlängd).",
    ),
) -> None:
    from pathlib import Path

    from nouse.daemon.file_text import extract_text
    from nouse.daemon.sources import DEFAULT_INGEST_EXTENSIONS, iter_ingest_files
    from nouse.embeddings.chunking import chunk_text
    from nouse.embeddings.index import JsonlVectorIndex, make_chunk_record
    from nouse.embeddings.ollama_embed import OllamaEmbedder

    src = Path(source).expanduser()
    if not src.exists():
        console.print(f"[red]Hittade inte: {src}[/red]")
        raise typer.Exit(1)

    files: list[Path]
    if src.is_dir():
        files = list(iter_ingest_files(src, extensions=DEFAULT_INGEST_EXTENSIONS))
    else:
        files = [src]

    if not files:
        console.print("[yellow]Inga indexerbara filer hittades.[/yellow]")
        return

    embedder = OllamaEmbedder()
    index = JsonlVectorIndex()
    # Conservative defaults to keep learn-from operational even if CLI options
    # are omitted from this command signature.
    max_chars = 1200
    overlap_chars = 180
    batch = 16

    chunk_rows: list[dict] = []
    for f in files:
        try:
            txt = extract_text(f)
        except Exception:
            continue
        if debug_extract:
            console.print(
                f"[dim]extract: {f} · chars={len(txt)}[/dim]"
            )
        if len(txt.strip()) < 80:
            continue
        chunks = chunk_text(txt, max_chars=max_chars, overlap_chars=overlap_chars)
        for i, ch in enumerate(chunks):
            chunk_rows.append({
                "path": str(f),
                "chunk_ix": i,
                "text": ch,
                "source": "embed_index",
                "domain_hint": "okänd",
            })

    if not chunk_rows:
        console.print("[yellow]Ingen text kunde chunkas för embedding.[/yellow]")
        return

    written = 0
    i = 0
    while i < len(chunk_rows):
        batch_rows = chunk_rows[i:i + max(1, batch)]
        vectors = embedder.embed_texts([r["text"] for r in batch_rows])
        records = [
            make_chunk_record(
                path=r["path"],
                chunk_ix=r["chunk_ix"],
                text=r["text"],
                vector=v,
                source=r["source"],
                domain_hint=r["domain_hint"],
            )
            for r, v in zip(batch_rows, vectors, strict=True)
        ]
        written += index.add_records(records)
        i += len(batch_rows)

    console.print(
        f"[green]Embedding-index uppdaterat.[/green] "
        f"Filer={len(files)} · chunks={len(chunk_rows)} · skrivna={written}"
    )


@app.command(name="embed-search")
def embed_search(
    query: str = typer.Argument(..., help="Semantisk fråga"),
    top_k: int = typer.Option(5, "--top-k", help="Antal träffar"),
) -> None:
    from nouse.embeddings.index import search_index
    from nouse.embeddings.ollama_embed import OllamaEmbedder

    q = query.strip()
    if not q:
        console.print("[red]Tom query.[/red]")
        raise typer.Exit(1)

    embedder = OllamaEmbedder()
    try:
        qv = embedder.embed_texts([q])[0]
    except Exception as e:
        console.print(f"[red]Kunde inte skapa embedding:[/red] {e}")
        raise typer.Exit(1) from e

    got = search_index(query_vector=qv, top_k=max(1, top_k))
    if not got:
        console.print("[yellow]Inga träffar i embedding-index.[/yellow]")
        return

    console.print(f"[bold]Top {len(got)} träffar[/bold] för: [cyan]{q}[/cyan]\n")
    for i, h in enumerate(got, start=1):
        snippet = " ".join((h.text or "").split())
        if len(snippet) > 220:
            snippet = snippet[:217] + "..."
        console.print(
            f"{i}. [cyan]{h.score:.3f}[/cyan] "
            f"[dim]{h.path}#{h.chunk_ix} · {h.source} · {h.domain_hint}[/dim]"
        )
        if snippet:
            console.print(f"   {snippet}")


@app.command()
def visualize(
    output: str = typer.Option(
        "/tmp/b76_graph.html",
        "--output", "-o",
        help="HTML-fil att skriva till"
    ),
    domain: str | None = typer.Option(
        None, "--domain", "-d",
        help="Filtrera till specifik domän"
    ),
    min_strength: float = typer.Option(
        0.0, "--min-strength",
        help="Minsta kantstyrka att visa"
    ),
    max_nodes: int = typer.Option(
        200, "--max-nodes",
        help="Max antal noder"
    ),
) -> None:
    from nouse.client import daemon_running, get_nerv
    if daemon_running():
        result = get_nerv(domain_a, domain_b, max_hops=max_hops)
        if not result.get("found"):
            console.print(f"[red]Ingen stig hittad: {domain_a} -> {domain_b}[/red]")
            raise typer.Exit(1)
        console.print(f"\n[bold]Nervbana[/bold] {domain_a} -> {domain_b}  "
                      f"[cyan]novelty={result['novelty']:.1f}[/cyan]\n")
        for step in result["path"]:
            console.print(f"  [yellow]{step['from']}[/yellow] -[{step['rel']}]-> [green]{step['to']}[/green]")
    else:
        from nouse.field.surface import FieldSurface
        field = FieldSurface(read_only=False)
        path = field.find_path(domain_a, domain_b, max_hops=max_hops)
        if not path:
            console.print(f"[red]Ingen stig: {domain_a} -> {domain_b}[/red]")
            raise typer.Exit(1)
        novelty = field.path_novelty(path)
        console.print(f"\n[bold]Nervbana[/bold] {domain_a} -> {domain_b}  "
                      f"[cyan]novelty={novelty:.1f}[/cyan]\n")
        for src, rel, tgt in path:
            console.print(f"  [yellow]{src}[/yellow] -[{rel}]-> [green]{tgt}[/green]")


@app.command()
def bisoc(
    tau: float = typer.Option(0.55, "--tau", "-t",
                              help="Min topologisk similaritet (0-1)"),
    epsilon: float = typer.Option(2.0, "--epsilon", "-e",
                                  help="Vietoris-Rips epsilon"),
    limit: int = typer.Option(50, "--limit", "-l",
                              help="Max antal domäner att analysera (top-N efter storlek)"),
) -> None:
    from nouse.tda.bridge import is_rust_active
    from nouse.client import daemon_running, get_bisoc

    engine = "[green]Rust[/green]" if is_rust_active() else "[yellow]Python[/yellow]"
    console.print(f"\n[bold cyan]TDA Bisociation[/bold cyan]  "
                  f"motor={engine}  τ≥{tau}  ε={epsilon}\n")

    if daemon_running():
        data = get_bisoc(tau=tau, epsilon=epsilon, max_domains=limit)
        candidates = data.get("candidates", [])
    else:
        from nouse.field.surface import FieldSurface
        field = FieldSurface(read_only=True)
        candidates = field.bisociation_candidates(tau_threshold=tau,
                                                  max_epsilon=epsilon,
                                                  max_domains=limit)
    if not candidates:
        console.print("[dim]Inga kandidater - lägg till fler domäner först.[/dim]")
        return

    for c in candidates:
        sem = c.get("semantic_similarity")
        sem_txt = f"{float(sem):.3f}" if sem is not None else "n/a"
        console.print(
            f"  [bold]score={float(c.get('score', c['tau'])):.3f}[/bold] "
            f"[cyan]τ={c['tau']:.3f}[/cyan] "
            f"[magenta]sem={sem_txt}[/magenta] "
            f"[yellow]{c['domain_a']}[/yellow] × [green]{c['domain_b']}[/green]  "
            f"[dim](H0: {c['h0_a']}/{c['h0_b']}  H1: {c['h1_a']}/{c['h1_b']})[/dim]"
        )
    console.print(f"\n[dim]{len(candidates)} kandidater totalt.[/dim]")


@app.command()
def limbic() -> None:
    from nouse.metacognition.snapshot import create_snapshot
    from nouse.field.surface import FieldSurface
    field = FieldSurface(read_only=True)
    
    console.print(f"[dim]Kopierar graf-databas, exporterar limbiska variabler och beräknar nätverkstopologi H0/H1...[/dim]")
    out_dir = create_snapshot(field, tag=tag)
    console.print(f"\n[bold green]✅ Snapshot lagrat (tag: {tag})[/bold green]")
    console.print(f"Sökväg: [cyan]{out_dir}[/cyan]")



@app.command()
def autonomous(
    iterations: int = typer.Option(0, "--iterations", "-i", help="Antal iterationer att köra (0 = oändligt)")
) -> None:
    import asyncio
    import os
    import time

    from nouse.client import (
        daemon_running,
        get_queue_run_status,
        get_queue_status,
        post_queue_run,
        post_queue_scan,
    )
    from nouse.daemon.research_queue import (
        claim_next_task,
        complete_task,
        enqueue_gap_tasks,
        fail_task,
        peek_tasks,
        queue_stats,
    )
    from nouse.daemon.initiative import run_curiosity_burst
    from nouse.daemon.evidence import assess_relation, format_why_with_evidence
    from nouse.daemon.extractor import extract_relations_with_diagnostics
    from nouse.field.surface import FieldSurface
    from nouse.limbic.signals import load_state

    def _parse_models(raw: str) -> list[str]:
        return [x.strip() for x in (raw or "").split(",") if x.strip()]

    def _read_positive_float(raw: str, default: float = 0.0) -> float:
        try:
            value = float((raw or "").strip())
        except (TypeError, ValueError):
            return float(default)
        return value if value > 0 else float(default)

    env_task_timeout = _read_positive_float(os.getenv("NOUSE_RESEARCH_QUEUE_TASK_TIMEOUT_SEC", "0"))
    env_extract_timeout = _read_positive_float(
        os.getenv("NOUSE_RESEARCH_QUEUE_EXTRACT_TIMEOUT_SEC", "0")
    )
    effective_task_timeout = float(task_timeout) if task_timeout > 0 else env_task_timeout
    effective_extract_timeout = (
        float(extract_timeout) if extract_timeout > 0 else env_extract_timeout
    )
    effective_extract_models = _parse_models(
        extract_models or os.getenv("NOUSE_RESEARCH_QUEUE_EXTRACT_MODELS", "")
    )

    async def _run_one_task(field: FieldSurface, *, source: str) -> dict[str, object]:
        enqueue_gap_tasks(field, max_new=3)
        task = claim_next_task()
        if not task:
            return {"status": "empty"}

        task_id = int(task.get("id", -1) or -1)
        console.print(
            f"[bold]Kör task #{task_id}[/bold] [cyan]{task.get('domain','okänd')}[/cyan]"
        )
        limbic = load_state()

        try:
            curiosity_coro = run_curiosity_burst(field, limbic, task=task)
            if effective_task_timeout > 0:
                text = await asyncio.wait_for(curiosity_coro, timeout=effective_task_timeout)
            else:
                text = await curiosity_coro
        except asyncio.TimeoutError:
            fail_task(task_id, f"Task-timeout efter {effective_task_timeout:.1f}s (curiosity)")
            return {
                "status": "failed",
                "task_id": task_id,
                "error": "curiosity_timeout",
                "timeout": True,
            }
        except Exception as e:
            fail_task(task_id, f"Curiosity misslyckades: {e}")
            return {
                "status": "failed",
                "task_id": task_id,
                "error": str(e),
                "timeout": "timeout" in str(e).lower(),
            }

        if not text:
            fail_task(task_id, "Ingen rapport producerades")
            return {
                "status": "failed",
                "task_id": task_id,
                "error": "no_report",
            }

        meta: dict[str, object] = {
            "source": source,
            "path": f"task_{task_id}",
            "domain_hint": str(task.get("domain") or "okänd"),
        }
        if effective_extract_timeout > 0:
            meta["extract_timeout_sec"] = effective_extract_timeout
        if effective_extract_models:
            meta["extract_models"] = effective_extract_models

        try:
            extract_coro = extract_relations_with_diagnostics(text, meta)
            if effective_task_timeout > 0:
                rels, diag = await asyncio.wait_for(extract_coro, timeout=effective_task_timeout)
            else:
                rels, diag = await extract_coro
        except asyncio.TimeoutError:
            fail_task(task_id, f"Task-timeout efter {effective_task_timeout:.1f}s (extract)")
            return {
                "status": "failed",
                "task_id": task_id,
                "error": "extract_timeout",
                "timeout": True,
            }
        except Exception as e:
            fail_task(task_id, f"Extraktion misslyckades: {e}")
            return {
                "status": "failed",
                "task_id": task_id,
                "error": str(e),
                "timeout": "timeout" in str(e).lower(),
            }

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
            "added": added,
            "avg_evidence": avg_evidence,
            "max_evidence": max_evidence,
            "tier_counts": tier_counts,
            "diag": diag,
        }

    def _self_update_recommendations(summary: dict[str, int]) -> list[str]:
        notes: list[str] = []
        processed = int(summary.get("processed", 0))
        zero_rel = int(summary.get("zero_rel", 0))
        failed = int(summary.get("failed", 0))
        extract_timeouts = int(summary.get("extract_timeouts", 0))
        curiosity_timeouts = int(summary.get("curiosity_timeouts", 0))
        no_report = int(summary.get("no_report", 0))
        if processed >= 2 and zero_rel >= max(2, processed // 2):
            notes.append(
                "Extraktionen ger ofta 0 relationer -> höj --extract-timeout eller ange "
                "--extract-models med snabb modell först (t.ex. deepseek-r1:1.5b)."
            )
        if extract_timeouts >= 2:
            notes.append(
                "Flera extract-timeouts upptäckta -> trimma EXTRACT_MAX_CHARS eller "
                "routa till lättare modell för workload 'extract'."
            )
        if no_report >= 1:
            notes.append(
                "Curiosity gav tom rapport -> överväg kortare query + fler källor för respektive domän."
            )
        if curiosity_timeouts >= 1:
            notes.append(
                "Curiosity-timeout upptäckt -> öka NOUSE_LLM_TIMEOUT_SEC eller välj snabbare basmodell."
            )
        if failed >= max(2, processed // 2):
            notes.append(
                "Hög felandel i batch -> systemet föreslår en intern stabiliseringsfas innan större körning."
            )
        return notes

    def _print_queue_status_payload(payload: dict[str, object]) -> None:
        stats = payload.get("stats") if isinstance(payload, dict) else {}
        tasks = payload.get("tasks") if isinstance(payload, dict) else []
        s = stats if isinstance(stats, dict) else {}
        trows = tasks if isinstance(tasks, list) else []
        console.print(
            f"[bold cyan]Research Queue[/bold cyan]  "
            f"total={int(s.get('total', 0))}  pending={int(s.get('pending', 0))}  "
            f"in_progress={int(s.get('in_progress', 0))}  "
            f"awaiting_approval={int(s.get('awaiting_approval', 0))}  "
            f"cooling_down={int(s.get('cooling_down', 0))}  "
            f"done={int(s.get('done', 0))}  failed={int(s.get('failed', 0))}"
        )
        for t in trows[: max(1, limit)]:
            if not isinstance(t, dict):
                continue
            console.print(
                f"  [dim]#{t.get('id')}[/dim] "
                f"[yellow]{t.get('status')}[/yellow] "
                f"prio={float(t.get('priority', 0.0) or 0.0):.2f} "
                f"domän=[green]{t.get('domain', 'okänd')}[/green] "
                f"gap={t.get('gap_type', '?')}"
            )

    def _print_batch_results(summary: dict[str, int], results: list[dict[str, object]]) -> None:
        if not results:
            console.print("[yellow]Inga task-resultat returnerades.[/yellow]")
        for result in results:
            status = str(result.get("status", ""))
            if status == "empty":
                console.print("[yellow]Queue tom - avbryter batch.[/yellow]")
                break
            if status != "done":
                console.print(
                    f"[red]Task #{result.get('task_id', '?')} misslyckades.[/red] "
                    f"[dim]{result.get('error', '')}[/dim]"
                )
                continue
            console.print(
                f"[green]Task #{result.get('task_id', '?')} klar.[/green] "
                f"+{int(result.get('added', 0) or 0)} relationer "
                f"[dim](avg={float(result.get('avg_evidence', 0.0) or 0.0):.3f}, "
                f"max={float(result.get('max_evidence', 0.0) or 0.0):.3f})[/dim]"
            )

        console.print(
            f"\n[bold]Batch klart:[/bold] processed={int(summary.get('processed', 0))}/"
            f"{int(summary.get('requested', 0))}  "
            f"added_relations={int(summary.get('added_relations', 0))}  "
            f"zero_rel={int(summary.get('zero_rel', 0))}  "
            f"failed={int(summary.get('failed', 0))}"
        )
        notes = _self_update_recommendations(summary)
        if notes:
            console.print("[bold magenta]Systemets egna förbättringsförslag[/bold magenta]")
            for note in notes:
                console.print(f"  - {note}")

    if daemon_running():
        if action == "status":
            try:
                payload = get_queue_status(limit=max(1, limit), status="all", timeout=15.0)
            except Exception as e:
                console.print(f"[red]Kunde inte läsa queue-status via daemon API:[/red] {e}")
                raise typer.Exit(2)
            _print_queue_status_payload(payload)
            return

        if action == "scan":
            try:
                payload = post_queue_scan(max_new=max(1, limit), timeout=20.0)
            except Exception as e:
                console.print(f"[red]Kunde inte köra scan via daemon API:[/red] {e}")
                raise typer.Exit(2)
            console.print(f"[green]+{int(payload.get('added', 0))} nya taskar i research-queue.[/green]")
            _print_queue_status_payload(payload)
            return

        if action in {"run-one", "run-batch"}:
            requested = 1 if action == "run-one" else max(1, int(count))
            source_tag = "research_queue_cli" if action == "run-one" else "research_queue_batch_cli"
            api_task_timeout = float(effective_task_timeout) if effective_task_timeout > 0 else 180.0
            api_extract_timeout = (
                float(effective_extract_timeout) if effective_extract_timeout > 0 else 30.0
            )
            try:
                queued = post_queue_run(
                    count=requested,
                    task_timeout_sec=api_task_timeout,
                    extract_timeout_sec=api_extract_timeout,
                    extract_models=",".join(effective_extract_models),
                    source=source_tag,
                    wait=False,
                    timeout=20.0,
                )
            except Exception as e:
                console.print(f"[red]Kunde inte starta queue-job via daemon API:[/red] {e}")
                raise typer.Exit(2)

            job_id = str(queued.get("job_id") or "").strip()
            if not job_id:
                console.print("[red]Queue-job startades inte (saknar job_id).[/red]")
                raise typer.Exit(2)

            console.print(
                f"[cyan]Queue-job köad[/cyan] job_id={job_id}  "
                f"[dim](count={requested}, task_timeout={api_task_timeout:.1f}s, "
                f"extract_timeout={api_extract_timeout:.1f}s)[/dim]"
            )
            if effective_extract_models:
                console.print(f"[dim]extract_models={', '.join(effective_extract_models)}[/dim]")

            deadline = time.monotonic() + max(
                45.0,
                requested * max(60.0, api_task_timeout) + 90.0,
            )
            while time.monotonic() < deadline:
                try:
                    status_row = get_queue_run_status(
                        job_id=job_id,
                        include_results=True,
                        timeout=20.0,
                    )
                except Exception:
                    time.sleep(1.0)
                    continue
                status = str(status_row.get("status", "")).strip().lower()
                if status in {"queued", "running"}:
                    time.sleep(1.0)
                    continue
                if status == "failed":
                    console.print(
                        f"[red]Queue-job misslyckades.[/red] "
                        f"[dim]{status_row.get('error', 'okänt fel')}[/dim]"
                    )
                    raise typer.Exit(2)
                if status == "done":
                    summary_raw = status_row.get("summary")
                    results_raw = status_row.get("results")
                    summary = summary_raw if isinstance(summary_raw, dict) else {}
                    results = results_raw if isinstance(results_raw, list) else []
                    _print_batch_results(summary, results)
                    return
                time.sleep(1.0)

            console.print(
                "[yellow]Timeout när vi väntade på queue-jobbet via API.[/yellow] "
                f"[dim]Fortsätt följa med: nouse research-queue status eller /api/queue/run_status?job_id={job_id}[/dim]"
            )
            raise typer.Exit(2)

    if action == "status":
        s = queue_stats()
        console.print(
            f"[bold cyan]Research Queue[/bold cyan]  "
            f"total={s['total']}  pending={s['pending']}  "
            f"in_progress={s['in_progress']}  awaiting_approval={s.get('awaiting_approval',0)}  "
            f"cooling_down={s.get('cooling_down',0)}  "
            f"done={s['done']}  failed={s['failed']}"
        )
        for t in peek_tasks(limit=limit):
            console.print(
                f"  [dim]#{t.get('id')}[/dim] "
                f"[yellow]{t.get('status')}[/yellow] "
                f"prio={float(t.get('priority',0.0)):.2f} "
                f"domän=[green]{t.get('domain','okänd')}[/green] "
                f"gap={t.get('gap_type','?')}"
            )
        return

    if action == "scan":
        try:
            field = FieldSurface(read_only=True)
        except RuntimeError as e:
            if "Could not set lock on file" in str(e):
                console.print(
                    "[red]Kunde inte läsa grafen p.g.a. fillås.[/red]\n"
                    "[dim]Tips:[/dim] kör scan när daemon är stoppad, "
                    "eller låt daemonens inbyggda gap-queue sköta detta automatiskt."
                )
                raise typer.Exit(2)
            raise
        added = enqueue_gap_tasks(field, max_new=max(1, limit))
        console.print(f"[green]+{len(added)} nya taskar i research-queue.[/green]")
        for t in added[:limit]:
            console.print(
                f"  [dim]#{t['id']}[/dim] "
                f"[green]{t['domain']}[/green] "
                f"prio={t.get('priority',0):.2f} "
                f"[dim]{(t.get('query','')[:100])}[/dim]"
            )
        return

    if action == "run-one":
        async def _run_one() -> None:
            try:
                field = FieldSurface()
            except RuntimeError as e:
                if "Could not set lock on file" in str(e):
                    console.print(
                        "[red]Kunde inte öppna grafen i skrivläge p.g.a. fillås.[/red]\n"
                        "[dim]Tips:[/dim] stoppa daemon eller kör run-one via daemon-loop."
                    )
                    return
                raise
            result = await _run_one_task(field, source="research_queue_cli")
            if result.get("status") == "empty":
                console.print("[yellow]Ingen pending task i queue.[/yellow]")
                return
            if result.get("status") != "done":
                console.print(
                    f"[red]Task #{result.get('task_id', '?')} misslyckades.[/red] "
                    f"[dim]{result.get('error', '')}[/dim]"
                )
                return
            console.print(
                f"[green]Klart.[/green] +{int(result.get('added', 0) or 0)} relationer "
                f"från task #{result.get('task_id', '?')}  "
                f"[dim](evidence avg={float(result.get('avg_evidence', 0.0)):.3f}, "
                f"max={float(result.get('max_evidence', 0.0)):.3f}, "
                f"tiers={result.get('tier_counts', {})})[/dim]"
            )

        asyncio.run(_run_one())
        return

    if action == "run-batch":
        async def _run_batch() -> None:
            try:
                field = FieldSurface()
            except RuntimeError as e:
                if "Could not set lock on file" in str(e):
                    console.print(
                        "[red]Kunde inte öppna grafen i skrivläge p.g.a. fillås.[/red]\n"
                        "[dim]Tips:[/dim] stoppa daemon eller kör batch via daemon-loop."
                    )
                    return
                raise

            requested = max(1, int(count))
            summary = {
                "requested": requested,
                "processed": 0,
                "failed": 0,
                "zero_rel": 0,
                "no_report": 0,
                "extract_timeouts": 0,
                "curiosity_timeouts": 0,
                "added_relations": 0,
            }
            console.print(
                f"[bold cyan]run-batch[/bold cyan] count={requested}  "
                f"[dim]task_timeout={effective_task_timeout or 0:.1f}s, "
                f"extract_timeout={effective_extract_timeout or 0:.1f}s[/dim]"
            )
            if effective_extract_models:
                console.print(
                    f"[dim]extract_models={', '.join(effective_extract_models)}[/dim]"
                )

            for _ in range(requested):
                result = await _run_one_task(field, source="research_queue_batch")
                if result.get("status") == "empty":
                    q = queue_stats()
                    if int(q.get("pending", 0)) > 0 and int(q.get("cooling_down", 0)) > 0:
                        console.print(
                            "[yellow]Inga taskar redo just nu.[/yellow] "
                            f"[dim]{q.get('cooling_down', 0)} taskar är i cooldown.[/dim]"
                        )
                    else:
                        console.print("[yellow]Queue tom - avbryter batch.[/yellow]")
                    break
                summary["processed"] += 1
                if result.get("status") != "done":
                    summary["failed"] += 1
                    err = str(result.get("error", ""))
                    if err == "no_report":
                        summary["no_report"] += 1
                    if err == "extract_timeout":
                        summary["extract_timeouts"] += 1
                    elif err == "curiosity_timeout":
                        summary["curiosity_timeouts"] += 1
                    console.print(
                        f"[red]Task #{result.get('task_id', '?')} misslyckades.[/red] "
                        f"[dim]{result.get('error', '')}[/dim]"
                    )
                    continue

                added = int(result.get("added", 0) or 0)
                summary["added_relations"] += added
                if added == 0:
                    summary["zero_rel"] += 1
                diag = result.get("diag")
                if isinstance(diag, dict):
                    summary["extract_timeouts"] += int(diag.get("timeouts", 0) or 0)

                console.print(
                    f"[green]Task #{result.get('task_id', '?')} klar.[/green] "
                    f"+{added} relationer "
                    f"[dim](avg={float(result.get('avg_evidence', 0.0)):.3f}, "
                    f"max={float(result.get('max_evidence', 0.0)):.3f})[/dim]"
                )

            console.print(
                f"\n[bold]Batch klart:[/bold] processed={summary['processed']}/{summary['requested']}  "
                f"added_relations={summary['added_relations']}  "
                f"zero_rel={summary['zero_rel']}  failed={summary['failed']}"
            )

            notes = _self_update_recommendations(summary)
            if notes:
                console.print("[bold magenta]Systemets egna förbättringsförslag[/bold magenta]")
                for note in notes:
                    console.print(f"  - {note}")

        asyncio.run(_run_batch())
        return

    console.print("[red]Ogiltig action.[/red] Använd: status | scan | run-one | run-batch")


@app.command(name="mission")
def mission_cmd(
    action: str = typer.Argument("show", help="show | set | clear | metrics"),
    text: str = typer.Option("", "--text", "-t", help="Mission-text (för action=set)"),
    north_star: str = typer.Option("", "--north-star", help="Övergripande riktning"),
    focus_domain: list[str] = typer.Option(
        [],
        "--focus-domain",
        "-d",
        help="Domänfokus (kan anges flera gånger)",
    ),
    kpi: list[str] = typer.Option(
        [],
        "--kpi",
        help="KPI/utfallsmått (kan anges flera gånger)",
    ),
    constraint: list[str] = typer.Option(
        [],
        "--constraint",
        help="Hårda begränsningar (kan anges flera gånger)",
    ),
    lines: int = typer.Option(10, "--lines", "-n", help="Rader vid action=metrics"),
) -> None:
    from nouse.daemon.hitl import (
        approve_interrupt,
        interrupt_stats,
        list_interrupts,
        reject_interrupt,
    )
    from nouse.daemon.research_queue import (
        approve_task_after_hitl,
        reject_task_after_hitl,
    )

    if action == "status":
        s = interrupt_stats()
        rows = list_interrupts(
            status=(status if status != "all" else None),
            limit=max(1, limit),
        )
        console.print(
            f"[bold cyan]HITL[/bold cyan] total={s['total']} "
            f"pending={s['pending']} approved={s['approved']} rejected={s['rejected']}"
        )
        for row in rows:
            task = row.get("task") or {}
            console.print(
                f"  [dim]#{row.get('id')}[/dim] [yellow]{row.get('status')}[/yellow] "
                f"task=#{task.get('id','?')} "
                f"domän=[green]{task.get('domain','okänd')}[/green] "
                f"reason={row.get('reason','')}"
            )
        return

    if action == "approve":
        if interrupt_id <= 0:
            console.print("[red]Ange --id för interrupt.[/red]")
            raise typer.Exit(2)
        row = approve_interrupt(interrupt_id, reviewer=reviewer, note=note)
        if not row:
            console.print(f"[red]Interrupt #{interrupt_id} hittades inte.[/red]")
            raise typer.Exit(1)
        task_id = int(row.get("task_id", -1) or -1)
        if task_id > 0:
            approve_task_after_hitl(
                task_id,
                note=(note or "approved via CLI"),
            )
        console.print(
            f"[green]Godkänd[/green] interrupt #{interrupt_id} -> task #{task_id} återköad."
        )
        return

    if action == "reject":
        if interrupt_id <= 0:
            console.print("[red]Ange --id för interrupt.[/red]")
            raise typer.Exit(2)
        row = reject_interrupt(interrupt_id, reviewer=reviewer, note=note)
        if not row:
            console.print(f"[red]Interrupt #{interrupt_id} hittades inte.[/red]")
            raise typer.Exit(1)
        task_id = int(row.get("task_id", -1) or -1)
        if task_id > 0:
            reject_task_after_hitl(
                task_id,
                reason=(note or "rejected via CLI"),
            )
        console.print(
            f"[yellow]Avslagen[/yellow] interrupt #{interrupt_id} -> task #{task_id} markerad failed."
        )
        return

    console.print("[red]Ogiltig action.[/red] Använd: status | approve | reject")


@app.command(name="session")
def session_cmd(
    action: str = typer.Argument("stats", help="open | list | runs | energy | cancel | stats"),
    session_id: str = typer.Option("main", "--session-id", "-s", help="Session-id"),
    lane: str = typer.Option("main", "--lane", help="Session-lane"),
    source: str = typer.Option("cli", "--source", help="Källa för session-händelse"),
    status: str = typer.Option("all", "--status", help="Filter för list/runs"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max antal rader"),
    energy: float = typer.Option(0.5, "--energy", help="Energinivå 0..1 (action=energy)"),
) -> None:
    from nouse.llm.model_router import decay_router_state, router_status
    from nouse.llm.policy import get_workload_policy, reset_policy, set_workload_candidates

    def _split(raw: str) -> list[str]:
        return [x.strip() for x in str(raw or "").split(",") if x.strip()]

    if action == "status":
        policy = get_workload_policy(workload)
        router = router_status(workload=workload)
        rows = (router.get("workloads") or {}).get(workload) or []
        console.print(
            f"[bold cyan]Model Policy[/bold cyan] workload={policy.get('workload')} "
            f"provider={policy.get('provider')}"
        )
        console.print(
            "  candidates: "
            + (", ".join(policy.get("candidates") or []) if policy.get("candidates") else "[dim]inga explicita[/dim]")
        )
        if not rows:
            console.print("  [dim]Ingen router-historik ännu.[/dim]")
            return
        console.print("[bold]Router-rankning[/bold]")
        for row in rows:
            cooldown = float(row.get("cooldown_until", 0.0) or 0.0)
            cd_txt = "cooldown" if cooldown > 0 else "ok"
            console.print(
                f"  {row.get('model')}: score={float(row.get('score', 0.0)):.3f} "
                f"s={int(row.get('success', 0) or 0)} "
                f"f={int(row.get('failure', 0) or 0)} "
                f"t={int(row.get('timeout', 0) or 0)} "
                f"q={float(row.get('quality_avg', 0.0) or 0.0):.3f} {cd_txt}"
            )
        return

    if action == "set-fallback":
        values = _split(candidates)
        if not values:
            console.print("[red]Ange minst en kandidat via --candidates.[/red]")
            raise typer.Exit(2)
        row = set_workload_candidates(
            workload=workload,
            candidates=values,
            provider=provider,
        )
        console.print(
            f"[green]Policy sparad.[/green] workload={row.get('workload')} "
            f"candidates={', '.join(row.get('candidates') or [])}"
        )
        return

    if action == "reset":
        reset_policy()
        decay_router_state(workload=workload, factor=0.0, clear_cooldowns=True)
        console.print(
            f"[green]Model-policy återställd.[/green] workload={workload} "
            "[dim](router counters nollställda för workload)[/dim]"
        )
        return

    console.print("[red]Ogiltig action.[/red] Använd: status | set-fallback | reset")


@app.command(name="wake")
def wake_cmd(
    action: str = typer.Argument("status", help="status | emit"),
    text: str = typer.Option("", "--text", "-t", help="Systemsignal att lägga i kön"),
    session_id: str = typer.Option("main", "--session-id", "-s", help="Session för signalen"),
    mode: str = typer.Option("now", "--mode", "-m", help="now | next-heartbeat"),
    reason: str = typer.Option("operator_wake", "--reason", help="Wake-orsak"),
    source: str = typer.Option("cli", "--source", help="Källa"),
    context_key: str = typer.Option("", "--context-key", help="Valfri kontext-tag"),
    limit: int = typer.Option(10, "--limit", "-l", help="Antal events i status"),
) -> None:
    from nouse.llm.usage import list_usage, usage_summary

    if action == "summary":
        s = usage_summary(limit=max(1, limit))
        console.print(
            f"[bold cyan]Usage Summary[/bold cyan] rows={int(s.get('rows', 0) or 0)} "
            f"failed={int(s.get('failed', 0) or 0)} "
            f"tokens={int(s.get('total_tokens', 0) or 0)} "
            f"cost=${float(s.get('cost_usd', 0.0) or 0.0):.6f}"
        )
        for row in (s.get("by_model") or [])[:10]:
            console.print(
                f"  {row.get('model')}: calls={int(row.get('calls', 0) or 0)} "
                f"failed={int(row.get('failed', 0) or 0)} "
                f"tokens={int(row.get('total_tokens', 0) or 0)} "
                f"cost=${float(row.get('cost_usd', 0.0) or 0.0):.6f} "
                f"avg_latency={int(row.get('avg_latency_ms', 0) or 0)}ms"
            )
        return

    if action == "tail":
        rows = list_usage(
            limit=max(1, limit),
            session_id=(session_id or None),
            workload=(workload or None),
            model=(model or None),
            status=(status or None),
        )
        if not rows:
            console.print("[yellow]Ingen usage-data ännu.[/yellow]")
            return
        for row in rows:
            console.print(
                f"  {row.get('ts')}  session={row.get('session_id')} "
                f"{row.get('workload')} {row.get('provider')}:{row.get('model')} "
                f"{row.get('status')} tok={int(row.get('total_tokens', 0) or 0)} "
                f"cost=${float(row.get('cost_usd', 0.0) or 0.0):.6f} "
                f"lat={int(row.get('latency_ms', 0) or 0)}ms"
            )
        return

    console.print("[red]Ogiltig action.[/red] Använd: summary | tail")


@app.command(name="allowlist")
def allowlist_cmd(
    action: str = typer.Argument("list", help="list | pending | add | remove | approve"),
    channel: str = typer.Option("telegram", "--channel", "-c", help="Ingress-kanal"),
    actor: str = typer.Option("", "--actor", "-a", help="Actor-id"),
    code: str = typer.Option("", "--code", help="Pairing-kod"),
) -> None:
    from nouse.saas.auth import create_key, list_keys, revoke_key

    if action == "create":
        if not tenant:
            console.print("[red]--tenant krävs för create.[/red]")
            raise typer.Exit(1)
        new_key = create_key(tenant_id=tenant, label=label)
        console.print(f"\n[bold green]API-nyckel skapad[/bold green] (visas bara en gång):\n")
        console.print(f"  [bold cyan]{new_key}[/bold cyan]\n")
        console.print(f"[dim]Tenant: {tenant}  Label: {label or '–'}[/dim]")

    elif action == "list":
        rows = list_keys(tenant_id=tenant or None)
        if not rows:
            console.print("[dim]Inga nycklar.[/dim]")
            return
        console.print(f"[bold cyan]API-nycklar[/bold cyan]")
        for r in rows:
            status = "[green]aktiv[/green]" if r["active"] else "[red]inaktiv[/red]"
            console.print(f"  {r['key_hash']}  tenant={r['tenant_id']}  "
                          f"label={r['label'] or '–'}  {status}  {r['created_at'][:10]}")

    elif action == "revoke":
        if not key:
            console.print("[red]--key krävs för revoke.[/red]")
            raise typer.Exit(1)
        ok = revoke_key(key)
        if ok:
            console.print("[green]Nyckel inaktiverad.[/green]")
        else:
            console.print("[red]Nyckel hittades inte.[/red]")
            raise typer.Exit(1)

    else:
        console.print("[red]Ogiltig action.[/red] Använd: list | create | revoke")


@app.command(name="ingress")
def ingress_cmd(
    action: str = typer.Argument("status", help="status | telegram-once"),
    token: str = typer.Option("", "--token", help="Telegram bot token (eller env NOUSE_TELEGRAM_BOT_TOKEN)"),
    offset: int = typer.Option(0, "--offset", help="Start-offset för Telegram updates"),
    timeout: int = typer.Option(8, "--timeout", help="Long-poll timeout (sek)"),
    limit: int = typer.Option(20, "--limit", help="Antal updates per poll"),
    strict_pairing: bool = typer.Option(True, "--strict-pairing/--open", help="Kräv allowlist/pairing"),
) -> None:
    from nouse.plugins import install_plugin, list_plugins, remove_plugin, update_plugin

    if action == "list":
        rows = list_plugins()
        if not rows:
            console.print("[yellow]Inga plugins laddade.[/yellow]")
            console.print(
                "[dim]Tips: installera en pluginfil via "
                "`nouse plugins install --source /sökväg/plugin.py --name my_plugin`.[/dim]"
            )
            return
        console.print(f"[bold cyan]Plugins ({len(rows)})[/bold cyan]")
        for row in rows:
            console.print(
                f"  {row.get('name')} v{row.get('version')} "
                f"[dim]{row.get('source')}[/dim] {row.get('description', '')}"
            )
        return

    if action == "install":
        if not source:
            console.print("[red]Ange --source för install.[/red]")
            raise typer.Exit(2)
        row = install_plugin(
            source,
            name=name,
            version=version,
            description=description,
        )
        console.print(
            f"[green]Plugin installerad.[/green] name={row.get('name')} "
            f"version={row.get('version')} path={row.get('path')}"
        )
        return

    if action == "remove":
        if not name:
            console.print("[red]Ange --name för remove.[/red]")
            raise typer.Exit(2)
        row = remove_plugin(name)
        console.print(
            f"[yellow]Plugin borttagen.[/yellow] name={row.get('name')} "
            f"file={row.get('removed_file')} registry={row.get('removed_registry')}"
        )
        return

    if action == "update":
        if not name or not source:
            console.print("[red]Ange både --name och --source för update.[/red]")
            raise typer.Exit(2)
        row = update_plugin(
            name,
            source,
            version=version,
            description=description,
        )
        console.print(
            f"[green]Plugin uppdaterad.[/green] name={row.get('name')} "
            f"version={row.get('version')} path={row.get('path')}"
        )
        return

    console.print("[red]Ogiltig action.[/red] Använd: list | install | remove | update")


@app.command(name="doctor")
def doctor_cmd(
    action: str = typer.Argument("check", help="check | fix"),
    stale_run_age_sec: float = typer.Option(
        3600.0,
        "--stale-run-age-sec",
        help="Ålder för att auto-fixa hängande running-sessioner (action=fix)",
    ),
) -> None:
    from datetime import datetime, timezone
    from pathlib import Path
    from nouse.daemon.journal import JOURNAL_DIR, latest_journal_file

    if action == "latest":
        p = latest_journal_file()
        if not p:
            console.print("[yellow]Ingen journal hittad ännu.[/yellow]")
            return
        console.print(f"[bold cyan]Senaste journal:[/bold cyan] {p}")
        console.print(p.read_text(encoding="utf-8", errors="ignore"))
        return

    if action == "today":
        p = JOURNAL_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"
        if not p.exists():
            console.print(f"[yellow]Ingen journal för idag:[/yellow] {p}")
            return
        console.print(f"[bold cyan]Dagens journal:[/bold cyan] {p}")
        console.print(p.read_text(encoding="utf-8", errors="ignore"))
        return

    if action == "tail":
        p = latest_journal_file()
        if not p:
            console.print("[yellow]Ingen journal hittad ännu.[/yellow]")
            return
        all_lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        timeline_idx = [i for i, row in enumerate(all_lines) if row.startswith("- ")]
        if timeline_idx:
            segments: list[str] = []
            for i, start in enumerate(timeline_idx):
                end = timeline_idx[i + 1] if (i + 1) < len(timeline_idx) else len(all_lines)
                block = "\n".join(all_lines[start:end]).strip()
                if block:
                    segments.append(block)
            take = max(1, int(entries))
            tail_segments = segments[-take:]
            if newest_first:
                tail_segments = list(reversed(tail_segments))

            timeline_header_idx = next(
                (i for i, row in enumerate(all_lines) if row.strip() == "## Timeline"),
                None,
            )
            header_lines = all_lines[: timeline_header_idx + 1] if timeline_header_idx is not None else []
            out = []
            if header_lines:
                out.extend(header_lines)
                out.append("")
            out.extend(tail_segments)
            tail = out
        else:
            tail = all_lines[-max(1, lines):]
            if newest_first:
                tail = list(reversed(tail))
        console.print(f"[bold cyan]Journal tail:[/bold cyan] {p}")
        console.print("\n".join(tail))
        return

    if action == "research-tail":
        p = latest_journal_file()
        if not p:
            console.print("[yellow]Ingen journal hittad ännu.[/yellow]")
            return
        events_path = p.with_suffix(".events.jsonl")
        if not events_path.exists():
            console.print(f"[yellow]Ingen research-eventlogg hittad:[/yellow] {events_path}")
            return
        rows = events_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        take = max(1, int(entries))
        tail_rows = rows[-take:]
        if newest_first:
            tail_rows = list(reversed(tail_rows))
        console.print(f"[bold cyan]Research tail:[/bold cyan] {events_path}")
        for row in tail_rows:
            try:
                payload = json.loads(row)
            except Exception:
                console.print(row)
                continue
            console.print_json(data=payload)
        return

    console.print("[red]Ogiltig action.[/red] Använd: latest | today | tail")


@app.command(name="self")
def self_cmd(
    action: str = typer.Argument("status", help="status | set-mission | remember"),
    mission: str = typer.Option("", "--mission", help="Ny mission-text"),
    note: str = typer.Option("", "--note", help="Minnerad att lagra"),
    tags: str = typer.Option("", "--tags", help="Komma-separerade tags för memory"),
    values: str = typer.Option("", "--values", help="Komma-separerad values-lista"),
    personality: str = typer.Option("", "--personality", help="Kort personlighetsprofil"),
    boundaries: str = typer.Option("", "--boundaries", help="Komma-separerade gränser"),
    limit: int = typer.Option(5, "--limit", "-l", help="Antal minnen i status"),
) -> None:
    import json
    from nouse.client import daemon_running, get_output_trace
    from nouse.trace.output_trace import load_events

    safe_limit = max(1, min(limit, 5000))
    if daemon_running():
        events = get_output_trace(trace_id=trace_id, limit=safe_limit).get("events", [])
    else:
        events = load_events(limit=safe_limit, trace_id=trace_id)

    if not events:
        msg = f"Ingen trace hittad för trace_id={trace_id}" if trace_id else "Inga trace-events hittade ännu."
        console.print(f"[yellow]{msg}[/yellow]")
        return

    if as_json:
        console.print(json.dumps(events, ensure_ascii=False, indent=2))
        return

    console.print(
        f"[bold cyan]Output Trace[/bold cyan]  "
        f"events={len(events)}"
        + (f"  [dim]trace_id={trace_id}[/dim]" if trace_id else "")
    )
    for e in events:
        ts = str(e.get("ts", ""))[:19]
        tid = str(e.get("trace_id", ""))[:26]
        ev = e.get("event", "")
        endpoint = e.get("endpoint", "-")
        model = e.get("model")
        payload = e.get("payload") or {}

        summary = ""
        if "query" in payload:
            summary = f" q={str(payload['query'])[:120]}"
        elif "response" in payload:
            summary = f" rsp={str(payload['response'])[:120]}"
        elif "name" in payload:
            summary = f" tool={payload['name']}"
        elif "error" in payload:
            summary = f" err={str(payload['error'])[:120]}"
        elif "added" in payload:
            summary = f" added={payload['added']}"
        attack_plan = payload.get("attack_plan")
        if isinstance(attack_plan, dict):
            qn = len(attack_plan.get("questions") or [])
            cn = len(attack_plan.get("claims") or [])
            an = len(attack_plan.get("assumptions") or [])
            summary += f" plan=Q{qn}/C{cn}/A{an}"

        model_str = f" model={model}" if model else ""
        console.print(
            f"[dim]{ts}[/dim]  [cyan]{tid}[/cyan]  [bold]{ev}[/bold]  "
            f"[dim]{endpoint}{model_str}{summary}[/dim]"
        )


@app.command(name="trace-probe")
def trace_probe_cmd(
    set_path: str = typer.Option(
        "results/eval_set_trace_observability.yaml",
        "--set",
        help="YAML med testproblem för trace-observability",
    ),
    limit: int = typer.Option(8, "--limit", "-l", help="Max antal problem att köra"),
    timeout_sec: float = typer.Option(90.0, "--timeout", help="Timeout per fråga"),
) -> None:
    from nouse.client import daemon_running, get_memory_audit
    from nouse.memory.store import MemoryStore

    safe_limit = max(1, min(limit, 5000))
    if daemon_running():
        try:
            audit = get_memory_audit(limit=safe_limit)
        except Exception:
            console.print(
                "[yellow]Daemon saknar memory-endpoint (äldre version) - kör lokal audit.[/yellow]"
            )
            audit = MemoryStore().audit(limit=safe_limit)
    else:
        audit = MemoryStore().audit(limit=safe_limit)

    console.print(
        f"[bold cyan]Memory Audit[/bold cyan]  "
        f"episodes={int(audit.get('episodes_total', 0) or 0)}  "
        f"unconsolidated={int(audit.get('unconsolidated_total', 0) or 0)}  "
        f"working={int(audit.get('working_items', 0) or 0)}  "
        f"facts={int(audit.get('semantic_facts', 0) or 0)}  "
        f"concepts={int(audit.get('semantic_concepts', 0) or 0)}"
    )

    top_types = audit.get("top_relation_types") or []
    if top_types:
        parts = [f"{r.get('type','?')}={int(r.get('count', 0) or 0)}" for r in top_types[:8]]
        console.print(f"[dim]relation_types:[/dim] {', '.join(parts)}")

    top_sources = audit.get("top_sources") or []
    if top_sources:
        parts = [f"{r.get('source','?')}={int(r.get('count', 0) or 0)}" for r in top_sources[:8]]
        console.print(f"[dim]sources:[/dim] {', '.join(parts)}")

    preview = audit.get("unconsolidated_preview") or []
    for row in preview:
        console.print(
            f"- [yellow]{row.get('id','?')}[/yellow] "
            f"[dim]{row.get('source','?')} · domain={row.get('domain_hint','?')} · "
            f"rels={int(row.get('relation_count', 0) or 0)} · ts={row.get('ts','')}[/dim]"
        )


@app.command(name="consolidation-run")
def consolidation_run_cmd(
    max_episodes: int = typer.Option(
        40,
        "--max-episodes",
        "-m",
        help="Max antal episoder att konsolidera i körningen",
    ),
    strict_min_evidence: float = typer.Option(
        0.65,
        "--min-evidence",
        help="Min evidence-score för strict konsolidering",
    ),
) -> None:
    from nouse.client import daemon_running, get_knowledge_audit
    from nouse.field.surface import FieldSurface

    safe_limit = max(1, min(limit, 5000))
    min_score = max(0.0, min(1.0, float(min_evidence_score)))
    if daemon_running():
        try:
            audit = get_knowledge_audit(
                limit=safe_limit,
                strict=strict,
                min_evidence_score=min_score,
            )
        except Exception:
            console.print(
                "[yellow]Daemon saknar knowledge-endpoint (äldre version) - kör lokal audit.[/yellow]"
            )
            try:
                field = FieldSurface(read_only=True)
                audit = field.knowledge_audit(
                    limit=safe_limit,
                    strict=strict,
                    min_evidence_score=min_score,
                )
            except Exception as e:
                console.print("[red]Kunde inte köra lokal audit.[/red]")
                console.print(f"[dim]{e}[/dim]")
                raise typer.Exit(1)
    else:
        try:
            field = FieldSurface(read_only=True)
            audit = field.knowledge_audit(
                limit=safe_limit,
                strict=strict,
                min_evidence_score=min_score,
            )
        except Exception as e:
            console.print("[red]Kunde inte öppna grafen för audit.[/red]")
            console.print(f"[dim]{e}[/dim]")
            raise typer.Exit(1)

    total = int(audit.get("total_concepts", 0) or 0)
    complete = int(audit.get("complete_nodes", 0) or 0)
    missing_total = int(audit.get("missing_total", 0) or 0)
    cov = audit.get("coverage") or {}
    context_cov = float(cov.get("context", 0.0) or 0.0)
    facts_cov = float(cov.get("facts", 0.0) or 0.0)
    strong_cov = float(cov.get("strong_facts", 0.0) or 0.0)
    complete_cov = float(cov.get("complete", 0.0) or 0.0)
    mode = "strict" if strict else "basic"

    console.print(
        f"[bold cyan]Knowledge Audit[/bold cyan]  total={total}  complete={complete}  missing={missing_total}\n"
        f"[dim]mode={mode} min_evidence_score={min_score:.2f} · "
        f"coverage: context={context_cov:.1%} facts={facts_cov:.1%} "
        f"strong_facts={strong_cov:.1%} complete={complete_cov:.1%}[/dim]"
    )
    missing = audit.get("missing") or []
    if not missing:
        console.print("[green]Alla noder har nu både kontext och fakta.[/green]")
        return
    for row in missing:
        reasons = ",".join(row.get("reasons") or [])
        console.print(
            f"- [yellow]{row.get('name','?')}[/yellow] "
            f"[dim]domain={row.get('domain','?')} reasons={reasons} "
            f"claims={row.get('claims', 0)} evidence={row.get('evidence_refs', 0)}[/dim]"
        )


@app.command(name="knowledge-backfill")
def knowledge_backfill_cmd(
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-l",
        help="Begränsa antal saknade noder att backfilla (default alla)",
    ),
    strict: bool = typer.Option(
        True,
        "--strict/--basic",
        help="Strict backfill fokuserar på noder utan starka fakta.",
    ),
    min_evidence_score: float = typer.Option(
        0.65,
        "--min-evidence-score",
        help="Min score för stark evidens i strict-läge.",
    ),
) -> None:
    # Spåra resoneringskedjan mellan två koncept/domäner. Visar why, styrka och domänövergång per hopp - för att studera hur kopplingarna sitter.
    import asyncio
    from nouse.cli.run_repl import run_repl
    asyncio.run(run_repl(
        model_override=model or None,
        provider_override=provider or None,
        no_learn=no_learn,
        no_context=no_context,
    ))


@app.command(name="companion")
def run_companion(
    topic: str | None = typer.Option(
        None, "--topic", "-t", help="Sätt fokus för sessionen"
    ),
    model: str | None = typer.Option(
        None, "--model", "-m", help="Modell för companion (t.ex. qwen2.5:3b)"
    ),
    profile: str = typer.Option(
        "balanced",
        "--profile",
        "-p",
        help="Companion-profil: fast | balanced | deep",
    ),
) -> None:
        # Kartlägg disken och skapa ett rankat ingest-förslag. (se README)
        pass
