"""
Salience -- Compute concept prominence metrics based on connection strength and recency.
=================================
Provides utilities to normalize Hebbian strengths, apply temporal decay, and derive top-of-mind scores
for concepts by aggregating their relational history within the knowledge graph.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional


def looks_like_dependency_source(source_tag: Optional[str]) -> bool:
    """Check if a source tag resembles a dependency directory."""
    if not source_tag:
        return False
    keywords = ("site-packages", ".venv", "virtualenvs", "node_modules")
    return any(keyword in source_tag for keyword in keywords)


_CODE_FILE_EXTENSIONS = (
    ".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".rb", ".sh",
)


def looks_like_code_file(source_tag: str) -> bool:
    """Check if a source tag is a path to a source-code file, as opposed to
    prose (.md/.txt/.pdf/...). Verified against the live graph 2026-08-25:
    of path-like source_tag values, .py accounts for 1697, prose formats
    combined for 82 -- code files dominate the raw path-tagged evidence."""
    if not source_tag:
        return False
    return source_tag.rstrip().lower().endswith(_CODE_FILE_EXTENSIONS)


_GENERIC_SOURCE_TAGS = frozenset({None, "", "auto"})  # mirrors wiki_generator.py's
# own constant -- duplicated, not imported, to avoid a circular import
# (wiki_generator already imports this module).


def is_code_only_concept(field, name: str) -> bool:
    """True if every NAMED (non-generic-tag) relation touching this concept
    traces to a code file -- i.e. among whatever real, attributable evidence
    it has, none of it is prose (a doc, a note, a design file).

    Found via real-data testing, not assumed: an earlier version checked
    ALL relations including "auto"-tagged ones, which are Hebbian-inferred
    with NO real source at all -- not code, not prose, just unlabeled. That
    version wrongly protected concepts like ROOT from exclusion, because
    "auto" fails the looks_like_code_file() check and made the all()
    trivially False even when 100% of ROOT's REAL, named sources were .py
    files (its other ~114 relations were just untagged noise). Only the
    named relations carry a real signal either way.

    Deliberately not a stoplist of specific identifiers (ROOT, str,
    __version__, ...): fragile, doesn't generalize, and a concept discussed
    in real prose stays included no matter how "generic" its name looks.
    See nous-codex-dialogue-2026-08-25-concept-noise.md.
    """
    all_rels = field.out_relations(name) + field.in_relations(name)
    named_rels = [r for r in all_rels if r.get("source_tag") not in _GENERIC_SOURCE_TAGS]
    if not named_rels:
        return False  # no real evidence at all -- not this function's call to make
    return all(looks_like_code_file(rel.get("source_tag") or "") for rel in named_rels)


def concept_depth(field, name: str) -> int:
    """Count DISTINCT non-dependency concepts pointing to this one.

    Fixed via a real relay:codex dialogue, 2026-08-25 (see
    nous-codex-dialogue-2026-08-25-concept-noise.md), verified independently
    against the live graph before applying: this used to count in_relations()
    ROWS, not distinct neighbors. A MultiDiGraph allows parallel edges, so a
    relationship recorded multiple times (re-extraction, never deduplicated)
    inflated the count -- confirmed on 'ROOT' (84 rows, only 15 distinct
    neighbors) and 'text' (78 rows, 21 neighbors).
    """
    neighbors: set[str] = set()
    for rel in field.in_relations(name):
        if looks_like_dependency_source(rel.get("source_tag")):
            continue
        source = rel.get("source")
        if source is not None:
            neighbors.add(source)
    return len(neighbors)


def use_component(strength: float) -> float:
    """Normalize raw strength to the [0.45, 0.95] range."""
    return min(0.95, max(0.45, 0.45 + (strength - 1.0) * 0.25))


def recency_decay(
    created_iso: Optional[str], *, half_life_days: float = 21.0, now: Optional[datetime] = None
) -> float:
    """Calculate exponential decay based on creation timestamp."""
    if not created_iso:
        return 1.0

    try:
        # Handle 'Z' suffix by replacing with '+00:00' for fromisoformat compatibility
        normalized = created_iso.replace("Z", "+00:00")
        parsed_dt = datetime.fromisoformat(normalized)

        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)

        if now is None:
            now_utc = datetime.now(timezone.utc)
        else:
            now_utc = now

        days_since = (now_utc - parsed_dt).total_seconds() / 86400.0

        if days_since < 0:
            days_since = 0

        return math.exp(-math.log(2) / half_life_days * days_since)
    except Exception:
        return 1.0


def top_of_mind_score(strength: float, created_iso: Optional[str]) -> float:
    """Combine normalized strength with recency decay."""
    return use_component(strength) * recency_decay(created_iso)


def concept_top_of_mind_score(field, name: str) -> float:
    """Get the highest top-of-mind score across non-dependency relations of
    a concept. Max, not average/sum: a single very active connection is
    enough to make a concept feel current, matching spreading activation.

    Dependency-path relations excluded (fixed 2026-08-25, same dialogue as
    concept_depth() above) -- previously a site-packages relation with a
    high Hebbian strength could dominate the score even though the
    connection itself is noise, not real activity. "auto"-tagged relations
    stay eligible on purpose: this fix is specifically about dependency
    paths, not about provenance quality in general (see
    concept_qualifies_for_page() in wiki_generator.py for that distinction).
    """
    candidates = []

    for rel in field.in_relations(name):
        if looks_like_dependency_source(rel.get("source_tag")):
            continue
        s = rel.get("strength", 1.0)
        c = rel.get("created")
        candidates.append(top_of_mind_score(s, c))

    for rel in field.out_relations(name):
        if looks_like_dependency_source(rel.get("source_tag")):
            continue
        s = rel.get("strength", 1.0)
        c = rel.get("created")
        candidates.append(top_of_mind_score(s, c))

    return max(candidates) if candidates else 0.0
