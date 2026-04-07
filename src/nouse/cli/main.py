import importlib.metadata as _meta
import json
import subprocess
import sys
import time
from pathlib import Path
from statistics import mean


import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from nouse.cli.lang import tr

app = typer.Typer(
    name="nouse",
    help="nouse — local multi-agent society on the FNC framework.",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
)

# --- CLI: select-model ---
@app.command("select-model")
def select_model():
    """Välj och spara aktiv LLM-modell (interaktivt)."""
    import runpy
    runpy.run_module("nouse.cli.commands.select_model", run_name="__main__")

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        try:
            version = _meta.version("nouse")
        except _meta.PackageNotFoundError:
            console.print("[red]Error:[/red] nouse package not found. Run `uv sync` to install.")
            raise typer.Exit(code=1)
        console.print(f"nouse version {version}")
        raise typer.Exit()


_REL_ASSUMPTION = {
    "är_analogt_med": "att strukturell analogi är giltig trots semantisk distans",
    "orsakar": "att orsakssambandet inte bara är samvariation",
    "modulerar": "att påverkan ändrar intensitet/riktning utan att vara huvudorsak",
    "reglerar": "att relationen är en återkommande kontrollmekanism",
    "konsoliderar": "att kopplingen förstärks över tid/repetition",
    "stärker": "att effekten ökar styrka eller sannolikhet",
    "försvagar": "att effekten minskar styrka eller sannolikhet",
    "producerar": "att output faktiskt genereras från källan",
    "är_del_av": "att målet är en stabil överordnad struktur",
    "synkroniserar": "att kopplingen sker tidsmässigt koordinerat",
    "oscillerar": "att mönstret är cykliskt och inte slumpmässigt",
    "beskriver": "att relationen är representativ och inte bara retorisk",
}


def _avg_strength(path: list[dict]) -> float:
    vals = [float(s.get("strength", 0.0)) for s in path]
    return mean(vals) if vals else 0.0


def _best_minimal_path(paths: list[list[dict]]) -> list[dict]:
    """
    Minsta möjliga koppling:
    1) kortast kedja
    2) högst medelstyrka
    """
    return min(paths, key=lambda p: (len(p), -_avg_strength(p)))


def _edge_assumptions(step: dict) -> list[str]:
    rel = (step.get("rel_type") or "").strip()
    why = (step.get("why") or "").strip()
    src_dom = step.get("src_domain") or "okänd"
    tgt_dom = step.get("tgt_domain") or "okänd"
    rel_assumption = _REL_ASSUMPTION.get(
        rel, "att relationstypen uttrycker ett verkligt mönster i datan"
    )

    assumptions = [
        f"Källnoden tolkas korrekt i domänen '{src_dom}'.",
        f"Målnoden tolkas korrekt i domänen '{tgt_dom}'.",
        f"Relationen '{rel}' antas hålla: {rel_assumption}.",
    ]
    if why:
        assumptions.append(f"Motiveringen antas bära evidens: \"{why[:120]}\".")
    else:
        assumptions.append("Ingen explicit motivering finns; antagandet är därför svagare.")

    ev = step.get("evidence_score")
    if ev is not None:
        assumptions.append(f"Kantens evidence_score antas vara korrekt skattad ({float(ev):.2f}).")
    af = step.get("assumption_flag")
    if af is not None:
        assumptions.append(
            "Kanten är markerad som antagande." if bool(af) else "Kanten är markerad som evidensstödd."
        )
    return assumptions



    try:
        version = _meta.version("nouse")
    except _meta.PackageNotFoundError:
        version = "?"

    console.print(
        Panel(
            f"[bold cyan]νοῦς  v{version}[/bold cyan]\n"
            "Epistemic grounding substrate for LLMs",
            title=tr("front_title"),
            border_style="cyan",
        )
    )

    # --- Start ---
    t = Table(show_header=True, header_style="bold", title=f"🚀 {tr('start')}", title_style="bold cyan")
    t.add_column(tr("command"), style="green", no_wrap=True)
    t.add_column(tr("description"))
    t.add_row("nouse start me", "Direct chat with the brain (operator focus)" if tr("start") == "Start" else "Direkt samtal med hjärnan (operatörsfokus)")
    t.add_row("nouse start research", "Dashboard + observability (scorecard, traces, metrics)" if tr("start") == "Start" else "Dashboard + observabilitet (scorecard, traces, metrics)")
    t.add_row("nouse start autonomy", "Ingress/autonomy mode (Clawbot, system-events, wake)" if tr("start") == "Start" else "Ingress/autonomi-läge (Clawbot, system-events, wake)")
    t.add_row("nouse daemon start|web|status", "Brain loop — listens to all sources, updates the graph" if tr("start") == "Start" else "Brain loop — lyssnar på alla källor, uppdaterar grafen")
    t.add_row("nouse web", "Realtime dashboard (also starts daemon)" if tr("start") == "Start" else "Realtids-dashboard (startar även daemon)")
    console.print(t)

    # --- Conversation ---
    t = Table(show_header=True, header_style="bold", title=f"💬 {tr('conversation')}", title_style="bold cyan")
    t.add_column(tr("command"), style="green", no_wrap=True)
    t.add_column(tr("description"))
    t.add_row("nouse chat  / i", "Agent chat with tool-calling + graph growth" if tr("conversation") == "Conversation" else "Agent-chat med tool-calling + grafväxt")
    t.add_row("nouse run", "LLM-agnostic REPL (Ollama, Claude, OpenAI, Copilot)")
    t.add_row("nouse ask 'question'", "Quick one-shot question" if tr("conversation") == "Conversation" else "Snabb one-shot fråga")
    t.add_row("nouse snabbchat", "Lightweight read-only chat" if tr("conversation") == "Conversation" else "Lättviktig read-only chat")
    t.add_row("nouse companion", "Dialogue mode — idea exchange and relationship building" if tr("conversation") == "Conversation" else "Samtalsläge — idéutbyte och relationsbyggande")
    console.print(t)

    # --- Knowledge & Learning ---
    t = Table(show_header=True, header_style="bold", title=f"📚 {tr('knowledge')}", title_style="bold cyan")
    t.add_column(tr("command"), style="green", no_wrap=True)
    t.add_column(tr("description"))
    t.add_row("nouse ingest", "Ingest file or text directly into the graph" if tr("knowledge") == "Knowledge & Learning" else "Mata in fil eller text direkt i grafen")
    t.add_row("nouse learn-from", "Learn from YouTube, web, PDF or local file/folder" if tr("knowledge") == "Knowledge & Learning" else "Lär från YouTube, webb, PDF eller lokal fil/katalog")
    t.add_row("nouse scan-disk", "Scan disk → ranked ingest suggestion" if tr("knowledge") == "Knowledge & Learning" else "Kartlägg disk → rankat ingest-förslag")
    t.add_row("nouse enrich-nodes", "Enrich nodes missing context (LLM-generated)" if tr("knowledge") == "Knowledge & Learning" else "Berika noder som saknar kontext (LLM-genererat)")
    t.add_row("nouse enrich", "Enrich isolated nodes via frontier LLM" if tr("knowledge") == "Knowledge & Learning" else "Berika isolerade noder via frontier LLM")
    t.add_row("nouse knowledge-backfill", "Fill missing node profiles (context + facts)" if tr("knowledge") == "Knowledge & Learning" else "Fyll saknade nodprofiler (kontext + fakta)")
    t.add_row("nouse deepdive", "Axiom-discovery: deep analysis of nodes in the graph" if tr("knowledge") == "Knowledge & Learning" else "Axiom-discovery: djupanalys av noder i grafen")
    t.add_row("nouse consolidation-run", "Manual consolidation episodic → semantic memory" if tr("knowledge") == "Knowledge & Learning" else "Manuell konsolidering episodiskt → semantiskt minne")
    t.add_row("nouse nightrun", "NightRun — consolidation of working memory to FieldSurface" if tr("knowledge") == "Knowledge & Learning" else "NightRun — konsolidering av arbetsminne till FieldSurface")
    console.print(t)

    # --- Exploration & Discovery ---
    t = Table(show_header=True, header_style="bold", title=f"🔍 {tr('exploration')}", title_style="bold cyan")
    t.add_column(tr("command"), style="green", no_wrap=True)
    t.add_column(tr("description"))
    t.add_row("nouse nerv", "Shortest nerve path between two domains" if tr("exploration") == "Exploration & Discovery" else "Kortaste nervbana mellan två domäner")
    t.add_row("nouse trace", "Reasoning chain between concepts/domains" if tr("exploration") == "Exploration & Discovery" else "Resoneringskedja mellan koncept/domäner")
    t.add_row("nouse bisoc", "Bisociation candidates via TDA (topological analysis)" if tr("exploration") == "Exploration & Discovery" else "Bisociationskandidater via TDA (topologisk analys)")
    t.add_row("nouse bridge", "Latent structural bridges between concepts" if tr("exploration") == "Exploration & Discovery" else "Latenta strukturella bryggor mellan koncept")
    t.add_row("nouse cascade", "Compound idea synthesis: 1+1=3+1=5+1=9..." if tr("exploration") == "Exploration & Discovery" else "Kompounderad idésyntes: 1+1=3+1=5+1=9...")
    t.add_row("nouse embed-search", "Semantic search in local embedding index" if tr("exploration") == "Exploration & Discovery" else "Semantisk sökning i lokal embedding-index")
    t.add_row("nouse embed-index", "Build/extend local embedding index" if tr("exploration") == "Exploration & Discovery" else "Bygg/utöka lokal embedding-index")
    t.add_row("nouse eval-embed", "Quick hit@k-eval on embedding index" if tr("exploration") == "Exploration & Discovery" else "Snabb hit@k-eval på embedding-index")
    t.add_row("nouse visualize", "Interactive HTML graph of the knowledge graph" if tr("exploration") == "Exploration & Discovery" else "Interaktiv HTML-graf av kunskapsgrafen")
    console.print(t)

    # --- Diagnostics ---
    t = Table(show_header=True, header_style="bold", title=f"🧠 {tr('diagnostics')}", title_style="bold cyan")
    t.add_column(tr("command"), style="green", no_wrap=True)
    t.add_column(tr("description"))
    t.add_row("nouse brain state|health|gap|metrics|live", "Direct insight into brain-db-core" if tr("diagnostics") == "Brain State & Diagnostics" else "Direkt insyn i brain-db-core")
    t.add_row("nouse limbic", "Limbic state (DA/NA/ACh/λ/arousal)" if tr("diagnostics") == "Brain State & Diagnostics" else "Limbiskt tillstånd (DA/NA/ACh/λ/arousal)")
    t.add_row("nouse snapshot", "Research dump of the entire brain state" if tr("diagnostics") == "Brain State & Diagnostics" else "Forsknings-dump av hela hjärnans tillstånd")
    t.add_row("nouse memory-audit", "Status of episodic/semantic memory" if tr("diagnostics") == "Brain State & Diagnostics" else "Status för episodiskt/semantiskt minne")
    t.add_row("nouse knowledge-audit", "Check that nodes have context + facts" if tr("diagnostics") == "Brain State & Diagnostics" else "Kontrollera att noder har kontext + fakta")
    t.add_row("nouse doctor", "Diagnostics + safe auto-fixes" if tr("diagnostics") == "Brain State & Diagnostics" else "Driftdiagnostik + säkra auto-fixar")
    t.add_row("nouse output-trace", "Output trace (question → attack → tool → answer)" if tr("diagnostics") == "Brain State & Diagnostics" else "Output-trace (fråga → angrepp → verktyg → svar)")
    t.add_row("nouse trace-probe", "Run problem set and verify trace chain" if tr("diagnostics") == "Brain State & Diagnostics" else "Kör problemset och verifiera tracekedjan")
    console.print(t)

    # --- Autonomy & Research ---
    t = Table(show_header=True, header_style="bold", title=f"🤖 {tr('autonomy')}", title_style="bold cyan")
    t.add_column(tr("command"), style="green", no_wrap=True)
    t.add_column(tr("description"))
    t.add_row("nouse autonomous", "Autonomous mode — discover and add new knowledge" if tr("autonomy") == "Autonomy & Research" else "Autonomt läge — upptäck och lägg till ny kunskap")
    t.add_row("nouse kickstart", "Seed agent/subagent-tasks + wake autonomous loop" if tr("autonomy") == "Autonomy & Research" else "Seeda agent/subagent-tasks + väck autonom loop")
    t.add_row("nouse research-queue", "Inspect/run gap-based research queue" if tr("autonomy") == "Autonomy & Research" else "Inspektera/kör gap-baserad research-queue")
    t.add_row("nouse mission", "Global mission for autonomous direction + measurement" if tr("autonomy") == "Autonomy & Research" else "Global mission för autonom riktning + mätning")
    t.add_row("nouse hitl", "HITL interrupts (pause/approve/reject)" if tr("autonomy") == "Autonomy & Research" else "HITL-interrupts (pause/approve/reject)")
    t.add_row("nouse wake", "Wake/system-events (autonomous trigger bus)" if tr("autonomy") == "Autonomy & Research" else "Wake/system-events (autonom triggerbuss)")
    console.print(t)

    # --- Identity & Self ---
    t = Table(show_header=True, header_style="bold", title=f"🪞 {tr('identity')}", title_style="bold cyan")
    t.add_column(tr("command"), style="green", no_wrap=True)
    t.add_column(tr("description"))
    t.add_row("nouse self", "Continuous identity + memories + drives" if tr("identity") == "Identity & Self" else "Kontinuerlig identitet + minnen + drivkrafter")
    t.add_row("nouse journal", "Daily journal (self-development + open questions)" if tr("identity") == "Identity & Self" else "Daglig journal (självutveckling + öppna frågor)")
    console.print(t)

    # --- Integration & Ingress ---
    t = Table(show_header=True, header_style="bold", title=f"🔌 {tr('integration')}", title_style="bold cyan")
    t.add_column(tr("command"), style="green", no_wrap=True)
    t.add_column(tr("description"))
    t.add_row("nouse mcp serve", "MCP server (stdio) for Copilot/OpenClaw" if tr("integration") == "Integration & Ingress" else "MCP-server (stdio) för Copilot/OpenClaw")
    t.add_row("nouse clawbot", "Clawbot bridge (status/allowlist/approve/ingest)" if tr("integration") == "Integration & Ingress" else "Clawbot bridge (status/allowlist/approve/ingest)")
    t.add_row("nouse ingress", "Ingress adapter layer (Telegram etc.)" if tr("integration") == "Integration & Ingress" else "Ingress-adapterlager (Telegram m.fl.)")
    t.add_row("nouse allowlist", "Pairing/allowlist for external ingress" if tr("integration") == "Integration & Ingress" else "Pairing/allowlist för extern ingress")
    t.add_row("nouse plugins", "Skill/plugin lifecycle with version tracking" if tr("integration") == "Integration & Ingress" else "Skill/plugin-livscykel med versionsspårning")
    console.print(t)

    # --- Configuration ---
    t = Table(show_header=True, header_style="bold", title=f"⚙️  {tr('config')}", title_style="bold cyan")
    t.add_column(tr("command"), style="green", no_wrap=True)
    t.add_column(tr("description"))
    t.add_row("nouse setup", "Configure storage profile (small/medium/large)" if tr("config") == "Configuration" else "Konfigurera lagringsprofil (small/medium/large)")
    t.add_row("nouse llm", "Manage LLM providers — auto-detect & configure" if tr("config") == "Configuration" else "Hantera LLM-providers — auto-detect & konfigurera")
    t.add_row("nouse models", "Model failover policy per task type" if tr("config") == "Configuration" else "Modell-failover policy per tasktyp")
    t.add_row("nouse select-model", "Select and save active LLM model (interactive)" if tr("config") == "Configuration" else "Välj och spara aktiv LLM-modell (interaktivt)")
    t.add_row("nouse session", "Session layer (lifecycle + runs + energy)" if tr("config") == "Configuration" else "Sessionslager (lifecycle + runs + energi)")
    t.add_row("nouse usage", "Usage/cost telemetry per run/model/session" if tr("config") == "Configuration" else "Usage/cost-telemetri per run/modell/session")
    console.print(t)

    console.print(f"\n[dim]{tr('quickstart')}[/dim]")


