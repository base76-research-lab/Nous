from __future__ import annotations

import nouse.web.server as ws


class _FakeFieldWithScopes:
    def __init__(self):
        self._rows = [
            {"name": "blodtryck_mätning", "domain": "halsa", "scope": "personal_health"},
            {"name": "blodtryck_teori", "domain": "medicin", "scope": "general"},
        ]

    def concepts(self, domain=None, limit=None, exclude_scopes=None):
        if not exclude_scopes:
            return list(self._rows)
        return [r for r in self._rows if r["scope"] not in exclude_scopes]

    def out_relations(self, name):
        return []


async def test_context_excludes_sensitive_scope_by_default(monkeypatch):
    monkeypatch.setattr(ws, "get_field", lambda: _FakeFieldWithScopes())

    result = await ws.post_context(ws.ContextRequest(query="blodtryck", top_k=5))

    assert "blodtryck_mätning" not in result["nodes"]
    assert "blodtryck_teori" in result["nodes"]
    assert "blodtryck_mätning" not in result["context_block"]
    assert "blodtryck_teori" in result["context_block"]


async def test_context_includes_sensitive_scope_when_explicitly_requested(monkeypatch):
    monkeypatch.setattr(ws, "get_field", lambda: _FakeFieldWithScopes())

    result = await ws.post_context(ws.ContextRequest(query="blodtryck", top_k=5, include_sensitive=True))

    assert "blodtryck_mätning" in result["context_block"]
    assert "blodtryck_teori" in result["context_block"]
