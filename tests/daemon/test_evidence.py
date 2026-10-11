from __future__ import annotations

from pathlib import Path

import pytest

from nouse.daemon.evidence import (
    _bump_evidence,
    _set_evidence,
    activate_relation,
    run_evidence_pass,
)
from nouse.field.surface import (
    PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING,
    FieldSurface,
)


def _mk_field(tmp_path: Path) -> FieldSurface:
    return FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)


def test_activate_relation_never_changes_evidence_score(tmp_path):
    # Real bug, found via a verified relay:codex dialogue 2026-08-25: this
    # used to bump evidence_score on every activation (query hit,
    # bisociation), letting mere retrieval climb toward is_strong (>=0.75)
    # with zero new independent evidence.
    field = _mk_field(tmp_path)
    field.add_relation("A", "relates_to", "B", why="test", evidence_score=0.5)
    before = field.out_relations("A")[0]["evidence_score"]

    for _ in range(50):
        activate_relation(field, "A", "B")

    after = field.out_relations("A")[0]["evidence_score"]
    assert after == before


def test_activate_relation_still_strengthens_hebbian_weight(tmp_path):
    # The fix removes the evidence bump but must not remove the real,
    # intended salience effect.
    field = _mk_field(tmp_path)
    field.add_relation("A", "relates_to", "B", why="test")
    before = field.out_relations("A")[0]["strength"]

    activate_relation(field, "A", "B")

    after = field.out_relations("A")[0]["strength"]
    assert after > before


def test_activate_relation_accepts_rel_type_without_crashing(tmp_path):
    # The checked-in version referenced rel_type in its body without
    # accepting it as a parameter -- a NameError silently swallowed by a
    # bare except, so this returned False and did nothing on every real
    # call. Verified directly against the source before fixing.
    field = _mk_field(tmp_path)
    field.add_relation("A", "relates_to", "B", why="test")
    assert activate_relation(field, "A", "B", rel_type="relates_to") is True


def test_run_evidence_pass_never_mutates_evidence_score(tmp_path):
    # Real, live bug (unlike activate_relation, this one had a real
    # caller -- NightRun): the old SQL WHERE clause already restricted
    # rows to strictly between the promote/demote thresholds, making
    # those two branches unreachable, so every selected row got the same
    # unconditional +0.01 every cycle regardless of any new evidence.
    field = _mk_field(tmp_path)
    field.add_relation("A", "relates_to", "B", why="test", evidence_score=0.5)
    before = field.out_relations("A")[0]["evidence_score"]

    result = run_evidence_pass(field)

    after = field.out_relations("A")[0]["evidence_score"]
    assert after == before
    assert result.promoted == 0
    assert result.demoted == 0
    assert result.activated == 0


# ── Fas 1-review hål 1: _bump_evidence() måste respektera evidenstaket ─────────

def test_bump_evidence_never_exceeds_ceiling_without_named_support(tmp_path):
    # Hål 1: taklös direkt-UPDATE. En modellhärledd relation får aldrig
    # bumpas över taket utan namngiven observed/user-support.
    from nouse.field.surface import PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING
    field = _mk_field(tmp_path)
    field.add_relation("A", "suggests", "B", why="model candidate",
                       evidence_score=0.6, source_tag="ghost_q")
    _bump_evidence(field, "A", "B", delta=0.5)
    after = field.out_relations("A")[0]["evidence_score"]
    assert after <= PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING


def test_bump_evidence_scopes_update_to_rel_type(tmp_path):
    # Hål 1, andra halvan: WHERE saknade `type`, så SQL och NetworkX
    # divergerade när flera typer delade samma src/tgt-par.
    field = _mk_field(tmp_path)
    field.add_relation("A", "relates_to", "B", why="one",
                       evidence_score=0.5, source_tag="s:support-a",
                       provenance_class="observed_source",
                       support_refs=("s:support-a",))
    field.add_relation("A", "causes", "B", why="two",
                       evidence_score=0.5, source_tag="s:support-b",
                       provenance_class="observed_source",
                       support_refs=("s:support-b",))
    _bump_evidence(field, "A", "B", delta=0.1, rel_type="causes")
    scores = {
        row["type"]: row["evidence_score"]
        for row in field._sql.execute(
            "SELECT type, evidence_score FROM relation WHERE src = 'A' AND tgt = 'B'"
        ).fetchall()
    }
    assert scores["causes"] == 0.6
    assert scores["relates_to"] == 0.5


def test_bump_evidence_allows_named_observed_support_above_ceiling(tmp_path):
    # Positivt kontrakt: namngiven observed-support FÅR bära evidens över taket.
    field = _mk_field(tmp_path)
    field.add_relation("A", "documents", "B", why="named source",
                       evidence_score=0.9, source_tag="doi:10.1/x",
                       provenance_class="observed_source",
                       support_refs=("doi:10.1/x",))
    _bump_evidence(field, "A", "B", delta=0.05)
    after = field.out_relations("A")[0]["evidence_score"]
    assert after == pytest.approx(0.95)


# ── Fas 1-review hål 2: _set_evidence() måste respektera evidenstaket ──────────

def test_set_evidence_never_exceeds_ceiling_without_named_support(tmp_path):
    # Hål 2: godtycklig evidenssättning, idag oanropad men live importbar.
    from nouse.field.surface import PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING
    field = _mk_field(tmp_path)
    field.add_relation("A", "suggests", "B", why="model candidate",
                       evidence_score=0.5, source_tag="ghost_q")
    _set_evidence(field, "A", "B", 0.99)
    after = field.out_relations("A")[0]["evidence_score"]
    assert after <= PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING


# ── Fas 1-review hål 3: evidence.confirm_relation skuggar surface-versionen ────

def test_evidence_confirm_relation_name_collision_removed():
    # Hål 3: samma namn, taklös in-place-bump. Namnkrocken ska vara borta
    # medan surface-versionen (enda legitima bekräftelsevägen) finns kvar.
    import nouse.daemon.evidence as evidence_module
    from nouse.field.surface import FieldSurface as _FS
    assert not hasattr(evidence_module, "confirm_relation"), (
        "nouse.daemon.evidence.confirm_relation skuggar fortfarande "
        "FieldSurface.confirm_relation"
    )
    assert hasattr(_FS, "confirm_relation")
