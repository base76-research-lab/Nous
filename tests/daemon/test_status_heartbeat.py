from __future__ import annotations

import json
from datetime import datetime

from nouse.daemon import main


def test_refresh_status_heartbeat_preserves_cycle_stats(tmp_path, monkeypatch):
    status_path = tmp_path / "status.json"
    status_path.write_text(
        json.dumps({"concepts": 12, "relations": 34, "cycle": 6, "updated": "old"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "_STATUS_FILE", status_path)

    main._refresh_status_heartbeat(7, phase="source_ingest", progress={"docs_total": 3})

    data = json.loads(status_path.read_text(encoding="utf-8"))
    assert data["concepts"] == 12
    assert data["relations"] == 34
    assert data["cycle"] == 7
    assert data["phase"] == "source_ingest"
    assert data["progress"] == {"docs_total": 3}
    assert datetime.fromisoformat(data["updated"])
    assert not status_path.with_name(".status.json.tmp").exists()
