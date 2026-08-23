from __future__ import annotations

from pathlib import Path

import nouse.daemon.journal as journal


def test_write_and_count_bisociation_finding_events(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_DIR", tmp_path)

    journal.write_bisociation_finding_event(
        domain_a="topologi", domain_b="musikteori", tau=0.81,
        suggestions=2, ingested=1, synthesis="en bro mellan topologi och musikteori",
    )
    journal.write_bisociation_finding_event(
        domain_a="termodynamik", domain_b="ekonomi", tau=0.63,
        suggestions=1, ingested=0, synthesis="entropi som modell för marknader",
    )

    counts = journal.count_bisociation_finding_events("2000-01-01T00:00:00")

    assert counts["found"] == 2
    assert counts["ingested_total"] == 1
    assert counts["tau_mean"] == round((0.81 + 0.63) / 2, 3)


def test_count_bisociation_finding_events_respects_since_ts(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_DIR", tmp_path)
    journal.write_bisociation_finding_event(domain_a="a", domain_b="b", tau=0.7)

    counts = journal.count_bisociation_finding_events("2999-01-01T00:00:00")

    assert counts["found"] == 0
