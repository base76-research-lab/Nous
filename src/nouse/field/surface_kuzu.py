"""
Field — KuzuDB-backed persistent knowledge graph
=================================================
Field-lagret i FNC: det substrat som binder Noder.
Grafen lever mellan sessioner. Varje ny kant är permanent topologisk tillväxt.
Kanternas styrka ökar Hebbiskt när stigar aktiveras.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path
import json
import math
import os
import re

import kuzu

_DEFAULT_DB = Path.home() / ".local" / "share" / "nouse" / "field.kuzu"
_STRONG_FACT_MIN_SCORE = float(os.getenv("NOUSE_STRONG_FACT_MIN_SCORE", "0.65"))


def _queue_indications(src_node: str, rows: list[dict]) -> None:
    """
    Fire-and-forget: registrera indikationer på flaggade relationer i ReviewQueue.
    Körs synkront men är snabb (bara dict-lookup + counter-increment utan I/O
    om gränsen inte nåtts). Importerar ReviewQueue lazy för att undvika cirkulär import.
    """
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
                # Synkront anrop utanför event loop (t.ex. tests/CLI)
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
    or "nomic-embed-text:latest"
).strip()
_GRAPH_EMBED_BATCH = _env_int("NOUSE_GRAPH_EMBED_BATCH", 24, 1)
_BISOC_SEMANTIC_WEIGHT = _env_float("NOUSE_BISOC_SEMANTIC_WEIGHT", 0.35, 0.0, 0.8)
_BISOC_SEMANTIC_SIM_MAX = _env_float("NOUSE_BISOC_SEMANTIC_SIM_MAX", 0.92, 0.0, 1.0)


class FieldSurface:
    """Persistent kunskapsgraf över KuzuDB."""

    def __init__(self, db_path: Path | str | None = None, read_only: bool = False):
        path = Path(db_path) if db_path else _DEFAULT_DB
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db        = kuzu.Database(str(path), read_only=read_only)
        self._conn      = kuzu.Connection(self._db)
        self._read_only = read_only
        self._relation_meta_available = False
        self._concept_embedding_available = False
        self._embedding_enabled = _GRAPH_EMBED_ENABLED
        self._embed_model = _GRAPH_EMBED_MODEL
        self._embedder = None
        self._embedding_cache: dict[str, list[float]] = {}
        if not read_only:
            self._init_schema()
        self._relation_meta_available = self._probe_relation_meta_available()
        self._concept_embedding_available = self._probe_concept_embedding_available()

    # ── Schema ───────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        self._conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Concept(
                name        STRING,
                domain      STRING,
                granularity INT,
                source      STRING,
                created     STRING,
                PRIMARY KEY(name)
            )
        """)
        self._conn.execute("""
            CREATE REL TABLE IF NOT EXISTS Relation(
                FROM Concept TO Concept,
                type            STRING,
                why             STRING,
                strength        DOUBLE,
                created         STRING,
                evidence_score  DOUBLE,
                assumption_flag BOOL
            )
        """)
        self._conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS ConceptKnowledge(
                name            STRING,
                summary         STRING,
                claims_json     STRING,
                evidence_json   STRING,
                related_json    STRING,
                uncertainty     DOUBLE,
                revision_count  INT64,
                updated         STRING,
                PRIMARY KEY(name)
            )
        """)
        self._conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS ConceptEmbedding(
                name        STRING,
                vector_json STRING,
                model       STRING,
                dims        INT64,
                updated     STRING,
                PRIMARY KEY(name)
            )
        """)
        self._safe_migrate_relation_meta()

    def _safe_migrate_relation_meta(self) -> None:
        # Bakåtkompatibel migrering: försök lägga till nya edgefält, ignorera om de finns saknas/stöds ej.
        statements = [
            "ALTER TABLE Relation ADD COLUMN evidence_score DOUBLE",
            "ALTER TABLE Relation ADD COLUMN assumption_flag BOOL",
        ]
        for stmt in statements:
            try:
                self._conn.execute(stmt)
            except Exception:
                pass

    def _probe_relation_meta_available(self) -> bool:
        try:
            self._conn.execute(
                "MATCH (:Concept)-[r:Relation]->(:Concept) "
                "RETURN r.evidence_score AS e, r.assumption_flag AS a LIMIT 1"
            ).get_as_df()
            return True
        except Exception:
            return False

    def _probe_concept_embedding_available(self) -> bool:
        try:
            self._conn.execute(
                "MATCH (e:ConceptEmbedding) RETURN e.name AS n LIMIT 1"
            ).get_as_df()
            return True
        except Exception:
            return False

    # ── Skrivoperationer ─────────────────────────────────────────────────────

    def add_concept(self, name: str, domain: str,
                    granularity: int = 1, source: str = "auto",
                    ensure_knowledge: bool = True) -> None:
        self._conn.execute(
            "MERGE (c:Concept {name: $n}) "
            "ON CREATE SET c.domain=$d, c.granularity=$g, c.source=$s, c.created=$t",
            {"n": name, "d": domain, "g": granularity,
             "s": source, "t": datetime.utcnow().isoformat()},
        )
        if ensure_knowledge:
            self.ensure_minimal_concept_knowledge(name, domain=domain, source=source)

    def add_relation(self, src: str, rel_type: str, tgt: str,
                     why: str = "", strength: float = 1.0,
                     source_tag: str = "auto",
                     evidence_score: float | None = None,
                     assumption_flag: bool | None = None) -> None:
        ts = datetime.utcnow().isoformat()
        for name in (src, tgt):
            self.add_concept(
                name,
                domain="external",
                granularity=1,
                source=source_tag,
                ensure_knowledge=False,
            )

        why_clean = (why or "").strip()
        ev = float(evidence_score) if evidence_score is not None else (
            min(1.0, max(0.0, float(strength))) if why_clean else 0.35
        )
        af = bool(assumption_flag) if assumption_flag is not None else (not bool(why_clean))

        params = {
            "s": src,
            "t": tgt,
            "type": rel_type,
            "why": why,
            "str": strength,
            "ts": ts,
            "ev": ev,
            "af": af,
        }

        if self._relation_meta_available:
            try:
                self._conn.execute(
                    "MATCH (a:Concept {name: $s}), (b:Concept {name: $t}) "
                    "CREATE (a)-[:Relation {type:$type, why:$why, strength:$str, created:$ts, "
                    "evidence_score:$ev, assumption_flag:$af}]->(b)",
                    params,
                )
            except Exception:
                self._relation_meta_available = False

        if not self._relation_meta_available:
            legacy_params = {
                "s": src,
                "t": tgt,
                "type": rel_type,
                "why": why,
                "str": strength,
                "ts": ts,
            }
            self._conn.execute(
                "MATCH (a:Concept {name: $s}), (b:Concept {name: $t}) "
                "CREATE (a)-[:Relation {type:$type, why:$why, strength:$str, created:$ts}]->(b)",
                legacy_params,
            )

        self._enrich_nodes_from_relation(src, rel_type, tgt, why, source_tag)

    def _parse_json_list(self, raw: str | None) -> list[str]:
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(x) for x in data if str(x).strip()]
        except Exception:
            pass
        return []

    def _has_context(self, knowledge: dict | None) -> bool:
        if not knowledge:
            return False
        summary = str(knowledge.get("summary") or "").strip()
        related = [str(x).strip() for x in (knowledge.get("related_terms") or []) if str(x).strip()]
        return bool(summary or related)

    def _has_facts(self, knowledge: dict | None) -> bool:
        if not knowledge:
            return False
        claims = [str(x).strip() for x in (knowledge.get("claims") or []) if str(x).strip()]
        evidence = [str(x).strip() for x in (knowledge.get("evidence_refs") or []) if str(x).strip()]
        return bool(claims and evidence)

    def _all_concepts_meta(self) -> list[dict]:
        try:
            rows = self._conn.execute(
                "MATCH (c:Concept) "
                "RETURN c.name AS name, c.domain AS domain, c.source AS source, c.created AS created"
            ).get_as_df().to_dict("records")
        except Exception:
            return []
        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "name": str(row.get("name") or ""),
                    "domain": str(row.get("domain") or ""),
                    "source": str(row.get("source") or ""),
                    "created": str(row.get("created") or ""),
                }
            )
        return out

    def _all_knowledge_by_name(self) -> dict[str, dict]:
        try:
            rows = self._conn.execute(
                "MATCH (k:ConceptKnowledge) "
                "RETURN k.name AS name, k.summary AS summary, k.claims_json AS claims_json, "
                "k.evidence_json AS evidence_json, k.related_json AS related_json, "
                "k.uncertainty AS uncertainty, k.revision_count AS revision_count, k.updated AS updated"
            ).get_as_df().to_dict("records")
        except Exception:
            return {}
        out: dict[str, dict] = {}
        for row in rows:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            out[name] = {
                "name": name,
                "summary": row.get("summary") or "",
                "claims": self._parse_json_list(row.get("claims_json")),
                "evidence_refs": self._parse_json_list(row.get("evidence_json")),
                "related_terms": self._parse_json_list(row.get("related_json")),
                "uncertainty": (
                    float(row.get("uncertainty"))
                    if row.get("uncertainty") is not None
                    else None
                ),
                "revision_count": int(row.get("revision_count") or 0),
                "updated": row.get("updated") or "",
            }
        return out

    def _classify_evidence_ref(self, evidence_ref: str) -> str:
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

    def _evidence_ref_score(self, evidence_ref: str) -> float:
        ref = (evidence_ref or "").strip().lower()
        m = re.search(r"ev=([0-9]*\.?[0-9]+)", ref)
        if m:
            try:
                v = float(m.group(1))
                return max(0.0, min(1.0, v))
            except Exception:
                pass

        kind = self._classify_evidence_ref(ref)
        if kind == "peer_reviewed":
            return 0.95
        if kind == "primary_source":
            return 0.85
        if kind == "graph_relation":
            return 0.78
        if kind == "rationale":
            return 0.62
        if kind == "provenance":
            return 0.55
        if kind == "assumption":
            return 0.30
        return 0.45

    def _fact_quality(self, knowledge: dict | None, *, min_score: float) -> dict:
        claims = [str(x).strip() for x in ((knowledge or {}).get("claims") or []) if str(x).strip()]
        evidence = [
            str(x).strip()
            for x in ((knowledge or {}).get("evidence_refs") or [])
            if str(x).strip()
        ]
        scored = [{"ref": e, "kind": self._classify_evidence_ref(e), "score": self._evidence_ref_score(e)} for e in evidence]
        strong = [x for x in scored if x["score"] >= min_score and x["kind"] != "assumption"]
        classified = [x for x in scored if x["kind"] != "unknown"]

        return {
            "claims": len(claims),
            "evidence_refs": len(evidence),
            "strong_evidence_refs": len(strong),
            "classified_evidence_refs": len(classified),
            "min_score": float(min_score),
            "per_claim_supported": bool(claims) and len(strong) >= len(claims),
            "fully_classified": bool(evidence) and len(classified) == len(evidence),
        }

    def upsert_concept_knowledge(
        self,
        name: str,
        *,
        summary: str | None = None,
        claim: str | None = None,
        claims: list[str] | None = None,
        evidence_ref: str | None = None,
        evidence_refs: list[str] | None = None,
        related_terms: list[str] | None = None,
        uncertainty: float | None = None,
    ) -> None:
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
        self._conn.execute(
            "MERGE (k:ConceptKnowledge {name:$n}) "
            "SET k.summary=$summary, k.claims_json=$claims, k.evidence_json=$evidence, "
            "k.related_json=$related, k.uncertainty=$unc, k.revision_count=$rev, k.updated=$ts",
            {
                "n": name,
                "summary": final_summary,
                "claims": json.dumps(sorted(claim_set), ensure_ascii=False),
                "evidence": json.dumps(sorted(evidence_set), ensure_ascii=False),
                "related": json.dumps(sorted(related_set), ensure_ascii=False),
                "unc": final_unc,
                "rev": revision,
                "ts": ts,
            },
        )

    def concept_knowledge(self, name: str) -> dict:
        empty = {
            "name": name,
            "summary": "",
            "claims": [],
            "evidence_refs": [],
            "related_terms": [],
            "uncertainty": None,
            "revision_count": 0,
            "updated": "",
        }
        try:
            r = self._conn.execute(
                "MATCH (k:ConceptKnowledge {name:$n}) "
                "RETURN k.name AS name, k.summary AS summary, k.claims_json AS claims_json, "
                "k.evidence_json AS evidence_json, k.related_json AS related_json, "
                "k.uncertainty AS uncertainty, k.revision_count AS revision_count, k.updated AS updated",
                {"n": name},
            ).get_as_df()
        except Exception:
            return empty

        if r.empty:
            return empty
        row = r.iloc[0]
        return {
            "name": row.get("name") or name,
            "summary": row.get("summary") or "",
            "claims": self._parse_json_list(row.get("claims_json")),
            "evidence_refs": self._parse_json_list(row.get("evidence_json")),
            "related_terms": self._parse_json_list(row.get("related_json")),
            "uncertainty": (float(row.get("uncertainty")) if row.get("uncertainty") is not None else None),
            "revision_count": int(row.get("revision_count") or 0),
            "updated": row.get("updated") or "",
        }

    def ensure_minimal_concept_knowledge(
        self,
        name: str,
        *,
        domain: str,
        source: str,
    ) -> None:
        existing = self.concept_knowledge(name)
        need_context = not self._has_context(existing)
        need_facts = not self._has_facts(existing)
        if not (need_context or need_facts):
            return

        summary = None
        if need_context:
            summary = (
                f"{name} är ett koncept i domänen '{domain or 'okänd'}'. "
                f"Skapat från källa '{source or 'okänd'}'."
            )

        fallback_claims: list[str] = []
        fallback_evidence: list[str] = []
        if need_facts:
            fallback_claims.append(f"{name} tillhör domänen '{domain or 'okänd'}'.")
            fallback_evidence.append(f"concept_source:{source or 'okänd'}")

        related_terms = [x for x in [domain, source] if str(x or "").strip()]
        uncertainty = 0.65 if need_facts else None
        self.upsert_concept_knowledge(
            name,
            summary=summary,
            claims=fallback_claims,
            evidence_refs=fallback_evidence,
            related_terms=related_terms,
            uncertainty=uncertainty,
        )

    def _in_relations(self, name: str) -> list[dict]:
        if self._relation_meta_available:
            try:
                r = self._conn.execute(
                    "MATCH (a:Concept)-[r:Relation]->(b:Concept {name:$n}) "
                    "RETURN a.name AS source, a.domain AS source_domain, "
                    "r.type AS type, r.why AS why, r.strength AS strength, "
                    "r.evidence_score AS evidence_score, r.assumption_flag AS assumption_flag, "
                    "r.created AS created",
                    {"n": name},
                )
                return r.get_as_df().to_dict("records")
            except Exception:
                self._relation_meta_available = False

        r = self._conn.execute(
            "MATCH (a:Concept)-[r:Relation]->(b:Concept {name:$n}) "
            "RETURN a.name AS source, a.domain AS source_domain, "
            "r.type AS type, r.why AS why, r.strength AS strength, r.created AS created",
            {"n": name},
        )
        out = r.get_as_df().to_dict("records")
        for row in out:
            row.setdefault("evidence_score", None)
            row.setdefault("assumption_flag", None)
        return out

    def backfill_concept_knowledge(
        self,
        name: str,
        *,
        strict: bool = False,
        min_evidence_score: float = _STRONG_FACT_MIN_SCORE,
    ) -> dict:
        cmeta_df = self._conn.execute(
            "MATCH (c:Concept {name:$n}) "
            "RETURN c.name AS name, c.domain AS domain, c.source AS source",
            {"n": name},
        ).get_as_df()
        if cmeta_df.empty:
            return {"name": name, "updated": False, "reason": "missing_concept"}

        cmeta = cmeta_df.iloc[0]
        domain = str(cmeta.get("domain") or "okänd")
        source = str(cmeta.get("source") or "okänd")
        existing = self.concept_knowledge(name)
        min_score = max(0.0, min(1.0, float(min_evidence_score)))
        need_context = not self._has_context(existing)
        need_facts = not self._has_facts(existing)
        fq_before = self._fact_quality(existing, min_score=min_score)
        has_strong_facts = bool(
            need_facts is False
            and fq_before.get("per_claim_supported")
            and fq_before.get("fully_classified")
        )
        need_strong = bool(strict) and not has_strong_facts

        if not (need_context or need_facts or need_strong):
            return {"name": name, "updated": False, "reason": "already_complete"}

        outgoing = self.out_relations(name)
        incoming = self._in_relations(name)
        degree = len(outgoing) + len(incoming)

        summary = None
        if need_context:
            summary = (
                f"{name} i domänen '{domain}'. "
                f"Noden har {degree} relationer i grafen och källa '{source}'."
            )
            if outgoing:
                o = outgoing[0]
                summary += f" Exempel ut: [{o.get('type', '')}] till '{o.get('target', '')}'."
            elif incoming:
                i = incoming[0]
                summary += f" Exempel in: '{i.get('source', '')}' via [{i.get('type', '')}]."

        synthesized_claims: list[str] = []
        synthesized_evidence: list[str] = []
        related_terms: list[str] = [domain]

        for rel in outgoing[:4]:
            tgt = str(rel.get("target") or "").strip()
            typ = str(rel.get("type") or "").strip()
            why = str(rel.get("why") or "").strip()
            ev = rel.get("evidence_score")
            if tgt and typ:
                synthesized_claims.append(f"{name} --[{typ}]--> {tgt}")
                if ev is not None:
                    synthesized_evidence.append(
                        f"relation_out:{name}->{tgt}:{typ}:ev={float(ev):.2f}"
                    )
                else:
                    synthesized_evidence.append(f"relation_out:{name}->{tgt}:{typ}")
                related_terms.extend([tgt, typ])
                if why:
                    synthesized_evidence.append(f"why:{why[:120]}")

        for rel in incoming[:4]:
            src = str(rel.get("source") or "").strip()
            typ = str(rel.get("type") or "").strip()
            why = str(rel.get("why") or "").strip()
            ev = rel.get("evidence_score")
            if src and typ:
                synthesized_claims.append(f"{src} --[{typ}]--> {name}")
                if ev is not None:
                    synthesized_evidence.append(
                        f"relation_in:{src}->{name}:{typ}:ev={float(ev):.2f}"
                    )
                else:
                    synthesized_evidence.append(f"relation_in:{src}->{name}:{typ}")
                related_terms.extend([src, typ])
                if why:
                    synthesized_evidence.append(f"why:{why[:120]}")

        if need_facts and not synthesized_claims:
            synthesized_claims.append(f"{name} tillhör domänen '{domain}'.")
        if need_facts and not synthesized_evidence:
            synthesized_evidence.append(f"concept_source:{source}")
        if need_strong and source:
            synthesized_evidence.append(f"source_doc:{source}")

        uncertainty = 0.45 if degree > 0 else 0.62
        self.upsert_concept_knowledge(
            name,
            summary=summary,
            claims=synthesized_claims if need_facts else None,
            evidence_refs=synthesized_evidence if (need_facts or need_strong) else None,
            related_terms=related_terms,
            uncertainty=uncertainty,
        )
        after = self.concept_knowledge(name)
        fq_after = self._fact_quality(after, min_score=min_score)
        has_strong_after = bool(
            self._has_facts(after)
            and fq_after.get("per_claim_supported")
            and fq_after.get("fully_classified")
        )
        return {
            "name": name,
            "updated": bool(
                need_context
                or need_facts
                or (need_strong and has_strong_after and (not has_strong_facts))
            ),
            "used_relations": degree,
            "need_context": need_context,
            "need_facts": need_facts,
            "need_strong_facts": need_strong,
            "strong_facts_before": has_strong_facts,
            "strong_facts_after": has_strong_after,
        }

    def knowledge_audit(
        self,
        limit: int = 50,
        *,
        strict: bool = False,
        min_evidence_score: float = _STRONG_FACT_MIN_SCORE,
    ) -> dict:
        concepts = self._all_concepts_meta()
        knowledge = self._all_knowledge_by_name()
        total = len(concepts)
        with_context = 0
        with_facts_basic = 0
        with_facts_strong = 0
        complete = 0
        missing: list[dict] = []
        min_score = max(0.0, min(1.0, float(min_evidence_score)))

        for c in concepts:
            name = c["name"]
            k = knowledge.get(name)
            has_context = self._has_context(k)
            has_facts = self._has_facts(k)
            fq = self._fact_quality(k, min_score=min_score)
            has_strong_facts = bool(
                has_facts
                and fq.get("per_claim_supported")
                and fq.get("fully_classified")
            )
            if has_context:
                with_context += 1
            if has_facts:
                with_facts_basic += 1
            if has_strong_facts:
                with_facts_strong += 1
            is_complete = has_context and (has_strong_facts if strict else has_facts)
            if is_complete:
                complete += 1
            else:
                reasons: list[str] = []
                if not has_context:
                    reasons.append("missing_context")
                if strict:
                    if not has_strong_facts:
                        reasons.append("missing_strong_facts")
                elif not has_facts:
                    reasons.append("missing_facts")
                missing.append(
                    {
                        "name": name,
                        "domain": c.get("domain") or "okänd",
                        "source": c.get("source") or "okänd",
                        "reasons": reasons,
                        "claims": len((k or {}).get("claims", [])),
                        "evidence_refs": len((k or {}).get("evidence_refs", [])),
                        "has_context": has_context,
                        "has_facts": has_facts,
                        "has_strong_facts": has_strong_facts,
                        "fact_quality": fq,
                    }
                )

        missing.sort(key=lambda x: (x["domain"], x["name"]))
        safe_limit = max(1, int(limit or 1))
        return {
            "total_concepts": total,
            "with_context": with_context,
            "with_facts": with_facts_basic,
            "with_strong_facts": with_facts_strong,
            "complete_nodes": complete,
            "missing_total": len(missing),
            "gate": {"strict": bool(strict), "min_evidence_score": min_score},
            "coverage": {
                "context": (with_context / total if total else 1.0),
                "facts": (with_facts_basic / total if total else 1.0),
                "strong_facts": (with_facts_strong / total if total else 1.0),
                "complete": (complete / total if total else 1.0),
            },
            "missing": missing[:safe_limit],
        }

    def backfill_missing_concept_knowledge(
        self,
        limit: int | None = None,
        *,
        strict: bool = False,
        min_evidence_score: float = _STRONG_FACT_MIN_SCORE,
    ) -> dict:
        audit = self.knowledge_audit(
            limit=100000,
            strict=strict,
            min_evidence_score=min_evidence_score,
        )
        missing = audit.get("missing", [])
        if limit is not None and limit > 0:
            missing = missing[:limit]

        updated = 0
        results: list[dict] = []
        for item in missing:
            res = self.backfill_concept_knowledge(
                str(item.get("name") or ""),
                strict=strict,
                min_evidence_score=min_evidence_score,
            )
            if res.get("updated"):
                updated += 1
            results.append(res)
        return {
            "requested": len(missing),
            "updated": updated,
            "results": results,
            "before": audit,
            "after": self.knowledge_audit(
                limit=50,
                strict=strict,
                min_evidence_score=min_evidence_score,
            ),
        }

    def node_context_for_query(self, query: str, limit: int = 5) -> list[dict]:
        tokens = [t.lower() for t in re.findall(r"[\wåäöÅÄÖ]{3,}", query or "")]
        if not tokens:
            return []
        concepts = self.concepts()
        scored: list[tuple[int, str]] = []
        for c in concepts:
            name = str(c.get("name") or "")
            lname = name.lower()
            score = sum(1 for t in tokens if t in lname)
            if score > 0:
                scored.append((score, name))
        scored.sort(key=lambda x: (-x[0], len(x[1])))

        out: list[dict] = []
        seen = set()
        for _, name in scored:
            if name in seen:
                continue
            seen.add(name)
            k = self.concept_knowledge(name)
            out.append({
                "name": name,
                "summary": k.get("summary", ""),
                "claims": list(k.get("claims", []))[:3],
                "evidence_refs": list(k.get("evidence_refs", []))[:3],
                "related_terms": list(k.get("related_terms", []))[:5],
                "uncertainty": k.get("uncertainty"),
            })
            if len(out) >= limit:
                break
        return out

    def _enrich_nodes_from_relation(
        self,
        src: str,
        rel_type: str,
        tgt: str,
        why: str,
        source_tag: str,
    ) -> None:
        why_short = (why or "").strip()[:280]
        claim = f"{src} --[{rel_type}]--> {tgt}"
        edge_ref = f"relation_edge:{src}->{tgt}:{rel_type}"
        source_ref = f"relation_source:{source_tag or 'relation'}"
        evidence_refs = [edge_ref, source_ref]
        if why_short:
            evidence_refs.append(f"why:{why_short}")

        src_summary = (
            f"Koncept i grafen. Kopplat via relation '{rel_type}' till '{tgt}'."
            + (f" Motivation: {why_short}" if why_short else "")
        )
        tgt_summary = (
            f"Koncept i grafen. Relaterat från '{src}' via '{rel_type}'."
            + (f" Motivation: {why_short}" if why_short else "")
        )

        rel_terms = [src, tgt, rel_type]
        uncertainty = 0.45 if why_short else 0.7

        try:
            self.upsert_concept_knowledge(
                src,
                summary=src_summary,
                claim=claim,
                evidence_refs=evidence_refs,
                related_terms=rel_terms,
                uncertainty=uncertainty,
            )
            self.upsert_concept_knowledge(
                tgt,
                summary=tgt_summary,
                claim=claim,
                evidence_refs=evidence_refs,
                related_terms=rel_terms,
                uncertainty=uncertainty,
            )
        except Exception:
            # Kunskapslager får aldrig blockera relationsskrivning.
            return

    def strengthen(self, src: str, tgt: str, delta: float = 0.05) -> None:
        """Hebbisk stärkning — öka styrkan på kanter längs aktiverade stigar."""
        self._conn.execute(
            "MATCH (a:Concept {name:$s})-[r:Relation]->(b:Concept {name:$t}) "
            "SET r.strength = r.strength + $d",
            {"s": src, "t": tgt, "d": delta},
        )

    # ── Läsoperationer ────────────────────────────────────────────────────────

    def concepts(self, domain: str | None = None) -> list[dict]:
        if domain:
            r = self._conn.execute(
                "MATCH (c:Concept) WHERE c.domain=$d RETURN c.name AS name",
                {"d": domain})
        else:
            r = self._conn.execute(
                "MATCH (c:Concept) RETURN c.name AS name, c.domain AS domain")
        return r.get_as_df().to_dict("records")

    def out_relations(self, name: str) -> list[dict]:
        if self._relation_meta_available:
            try:
                r = self._conn.execute(
                    "MATCH (a:Concept {name:$n})-[r:Relation]->(b:Concept) "
                    "RETURN b.name AS target, r.type AS type, r.why AS why, r.strength AS strength, "
                    "r.evidence_score AS evidence_score, r.assumption_flag AS assumption_flag",
                    {"n": name},
                )
                rows = r.get_as_df().to_dict("records")
                # Indikera flaggade relationer i ReviewQueue (fire-and-forget)
                _queue_indications(name, rows)
                return rows
            except Exception:
                self._relation_meta_available = False

        r = self._conn.execute(
            "MATCH (a:Concept {name:$n})-[r:Relation]->(b:Concept) "
            "RETURN b.name AS target, r.type AS type, r.why AS why, r.strength AS strength",
            {"n": name},
        )
        out = r.get_as_df().to_dict("records")
        for row in out:
            row.setdefault("evidence_score", None)
            row.setdefault("assumption_flag", None)
        return out

    def domains(self) -> list[str]:
        r = self._conn.execute(
            "MATCH (c:Concept) RETURN DISTINCT c.domain AS domain")
        return [row["domain"] for row in r.get_as_df().to_dict("records")]

    def stats(self) -> dict:
        nc = self._conn.execute(
            "MATCH (c:Concept) RETURN count(c) AS n").get_as_df()
        nr = self._conn.execute(
            "MATCH ()-[r:Relation]->() RETURN count(r) AS n").get_as_df()
        return {"concepts": int(nc["n"].iloc[0]),
                "relations": int(nr["n"].iloc[0])}

    # ── Multi-hop path finder ─────────────────────────────────────────────────

    def find_path(self, domain_a: str, domain_b: str,
                  max_hops: int = 8) -> list[tuple[str, str, str]] | None:
        """
        BFS: kortaste stig från domän_a till domän_b via intermediära noder.
        Stärker kanterna längs hittad stig (Hebb).
        """
        starts = [r["name"] for r in self.concepts(domain_a)]
        goals  = {r["name"] for r in self.concepts(domain_b)}
        queue, visited = deque(), set()
        for s in starts:
            queue.append((s, []))
            visited.add(s)

        while queue:
            node, path = queue.popleft()
            if len(path) >= max_hops:
                continue
            for rel in self.out_relations(node):
                tgt      = rel["target"]
                new_path = path + [(node, rel["type"], tgt)]
                if tgt in goals:
                    if not self._read_only:
                        for s_, _, t_ in new_path:
                            self.strengthen(s_, t_, 0.05)
                    return new_path
                if tgt not in visited:
                    visited.add(tgt)
                    queue.append((tgt, new_path))
        return None

    # ── Trace / explainability ────────────────────────────────────────────────

    def _resolve_nodes(self, name: str) -> list[str]:
        """Tolka 'name' som domännamn eller konceptnamn — returnera lista av koncept."""
        r = self._conn.execute(
            "MATCH (c:Concept) WHERE c.domain=$d RETURN c.name AS name LIMIT 30",
            {"d": name}).get_as_df()
        if not r.empty:
            return r["name"].tolist()
        r = self._conn.execute(
            "MATCH (c:Concept) WHERE c.name CONTAINS $n RETURN c.name AS name LIMIT 10",
            {"n": name}).get_as_df()
        return r["name"].tolist()

    def _out_relations_full(self, name: str) -> list[dict]:
        """Relationer med full metadata: domäner, why, strength, evidence_score, assumption_flag, created."""
        if self._relation_meta_available:
            try:
                r = self._conn.execute(
                    "MATCH (a:Concept {name:$n})-[r:Relation]->(b:Concept) "
                    "RETURN a.domain AS src_domain, r.type AS rel_type, "
                    "r.why AS why, r.strength AS strength, "
                    "r.evidence_score AS evidence_score, r.assumption_flag AS assumption_flag, "
                    "r.created AS created, b.name AS tgt, b.domain AS tgt_domain",
                    {"n": name},
                )
                return r.get_as_df().to_dict("records")
            except Exception:
                self._relation_meta_available = False

        r = self._conn.execute(
            "MATCH (a:Concept {name:$n})-[r:Relation]->(b:Concept) "
            "RETURN a.domain AS src_domain, r.type AS rel_type, "
            "r.why AS why, r.strength AS strength, r.created AS created, "
            "b.name AS tgt, b.domain AS tgt_domain",
            {"n": name},
        )
        out = r.get_as_df().to_dict("records")
        for row in out:
            row.setdefault("evidence_score", None)
            row.setdefault("assumption_flag", None)
        return out

    def trace_path(
        self,
        start: str,
        end: str,
        max_hops: int = 10,
        max_paths: int = 3,
    ) -> list[list[dict]]:
        """
        Hitta upp till max_paths stigar från start → end.
        Start/end kan vara konceptnamn eller domännamn.

        Varje hopp är ett dict:
          {src, src_domain, rel_type, why, strength, created, tgt, tgt_domain}

        Returnerar stigarna sorterade på domänbredd (novelty) fallande.
        """
        start_nodes = self._resolve_nodes(start)
        end_nodes   = set(self._resolve_nodes(end))
        if not start_nodes or not end_nodes:
            return []

        found  = []
        # BFS — visited spåras per stig (inte globalt) för att hitta alternativa vägar
        queue  = deque([(n, []) for n in start_nodes])
        # Global besökt för effektivitet — tillåt max_paths vägar via samma nod
        visit_count: dict[str, int] = {}

        while queue and len(found) < max_paths:
            node, path = queue.popleft()
            if len(path) >= max_hops:
                continue

            visited_in_path = {s["src"] for s in path} | ({path[-1]["tgt"]} if path else set())

            for rel in self._out_relations_full(node):
                tgt = rel["tgt"]
                if tgt in visited_in_path:
                    continue

                step = {
                    "src":        node,
                    "src_domain": rel.get("src_domain") or "okänd",
                    "rel_type":   rel.get("rel_type") or "",
                    "why":        rel.get("why") or "",
                    "strength":   float(rel.get("strength") or 0.0),
                    "evidence_score": (
                        float(rel.get("evidence_score"))
                        if rel.get("evidence_score") is not None
                        else None
                    ),
                    "assumption_flag": (
                        bool(rel.get("assumption_flag"))
                        if rel.get("assumption_flag") is not None
                        else None
                    ),
                    "created":    rel.get("created") or "",
                    "tgt":        tgt,
                    "tgt_domain": rel.get("tgt_domain") or "okänd",
                }
                new_path = path + [step]

                if tgt in end_nodes:
                    found.append(new_path)
                    if len(found) >= max_paths:
                        break
                else:
                    cnt = visit_count.get(tgt, 0)
                    if cnt < max_paths:
                        visit_count[tgt] = cnt + 1
                        queue.append((tgt, new_path))

        # Sortera på domänbredd (antal unika domäner = novelty-proxy)
        def _breadth(p: list[dict]) -> int:
            return len({s["src_domain"] for s in p} | {p[-1]["tgt_domain"]})

        found.sort(key=_breadth, reverse=True)
        return found

    def path_novelty(self, path: list[tuple[str, str, str]]) -> float:
        """
        Novelty = domänbredd + analogibonus.
        Kräver INTE analogikanter för att ge poäng — domänkorsning räcker.
        Analogikanter ger extra bonus (explicita strukturella bryggor).
        """
        if not path:
            return 0.0
        domains, analogies = set(), 0
        for src, rel, tgt in path:
            for name in (src, tgt):
                r = self._conn.execute(
                    "MATCH (c:Concept {name:$n}) RETURN c.domain AS d",
                    {"n": name}).get_as_df()
                if not r.empty:
                    domains.add(r["d"].iloc[0])
            if rel == "är_analogt_med":
                analogies += 1
        return float(len(domains)) + analogies * 2.0

    # ── Koncept-embeddings i grafen ──────────────────────────────────────────

    def _vector_mean(self, vectors: list[list[float]]) -> list[float] | None:
        if not vectors:
            return None
        dims = len(vectors[0])
        if dims <= 0:
            return None
        if any(len(v) != dims for v in vectors):
            return None
        sums = [0.0] * dims
        for vec in vectors:
            for idx, value in enumerate(vec):
                sums[idx] += float(value)
        n = float(len(vectors))
        return [v / n for v in sums]

    def _cosine_similarity(self, a: list[float] | None, b: list[float] | None) -> float | None:
        if not a or not b:
            return None
        if len(a) != len(b):
            return None
        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0
        for av, bv in zip(a, b, strict=True):
            af = float(av)
            bf = float(bv)
            dot += af * bf
            norm_a += af * af
            norm_b += bf * bf
        if norm_a <= 0.0 or norm_b <= 0.0:
            return None
        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))

    def _load_concept_embedding(self, name: str) -> list[float] | None:
        if name in self._embedding_cache:
            return self._embedding_cache.get(name)
        if not self._concept_embedding_available:
            return None
        try:
            r = self._conn.execute(
                "MATCH (e:ConceptEmbedding {name:$n}) "
                "RETURN e.vector_json AS v LIMIT 1",
                {"n": name},
            ).get_as_df()
        except Exception:
            self._concept_embedding_available = False
            return None
        if r.empty:
            return None
        raw = str(r["v"].iloc[0] or "").strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except Exception:
            return None
        if not isinstance(parsed, list) or not parsed:
            return None
        vec = [float(x) for x in parsed]
        self._embedding_cache[name] = vec
        return vec

    def _upsert_concept_embedding(self, name: str, vector: list[float]) -> None:
        if self._read_only or not self._concept_embedding_available or not vector:
            return
        try:
            self._conn.execute(
                "MERGE (e:ConceptEmbedding {name:$n}) "
                "SET e.vector_json=$v, e.model=$m, e.dims=$d, e.updated=$t",
                {
                    "n": name,
                    "v": json.dumps(vector, ensure_ascii=False),
                    "m": self._embed_model,
                    "d": int(len(vector)),
                    "t": datetime.utcnow().isoformat(),
                },
            )
            self._embedding_cache[name] = vector
        except Exception:
            # Embeddinglagret får aldrig blockera huvudgrafen.
            self._concept_embedding_available = False

    def _get_embedder(self):
        if not self._embedding_enabled:
            return None
        if self._embedder is not None:
            return self._embedder
        try:
            from nouse.embeddings.ollama_embed import OllamaEmbedder

            self._embedder = OllamaEmbedder(model=self._embed_model)
            return self._embedder
        except Exception:
            self._embedding_enabled = False
            return None

    def _embedding_text_for_concept(self, name: str, domain: str) -> str:
        knowledge = self.concept_knowledge(name)
        summary = str(knowledge.get("summary") or "").strip()
        claims = [str(x).strip() for x in (knowledge.get("claims") or []) if str(x).strip()]
        related = [str(x).strip() for x in (knowledge.get("related_terms") or []) if str(x).strip()]
        parts = [f"name: {name}", f"domain: {domain or 'okänd'}"]
        if summary:
            parts.append(f"summary: {summary[:600]}")
        if claims:
            parts.append(f"claims: {' | '.join(claims[:4])}")
        if related:
            parts.append(f"related: {', '.join(related[:8])}")
        return "\n".join(parts)

    def _ensure_concept_embeddings(
        self,
        concepts: list[dict[str, str]],
    ) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        if not concepts:
            return out

        missing: list[dict[str, str]] = []
        for row in concepts:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            vec = self._load_concept_embedding(name)
            if vec:
                out[name] = vec
            else:
                missing.append({"name": name, "domain": str(row.get("domain") or "okänd")})

        if not missing:
            return out

        embedder = self._get_embedder()
        if embedder is None:
            return out

        try:
            for batch_start in range(0, len(missing), _GRAPH_EMBED_BATCH):
                batch = missing[batch_start : batch_start + _GRAPH_EMBED_BATCH]
                texts = [self._embedding_text_for_concept(row["name"], row["domain"]) for row in batch]
                vectors = embedder.embed_texts(texts)
                if len(vectors) != len(batch):
                    continue
                for row, vector in zip(batch, vectors, strict=True):
                    if not isinstance(vector, list) or not vector:
                        continue
                    clean_vec = [float(x) for x in vector]
                    out[row["name"]] = clean_vec
                    if not self._read_only:
                        self._upsert_concept_embedding(row["name"], clean_vec)
                    else:
                        self._embedding_cache[row["name"]] = clean_vec
        except Exception:
            # Kör vidare med topologisk fallback om embedding-modellen fallerar.
            return out

        return out

    # ── TDA: Topologisk domänanalys (Bisociation Step B) ─────────────────────

    def domain_tda_profile(self, domain: str,
                           max_epsilon: float = 2.0,
                           include_centroid: bool = False) -> dict:
        """
        Beräkna topologiskt fingeravtryck för en domän.

        Returnerar: {"domain": str, "h0": int, "h1": int, "n_concepts": int}

        H0 = antal isolerade kluster (separata kunskapsöar)
        H1 = antal feedback-cykler (cirkulär/self-referentiell kunskap)

        Hög H1 i en domän → rik intern struktur.
        Hög H0 → fragmenterad kunskap (många isolerade begrepp).
        """
        try:
            from nouse.tda.bridge import compute_distance_matrix, compute_betti
        except ImportError:
            return {"domain": domain, "h0": 1, "h1": 0, "n_concepts": 0}

        concepts = self.concepts(domain=domain)
        n = len(concepts)
        if n < 2:
            out = {
                "domain": domain,
                "h0": max(n, 1),
                "h1": 0,
                "n_concepts": n,
                "embedding_mode": "none",
                "embedding_coverage": 0.0,
            }
            if include_centroid:
                out["centroid"] = None
            return out

        concept_rows = [
            {"name": str(c.get("name") or "").strip(), "domain": domain}
            for c in concepts
            if str(c.get("name") or "").strip()
        ]
        semantic_map = self._ensure_concept_embeddings(concept_rows)
        semantic_vectors = [
            semantic_map[row["name"]]
            for row in concept_rows
            if row["name"] in semantic_map
        ]
        coverage = (len(semantic_vectors) / float(n)) if n > 0 else 0.0

        if len(semantic_vectors) >= 2:
            dm = compute_distance_matrix(semantic_vectors)
            h0, h1 = compute_betti(dm, max_epsilon=max_epsilon, steps=30)
            out = {
                "domain": domain,
                "h0": h0,
                "h1": h1,
                "n_concepts": n,
                "embedding_mode": "semantic",
                "embedding_coverage": round(float(coverage), 4),
            }
            if include_centroid:
                out["centroid"] = self._vector_mean(semantic_vectors)
            return out

        # Fallback: topologi från relationsgrad om embeddings saknas.
        # Varje koncept representeras av [out_degree, in_degree, strength_sum]
        topo_vectors: list[list[float]] = []
        for c in concepts:
            rels = self.out_relations(c["name"])
            out_d = float(len(rels))
            s_sum = sum(float(r.get("strength") or 1.0) for r in rels)
            in_r = self._conn.execute(
                "MATCH (a)-[r:Relation]->(b:Concept {name:$n}) RETURN count(r) AS n",
                {"n": c["name"]},
            ).get_as_df()
            in_d = float(in_r["n"].iloc[0]) if not in_r.empty else 0.0
            topo_vectors.append([out_d, in_d, s_sum])

        dm = compute_distance_matrix(topo_vectors)
        h0, h1 = compute_betti(dm, max_epsilon=max_epsilon, steps=30)
        out = {
            "domain": domain,
            "h0": h0,
            "h1": h1,
            "n_concepts": n,
            "embedding_mode": "topology_fallback",
            "embedding_coverage": round(float(coverage), 4),
        }
        if include_centroid:
            out["centroid"] = None
        return out

    def bisociation_candidates(
        self,
        tau_threshold: float = 0.55,
        max_epsilon: float = 2.0,
        semantic_similarity_max: float = _BISOC_SEMANTIC_SIM_MAX,
        max_domains: int = 50,
    ) -> list[dict]:
        """
        Hitta domänpar med HÖG topologisk similaritet och LÅG semantisk likhet,
        men INGEN direkt BFS-stig.

        Dessa är genuina bisociationskandidater (Koestler 1964):
          - Låg semantisk koppling mellan domäncentroider
          - Hög strukturell likhet (τ ≥ tau_threshold)
          - Ingen direkt topologisk väg mellan domänerna
          → 1+1=3-potentialen är störst här.

        Returnerar lista med:
          {"domain_a", "domain_b", "tau", "semantic_similarity", "semantic_gap", "score", ...}
        Sorterat på kombinerad score (topologi + semantiskt gap) fallande.
        """
        try:
            from nouse.tda.bridge import topological_similarity
        except ImportError:
            return []

        all_domains = self.domains()
        if max_domains and len(all_domains) > max_domains:
            # Välj de domäner med flest noder — de är mest meningsfulla för bisociation
            r = self._conn.execute(
                "MATCH (c:Concept) RETURN c.domain AS domain, count(c) AS n "
                "ORDER BY n DESC LIMIT $lim",
                {"lim": max_domains},
            )
            top = [row["domain"] for row in r.get_as_df().to_dict("records")]
            domains = [d for d in all_domains if d in set(top)]
        else:
            domains = all_domains
        profiles = {
            d: self.domain_tda_profile(d, max_epsilon, include_centroid=True)
            for d in domains
        }

        # En enda bulk-query ersätter N² find_path-anrop:
        # Hitta alla domänpar som redan är anslutna (max 4 hopp)
        connected_pairs: set[tuple[str, str]] = set()
        try:
            r = self._conn.execute(
                "MATCH (a:Concept)-[:Relation*1..4]->(b:Concept) "
                "WHERE a.domain IN $doms AND b.domain IN $doms AND a.domain <> b.domain "
                "RETURN DISTINCT a.domain AS da, b.domain AS db",
                {"doms": domains},
            )
            for row in r.get_as_df().to_dict("records"):
                da_, db_ = row["da"], row["db"]
                connected_pairs.add((da_, db_))
                connected_pairs.add((db_, da_))
        except Exception:
            pass  # fallback: anta inga anslutningar känd → alla par analyseras

        results  = []

        for i, da in enumerate(domains):
            for db in domains[i + 1:]:
                # Hoppa om det finns en direkt stig (redan kopplad)
                if (da, db) in connected_pairs:
                    continue
                pa = profiles[da]
                pb = profiles[db]
                tau = topological_similarity(pa["h0"], pa["h1"],
                                             pb["h0"], pb["h1"])
                centroid_a = pa.get("centroid")
                centroid_b = pb.get("centroid")
                cos_sim = self._cosine_similarity(centroid_a, centroid_b)
                semantic_similarity = None
                if cos_sim is not None:
                    semantic_similarity = max(0.0, min(1.0, (float(cos_sim) + 1.0) / 2.0))
                    if semantic_similarity > max(0.0, min(1.0, float(semantic_similarity_max))):
                        continue
                semantic_gap = 1.0 - semantic_similarity if semantic_similarity is not None else 1.0
                score = ((1.0 - _BISOC_SEMANTIC_WEIGHT) * float(tau)) + (
                    _BISOC_SEMANTIC_WEIGHT * float(semantic_gap)
                )
                if tau >= tau_threshold:
                    results.append(
                        {
                            "domain_a": da,
                            "domain_b": db,
                            "tau": tau,
                            "h0_a": pa["h0"],
                            "h1_a": pa["h1"],
                            "h0_b": pb["h0"],
                            "h1_b": pb["h1"],
                            "semantic_similarity": semantic_similarity,
                            "semantic_gap": semantic_gap,
                            "score": score,
                            "embedding_coverage_a": float(pa.get("embedding_coverage", 0.0) or 0.0),
                            "embedding_coverage_b": float(pb.get("embedding_coverage", 0.0) or 0.0),
                            "embedding_mode_a": str(pa.get("embedding_mode") or "unknown"),
                            "embedding_mode_b": str(pb.get("embedding_mode") or "unknown"),
                        }
                    )

        results.sort(key=lambda x: (float(x.get("score", 0.0)), float(x.get("tau", 0.0))), reverse=True)
        return results
