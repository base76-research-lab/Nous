#!/usr/bin/env python3
"""
NoUse demo — producerar en dramatisk terminal-demo av den plastiska hjärnan.
Körs via scripts/make_gif.sh för att skapa README-GIF.

Visar:
  1. Hjärnan skapas med biologiska regioner
  2. Synapser bildas med residual streams (w, r, u)
  3. Kognitiva cykler körs — signaler flödar, osäkerhet minskar
  4. Kristallisering: svaga kanter dör, starka kanter överlever för alltid
  5. Gap-karta: hjärnan vet vad den inte vet
"""

import sys
import time

from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

import nouse

console = Console(width=88)
DELAY = 0.06  # sekunder mellan tecken (typewriter-effekt)
STEP_DELAY = 0.18  # sekunder mellan cykler


def typewrite(text: str, style: str = "", delay: float = DELAY) -> None:
    for char in text:
        console.print(char, end="", style=style, highlight=False)
        time.sleep(delay)
    console.print()


def pause(t: float = 0.6) -> None:
    time.sleep(t)


def section(title: str) -> None:
    console.print()
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]", style="dim cyan"))
    console.print()
    pause(0.3)


def show_edge_row(edge_id: str, edge, changed: bool = False) -> list:
    ps = edge.path_signal
    bar_w = int(edge.w * 20)
    bar_r = int(abs(edge.r) * 10)
    bar_u = int(edge.u * 20)
    w_bar = f"[green]{'█' * bar_w}{'░' * (20 - bar_w)}[/green]"
    r_bar = f"[yellow]{'█' * bar_r}{'░' * (10 - bar_r)}[/yellow]"
    u_bar = f"[red]{'█' * bar_u}{'░' * (20 - bar_u)}[/red]"
    ps_color = "green" if ps > 0.4 else ("yellow" if ps > 0.1 else "red")
    crystal = "❄️ " if edge.crystallized else "   "
    style = "bold" if changed else ""
    return [
        Text(crystal + edge_id[:22], style=style),
        Text(w_bar),
        Text(r_bar),
        Text(u_bar),
        Text(f"[{ps_color}]{ps:+.3f}[/{ps_color}]", style=style),
    ]


def make_edge_table(brain: nouse.Kernel, changed: set = None) -> Table:
    changed = changed or set()
    t = Table(box=None, padding=(0, 1), show_header=True, header_style="bold dim")
    t.add_column("kant", width=25)
    t.add_column("w  struktur          ", width=23)
    t.add_column("r  signal  ", width=13)
    t.add_column("u  osäkerhet        ", width=23)
    t.add_column("path_signal", width=12, justify="right")
    for eid, edge in brain.edges.items():
        t.add_row(*show_edge_row(eid, edge, eid in changed))
    return t


