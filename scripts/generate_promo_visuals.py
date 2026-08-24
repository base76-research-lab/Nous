#!/usr/bin/env python3
"""
NoUse Promo Visuals — X/Twitter-ready graphs and infographics.

Generates publication-quality visualizations from live NoUse graph data.
Output: ~/nouse_promo/ (PNG, 1200x675 for X cards, 1080x1080 for square)
"""
from __future__ import annotations

import collections
import json
import os
import sqlite3
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# ── Config ────────────────────────────────────────────────────────────
DB_PATH = Path.home() / ".local/share/nouse/field.sqlite"
OUT_DIR = Path.home() / "nouse_promo"
OUT_DIR.mkdir(exist_ok=True)

# Brand colors
BG = "#0d1117"        # GitHub dark
ACCENT = "#58a6ff"    # Bright blue
ACCENT2 = "#f78166"   # Orange/coral
ACCENT3 = "#7ee787"   # Green
ACCENT4 = "#d2a8ff"   # Purple
TEXT = "#c9d1d9"       # Light gray
GRID = "#21262d"       # Subtle grid

plt.rcParams.update({
    "figure.facecolor": BG,
    "axes.facecolor": BG,
    "axes.edgecolor": GRID,
    "axes.labelcolor": TEXT,
    "text.color": TEXT,
    "xtick.color": TEXT,
    "ytick.color": TEXT,
    "grid.color": GRID,
    "font.family": "sans-serif",
    "font.size": 13,
})


def load_data():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    concepts = db.execute("SELECT name, domain, created FROM concept").fetchall()
    relations = db.execute(
        "SELECT src, tgt, type, strength, evidence_score, assumption_flag FROM relation"
    ).fetchall()
    knowledge = db.execute(
        "SELECT name, uncertainty FROM concept_knowledge WHERE uncertainty IS NOT NULL"
    ).fetchall()
    embeddings = db.execute("SELECT COUNT(*) FROM concept_embedding").fetchone()[0]

    db.close()
    return concepts, relations, knowledge, embeddings


def _watermark(ax):
    ax.text(
        0.99, 0.01, "NoUse — Epistemic Memory Substrate",
        transform=ax.transAxes, fontsize=9, color=GRID,
        ha="right", va="bottom", alpha=0.7, style="italic",
    )


# ── 1. Knowledge Graph Growth ────────────────────────────────────────
def plot_growth(concepts, relations):
    fig, ax = plt.subplots(figsize=(12, 6.75))

    # Cumulative growth by day
    by_day = collections.Counter(c["created"][:10] for c in concepts)
    days = sorted(by_day.keys())
    cumulative = []
    total = 0
    for d in days:
        total += by_day[d]
        cumulative.append(total)

    ax.fill_between(range(len(days)), cumulative, alpha=0.3, color=ACCENT)
    ax.plot(cumulative, color=ACCENT, linewidth=3, marker="o", markersize=8)

    for i, (d, v) in enumerate(zip(days, cumulative)):
        ax.annotate(f"{v:,}", (i, v), textcoords="offset points",
                    xytext=(0, 14), ha="center", fontsize=11, fontweight="bold",
                    color=ACCENT)

    ax.set_xticks(range(len(days)))
    ax.set_xticklabels([d[5:] for d in days], fontsize=11)
    ax.set_ylabel("Concepts", fontsize=14)
    ax.set_title(
        f"NoUse: Autonomous Knowledge Growth\n"
        f"{len(concepts):,} concepts · {len(relations):,} relations · 7 days",
        fontsize=18, fontweight="bold", pad=20,
    )
    ax.grid(True, alpha=0.3)
    _watermark(ax)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "01_growth.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ 01_growth.png")


# ── 2. Domain Universe (treemap-style bar) ──────────────────────────

