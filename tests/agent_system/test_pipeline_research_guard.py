from __future__ import annotations

from nouse.agent_system.pipeline import _touches_research, _touches_research_by_scope


def test_touches_research_still_matches_the_env_marker_list(monkeypatch):
    """The curated .env list (NOUSE_RESEARCH_LOCAL_MARKERS) is real and
    already reasonably populated — this fix is additive, not a
    replacement. Confirm the original mechanism still works."""
    monkeypatch.setenv("NOUSE_RESEARCH_LOCAL_MARKERS", "plg,acta sociologica")

    assert _touches_research("hjälp mig sammanfatta PLG-artikeln") is True
    assert _touches_research("nothing related here") is False


def test_touches_research_by_scope_catches_an_iic_path_not_in_the_marker_list(monkeypatch):
    """The gap this fix closes: request text that references an IIC path
    the curated marker list was never updated to include."""
    monkeypatch.delenv("NOUSE_RESEARCH_LOCAL_MARKERS", raising=False)

    text = "titta på /home/bjorn/IIC/01_PROJECTS/some-new-paper/draft.md"
    assert _touches_research_by_scope(text) is True
    assert _touches_research(text) is True


def test_touches_research_by_scope_ignores_plain_computer_zone_text(monkeypatch):
    """Must not over-trigger — most requests are not research and should
    not be forced to a local executor."""
    monkeypatch.delenv("NOUSE_RESEARCH_LOCAL_MARKERS", raising=False)

    assert _touches_research_by_scope("what's the weather like today") is False
    assert _touches_research_by_scope("check my calendar for tomorrow") is False


def test_touches_research_by_scope_excludes_health_and_user_model():
    """personal_health/user_model are governed by other rules (workspace
    scoping), not hard rule 1 — folding them into the research-local check
    would over-trigger it for content this rule was never about."""
    health_text = "hur var min glp1-dos den här veckan"
    person_text = "/home/bjorn/IIC/04_SYSTEM/system/PERSON.md"

    assert _touches_research_by_scope(health_text) is False
    assert _touches_research_by_scope(person_text) is False


def test_touches_research_by_scope_matches_nous_own_source_tree_as_not_research():
    """nous_system (Nous's own code) is a public open-source repo, not
    private research — must stay unaffected by this rule."""
    assert _touches_research_by_scope("/home/bjorn/Work/nous/src/nouse/inject.py") is False
