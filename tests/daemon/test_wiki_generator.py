from __future__ import annotations

from pathlib import Path

from nouse.daemon.wiki_generator import (
    concept_qualifies_for_page,
    slugify,
    render_wiki_page,
    should_regenerate,
    generate_wiki_pages,
    generate_wiki_index,
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


def test_render_wiki_page_includes_depth_and_top_of_mind_score(tmp_path):
    field = _mk_field(tmp_path)
    field.add_relation("Test Concept", "related_to", "Target", source_tag="file:///source.md")
    content = render_wiki_page(field, "Test Concept")
    assert "depth:" in content
    assert "top_of_mind_score:" in content


def test_generate_wiki_index_ranks_strengthened_concept_above_untouched_one(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUSE_WIKI_DIR", str(tmp_path / "wiki"))
    field = _mk_field(tmp_path)

    field.add_relation("Hot Concept", "relates_to", "H", source_tag="file")
    field.strengthen("Hot Concept", "H", delta=2.0)

    field.add_relation("Cold Concept", "relates_to", "C", source_tag="file")

    generate_wiki_pages(field)
    result = generate_wiki_index(field)

    assert result["indexed"] >= 2
    index_text = (tmp_path / "wiki" / "_index.md").read_text(encoding="utf-8")
    assert index_text.index("Hot Concept") < index_text.index("Cold Concept")


def test_generate_wiki_index_excludes_non_qualifying_concepts(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUSE_WIKI_DIR", str(tmp_path / "wiki"))
    field = _mk_field(tmp_path)
    field.add_relation("Unsourced Concept", "relates_to", "Other")  # default "auto" tag

    generate_wiki_pages(field)
    generate_wiki_index(field)

    index_text = (tmp_path / "wiki" / "_index.md").read_text(encoding="utf-8")
    assert "Unsourced Concept" not in index_text


def test_generate_wiki_pages_disambiguates_slug_collisions(tmp_path, monkeypatch):
    # Verified against the live graph 2026-08-25: names differing only by
    # case/punctuation (CONTEXT / Context / context) collapse to the same
    # slug and, without disambiguation, silently overwrite each other.
    monkeypatch.setenv("NOUSE_WIKI_DIR", str(tmp_path / "wiki"))
    field = _mk_field(tmp_path)
    field.add_relation("Context", "relates_to", "X", source_tag="file")
    field.add_relation("CONTEXT", "relates_to", "Y", source_tag="file")
    field.add_relation("context", "relates_to", "Z", source_tag="file")

    result = generate_wiki_pages(field)

    # All three qualify and are distinct concepts -- none should be silently
    # dropped just because they collide on slugify().
    assert result["generated"] >= 3
    written = list((tmp_path / "wiki").glob("context*.md"))
    assert len(written) >= 3
