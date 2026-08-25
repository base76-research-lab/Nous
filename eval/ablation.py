"""
eval/ablation.py
=================
Controlled ablation building blocks for the "North Star" benchmark proposed
in the 2026-08-25 repo review: LLM only / long context / vector RAG /
Nous graph only / +evidence / +temporal validity / +contradiction /
+plasticity / full Nous — same model, same data, same budget.

Every condition here reads from a FieldSurface the caller already isolated
(see snapshot_production_field() below and CLAUDE.md's isolated-FieldSurface
rule) — nothing in this module writes to the live production graph, and
none of it makes a paid cloud-model call (the vector RAG condition calls
local Ollama for embeddings only).

Deliberately NOT included here: actually running the full ablation sweep.
That is a separate, explicit, cost-bearing step — see STATUS.md.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# ── Isolation ────────────────────────────────────────────────────────────

def snapshot_production_field(dest_path: Path) -> Path:
    """Safe, read-only, point-in-time copy of the live production graph.

    A raw file copy of a WAL-mode SQLite db can miss data still sitting in
    the -wal file, or copy a torn state under concurrent daemon writes.
    sqlite3's own online backup API (used here through a read-only source
    connection) is the correct way to snapshot a live db. Every condition
    in this module reads only from `dest_path` afterwards — the live file
    is opened read-only and only for the duration of the backup call.
    """
    from nouse.config.paths import path_from_env

    prod_path = path_from_env("NOUSE_FIELD_DB", "field.sqlite")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{prod_path}?mode=ro", uri=True)
    dest = sqlite3.connect(str(dest_path))
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()
    return dest_path


# ── Feature toggles ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class NousFeatureConfig:
    """One step of the ablation staircase over the graph context pipeline.

    All flags default True (= current full-Nous behavior, unchanged). Each
    flag strips exactly one mechanism from the formatted context so
    conditions compose as "+evidence", "+evidence+temporal_validity", etc.
    """
    use_evidence: bool = True         # show/sort by evidence scores
    use_temporal_validity: bool = True  # drop relations whose valid_until has passed
    use_contradiction: bool = True    # annotate concepts with a recorded contradiction
    use_plasticity: bool = True       # let Hebbian strength drive ranking


NOUS_GRAPH_ONLY = NousFeatureConfig(False, False, False, False)
NOUS_PLUS_EVIDENCE = NousFeatureConfig(True, False, False, False)
NOUS_PLUS_TEMPORAL_VALIDITY = NousFeatureConfig(True, True, False, False)
NOUS_PLUS_CONTRADICTION = NousFeatureConfig(True, True, True, False)
NOUS_FULL = NousFeatureConfig(True, True, True, True)

ABLATION_CONDITION_CONFIGS: dict[str, NousFeatureConfig] = {
    "nous_graph_only": NOUS_GRAPH_ONLY,
    "nous_plus_evidence": NOUS_PLUS_EVIDENCE,
    "nous_plus_temporal_validity": NOUS_PLUS_TEMPORAL_VALIDITY,
    "nous_plus_contradiction": NOUS_PLUS_CONTRADICTION,
    "nous_plus_plasticity": NOUS_FULL,  # last step == full Nous
}


def get_nous_context_ablated(
    question: str, field, config: NousFeatureConfig, max_nodes: int = 10,
) -> str:
    """Same retrieval as get_nous_context(), with individual mechanisms
    switchable off per `config` — for the ablation table, not for
    production use."""
    from nouse.inject import _CONTRADICTION_REL_TYPES, _rows_to_axioms

    try:
        nodes = field.node_context_for_query(question)
    except Exception:
        nodes = []
    if not nodes:
        return "[Kunskapsminne: inga relevanta koncept]"

    # Naive UTC, matching the format add_relation()/surface.py actually
    # stores valid_from/valid_until in (datetime.utcnow().isoformat(), no
    # timezone suffix). Comparing against a timezone-aware string here would
    # silently make every stored timestamp compare as "expired" — a real
    # ordering bug, not just a style mismatch.
    now_iso = datetime.utcnow().isoformat()
    lines: list[str] = []
    for node in nodes[:max_nodes]:
        name = node.get("name", "?")
        try:
            rows = field.out_relations(name) + field.in_relations(name)
        except Exception:
            rows = []

        if config.use_temporal_validity:
            rows = [
                r for r in rows
                if not r.get("valid_until") or str(r["valid_until"]) > now_iso
            ]

        axioms = _rows_to_axioms(name, rows)
        if not axioms:
            continue

        if config.use_plasticity:
            axioms.sort(key=lambda a: -a.strength)
        elif config.use_evidence:
            axioms.sort(key=lambda a: -a.evidence)
        # else: retrieval order — no ranking signal at all, the bluntest
        # "graph only" condition.

        has_contradiction = config.use_contradiction and any(
            a.rel in _CONTRADICTION_REL_TYPES for a in axioms
        )
        lines.append(name + ("  [motsägelse i grafen]" if has_contradiction else ""))
        for a in axioms[:5]:
            if config.use_evidence:
                lines.append(f"  {a.src} —[{a.rel}]→ {a.tgt}  (ev={a.evidence:.2f})")
            else:
                lines.append(f"  {a.src} —[{a.rel}]→ {a.tgt}")

    return "\n".join(lines) if lines else "[Kunskapsminne: inga relevanta relationer]"


# ── Long-context baseline ────────────────────────────────────────────────

def get_long_context_baseline(field, max_chars: int = 12000) -> str:
    """No retrieval step at all: the isolated graph's full concept
    summaries, unranked, unfiltered, truncated only by a character budget.
    This is what "long context" means as a control condition — everything
    the model could plausibly use, without Nous's retrieval or structure."""
    try:
        concepts = list(field.concepts())
    except Exception:
        concepts = []
    if not concepts:
        return "[Kunskapsminne: tomt]"

    parts: list[str] = []
    total = 0
    for c in concepts:
        name = c.get("name", "")
        if not name:
            continue
        domain = c.get("domain", "")
        try:
            summary = str(field.concept_knowledge(name).get("summary") or "").strip()
        except Exception:
            summary = ""
        line = f"{name} [{domain}]" + (f": {summary}" if summary else "")
        if total + len(line) > max_chars:
            break
        parts.append(line)
        total += len(line)

    return "\n".join(parts) if parts else "[Kunskapsminne: tomt]"


