"""
Wiki generator — exports selected concepts as Markdown wiki pages to disk.
================================================================================
Reads concept metadata and relations from FieldSurface, filters by evidence quality,
and writes static Markdown files. This module is read-only and never modifies the graph.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from nouse.daemon import salience

if TYPE_CHECKING:
    from nouse.field.surface import FieldSurface


def wiki_dir() -> Path:
    """Returns the output directory for wiki pages."""
    env_override = os.environ.get("NOUSE_WIKI_DIR")
    if env_override:
        return Path(env_override)
    return Path(__file__).resolve().parents[3] / "wiki"


_GENERIC_SOURCE_TAGS = frozenset({None, "", "auto"})


def concept_qualifies_for_page(field: "FieldSurface", name: str) -> bool:
    """A concept gets a page only if it has at least one relation with a real, named
    source_tag (a file path, domain_bootstrap, curiosity_loop:..., etc.) — not the
    generic "auto" default.

    NOT evidence_score >= threshold: verified against the live graph
    (~/.local/share/nouse/field.sqlite, 2026-08-25) that add_relation() always
    computes and persists a real evidence_score (never leaves it NULL — even an
    explicit evidence_score=None falls back to a strength-derived or flat-0.35
    value), and in practice 26136/26647 real relations already score >= 0.75
    regardless of origin. Any evidence_score-based cutoff would pass ~98% of the
    graph, defeating the whole point of a threshold. source_tag is what actually
    varies: ~4053/20544 concepts have a non-generic one, vs. an evidence_score
    filter passing nearly all 20544.
    """
    all_rels = field.out_relations(name) + field.in_relations(name)
    return any(rel.get("source_tag") not in _GENERIC_SOURCE_TAGS for rel in all_rels)


def slugify(name: str) -> str:
    """Filesystem-safe filename stem: lowercase, spaces and non-alphanumeric runs replaced with a single '-'."""
    s = name.lower()
    s = re.sub(r'[^a-z0-9\-]', ' ', s)
    s = re.sub(r'[-\s]+', '-', s)
    return s.strip('-')


def render_wiki_page(field: "FieldSurface", name: str) -> str:
    """Builds the full Markdown text (frontmatter + body) for one concept."""

    # Linjär genomsökning — körs i en periodisk batch-cykel, inte en het väg,
    # så det finns ingen anledning att optimera/cacha den här uppslagningen.
    row = None
    for c in field.get_concepts_with_metadata(limit=5000):
        if c.get("id") == name:
            row = c
            break
    domain = row.get("dom", "") if row else ""
    scope = row.get("scope", "general") if row else "general"

    qualifies = concept_qualifies_for_page(field, name)

    kw = field.concept_knowledge(name)
    summary = kw.get("summary") or "(ingen sammanfattning ännu.)"
    revision_count = kw.get("revision_count", 0)

    out_rels = field.out_relations(name)
    in_rels = field.in_relations(name)
    all_rels = out_rels + in_rels

    has_parametric = any(rel.get("source_tag") == "domain_bootstrap" for rel in all_rels)

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # out_rels och in_rels hålls isär genom HELA formateringen (aldrig slagna
    # ihop till en lista och sedan gissade isär igen) — in_relations()-rader
    # har också en "target"-nyckel (satt till namnet självt), så en
    # efterhandsgissning baserad på nyckelnärvaro kan inte skilja dem åt.
    strong_lines: list[str] = []
    uncertain_lines: list[str] = []

    for rel in out_rels:
        score = rel.get("evidence_score")
        score_str = f"{score:.2f}" if score is not None else "n/a"
        line = (f"- {name} —[{rel.get('type','')}]→ [[{rel.get('target','')}]] "
                f"(evidens: {score_str}, källa: {rel.get('source_tag','')})")
        if rel.get("source_tag") not in _GENERIC_SOURCE_TAGS:
            strong_lines.append(line)
        else:
            uncertain_lines.append(line)

    for rel in in_rels:
        score = rel.get("evidence_score")
        score_str = f"{score:.2f}" if score is not None else "n/a"
        line = (f"- [[{rel.get('source','')}]] —[{rel.get('type','')}]→ {name} "
                f"(evidens: {score_str}, källa: {rel.get('source_tag','')})")
        if rel.get("source_tag") not in _GENERIC_SOURCE_TAGS:
            strong_lines.append(line)
        else:
            uncertain_lines.append(line)

    strong_relations_str = "\n".join(strong_lines) if strong_lines else "- (inga ännu)"
    uncertain_relations_str = "\n".join(uncertain_lines) if uncertain_lines else "- (inga ännu)"

    related_terms = kw.get("related_terms", [])
    related_str = " · ".join(f"[[{t}]]" for t in related_terms) if related_terms else "(inga ännu)"

    depth = salience.concept_depth(field, name)
    top_of_mind = salience.concept_top_of_mind_score(field, name)

    frontmatter = f"""---
