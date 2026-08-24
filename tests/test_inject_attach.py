from __future__ import annotations

import sys
from types import SimpleNamespace

import nouse.inject as inject


class _DummyLocalBrain:
    def __init__(self, db_path=None, read_only: bool = False):
        self.db_path = db_path
        self.read_only = read_only


def test_attach_prefers_http_when_daemon_is_online(monkeypatch):
    class _DummyClient:
        def __init__(self, timeout: float = 30.0):
            self.timeout = timeout

    def _fake_get(url: str, timeout: float = 1.0):
        return SimpleNamespace(status_code=200)

    fake_httpx = SimpleNamespace(get=_fake_get, Client=_DummyClient)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    brain = inject.attach(prefer_http=True)

    assert isinstance(brain, inject.NouseBrainHTTP)


def test_attach_falls_back_to_local_brain_when_http_unavailable(monkeypatch):
    def _fake_get(url: str, timeout: float = 1.0):
        raise RuntimeError("daemon offline")

    fake_httpx = SimpleNamespace(get=_fake_get, Client=object)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    monkeypatch.setattr(inject, "NouseBrain", _DummyLocalBrain)

    brain = inject.attach(prefer_http=True, read_only=True)

    assert isinstance(brain, _DummyLocalBrain)
    assert brain.read_only is True


def test_attach_can_force_local_mode(monkeypatch):
    monkeypatch.setattr(inject, "NouseBrain", _DummyLocalBrain)

    brain = inject.attach(prefer_http=False)

    assert isinstance(brain, _DummyLocalBrain)


def test_query_returns_incoming_relation_for_target(tmp_path):
    brain = inject.NouseBrain(db_path=tmp_path / "field.sqlite")
    brain.add(
        "evidence", "supports", "reproducibility",
        why="A complete run includes raw outputs.", evidence_score=0.82,
    )

    result = brain.query("reproducibility")

    assert result.has_knowledge is True
    assert [(a.src, a.rel, a.tgt) for a in result.axioms] == [
        ("evidence", "supports", "reproducibility"),
    ]


def test_http_add_propagates_server_errors():
    class Response:
        def raise_for_status(self):
            raise RuntimeError("server rejected write")

    class Client:
        def post(self, url, json):
            return Response()

    brain = object.__new__(inject.NouseBrainHTTP)
    brain._base = "http://127.0.0.1:8765"
    brain._client = Client()

    try:
        brain.add("a", "supports", "b")
    except RuntimeError as error:
        assert str(error) == "server rejected write"
    else:
        raise AssertionError("HTTP write failure was swallowed")