def main() -> None:
    console.clear()
    pause(0.4)

    # ── TITEL ────────────────────────────────────────────────────────────────
    console.print(Align.center(Panel.fit(
        "[bold white]NoUse[/bold white]  [dim]νοῦς[/dim]\n"
        "[cyan]Den plastiska hjärnan — det saknade lagret till AGI[/cyan]",
        border_style="bold blue",
        padding=(1, 6),
    )))
    pause(1.0)

    # ── STEG 1: Skapa hjärnan ────────────────────────────────────────────────
    section("1 · Skapar kognitiv substrat")
    typewrite(">>> import nouse", style="bold green")
    pause(0.3)
    typewrite(">>> brain = nouse.Kernel(r_decay=0.89, w_threshold=0.55, u_ceiling=0.35)",
              style="bold green")
    pause(0.4)
    brain = nouse.Kernel(r_decay=0.89, w_threshold=0.55, u_ceiling=0.35)
    console.print("[dim]   ✓ Brain Kernel initierad  "
                  "[cyan]cycle=0[/cyan]  "
                  "nodes=0  edges=0[/dim]")
    pause(0.6)

    # ── STEG 2: Biologiska regioner ──────────────────────────────────────────
    section("2 · Lägger till hjärnregioner")

    regions = [
        ("hippocampus",      "region", "Hippocampus",      {"encoder": 0.7, "spatial": 0.3},   0.52, 0.61, 0.44),
        ("prefrontal_cortex","region", "Prefrontal Cortex", {"executive": 0.8, "wm": 0.2},      0.38, 0.42, 0.72),
        ("amygdala",         "region", "Amygdala",          {"threat": 0.6, "reward": 0.4},     0.61, 0.28, 0.31),
        ("thalamus",         "region", "Thalamus",          {"relay": 0.9, "gate": 0.1},        0.29, 0.55, 0.48),
        ("striatum",         "region", "Striatum",          {"habit": 0.5, "reward": 0.5},      0.44, 0.33, 0.62),
    ]

    for node_id, ntype, label, states, u, ev, gw in regions:
        typewrite(f">>> brain.add_node('{node_id}', ...)", style="bold green", delay=0.02)
        brain.add_node(node_id, node_type=ntype, label=label, states=states,
                       uncertainty=u, evidence_score=ev, goal_weight=gw, attrs={})
        console.print(f"   [dim]✓ {label:<22} u={u:.2f}  evidence={ev:.2f}[/dim]")
        time.sleep(0.15)

    pause(0.5)
    node_t = Table(box=None, padding=(0, 2), show_header=True, header_style="bold dim")
    node_t.add_column("nod", width=22)
    node_t.add_column("typ", width=8)
    node_t.add_column("osäkerhet", width=12, justify="right")
    node_t.add_column("bevis", width=10, justify="right")
    for nid, node in brain.nodes.items():
        u_bar = "█" * int((1 - node.uncertainty) * 10) + "░" * int(node.uncertainty * 10)
        console.print()
    console.print(f"   [green]✓ {len(brain.nodes)} regioner aktiva[/green]")
    pause(0.6)

    # ── STEG 3: Synapser med residual streams ────────────────────────────────
    section("3 · Bildar synapser med Residual Streams  (w · r · u)")

    console.print("[dim]   Tre kanaler per synaps:[/dim]")
    console.print("   [green]w[/green] strukturell vikt  — långtidsminne, persistent")
    console.print("   [yellow]r[/yellow] residualsignal    — aktiv aktivering, ephemeral")
    console.print("   [red]u[/red] osäkerhet         — blockerar konsolidering om hög")
    console.print("   [bold white]path_signal = w + 0.45·r − 0.25·u[/bold white]")
    pause(0.8)
    console.print()

    synapses = [
        ("hippo→pfc",    "hippocampus",       "consolidated_into", "prefrontal_cortex", 0.38, 0.0, 0.72, "episodic_learning"),
        ("pfc→amyg",     "prefrontal_cortex", "regulates",         "amygdala",          0.51, 0.0, 0.48, "emotional_control"),
        ("thal→hippo",   "thalamus",          "modulates",         "hippocampus",       0.29, 0.0, 0.81, "sensory_relay"),
        ("amyg→stria",   "amygdala",          "causes",            "striatum",          0.44, 0.0, 0.63, "reward_signal"),
        ("stria→pfc",    "striatum",          "predicts",          "prefrontal_cortex", 0.22, 0.0, 0.88, "habit_prediction"),
        ("hippo→thal",   "hippocampus",       "oscillates_with",   "thalamus",          0.35, 0.0, 0.55, "theta_coupling"),
    ]

    for eid, src, rel, tgt, w, r, u, prov in synapses:
        brain.upsert_edge(eid, src=src, rel_type=rel, tgt=tgt,
                          w=w, r=r, u=u, provenance=prov)
        ps = brain.edges[eid].path_signal
        ps_c = "green" if ps > 0.3 else ("yellow" if ps > 0.1 else "red")
        console.print(f"   [dim]{eid:<16}[/dim]  "
                      f"w=[green]{w:.2f}[/green]  "
                      f"r=[yellow]{r:.2f}[/yellow]  "
                      f"u=[red]{u:.2f}[/red]  "
                      f"→ path_signal=[{ps_c}]{ps:+.3f}[/{ps_c}]")
        time.sleep(0.2)

    pause(0.5)
    console.print()
    console.print(make_edge_table(brain))
    pause(1.0)

    # ── STEG 4: Kognitiva cykler ─────────────────────────────────────────────
    section("4 · Kognitiva cykler — signaler flödar, hjärnan lär sig")

    evidence_stream = [
        ("hippo→pfc",  0.06,  0.9,  -0.08, 0.78, "recall:spatial_task"),
        ("pfc→amyg",   0.04,  0.5,  -0.06, 0.65, "inhibition:fear_response"),
        ("thal→hippo", 0.08,  1.1,  -0.12, 0.84, "sensory:visual_input"),
        ("hippo→pfc",  0.07,  0.8,  -0.09, 0.81, "recall:spatial_task"),
        ("amyg→stria", 0.05,  0.6,  -0.07, 0.71, "reward:dopamine_release"),
        ("pfc→amyg",   0.05,  0.7,  -0.08, 0.69, "inhibition:fear_response"),
        ("hippo→pfc",  0.06,  1.0,  -0.10, 0.83, "recall:pattern_completion"),
        ("stria→pfc",  0.09,  0.4,  -0.05, 0.58, "habit:motor_sequence"),
        ("hippo→thal", 0.04,  0.8,  -0.09, 0.72, "theta:memory_consolidation"),
        ("hippo→pfc",  0.08,  1.2,  -0.11, 0.88, "recall:long_term_potentiation"),
        ("pfc→amyg",   0.06,  0.6,  -0.09, 0.74, "regulation:emotional_memory"),
        ("thal→hippo", 0.07,  0.9,  -0.10, 0.79, "sensory:tactile_input"),
    ]

    with Live(console=console, refresh_per_second=8) as live:
        for i, (eid, wd, rd, ud, ev, prov) in enumerate(evidence_stream):
            event = nouse.FieldEvent(
                edge_id=eid,
                src=brain.edges[eid].src,
                rel_type=brain.edges[eid].rel_type,
                tgt=brain.edges[eid].tgt,
                w_delta=wd, r_delta=rd, u_delta=ud,
                evidence_score=ev,
                provenance=prov,
            )
            brain.step(events=[event])

            status = (
                f"[bold cyan]cykel {brain.cycle:>3}[/bold cyan]  "
                f"event=[yellow]{eid:<14}[/yellow]  "
                f"Δw=[green]+{wd:.2f}[/green]  "
                f"Δr=[yellow]+{rd:.1f}[/yellow]  "
                f"Δu=[red]{ud:.2f}[/red]  "
                f"provenance=[dim]{prov}[/dim]"
            )
            live.update(Panel(
                f"{status}\n\n" + str(make_edge_table(brain, changed={eid})),
                title=f"[bold]Kognitiv cykel {brain.cycle}[/bold]",
                border_style="cyan",
            ))
            time.sleep(STEP_DELAY)

    pause(0.6)

    # ── STEG 5: Kristallisering ──────────────────────────────────────────────
    section("5 · Kristallisering — starka minnen överlever för alltid")

    console.print("[dim]   Regel: w > 0.55  AND  u < 0.35  →  ❄️  permanent synaps[/dim]")
    pause(0.6)
    typewrite(">>> crystallized = brain.crystallize()", style="bold green")
    crystallized = brain.crystallize()

    if crystallized:
        for e in crystallized:
            console.print(f"   [bold cyan]❄️  {e.edge_id:<18}[/bold cyan]  "
                          f"w=[green]{e.w:.3f}[/green]  "
                          f"u=[red]{e.u:.3f}[/red]  "
                          f"[dim]→ kristalliserat vid cykel {e.crystallized_at_cycle}[/dim]")
            time.sleep(0.2)
        console.print()
        console.print(f"   [bold green]{len(crystallized)} synaps(er) kristalliserade[/bold green]  "
                      f"[dim]— dessa kanter är nu permanenta minnesspår[/dim]")
    else:
        console.print("   [dim]Inga kanter nådde tröskeln ännu — fler cykler behövs[/dim]")

    pause(0.6)
    console.print()
    console.print(make_edge_table(brain))
    pause(0.8)

    # ── STEG 6: Gap-karta ────────────────────────────────────────────────────
    section("6 · Gap-karta — hjärnan vet vad den inte vet")

    typewrite(">>> brain.gap_map()", style="bold green")
    gm = brain.gap_map()
    pause(0.3)

    gap_t = Table(box=None, padding=(0, 2), show_header=True, header_style="bold dim")
    gap_t.add_column("nod", width=22)
    gap_t.add_column("osäkerhet", width=12, justify="right")
    gap_t.add_column("kunskapslucka", width=40)

    weak_nodes = gm.get("weak_nodes", [])
    for entry in weak_nodes[:4]:
        nid = entry if isinstance(entry, str) else entry.get("node_id", str(entry))
        node = brain.nodes.get(nid)
        if node:
            bar = "░" * int(node.uncertainty * 20)
            gap_t.add_row(
                nid,
                f"[red]{node.uncertainty:.2f}[/red]",
                f"[dim red]{bar}[/dim red]  [dim]→ behöver mer bevis[/dim]",
            )

    console.print(gap_t)
    total_gaps = len(weak_nodes)
    console.print(f"\n   [dim]{total_gaps} noder med hög osäkerhet identifierade[/dim]  "
                  f"[dim]— dessa driver framtida inlärning[/dim]")
    pause(0.8)

    # ── AVSLUTNING ───────────────────────────────────────────────────────────
    console.print()
    console.print(Rule(style="dim blue"))
    pause(0.3)

    summary = Table(box=None, padding=(0, 3), show_header=False)
    summary.add_column(width=35)
    summary.add_column(width=35)
    summary.add_row(
        f"[cyan]Cykler körda[/cyan]        [bold white]{brain.cycle}[/bold white]",
        f"[cyan]Noder[/cyan]              [bold white]{len(brain.nodes)}[/bold white]",
    )
    summary.add_row(
        f"[cyan]Kanter totalt[/cyan]       [bold white]{len(brain.edges)}[/bold white]",
        f"[cyan]Kristalliserade[/cyan]     [bold white]{sum(1 for e in brain.edges.values() if e.crystallized)}[/bold white]",
    )
    summary.add_row(
        f"[cyan]Minnesnivåer[/cyan]        [bold white]working→episodic→semantic→procedural[/bold white]",
        "",
    )
    console.print(Align.center(summary))
    pause(0.4)

    console.print()
    console.print(Align.center(
        "[bold white]pip install nouse[/bold white]  "
        "[dim]·[/dim]  "
        "[cyan]github.com/base76-research-lab/Nous[/cyan]"
    ))
    console.print(Align.center(
        "[dim]νοῦς — det saknade lagret till AGI[/dim]"
    ))
    console.print()
    pause(2.0)


if __name__ == "__main__":
    main()