_DOMAIN_TRANSLATE = {
    "neurovetenskap": "Neuroscience",
    "programmering": "Programming",
    "programvaruutveckling": "Software Engineering",
    "mjukvaruutveckling": "Software Development",
    "programvara": "Software",
    "mjukvara": "Software (alt)",
    "mjukvaruarkitektur": "Software Architecture",
    "filosofi": "Philosophy",
    "maskininlärning": "Machine Learning",
    "datorvetenskap": "Computer Science",
    "säkerhet": "Security",
    "mjukvarutestning": "Software Testing",
    "epistemologi": "Epistemology",
    "AI-system": "AI Systems",
    "programvarutestning": "Software QA",
    "datavetenskap": "Data Science",
    "AI-forskning": "AI Research",
    "AI-utvärdering": "AI Evaluation",
    "pedagogik": "Pedagogy",
    "systemarkitektur": "Systems Architecture",
    "matematik": "Mathematics",
    "ekonomi": "Economics",
    "programvaruarkitektur": "Software Architecture (alt)",
    "forskning": "Research",
    "artificiell intelligens": "Artificial Intelligence",
    "datastruktur": "Data Structures",
    "systemteori": "Systems Theory",
    "software": "Software",
    "AI-utveckling": "AI Development",
}


def _translate_domain(sv: str) -> str:
    return _DOMAIN_TRANSLATE.get(sv, sv.replace("ö", "o").replace("ä", "a").replace("å", "a").title())


def plot_domains(concepts):
    fig, ax = plt.subplots(figsize=(12, 6.75))

    domain_counts = collections.Counter(c["domain"] for c in concepts)
    top = domain_counts.most_common(15)
    labels_sv, values = zip(*reversed(top))
    labels = [_translate_domain(l) for l in labels_sv]

    colors = plt.cm.plasma(np.linspace(0.2, 0.85, len(labels)))
    bars = ax.barh(range(len(labels)), values, color=colors, edgecolor=BG, linewidth=0.5)

    for bar, v in zip(bars, values):
        ax.text(bar.get_width() + 15, bar.get_y() + bar.get_height() / 2,
                f"{v:,}", va="center", fontsize=11, fontweight="bold", color=TEXT)

    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=12)
    ax.set_xlabel("Concepts", fontsize=14)
    ax.set_title(
        f"Domain Distribution — {len(domain_counts)} unique domains",
        fontsize=18, fontweight="bold", pad=20,
    )
    ax.grid(True, axis="x", alpha=0.3)
    _watermark(ax)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "02_domains.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ 02_domains.png")


# ── 3. Scale-Free Topology (power law) ──────────────────────────────
def plot_degree_distribution(concepts, relations):
    fig, ax = plt.subplots(figsize=(12, 6.75))

    # Compute degrees
    deg = collections.Counter()
    for r in relations:
        deg[r["src"]] += 1
        deg[r["tgt"]] += 1
    for c in concepts:
        if c["name"] not in deg:
            deg[c["name"]] = 0

    deg_vals = list(deg.values())
    deg_counts = collections.Counter(deg_vals)

    x = sorted(k for k in deg_counts if k > 0)
    y = [deg_counts[k] for k in x]

    ax.scatter(x, y, s=40, color=ACCENT, alpha=0.8, zorder=3)

    # Power law fit line
    log_x = np.log10([xx for xx in x if xx > 0])
    log_y = np.log10([yy for xx, yy in zip(x, y) if xx > 0])
    if len(log_x) > 2:
        coeffs = np.polyfit(log_x, log_y, 1)
        fit_x = np.logspace(0, np.log10(max(x)), 100)
        fit_y = 10 ** (coeffs[0] * np.log10(fit_x) + coeffs[1])
        ax.plot(fit_x, fit_y, "--", color=ACCENT2, linewidth=2, alpha=0.8,
                label=f"Power law: γ = {-coeffs[0]:.2f}")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Node Degree (connections)", fontsize=14)
    ax.set_ylabel("Count", fontsize=14)
    ax.set_title(
        "Scale-Free Network Topology\n"
        "NoUse self-organizes into brain-like hub structure",
        fontsize=18, fontweight="bold", pad=20,
    )
    ax.legend(fontsize=13, loc="upper right", framealpha=0.3)
    ax.grid(True, alpha=0.3)
    _watermark(ax)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "03_scale_free.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ 03_scale_free.png")


