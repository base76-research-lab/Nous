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


def looks_like_dependency_source(source_tag: str) -> bool:
    """Check if a source tag resembles a dependency directory."""
    if not source_tag:
        return False
    keywords = ("site-packages", ".venv", "virtualenvs", "node_modules")
    return any(keyword in source_tag for keyword in keywords)


def concept_depth(field, name: str) -> int:
    """Count non-dependency sources pointing to a concept."""
    count = 0
    for rel in field.in_relations(name):
        tag = rel.get("source_tag", "")
        if not looks_like_dependency_source(tag):
            count += 1
    return count


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
    """Get the highest top-of-mind score across all relations of a concept."""
    # Combine in and out relations; max score reflects active spreading activation.
    candidates = []

    for rel in field.in_relations(name):
        s = rel.get("strength", 1.0)
        c = rel.get("created")
        candidates.append(top_of_mind_score(s, c))

    for rel in field.out_relations(name):
        s = rel.get("strength", 1.0)
        c = rel.get("created")
        candidates.append(top_of_mind_score(s, c))

    return max(candidates) if candidates else 0.0
