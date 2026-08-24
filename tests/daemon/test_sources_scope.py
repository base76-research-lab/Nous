from __future__ import annotations

from pathlib import Path

from nouse.daemon.sources import scope_from_path


def test_scope_from_path_flags_health_project():
    assert scope_from_path(Path("/home/bjorn/IIC/01_PROJECTS/halsa-glp1/LOGG.md")) == "personal_health"


def test_scope_from_path_flags_glp1_mention_directly():
    assert scope_from_path(Path("/home/bjorn/IIC/00_INBOX/ljudanteckningar/2026-08-23-gym-glp1-001.md")) in (
        "personal_health", "voice_notes",
    )


def test_scope_from_path_flags_nous_source_tree():
    assert scope_from_path(Path("/home/bjorn/Work/nous/src/nouse/field/surface.py")) == "nous_system"


def test_scope_from_path_flags_voice_notes():
    assert scope_from_path(Path("/home/bjorn/IIC/00_INBOX/ljudanteckningar/2026-08-22-test-01.md")) == "voice_notes"


def test_scope_from_path_flags_research_library():
    assert scope_from_path(Path("/home/bjorn/IIC/02_LIBRARY/RESEARCH/papers/foo.md")) == "research_plg"


def test_scope_from_path_defaults_to_general_for_unrelated_path():
    assert scope_from_path(Path("/home/bjorn/IIC/01_PROJECTS/cdf/kurs.md")) == "general"


def test_scope_from_path_flags_person_md():
    assert scope_from_path(Path("/home/bjorn/IIC/04_SYSTEM/system/PERSON.md")) == "user_model"


def test_scope_from_path_flags_claude_memory_dir():
    assert scope_from_path(
        Path("/home/bjorn/.claude/projects/-home-bjorn/memory/bjorn-sells-by-demonstration.md")
    ) == "user_model"