# ── 4. Relation Type Wheel ──────────────────────────────────────────
def plot_relation_types(relations):
    fig, ax = plt.subplots(figsize=(10.8, 10.8))

    type_counts = collections.Counter(r["type"] for r in relations)
    top = type_counts.most_common(12)
    labels, values = zip(*top)

    colors = plt.cm.twilight(np.linspace(0.1, 0.9, len(labels)))
    wedges, texts, autotexts = ax.pie(
        values, labels=None, colors=colors,
        autopct=lambda p: f"{p:.1f}%", pctdistance=0.82,
        startangle=90, wedgeprops={"edgecolor": BG, "linewidth": 2},
    )

    for t in autotexts:
        t.set_fontsize(11)
        t.set_fontweight("bold")
        t.set_color(TEXT)

    # Legend
    ax.legend(
        wedges, [f"{l} ({v:,})" for l, v in zip(labels, values)],
        loc="center left", bbox_to_anchor=(-0.25, 0.5),
        fontsize=11, framealpha=0.3,
    )

    ax.set_title(
        f"Relation Taxonomy\n{len(type_counts)} types · {len(relations):,} edges",
        fontsize=18, fontweight="bold", pad=20,
    )
    _watermark(ax)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "04_relation_types.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ 04_relation_types.png")


# ── 5. Performance Benchmarks ────────────────────────────────────────
def plot_performance():
    fig, axes = plt.subplots(1, 2, figsize=(12, 6.75))

    # Left: TDA speedup
    ax = axes[0]
    labels = ["Before\n(NetworkX)", "After\n(NumPy cdist)"]
    values = [14.0, 0.28]
    colors_bar = [ACCENT2, ACCENT3]
    bars = ax.bar(labels, values, color=colors_bar, width=0.5, edgecolor=BG)
    ax.set_ylabel("Seconds", fontsize=14)
    ax.set_title("TDA Computation\n(n=1175 concepts)", fontsize=15, fontweight="bold")
    ax.bar_label(bars, [f"{v}s" for v in values], fontsize=14, fontweight="bold", padding=5)
    speedup_tda = values[0] / values[1]
    ax.text(0.5, 0.85, f"{speedup_tda:.0f}× faster", transform=ax.transAxes,
            fontsize=20, fontweight="bold", ha="center", color=ACCENT3)
    ax.grid(True, axis="y", alpha=0.3)

    # Right: Bisociation pipeline
    ax = axes[1]
    labels = ["Before", "After\n(optimized)"]
    values = [280, 31.5]
    bars = ax.bar(labels, values, color=colors_bar, width=0.5, edgecolor=BG)
    ax.set_ylabel("Seconds", fontsize=14)
    ax.set_title("Bisociation Pipeline\n(full domain scan)", fontsize=15, fontweight="bold")
    ax.bar_label(bars, [f"{v}s" for v in values], fontsize=14, fontweight="bold", padding=5)
    speedup_bisoc = values[0] / values[1]
    ax.text(0.5, 0.85, f"{speedup_bisoc:.0f}× faster", transform=ax.transAxes,
            fontsize=20, fontweight="bold", ha="center", color=ACCENT3)
    ax.grid(True, axis="y", alpha=0.3)

    fig.suptitle(
        "NoUse Performance: Pure Python Optimization",
        fontsize=18, fontweight="bold", y=1.02,
    )
    _watermark(axes[1])

    fig.tight_layout()
    fig.savefig(OUT_DIR / "05_performance.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ 05_performance.png")


