"""
daemon.user_model_seed — strukturerad seedning av Björn-profilen
===================================================================
Fas 3, "systemet bör känna mig till punkt och pricka" (2026-08-24
konversation). Bygger `scope="user_model"`-subgrafen från redan
kuraterat, avsiktligt skrivet material — INTE via extract_relations()s
LLM-baserade tematiska extraktion.

Varför inte samma pipeline som allt annat: LongMemEval-grundorsaken
(se docs/NOUS_NEXT_GENERATION_PLAN.md) visade exakt vad som går fel när
precisa, operationella meningar ("ge kort feedback först") körs genom en
extraktor byggd för tematiska relationer mellan idéer — de späds ut till
vaga kopplingar och tappar det som gjorde dem användbara. Källorna här
(PERSON.md, Claude-minnesfiler) är redan skrivna som strukturerade,
precisa påståenden — parsning, inte LLM-tolkning, räcker och bevarar
exaktheten.

Idempotent: kör man om seedningen (t.ex. efter att PERSON.md eller en
minnesfil uppdaterats) läggs bara nya/ändrade relationer till, inga
dubbletter av identiska (src, type, tgt)-tripplar.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from nouse.field.surface import FieldSurface

SUBJECT = "Björn Wikström"
SOURCE_TAG = "user_model_seed_v1"

# Sektionsrubrik i PERSON.md → relationstyp. Okänd rubrik faller tillbaka
# till en slugifierad variant i stället för att tystas bort — filen kan
# växa utan att seedningen tyst missar nya avsnitt.
_PERSON_MD_SECTION_TYPES = {
    "how to work with björn": "kommunikationsstil",
    "how björn learns": "lärstil",
    "cognitive and communication needs": "kognitivt_behov",
    "decision rule for agents": "användningsregel",
}

# Minnesfilers metadata.type → relationstyp. Bara typer som faktiskt
# beskriver VEM Björn är (inte pågående projektstatus/referenser, som
# hör hemma i STATUS.md-liknande dokument, inte en personmodell).
_MEMORY_TYPE_RELATION_TYPES = {
    "user": "personmönster",
    "feedback": "arbetssätt",
}

_WHY_MAX_CHARS = 1200


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.strip().lower()).strip("_")
    return f"avsnitt_{slug}" if slug else "avsnitt_okänt"


def parse_person_md(path: Path) -> list[dict[str, Any]]:
    """Parsa `## Sektion` + punktlistor i PERSON.md till relation-dicts.
    En bullet = en relation, med hela bullet-texten som tgt (inte en
    LLM-genererad sammanfattning) så exaktheten bevaras."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")

    rows: list[dict[str, Any]] = []
    current_section = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current_section = line[3:].strip()
            continue
        if not current_section:
            continue
        if line.startswith("- "):
            bullet = line[2:].strip()
            if not bullet:
                continue
            rel_type = _PERSON_MD_SECTION_TYPES.get(
                current_section.lower(), _slugify(current_section)
            )
            rows.append({
                "src": SUBJECT,
                "type": rel_type,
                "tgt": bullet,
                "why": f"Källa: {path.name}, avsnitt \"{current_section}\".",
                "domain_src": "person",
                "domain_tgt": "person",
            })
    return rows


def _extract_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Minimal frontmatter-parser (name/description/metadata.type) — inga
    externa YAML-beroenden, memory-filerna har ett känt, enkelt format."""
    meta: dict[str, str] = {}
    if not text.startswith("---"):
        return meta, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return meta, text
    header, body = parts[1], parts[2]
    in_metadata = False
    for line in header.splitlines():
        stripped = line.strip()
        if stripped == "metadata:":
            in_metadata = True
            continue
        if in_metadata and stripped.startswith("type:"):
            meta["type"] = stripped.split(":", 1)[1].strip()
            in_metadata = False
            continue
        if ":" in stripped and not in_metadata:
            key, _, value = stripped.partition(":")
            meta[key.strip()] = value.strip()
    return meta, body.strip()


def parse_memory_files(memory_dir: Path) -> list[dict[str, Any]]:
    """Parsa Claude-minnesfiler med metadata.type i {user, feedback} till
    relation-dicts. tgt = description (kort, redan en mening); why = hela
    kroppstexten (upp till _WHY_MAX_CHARS) så resonemanget bakom bevaras,
    inte bara slutsatsen."""
    if not memory_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(memory_dir.glob("*.md")):
        if path.name == "MEMORY.md":
            continue
        meta, body = _extract_frontmatter(path.read_text(encoding="utf-8"))
        mem_type = meta.get("type", "")
        rel_type = _MEMORY_TYPE_RELATION_TYPES.get(mem_type)
        if not rel_type:
            continue
        description = meta.get("description", "").strip()
        if not description:
            continue
        rows.append({
            "src": SUBJECT,
            "type": rel_type,
            "tgt": description,
            "why": f"Källa: {path.name}. {body[:_WHY_MAX_CHARS]}".strip(),
            "domain_src": "person",
            "domain_tgt": "person",
        })
    return rows


def seed_user_model(
    field: FieldSurface,
    person_md_path: Path,
    memory_dir: Path,
) -> dict[str, int]:
    """Seeda scope="user_model"-subgrafen. Returnerar {"added": N, "skipped": M}
    — skipped är redan existerande identiska (src,type,tgt)-relationer
    (idempotens vid omkörning)."""
    rows = parse_person_md(person_md_path) + parse_memory_files(memory_dir)

    added = 0
    skipped = 0
    for row in rows:
        existing = field._sql.execute(
            "SELECT 1 FROM relation WHERE src = ? AND type = ? AND tgt = ? LIMIT 1",
            (row["src"], row["type"], row["tgt"]),
        ).fetchone()
        if existing:
            skipped += 1
            continue
        field.add_relation(
            row["src"], row["type"], row["tgt"],
            why=row["why"],
            domain_src=row["domain_src"],
            domain_tgt=row["domain_tgt"],
            source_tag=SOURCE_TAG,
            scope_src="user_model",
            scope_tgt="user_model",
        )
        added += 1
    return {"added": added, "skipped": skipped}