def _ensure_daemon_background(*, web_port: int = 8765, wait_sec: float = 8.0) -> bool:
    from nouse.client import daemon_running

    if daemon_running():
        return True
    cmd = [sys.executable, "-m", "nouse.cli.main", "daemon", "web", "--port", str(web_port)]
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        return False

    deadline = time.time() + max(1.0, float(wait_sec))
    while time.time() < deadline:
        if daemon_running():
            return True
        time.sleep(0.25)
    return daemon_running()


@app.command()
def daemon(
    action: str = typer.Argument("start", help="start | status | web"),
    port:   int = typer.Option(8765, "--port", "-p", help="Webb-port (med 'web')"),
) -> None:
    """Starta brain loop — lyssnar på alla källor och uppdaterar grafen."""
    from nouse.client import daemon_running, get_status

    def _print_already_running() -> None:
        try:
            s = get_status()
            console.print(
                "[yellow]nouse daemon verkar redan vara igång.[/yellow]  "
                f"[dim]{s.get('concepts', '?')} koncept · {s.get('relations', '?')} relationer[/dim]"
            )
        except Exception:
            console.print("[yellow]nouse daemon verkar redan vara igång.[/yellow]")

    def _run_or_explain(*, with_web: bool = False, web_port: int = 8765) -> None:
        from nouse.daemon.main import run

        try:
            run(with_web=with_web, web_port=web_port)
        except RuntimeError as e:
            msg = str(e)
            if "Could not set lock on file" in msg:
                if daemon_running():
                    _print_already_running()
                    console.print(
                        "[dim]Tips: använd `nouse daemon status` eller anslut med `nouse chat`.[/dim]"
                    )
                else:
                    console.print(
                        "[red]Kunde inte starta daemon: databasen är låst av en annan process.[/red]"
                    )
                    try:
                        import subprocess
                        from pathlib import Path

                        db_path = str(Path.home() / ".local" / "share" / "nouse" / "field.sqlite")
                        raw = subprocess.check_output(["lsof", "-t", db_path], text=True).strip()
                        pids = [pid for pid in raw.splitlines() if pid.strip()]
                    except Exception:
                        pids = []

                    if pids:
                        console.print(
                            f"[dim]Lås hålls av PID: {', '.join(pids[:8])}. Stoppa dem och prova igen.[/dim]"
                        )
                    else:
                        console.print(
                            "[dim]Stäng processen som håller låset och prova igen.[/dim]"
                        )
                raise typer.Exit(1)
            raise

    if action == "start":
        if daemon_running():
            _print_already_running()
            return
        console.print("[green]Startar nouse brain loop...[/green]")
        _run_or_explain()
    elif action == "web":
        if daemon_running():
            _print_already_running()
            console.print(f"[bold cyan]http://127.0.0.1:{port}[/bold cyan]")
            return
        console.print(f"[green]Startar brain loop + web-UI på port {port}...[/green]")
        console.print(f"[bold cyan]http://127.0.0.1:{port}[/bold cyan]")
        _run_or_explain(with_web=True, web_port=port)
    elif action == "status":
        if daemon_running():
            s = get_status()
            console.print(f"Graf:    [cyan]{s['concepts']}[/cyan] koncept · "
                          f"[cyan]{s['relations']}[/cyan] relationer")
            console.print(f"Domäner: [dim]{', '.join(s['domains'][:8])}{'…' if len(s['domains'])>8 else ''}[/dim]")
            console.print(f"Limbic:  λ={s['lambda']}  DA={s['dopamine']}  "
                          f"NA={s['noradrenaline']}  arousal={s['arousal']}  cykel={s['cycle']}")
        else:
            console.print("[yellow]Daemon ej igång[/yellow]")


@app.command(name="status")
def status() -> None:
    """Show graph stats, memory breakdown, daemon health, and last activity."""
    from nouse.cli.commands.status import run_status

    run_status()


@app.command(name="relay")
def relay_cmd(
    action: str = typer.Argument("list", help="open | list | show | continue | update | close"),
    args: list[str] = typer.Argument(default=None),
) -> None:
    """Cross-model session relay — hand off work between any models."""
    from nouse.cli.commands.relay import app as relay_app
    import sys
    sys.argv = ["nouse", "relay", action] + (args or [])
    relay_app()


@app.command(name="mcp")
def mcp_cmd(
    action: str = typer.Argument("serve", help="serve"),
) -> None:
    """Starta nouse MCP-server (stdio) för externa klienter som Copilot/OpenClaw."""
    if action != "serve":
        console.print("[red]Endast 'serve' stöds just nu.[/red]")
        raise typer.Exit(code=1)
    try:
        from nouse.mcp_gateway.server import run_stdio

        run_stdio()
    except Exception as e:
        console.print(f"[red]Kunde inte starta MCP-server:[/red] {e}")
        console.print("[dim]Tips: installera MCP-stöd i miljön, t.ex. `pip install mcp`.[/dim]")
        raise typer.Exit(code=1)


@app.command(name="start")
def start_mode(
    mode: str = typer.Argument("me", help="me | research | autonomy"),
    web_port: int = typer.Option(8765, "--web-port", help="Port för web UI"),
    session_id: str = typer.Option("me", "--session-id", "-s", help="Session för me-läge"),
    open_browser: bool = typer.Option(True, "--open-browser/--no-open-browser"),
) -> None:
    """Enkel en-väg-in till rätt arbetsläge."""
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
        console.print("[yellow]Daemon ej igång — startar web cockpit...[/yellow]")
        daemon(action="web", port=web_port)
        return

    if not daemon_running():
        console.print("[yellow]Daemon ej igång — försöker starta i bakgrunden...[/yellow]")
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
    """Prata direkt med brain-db-core (port 7676)."""
    from nouse.client import (
        BRAIN_DB_BASE,
        brain_db_running,
        brain_get_gap_map,
        brain_get_health,
        brain_get_live,
        brain_get_metrics,
        brain_get_state,
        brain_save,
        brain_step,
    )

    act = action.strip().lower()
    if act == "status":
        if not brain_db_running():
            console.print(f"[yellow]brain-db-core ej nåbar på {BRAIN_DB_BASE}[/yellow]")
            raise typer.Exit(1)
        health = brain_get_health()
        rt = health.get("runtime") or {}
        console.print(
            f"[green]brain-db-core online[/green] {BRAIN_DB_BASE}  "
            f"[dim]cycle={rt.get('cycle','?')} nodes={rt.get('nodes','?')} "
            f"edges={rt.get('edges','?')} crystallized={rt.get('crystallized_edges','?')}[/dim]"
        )
        return

    if act == "health":
        console.print_json(data=brain_get_health())
        return
    if act == "state":
        console.print_json(data=brain_get_state())
        return
    if act in {"gap", "gap_map"}:
        console.print_json(data=brain_get_gap_map())
        return
    if act == "metrics":
        console.print_json(data=brain_get_metrics(last_n=last_n))
        return
    if act == "live":
        console.print_json(data=brain_get_live(limit_nodes=limit_nodes, limit_edges=limit_edges))
        return
    if act == "save":
        console.print_json(data=brain_save())
        return
    if act == "step":
        events: list[dict]
        if events_json.strip():
            try:
                parsed = json.loads(events_json)
            except json.JSONDecodeError as e:
                console.print(f"[red]Ogiltig --events-json:[/red] {e}")
                raise typer.Exit(1)
            if not isinstance(parsed, list):
                console.print("[red]--events-json måste vara en JSON-lista.[/red]")
                raise typer.Exit(1)
            events = [row for row in parsed if isinstance(row, dict)]
        else:
            events = []
        console.print_json(data=brain_step(events=events))
        return

    console.print(
        "[red]Okänd action.[/red] Använd: status | health | state | gap | metrics | live | step | save"
    )
    raise typer.Exit(1)


@app.command(name="clawbot")
def clawbot_bridge(
    action: str = typer.Argument("status", help="status | allowlist | approve | ingest"),
    channel: str = typer.Option("default", "--channel", "-c", help="Clawbot-kanal"),
    actor_id: str = typer.Option("", "--actor-id", "-a", help="Avsändar-id i Clawbot"),
    text: str = typer.Option("", "--text", "-t", help="Meddelande att skicka in"),
    code: str = typer.Option("", "--code", help="Pairing-kod för approve"),
    mode: str = typer.Option("now", "--mode", help="now | next-heartbeat"),
    strict_pairing: bool = typer.Option(True, "--strict-pairing/--no-strict-pairing"),
) -> None:
    """Clawbot bridge till nouse-daemonens ingress/autonomi."""
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
    """Interagera med hjärnan via grafen (agent-chat med tool-calling)."""
    from nouse.client import daemon_running
    if daemon_running():
        _chat_via_api(session_id=session_id, show_background=show_background)
    else:
        import asyncio
        from nouse.cli.chat import chat_loop
        asyncio.run(chat_loop(session_id=session_id))


@app.command(name="interact")
def interact_alias(
    session_id: str = typer.Option("main", "--session-id", "-s", help="Session-id för interaktion"),
    show_background: bool = typer.Option(
        False,
        "--show-background/--hide-background",
        help="Visa/dölj interna tool-spår under interaktion.",
    ),
) -> None:
    """Alias för att starta interaktion med hjärnan."""
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
    """Kortalias för interaktion: `nouse i`."""
    chat(session_id=session_id, show_background=show_background)


def _chat_via_api(*, session_id: str = "main", show_background: bool = False) -> None:
    """Terminal-chat som streamer mot daemon-API:et."""
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
    """Ställ en snabb, enkel fråga till hjärnan."""
    import asyncio
    from nouse.cli.ask import ask_brain
    asyncio.run(ask_brain(question, chat_mode=False, session_id=session_id))


@app.command()
def snabbchat(
    session_id: str = typer.Option("main", "--session-id", "-s", help="Session-id för snabbchat"),
) -> None:
    """Lättviktig chatt — Blixtsnabb, enbart text och read-only KuzuDB."""
    import asyncio
    from nouse.cli.ask import ask_brain
    try:
        asyncio.run(ask_brain("", chat_mode=True, session_id=session_id))
    except KeyboardInterrupt:
        console.print("\n[dim]Avslutar snabbchatt.[/dim]")