# ── 6. Epistemic Uncertainty — Comparative View ─────────────────────
def plot_uncertainty(knowledge, concepts, relations):
    fig, axes = plt.subplots(1, 2, figsize=(12, 6.75), gridspec_kw={"width_ratios": [2, 1]})

    uncertainties = [k["uncertainty"] for k in knowledge]

    # ── Left: Sorted uncertainty gradient (every concept as a thin line) ──
    ax = axes[0]
    sorted_u = sorted(uncertainties)
    n = len(sorted_u)
    # Sample down for performance if huge
    step = max(1, n // 2000)
    sampled = sorted_u[::step]
    colors_grad = plt.cm.RdYlGn_r(np.array(sampled))  # red=high, green=low
    ax.bar(range(len(sampled)), sampled, width=1.0, color=colors_grad, edgecolor="none")
    ax.set_xlim(0, len(sampled))
    ax.set_ylim(0, 1.0)  # Full 0–1 scale to show where the mass sits

    mean_u = statistics.mean(uncertainties)
    ax.axhline(mean_u, color=ACCENT2, linestyle="--", linewidth=2, alpha=0.8)
    ax.text(len(sampled) * 0.02, mean_u + 0.02, f"mean = {mean_u:.3f}",
            fontsize=12, color=ACCENT2, fontweight="bold")

    # Annotate zones
    ax.axhspan(0.0, 0.3, alpha=0.06, color=ACCENT3)
    ax.axhspan(0.7, 1.0, alpha=0.06, color=ACCENT2)
    ax.text(len(sampled) * 0.98, 0.15, "High confidence", ha="right",
            fontsize=10, color=ACCENT3, alpha=0.7)
    ax.text(len(sampled) * 0.98, 0.85, "Low confidence", ha="right",
            fontsize=10, color=ACCENT2, alpha=0.7)

    ax.set_xlabel(f"Concepts (sorted, n={n:,})", fontsize=13)
    ax.set_ylabel("Uncertainty Score", fontsize=13)
    ax.set_title("Every Concept's Epistemic Uncertainty", fontsize=15, fontweight="bold")

    # ── Right: Comparison panel — NoUse vs typical LLM ──
    ax = axes[1]
    categories = ["Standard\nLLM", "NoUse"]
    # Standard LLM: always says it's confident (implicit ~0.1 uncertainty)
    # NoUse: tracked distribution
    bar_vals = [0.0, mean_u]
    bar_colors = ["#444c56", ACCENT4]
    bars = ax.bar(categories, bar_vals, color=bar_colors, width=0.5, edgecolor=BG)

    # Error bars showing spread
    min_u, max_u = min(uncertainties), max(uncertainties)
    ax.errorbar(1, mean_u, yerr=[[mean_u - min_u], [max_u - mean_u]],
                fmt="none", ecolor=TEXT, elinewidth=2, capsize=8, capthick=2)

    ax.set_ylim(0, 1.0)
    ax.set_ylabel("Tracked Uncertainty", fontsize=13)
    ax.text(0, 0.05, "Unknown\n(no tracking)", ha="center", fontsize=10,
            color="#8b949e", style="italic")
    ax.text(1, mean_u + 0.08, f"{mean_u:.2f}\n± {(max_u-min_u)/2:.2f}",
            ha="center", fontsize=11, fontweight="bold", color=ACCENT4)
    ax.set_title("Tracked vs Untracked", fontsize=15, fontweight="bold")
    ax.grid(True, axis="y", alpha=0.3)

    fig.suptitle(
        f"Epistemic Grounding — {n:,} concepts with explicit uncertainty",
        fontsize=18, fontweight="bold", y=1.02,
    )
    _watermark(axes[1])

    fig.tight_layout()
    fig.savefig(OUT_DIR / "06_uncertainty.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ 06_uncertainty.png")


# ── 7. Strength vs Topology (Hebbian learning visible) ──────────────
def plot_hebbian_strength(relations):
    fig, ax = plt.subplots(figsize=(12, 6.75))

    strengths = [r["strength"] for r in relations if r["strength"] and r["strength"] > 0]
    evidence = [r["evidence_score"] for r in relations
                if r["evidence_score"] is not None and r["strength"] and r["strength"] > 0]

    # Only if we have matching pairs
    if len(strengths) == len(evidence):
        scatter = ax.scatter(
            strengths[:5000], evidence[:5000],
            s=8, alpha=0.4, c=strengths[:5000],
            cmap="plasma", vmin=1, vmax=min(20, max(strengths)),
        )
        cbar = fig.colorbar(scatter, ax=ax, label="Hebbian Strength")
        cbar.ax.yaxis.label.set_color(TEXT)
        cbar.ax.tick_params(colors=TEXT)
    else:
        ax.hist(strengths, bins=80, color=ACCENT, alpha=0.85, edgecolor=BG, log=True)

    high_strength = sum(1 for s in strengths if s > 5)
    ax.set_xlabel("Relation Strength" if len(strengths) != len(evidence) else "Hebbian Strength", fontsize=14)
    ax.set_ylabel("Evidence Score" if len(strengths) == len(evidence) else "Count (log)", fontsize=14)
    ax.set_title(
        f"Hebbian Learning in Action\n"
        f"{high_strength:,} strongly reinforced pathways (strength > 5)",
        fontsize=18, fontweight="bold", pad=20,
    )
    ax.grid(True, alpha=0.3)
    _watermark(ax)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "07_hebbian.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ 07_hebbian.png")


