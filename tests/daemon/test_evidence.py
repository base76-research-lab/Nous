from __future__ import annotations

from pathlib import Path

from nouse.daemon.evidence import activate_relation, run_evidence_pass
from nouse.field.surface import FieldSurface


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
