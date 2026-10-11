"""Kontraktstest för Fas 1-reviewens hål 4-9 (REBUILD-PLAN.md).

Varje test gör ett taklöst/anonymt/felklassat skrivförsök mot en isolerad
tmp-databas och kräver att taket, spårbarheten eller signaturen håller.
"""
from __future__ import annotations

from pathlib import Path

from nouse.field.surface import (
    PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING,
    FieldSurface,
    _provenance_class,
)


def _field(tmp_path: Path) -> FieldSurface:
    return FieldSurface(db_path=tmp_path / "field.sqlite", read_only=False)


# ── Hål 9: felklassad proveniens ───────────────────────────────────────────────

def test_new_model_derived_source_tags_classify_as_model_hypothesis():
    for tag in ("homeostasis_bootstrap", "graph_enricher", "deepdive_axiom",
                "curiosity_loop:hypotes", "curiosity_loop:validerad"):
        assert _provenance_class(None, tag) == "model_hypothesis", tag


def test_new_model_derived_tags_capped_at_write(tmp_path):
    field = _field(tmp_path)
    for tag in ("homeostasis_bootstrap", "graph_enricher", "deepdive_axiom",
                "curiosity_loop:hypotes"):
        src, tgt = f"S-{tag}", f"T-{tag}"
        field.add_relation(src, "claims", tgt, why="model output",
                           evidence_score=1.0, source_tag=tag)
        row = field._sql.execute(
            "SELECT evidence_score, provenance_class FROM relation "
            "WHERE src = ? AND tgt = ?", (src, tgt),
        ).fetchone()
        assert row["evidence_score"] == PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING, tag
        assert row["provenance_class"] == "model_hypothesis", tag


def test_user_model_seed_writes_user_assertion(tmp_path):
    from nouse.daemon import user_model_seed
    person = tmp_path / "PERSON.md"
    person.write_text("## How to work with Björn\n\n- Ge kort feedback först.\n",
                      encoding="utf-8")
    memdir = tmp_path / "mem"
    memdir.mkdir()
    (memdir / "m1.md").write_text(
        "---\nname: m1\ndescription: Föredrar konkreta exempel.\nmetadata:\ntype: user\n---\nBody text här.\n",
        encoding="utf-8",
    )
    field = _field(tmp_path)
    result = user_model_seed.seed_user_model(field, person, memdir)
    assert result["added"] == 2
    rows = field._sql.execute(
        "SELECT DISTINCT provenance_class FROM relation WHERE src = 'Björn Wikström'"
    ).fetchall()
    assert rows and {r["provenance_class"] for r in rows} == {"user_assertion"}


# ── Hål 5: död väg field.upsert_relation i decomposition ───────────────────────

def test_promote_axioms_writes_real_edges_with_structural_provenance(tmp_path):
    from nouse.daemon.decomposition import AxiomCandidate, promote_axioms_to_graph
    field = _field(tmp_path)
    before = field.stats()["relations"]
    axioms = [AxiomCandidate(concept="feedback", domains=["d_a", "d_b"],
                             bridge_score=0.8, discovery_depth=2,
                             source_insight="test")]
    added = promote_axioms_to_graph(field, axioms)
    assert added == 1
    assert field.stats()["relations"] == before + 1
    row = field._sql.execute(
        "SELECT evidence_score, provenance_class, source_tag FROM relation LIMIT 1"
    ).fetchone()
    assert row["provenance_class"] == "structural_derivation"
    assert row["evidence_score"] <= PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING


# ── Hål 6: extract_relations med fel signatur (ghost_q, run_repl) ──────────────

async def _run_ghost_q_with_canned_extract(tmp_path, monkeypatch):
    import nouse.daemon.extractor as extractor
    import nouse.daemon.ghost_q as ghost_q
    monkeypatch.setattr(ghost_q, "HISTORY_FILE", tmp_path / "ghost_hist.json")
    calls: list[tuple] = []

    async def _fake_extract(text, metadata):
        calls.append((text, metadata))
        assert isinstance(metadata, dict), (
            f"extract_relations måste anropas med metadata-dict, fick {type(metadata)}"
        )
        return [{"src": "Alpha", "type": "relaterar_till", "tgt": "Beta",
                 "domain_src": "d1", "domain_tgt": "d1", "why": "canned"}]

    monkeypatch.setattr(extractor, "extract_relations", _fake_extract)

    class _Router:
        async def complete(self, query, system="", max_tokens=0):
            return "Alpha relaterar till Beta eftersom testdata säger så."

    field = _field(tmp_path)
    field.add_relation("SvagNod", "relaterar_till", "AnnanNod", why="seed")
    result = await ghost_q.run_ghost_q(field, _Router(), max_queries=2)
    return field, result, calls


async def test_ghost_q_uses_real_extract_signature_and_persists(tmp_path, monkeypatch):
    field, result, calls = await _run_ghost_q_with_canned_extract(tmp_path, monkeypatch)
    assert calls, "extract_relations anropades aldrig"
    assert result.relations_added >= 1, (
        "ghost_q extraherade men persisterade 0 relationer (död väg)"
    )
    assert "extract_error" not in "".join(result.errors)
    row = field._sql.execute(
        "SELECT source_tag FROM relation WHERE src = 'Alpha' AND tgt = 'Beta'"
    ).fetchone()
    assert row is not None and row["source_tag"] == "ghost_q"