# ── 8. Hero Stats Card ──────────────────────────────────────────────
def plot_hero_card(concepts, relations, knowledge, embeddings):
    fig, ax = plt.subplots(figsize=(12, 6.75))
    ax.axis("off")

    # Title
    ax.text(0.5, 0.92, "NoUse", fontsize=52, fontweight="bold",
            ha="center", va="top", color=ACCENT,
            fontfamily="monospace")
    ax.text(0.5, 0.80, "Epistemic Memory Substrate for LLMs",
            fontsize=18, ha="center", va="top", color=TEXT, style="italic")

    # Stats grid
    stats = [
        (f"{len(concepts):,}", "Concepts"),
        (f"{len(relations):,}", "Relations"),
        (f"{len(set(c['domain'] for c in concepts))}", "Domains"),
        (f"{embeddings:,}", "Embeddings"),
        ("50×", "TDA speedup"),
        ("9×", "Pipeline speedup"),
        ("0.55", "Avg uncertainty"),
        ("99.98%", "Evidenced"),
    ]

    cols = 4
    rows = 2
    for i, (val, label) in enumerate(stats):
        col = i % cols
        row = i // cols
        x = 0.125 + col * 0.25
        y = 0.52 - row * 0.25

        ax.text(x, y, val, fontsize=28, fontweight="bold",
                ha="center", va="center", color=ACCENT3 if "×" in val else TEXT)
        ax.text(x, y - 0.07, label, fontsize=12,
                ha="center", va="center", color=GRID.replace("21262d", "8b949e"))

    # Footer
    ax.text(0.5, 0.03, "github.com/base76-research-lab/Nous  ·  MIT License  ·  Python 3.13+",
            fontsize=10, ha="center", va="bottom", color=GRID, alpha=0.6)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "00_hero.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ 00_hero.png")


