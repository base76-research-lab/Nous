"""Tests for user_model_seed — structured (non-LLM) seeding of the
scope="user_model" subgraph from PERSON.md and Claude memory files."""
from __future__ import annotations

from pathlib import Path

from nouse.daemon.user_model_seed import (
    parse_memory_files,
    parse_person_md,
    seed_user_model,
)
from nouse.field.surface import FieldSurface

PERSON_MD = """\
# User context — Björn Wikström

Not a biography.

## How to work with Björn

- Be clear, direct and structurally precise.
- Give short feedback first; add detail only when it changes the decision.

## How Björn learns

- Start with the whole map, then move into detail.

## Some New Section

- A bullet under an unmapped section.
"""

MEMORY_USER = """\
---
name: bjorn-example-user
description: A concise user-type description.
metadata:
  type: user
---

Full body text explaining the pattern in depth.
"""

MEMORY_FEEDBACK = """\
---
name: bjorn-example-feedback
description: A concise feedback-type description.
metadata:
  type: feedback
---

Full body text about feedback.
"""

MEMORY_PROJECT = """\
---
name: bjorn-example-project
description: A project-type description that should be excluded.
metadata:
  type: project
---

Body text.
"""


def _mk_person_md(tmp_path: Path) -> Path:
    p = tmp_path / "PERSON.md"
    p.write_text(PERSON_MD, encoding="utf-8")
    return p


def _mk_memory_dir(tmp_path: Path) -> Path:
    d = tmp_path / "memory"
    d.mkdir()
    (d / "bjorn-example-user.md").write_text(MEMORY_USER, encoding="utf-8")
    (d / "bjorn-example-feedback.md").write_text(MEMORY_FEEDBACK, encoding="utf-8")
    (d / "bjorn-example-project.md").write_text(MEMORY_PROJECT, encoding="utf-8")
    (d / "MEMORY.md").write_text("# index, not a memory\n", encoding="utf-8")
    return d


def test_parse_person_md_maps_known_sections_to_types(tmp_path):
    rows = parse_person_md(_mk_person_md(tmp_path))
    types = {r["type"] for r in rows}
    assert "kommunikationsstil" in types
    assert "lärstil" in types
    bullets = {r["tgt"] for r in rows}
    assert "Be clear, direct and structurally precise." in bullets


def test_parse_person_md_slugifies_unmapped_sections(tmp_path):
    rows = parse_person_md(_mk_person_md(tmp_path))
    slugged = [r for r in rows if r["tgt"] == "A bullet under an unmapped section."]
    assert len(slugged) == 1
    assert slugged[0]["type"] == "avsnitt_some_new_section"


def test_parse_person_md_missing_file_returns_empty(tmp_path):
    assert parse_person_md(tmp_path / "does_not_exist.md") == []


def test_parse_memory_files_includes_user_and_feedback_only(tmp_path):
    rows = parse_memory_files(_mk_memory_dir(tmp_path))
    descriptions = {r["tgt"] for r in rows}
    assert "A concise user-type description." in descriptions
    assert "A concise feedback-type description." in descriptions
    assert "A project-type description that should be excluded." not in descriptions


def test_parse_memory_files_skips_memory_md_index(tmp_path):
    rows = parse_memory_files(_mk_memory_dir(tmp_path))
    assert all("index, not a memory" not in r["why"] for r in rows)


def test_parse_memory_files_why_includes_body(tmp_path):
    rows = parse_memory_files(_mk_memory_dir(tmp_path))
    row = next(r for r in rows if "user-type" in r["tgt"])
    assert "Full body text explaining the pattern in depth." in row["why"]


def test_seed_user_model_writes_scoped_relations(tmp_path):
    field = FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)
    result = seed_user_model(field, _mk_person_md(tmp_path), _mk_memory_dir(tmp_path))

    assert result["added"] > 0
    assert result["skipped"] == 0

    rows = field.query_all_relations_with_metadata(include_evidence=True)
    person_rows = [r for r in rows if r["src"] == "Björn Wikström"]
    assert len(person_rows) == result["added"]

    concept_scope = field._sql.execute(
        "SELECT scope FROM concept WHERE name = 'Björn Wikström'"
    ).fetchone()
    assert concept_scope["scope"] == "user_model"


def test_seed_user_model_is_idempotent(tmp_path):
    field = FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)
    person_md = _mk_person_md(tmp_path)
    memory_dir = _mk_memory_dir(tmp_path)

    first = seed_user_model(field, person_md, memory_dir)
    second = seed_user_model(field, person_md, memory_dir)

    assert first["added"] > 0
    assert second["added"] == 0
    assert second["skipped"] == first["added"]


def test_seed_user_model_picks_up_new_bullets_on_rerun(tmp_path):
    field = FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)
    person_md = _mk_person_md(tmp_path)
    memory_dir = _mk_memory_dir(tmp_path)

    seed_user_model(field, person_md, memory_dir)

    person_md.write_text(
        PERSON_MD + "\n## How to work with Björn\n\n- A brand new bullet.\n",
        encoding="utf-8",
    )
    result = seed_user_model(field, person_md, memory_dir)
    assert result["added"] >= 1