concept: "{name}"
domain: "{domain}"
scope: {scope}
evidence_backed: {str(qualifies).lower()}
parametric_hypothesis: {str(has_parametric).lower()}
revision_count: {revision_count}
depth: {depth}
top_of_mind_score: {top_of_mind:.3f}
last_generated: "{now_utc}"
---"""

    body = f"""## {name}

{summary}

### Vad vi vet (namngiven källa)
{strong_relations_str}

### Osäkert / under granskning
{uncertain_relations_str}

### Relaterat
{related_str}
"""

    return frontmatter + "\n\n" + body


def parse_revision_count_from_file(filepath: Path) -> int | None:
    """Enkel manuell parsning av YAML-frontmatter — ingen PyYAML-dependency."""
    if not filepath.exists():
        return None
    try:
        for line in filepath.read_text(encoding="utf-8").split("\n"):
            stripped = line.strip()
            if stripped.startswith("revision_count:"):
                val_str = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                try:
                    return int(val_str)
                except ValueError:
                    return None
    except Exception:
        pass
    return None


def should_regenerate(field: "FieldSurface", name: str) -> bool:
    """True om sidan saknas, eller om grafens revision_count gått om filens."""
    wiki_path = wiki_dir() / f"{slugify(name)}.md"
    current_rev_count = field.concept_knowledge(name)["revision_count"]
    file_rev_count = parse_revision_count_from_file(wiki_path)
    if file_rev_count is None:
        return True
    return current_rev_count > file_rev_count


def generate_wiki_pages(field: "FieldSurface", *, limit: int = 5000) -> dict:
    """Main entry point to generate wiki pages for qualifying concepts."""
    wiki_dir_path = wiki_dir()
    wiki_dir_path.mkdir(parents=True, exist_ok=True)

    generated_count = 0
    skipped_count = 0
    total_concepts = 0

    try:
        concepts_meta = field.get_concepts_with_metadata(limit=limit)
    except Exception:
        return {"generated": 0, "skipped": 0, "total_concepts": 0}

    for concept_row in concepts_meta:
        name = concept_row.get("id")
        if not name:
            skipped_count += 1
            continue

        total_concepts += 1

        if not concept_qualifies_for_page(field, name):
            skipped_count += 1
            continue

        if not should_regenerate(field, name):
            skipped_count += 1
            continue

        try:
            content = render_wiki_page(field, name)
            (wiki_dir_path / f"{slugify(name)}.md").write_text(content, encoding="utf-8")
            generated_count += 1
        except Exception:
            continue

    return {"generated": generated_count, "skipped": skipped_count, "total_concepts": total_concepts}


def generate_wiki_index(field: "FieldSurface", *, limit: int = 5000) -> dict:
    """Writes wiki/_index.md: qualifying concepts ranked by top_of_mind_score,
    highest first — a snapshot of what Nous is currently "thinking about",
    not just an alphabetical file listing."""
    wiki_dir_path = wiki_dir()
    wiki_dir_path.mkdir(parents=True, exist_ok=True)

    try:
        concepts_meta = field.get_concepts_with_metadata(limit=limit)
    except Exception:
        return {"indexed": 0}

    ranked: list[tuple[float, str]] = []
    for concept_row in concepts_meta:
        name = concept_row.get("id")
        if not name or not concept_qualifies_for_page(field, name):
            continue
        try:
            score = salience.concept_top_of_mind_score(field, name)
        except Exception:
            continue
        ranked.append((score, name))

    ranked.sort(key=lambda pair: pair[0], reverse=True)

    lines = ["# Nous — wiki-index (top of mind)", ""]
    for score, name in ranked:
        lines.append(f"- [[{slugify(name)}]] {name} (score: {score:.3f})")
    (wiki_dir_path / "_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {"indexed": len(ranked)}