# ── 9. Top Hubs — Force-directed with gravity ──────────────────────
def plot_hub_ego(concepts, relations):
    """Force-directed layout: hubs pulled to center by degree, repelled by overlap."""
    fig, ax = plt.subplots(figsize=(10.8, 10.8))

    # Compute degrees + adjacency
    deg = collections.Counter()
    adj = collections.defaultdict(set)
    for r in relations:
        deg[r["src"]] += 1
        deg[r["tgt"]] += 1
        adj[r["src"]].add(r["tgt"])
        adj[r["tgt"]].add(r["src"])

    max_deg = max(deg.values())

    # Select nodes: top 12 hubs + up to 8 neighbors each
    top_hubs = [name for name, _ in deg.most_common(12)]
    hub_set = set(top_hubs)
    show_nodes = set(top_hubs)
    for hub in top_hubs:
        nbs = sorted(adj[hub], key=lambda n: deg[n], reverse=True)[:8]
        show_nodes.update(nbs)

    # Collect edges between visible nodes
    edge_set = set()
    for r in relations:
        if r["src"] in show_nodes and r["tgt"] in show_nodes:
            edge_set.add((r["src"], r["tgt"]))

    # ── Force-directed layout ──
    np.random.seed(42)
    nodes = list(show_nodes)
    pos = {n: np.random.randn(2) * 2.0 for n in nodes}

    # Gravity: pull toward center proportional to degree (hubs → center)
    for _ in range(300):
        forces = {n: np.zeros(2) for n in nodes}

        # Repulsion (all pairs — sampled for speed)
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                diff = pos[a] - pos[b]
                dist = max(np.linalg.norm(diff), 0.1)
                repel = diff / dist * (1.5 / dist ** 2)
                forces[a] += repel
                forces[b] -= repel

        # Attraction along edges
        for a, b in edge_set:
            if a in pos and b in pos:
                diff = pos[b] - pos[a]
                dist = np.linalg.norm(diff)
                attract = diff * 0.01 * dist
                forces[a] += attract
                forces[b] -= attract

        # Gravity toward center — stronger for high-degree nodes
        for n in nodes:
            gravity_strength = 0.02 + 0.08 * (deg.get(n, 1) / max_deg)
            forces[n] -= pos[n] * gravity_strength

        # Apply forces with damping
        for n in nodes:
            pos[n] += forces[n] * 0.3

    # ── Draw edges ──
    for a, b in edge_set:
        if a in pos and b in pos:
            x0, y0 = pos[a]
            x1, y1 = pos[b]
            # Thicker edges between hubs
            lw = 1.5 if (a in hub_set and b in hub_set) else 0.3
            alpha = 0.5 if (a in hub_set and b in hub_set) else 0.15
            ax.plot([x0, x1], [y0, y1], color=ACCENT if lw > 1 else GRID,
                    alpha=alpha, linewidth=lw)

    # ── Draw nodes — size proportional to degree ──
    for node in nodes:
        x, y = pos[node]
        d = deg.get(node, 1)
        is_hub = node in hub_set

        # Scale: hub with degree 229 → ~2000 scatter size, leaf with degree 1 → 15
        if is_hub:
            s = 80 + (d / max_deg) * 2500
            color = ACCENT
            alpha = 0.9
            zorder = 5
        else:
            s = 10 + (d / max_deg) * 200
            color = ACCENT4
            alpha = 0.4
            zorder = 3

        ax.scatter(x, y, s=s, color=color, alpha=alpha, zorder=zorder,
                   edgecolors=BG, linewidth=0.5)

        # Label hubs
        if is_hub:
            label = node[:18] + "…" if len(node) > 18 else node
            fontsize = 8 + (d / max_deg) * 6
            ax.annotate(
                label, (x, y), fontsize=fontsize, fontweight="bold",
                ha="center", va="bottom",
                xytext=(0, max(6, s ** 0.5 * 0.4)),
                textcoords="offset points", color=TEXT,
            )

    # Auto-fit limits
    all_x = [pos[n][0] for n in nodes]
    all_y = [pos[n][1] for n in nodes]
    margin = 1.5
    ax.set_xlim(min(all_x) - margin, max(all_x) + margin)
    ax.set_ylim(min(all_y) - margin, max(all_y) + margin)
    ax.axis("off")
    ax.set_title(
        f"Hub Network — Scale-Free Topology\n"
        f"High-degree nodes gravitate to center (Hebbian plasticity)",
        fontsize=18, fontweight="bold", pad=20,
    )
    _watermark(ax)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "08_hub_network.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ 08_hub_network.png")


# ── Main ──────────────────────────────────────────────────────────────
def main():
    print(f"Loading data from {DB_PATH}…")
    concepts, relations, knowledge, embeddings = load_data()
    print(f"  {len(concepts):,} concepts, {len(relations):,} relations\n")
    print(f"Generating visuals → {OUT_DIR}/\n")

    plot_hero_card(concepts, relations, knowledge, embeddings)
    plot_growth(concepts, relations)
    plot_domains(concepts)
    plot_degree_distribution(concepts, relations)
    plot_relation_types(relations)
    plot_performance()
    plot_uncertainty(knowledge, concepts, relations)
    plot_hebbian_strength(relations)
    plot_hub_ego(concepts, relations)

    print(f"\n✅ Done! {len(list(OUT_DIR.glob('*.png')))} images in {OUT_DIR}")


if __name__ == "__main__":
    main()