@app.command()
def web(port: int = typer.Option(8765, "--port", "-p")) -> None:
    """Starta den interaktiva realtids-dashboardappen (Startar även B76 Hjärnan!)."""
    import socket
    import subprocess
    from nouse.web.server import start_server

    # Kolla om daemonen redan kör web-UI på porten
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        already_running = s.connect_ex(("127.0.0.1", port)) == 0

    if already_running:
        url = f"http://127.0.0.1:{port}"
        console.print(f"[bold yellow]⚡ Daemonen kör redan web-UI på port {port}[/bold yellow]")
        console.print(f"[bold cyan]Öppnar: {url}[/bold cyan]")
        try:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        raise typer.Exit(0)

    console.print(f"[bold magenta]▶ Web-UI Master Control startad[/bold magenta]")
    console.print(f"[dim]Dashboarden är nu hjärnan! Den kör metakognition, nyfikenhetsloopen och web-gränssnittet asynkront.[/dim]")
    console.print(f"[bold cyan]Länk: http://127.0.0.1:{port}[/bold cyan]")
    try:
        subprocess.Popen(["xdg-open", f"http://127.0.0.1:{port}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    start_server(port=port)


@app.command()
def ingest(
    path: str = typer.Argument(..., help="Fil eller URL att mata in i grafen"),
) -> None:
    """Mata in en fil eller text direkt i grafen."""
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
    """Lär in från YouTube, webbartikel, PDF-URL eller lokal fil/katalog."""
    import asyncio
    from pathlib import Path

    from nouse.daemon.extractor import extract_relations
    from nouse.daemon.web_text import extract_text_from_url, is_url
    from nouse.field.surface import FieldSurface

    if not is_url(source):
        p = Path(source).expanduser()
        if not p.exists():
            console.print(f"[red]Hittade inte: {source}[/red]")
            raise typer.Exit(1)
        ingest(str(p))
        return

    try:
        text, meta = extract_text_from_url(source)
    except Exception as e:
        console.print(f"[red]Kunde inte läsa URL:[/red] {e}")
        raise typer.Exit(1)

    if len(text.strip()) < 80:
        console.print("[yellow]För lite text extraherades från källan.[/yellow]")
        raise typer.Exit(1)

    source_tag = str(meta.get("source", "learn_from"))
    extract_reason = str(meta.get("extract_reason") or "")

    if debug_extract:
        console.print(
            f"[dim]debug_extract: source={source_tag} · reason={extract_reason or '-'} · chars={len(text)}[/dim]"
        )

    async def _run_db() -> tuple[int, dict]:
        field = FieldSurface()
        rels = await extract_relations(text, {
            "path": source,
            "source": source_tag,
            "extract_models": "minimax-m2.7:cloud,deepseek-r1:1.5b",
            "extract_timeout_sec": 75.0,
        })
        for r in rels:
            field.add_concept(r["src"], r["domain_src"], source=source_tag)
            field.add_concept(r["tgt"], r["domain_tgt"], source=source_tag)
            field.add_relation(
                r["src"],
                r["type"],
                r["tgt"],
                why=r.get("why", ""),
                source_tag=source_tag,
            )
        return len(rels), field.stats()

    try:
        added, stats = asyncio.run(_run_db())
        console.print(
            f"[green]learn-from klart.[/green] +{added} relationer från {source}\n"
            f"[dim]Källa: {source_tag} · Graf: {stats}[/dim]"
        )
        if source_tag == "youtube_meta":
            reason_txt = extract_reason or "okänd"
            console.print(
                f"[yellow]YouTube transcript saknas — låg på metadata-nivå.[/yellow] [dim]reason={reason_txt}[/dim]"
            )
        return
    except RuntimeError as e:
        msg = str(e)
        if "Could not set lock on file" not in msg:
            raise

    # Fallback när Kuzu är låst: skicka till daemon API eller köa lokalt.
    try:
        import httpx
        from nouse.client import DAEMON_BASE, daemon_running

        if daemon_running():
            r = httpx.post(
                f"{DAEMON_BASE}/api/ingest",
                json={"text": text, "source": source_tag},
                timeout=60.0,
            )
            r.raise_for_status()
            data = r.json()
            console.print(
                f"[green]learn-from klart via daemon.[/green] +{data.get('added', 0)} relationer från {source}\n"
                f"[dim]Källa: {source_tag} · mode=api_ingest[/dim]"
            )
            if source_tag == "youtube_meta":
                reason_txt = extract_reason or "okänd"
                console.print(
                    f"[yellow]YouTube transcript saknas — låg på metadata-nivå.[/yellow] [dim]reason={reason_txt}[/dim]"
                )
            return
    except Exception:
        pass

    from datetime import datetime, timezone
    from pathlib import Path as _Path
    qdir = _Path.home() / ".local" / "share" / "nouse" / "capture_queue"
    qdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    queued = qdir / f"learn_from_{ts}.txt"
    queued.write_text(text, encoding="utf-8")
    console.print(
        f"[yellow]DB låst och daemon ej nåbar. Köade text för senare ingest.[/yellow] {queued}"
    )


@app.command(name="embed-index")
def embed_index(
    path: str = typer.Argument(..., help="Katalog eller fil att indexera för embeddings"),
    batch: int = typer.Option(16, "--batch", help="Batchstorlek för embedding-anrop"),
    max_chars: int = typer.Option(1400, "--max-chars", help="Max tecken per chunk"),
    overlap_chars: int = typer.Option(200, "--overlap", help="Överlapp mellan chunks"),
) -> None:
    """Bygg/utöka lokal embedding-index från filer."""
    from pathlib import Path

    from nouse.daemon.file_text import extract_text
    from nouse.daemon.sources import DEFAULT_INGEST_EXTENSIONS, iter_ingest_files
    from nouse.embeddings.chunking import chunk_text
    from nouse.embeddings.index import JsonlVectorIndex, make_chunk_record
    from nouse.embeddings.ollama_embed import OllamaEmbedder

    src = Path(path).expanduser()
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

    chunk_rows: list[dict] = []
    for f in files:
        try:
            txt = extract_text(f)
        except Exception:
            continue
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
    """Semantisk sök i lokal embedding-index."""
    from nouse.embeddings.index import search_index
    from nouse.embeddings.ollama_embed import OllamaEmbedder

    embedder = OllamaEmbedder()
    qv = embedder.embed_texts([query])[0]
    hits = search_index(query_vector=qv, top_k=top_k)
    if not hits:
        console.print("[yellow]Inga träffar i embedding-index ännu.[/yellow]")
        return

    console.print(f"[bold]Top {len(hits)} embedding-träffar[/bold]")
    for h in hits:
        snippet = (h.text or "").replace("\n", " ")[:220]
        console.print(
            f"- [cyan]{h.score:.3f}[/cyan] {h.path}#chunk{h.chunk_ix}\n"
            f"  [dim]{snippet}[/dim]"
        )


@app.command(name="eval-embed")
def eval_embed(
    set_path: str = typer.Option(
        "results/eval_set_papers_top5.yaml",
        "--set",
        help="YAML med queries + expected_top5"
    ),
    top_k: int = typer.Option(5, "--top-k", help="Top-k för träffmätning"),
) -> None:
    """Kör snabb hit@k-eval på embedding-index."""
    from pathlib import Path

    from ruamel.yaml import YAML

    from nouse.embeddings.index import search_index
    from nouse.embeddings.ollama_embed import OllamaEmbedder

    pset = Path(set_path).expanduser()
    if not pset.exists():
        console.print(f"[red]Eval-set saknas:[/red] {pset}")
        raise typer.Exit(1)

    yaml = YAML(typ="safe")
    data = yaml.load(pset.read_text(encoding="utf-8", errors="ignore")) or {}
    queries = data.get("queries") or []
    if not queries:
        console.print("[red]Inga queries i eval-set.[/red]")
        raise typer.Exit(1)

    embedder = OllamaEmbedder()

    hits_total = 0
    for item in queries:
        q = str(item.get("query") or "").strip()
        expected = [str(x).lower() for x in (item.get("expected_top5") or [])]
        if not q:
            continue

        qv = embedder.embed_texts([q])[0]
        got = search_index(query_vector=qv, top_k=top_k)
        corpus = "\n".join((f"{h.path} {h.text}").lower() for h in got)
        ok = any(e and e in corpus for e in expected)
        hits_total += 1 if ok else 0
        icon = "✓" if ok else "✗"
        console.print(f"{icon} {item.get('id','?')}: {q[:90]}")

    total = len(queries)
    ratio = hits_total / max(1, total)
    console.print(
        f"\n[bold]Eval klar[/bold]  hit@{top_k} = "
        f"[cyan]{hits_total}/{total} ({ratio:.1%})[/cyan]"
    )


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
    """Generera interaktiv HTML-graf av kunskapsgrafen."""
    from nouse.client import get_graph
    from nouse.cli.viz import build_html, build_html_from_data
    from nouse.field.surface import FieldSurface

    try:
        field = FieldSurface(read_only=True)
        path_out = build_html(
            field,
            output,
            domain=domain,
            min_strength=min_strength,
            max_nodes=max_nodes,
        )
    except Exception as e:
        msg = str(e)
        if "Could not set lock on file" in msg:
            try:
                data = get_graph(limit=max_nodes)
                path_out = build_html_from_data(
                    data,
                    output,
                    domain=domain,
                    min_strength=min_strength,
                )
                console.print("[yellow]DB låst lokalt — använder daemon-grafen.[/yellow]")
            except Exception as api_e:
                console.print(
                    "[red]Kunde inte visualisera: DB är låst och daemon-API svarar inte.[/red]"
                )
                console.print(f"[dim]{api_e}[/dim]")
                raise typer.Exit(1)
        else:
            console.print(f"[red]Kunde inte visualisera grafen:[/red] {e}")
            raise typer.Exit(1)

    console.print(f"[green]Graf sparad:[/green] {path_out}")
    import subprocess
    try:
        subprocess.Popen(["xdg-open", path_out],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


@app.command()
def nerv(
    domain_a: str = typer.Argument(..., help="Startdomän"),
    domain_b: str = typer.Argument(..., help="Måldomän"),
    max_hops: int = typer.Option(8, "--hops"),
) -> None:
    """Hitta kortaste nervbana mellan två domäner."""
    from nouse.client import daemon_running, get_nerv
    if daemon_running():
        result = get_nerv(domain_a, domain_b, max_hops=max_hops)
        if not result.get("found"):
            console.print(f"[red]Ingen stig hittad: {domain_a} → {domain_b}[/red]")
            raise typer.Exit(1)
        console.print(f"\n[bold]Nervbana[/bold] {domain_a} → {domain_b}  "
                      f"[cyan]novelty={result['novelty']:.1f}[/cyan]\n")
        for step in result["path"]:
            console.print(f"  [yellow]{step['from']}[/yellow] —[{step['rel']}]→ [green]{step['to']}[/green]")
    else:
        from nouse.field.surface import FieldSurface
        field = FieldSurface(read_only=False)
        path = field.find_path(domain_a, domain_b, max_hops=max_hops)
        if not path:
            console.print(f"[red]Ingen stig: {domain_a} → {domain_b}[/red]")
            raise typer.Exit(1)
        novelty = field.path_novelty(path)
        console.print(f"\n[bold]Nervbana[/bold] {domain_a} → {domain_b}  "
                      f"[cyan]novelty={novelty:.1f}[/cyan]\n")
        for src, rel, tgt in path:
            console.print(f"  [yellow]{src}[/yellow] —[{rel}]→ [green]{tgt}[/green]")


@app.command()
def bisoc(
    tau: float = typer.Option(0.55, "--tau", "-t",
                              help="Min topologisk similaritet (0-1)"),
    epsilon: float = typer.Option(2.0, "--epsilon", "-e",
                                  help="Vietoris-Rips epsilon"),
    limit: int = typer.Option(50, "--limit", "-l",
                              help="Max antal domäner att analysera (top-N efter storlek)"),
) -> None:
    """
    Hitta bisociationskandidater via TDA (Topologisk Dataanalys).

    Domänpar med hög strukturell likhet (τ) men ingen semantisk länk —
    det är där 1+1=3-potentialen är störst (Koestler 1964).
    """
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
        console.print("[dim]Inga kandidater — lägg till fler domäner först.[/dim]")
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
    """Visa aktuellt limbiskt tillstånd (DA/NA/ACh/λ/arousal)."""
    from nouse.limbic.signals import load_state
    s = load_state()
    console.print(f"\n[bold cyan]Limbic State[/bold cyan]  [dim]cykel {s.cycle}[/dim]\n")
    console.print(f"  Dopamin       [yellow]{s.dopamine:.3f}[/yellow]  "
                  f"[dim](belöning / TD error)[/dim]")
    console.print(f"  Noradrenalin  [yellow]{s.noradrenaline:.3f}[/yellow]  "
                  f"[dim](surprise / novelty)[/dim]")
    console.print(f"  Acetylkolin   [yellow]{s.acetylcholine:.3f}[/yellow]  "
                  f"[dim](β / attention temp)[/dim]")
    console.print(f"  λ (kreativitet) [bold]{s.lam:.3f}[/bold]  "
                  f"[dim](F_bisoc kreativitetskofficient)[/dim]")
    console.print(f"  Arousal       [cyan]{s.arousal:.3f}[/cyan]")
    console.print(f"  Performance   [cyan]{s.performance:.3f}[/cyan]  "
                  f"[dim](Yerkes-Dodson)[/dim]")
    console.print(f"  Pruning-aggressivitet  "
                  f"[magenta]{s.pruning_aggression:.3f}[/magenta]")

@app.command()
def snapshot(tag: str = typer.Option("manual", "--tag", "-t", help="Tagga ditt snapshot, t.ex. 'innan_experiment_2'")) -> None:
    """Ta en forsknings-dump (snapshot) av hela hjärnans tillstånd (graf + hormonvärden)."""
    from nouse.metacognition.snapshot import create_snapshot
    from nouse.field.surface import FieldSurface
    field = FieldSurface(read_only=True)
    
    console.print(f"[dim]Kopierar graf-databas, exporterar limbiska variabler och beräknar nätverkstopologi H0/H1...[/dim]")
    out_dir = create_snapshot(field, tag=tag)
    console.print(f"\n[bold green]✅ Snapshot lagrat (tag: {tag})[/bold green]")
    console.print(f"Sökväg: [cyan]{out_dir}[/cyan]")



@app.command()
def autonomous(
    iterations: int = typer.Option(0, "--iterations", "-i", help="Antal iterationer att köra (0 = oändligt)"),
) -> None:
    """Kör agenten i autonomt läge för att upptäcka och lägga till ny kunskap."""
    import asyncio
    import os
    import random
    from nouse.field.surface import FieldSurface
    from nouse.daemon.extractor import synthesize_bridges

    async def _run():
        async def _run_gap_queue_fallback(field: FieldSurface) -> dict[str, object]:
            from nouse.daemon.evidence import assess_relation, format_why_with_evidence
            from nouse.daemon.extractor import extract_relations
            from nouse.daemon.initiative import run_curiosity_burst
            from nouse.daemon.research_queue import (
                claim_next_task,
                complete_task,
                enqueue_gap_tasks,
                fail_task,
            )
            from nouse.limbic.signals import load_state

            enqueue_gap_tasks(field, max_new=2)
            task = claim_next_task()
            if not task:
                return {"status": "empty"}

            task_id = int(task.get("id", -1) or -1)
            limbic = load_state()
            text = await run_curiosity_burst(field, limbic, task=task)
            if not text:
                if task_id > 0:
                    fail_task(task_id, "Autonomous fallback: Ingen rapport producerades")
                return {"status": "failed", "task_id": task_id, "added": 0}

            rels = await extract_relations(
                text,
                {"source": "autonomous_fallback", "path": f"task_{task_id}"},
            )

            added = 0
            evidence_scores: list[float] = []
            tier_counts = {"hypotes": 0, "indikation": 0, "validerad": 0}
            for r in rels:
                ass = assess_relation(r, task=task)
                evidence_scores.append(ass.score)
                tier_counts[ass.tier] = tier_counts.get(ass.tier, 0) + 1
                field.add_concept(r["src"], r["domain_src"], source="autonomous_fallback")
                field.add_concept(r["tgt"], r["domain_tgt"], source="autonomous_fallback")
                field.add_relation(
                    r["src"],
                    r["type"],
                    r["tgt"],
                    why=format_why_with_evidence(r.get("why", ""), ass),
                    strength=float(ass.score),
                    source_tag=f"autonomous_fallback:{ass.tier}",
                    evidence_score=float(ass.score),
                    assumption_flag=(ass.tier == "hypotes"),
                )
                added += 1

            avg_evidence = (
                sum(evidence_scores) / len(evidence_scores) if evidence_scores else 0.0
            )
            max_evidence = max(evidence_scores) if evidence_scores else 0.0
            if task_id > 0:
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
            }

        fallback_streak = max(
            2,
            int(os.getenv("NOUSE_AUTONOMOUS_FALLBACK_STREAK", "3")),
        )

        try:
            field = FieldSurface()
        except RuntimeError as e:
            if "Could not set lock on file" in str(e):
                console.print(
                    "[red]Autonomous kräver exklusivt databaslås.[/red]\n"
                    "[dim]Stoppa daemonen först (t.ex. systemctl --user stop nouse-daemon.service).[/dim]"
                )
                raise typer.Exit(2)
            raise
        i = 0
        no_path_streak = 0
        while iterations == 0 or i < iterations:
            domains = field.domains()
            if len(domains) < 2:
                console.print("[red]Inte tillräckligt med domäner för att hitta en meningsfull stig.[/red]")
                break

            domain_a, domain_b = random.sample(domains, 2)
            console.print(f"\n[bold]Iteration {i+1}[/bold] [cyan]{domain_a} → {domain_b}[/cyan]")
            path = field.find_path(domain_a, domain_b, max_hops=8)

            if not path:
                no_path_streak += 1
                console.print(f"[dim]Ingen stig hittad (streak={no_path_streak}).[/dim]")
                if no_path_streak >= fallback_streak:
                    console.print("[yellow]Fallback: kör gap-queue task istället.[/yellow]")
                    result = await _run_gap_queue_fallback(field)
                    if result.get("status") == "empty":
                        console.print("[dim]Fallback: queue tom.[/dim]")
                    elif result.get("status") == "failed":
                        console.print(
                            f"[red]Fallback misslyckades för task #{result.get('task_id', '?')}.[/red]"
                        )
                    else:
                        console.print(
                            f"[green]Fallback klart.[/green] "
                            f"task #{result.get('task_id', '?')} "
                            f"+{int(result.get('added', 0) or 0)} relationer "
                            f"[dim](evidence avg={float(result.get('avg_evidence', 0.0)):.3f}, "
                            f"max={float(result.get('max_evidence', 0.0)):.3f})[/dim]"
                        )
                    no_path_streak = 0
                await asyncio.sleep(1)
                i += 1
                continue

            no_path_streak = 0
            novelty = field.path_novelty(path)
            console.print(f"  [dim]Hittade stig med {len(path)} hopp, novelty={novelty:.1f}[/dim]")

            new_relations = await synthesize_bridges(path, domain_a, domain_b)
            if not new_relations:
                console.print(f"  [dim]Inga nya relationer syntetiserades.[/dim]")
                await asyncio.sleep(1)
                i += 1
                continue

            for r in new_relations:
                console.print(
                    f"  [dim cyan]⊕ Syntetiserad relation:[/dim cyan] "
                    f"[yellow]{r['src']}[/yellow] "
                    f"--[{r['rel_type']}]--> "
                    f"[green]{r['tgt']}[/green]  "
                    f"[dim]({r.get('why','')[:60]})[/dim]"
                )
                field.add_concept(r["src"], r["domain_src"])
                field.add_concept(r["tgt"], r["domain_tgt"])
                field.add_relation(
                    r["src"], r["rel_type"], r["tgt"],
                    why=r.get("why", ""),
                    source_tag="autonomous",
                )
            i += 1
            await asyncio.sleep(1)

    asyncio.run(_run())


@app.command(name="kickstart")
def kickstart_cmd(
    mission: str = typer.Option(
        "",
        "--mission",
        "-m",
        help="Kort mission for kickoff (tom = smart default).",
    ),
    focus: str = typer.Option(
        "autonomy,chat,memory",
        "--focus",
        "-f",
        help="Komma-separerade fokusdomaner.",
    ),
    repo_root: str = typer.Option(
        "/home/bjorn/projects/GH_autonom_b76",
        "--repo-root",
        help="Extern repo-root som kickoff-agenter far anvanda som sandbox.",
    ),
    iic1_root: str = typer.Option(
        "/media/bjorn/iic1",
        "--iic1-root",
        help="Projects root; dokument hariffran indexeras som project:-kalla.",
    ),
    max_tasks: int = typer.Option(8, "--max-tasks", help="Max antal kickoff-taskar."),
    max_docs: int = typer.Option(8, "--max-docs", help="Max antal lokala dokument i seed."),
    session_id: str = typer.Option("main", "--session-id", "-s", help="Session-id."),
) -> None:
    """Kicka igang projektet: seeda agent/subagent-taskar + vack autonom loopen."""
    from nouse.client import post_kickstart
    from nouse.daemon.kickstart import run_kickstart_bootstrap
    from nouse.field.surface import FieldSurface
    import httpx

    result = None
    api_error: Exception | None = None

    for _ in range(3):
        try:
            result = post_kickstart(
                session_id=session_id,
                mission=mission,
                focus_domains=focus,
                repo_root=repo_root,
                iic1_root=iic1_root,
                max_tasks=max_tasks,
                max_docs=max_docs,
                source="cli_kickstart",
                timeout=45.0,
            )
            break
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            api_error = e
            time.sleep(0.8)
        except Exception as e:
            api_error = e
            break

    if result is None:
        try:
            field = FieldSurface()
        except RuntimeError as e:
            if "Could not set lock on file" in str(e):
                # Daemon kan vara igang men API-check misslyckades tillfalligt precis vid restart.
                try:
                    result = post_kickstart(
                        session_id=session_id,
                        mission=mission,
                        focus_domains=focus,
                        repo_root=repo_root,
                        iic1_root=iic1_root,
                        max_tasks=max_tasks,
                        max_docs=max_docs,
                        source="cli_kickstart_retry",
                        timeout=90.0,
                    )
                except Exception:
                    console.print(
                        "[red]Kickstart kraver daemon-API i detta lage (DB-las aktivt).[/red]"
                    )
                    if api_error is not None:
                        console.print(f"[dim]Senaste API-fel: {api_error}[/dim]")
                    raise typer.Exit(2)
            else:
                raise
        if result is None:
            domains = [x.strip() for x in (focus or "").split(",") if x.strip()]
            result = run_kickstart_bootstrap(
                field=field,
                session_id=session_id,
                mission=mission,
                focus_domains=domains,
                repo_root=repo_root,
                iic1_root=iic1_root,
                max_tasks=max_tasks,
                max_docs=max_docs,
                source="cli_kickstart_local",
            )

    if result is None:
        console.print("[red]Kickstart misslyckades utan resultat.[/red]")
        if api_error is not None:
            console.print(f"[dim]Senaste API-fel: {api_error}[/dim]")
        raise typer.Exit(2)

    console.print(
        Panel(
            f"[bold cyan]Kickstart klart[/bold cyan]\n"
            f"session={result.get('session_id', 'main')}\n"
            f"seeded={int(result.get('seeded', 0) or 0)} · "
            f"added={int(result.get('added', 0) or 0)}\n"
            f"queue pending={int((result.get('queue') or {}).get('pending', 0) or 0)}",
            border_style="cyan",
        )
    )
    console.print(f"[dim]Repo-root:[/dim] {result.get('repo_root') or repo_root}")
    docs = result.get("docs") or []
    if docs:
        console.print("[dim]Dokumentunderlag:[/dim] " + ", ".join(str(x) for x in docs[:6]))


@app.command(name="research-queue")
def research_queue_cmd(
    action: str = typer.Argument("status", help="status | scan | run-one | run-batch"),
    limit: int = typer.Option(5, "--limit", "-l", help="Hur många tasks att visa"),
    count: int = typer.Option(5, "--count", "-c", help="Antal taskar i run-batch"),
    task_timeout: float = typer.Option(
        0.0,
        "--task-timeout",
        help="Hård timeout per task i sekunder (0 = ingen extra timeout).",
    ),
    extract_timeout: float = typer.Option(
        0.0,
        "--extract-timeout",
        help="Override extractor-timeout i sekunder (0 = default).",
    ),
    extract_models: str = typer.Option(
        "",
        "--extract-models",
        help="Komma-separerad modellordning för extraktion.",
    ),
) -> None:
    """Inspektera och kör autonom gap-baserad research-queue."""
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
                console.print("[yellow]Queue tom — avbryter batch.[/yellow]")
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
                        console.print("[yellow]Queue tom — avbryter batch.[/yellow]")
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
    """Hantera global mission för autonom riktning + mätning."""
    from nouse.daemon.mission import (
        clear_mission,
        load_mission,
        read_recent_metrics,
        save_mission,
    )

    if action == "show":
        mission = load_mission()
        if not mission:
            console.print("[yellow]Ingen aktiv mission.[/yellow]")
            return
        console.print("[bold cyan]Aktiv mission[/bold cyan]")
        console.print(f"  Mission: [white]{mission.get('mission','')}[/white]")
        ns = str(mission.get("north_star") or "").strip()
        if ns:
            console.print(f"  North star: [white]{ns}[/white]")
        domains = mission.get("focus_domains") or []
        if domains:
            console.print(f"  Fokusdomäner: [green]{', '.join(domains)}[/green]")
        kpis = mission.get("kpis") or []
        if kpis:
            console.print(f"  KPI: [magenta]{' | '.join(kpis)}[/magenta]")
        constraints = mission.get("constraints") or []
        if constraints:
            console.print(f"  Constraints: [yellow]{' | '.join(constraints)}[/yellow]")
        console.print(
            f"  Version: {mission.get('version', '?')}  "
            f"[dim]uppdaterad={mission.get('updated_at','?')}[/dim]"
        )
        return

    if action == "set":
        mission_text = str(text or "").strip()
        if not mission_text:
            console.print("[red]Ange mission-text med --text.[/red]")
            raise typer.Exit(2)
        saved = save_mission(
            mission_text,
            north_star=north_star,
            focus_domains=focus_domain,
            kpis=kpi,
            constraints=constraint,
        )
        console.print("[green]Mission sparad.[/green]")
        console.print(f"[dim]version={saved.get('version')}[/dim]")
        return

    if action == "clear":
        removed = clear_mission()
        if removed:
            console.print("[green]Mission rensad.[/green]")
        else:
            console.print("[yellow]Ingen mission att rensa.[/yellow]")
        return

    if action == "metrics":
        rows = read_recent_metrics(limit=max(1, lines))
        if not rows:
            console.print("[yellow]Inga mission-metrics ännu.[/yellow]")
            return
        console.print(f"[bold cyan]Senaste {len(rows)} mission-metrics[/bold cyan]")
        for row in rows:
            graph = row.get("graph") or {}
            delta = row.get("delta") or {}
            queue = row.get("queue") or {}
            cov = row.get("knowledge_coverage") or {}
            cov_part = ""
            if cov:
                cov_part = f" · coverage={float(cov.get('complete', 0.0)):.3f}"
            console.print(
                f"  {row.get('ts','?')}  cycle={row.get('cycle','?')}  "
                f"graph={int(graph.get('concepts',0))}/{int(graph.get('relations',0))}  "
                f"+rel={int(delta.get('new_relations',0))}  "
                f"queue(p/i/d/f)={int(queue.get('pending',0))}/"
                f"{int(queue.get('in_progress',0))}/"
                f"{int(queue.get('done',0))}/"
                f"{int(queue.get('failed',0))}{cov_part}"
            )
        return

    console.print("[red]Ogiltig action.[/red] Använd: show | set | clear | metrics")


@app.command(name="hitl")
def hitl_cmd(
    action: str = typer.Argument("status", help="status | approve | reject"),
    interrupt_id: int = typer.Option(0, "--id", "-i", help="Interrupt-id"),
    reviewer: str = typer.Option("human", "--reviewer", help="Vem godkänner/avslår"),
    note: str = typer.Option("", "--note", help="Anteckning"),
    status: str = typer.Option("pending", "--status", help="Filter för status"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max antal rader"),
) -> None:
    """Hantera HITL-interrupts (pause/approve/reject)."""
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
            f"[green]Godkänd[/green] interrupt #{interrupt_id} → task #{task_id} återköad."
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
            f"[yellow]Avslagen[/yellow] interrupt #{interrupt_id} → task #{task_id} markerad failed."
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
    """Hantera sessionslager (lifecycle + runs + energi)."""
    from nouse.session import (
        cancel_active_run,
        ensure_session,
        list_runs,
        list_sessions,
        session_stats,
        set_energy,
    )

    safe_limit = max(1, min(int(limit), 5000))
    if action == "open":
        row = ensure_session(session_id, lane=lane, source=source)
        console.print(
            f"[green]Session aktiv:[/green] id={row.get('id')} lane={row.get('lane')} "
            f"status={row.get('status')} energy={float(row.get('energy', 0.5)):.2f}"
        )
        return

    if action == "list":
        rows = list_sessions(status=(None if status == "all" else status), limit=safe_limit)
        if not rows:
            console.print("[yellow]Inga sessioner hittades.[/yellow]")
            return
        console.print(f"[bold cyan]Sessioner ({len(rows)})[/bold cyan]")
        for row in rows:
            counters = row.get("counters") or {}
            console.print(
                f"  [dim]{row.get('id')}[/dim] lane={row.get('lane')} "
                f"status=[yellow]{row.get('status')}[/yellow] "
                f"energy={float(row.get('energy', 0.5) or 0.5):.2f} "
                f"runs={int(counters.get('started', 0) or 0)} "
                f"(ok={int(counters.get('succeeded', 0) or 0)} "
                f"fail={int(counters.get('failed', 0) or 0)} "
                f"cancel={int(counters.get('cancelled', 0) or 0)})"
            )
        return

    if action == "runs":
        rows = list_runs(
            session_id=(session_id or None),
            status=(None if status == "all" else status),
            limit=safe_limit,
        )
        if not rows:
            console.print("[yellow]Inga runs hittades.[/yellow]")
            return
        console.print(f"[bold cyan]Runs ({len(rows)})[/bold cyan]")
        for row in rows:
            console.print(
                f"  [dim]{row.get('run_id')}[/dim] session={row.get('session_id')} "
                f"[yellow]{row.get('status')}[/yellow] workload={row.get('workload')} "
                f"model={row.get('model')} prompt={int(row.get('request_chars', 0) or 0)} "
                f"resp={int(row.get('response_chars', 0) or 0)}"
            )
        return

    if action == "energy":
        row = set_energy(session_id, energy, source=source)
        console.print(
            f"[green]Energy uppdaterad.[/green] session={row.get('id')} "
            f"energy={float(row.get('energy', 0.5) or 0.5):.2f}"
        )
        return

    if action == "cancel":
        row = cancel_active_run(session_id, reason="cancel via cli", actor=source or "cli")
        if not row:
            console.print("[yellow]Ingen aktiv run att avbryta.[/yellow]")
            return
        console.print(
            f"[yellow]Run avbruten.[/yellow] run_id={row.get('run_id')} "
            f"session={row.get('session_id')}"
        )
        return

    if action == "stats":
        s = session_stats()
        console.print(
            f"[bold cyan]Session Stats[/bold cyan] "
            f"sessions={int(s.get('sessions_total', 0) or 0)} "
            f"running={int(s.get('sessions_running', 0) or 0)} "
            f"runs={int(s.get('runs_total', 0) or 0)} "
            f"active_runs={int(s.get('active_runs', 0) or 0)}"
        )
        return

    console.print("[red]Ogiltig action.[/red] Använd: open | list | runs | energy | cancel | stats")


@app.command(name="models")
def models_cmd(
    action: str = typer.Argument("status", help="status | set-fallback | reset"),
    workload: str = typer.Option("chat", "--workload", "-w", help="Workload att styra"),
    candidates: str = typer.Option(
        "",
        "--candidates",
        "-c",
        help="Komma-separerad modellordning för fallback",
    ),
    provider: str = typer.Option("ollama", "--provider", help="Provider för policy"),
) -> None:
    """Hantera modell-failover policy per tasktyp."""
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
    """Operatörs-CLI för wake/system-events (autonom triggerbuss)."""
    from nouse.client import (
        daemon_running,
        get_system_events,
        post_system_wake,
    )
    from nouse.daemon.system_events import (
        enqueue_system_event,
        peek_system_event_entries,
        peek_wake_reasons,
        request_wake,
        system_event_stats,
    )

    clean_mode = str(mode or "now").strip().lower()
    if clean_mode not in {"now", "next-heartbeat"}:
        clean_mode = "now"

    if action == "status":
        safe_limit = max(1, min(int(limit), 200))
        if daemon_running():
            payload = get_system_events(limit=safe_limit, session_id=session_id, timeout=10.0)
            stats = payload.get("stats") or {}
            events = payload.get("events") or []
            wakes = payload.get("wake_reasons") or []
        else:
            stats = system_event_stats()
            events = peek_system_event_entries(limit=safe_limit, session_id=session_id)
            wakes = peek_wake_reasons(limit=safe_limit)

        console.print(
            f"[bold cyan]Wake Status[/bold cyan] pending={int(stats.get('pending_total', 0) or 0)} "
            f"session={session_id}"
        )
        if events:
            console.print("[bold]System-events[/bold]")
            for row in events:
                console.print(
                    f"  {str(row.get('ts', ''))[:19]}  "
                    f"{row.get('session_id')}  {row.get('source')}  "
                    f"{str(row.get('text', ''))[:120]}"
                )
        else:
            console.print("[dim]Inga pending system-events.[/dim]")
        if wakes:
            console.print("[bold]Wake-reasons[/bold]")
            for row in wakes:
                console.print(
                    f"  {str(row.get('ts', ''))[:19]}  "
                    f"{row.get('session_id')}  {row.get('reason')}"
                )
        return

    if action == "emit":
        clean_text = str(text or "").strip()
        if not clean_text and clean_mode != "now":
            console.print("[red]Ange --text eller kör --mode now.[/red]")
            raise typer.Exit(2)

        if daemon_running():
            payload = post_system_wake(
                text=clean_text,
                session_id=session_id,
                source=source,
                mode=clean_mode,
                reason=reason,
                context_key=context_key,
                timeout=10.0,
            )
            if not bool(payload.get("ok", False)):
                console.print(f"[red]Wake misslyckades:[/red] {payload.get('error', 'okänt fel')}")
                raise typer.Exit(1)
            console.print(
                f"[green]Wake skickad via daemon.[/green] queued={payload.get('queued')} "
                f"wake={payload.get('wake_requested')} mode={payload.get('mode')}"
            )
            return

        queued = False
        if clean_text:
            queued = enqueue_system_event(
                clean_text,
                session_id=session_id,
                source=source,
                context_key=context_key,
            )
        if clean_mode == "now":
            request_wake(reason=reason, session_id=session_id, source=source)
        console.print(
            f"[yellow]Daemon offline — wake lagrad lokalt.[/yellow] "
            f"queued={queued} wake={(clean_mode == 'now')} mode={clean_mode}"
        )
        return

    console.print("[red]Ogiltig action.[/red] Använd: status | emit")


@app.command(name="usage")
def usage_cmd(
    action: str = typer.Argument("summary", help="summary | tail"),
    limit: int = typer.Option(50, "--limit", "-l", help="Antal rader att visa"),
    session_id: str = typer.Option("", "--session-id", help="Filtrera på session"),
    workload: str = typer.Option("", "--workload", help="Filtrera på workload"),
    model: str = typer.Option("", "--model", help="Filtrera på modell"),
    status: str = typer.Option("", "--status", help="Filtrera på status"),
) -> None:
    """Visa usage/cost-telemetri per run/modell/session."""
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
    """Hantera pairing/allowlist för extern ingress."""
    from nouse.ingress.allowlist import (
        add_allowed_actor,
        approve_pairing,
        list_allowed,
        list_pending,
        remove_allowed_actor,
    )

    if action == "list":
        rows = list_allowed(channel)
        console.print(f"[bold cyan]Allowlist ({channel})[/bold cyan]")
        if not rows:
            console.print("[dim]Tom lista.[/dim]")
            return
        for row in rows:
            console.print(f"  {row}")
        return

    if action == "pending":
        rows = list_pending(channel)
        console.print(f"[bold cyan]Pending Pairing ({channel})[/bold cyan]")
        if not rows:
            console.print("[dim]Inga väntande pairing-koder.[/dim]")
            return
        for row in rows:
            console.print(f"  code={row.get('code')} actor={row.get('actor_id')} created={row.get('created_at')}")
        return

    if action == "add":
        if not actor:
            console.print("[red]Ange --actor för add.[/red]")
            raise typer.Exit(2)
        add_allowed_actor(channel, actor)
        console.print(f"[green]Actor tillagd.[/green] channel={channel} actor={actor}")
        return

    if action == "remove":
        if not actor:
            console.print("[red]Ange --actor för remove.[/red]")
            raise typer.Exit(2)
        removed = remove_allowed_actor(channel, actor)
        if removed:
            console.print(f"[yellow]Actor borttagen.[/yellow] channel={channel} actor={actor}")
        else:
            console.print("[yellow]Actor fanns inte i allowlist.[/yellow]")
        return

    if action == "approve":
        if not code:
            console.print("[red]Ange --code för approve.[/red]")
            raise typer.Exit(2)
        row = approve_pairing(channel, code)
        if not row:
            console.print("[red]Ogiltig pairing-kod.[/red]")
            raise typer.Exit(1)
        console.print(
            f"[green]Pairing godkänd.[/green] channel={row.get('channel')} "
            f"actor={row.get('actor_id')} code={row.get('code')}"
        )
        return

    console.print("[red]Ogiltig action.[/red] Använd: list | pending | add | remove | approve")


@app.command(name="api-keys")
def api_keys_cmd(
    action: str = typer.Argument("list", help="list | create | revoke"),
    tenant: str = typer.Option("", "--tenant", "-t", help="Tenant-id (krävs för create)"),
    label: str = typer.Option("", "--label", "-l", help="Beskrivning av nyckeln"),
    key: str = typer.Option("", "--key", "-k", help="API-nyckel att återkalla (revoke)"),
) -> None:
    """Hantera SaaS API-nycklar (nsk-...). Kräver nouse-saas."""
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
    """Ingress-adapterlager (första kanal: Telegram)."""
    import os
    from pathlib import Path
    from nouse.ingress.allowlist import list_allowed, list_pending
    from nouse.ingress.telegram import ingest_telegram_once

    offset_path = Path.home() / ".local" / "share" / "nouse" / "telegram_offset.txt"

    def _read_offset() -> int:
        if offset > 0:
            return int(offset)
        if not offset_path.exists():
            return 0
        try:
            return int((offset_path.read_text(encoding="utf-8") or "0").strip())
        except Exception:
            return 0

    def _write_offset(value: int) -> None:
        offset_path.parent.mkdir(parents=True, exist_ok=True)
        offset_path.write_text(str(int(value)), encoding="utf-8")

    if action == "status":
        allowed = list_allowed("telegram")
        pending = list_pending("telegram")
        current_offset = _read_offset()
        console.print(
            f"[bold cyan]Ingress Status[/bold cyan] telegram_allow={len(allowed)} "
            f"pending_pairing={len(pending)} offset={current_offset}"
        )
        return

    if action == "telegram-once":
        effective_token = (token or os.getenv("NOUSE_TELEGRAM_BOT_TOKEN", "")).strip()
        if not effective_token:
            console.print("[red]Saknar Telegram-token.[/red] Ange --token eller NOUSE_TELEGRAM_BOT_TOKEN.")
            raise typer.Exit(2)
        start_offset = _read_offset()
        result = ingest_telegram_once(
            token=effective_token,
            offset=start_offset,
            timeout_sec=max(1, int(timeout)),
            limit=max(1, int(limit)),
            strict_pairing=bool(strict_pairing),
        )
        next_offset = int(result.get("next_offset", start_offset) or start_offset)
        _write_offset(next_offset)
        console.print(
            f"[green]Telegram poll klart.[/green] updates={int(result.get('updates', 0) or 0)} "
            f"processed={int(result.get('processed', 0) or 0)} "
            f"answered={int(result.get('answered', 0) or 0)} "
            f"rejected={int(result.get('rejected', 0) or 0)} "
            f"next_offset={next_offset}"
        )
        return

    console.print("[red]Ogiltig action.[/red] Använd: status | telegram-once")


@app.command(name="plugins")
def plugins_cmd(
    action: str = typer.Argument("list", help="list | install | remove | update"),
    source: str = typer.Option("", "--source", help="Pluginfil (.py) för install/update"),
    name: str = typer.Option("", "--name", help="Pluginnamn"),
    version: str = typer.Option("0.1.0", "--version", help="Pluginversion"),
    description: str = typer.Option("", "--description", help="Kort beskrivning"),
) -> None:
    """Hantera skill/plugin-livscykel med versionsspårning."""
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
    """Driftdiagnostik + säkra auto-fixar för vanliga fel."""
    import json
    from pathlib import Path
    from nouse.client import daemon_running, get_queue_status
    from nouse.daemon.mission import MISSION_METRICS_PATH
    from nouse.daemon.research_queue import DEFAULT_QUEUE_PATH
    from nouse.llm.model_router import router_status
    from nouse.llm.policy import MODEL_POLICY_PATH, reset_policy
    from nouse.llm.usage import USAGE_LOG_PATH
    from nouse.self_layer import LIVING_CORE_PATH, ensure_living_core, load_living_core
    from nouse.session import SESSION_STATE_PATH, clear_stale_running, session_stats

    checks: list[tuple[str, bool, str, bool]] = []
    fixes: list[str] = []

    def add(name: str, ok: bool, detail: str, *, critical: bool = True) -> None:
        checks.append((name, bool(ok), detail, bool(critical)))

    daemon_ok = daemon_running()
    add("daemon", daemon_ok, "up" if daemon_ok else "not running")

    if daemon_ok:
        try:
            q = get_queue_status(limit=1, status="all", timeout=10.0)
            s = q.get("stats") or {}
            add(
                "queue",
                True,
                (
                    f"pending={int(s.get('pending', 0) or 0)} "
                    f"failed={int(s.get('failed', 0) or 0)} "
                    f"awaiting={int(s.get('awaiting_approval', 0) or 0)}"
                ),
            )
        except Exception as e:
            add("queue", False, f"api error: {e}", critical=True)
    else:
        if DEFAULT_QUEUE_PATH.exists():
            try:
                data = json.loads(DEFAULT_QUEUE_PATH.read_text(encoding="utf-8"))
                rows = data if isinstance(data, list) else []
                add("queue", True, f"local queue file ok ({len(rows)} rows)")
            except Exception as e:
                add("queue", False, f"queue file unreadable: {e}", critical=True)
        else:
            add("queue", True, "queue file saknas ännu (ok vid ny setup)", critical=False)

    stats = session_stats()
    add(
        "sessions",
        True,
        (
            f"sessions={int(stats.get('sessions_total', 0) or 0)} "
            f"running={int(stats.get('sessions_running', 0) or 0)} "
            f"runs={int(stats.get('runs_total', 0) or 0)}"
        ),
    )

    if MODEL_POLICY_PATH.exists():
        try:
            policy = json.loads(MODEL_POLICY_PATH.read_text(encoding="utf-8"))
            workloads = policy.get("workloads") if isinstance(policy, dict) else {}
            count = len(workloads) if isinstance(workloads, dict) else 0
            add("model_policy", True, f"exists workloads={count}")
        except Exception as e:
            add("model_policy", False, f"corrupt: {e}", critical=False)
    else:
        add("model_policy", False, "saknas", critical=False)

    router = router_status()
    router_workloads = router.get("workloads") if isinstance(router, dict) else {}
    add(
        "model_router",
        True,
        f"workloads={len(router_workloads) if isinstance(router_workloads, dict) else 0}",
    )

    if MISSION_METRICS_PATH.exists():
        add("mission_metrics", True, f"exists at {MISSION_METRICS_PATH}")
    else:
        add("mission_metrics", False, "saknas", critical=False)

    if USAGE_LOG_PATH.exists():
        add("usage_log", True, f"exists at {USAGE_LOG_PATH}")
    else:
        add("usage_log", False, "saknas", critical=False)

    if LIVING_CORE_PATH.exists():
        core = load_living_core()
        homeo = core.get("homeostasis") if isinstance(core, dict) else {}
        drives = core.get("drives") if isinstance(core, dict) else {}
        identity = core.get("identity") if isinstance(core, dict) else {}
        memories = identity.get("memories") if isinstance(identity, dict) else []
        add(
            "living_core",
            True,
            (
                f"mode={str((homeo or {}).get('mode', 'steady'))} "
                f"drive={str((drives or {}).get('active', 'maintenance'))} "
                f"memories={len(memories) if isinstance(memories, list) else 0}"
            ),
            critical=False,
        )
    else:
        add("living_core", False, "saknas", critical=False)

    if action == "fix":
        # Ensure common runtime directories.
        runtime_dirs = [
            Path.home() / ".local" / "share" / "nouse",
            Path.home() / ".local" / "share" / "nouse" / "capture_queue",
            Path.home() / ".local" / "share" / "nouse" / "trace" / "events",
            Path.home() / ".local" / "share" / "nouse" / "plugins",
        ]
        for d in runtime_dirs:
            d.mkdir(parents=True, exist_ok=True)
        fixes.append("runtime_dirs ensured")

        if not MODEL_POLICY_PATH.exists():
            reset_policy()
            fixes.append("model policy reset to defaults")

        core = ensure_living_core()
        fixes.append(
            "living core ensured "
            f"(mode={(core.get('homeostasis') or {}).get('mode', 'steady')}, "
            f"drive={(core.get('drives') or {}).get('active', 'maintenance')})"
        )

        stale = clear_stale_running(max_age_sec=max(30.0, float(stale_run_age_sec)))
        if stale:
            fixes.append(f"cleared stale running sessions: {', '.join(stale)}")

    failures = 0
    console.print("[bold cyan]nouse doctor[/bold cyan]")
    for name, ok, detail, critical in checks:
        if ok:
            icon = "[green]OK[/green]"
        else:
            icon = "[red]FAIL[/red]" if critical else "[yellow]WARN[/yellow]"
        if not ok and critical:
            failures += 1
        console.print(f"  {icon} {name}: {detail}")
    if fixes:
        console.print("[bold]Applied fixes[/bold]")
        for row in fixes:
            console.print(f"  - {row}")

    if failures:
        raise typer.Exit(1)


@app.command(name="journal")
def journal_cmd(
    action: str = typer.Argument("tail", help="tail | latest | today | research-tail"),
    entries: int = typer.Option(
        8,
        "--entries",
        "-e",
        help="Antal timeline-poster för tail.",
    ),
    lines: int = typer.Option(
        80,
        "--lines",
        "-n",
        help="Fallback: antal rader om inga timeline-poster hittas.",
    ),
    newest_first: bool = typer.Option(
        True,
        "--newest-first",
        help="Visa tail med senaste raden först.",
    ),
) -> None:
    """Visa b76:s dagliga journal (självutveckling + öppna frågor)."""
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
    """Kontinuerlig identitet + minnen + interna drivkrafter."""
    from nouse.self_layer import (
        append_identity_memory,
        ensure_living_core,
        load_living_core,
        update_identity_profile,
    )

    def _split_csv(raw: str) -> list[str]:
        return [x.strip() for x in str(raw or "").split(",") if x.strip()]

    if action == "status":
        core = ensure_living_core()
        identity = core.get("identity") if isinstance(core, dict) else {}
        drives = core.get("drives") if isinstance(core, dict) else {}
        homeo = core.get("homeostasis") if isinstance(core, dict) else {}
        reflection = core.get("last_reflection") if isinstance(core, dict) else {}
        memories = (identity.get("memories") or []) if isinstance(identity, dict) else []
        console.print("[bold cyan]nouse self[/bold cyan]")
        console.print(f"  mission: {identity.get('mission')}")
        console.print(f"  values: {', '.join(identity.get('values') or [])}")
        console.print(
            f"  mode={homeo.get('mode')} energy={float(homeo.get('energy', 0.0) or 0.0):.3f} "
            f"focus={float(homeo.get('focus', 0.0) or 0.0):.3f} risk={float(homeo.get('risk', 0.0) or 0.0):.3f}"
        )
        console.print(f"  active_drive={drives.get('active')} goals={', '.join(drives.get('goals') or [])}")
        console.print(f"  thought: {reflection.get('thought')}")
        console.print(f"  feeling: {reflection.get('feeling')}")
        if memories:
            console.print(f"[bold]Recent memories ({min(limit, len(memories))})[/bold]")
            for row in memories[-max(1, limit):]:
                console.print(f"  - {str(row.get('ts') or '')}: {str(row.get('note') or '')[:220]}")
        else:
            console.print("[dim]Inga memories ännu.[/dim]")
        return

    if action == "set-mission":
        mission_clean = str(mission or "").strip()
        if not mission_clean:
            console.print("[red]Ange --mission för set-mission.[/red]")
            raise typer.Exit(2)
        row = update_identity_profile(
            mission=mission_clean,
            values=_split_csv(values) if values else None,
            personality=(personality or None),
            boundaries=_split_csv(boundaries) if boundaries else None,
        )
        identity = row.get("identity") or {}
        console.print("[green]Identity uppdaterad.[/green]")
        console.print(f"  mission: {identity.get('mission')}")
        return

    if action == "remember":
        note_clean = str(note or "").strip()
        if not note_clean:
            console.print("[red]Ange --note för remember.[/red]")
            raise typer.Exit(2)
        row = append_identity_memory(
            note_clean,
            tags=_split_csv(tags),
            session_id="operator",
            run_id="cli_self",
            kind="operator_note",
        )
        memories = ((row.get("identity") or {}).get("memories") or [])
        console.print(f"[green]Memory lagrat.[/green] total_memories={len(memories)}")
        return

    if action == "reload":
        core = load_living_core()
        console.print(
            f"[green]Reload ok.[/green] updated={core.get('updated_at')} "
            f"mode={(core.get('homeostasis') or {}).get('mode', 'steady')}"
        )
        return

    console.print("[red]Ogiltig action.[/red] Använd: status | set-mission | remember | reload")


@app.command(name="output-trace")
def output_trace_cmd(
    trace_id: str | None = typer.Option(
        None,
        "--trace-id",
        "-t",
        help="Filtrera på specifik trace_id",
    ),
    limit: int = typer.Option(
        80,
        "--limit",
        "-l",
        help="Max antal events att visa",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Skriv events som JSON-array",
    ),
) -> None:
    """Visa output-trace (fråga -> angrepp -> verktyg -> svar -> antaganden)."""
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
    """Kör ett problemset mot /api/chat och verifiera att tracekedjan blir komplett."""
    import json
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    import httpx
    from ruamel.yaml import YAML

    from nouse.client import DAEMON_BASE, daemon_running, get_output_trace

    if not daemon_running():
        console.print("[red]Daemon måste vara igång för trace-probe.[/red]")
        console.print("[dim]Kör: nouse daemon web[/dim]")
        raise typer.Exit(1)

    pset = Path(set_path).expanduser()
    if not pset.exists():
        console.print(f"[red]Problemset saknas:[/red] {pset}")
        raise typer.Exit(1)

    yaml = YAML(typ="safe")
    data = yaml.load(pset.read_text(encoding="utf-8", errors="ignore")) or {}
    all_cases = data.get("cases") or []
    if not all_cases:
        console.print("[red]Inga 'cases' hittades i problemsetet.[/red]")
        raise typer.Exit(1)

    selected = all_cases[: max(1, limit)]
    rows: list[dict] = []
    passed = 0

    console.print(f"[bold cyan]Trace Probe[/bold cyan]  cases={len(selected)}  set={pset}")
    for i, case in enumerate(selected, 1):
        cid = str(case.get("id") or f"case_{i}")
        prompt = str(case.get("prompt") or "").strip()
        expect = case.get("expect") or {}
        min_q = int(expect.get("min_questions", 0) or 0)
        min_c = int(expect.get("min_claims", 0) or 0)
        min_a = int(expect.get("min_assumptions", 0) or 0)
        if not prompt:
            continue

        try:
            r = httpx.post(
                f"{DAEMON_BASE}/api/chat",
                json={"query": prompt},
                timeout=timeout_sec,
            )
            r.raise_for_status()
            payload = r.json() or {}
            trace_id = str(payload.get("trace_id") or "")
            response = str(payload.get("response") or "")
        except Exception as e:
            console.print(f"[red]✗ {cid}[/red] {e}")
            rows.append(
                {
                    "id": cid,
                    "ok": False,
                    "error": str(e),
                    "prompt": prompt,
                }
            )
            continue

        events: list[dict] = []
        for _ in range(5):
            events = get_output_trace(trace_id=trace_id, limit=300).get("events", [])
            names = [str(e.get("event") or "") for e in events]
            if "chat.response" in names or "chat.error" in names:
                break
            time.sleep(0.25)

        names = [str(e.get("event") or "") for e in events]
        req_event = next((e for e in events if e.get("event") == "chat.request"), {})
        plan = (req_event.get("payload") or {}).get("attack_plan") or {}
        qn = len(plan.get("questions") or [])
        cn = len(plan.get("claims") or [])
        an = len(plan.get("assumptions") or [])
        has_chain = ("chat.request" in names) and ("chat.llm_call" in names) and (
            "chat.response" in names or "chat.error" in names
        )
        class_ok = qn >= min_q and cn >= min_c and an >= min_a
        ok = has_chain and class_ok
        if ok:
            passed += 1

        icon = "[green]✓[/green]" if ok else "[red]✗[/red]"
        console.print(
            f"{icon} {cid}  trace={trace_id[:26]}  "
            f"plan=Q{qn}/C{cn}/A{an}  events={len(events)}"
        )
        rows.append(
            {
                "id": cid,
                "ok": ok,
                "trace_id": trace_id,
                "prompt": prompt,
                "response": response,
                "event_names": names,
                "plan_counts": {"questions": qn, "claims": cn, "assumptions": an},
                "expected_min": {
                    "questions": min_q,
                    "claims": min_c,
                    "assumptions": min_a,
                },
                "has_chain": has_chain,
                "class_ok": class_ok,
            }
        )

    total = len(rows)
    ratio = passed / max(1, total)
    out_dir = Path("results/metrics")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"trace_probe_{stamp}.json"
    out_path.write_text(
        json.dumps(
            {
                "set": str(pset),
                "timestamp_utc": stamp,
                "total": total,
                "passed": passed,
                "pass_rate": ratio,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    console.print(
        f"\n[bold]Resultat[/bold]  [cyan]{passed}/{total} ({ratio:.1%})[/cyan]  "
        f"[dim]{out_path}[/dim]"
    )


@app.command(name="memory-audit")
def memory_audit_cmd(
    limit: int = typer.Option(20, "--limit", "-l", help="Antal okonsoliderade episoder att visa"),
) -> None:
    """Visa status för episodiskt/semantiskt minne."""
    from nouse.client import daemon_running, get_memory_audit
    from nouse.memory.store import MemoryStore

    safe_limit = max(1, min(limit, 5000))
    if daemon_running():
        try:
            audit = get_memory_audit(limit=safe_limit)
        except Exception:
            console.print(
                "[yellow]Daemon saknar memory-endpoint (äldre version) — kör lokal audit.[/yellow]"
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
    """Kör en manuell konsolidering från episodiskt till semantiskt minne."""
    from nouse.client import daemon_running, post_memory_consolidate
    from nouse.field.surface import FieldSurface
    from nouse.memory.store import MemoryStore

    safe_max = max(1, min(max_episodes, 5000))
    safe_min_ev = max(0.0, min(1.0, float(strict_min_evidence)))

    if daemon_running():
        try:
            result = post_memory_consolidate(
                max_episodes=safe_max,
                strict_min_evidence=safe_min_ev,
            )
        except Exception as e:
            console.print("[red]Konsolidering via daemon misslyckades.[/red]")
            console.print(f"[dim]{e}[/dim]")
            raise typer.Exit(1)
    else:
        try:
            field = FieldSurface(read_only=False)
        except Exception as e:
            console.print("[red]Kunde inte öppna grafen för lokal konsolidering.[/red]")
            console.print(f"[dim]{e}[/dim]")
            raise typer.Exit(1)
        result = MemoryStore().consolidate(
            field,
            max_episodes=safe_max,
            strict_min_evidence=safe_min_ev,
        )

    if result.get("ok") is False:
        console.print("[red]Konsolidering misslyckades.[/red]")
        console.print(f"[dim]{result.get('error', 'okänt fel')}[/dim]")
        raise typer.Exit(1)

    console.print(
        f"[bold cyan]Memory Consolidation[/bold cyan]  "
        f"eps={int(result.get('processed_episodes', 0) or 0)} "
        f"rels={int(result.get('consolidated_relations', 0) or 0)} "
        f"facts={int(result.get('semantic_facts_before', 0) or 0)}→"
        f"{int(result.get('semantic_facts_after', 0) or 0)} "
        f"uncon={int(result.get('unconsolidated_before', 0) or 0)}→"
        f"{int(result.get('unconsolidated_after', 0) or 0)}"
    )


@app.command(name="knowledge-audit")
def knowledge_audit_cmd(
    limit: int = typer.Option(30, "--limit", "-l", help="Max antal saknade noder att visa"),
    strict: bool = typer.Option(
        True,
        "--strict/--basic",
        help="Strict kräver evidensklassning + tillräcklig evidens per claim.",
    ),
    min_evidence_score: float = typer.Option(
        0.65,
        "--min-evidence-score",
        help="Min score för att evidens ska räknas som stark i strict-läge.",
    ),
) -> None:
    """Visa om noder har både kontext och fakta."""
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
                "[yellow]Daemon saknar knowledge-endpoint (äldre version) — kör lokal audit.[/yellow]"
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
    """Fyll saknade nodprofiler så varje nod får kontext + fakta."""
    from nouse.client import daemon_running, post_knowledge_backfill
    from nouse.field.surface import FieldSurface

    safe_limit = None
    if limit is not None:
        safe_limit = max(1, min(limit, 100000))
    min_score = max(0.0, min(1.0, float(min_evidence_score)))

    if daemon_running():
        try:
            result = post_knowledge_backfill(
                limit=safe_limit,
                strict=strict,
                min_evidence_score=min_score,
            )
            trace_id = result.get("trace_id")
        except Exception:
            console.print(
                "[yellow]Daemon saknar knowledge-endpoint (äldre version) — kör lokal backfill.[/yellow]"
            )
            try:
                field = FieldSurface(read_only=False)
                result = field.backfill_missing_concept_knowledge(
                    limit=safe_limit,
                    strict=strict,
                    min_evidence_score=min_score,
                )
                trace_id = None
            except Exception as e:
                console.print(
                    "[red]Kunde inte köra lokal backfill när daemon redan låser DB.[/red]"
                )
                console.print(f"[dim]{e}[/dim]")
                console.print(
                    "[dim]Lösning: restarta daemon till senaste kod och kör igen.[/dim]"
                )
                raise typer.Exit(1)
    else:
        field = FieldSurface(read_only=False)
        result = field.backfill_missing_concept_knowledge(
            limit=safe_limit,
            strict=strict,
            min_evidence_score=min_score,
        )
        trace_id = None

    updated = int(result.get("updated", 0) or 0)
    requested = int(result.get("requested", 0) or 0)
    after = result.get("after") or {}
    remaining = int(after.get("missing_total", 0) or 0)
    console.print(
        f"[bold cyan]Knowledge Backfill[/bold cyan]  mode={'strict' if strict else 'basic'} "
        f"updated={updated}/{requested}  remaining_missing={remaining}"
    )
    if trace_id:
        console.print(f"[dim]trace_id: {trace_id}[/dim]")


@app.command()
def trace(
    start: str = typer.Argument(..., help="Startkoncept eller domän"),
    end:   str = typer.Argument(..., help="Målkoncept eller domän"),
    hops:  int = typer.Option(10, "--hops", "-h", help="Max hopp per stig"),
    paths: int = typer.Option(3,  "--paths", "-p", help="Max antal stigar"),
    minimal: bool = typer.Option(
        True,
        "--minimal/--all",
        help="Visa bara minsta kärnkedjan (default) eller alla stigar.",
    ),
    atomic: bool = typer.Option(
        False,
        "--atomic",
        help="Visa atomiska antaganden per hopp.",
    ),
) -> None:
    """
    Spåra resoneringskedjan mellan två koncept/domäner.
    Visar why, styrka och domänövergång per hopp — för att studera hur kopplingarna sitter.
    """
    from nouse.client import daemon_running, get_trace
    from nouse.field.surface import FieldSurface

    if daemon_running():
        data    = get_trace(start, end, max_hops=hops, max_paths=paths)
        results = data.get("paths", [])
    else:
        try:
            field   = FieldSurface(read_only=True)
            results = field.trace_path(start, end, max_hops=hops, max_paths=paths)
        except RuntimeError as e:
            if "Could not set lock on file" in str(e):
                console.print(
                    "[red]Kunde inte läsa grafen p.g.a. fillås.[/red]\n"
                    "[dim]Tips:[/dim] starta API-läget med `nouse daemon web` "
                    "eller stoppa skrivande process innan trace."
                )
                raise typer.Exit(2)
            raise

    if not results:
        console.print(f"[red]Ingen stig hittad: {start} → {end}[/red]")
        raise typer.Exit(1)

    if minimal:
        results = [_best_minimal_path(results)]

    console.print(f"\n[bold cyan]TRACE[/bold cyan]  "
                  f"[yellow]{start}[/yellow] → [green]{end}[/green]  "
                  f"[dim]{len(results)} stig{'ar' if len(results)>1 else ''}[/dim]\n")

    for i, path in enumerate(results, 1):
        domains = sorted({s["src_domain"] for s in path} | {path[-1]["tgt_domain"]})
        console.print(f"[bold]── Stig {i}[/bold]  {len(path)} hopp  "
                      f"[dim]{' · '.join(domains)}[/dim]")

        prev_domain = None
        for j, step in enumerate(path):
            # Källnod (bara för första hopp)
            if j == 0:
                dom_shift = step["src_domain"] != prev_domain
                console.print(
                    f"  [yellow]{step['src']}[/yellow]  "
                    f"[dim]{step['src_domain']}[/dim]"
                )
            # Kant
            why_str = f"  [dim italic]\"{step['why'][:90]}\"[/dim italic]" \
                      if step["why"] else ""
            ev = step.get("evidence_score")
            ev_str = f" · ev=[bold]{float(ev):.2f}[/bold]" if ev is not None else ""
            af = step.get("assumption_flag")
            af_str = " · [yellow]antagande[/yellow]" if af is True else (" · [green]evidens[/green]" if af is False else "")
            console.print(
                f"  [dim]↓[/dim] [cyan]{step['rel_type']}[/cyan]  "
                f"styrka=[bold]{step['strength']:.2f}[/bold]{ev_str}{af_str}"
                f"{why_str}"
            )
            # Målnod — markera domänövergång
            domain_changed = step["tgt_domain"] != step["src_domain"]
            marker = "  [magenta]◈ domänkorsning[/magenta]" if domain_changed else ""
            node_markup = (f"[bold green]{step['tgt']}[/bold green]"
                           if domain_changed else f"[yellow]{step['tgt']}[/yellow]")
            console.print(
                f"  {node_markup}  "
                f"[dim]{step['tgt_domain']}[/dim]{marker}"
            )
            if atomic:
                for assumption in _edge_assumptions(step):
                    console.print(f"    [dim]· antagande:[/dim] {assumption}")
            prev_domain = step["tgt_domain"]
        console.print()


@app.command(name="run")
def run_brain(
    model: str = typer.Option("", "--model", "-m", help="LLM-modell (tom = autodiscover från model_policy.json)"),
    provider: str = typer.Option("", "--provider", "-p", help="Provider: ollama | openai | anthropic | copilot"),
    no_learn: bool = typer.Option(False, "--no-learn", help="Stäng av bakgrundsinlärning"),
    no_context: bool = typer.Option(False, "--no-context", help="Stäng av grafkontextberikelse"),
) -> None:
    """Starta Nouse REPL — fungerar med Ollama, Claude, OpenAI, Copilot eller valfri LLM."""
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
    """Samtalsläge för idéutbyte och relationsbyggande med b76."""
    from nouse.cli.companion import run
    run(topic=topic, model=model, profile=profile)


@app.command(name="scan-disk")
def scan_disk_cmd(
    paths: list[str] = typer.Argument(
        None,
        help="Sökvägar att skanna (standard: hemkatalog)",
    ),
    max_files: int = typer.Option(
        2000, "--max-files", "-n",
        help="Max antal filer i ingest-planen",
    ),
    threshold: float = typer.Option(
        0.55, "--threshold", "-t",
        help="Minimumpoäng för att ta med en fil (0–1)",
    ),
    save: bool = typer.Option(
        False, "--save", "-s",
        help="Spara ingest-plan för daemon att hämta",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Hoppa över interaktiv bekräftelse",
    ),
) -> None:
    """
    Kartlägg disken och skapa ett rankat ingest-förslag.

    Fas 1: Snabb filsystemsscanning (inga LLM-anrop).
    Fas 2: Rankat förslag — visa och låt dig skala av.

    Exempel:
      b76 scan-disk                           # skanna hemkatalog
      b76 scan-disk /home/bjorn /media/data   # skanna flera
      b76 scan-disk --save                    # spara plan för daemon
    """
    from nouse.daemon.disk_mapper import DiskMapper

    roots = paths if paths else [str(Path.home())]
    console.print(f"\n[bold cyan]Skannar:[/bold cyan] {', '.join(roots)}")
    console.print("[dim]Fas 1: räknar filer (inga LLM-anrop)...[/dim]\n")

    mapper = DiskMapper(roots)
    report = mapper.scan()
    plan = mapper.plan(report, max_files=max_files, score_threshold=threshold)
    mapper.present(report, plan)

    if report.noise_dirs and not yes:
        console.print("[yellow]Brus-kataloger hittades. Vill du utesluta dem?[/yellow]")
        confirm = typer.confirm("Uteslut föreslagna brus-kataloger?", default=True)
        if not confirm:
            plan = mapper.plan(
                report,
                max_files=max_files,
                score_threshold=threshold,
                skip_dirs=[],
            )

    if not yes:
        console.print(
            f"\n[bold]Plan: {plan.estimated_files:,} filer, "
            f"~{plan.estimated_llm_calls:,} LLM-anrop[/bold]"
        )
        new_max = typer.prompt(
            "Hur många filer vill du indexera? (Enter = behåll förslag)",
            default=str(plan.estimated_files),
        )
        try:
            new_max_int = int(new_max)
            if new_max_int != plan.estimated_files:
                plan = mapper.plan(
                    report,
                    max_files=new_max_int,
                    score_threshold=threshold,
                )
                console.print(f"[green]Plan uppdaterad: {plan.estimated_files:,} filer[/green]")
        except ValueError:
            pass

    if save or (not yes and typer.confirm("Spara plan för daemon?", default=True)):
        saved = plan.save()
        console.print(f"\n[green]✓ Plan sparad:[/green] {saved}")
        console.print("[dim]Daemonen hämtar planen vid nästa körning.[/dim]")
    else:
        console.print("\n[dim]Plan ej sparad.[/dim]")


@app.command(name="llm")
def llm_cmd(
    action: str = typer.Argument(
        "status",
        help="Åtgärd: detect | setup | status",
    ),
    prefer: str | None = typer.Option(
        None, "--prefer",
        help="Föredragen provider: ollama | lm_studio | copilot | anthropic | openai | groq | openrouter | custom",
    ),
    model: str | None = typer.Option(
        None, "--model", "-m",
        help="Sätt en specifik modell för alla workloads",
    ),
) -> None:
    """Hantera LLM-providers — auto-detect och konfigurera.

    Exempel:
      b76 llm detect                    # visa alla tillgängliga providers
      b76 llm setup                     # välj bästa automatiskt
      b76 llm setup --prefer copilot    # tvinga GitHub Copilot
      b76 llm setup --prefer ollama     # tvinga lokal Ollama
      b76 llm status                    # visa aktiv konfiguration
    """
    from nouse.llm.autodiscover import detect_providers, apply_best, DiscoveredProvider
    from nouse.llm.policy import MODEL_POLICY_PATH
    from rich.table import Table
    import json

    if action in ("detect", "setup"):
        console.print("[dim]Söker LLM-providers…[/dim]")
        providers = detect_providers()

        if not providers:
            console.print("[red]Inga providers hittades.[/red]")
            console.print(
                "\nKör Ollama lokalt:  [cyan]ollama serve[/cyan]\n"
                "Eller sätt en av:   [cyan]ANTHROPIC_API_KEY | OPENAI_API_KEY | "
                "GITHUB_TOKEN | GROQ_API_KEY | OPENROUTER_API_KEY[/cyan]"
            )
            raise typer.Exit(1)

        t = Table(title="Tillgängliga LLM-providers", show_header=True)
        t.add_column("#",        style="dim",   width=3)
        t.add_column("Provider", style="cyan",  min_width=22)
        t.add_column("Modeller", style="white", min_width=28)
        t.add_column("Latens",   style="green", width=10)
        t.add_column("Not",      style="dim")

        for i, p in enumerate(providers, 1):
            models_str = ", ".join(p.available_models[:3])
            if len(p.available_models) > 3:
                models_str += f"  (+{len(p.available_models)-3})"
            t.add_row(
                str(i),
                p.label(),
                models_str or "–",
                f"{p.latency_ms:.0f} ms" if p.latency_ms else "–",
                p.note,
            )
        console.print(t)

        if action == "detect":
            return

        # setup: välj och skriv policy
        chosen_kind = prefer
        if not chosen_kind and len(providers) > 1:
            choices = [f"{p.label()} [{p.kind}]" for p in providers]
            choice_str = "\n".join(f"  {i}. {c}" for i, c in enumerate(choices, 1))
            console.print(f"\n[bold]Välj provider:[/bold]\n{choice_str}\n")
            raw = typer.prompt("Nummer eller namn", default="1").strip()
            try:
                idx = int(raw) - 1
                chosen_kind = providers[idx].kind
            except (ValueError, IndexError):
                chosen_kind = raw.lower()

        chosen = apply_best(providers, preferred_kind=chosen_kind)  # type: ignore[arg-type]
        if not chosen:
            console.print("[red]Kunde inte sätta provider.[/red]")
            raise typer.Exit(1)

        # Valfritt: sätt specifik modell för alla workloads
        if model:
            pol = json.loads(MODEL_POLICY_PATH.read_text())
            for wl in pol.get("workloads", {}):
                pol["workloads"][wl]["candidates"] = [model]
            MODEL_POLICY_PATH.write_text(json.dumps(pol, indent=2))
            console.print(f"  Modell satt: [bold]{model}[/bold] (alla workloads)")

        console.print(
            f"\n[green]✓ LLM-provider satt:[/green] [bold]{chosen.label()}[/bold]\n"
            f"  Endpoint: {chosen.base_url}\n"
            f"  Policy:   {MODEL_POLICY_PATH}"
        )

    elif action == "status":
        if not MODEL_POLICY_PATH.exists():
            console.print("[yellow]Ingen model_policy.json — kör 'nouse llm setup'[/yellow]")
            raise typer.Exit(0)

        pol = json.loads(MODEL_POLICY_PATH.read_text())
        auto = pol.get("_autodiscovered", {})
        t = Table(title="Aktiv LLM-konfiguration", show_header=False)
        t.add_column("", style="cyan")
        t.add_column("", style="white")
        t.add_row("Provider", auto.get("label") or "manuell")
        t.add_row("Endpoint", auto.get("base_url") or "–")
        for wl, cfg in pol.get("workloads", {}).items():
            cands = cfg.get("candidates", [])
            t.add_row(f"  {wl}", cands[0] if cands else "–")
        console.print(t)

    else:
        console.print(f"[red]Okänd åtgärd: '{action}'. Välj: detect | setup | status[/red]")
        raise typer.Exit(1)


@app.command(name="setup")
def setup_cmd(
    tier: str | None = typer.Argument(
        None,
        help="Lagringsprofil: small | medium | large",
    ),
    cloud_db_url: str = typer.Option(
        "", "--cloud-db", help="URL till extern cloud-DB (medium: Qdrant, Pinecone etc.)"
    ),
    max_db_gb: float | None = typer.Option(
        None, "--max-db-gb", help="Anpassad max storlek för field.sqlite (GB)"
    ),
    status: bool = typer.Option(
        False, "--status", "-s", help="Visa aktiv tier och disk-hälsa"
    ),
) -> None:
    """Konfigurera lagringsprofil (small / medium / large).

    Exempel:
      b76 setup                    # interaktivt val
      b76 setup small              # laptop/testmiljö, max 10 GB, LLM online
      nouse setup medium             # desktop, max 100 GB, kontext per nod
      b76 setup large              # airgap/enterprise, max 500 GB, hela disken
      b76 setup --status           # visa aktiv profil och disk-hälsa
      nouse setup medium --cloud-db http://localhost:6333
    """
    from nouse.daemon.storage_tier import (
        StorageTierConfig, TIER_DESCRIPTIONS, TIER_DEFAULTS, check_disk_health,
    )

    if status or (tier is None and not cloud_db_url and max_db_gb is None):
        # Visa status
        health = check_disk_health()
        cfg    = StorageTierConfig.load()
        from rich.table import Table
        t = Table(title=f"Nouse Lagringsprofil — [bold]{cfg.tier.upper()}[/bold]", show_header=False)
        t.add_column("", style="cyan")
        t.add_column("", style="white")
        limits = cfg.limits()
        t.add_row("Aktiv tier",       cfg.tier.upper())
        t.add_row("Max DB-storlek",   f"{limits.max_db_gb:.0f} GB")
        t.add_row("Nuvarande DB",     f"{health['current_gb']:.1f} GB  ({health['pct']:.0f}%)")
        t.add_row("Kontext/nod",      f"{limits.context_per_node_chars:,} tecken" if limits.context_per_node_chars else "ingen (live)")
        t.add_row("Max filer-scan",   f"{limits.max_scan_files:,}")
        t.add_row("Hämta online",     "ja" if limits.fetch_online else "nej (airgap)")
        t.add_row("Cloud-DB",         limits.cloud_db_url or "–")
        t.add_row("NightRun tröskel", f"{limits.nightrun_min_evidence:.2f}")
        t.add_row("Prune under",      f"{limits.prune_below_weight:.2f}")
        console.print(t)
        if health["warning"]:
            console.print(f"\n{health['warning']}")

        if tier is None:
            # Interaktivt val om ingen tier angetts
            console.print("\n[bold]Välj lagringsprofil:[/bold]")
            for name, desc in TIER_DESCRIPTIONS.items():
                console.print(f"\n  [cyan]{name.upper()}[/cyan]\n{desc}")
            chosen = typer.prompt(
                "\nProfil",
                default=cfg.tier,
                show_default=True,
            ).strip().lower()
            if chosen not in TIER_DEFAULTS:
                console.print(f"[red]Ogiltigt val: '{chosen}'[/red]")
                raise typer.Exit(1)
            tier = chosen

        if tier == cfg.tier and not cloud_db_url and max_db_gb is None:
            return  # inget att ändra

    valid = set(TIER_DEFAULTS.keys())
    if tier not in valid:
        console.print(f"[red]Ogiltigt tier '{tier}'. Välj: {', '.join(valid)}[/red]")
        raise typer.Exit(1)

    cfg = StorageTierConfig.load()
    cfg.tier = tier  # type: ignore[assignment]
    if cloud_db_url:
        cfg.cloud_db_url = cloud_db_url
    if max_db_gb is not None:
        cfg.custom_max_db_gb = max_db_gb
    cfg.save()

    limits = cfg.limits()
    console.print(f"\n[green]✓ Lagringsprofil satt till [bold]{tier.upper()}[/bold][/green]")
    console.print(f"  Max DB:          {limits.max_db_gb:.0f} GB")
    console.print(f"  Kontext/nod:     {'ingen (live)' if not limits.context_per_node_chars else str(limits.context_per_node_chars) + ' tecken'}")
    console.print(f"  Max filer-scan:  {limits.max_scan_files:,}")
    console.print(f"  Online-hämtning: {'ja' if limits.fetch_online else 'nej (airgap)'}")
    if limits.cloud_db_url:
        console.print(f"  Cloud-DB:        {limits.cloud_db_url}")


@app.command(name="nightrun")
def nightrun_cmd(
    action: str = typer.Argument(
        "status",
        help="Åtgärd: status | now | config",
    ),
    mode: str | None = typer.Option(
        None, "--mode", help="Schema-mode: idle | night | always | never"
    ),
    idle_minutes: int | None = typer.Option(
        None, "--idle-minutes", help="Minuter inaktivitet före körning (mode=idle)"
    ),
) -> None:
    """Hantera NightRun — konsolidering av arbetsminne till FieldSurface.

    Exempel:
      b76 nightrun status              # visa senaste körning
      b76 nightrun now                 # kör direkt (blockerar)
      nouse nightrun config --mode idle --idle-minutes 30
      nouse nightrun config --mode night
      nouse nightrun config --mode never
    """
    import asyncio
    from nouse.daemon.nightrun import NightRunConfig, NightRunStatus, run_night_consolidation
    from nouse.daemon.node_inbox import get_inbox

    if action == "status":
        status = NightRunStatus.load()
        cfg    = NightRunConfig.load()
        from rich.table import Table
        from datetime import datetime, timezone
        t = Table(title="NightRun Status", show_header=False)
        t.add_column("Fält",  style="cyan")
        t.add_column("Värde", style="white")
        last = (
            datetime.fromtimestamp(status.last_run_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if status.last_run_ts else "–"
        )
        t.add_row("Schema",          f"mode={cfg.mode}, idle={cfg.idle_minutes}min")
        t.add_row("Senaste körning", last)
        t.add_row("Körtid",          f"{status.last_run_duration:.1f}s")
        t.add_row("Konsoliderade",   str(status.total_consolidated))
        t.add_row("Kasserade",       str(status.total_discarded))
        t.add_row("Bisociationer",   str(status.total_bisociations))
        t.add_row("Prunade",         str(status.total_pruned))
        if status.last_error:
            t.add_row("[red]Senaste fel[/red]", status.last_error)
        console.print(t)

    elif action == "config":
        cfg = NightRunConfig.load()
        if mode is not None:
            valid = {"idle", "night", "always", "never"}
            if mode not in valid:
                console.print(f"[red]Ogiltigt mode '{mode}'. Välj: {', '.join(valid)}[/red]")
                raise typer.Exit(1)
            cfg.mode = mode  # type: ignore[assignment]
        if idle_minutes is not None:
            cfg.idle_minutes = idle_minutes
        cfg.save()
        console.print(f"[green]✓ NightRun konfigurerad:[/green] mode={cfg.mode}, idle={cfg.idle_minutes}min")

    elif action == "now":
        console.print("[yellow]▶ NightRun startar manuellt…[/yellow]")
        from nouse.client import daemon_running, post_nightrun_now
        if daemon_running():
            try:
                r = post_nightrun_now(dry_run=False)
                if r.get("ok"):
                    console.print(
                        f"[green]✓ Klar[/green]: konsoliderat=[bold]{r.get('consolidated', 0)}[/bold] "
                        f"kasserat={r.get('discarded', 0)} bisociationer={r.get('bisociations', 0)} "
                        f"berikat={r.get('enriched', 0)} pruning={r.get('pruned', 0)} "
                        f"({r.get('duration', 0.0):.1f}s)"
                    )
                else:
                    console.print(f"[red]Daemonen svarade fel: {r.get('error')}[/red]")
                return
            except Exception as e:
                err = str(e)
                if "404" in err:
                    console.print(
                        "[yellow]Daemonen kör en äldre version.[/yellow]\n"
                        "Starta om med:  [cyan]systemctl --user restart nouse-brain[/cyan]"
                    )
                    raise typer.Exit(1)
                console.print(f"[yellow]Daemon-anrop misslyckades: {e}[/yellow]")

        from nouse.field.surface import FieldSurface
        from nouse.daemon.state import load_state
        from nouse.client import daemon_running as _nr_daemon_running
        db_path = Path.home() / ".local" / "share" / "nouse" / "field.sqlite"
        if not db_path.exists():
            console.print("[red]Ingen FieldSurface hittad. Kör 'nouse run' minst en gång.[/red]")
            raise typer.Exit(1)
        if _nr_daemon_running():
            console.print("[red]Daemon kör — nightrun bör triggas via daemon-API.[/red]")
            console.print("Kör: [bold]nouse nightrun now[/bold] (som redan försöktes ovan)")
            raise typer.Exit(1)
        field  = FieldSurface(db_path=str(db_path))
        limbic = load_state()
        inbox  = get_inbox()
        result = asyncio.run(run_night_consolidation(field, inbox, limbic))
        console.print(
            f"[green]✓ Klar[/green]: konsoliderat=[bold]{result.consolidated}[/bold] "
            f"kasserat={result.discarded} bisociationer={result.bisociations} "
            f"berikat={result.enriched} pruning={result.pruned} ({result.duration:.1f}s)"
        )

    else:
        console.print(f"[red]Okänd åtgärd: '{action}'. Välj: status | now | config[/red]")
        raise typer.Exit(1)


@app.command(name="enrich-nodes")
def enrich_nodes_cmd(
    max_nodes: int = typer.Option(
        50, "--max", "-n", help="Max antal noder att berika"
    ),
    max_minutes: float = typer.Option(
        15.0, "--minutes", "-t", help="Max körtid i minuter"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Simulera utan att skriva till grafen"
    ),
) -> None:
    """Berika noder som saknar kontext med LLM-genererade summaries.

    Respekterar aktiv lagringsprofil (nouse setup):
      small:  Graph-backfill utan LLM
      medium: LLM-summary från källfiler (2 000 tecken/nod)
      large:  LLM-summary med djupare analys (10 000 tecken/nod)

    Exempel:
      b76 enrich-nodes                 # berika 50 noder
      b76 enrich-nodes --max 200       # berika upp till 200 noder
      b76 enrich-nodes --dry-run       # testa utan att ändra
    """
    import asyncio
    from pathlib import Path
    from nouse.field.surface import FieldSurface
    from nouse.daemon.node_context import enrich_nodes
    from nouse.daemon.storage_tier import get_tier
    from nouse.client import daemon_running, post_knowledge_enrich

    tier   = get_tier()
    limits = tier.limits()
    console.print(
        f"[dim]Tier: {tier.tier.upper()} — "
        f"{'LLM disabled (small)' if not limits.context_per_node_chars else str(limits.context_per_node_chars) + ' tecken/nod'}[/dim]"
    )
    if dry_run:
        console.print("[yellow]⚠ dry-run — inga ändringar sparas[/yellow]")

    # Om daemonen kör: använd API (undviker KuzuDB-lock)
    if daemon_running():
        try:
            r = post_knowledge_enrich(max_nodes=max_nodes, max_minutes=max_minutes, dry_run=dry_run)
            if r.get("ok"):
                console.print(
                    f"[green]✓ Klar[/green]: berikat=[bold]{r.get('enriched', 0)}[/bold] "
                    f"hoppade={r.get('skipped', 0)} misslyckade={r.get('failed', 0)} "
                    f"({r.get('duration', 0.0):.1f}s)"
                )
            else:
                console.print(f"[red]Daemonen svarade fel: {r.get('error')}[/red]")
            return
        except Exception as e:
            err = str(e)
            if "404" in err:
                console.print(
                    "[yellow]Daemonen kör en äldre version (saknar /api/knowledge/enrich).[/yellow]\n"
                    "Starta om med:  [cyan]systemctl --user restart nouse-brain[/cyan]"
                )
            else:
                console.print(f"[yellow]Daemon-anrop misslyckades: {e}[/yellow]")
            raise typer.Exit(1)

    db_path = Path.home() / ".local" / "share" / "nouse" / "field.sqlite"
    if not db_path.exists():
        console.print("[red]Ingen FieldSurface hittad. Kör 'nouse run' minst en gång.[/red]")
        raise typer.Exit(1)

    from nouse.client import daemon_running as _en_daemon_running
    if _en_daemon_running():
        console.print("[red]Daemon kör — kan inte öppna grafen direkt.[/red]")
        console.print("Använd: [bold]nouse enrich-nodes --via-daemon[/bold] eller stoppa daemon först.")
        raise typer.Exit(1)
    field  = FieldSurface(db_path=str(db_path))
    result = asyncio.run(
        enrich_nodes(field, max_nodes=max_nodes, max_minutes=max_minutes, dry_run=dry_run)
    )
    console.print(
        f"[green]✓ Klar[/green]: berikat=[bold]{result.enriched}[/bold] "
        f"hoppade={result.skipped} misslyckade={result.failed} ({result.duration:.1f}s)"
    )


@app.command(name="deepdive")
def deepdive_cmd(
    node: str | None = typer.Argument(
        None,
        help="Nodnamn att djupdyka. Utelämnas = batch på top-N noder.",
    ),
    max_nodes: int = typer.Option(5, "--max", "-n",
                                  help="Max noder vid batch-körning."),
    max_minutes: float = typer.Option(20.0, "--minutes", "-m",
                                      help="Tidsgräns i minuter."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Testa utan att ändra grafen."),
    review_queue: bool = typer.Option(False, "--review-queue", "-r",
                                      help="Töm ReviewQueue (indikerade granskningar)."),
) -> None:
    """
    Axiom-discovery: djupanalys av noder i kunskapsgrafen.

    Varje nod genomgår:
      1. LLM-kunskapsverifiering  — vad vet modellen om noden?
      2. Webb-korscheck           — verifiera mot aktuella källor
      3. Claim-kontrastering      — hitta motsägelser i grafen
      4. Korrelationsanalys       — strukturellt liknande noder
      5. Axiom-discovery          — generalisera mönster till nya sanningar

    Starka axiom (ev>=0.75) skrivs direkt.
    Svaga (ev<0.75) flaggas och hamnar i ReviewQueue för djupare granskning
    vid indikerad användning.

    Exempel:
      b76 deepdive                      # batch på 5 noder
      b76 deepdive havströmmar          # djupdyk en specifik nod
      b76 deepdive --review-queue       # töm ReviewQueue direkt
    """
    import asyncio
    from nouse.field.surface import FieldSurface
    from nouse.daemon.node_deepdive import deepdive_node, deepdive_batch, get_review_queue

    db_path = Path.home() / ".local" / "share" / "nouse" / "field.sqlite"
    if not db_path.exists():
        console.print("[red]Ingen FieldSurface hittad. Kör 'nouse run' minst en gång.[/red]")
        raise typer.Exit(1)

    # Daemon-first: om daemon kör, dirigera dit istället för att öppna DB direkt
    from nouse.client import daemon_running
    if daemon_running():
        if not dry_run:
            console.print("[yellow]Daemon kör — deepdive via API körs i NightRun.[/yellow]")
            console.print("Trigga manuellt: [bold]nouse nightrun now[/bold]")
            raise typer.Exit(0)
        # dry_run/read-only: öppna i read_only-läge
        field = FieldSurface(db_path=str(db_path), read_only=True)
    else:
        field = FieldSurface(db_path=str(db_path))

    # ── ReviewQueue-tömning ───────────────────────────────────────────────────
    if review_queue:
        rq      = get_review_queue()
        pending = rq.pending_count()
        if pending == 0:
            console.print("[dim]ReviewQueue är tom — inga väntande granskningar.[/dim]")
            raise typer.Exit(0)
        console.print(f"[cyan]ReviewQueue: {pending} granskningar att bearbeta...[/cyan]")
        verdicts = asyncio.run(rq.flush_pending(field, max_reviews=pending, dry_run=dry_run))
        promoted  = sum(1 for v in verdicts if v.outcome == "promote")
        discarded = sum(1 for v in verdicts if v.outcome == "discard")
        kept      = len(verdicts) - promoted - discarded
        console.print(
            f"[green]✓ ReviewQueue klar[/green]: "
            f"befordrade=[bold]{promoted}[/bold] "
            f"kasserade={discarded} behållna={kept}"
        )
        raise typer.Exit(0)

    # ── Enskild nod ──────────────────────────────────────────────────────────
    if node:
        console.print(f"[cyan]DeepDive: {node}...[/cyan]")
        result = asyncio.run(deepdive_node(node, field, dry_run=dry_run))
        console.print(
            f"[green]✓ Klar[/green]: "
            f"verified={len(result.llm_verified)} "
            f"challenged={len(result.llm_challenged)} "
            f"web_facts={len(result.web_new_facts)} "
            f"contradictions={len(result.contradictions)} "
            f"shadows={len(result.shadow_nodes)} "
            f"axioms={len(result.axiom_candidates)} "
            f"committed=[bold]{result.committed}[/bold] "
            f"flagged={result.flagged} ({result.duration:.1f}s)"
        )
        if result.axiom_candidates:
            console.print("\n[bold]Axiom-kandidater:[/bold]")
            for ax in result.axiom_candidates:
                status = "[green]COMMIT[/green]" if ax.auto_commit else "[yellow]FLAG[/yellow]"
                console.print(
                    f"  {status} {ax.src} -[{ax.rel_type}]-> {ax.tgt}  "
                    f"ev={ax.evidence_score:.2f}  ({ax.source})"
                )
        raise typer.Exit(0)

    # ── Batch ─────────────────────────────────────────────────────────────────
    console.print(f"[cyan]DeepDive batch: max {max_nodes} noder, {max_minutes:.0f} min...[/cyan]")
    batch = asyncio.run(deepdive_batch(
        field, max_nodes=max_nodes, max_minutes=max_minutes, dry_run=dry_run
    ))
    console.print(
        f"[green]✓ Batch klar[/green]: "
        f"noder={batch.nodes_processed} "
        f"committed=[bold]{batch.total_committed}[/bold] "
        f"flagged={batch.total_flagged} ({batch.duration:.1f}s)"
    )


@app.command()
def enrich(
    rounds:      int   = typer.Option(2,   "--rounds",   "-r", help="Antal BFS-rundor"),
    budget:      int   = typer.Option(30,  "--budget",   "-b", help="Max noder per runda"),
    max_degree:  int   = typer.Option(3,   "--max-degree",     help="Noder med ≤N kanter bearbetas"),
    concurrency: int   = typer.Option(3,   "--concurrency",    help="Parallella LLM-anrop"),
    strategy:    str   = typer.Option("gravity", "--strategy", "-s",
                                      help="gravity | periphery | random"),
    dry_run:     bool  = typer.Option(False,"--dry-run",        help="Visa kandidater utan att skriva"),
) -> None:
    """
    Berika isolerade noder via frontier LLM.

    Hittar noder med få kanter och ber GPT aktivt fylla i strukturella
    relationer — hierarkiska, korsdomän och mekanistiska kopplingar.
    Körs i BFS-rundor: varje ny nod som skapas seedar nästa runda.

    Strategier:
      gravity   — Noder NÄRA ett hub bearbetas först. Minskar tomrymden
                  runt klustercentrum. Bäst för att förtäta det du vet.
      periphery — Noder LÄNGST från alla hub. Utforskar okänd terräng.
      random    — Baslinje.

    Exempel:
      nouse enrich --rounds 2 --budget 50
      nouse enrich --strategy periphery --budget 100
      nouse enrich --max-degree 1 --budget 100  # bara orphans
    """
    import asyncio
    from nouse.field.surface import FieldSurface
    from nouse.field.limbic_state import LimbicState
    from nouse.learning_coordinator import LearningCoordinator

    console.print(
        f"[cyan]GraphEnricher start:[/cyan] rounds={rounds}, budget={budget}/runda, "
        f"max_degree={max_degree}, concurrency={concurrency}, strategy=[bold]{strategy}[/bold]"
        + (" [yellow](dry-run)[/yellow]" if dry_run else "")
    )

    if dry_run:
        # Visa kandidater utan att skriva
        try:
            field = FieldSurface(read_only=True)
        except RuntimeError:
            console.print("[red]Databasen låst — stoppa daemon eerst (nouse daemon stop)[/red]")
            raise typer.Exit(1)
        from nouse.daemon.graph_enricher import _compute_degrees, _find_sparse_nodes
        degrees = _compute_degrees(field)
        candidates = _find_sparse_nodes(field, degrees, max_degree, budget, set(), True, strategy)
        console.print(f"\n[bold]Kandidater ({len(candidates)} st med ≤{max_degree} kanter, strategy={strategy}):[/bold]")
        for name, domain in candidates[:20]:
            deg = degrees.get(name, 0)
            console.print(f"  [dim]{domain:25}[/dim]  {name}  [dim](grad={deg})[/dim]")
        if len(candidates) > 20:
            console.print(f"  [dim]... och {len(candidates)-20} till[/dim]")
        return

    try:
        field = FieldSurface()
    except RuntimeError as e:
        if "lock" in str(e).lower():
            console.print("[red]Databasen låst — stoppa daemon först (nouse daemon stop)[/red]")
        else:
            console.print(f"[red]Fel: {e}[/red]")
        raise typer.Exit(1)

    limbic = LimbicState()
    coordinator = LearningCoordinator(field, limbic)

    from nouse.daemon.graph_enricher import run_enrichment
    stats = asyncio.run(run_enrichment(
        field, coordinator,
        max_degree=max_degree,
        rounds=rounds,
        budget_per_round=budget,
        concurrency=concurrency,
        strategy=strategy,
    ))

    console.print(
        f"\n[green bold]✓ Berikningsklar[/green bold]\n"
        f"  Noder bearbetade : [bold]{stats.nodes_processed}[/bold]\n"
        f"  Relationer tillagda: [bold]{stats.relations_added}[/bold]\n"
        f"  Korsdomänlänkar  : [bold]{stats.cross_domain_links}[/bold]\n"
        f"  Nya noder funna  : [bold]{stats.new_nodes_discovered}[/bold]\n"
        f"  Rundor           : {stats.rounds_completed}/{rounds}\n"
        f"  Fel              : [dim]{stats.errors}[/dim]"
    )


@app.command()
def bridge(
    concept_a:   str        = typer.Argument(...,    help="Startkoncept, t.ex. 'svampsoppa'"),
    concept_b:   str        = typer.Argument("",     help="Målkoncept (tomt = korsdomän-discovery)"),
    domains:     str        = typer.Option("",       "--domains", "-d",
                                           help="Komma-sep domäner för korsdomän-discovery"),
    max_pairs:   int        = typer.Option(20,       "--max-pairs", "-n",
                                           help="Max par att evaluera vid discovery"),
    sample:      int        = typer.Option(5,        "--sample",
                                           help="Noder per domän vid discovery"),
    force:       bool       = typer.Option(False,    "--force",
                                           help="Bygg brygga även om väg redan finns i grafen"),
    show_chain:  bool       = typer.Option(True,     "--show-chain/--no-chain",
                                           help="Visa kopplingkedja i terminalen"),
) -> None:
    """
    Hitta latenta strukturella bryggor mellan orelaterade koncept.

    Specifik brygga:
      nouse bridge svampsoppa kvantfysik
      nouse bridge Wittgenstein "kvantmekanik" --force

    Korsdomän-discovery (samplar alla domäner):
      nouse bridge --domains "filosofi,fysik,biologi" --max-pairs 30
      nouse bridge _auto --max-pairs 50

    Algoritm:
      1. Extrahera axiom-signatur för varje nod (strukturellt fingeravtryck)
      2. Skicka BÅDA signaturerna till frontier LLM
      3. LLM söker den isomorfa kopplingkedjan A→x1→x2→B
      4. Validera varje hopp med Bayesiansk evidensbedömning
      5. Skriv kedjan + META::bridge-nod till grafen
    """
    import asyncio
    from nouse.field.surface import FieldSurface
    from nouse.field.limbic_state import LimbicState
    from nouse.learning_coordinator import LearningCoordinator
    from nouse.field.bridge_finder import (
        discover_bridge, run_cross_domain_discovery,
        extract_axiom_signature,
    )

    try:
        field = FieldSurface()
    except RuntimeError as e:
        if "lock" in str(e).lower():
            console.print("[red]Databasen låst — stoppa daemon eerst (nouse daemon stop)[/red]")
        else:
            console.print(f"[red]Fel: {e}[/red]")
        raise typer.Exit(1)

    limbic = LimbicState()
    coordinator = LearningCoordinator(field, limbic)

    # ── Specifik brygga ────────────────────────────────────────────────────────
    if concept_b and concept_b != "_auto":
        console.print(
            f"[cyan]Söker latent brygga:[/cyan] "
            f"[bold]{concept_a}[/bold] ↔ [bold]{concept_b}[/bold]"
            + (" [dim](force)[/dim]" if force else "")
        )

        # Visa signaturer
        sig_a = extract_axiom_signature(concept_a, field)
        sig_b = extract_axiom_signature(concept_b, field)
        overlap = sig_a.overlap_score(sig_b)

        console.print(f"\n[dim]Axiom-overlap: {overlap:.3f}[/dim]")
        console.print(f"[dim]Signatur {concept_a}: {list(sig_a.structural_pattern)[:6]}[/dim]")
        console.print(f"[dim]Signatur {concept_b}: {list(sig_b.structural_pattern)[:6]}[/dim]")

        bridge_result = asyncio.run(
            discover_bridge(concept_a, concept_b, field, coordinator, force=force)
        )

        if bridge_result is None:
            console.print("\n[yellow]Ingen ny brygga behövs[/yellow] — antingen finns vägen redan "
                          "eller confidence < 0.3. Prova [bold]--force[/bold] eller djupare berikelse.")
            return

        console.print(f"\n[green bold]✓ Brygga kristalliserad![/green bold]")
        console.print(f"  Overlap  : {bridge_result.overlap_score:.3f}")
        console.print(f"  Meta-nod : [dim]{bridge_result.meta_bridge_id}[/dim]")

        if show_chain:
            console.print("\n[bold]Kopplingkedja:[/bold]")
            for i, (node, rel) in enumerate(
                zip(bridge_result.chain, bridge_result.relations + [""])
            ):
                score_str = (
                    f" [dim](ev={bridge_result.evidence_per_hop[i]:.3f})[/dim]"
                    if i < len(bridge_result.evidence_per_hop) else ""
                )
                if i < len(bridge_result.relations):
                    console.print(f"  [bold]{node}[/bold]{score_str}")
                    console.print(f"    [cyan]↓ {rel}[/cyan]")
                else:
                    console.print(f"  [bold]{node}[/bold]{score_str}")

        if bridge_result.why:
            console.print(f"\n[italic dim]{bridge_result.why}[/italic dim]")
        return

    # ── Korsdomän-discovery ────────────────────────────────────────────────────
    domain_list = [d.strip() for d in domains.split(",") if d.strip()] or None
    console.print(
        f"[cyan]Korsdomän-discovery:[/cyan] "
        f"max_pairs={max_pairs}, sample={sample}/domän"
        + (f", domäner=[{', '.join(domain_list)}]" if domain_list else "")
    )

    session = asyncio.run(
        run_cross_domain_discovery(
            field, coordinator,
            domains=domain_list,
            sample_per_domain=sample,
            max_pairs=max_pairs,
        )
    )

    console.print(
        f"\n[green bold]✓ Discovery klar[/green bold]\n"
        f"  Bryggor hittade  : [bold]{session.bridges_found}[/bold]\n"
        f"  Bryggor skrivna  : [bold]{session.bridges_written}[/bold]\n"
        f"  Par evaluerade   : {session.pairs_evaluated}\n"
        f"  Korsdomänpar     : {session.cross_domain_pairs}\n"
        f"  Fel              : [dim]{session.errors}[/dim]"
    )

    if session.top_bridges and show_chain:
        console.print("\n[bold]Topp-bryggor:[/bold]")
        for b in sorted(session.top_bridges, key=lambda x: x.overlap_score, reverse=True)[:5]:
            chain_str = " → ".join(b.chain)
            console.print(f"  [bold]{b.source}[/bold] ↔ [bold]{b.target}[/bold]")
            console.print(f"    [dim]{chain_str}[/dim]")
            if b.why:
                console.print(f"    [italic dim]{b.why[:120]}[/italic dim]")


@app.command()
def cascade(
    concepts:     str  = typer.Argument(...,
                         help="Komma-separerade startbegrepp, t.ex. 'mycel,kvantfysik,Wittgenstein'"),
    generations:  int  = typer.Option(4,  "--generations", "-g",
                                      help="Antal kompounderade lager"),
    pairs:        int  = typer.Option(3,  "--pairs", "-p",
                                      help="Par att kombinera per generation"),
) -> None:
    """
    Kompounderad idésyntes: 1+1=3+1=5+1=9...

    Tar en lista av startbegrepp och kombinerar dem iterativt.
    Varje generation skapar emergenta syntesnoder som sedan
    kombineras vidare i nästa generation.

    Generation 0: A + B = C  (tredje idén)
    Generation 1: C + D = E  (fjärde idén — kräver C för att existera)
    Generation 2: E + A = F  (femte idén — ser tillbaka och framåt)

    Det är precis det mänskligt kreativt tänkande gör.
    En vanlig LLM kan inte göra detta — den har inget minne av C och D.
    NoUse är det substratet.

    Exempel:
      nouse cascade "mycel,kvantfysik,Wittgenstein"
      nouse cascade "evolution,grammatik,termodynamik" --generations 3
    """
    import asyncio
    from nouse.field.surface import FieldSurface
    from nouse.field.limbic_state import LimbicState
    from nouse.learning_coordinator import LearningCoordinator
    from nouse.field.bridge_finder import run_synthesis_cascade

    seed_list = [c.strip() for c in concepts.split(",") if c.strip()]
    if len(seed_list) < 2:
        console.print("[red]Minst 2 startbegrepp krävs[/red]")
        raise typer.Exit(1)

    console.print(
        f"[cyan]Synthesis Cascade:[/cyan] {len(seed_list)} frön, "
        f"{generations} generationer, {pairs} par/gen\n"
        f"Frön: [bold]{', '.join(seed_list)}[/bold]\n"
    )

    try:
        field = FieldSurface()
    except RuntimeError as e:
        if "lock" in str(e).lower():
            console.print("[red]Databasen låst — stoppa daemon eerst (nouse daemon stop)[/red]")
        else:
            console.print(f"[red]Fel: {e}[/red]")
        raise typer.Exit(1)

    limbic = LimbicState()
    coordinator = LearningCoordinator(field, limbic)

    result = asyncio.run(run_synthesis_cascade(
        seed_list, field, coordinator,
        max_generations=generations,
        pairs_per_generation=pairs,
    ))

    console.print(f"\n[green bold]✓ Kaskad klar[/green bold]")
    console.print(f"  Generationer: {result.generations}")
    console.print(f"  Syntesnoder : [bold]{result.total_syntheses}[/bold]")

    if result.synthesis_chain:
        console.print("\n[bold]Emergerade insikter (i ordning):[/bold]")
        for i, name in enumerate(result.synthesis_chain):
            indent = "  " + "  " * (i // pairs)
            gen_num = i // pairs
            console.print(f"{indent}[cyan]Gen {gen_num}:[/cyan] [bold]{name}[/bold]")

    if result.final_synthesis:
        console.print(
            f"\n[yellow bold]Djupaste insikt:[/yellow bold] {result.final_synthesis}"
        )
        console.print(
            f"[dim](Kräver {result.generations} lager av syntes för att bli synlig)[/dim]"
        )


@app.callback()
def main(
    ctx: typer.Context,
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """nouse — local multi-agent society on the FNC framework."""
    if ctx.invoked_subcommand is None:
        _print_front_door()
        raise typer.Exit()
