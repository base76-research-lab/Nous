from __future__ import annotations

from pathlib import Path

from nouse.daemon.wiki_generator import (
    concept_qualifies_for_page,
    slugify,
    render_wiki_page,
    should_regenerate,
    generate_wiki_pages,
)
from nouse.field.surface import FieldSurface


def _mk_field(tmp_path: Path) -> FieldSurface:
    return FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)


def test_concept_qualifies_with_named_source_tag(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("My Concept", domain="misc")
    field.add_relation("My Concept", "related_to", "Other Thing", source_tag="file:///data.txt")

    assert concept_qualifies_for_page(field, "My Concept") is True


def test_concept_does_not_qualify_with_auto_source_tag(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("My Concept", domain="misc")
    # Default source_tag is "auto"
    field.add_relation("My Concept", "related_to", "Other Thing")

    assert concept_qualifies_for_page(field, "My Concept") is False


def test_concept_does_not_qualify_with_no_relations(tmp_path):
    field = _mk_field(tmp_path)
    field.add_concept("My Concept", domain="misc")

    assert concept_qualifies_for_page(field, "My Concept") is False


def test_slugify_normalizes_spaces_and_case():
    assert slugify("PLG Modellen") == "plg-modellen"
    # lower() -> "bjorn's idea!"; non-[a-z0-9-] chars (incl. the apostrophe,
    # "!", and existing spaces) all become " "; runs of "-"/whitespace then
    # collapse to a single "-"; leading/trailing "-" stripped. The "s" in
    # "bjorn's" is itself alphanumeric and survives — the apostrophe alone
    # becomes a separator, so it does NOT get absorbed into "bjorn".
    assert slugify("Bjorn's Idea!") == "bjorn-s-idea"


def test_generate_wiki_pages_writes_file_for_qualifying_concept(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUSE_WIKI_DIR", str(tmp_path / "wiki"))

    field = _mk_field(tmp_path)
    concept_name = "Test Concept"
    field.add_concept(concept_name, domain="test")
    field.add_relation(concept_name, "related_to", "Target", source_tag="file:///source.md")

    result = generate_wiki_pages(field)

    # add_relation() creates both endpoint concepts, and "Target" qualifies
    # too (same well-sourced relation, seen from its in_relations side) —
    # both legitimately get a page, not just the one this test names.
    assert result["generated"] == 2
    assert result["skipped"] == 0

    expected_file = tmp_path / "wiki" / f"{slugify(concept_name)}.md"
    assert expected_file.exists()
    assert concept_name in expected_file.read_text(encoding="utf-8")


def test_generate_wiki_pages_skips_non_qualifying_concept(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUSE_WIKI_DIR", str(tmp_path / "wiki"))

    field = _mk_field(tmp_path)
    concept_name = "Test Concept"
    field.add_concept(concept_name, domain="test")
    # Default source_tag ("auto") does not qualify
    field.add_relation(concept_name, "related_to", "Target")

    result = generate_wiki_pages(field)

    assert result["generated"] == 0
    assert result["skipped"] >= 1

    expected_file = tmp_path / "wiki" / f"{slugify(concept_name)}.md"
    assert not expected_file.exists()


def test_should_regenerate_true_when_no_existing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUSE_WIKI_DIR", str(tmp_path / "wiki"))

    field = _mk_field(tmp_path)
    concept_name = "Test Concept"
    field.add_concept(concept_name, domain="test")
    field.add_relation(concept_name, "related_to", "Target", source_tag="file:///source.md")

    assert not (tmp_path / "wiki" / f"{slugify(concept_name)}.md").exists()
    assert should_regenerate(field, concept_name) is True


def test_should_regenerate_false_when_revision_count_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUSE_WIKI_DIR", str(tmp_path / "wiki"))
    field = _mk_field(tmp_path)
    concept_name = "Test Concept"
    field.add_concept(concept_name, domain="test")
    field.add_relation(concept_name, "related_to", "Target", source_tag="file:///source.md")
    generate_wiki_pages(field)
    assert should_regenerate(field, concept_name) is False


def test_render_wiki_page_never_calls_a_write_method(tmp_path):
    field = _mk_field(tmp_path)
    concept_name = "Test Concept"
    field.add_concept(concept_name, domain="test")
    field.add_relation(concept_name, "related_to", "Target", source_tag="file:///source.md")
    before_count = field.concept_knowledge(concept_name)["revision_count"]
    render_wiki_page(field, concept_name)
    after_count = field.concept_knowledge(concept_name)["revision_count"]
    assert before_count == after_count
