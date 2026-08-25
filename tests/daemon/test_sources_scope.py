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


def test_scope_from_path_defaults_to_iic_general_for_unrelated_iic_path():
    """Var tidigare "general" (obemärkt, icke-sensitiv) innan 2026-08-25-
    fixen — se SENSITIVE_SCOPES-kommentaren i field/surface.py för varför
    ett IIC-projekt utan egen regel inte längre får falla igenom oskyddat."""
    assert scope_from_path(Path("/home/bjorn/IIC/01_PROJECTS/cdf/kurs.md")) == "iic_general"


def test_scope_from_path_falls_back_to_general_only_outside_home_and_iic():
    assert scope_from_path(Path("/mnt/external-drive/random.md")) == "general"


def test_scope_from_path_flags_person_md():
    assert scope_from_path(Path("/home/bjorn/IIC/04_SYSTEM/system/PERSON.md")) == "user_model"


def test_scope_from_path_flags_claude_memory_dir():
    assert scope_from_path(
        Path("/home/bjorn/.claude/projects/-home-bjorn/memory/bjorn-sells-by-demonstration.md")
    ) == "user_model"


def test_scope_from_path_flags_unmatched_iic_content_as_iic_general():
    """Anything under IIC that isn't already caught by a more specific rule
    (research_plg, voice_notes, ...) must not silently fall through to the
    old undifferentiated "general" bucket — see field/surface.py's
    SENSITIVE_SCOPES comment (2026-08-25) on why that mattered in practice."""
    assert scope_from_path(Path("/home/bjorn/IIC/01_PROJECTS/some-project/notes.md")) == "iic_general"
    assert scope_from_path(Path("/home/bjorn/IIC/03_WORKBENCH/ideation/draft.md")) == "iic_general"


def test_scope_from_path_flags_other_home_content_as_computer_general():
    assert scope_from_path(Path("/home/bjorn/Documents/random-note.txt")) == "computer_general"


def test_scope_from_path_prefers_specific_rules_over_iic_general():
    """The IIC/computer zone check must not shadow the more specific,
    already-reviewed rules above it (research_plg etc.)."""
    assert scope_from_path(Path("/home/bjorn/IIC/02_LIBRARY/RESEARCH/papers/foo.md")) == "research_plg"