# ── Vector RAG baseline ──────────────────────────────────────────────────

@dataclass
class VectorRagIndex:
    names: list[str]
    domains: list[str]
    texts: list[str]
    vectors: list[list[float]]


def build_vector_rag_index(field) -> VectorRagIndex | None:
    """Real embedding index over the isolated graph's concept text — the
    same local embedder (`nouse.embeddings.ollama_embed.OllamaEmbedder`)
    Nous itself uses for bisociation similarity, not a hardcoded text
    block. Built once per benchmark run and reused across questions;
    only the (cheap) query embedding happens per question."""
    from nouse.embeddings.ollama_embed import OllamaEmbedder

    try:
        concepts = list(field.concepts())
    except Exception:
        concepts = []
    if not concepts:
        return None

    names, domains, texts = [], [], []
    for c in concepts:
        name = c.get("name", "")
        if not name:
            continue
        try:
            summary = str(field.concept_knowledge(name).get("summary") or "").strip()
        except Exception:
            summary = ""
        names.append(name)
        domains.append(c.get("domain", ""))
        texts.append(f"{name}: {summary}" if summary else name)

    if not texts:
        return None

    embedder = OllamaEmbedder()
    try:
        vectors = embedder.embed_texts(texts)
    except Exception:
        return None
    if len(vectors) != len(texts):
        return None

    return VectorRagIndex(names=names, domains=domains, texts=texts, vectors=vectors)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def query_vector_rag_index(index: VectorRagIndex | None, question: str, top_k: int = 5) -> str:
    """Raw retrieved text only — no graph structure, evidence, or
    temporal/contradiction reasoning. The actual retrieval mechanic a
    vector-RAG competitor would use, not the flat hardcoded block the old
    `rag` condition used."""
    if index is None or not index.texts:
        return "[Vector RAG: tomt index]"

    from nouse.embeddings.ollama_embed import OllamaEmbedder

    try:
        [query_vector] = OllamaEmbedder().embed_texts([question])
    except Exception as exc:
        return f"[Vector RAG: embedding misslyckades: {exc}]"

    scored = sorted(
        range(len(index.texts)),
        key=lambda i: -_cosine(query_vector, index.vectors[i]),
    )
    return "\n".join(f"- {index.texts[i]}" for i in scored[:top_k])
