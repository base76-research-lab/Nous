"""
Field — SQLite + NetworkX persistent knowledge graph
=====================================================
Field-lagret i FNC: det substrat som binder Noder.
Grafen lever mellan sessioner. Varje ny kant är permanent topologisk tillväxt.
Kanternas styrka ökar Hebbiskt när stigar aktiveras.

Backend: SQLite WAL (persistence, concurrent readers) + NetworkX (in-memory traversal).
Migrerad från KuzuDB 2026-04-05.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path
import json
import math
import os
import re
import sqlite3
import threading

import networkx as nx

_DEFAULT_DB = Path.home() / ".local" / "share" / "nouse" / "field.sqlite"
_STRONG_FACT_MIN_SCORE = float(os.getenv("NOUSE_STRONG_FACT_MIN_SCORE", "0.65"))


def _queue_indications(src_node: str, rows: list[dict]) -> None:
    flagged = [r for r in rows if r.get("assumption_flag")]
    if not flagged:
        return
    try:
        from nouse.daemon.node_deepdive import get_review_queue
        import asyncio
        q = get_review_queue()
        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        for r in flagged:
            tgt = str(r.get("target") or "")
            typ = str(r.get("type") or "")
            if not tgt or not typ:
                continue
            if loop:
                loop.create_task(q.indicate(src_node, typ, tgt))
            else:
                try:
                    asyncio.run(q.indicate(src_node, typ, tgt))
                except RuntimeError:
                    pass
    except Exception:
        pass


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or ("1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = (os.getenv(name) or str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = (os.getenv(name) or str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


_GRAPH_EMBED_ENABLED = _env_bool("NOUSE_GRAPH_EMBED_ENABLED", True)
_GRAPH_EMBED_MODEL = (
    os.getenv("NOUSE_GRAPH_EMBED_MODEL")
    or os.getenv("NOUSE_EMBED_MODEL")
    or "nomic-embed-text-v2-moe:latest"
).strip()
_GRAPH_EMBED_BATCH = _env_int("NOUSE_GRAPH_EMBED_BATCH", 24, 1)
_BISOC_SEMANTIC_WEIGHT = _env_float("NOUSE_BISOC_SEMANTIC_WEIGHT", 0.35, 0.0, 0.8)
_BISOC_SEMANTIC_SIM_MAX = _env_float("NOUSE_BISOC_SEMANTIC_SIM_MAX", 0.92, 0.0, 1.0)


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


class FieldSurface:
    """Persistent kunskapsgraf — SQLite WAL + NetworkX."""

    def __init__(self, db_path: Path | str | None = None, read_only: bool = False):
        path = Path(db_path) if db_path else _DEFAULT_DB
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = path
        self._read_only = read_only
        self._lock = threading.Lock()

        if read_only:
            uri = f"file:{path}?mode=ro"
            self._sql = sqlite3.connect(uri, uri=True, check_same_thread=False)
        else:
            self._sql = sqlite3.connect(str(path), check_same_thread=False)
        self._sql.row_factory = _dict_factory
        self._sql.execute("PRAGMA journal_mode=WAL")
        self._sql.execute("PRAGMA foreign_keys=ON")
        self._sql.execute("PRAGMA busy_timeout=5000")

        self._relation_meta_available = True
        self._concept_embedding_available = True
        self._embedding_enabled = _GRAPH_EMBED_ENABLED
        self._embed_model = _GRAPH_EMBED_MODEL
        self._embedder = None
        self._embedding_cache: dict[str, list[float]] = {}

        if not read_only:
            self._init_schema()

        self._G: nx.MultiDiGraph = nx.MultiDiGraph()
        self._load_graph_into_networkx()

    def _init_schema(self) -> None:
        cur = self._sql.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS concept (
                name        TEXT PRIMARY KEY,
                domain      TEXT,
                granularity INTEGER DEFAULT 1,
                source      TEXT,
                created     TEXT
            );
            CREATE TABLE IF NOT EXISTS relation (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                src             TEXT NOT NULL,
                tgt             TEXT NOT NULL,
                type            TEXT,
                why             TEXT,
                strength        REAL DEFAULT 1.0,
                created         TEXT,
                evidence_score  REAL,
                assumption_flag INTEGER DEFAULT 0,
                FOREIGN KEY (src) REFERENCES concept(name),
                FOREIGN KEY (tgt) REFERENCES concept(name)
            );
            CREATE INDEX IF NOT EXISTS idx_relation_src ON relation(src);
            CREATE INDEX IF NOT EXISTS idx_relation_tgt ON relation(tgt);
            CREATE INDEX IF NOT EXISTS idx_relation_strength ON relation(strength);
            CREATE TABLE IF NOT EXISTS concept_knowledge (
                name            TEXT PRIMARY KEY,
                summary         TEXT,
                claims_json     TEXT,
                evidence_json   TEXT,
                related_json    TEXT,
                uncertainty     REAL,
                revision_count  INTEGER DEFAULT 0,
                updated         TEXT
            );
            CREATE TABLE IF NOT EXISTS concept_embedding (
                name        TEXT PRIMARY KEY,
                vector_json TEXT,
                model       TEXT,
                dims        INTEGER,
                updated     TEXT
            );
        """)
        self._sql.commit()

    def _load_graph_into_networkx(self) -> None:
        G = self._G
        G.clear()
        cur = self._sql.cursor()
        for row in cur.execute("SELECT name, domain, granularity, source, created FROM concept"):
            if row["name"] is None:
                continue
            G.add_node(row["name"], domain=row["domain"],
                       granularity=row["granularity"],
                       source=row["source"], created=row["created"])
        for row in cur.execute(
            "SELECT id, src, tgt, type, why, strength, created, "
            "evidence_score, assumption_flag FROM relation"
        ):
            if not row["src"] or not row["tgt"]:
                continue
            G.add_edge(row["src"], row["tgt"], key=row["id"], id=row["id"],
                       type=row["type"], why=row["why"],
                       strength=row["strength"] or 1.0,
                       created=row["created"],
                       evidence_score=row["evidence_score"],
                       assumption_flag=bool(row["assumption_flag"]))

    def _nx_add_concept(self, name, domain, granularity, source, created):
        self._G.add_node(name, domain=domain, granularity=granularity,
                         source=source, created=created)

    def _nx_add_relation(self, row_id, src, tgt, rel_type, why, strength,
                         created, evidence_score, assumption_flag):
        self._G.add_edge(src, tgt, key=row_id, id=row_id,
                         type=rel_type, why=why, strength=strength,
                         created=created, evidence_score=evidence_score,
                         assumption_flag=assumption_flag)

    # ── Write operations ─────────────────────────────────────────────────────

    def add_concept(self, name, domain, granularity=1, source="auto",
                    ensure_knowledge=True):
        ts = datetime.utcnow().isoformat()
        with self._lock:
            cur = self._sql.execute(
                "INSERT OR IGNORE INTO concept (name, domain, granularity, source, created) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, domain, granularity, source, ts))
            self._sql.commit()
            inserted = cur.rowcount > 0
        if inserted or name not in self._G:
            self._nx_add_concept(name, domain, granularity, source, ts)
        if ensure_knowledge:
            self.ensure_minimal_concept_knowledge(name, domain=domain, source=source)

    def add_relation(self, src, rel_type, tgt, why="", strength=1.0,
                     source_tag="auto", evidence_score=None, assumption_flag=None,
                     domain_src="external", domain_tgt="external"):
        ts = datetime.utcnow().isoformat()
        for name, domain in ((src, domain_src), (tgt, domain_tgt)):
            self.add_concept(name, domain=domain, granularity=1,
                             source=source_tag, ensure_knowledge=False)
        why_clean = (why or "").strip()
        ev = float(evidence_score) if evidence_score is not None else (
            min(1.0, max(0.0, float(strength))) if why_clean else 0.35)
        af = bool(assumption_flag) if assumption_flag is not None else (not bool(why_clean))

        with self._lock:
            cur = self._sql.execute(
                "INSERT INTO relation (src, tgt, type, why, strength, created, "
                "evidence_score, assumption_flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (src, tgt, rel_type, why, strength, ts, ev, int(af)))
            self._sql.commit()
            row_id = cur.lastrowid
        self._nx_add_relation(row_id, src, tgt, rel_type, why, strength, ts, ev, af)
        self._enrich_nodes_from_relation(src, rel_type, tgt, why, source_tag)

    def strengthen(self, src, tgt, delta=0.05):
        with self._lock:
            self._sql.execute(
                "UPDATE relation SET strength = strength + ? WHERE src = ? AND tgt = ?",
                (delta, src, tgt))
            self._sql.commit()
        if self._G.has_edge(src, tgt):
            for key in self._G[src][tgt]:
                self._G[src][tgt][key]["strength"] = (
                    self._G[src][tgt][key].get("strength", 1.0) + delta)

    # ── Knowledge CRUD ───────────────────────────────────────────────────────

    def _parse_json_list(self, raw):
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(x) for x in data if str(x).strip()]
        except Exception:
            pass
        return []

    def _has_context(self, knowledge):
        if not knowledge:
            return False
        summary = str(knowledge.get("summary") or "").strip()
        related = [str(x).strip() for x in (knowledge.get("related_terms") or []) if str(x).strip()]
        return bool(summary or related)

    def _has_facts(self, knowledge):
        if not knowledge:
            return False
        claims = [str(x).strip() for x in (knowledge.get("claims") or []) if str(x).strip()]
        evidence = [str(x).strip() for x in (knowledge.get("evidence_refs") or []) if str(x).strip()]
        return bool(claims and evidence)

    def _all_concepts_meta(self):
        rows = self._sql.execute(
            "SELECT name, domain, source, created FROM concept").fetchall()
        return [{"name": str(r["name"] or ""), "domain": str(r["domain"] or ""),
                 "source": str(r["source"] or ""), "created": str(r["created"] or "")}
                for r in rows]

    def _all_knowledge_by_name(self):
        rows = self._sql.execute(
            "SELECT name, summary, claims_json, evidence_json, related_json, "
            "uncertainty, revision_count, updated FROM concept_knowledge").fetchall()
        out = {}
        for row in rows:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            out[name] = {
                "name": name, "summary": row.get("summary") or "",
                "claims": self._parse_json_list(row.get("claims_json")),
                "evidence_refs": self._parse_json_list(row.get("evidence_json")),
                "related_terms": self._parse_json_list(row.get("related_json")),
                "uncertainty": float(row["uncertainty"]) if row.get("uncertainty") is not None else None,
                "revision_count": int(row.get("revision_count") or 0),
                "updated": row.get("updated") or "",
            }
        return out

    def _classify_evidence_ref(self, evidence_ref):
        ref = (evidence_ref or "").strip().lower()
        if not ref:
            return "unknown"
        if ref.startswith(("doi:", "arxiv:", "pmid:", "paper:", "source_paper:")):
            return "peer_reviewed"
        if ref.startswith(("url:", "web:", "source_url:", "source_doc:", "http://", "https://")):
            return "primary_source"
        if ref.startswith(("relation_out:", "relation_in:", "relation_edge:", "relation_source:")):
            return "graph_relation"
        if ref.startswith("why:"):
            return "rationale"
        if ref.startswith(("concept_source:", "source:")):
            return "provenance"
        if "assumption" in ref:
            return "assumption"
        return "unknown"

    def _evidence_ref_score(self, evidence_ref):
        ref = (evidence_ref or "").strip().lower()
        m = re.search(r"ev=([0-9]*\.?[0-9]+)", ref)
        if m:
            try:
                return max(0.0, min(1.0, float(m.group(1))))
            except Exception:
                pass
        kind = self._classify_evidence_ref(ref)
        return {"peer_reviewed": 0.95, "primary_source": 0.85, "graph_relation": 0.78,
                "rationale": 0.62, "provenance": 0.55, "assumption": 0.30}.get(kind, 0.45)

    def _fact_quality(self, knowledge, *, min_score):
        claims = [str(x).strip() for x in ((knowledge or {}).get("claims") or []) if str(x).strip()]
        evidence = [str(x).strip() for x in ((knowledge or {}).get("evidence_refs") or []) if str(x).strip()]
        scored = [{"ref": e, "kind": self._classify_evidence_ref(e),
                   "score": self._evidence_ref_score(e)} for e in evidence]
        strong = [x for x in scored if x["score"] >= min_score and x["kind"] != "assumption"]
        classified = [x for x in scored if x["kind"] != "unknown"]
        return {
            "claims": len(claims), "evidence_refs": len(evidence),
            "strong_evidence_refs": len(strong), "classified_evidence_refs": len(classified),
            "min_score": float(min_score),
            "per_claim_supported": bool(claims) and len(strong) >= len(claims),
            "fully_classified": bool(evidence) and len(classified) == len(evidence),
        }

    def upsert_concept_knowledge(self, name, *, summary=None, claim=None, claims=None,
                                  evidence_ref=None, evidence_refs=None,
                                  related_terms=None, uncertainty=None):
        ts = datetime.utcnow().isoformat()
        existing = self.concept_knowledge(name)
        claim_set = set(existing.get("claims", []))
        evidence_set = set(existing.get("evidence_refs", []))
        related_set = set(existing.get("related_terms", []))

        if claim and claim.strip():
            claim_set.add(claim.strip())
        for item in (claims or []):
            val = str(item).strip()
            if val:
                claim_set.add(val)
        if evidence_ref and evidence_ref.strip():
            evidence_set.add(evidence_ref.strip())
        for item in (evidence_refs or []):
            val = str(item).strip()
            if val:
                evidence_set.add(val)
        for term in (related_terms or []):
            t = str(term).strip()
            if t:
                related_set.add(t)

        old_summary = str(existing.get("summary") or "").strip()
        new_summary = (summary or "").strip()
        final_summary = new_summary if new_summary else old_summary

        old_unc = existing.get("uncertainty")
        if uncertainty is None:
            final_unc = old_unc
        elif old_unc is None:
            final_unc = max(0.0, min(1.0, float(uncertainty)))
        else:
            final_unc = (float(old_unc) + max(0.0, min(1.0, float(uncertainty)))) / 2.0

        revision = int(existing.get("revision_count") or 0) + 1
        with self._lock:
            self._sql.execute(
                "INSERT INTO concept_knowledge (name, summary, claims_json, evidence_json, "
                "related_json, uncertainty, revision_count, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET "
                "summary=excluded.summary, claims_json=excluded.claims_json, "
                "evidence_json=excluded.evidence_json, related_json=excluded.related_json, "
                "uncertainty=excluded.uncertainty, revision_count=excluded.revision_count, "
                "updated=excluded.updated",
                (name, final_summary,
                 json.dumps(sorted(claim_set), ensure_ascii=False),
                 json.dumps(sorted(evidence_set), ensure_ascii=False),
                 json.dumps(sorted(related_set), ensure_ascii=False),
                 final_unc, revision, ts))
            self._sql.commit()

    def concept_knowledge(self, name):
        empty = {"name": name, "summary": "", "claims": [], "evidence_refs": [],
                 "related_terms": [], "uncertainty": None, "revision_count": 0, "updated": ""}
        row = self._sql.execute(
            "SELECT name, summary, claims_json, evidence_json, related_json, "
            "uncertainty, revision_count, updated "
            "FROM concept_knowledge WHERE name = ?", (name,)).fetchone()
        if not row:
            return empty
        return {
            "name": row.get("name") or name,
            "summary": row.get("summary") or "",
            "claims": self._parse_json_list(row.get("claims_json")),
            "evidence_refs": self._parse_json_list(row.get("evidence_json")),
            "related_terms": self._parse_json_list(row.get("related_json")),
            "uncertainty": float(row["uncertainty"]) if row.get("uncertainty") is not None else None,
            "revision_count": int(row.get("revision_count") or 0),
            "updated": row.get("updated") or "",
        }

    def ensure_minimal_concept_knowledge(self, name, *, domain, source):
        existing = self.concept_knowledge(name)
        need_context = not self._has_context(existing)
        need_facts = not self._has_facts(existing)
        if not (need_context or need_facts):
            return
        summary = None
        if need_context:
            summary = (f"{name} är ett koncept i domänen '{domain or 'okänd'}'. "
                       f"Skapat från källa '{source or 'okänd'}'.")
        fallback_claims, fallback_evidence = [], []
        if need_facts:
            fallback_claims.append(f"{name} tillhör domänen '{domain or 'okänd'}'.")
            fallback_evidence.append(f"concept_source:{source or 'okänd'}")
        related_terms = [x for x in [domain, source] if str(x or "").strip()]
        uncertainty = 0.65 if need_facts else None
        self.upsert_concept_knowledge(name, summary=summary, claims=fallback_claims,
                                       evidence_refs=fallback_evidence,
                                       related_terms=related_terms, uncertainty=uncertainty)

    def _in_relations(self, name):
        rows = self._sql.execute(
            "SELECT c.name AS source, c.domain AS source_domain, "
            "r.type, r.why, r.strength, r.evidence_score, r.assumption_flag, r.created "
            "FROM relation r JOIN concept c ON c.name = r.src WHERE r.tgt = ?",
            (name,)).fetchall()
        out = []
        for row in rows:
            out.append({
                "source": row["source"], "source_domain": row["source_domain"],
                "type": row["type"], "why": row["why"], "strength": row["strength"],
                "evidence_score": row["evidence_score"],
                "assumption_flag": bool(row["assumption_flag"]) if row["assumption_flag"] is not None else None,
                "created": row["created"],
            })
        return out

    def backfill_concept_knowledge(self, name, *, strict=False,
                                    min_evidence_score=_STRONG_FACT_MIN_SCORE):
        row = self._sql.execute("SELECT name, domain, source FROM concept WHERE name = ?",
                                (name,)).fetchone()
        if not row:
            return {"name": name, "updated": False, "reason": "missing_concept"}
        domain = str(row.get("domain") or "okänd")
        source = str(row.get("source") or "okänd")
        existing = self.concept_knowledge(name)
        min_score = max(0.0, min(1.0, float(min_evidence_score)))
        need_context = not self._has_context(existing)
        need_facts = not self._has_facts(existing)
        fq_before = self._fact_quality(existing, min_score=min_score)
        has_strong_facts = bool(need_facts is False and fq_before.get("per_claim_supported")
                                and fq_before.get("fully_classified"))
        need_strong = bool(strict) and not has_strong_facts
        if not (need_context or need_facts or need_strong):
            return {"name": name, "updated": False, "reason": "already_complete"}
        outgoing = self.out_relations(name)
        incoming = self._in_relations(name)
        degree = len(outgoing) + len(incoming)
        summary = None
        if need_context:
            summary = (f"{name} i domänen '{domain}'. "
                       f"Noden har {degree} relationer i grafen och källa '{source}'.")
            if outgoing:
                o = outgoing[0]
                summary += f" Exempel ut: [{o.get('type', '')}] till '{o.get('target', '')}'."
            elif incoming:
                i = incoming[0]
                summary += f" Exempel in: '{i.get('source', '')}' via [{i.get('type', '')}]."
        synthesized_claims, synthesized_evidence = [], []
        related_terms = [domain]
        for rel in outgoing[:4]:
            tgt_n = str(rel.get("target") or "").strip()
            typ = str(rel.get("type") or "").strip()
            why_r = str(rel.get("why") or "").strip()
            ev = rel.get("evidence_score")
            if tgt_n and typ:
                synthesized_claims.append(f"{name} --[{typ}]--> {tgt_n}")
                if ev is not None:
                    synthesized_evidence.append(f"relation_out:{name}->{tgt_n}:{typ}:ev={float(ev):.2f}")
                else:
                    synthesized_evidence.append(f"relation_out:{name}->{tgt_n}:{typ}")
                related_terms.extend([tgt_n, typ])
                if why_r:
                    synthesized_evidence.append(f"why:{why_r[:120]}")
        for rel in incoming[:4]:
            src_n = str(rel.get("source") or "").strip()
            typ = str(rel.get("type") or "").strip()
            why_r = str(rel.get("why") or "").strip()
            ev = rel.get("evidence_score")
            if src_n and typ:
                synthesized_claims.append(f"{src_n} --[{typ}]--> {name}")
                if ev is not None:
                    synthesized_evidence.append(f"relation_in:{src_n}->{name}:{typ}:ev={float(ev):.2f}")
                else:
                    synthesized_evidence.append(f"relation_in:{src_n}->{name}:{typ}")
                related_terms.extend([src_n, typ])
                if why_r:
                    synthesized_evidence.append(f"why:{why_r[:120]}")
        if need_facts and not synthesized_claims:
            synthesized_claims.append(f"{name} tillhör domänen '{domain}'.")
        if need_facts and not synthesized_evidence:
            synthesized_evidence.append(f"concept_source:{source}")
        if need_strong and source:
            synthesized_evidence.append(f"source_doc:{source}")
        uncertainty = 0.45 if degree > 0 else 0.62
        self.upsert_concept_knowledge(
            name, summary=summary,
            claims=synthesized_claims if need_facts else None,
            evidence_refs=synthesized_evidence if (need_facts or need_strong) else None,
            related_terms=related_terms, uncertainty=uncertainty)
        after = self.concept_knowledge(name)
        fq_after = self._fact_quality(after, min_score=min_score)
        has_strong_after = bool(self._has_facts(after) and fq_after.get("per_claim_supported")
                                and fq_after.get("fully_classified"))
        return {
            "name": name,
            "updated": bool(need_context or need_facts
                            or (need_strong and has_strong_after and (not has_strong_facts))),
            "used_relations": degree, "need_context": need_context,
            "need_facts": need_facts, "need_strong_facts": need_strong,
            "strong_facts_before": has_strong_facts, "strong_facts_after": has_strong_after,
        }

    def knowledge_audit(self, limit=50, *, strict=False,
                        min_evidence_score=_STRONG_FACT_MIN_SCORE):
        concepts = self._all_concepts_meta()
        knowledge = self._all_knowledge_by_name()
        total = len(concepts)
        with_context = with_facts_basic = with_facts_strong = complete = 0
        missing = []
        min_score = max(0.0, min(1.0, float(min_evidence_score)))
        for c in concepts:
            name = c["name"]
            k = knowledge.get(name)
            has_context = self._has_context(k)
            has_facts = self._has_facts(k)
            fq = self._fact_quality(k, min_score=min_score)
            has_strong_facts = bool(has_facts and fq.get("per_claim_supported")
                                    and fq.get("fully_classified"))
            if has_context: with_context += 1
            if has_facts: with_facts_basic += 1
            if has_strong_facts: with_facts_strong += 1
            is_complete = has_context and (has_strong_facts if strict else has_facts)
            if is_complete:
                complete += 1
            else:
                reasons = []
                if not has_context: reasons.append("missing_context")
                if strict:
                    if not has_strong_facts: reasons.append("missing_strong_facts")
                elif not has_facts: reasons.append("missing_facts")
                missing.append({
                    "name": name, "domain": c.get("domain") or "okänd",
                    "source": c.get("source") or "okänd", "reasons": reasons,
                    "claims": len((k or {}).get("claims", [])),
                    "evidence_refs": len((k or {}).get("evidence_refs", [])),
                    "has_context": has_context, "has_facts": has_facts,
                    "has_strong_facts": has_strong_facts, "fact_quality": fq,
                })
        missing.sort(key=lambda x: (x["domain"], x["name"]))
        safe_limit = max(1, int(limit or 1))
        return {
            "total_concepts": total, "with_context": with_context,
            "with_facts": with_facts_basic, "with_strong_facts": with_facts_strong,
            "complete_nodes": complete, "missing_total": len(missing),
            "gate": {"strict": bool(strict), "min_evidence_score": min_score},
            "coverage": {
                "context": with_context / total if total else 1.0,
                "facts": with_facts_basic / total if total else 1.0,
                "strong_facts": with_facts_strong / total if total else 1.0,
                "complete": complete / total if total else 1.0,
            },
            "missing": missing[:safe_limit],
        }

    def backfill_missing_concept_knowledge(self, limit=None, *, strict=False,
                                            min_evidence_score=_STRONG_FACT_MIN_SCORE):
        audit = self.knowledge_audit(limit=100000, strict=strict,
                                     min_evidence_score=min_evidence_score)
        items = audit.get("missing", [])
        if limit is not None and limit > 0:
            items = items[:limit]
        updated = 0
        results = []
        for item in items:
            res = self.backfill_concept_knowledge(str(item.get("name") or ""),
                                                   strict=strict,
                                                   min_evidence_score=min_evidence_score)
            if res.get("updated"): updated += 1
            results.append(res)
        return {"requested": len(items), "updated": updated, "results": results,
                "before": audit,
                "after": self.knowledge_audit(limit=50, strict=strict,
                                              min_evidence_score=min_evidence_score)}

    def node_context_for_query(self, query, limit=5):
        tokens = [t.lower() for t in re.findall(r"[\wåäöÅÄÖ]{3,}", query or "")]
        if not tokens:
            return []
        concepts = self.concepts()
        scored = []
        for c in concepts:
            name = str(c.get("name") or "")
            lname = name.lower()
            score = sum(1 for t in tokens if t in lname)
            if score > 0:
                scored.append((score, name))
        scored.sort(key=lambda x: (-x[0], len(x[1])))
        out, seen = [], set()
        for _, name in scored:
            if name in seen: continue
            seen.add(name)
            k = self.concept_knowledge(name)
            out.append({
                "name": name, "summary": k.get("summary", ""),
                "claims": list(k.get("claims", []))[:3],
                "evidence_refs": list(k.get("evidence_refs", []))[:3],
                "related_terms": list(k.get("related_terms", []))[:5],
                "uncertainty": k.get("uncertainty"),
            })
            if len(out) >= limit: break
        return out

    def _enrich_nodes_from_relation(self, src, rel_type, tgt, why, source_tag):
        why_short = (why or "").strip()[:280]
        claim = f"{src} --[{rel_type}]--> {tgt}"
        edge_ref = f"relation_edge:{src}->{tgt}:{rel_type}"
        source_ref = f"relation_source:{source_tag or 'relation'}"
        evidence_refs = [edge_ref, source_ref]
        if why_short:
            evidence_refs.append(f"why:{why_short}")
        src_summary = (f"Koncept i grafen. Kopplat via relation '{rel_type}' till '{tgt}'."
                       + (f" Motivation: {why_short}" if why_short else ""))
        tgt_summary = (f"Koncept i grafen. Relaterat från '{src}' via '{rel_type}'."
                       + (f" Motivation: {why_short}" if why_short else ""))
        rel_terms = [src, tgt, rel_type]
        uncertainty = 0.45 if why_short else 0.7
        try:
            self.upsert_concept_knowledge(src, summary=src_summary, claim=claim,
                                           evidence_refs=evidence_refs,
                                           related_terms=rel_terms, uncertainty=uncertainty)
            self.upsert_concept_knowledge(tgt, summary=tgt_summary, claim=claim,
                                           evidence_refs=evidence_refs,
                                           related_terms=rel_terms, uncertainty=uncertainty)
        except Exception:
            return

    # ── Read operations ──────────────────────────────────────────────────────

    def concepts(self, domain=None, limit=None):
        if domain:
            sql = "SELECT name FROM concept WHERE domain = ?"
            params = (domain,)
        else:
            sql = "SELECT name, domain FROM concept"
            params = ()
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return self._sql.execute(sql, params).fetchall()

    def out_relations(self, name):
        if name not in self._G:
            return []
        rows = []
        for _, tgt, data in self._G.out_edges(name, data=True):
            rows.append({
                "target": tgt, "type": data.get("type"),
                "why": data.get("why"), "strength": data.get("strength"),
                "evidence_score": data.get("evidence_score"),
                "assumption_flag": data.get("assumption_flag"),
            })
        _queue_indications(name, rows)
        return rows

    def domains(self):
        rows = self._sql.execute("SELECT DISTINCT domain FROM concept").fetchall()
        return [row["domain"] for row in rows]

    def stats(self):
        nc = self._sql.execute("SELECT count(*) AS n FROM concept").fetchone()
        nr = self._sql.execute("SELECT count(*) AS n FROM relation").fetchone()
        return {"concepts": nc["n"] if nc else 0, "relations": nr["n"] if nr else 0}

    # ── Public API for external code (replaces raw _conn.execute) ────────────

    def top_relations_by_strength(self, limit=15, threshold=None):
        sql = ("SELECT r.src AS src_name, r.type, r.tgt AS tgt_name, r.strength "
               "FROM relation r ")
        params = []
        if threshold is not None:
            sql += "WHERE r.strength > ? "
            params.append(threshold)
        sql += f"ORDER BY r.strength DESC LIMIT {int(limit)}"
        return self._sql.execute(sql, params).fetchall()

    def query_all_relations(self, include_domain=False, limit=None):
        if include_domain:
            sql = ("SELECT c1.name AS src, r.type AS rel_type, c2.name AS tgt, "
                   "c1.domain AS src_domain FROM relation r "
                   "JOIN concept c1 ON c1.name = r.src "
                   "JOIN concept c2 ON c2.name = r.tgt")
        else:
            sql = "SELECT r.src, r.type AS rel_type, r.tgt FROM relation r"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return self._sql.execute(sql).fetchall()

    def query_all_relations_with_metadata(self, limit=5000, include_evidence=False):
        if include_evidence:
            sql = (f"SELECT r.src, r.type AS rel, r.strength, r.created, "
                   f"r.evidence_score, r.tgt FROM relation r LIMIT {int(limit)}")
        else:
            sql = (f"SELECT r.src, r.type AS rel, r.strength, r.created, r.tgt "
                   f"FROM relation r LIMIT {int(limit)}")
        return self._sql.execute(sql).fetchall()

    def neighbors(self, name, limit=15, bidirectional=False):
        if name not in self._G:
            return []
        if bidirectional:
            nbrs = set(self._G.successors(name)) | set(self._G.predecessors(name))
        else:
            nbrs = set(self._G.successors(name))
        return list(nbrs)[:limit]

    def concept_domain(self, name):
        if name in self._G:
            return self._G.nodes[name].get("domain")
        row = self._sql.execute("SELECT domain FROM concept WHERE name = ?", (name,)).fetchone()
        return row["domain"] if row else None

    def in_degree(self, name):
        if name not in self._G: return 0
        return self._G.in_degree(name)

    def get_all_node_degrees(self):
        return dict(self._G.degree())

    def relation_evidence_score(self, src, rel_type, tgt):
        row = self._sql.execute(
            "SELECT evidence_score FROM relation WHERE src = ? AND type = ? AND tgt = ? LIMIT 1",
            (src, rel_type, tgt)).fetchone()
        return float(row["evidence_score"]) if row and row["evidence_score"] is not None else None

    def promote_relation(self, src, rel_type, tgt, evidence_score):
        with self._lock:
            self._sql.execute(
                "UPDATE relation SET evidence_score = ?, assumption_flag = 0 "
                "WHERE src = ? AND type = ? AND tgt = ?",
                (evidence_score, src, rel_type, tgt))
            self._sql.commit()
        if self._G.has_edge(src, tgt):
            for key in self._G[src][tgt]:
                edata = self._G[src][tgt][key]
                if edata.get("type") == rel_type:
                    edata["evidence_score"] = evidence_score
                    edata["assumption_flag"] = False

    def discard_relation(self, src, rel_type, tgt):
        with self._lock:
            self._sql.execute(
                "UPDATE relation SET evidence_score = 0.0, assumption_flag = 1 "
                "WHERE src = ? AND type = ? AND tgt = ?",
                (src, rel_type, tgt))
            self._sql.commit()
        if self._G.has_edge(src, tgt):
            for key in self._G[src][tgt]:
                edata = self._G[src][tgt][key]
                if edata.get("type") == rel_type:
                    edata["evidence_score"] = 0.0
                    edata["assumption_flag"] = True

    def clear_assumption_flags(self, src, tgt):
        with self._lock:
            self._sql.execute(
                "UPDATE relation SET assumption_flag = 0 "
                "WHERE src = ? AND tgt = ? AND assumption_flag = 1", (src, tgt))
            self._sql.commit()
        if self._G.has_edge(src, tgt):
            for key in self._G[src][tgt]:
                self._G[src][tgt][key]["assumption_flag"] = False

    def set_concept_granularity(self, name, granularity):
        with self._lock:
            self._sql.execute("UPDATE concept SET granularity = ? WHERE name = ?",
                              (granularity, name))
            self._sql.commit()
        if name in self._G:
            self._G.nodes[name]["granularity"] = granularity

    def get_concepts_with_metadata(self, limit=5000):
        return self._sql.execute(
            "SELECT name AS id, domain AS dom, source, created FROM concept LIMIT ?",
            (limit,)).fetchall()

    def find_weak_concepts(self, threshold=1.2, max_rels=3, limit=9):
        return self._sql.execute(
            "SELECT r.src AS name, AVG(r.strength) AS avg_str, COUNT(r.id) AS n_rels "
            "FROM relation r GROUP BY r.src "
            "HAVING avg_str < ? AND n_rels <= ? "
            "ORDER BY avg_str ASC LIMIT ?",
            (threshold, max_rels, limit)).fetchall()

    def find_dangling_targets(self, limit=5000):
        return self._sql.execute(
            "SELECT DISTINCT r.tgt AS tgt, r.strength AS str "
            "FROM relation r LEFT JOIN concept c ON c.name = r.tgt "
            "WHERE c.name IS NULL ORDER BY r.strength DESC LIMIT ?",
            (limit,)).fetchall()

    def strong_relation_stats(self, threshold=0.65):
        row = self._sql.execute(
            "SELECT COUNT(*) AS cnt, AVG(strength) AS avg_s "
            "FROM relation WHERE evidence_score >= ?", (threshold,)).fetchone()
        return {
            "strong_count": int(row["cnt"]) if row else 0,
            "avg_strength": float(row["avg_s"]) if row and row["avg_s"] is not None else 0.0,
        }

    def delete_weak_relations(self, threshold, cutoff_iso):
        with self._lock:
            to_delete = self._sql.execute(
                "SELECT id, src, tgt FROM relation WHERE strength < ? AND created < ?",
                (threshold, cutoff_iso)).fetchall()
            if to_delete:
                ids = [r["id"] for r in to_delete]
                self._sql.execute(
                    f"DELETE FROM relation WHERE id IN ({','.join('?' * len(ids))})", ids)
                self._sql.commit()
                for r in to_delete:
                    if self._G.has_edge(r["src"], r["tgt"]):
                        try: self._G.remove_edge(r["src"], r["tgt"])
                        except Exception: pass
        return len(to_delete) if to_delete else 0

    def delete_orphan_concepts(self):
        orphans = [n for n in self._G.nodes() if self._G.degree(n) == 0]
        if not orphans: return 0
        with self._lock:
            self._sql.execute(
                f"DELETE FROM concept WHERE name IN ({','.join('?' * len(orphans))})", orphans)
            self._sql.commit()
        for n in orphans:
            self._G.remove_node(n)
        return len(orphans)

    # ── Multi-hop path finder (NetworkX) ─────────────────────────────────────

    def _domain_node_index(self) -> dict:
        """Cachat domain→noder-index. Ogiltigförklaras vid add_concept via _invalidate_domain_cache."""
        idx = getattr(self, "_domain_node_cache", None)
        if idx is None:
            idx: dict[str, list[str]] = {}
            for n, d in self._G.nodes(data=True):
                dom = d.get("domain") or ""
                if dom:
                    idx.setdefault(dom, []).append(n)
            self._domain_node_cache = idx
        return idx

    def _invalidate_domain_cache(self) -> None:
        self._domain_node_cache = None

    def find_path(self, domain_a, domain_b, max_hops=8):
        idx = self._domain_node_index()
        starts = idx.get(domain_a, [])
        goals = set(idx.get(domain_b, []))
        if not starts or not goals:
            return None
        queue = deque()
        visited = set()
        for s in starts[:20]:  # max 20 startnoder per domän
            queue.append((s, []))
            visited.add(s)
        while queue:
            node, path = queue.popleft()
            if len(path) >= max_hops:
                continue
            for _, tgt, data in self._G.out_edges(node, data=True):
                rel_type = data.get("type", "")
                new_path = path + [(node, rel_type, tgt)]
                if tgt in goals:
                    if not self._read_only:
                        for s_, _, t_ in new_path:
                            self.strengthen(s_, t_, 0.05)
                    return new_path
                if tgt not in visited:
                    visited.add(tgt)
                    queue.append((tgt, new_path))
        return None

    def _resolve_nodes(self, name):
        domain_nodes = [n for n, d in self._G.nodes(data=True) if d.get("domain") == name]
        if domain_nodes:
            return domain_nodes[:30]
        return [n for n in self._G.nodes() if name in n][:10]

    def _out_relations_full(self, name):
        if name not in self._G: return []
        node_data = self._G.nodes[name]
        src_domain = node_data.get("domain", "okänd")
        out = []
        for _, tgt, data in self._G.out_edges(name, data=True):
            tgt_data = self._G.nodes.get(tgt, {})
            out.append({
                "src_domain": src_domain, "rel_type": data.get("type") or "",
                "why": data.get("why") or "",
                "strength": float(data.get("strength") or 0.0),
                "evidence_score": float(data["evidence_score"]) if data.get("evidence_score") is not None else None,
                "assumption_flag": bool(data["assumption_flag"]) if data.get("assumption_flag") is not None else None,
                "created": data.get("created") or "",
                "tgt": tgt, "tgt_domain": tgt_data.get("domain", "okänd"),
            })
        return out

    def trace_path(self, start, end, max_hops=10, max_paths=3):
        start_nodes = self._resolve_nodes(start)
        end_nodes = set(self._resolve_nodes(end))
        if not start_nodes or not end_nodes: return []
        found = []
        queue = deque([(n, []) for n in start_nodes])
        visit_count = {}
        while queue and len(found) < max_paths:
            node, path = queue.popleft()
            if len(path) >= max_hops: continue
            visited_in_path = {s["src"] for s in path} | ({path[-1]["tgt"]} if path else set())
            for rel in self._out_relations_full(node):
                tgt = rel["tgt"]
                if tgt in visited_in_path: continue
                step = {
                    "src": node, "src_domain": rel.get("src_domain") or "okänd",
                    "rel_type": rel.get("rel_type") or "", "why": rel.get("why") or "",
                    "strength": float(rel.get("strength") or 0.0),
                    "evidence_score": rel.get("evidence_score"),
                    "assumption_flag": rel.get("assumption_flag"),
                    "created": rel.get("created") or "",
                    "tgt": tgt, "tgt_domain": rel.get("tgt_domain") or "okänd",
                }
                new_path = path + [step]
                if tgt in end_nodes:
                    found.append(new_path)
                    if len(found) >= max_paths: break
                else:
                    cnt = visit_count.get(tgt, 0)
                    if cnt < max_paths:
                        visit_count[tgt] = cnt + 1
                        queue.append((tgt, new_path))
        found.sort(key=lambda p: len({s["src_domain"] for s in p} | {p[-1]["tgt_domain"]}),
                   reverse=True)
        return found

    def path_novelty(self, path):
        if not path: return 0.0
        domains, analogies = set(), 0
        for src, rel, tgt in path:
            for name in (src, tgt):
                if name in self._G:
                    d = self._G.nodes[name].get("domain")
                    if d: domains.add(d)
            if rel == "är_analogt_med": analogies += 1
        return float(len(domains)) + analogies * 2.0

    # ── Embeddings ───────────────────────────────────────────────────────────

    def _vector_mean(self, vectors):
        if not vectors: return None
        dims = len(vectors[0])
        if dims <= 0 or any(len(v) != dims for v in vectors): return None
        sums = [0.0] * dims
        for vec in vectors:
            for idx, value in enumerate(vec):
                sums[idx] += float(value)
        n = float(len(vectors))
        return [v / n for v in sums]

    def _cosine_similarity(self, a, b):
        if not a or not b or len(a) != len(b): return None
        dot = norm_a = norm_b = 0.0
        for av, bv in zip(a, b, strict=True):
            af, bf = float(av), float(bv)
            dot += af * bf; norm_a += af * af; norm_b += bf * bf
        if norm_a <= 0.0 or norm_b <= 0.0: return None
        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))

    def _load_concept_embedding(self, name):
        if name in self._embedding_cache:
            return self._embedding_cache.get(name)
        if not self._concept_embedding_available: return None
        row = self._sql.execute(
            "SELECT vector_json FROM concept_embedding WHERE name = ? LIMIT 1",
            (name,)).fetchone()
        if not row: return None
        raw = str(row["vector_json"] or "").strip()
        if not raw: return None
        try:
            parsed = json.loads(raw)
        except Exception:
            return None
        if not isinstance(parsed, list) or not parsed: return None
        vec = [float(x) for x in parsed]
        self._embedding_cache[name] = vec
        return vec

    def _upsert_concept_embedding(self, name, vector):
        if self._read_only or not self._concept_embedding_available or not vector: return
        try:
            with self._lock:
                self._sql.execute(
                    "INSERT INTO concept_embedding (name, vector_json, model, dims, updated) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                    "vector_json=excluded.vector_json, model=excluded.model, "
                    "dims=excluded.dims, updated=excluded.updated",
                    (name, json.dumps(vector, ensure_ascii=False),
                     self._embed_model, int(len(vector)),
                     datetime.utcnow().isoformat()))
                self._sql.commit()
            self._embedding_cache[name] = vector
        except Exception:
            self._concept_embedding_available = False

    def _get_embedder(self):
        if not self._embedding_enabled: return None
        if self._embedder is not None: return self._embedder
        try:
            from nouse.embeddings.ollama_embed import OllamaEmbedder
            self._embedder = OllamaEmbedder(model=self._embed_model)
            return self._embedder
        except Exception:
            self._embedding_enabled = False
            return None

    def _embedding_text_for_concept(self, name, domain):
        knowledge = self.concept_knowledge(name)
        summary = str(knowledge.get("summary") or "").strip()
        claims = [str(x).strip() for x in (knowledge.get("claims") or []) if str(x).strip()]
        related = [str(x).strip() for x in (knowledge.get("related_terms") or []) if str(x).strip()]
        parts = [f"name: {name}", f"domain: {domain or 'okänd'}"]
        if summary: parts.append(f"summary: {summary[:600]}")
        if claims: parts.append(f"claims: {' | '.join(claims[:4])}")
        if related: parts.append(f"related: {', '.join(related[:8])}")
        return "\n".join(parts)

    def _bulk_load_embeddings(self, names: list[str]) -> dict[str, list[float]]:
        """Hämtar embeddings för en lista namn i en enda SQL-query."""
        out: dict[str, list[float]] = {}
        if not names or not self._concept_embedding_available:
            return out
        uncached = [n for n in names if n not in self._embedding_cache]
        if uncached:
            placeholders = ",".join("?" * len(uncached))
            rows = self._sql.execute(
                f"SELECT name, vector_json FROM concept_embedding WHERE name IN ({placeholders})",
                uncached,
            ).fetchall()
            for row in rows:
                raw = str(row["vector_json"] or "").strip()
                if not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list) and parsed:
                        vec = [float(x) for x in parsed]
                        self._embedding_cache[row["name"]] = vec
                except Exception:
                    pass
        for name in names:
            vec = self._embedding_cache.get(name)
            if vec:
                out[name] = vec
        return out

    def _ensure_concept_embeddings(self, concepts):
        out = {}
        if not concepts: return out
        names = [str(row.get("name") or "").strip() for row in concepts]
        names = [n for n in names if n]
        # Bulk-hämta från SQLite + in-memory cache i en query
        cached = self._bulk_load_embeddings(names)
        out.update(cached)
        missing = [
            {"name": str(row.get("name") or "").strip(),
             "domain": str(row.get("domain") or "okänd")}
            for row in concepts
            if str(row.get("name") or "").strip() not in out
        ]
        if not missing: return out
        embedder = self._get_embedder()
        if embedder is None: return out
        try:
            for batch_start in range(0, len(missing), _GRAPH_EMBED_BATCH):
                batch = missing[batch_start:batch_start + _GRAPH_EMBED_BATCH]
                texts = [self._embedding_text_for_concept(r["name"], r["domain"]) for r in batch]
                vectors = embedder.embed_texts(texts)
                if len(vectors) != len(batch): continue
                for row, vector in zip(batch, vectors, strict=True):
                    if not isinstance(vector, list) or not vector: continue
                    clean_vec = [float(x) for x in vector]
                    out[row["name"]] = clean_vec
                    if not self._read_only:
                        self._upsert_concept_embedding(row["name"], clean_vec)
                    else:
                        self._embedding_cache[row["name"]] = clean_vec
        except Exception:
            return out
        return out

    # ── TDA ──────────────────────────────────────────────────────────────────

    def domain_tda_profile(self, domain, max_epsilon=2.0, include_centroid=False,
                           max_tda_concepts=300):
        try:
            from nouse.tda.bridge import compute_distance_matrix, compute_betti
        except ImportError:
            return {"domain": domain, "h0": 1, "h1": 0, "n_concepts": 0}
        concepts = self.concepts(domain=domain)
        n = len(concepts)
        if n < 2:
            out = {"domain": domain, "h0": max(n, 1), "h1": 0, "n_concepts": n,
                   "embedding_mode": "none", "embedding_coverage": 0.0}
            if include_centroid: out["centroid"] = None
            return out
        # Subsampla stora domäner för att hålla TDA-beräkningstiden rimlig.
        # Topologin förändras minimalt vid representativt urval.
        if max_tda_concepts and n > max_tda_concepts:
            import random
            concepts = random.sample(concepts, max_tda_concepts)
        concept_rows = [{"name": str(c.get("name") or "").strip(), "domain": domain}
                        for c in concepts if str(c.get("name") or "").strip()]
        semantic_map = self._ensure_concept_embeddings(concept_rows)
        semantic_vectors = [semantic_map[r["name"]] for r in concept_rows if r["name"] in semantic_map]
        coverage = (len(semantic_vectors) / float(n)) if n > 0 else 0.0
        if len(semantic_vectors) >= 2:
            dm = compute_distance_matrix(semantic_vectors)
            h0, h1 = compute_betti(dm, max_epsilon=max_epsilon, steps=30)
            out = {"domain": domain, "h0": h0, "h1": h1, "n_concepts": n,
                   "embedding_mode": "semantic",
                   "embedding_coverage": round(float(coverage), 4)}
            if include_centroid: out["centroid"] = self._vector_mean(semantic_vectors)
            return out
        topo_vectors = []
        for c in concepts:
            cname = c["name"]
            out_d = float(self._G.out_degree(cname)) if cname in self._G else 0.0
            in_d = float(self._G.in_degree(cname)) if cname in self._G else 0.0
            s_sum = sum(d.get("strength", 1.0) for _, _, d in self._G.out_edges(cname, data=True)) if cname in self._G else 0.0
            topo_vectors.append([out_d, in_d, s_sum])
        dm = compute_distance_matrix(topo_vectors)
        h0, h1 = compute_betti(dm, max_epsilon=max_epsilon, steps=30)
        out = {"domain": domain, "h0": h0, "h1": h1, "n_concepts": n,
               "embedding_mode": "topology_fallback",
               "embedding_coverage": round(float(coverage), 4)}
        if include_centroid: out["centroid"] = None
        return out

    def bisociation_candidates(self, tau_threshold=0.55, max_epsilon=2.0,
                                semantic_similarity_max=_BISOC_SEMANTIC_SIM_MAX,
                                max_domains=50):
        try:
            from nouse.tda.bridge import topological_similarity
        except ImportError:
            return []
        all_domains = self.domains()
        if max_domains and len(all_domains) > max_domains:
            domain_counts = {}
            for n, d in self._G.nodes(data=True):
                dom = d.get("domain", "")
                domain_counts[dom] = domain_counts.get(dom, 0) + 1
            sorted_doms = sorted(domain_counts, key=domain_counts.get, reverse=True)
            top_set = set(sorted_doms[:max_domains])
            domains = [d for d in all_domains if d in top_set]
        else:
            domains = all_domains
        profiles = {d: self.domain_tda_profile(d, max_epsilon, include_centroid=True) for d in domains}
        domain_set = set(domains)
        connected_pairs = set()
        for src, tgt in self._G.edges():
            da = self._G.nodes[src].get("domain")
            db = self._G.nodes[tgt].get("domain")
            if da in domain_set and db in domain_set and da != db:
                connected_pairs.add((da, db))
                connected_pairs.add((db, da))
        results = []
        for i, da in enumerate(domains):
            for db in domains[i + 1:]:
                if (da, db) in connected_pairs: continue
                pa, pb = profiles[da], profiles[db]
                tau = topological_similarity(pa["h0"], pa["h1"], pb["h0"], pb["h1"])
                centroid_a, centroid_b = pa.get("centroid"), pb.get("centroid")
                cos_sim = self._cosine_similarity(centroid_a, centroid_b)
                semantic_similarity = None
                if cos_sim is not None:
                    semantic_similarity = max(0.0, min(1.0, (float(cos_sim) + 1.0) / 2.0))
                    if semantic_similarity > max(0.0, min(1.0, float(semantic_similarity_max))):
                        continue
                semantic_gap = 1.0 - semantic_similarity if semantic_similarity is not None else 1.0
                score = ((1.0 - _BISOC_SEMANTIC_WEIGHT) * float(tau)) + (_BISOC_SEMANTIC_WEIGHT * float(semantic_gap))
                if tau >= tau_threshold:
                    results.append({
                        "domain_a": da, "domain_b": db, "tau": tau,
                        "h0_a": pa["h0"], "h1_a": pa["h1"],
                        "h0_b": pb["h0"], "h1_b": pb["h1"],
                        "semantic_similarity": semantic_similarity,
                        "semantic_gap": semantic_gap, "score": score,
                        "embedding_coverage_a": float(pa.get("embedding_coverage", 0.0) or 0.0),
                        "embedding_coverage_b": float(pb.get("embedding_coverage", 0.0) or 0.0),
                        "embedding_mode_a": str(pa.get("embedding_mode") or "unknown"),
                        "embedding_mode_b": str(pb.get("embedding_mode") or "unknown"),
                    })
        results.sort(key=lambda x: (float(x.get("score", 0.0)), float(x.get("tau", 0.0))), reverse=True)
        return results