async def test_run_repl_learn_uses_real_extract_signature_and_persists(tmp_path, monkeypatch):
    import nouse.daemon.extractor as extractor
    from nouse.cli import run_repl
    calls: list[tuple] = []

    async def _fake_extract(text, metadata):
        calls.append((text, metadata))
        assert isinstance(metadata, dict)
        return [{"src": "ReplA", "type": "relaterar_till", "tgt": "ReplB",
                 "domain_src": "d", "domain_tgt": "d", "why": "canned"}]

    monkeypatch.setattr(extractor, "extract_relations", _fake_extract)
    field = _field(tmp_path)
    await run_repl._async_learn(field, "användartext", "assistenttext")
    assert calls, "extract_relations anropades aldrig"
    row = field._sql.execute(
        "SELECT source_tag FROM relation WHERE src = 'ReplA' AND tgt = 'ReplB'"
    ).fetchone()
    assert row is not None and row["source_tag"] == "nouse_run"


# ── Hål 7: island_bridge direkt-UPDATE utanför surface ──────────────────────────

def test_island_bridge_fusion_via_surface_syncs_sql_and_networkx(tmp_path):
    from nouse.tools import island_bridge
    field = _field(tmp_path)
    field.add_concept("C1", domain="gammal_domän")
    field.add_concept("C2", domain="gammal_domän")
    assert hasattr(island_bridge, "apply_domain_fusion_via_surface")
    changed = island_bridge.apply_domain_fusion_via_surface(
        field, {"gammal_domän": "ny_domän"})
    assert changed == 2
    rows = field._sql.execute(
        "SELECT DISTINCT domain FROM concept WHERE name IN ('C1', 'C2')"
    ).fetchall()
    assert [r["domain"] for r in rows] == ["ny_domän"]
    assert field._G.nodes["C1"]["domain"] == "ny_domän"
    assert field._G.nodes["C2"]["domain"] == "ny_domän"


# ── Hål 8: anonyma skrivare får explicita source_tags ──────────────────────────

def test_nightrun_cooccurrence_uses_named_source_tag(tmp_path):
    from nouse.daemon import nightrun
    field = _field(tmp_path)
    assert hasattr(nightrun, "write_cooccurrence_relations")
    n = nightrun.write_cooccurrence_relations(
        field, [{"nodes_used": ["NodA", "NodB"]}])
    assert n == 1
    row = field._sql.execute(
        "SELECT source_tag, why FROM relation WHERE type = 'co_occurs_with'"
    ).fetchone()
    assert row is not None and row["source_tag"] == "nightrun_cooccurrence"


def test_inject_add_uses_explicit_source_tag(tmp_path):
    from nouse.inject import NouseBrain
    brain = NouseBrain(db_path=tmp_path / "field.sqlite")
    brain.add("Källa", "relaterar_till", "Mål", why="direkt")
    row = brain._field._sql.execute(
        "SELECT source_tag FROM relation WHERE src = 'Källa'"
    ).fetchone()
    assert row is not None and str(row["source_tag"]).strip() not in {"", "auto"}


async def test_brain_learn_passes_source_tag(tmp_path, monkeypatch):
    import nouse.daemon.extractor as extractor
    import nouse.daemon.write_queue as write_queue
    from nouse.web import server

    async def _fake_extract(text, meta):
        return ([{"src": "LearnA", "type": "relaterar_till", "tgt": "LearnB",
                  "domain_src": "d", "domain_tgt": "d", "why": "canned",
                  "evidence_score": 0.5}], {})

    async def _inline(coro, *, timeout=120.0):
        return await coro

    monkeypatch.setattr(extractor, "extract_relations_with_diagnostics", _fake_extract)
    monkeypatch.setattr(write_queue, "enqueue_write", _inline)
    field = _field(tmp_path)
    monkeypatch.setattr(server, "_global_field", field)
    req = server._BrainLearnRequest(prompt="x" * 60, response="y" * 60,
                                    source="test_source_xyz")
    result = await server.brain_learn(req)
    assert result["ok"] is True
    row = field._sql.execute(
        "SELECT source_tag FROM relation WHERE src = 'LearnA'"
    ).fetchone()
    assert row is not None and row["source_tag"] == "test_source_xyz"


async def test_brain_add_requires_source(tmp_path, monkeypatch):
    import nouse.daemon.write_queue as write_queue
    from nouse.web import server

    async def _inline(coro, *, timeout=120.0):
        return await coro

    monkeypatch.setattr(write_queue, "enqueue_write", _inline)
    field = _field(tmp_path)
    monkeypatch.setattr(server, "_global_field", field)

    req_missing = server._BrainAddRequest(src="A", rel_type="r", tgt="B")
    result = await server.brain_add(req_missing)
    assert getattr(result, "status_code", 200) == 400
    assert field.stats()["relations"] == 0

    req_ok = server._BrainAddRequest(src="A2", rel_type="r", tgt="B2",
                                     source="explicit_test_source")
    result_ok = await server.brain_add(req_ok)
    assert result_ok == {"ok": True}
    row = field._sql.execute(
        "SELECT source_tag FROM relation WHERE src = 'A2'"
    ).fetchone()
    assert row is not None and row["source_tag"] == "explicit_test_source"


# ── Hål 4: Kuzu-backenden saknar tak (testet skippas utan kuzu-drivrutin) ───────

def test_kuzu_backend_clamps_evidence_to_ceiling(tmp_path):
    kuzu = __import__("pytest").importorskip("kuzu")
    del kuzu
    from nouse.field.surface_kuzu import FieldSurface as KuzuSurface
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        field = KuzuSurface(db_path=tmp_path / "field.kuzu")
    field.add_relation("A", "claims", "B", why="model output",
                       evidence_score=1.0, source_tag="ghost_q")
    rows = field.out_relations("A")
    assert rows and float(rows[0].get("evidence_score") or 0.0) <= float(
        PARAMETRIC_HYPOTHESIS_EVIDENCE_CEILING)
