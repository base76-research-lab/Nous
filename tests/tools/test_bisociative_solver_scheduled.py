from __future__ import annotations

import nouse.tools.bisociative_solver as bs


class _FakeResponse:
    def __init__(self, payload: dict, *, status_code: int = 200):
        self._payload = dict(payload)
        self.status_code = status_code

    def json(self) -> dict:
        return dict(self._payload)


def test_fetch_bisociation_candidates_calls_api_bisoc(monkeypatch):
    called: dict = {}

    def _fake_get(url, params=None, timeout=None):  # noqa: ANN001
        called["url"] = url
        called["params"] = params
        return _FakeResponse({"candidates": [{"domain_a": "a", "domain_b": "b", "tau": 0.7}]})

    monkeypatch.setattr(bs.httpx, "get", _fake_get)
    candidates = bs.fetch_bisociation_candidates(tau=0.6)

    assert called["url"].endswith("/api/bisoc")
    assert candidates == [{"domain_a": "a", "domain_b": "b", "tau": 0.7}]


def test_scheduled_pass_skips_when_no_candidates(monkeypatch, tmp_path):
    monkeypatch.setattr(bs, "_EXPLORED_PAIRS_PATH", tmp_path / "explored.json")
    monkeypatch.setattr(bs, "fetch_bisociation_candidates", lambda tau=0.55: [])

    results = bs.scheduled_bisociation_pass()

    assert results == []


def test_scheduled_pass_solves_top_unexplored_pair_and_logs_finding(monkeypatch, tmp_path):
    monkeypatch.setattr(bs, "_EXPLORED_PAIRS_PATH", tmp_path / "explored.json")
    monkeypatch.setattr(
        bs, "fetch_bisociation_candidates",
        lambda tau=0.55: [{"domain_a": "topologi", "domain_b": "musikteori", "tau": 0.81}],
    )

    solve_calls: list[str] = []

    def _fake_solve(problem, context="", feedback=True):
        solve_calls.append(problem)
        result = bs.SolverResult(problem=problem)
        result.suggestions = [bs.Suggestion("musikteori", "resonans", "app", "impl", 0.8, 0.6)]
        result.synthesis = "en bro mellan topologi och musikteori"
        result.ingested = 1
        return result

    monkeypatch.setattr(bs, "solve", _fake_solve)

    logged: list[dict] = []

    def _fake_write_event(**kwargs):
        logged.append(kwargs)

    import nouse.daemon.journal as journal
    monkeypatch.setattr(journal, "write_bisociation_finding_event", _fake_write_event)

    results = bs.scheduled_bisociation_pass(max_pairs=1)

    assert len(results) == 1
    assert "topologi" in solve_calls[0] and "musikteori" in solve_calls[0]
    assert logged[0]["domain_a"] == "topologi"
    assert logged[0]["domain_b"] == "musikteori"
    assert logged[0]["ingested"] == 1

    # Redan utforskade par körs inte igen
    solve_calls.clear()
    logged.clear()
    results_again = bs.scheduled_bisociation_pass(max_pairs=1)
    assert results_again == []
    assert solve_calls == []
