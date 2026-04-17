from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nouse.config.paths import path_from_env
from nouse.field.surface import FieldSurface

_DIALOGUE_PROMOTION_MIN_SUPPORT = max(
    2,
    int(os.getenv("NOUSE_MEMORY_DIALOGUE_PROMOTION_MIN_SUPPORT", "2") or 2),
)
_DIALOGUE_PROMOTION_MIN_ANSWER_CHARS = max(
    8,
    int(os.getenv("NOUSE_MEMORY_DIALOGUE_PROMOTION_MIN_ANSWER_CHARS", "20") or 20),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "..."


def _safe_float(value: Any, default: float = 0.5) -> float:
    try:
        return float(value)
    except Exception:
        return default


class MemoryStore:
    """
    Brain-inspired memory system with four stores:
      - working memory: short, bounded active set
      - episodic memory: timestamped event stream
      - semantic memory: consolidated relation facts
      - procedural memory: behavior patterns (sources/types)
    """

    def __init__(
        self,
        *,
        root: Path | str | None = None,
        working_capacity: int = 80,
        semantic_fact_cap: int = 12000,
    ) -> None:
        env_root = (os.getenv("NOUSE_MEMORY_DIR") or "").strip()
        if root is not None:
            base = Path(root)
        elif env_root:
            base = Path(env_root)
        else:
            base = path_from_env("NOUSE_MEMORY_DIR", "memory")
        self.root = base
        self.root.mkdir(parents=True, exist_ok=True)

        self.working_capacity = max(10, int(working_capacity))
        self.semantic_fact_cap = max(100, int(semantic_fact_cap))

        self.working_path = self.root / "working.json"
        self.episodes_path = self.root / "episodic.jsonl"
        self.semantic_path = self.root / "semantic.json"
        self.procedural_path = self.root / "procedural.json"

    def _load_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _save_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_episodes(self) -> list[dict[str, Any]]:
        if not self.episodes_path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.episodes_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def _save_episodes(self, episodes: list[dict[str, Any]]) -> None:
        self.episodes_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(e, ensure_ascii=False) for e in episodes]
        payload = "\n".join(lines) + ("\n" if lines else "")
        self.episodes_path.write_text(payload, encoding="utf-8")

    def _normalize_relation(self, rel: dict[str, Any]) -> dict[str, Any] | None:
        src = str(rel.get("src") or "").strip()
        rel_type = str(rel.get("type") or rel.get("rel_type") or "").strip()
        tgt = str(rel.get("tgt") or "").strip()
        if not src or not rel_type or not tgt:
            return None
        why = str(rel.get("why") or "").strip()
        return {
            "src": src,
            "type": rel_type,
            "tgt": tgt,
            "domain_src": str(rel.get("domain_src") or "okänd"),
            "domain_tgt": str(rel.get("domain_tgt") or "okänd"),
            "why": _clip(why, 280),
            "evidence_score": _safe_float(rel.get("evidence_score"), default=0.5),
            "assumption_flag": bool(rel.get("assumption_flag")) if rel.get("assumption_flag") is not None else None,
        }

    def _extract_cues(self, text: str, relations: list[dict[str, Any]], max_items: int = 14) -> list[str]:
        cues: list[str] = []
        for r in relations:
            cues.extend([r["src"], r["type"], r["tgt"]])
        for token in re.findall(r"[A-Za-z0-9_åäöÅÄÖ-]{4,}", text):
            cues.append(token)
        dedup: list[str] = []
        seen = set()
        for cue in cues:
            c = cue.strip()
            k = c.lower()
            if not c or k in seen:
                continue
            seen.add(k)
            dedup.append(c)
            if len(dedup) >= max_items:
                break
        return dedup

    def _extract_dialogue_pair(self, text: str) -> tuple[str, str] | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        q_match = re.search(r"(?im)^\s*fr[åa]ga\s*:\s*(.+?)\s*$", raw)
        a_match = re.search(r"(?im)^\s*svar\s*:\s*(.+?)\s*$", raw)
        if not q_match or not a_match:
            # Fallback for normalized one-line dialogues:
            # "Fraga: ... Svar: ..."
            q_match = re.search(r"(?i)\bfr[åa]ga\s*:\s*(.+?)(?:\s+\bsvar\s*:|$)", raw)
            a_match = re.search(r"(?i)\bsvar\s*:\s*(.+)$", raw)
        if not q_match or not a_match:
            return None
        question = re.sub(r"\s+", " ", q_match.group(1).strip())
        answer = re.sub(r"\s+", " ", a_match.group(1).strip())
        if not question or not answer:
            return None
        return (_clip(question, 400), _clip(answer, 700))

    def _dialogue_key(self, question: str, answer: str) -> str:
        q = re.sub(r"\s+", " ", str(question or "").strip().lower())
        a = re.sub(r"\s+", " ", str(answer or "").strip().lower())
        return f"{q[:240]}|{a[:420]}"

    def _load_working(self) -> dict[str, Any]:
        return self._load_json(
            self.working_path,
            {"capacity": self.working_capacity, "updated": "", "items": []},
        )

    def _save_working(self, data: dict[str, Any]) -> None:
        data["capacity"] = self.working_capacity
        data["updated"] = _now_iso()
        self._save_json(self.working_path, data)

    def working_snapshot(self, *, limit: int = 12) -> list[dict[str, Any]]:
        """
        Return newest working-memory items first.
        Useful for low-latency chat context ("prefrontal" read-path).
        """
        working = self._load_working()
        items = [row for row in (working.get("items") or []) if isinstance(row, dict)]
        safe_limit = max(1, min(int(limit), 200))
        tail = list(items[-safe_limit:])
        tail.reverse()
        out: list[dict[str, Any]] = []
        for row in tail:
            out.append(
                {
                    "id": str(row.get("id") or ""),
                    "ts": str(row.get("ts") or ""),
                    "source": str(row.get("source") or ""),
                    "domain_hint": str(row.get("domain_hint") or ""),
                    "summary": str(row.get("summary") or ""),
                    "relation_count": int(row.get("relation_count", 0) or 0),
                    "cues": [str(x) for x in (row.get("cues") or []) if str(x)],
                }
            )
        return out

    def _load_semantic(self) -> dict[str, Any]:
        return self._load_json(
            self.semantic_path,
            {"updated": "", "facts": {}, "concepts": {}},
        )

    def _save_semantic(self, data: dict[str, Any]) -> None:
        data["updated"] = _now_iso()
        self._save_json(self.semantic_path, data)

    def _load_procedural(self) -> dict[str, Any]:
        return self._load_json(
            self.procedural_path,
            {
                "updated": "",
                "source_counts": {},
                "relation_type_counts": {},
                "recent_patterns": [],
            },
        )

    def _save_procedural(self, data: dict[str, Any]) -> None:
        data["updated"] = _now_iso()
        self._save_json(self.procedural_path, data)

    def ingest_episode(
        self,
        text: str,
        meta: dict[str, Any] | None,
        relations: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """
        Store one event into episodic + working + procedural memory.
        """
        source_meta = meta or {}
        rels = [r for r in (self._normalize_relation(r or {}) for r in (relations or [])) if r is not None]
        ts = _now_iso()
        eid = f"ep_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:10]}"
        clean_text = " ".join((text or "").split())
        episode = {
            "id": eid,
            "ts": ts,
            "source": str(source_meta.get("source") or "unknown"),
            "domain_hint": str(source_meta.get("domain_hint") or "okänd"),
            "path": str(source_meta.get("path") or ""),
            "text_chars": len(clean_text),
            "text_excerpt": _clip(clean_text, 3000),
            "relations": rels[:80],
            "relation_count": len(rels),
            "consolidated": False,
            "consolidated_at": None,
        }

        episodes = self._load_episodes()
        episodes.append(episode)
        self._save_episodes(episodes)

        working = self._load_working()
        items = list(working.get("items") or [])
        items.append(
            {
                "id": eid,
                "ts": ts,
                "source": episode["source"],
                "domain_hint": episode["domain_hint"],
                "summary": _clip(clean_text, 220),
                "relation_count": len(rels),
                "cues": self._extract_cues(clean_text, rels),
            }
        )
        if len(items) > self.working_capacity:
            items = items[-self.working_capacity :]
        working["items"] = items
        self._save_working(working)

        procedural = self._load_procedural()
        src_counts = dict(procedural.get("source_counts") or {})
        src = episode["source"]
        src_counts[src] = int(src_counts.get(src, 0)) + 1

        type_counts = dict(procedural.get("relation_type_counts") or {})
        rel_types = sorted({str(r["type"]) for r in rels})
        for t in rel_types:
            type_counts[t] = int(type_counts.get(t, 0)) + 1

        patterns = list(procedural.get("recent_patterns") or [])

        # Extract domain pairs from relations for Cerebellum empowerment tracking
        domain_pairs: set[tuple[str, str]] = set()
        for r in rels:
            src_domain = str(r.get("domain_src") or "okänd")
            tgt_domain = str(r.get("domain_tgt") or "okänd")
            pair = (min(src_domain, tgt_domain), max(src_domain, tgt_domain))
            domain_pairs.add(pair)

        # Check for external confirmation (evidence_score >= 0.65 or assumption_flag=False)
        externally_confirmed = any(
            _safe_float(r.get("evidence_score"), 0.5) >= 0.65 and not bool(r.get("assumption_flag"))
            for r in rels
        ) if rels else False

        # Primary domain pair (or single domain if no relations)
        primary_pair = next(iter(domain_pairs)) if domain_pairs else (episode["domain_hint"], episode["domain_hint"])

        patterns.append(
            {
                "ts": ts,
                "source": src,
                "domain_hint": primary_pair[0],
                "domain_hint_B": primary_pair[1],
                "relation_count": len(rels),
                "relation_types": rel_types,
                "externally_confirmed": externally_confirmed,
                "domain_pairs_count": len(domain_pairs),
            }
        )
        if len(patterns) > 200:
            patterns = patterns[-200:]

        procedural["source_counts"] = src_counts
        procedural["relation_type_counts"] = type_counts
        procedural["recent_patterns"] = patterns
        self._save_procedural(procedural)
        return episode

    def _touch_semantic_concept(
        self,
        concepts: dict[str, Any],
        *,
        name: str,
        domain: str,
    ) -> None:
        c = concepts.get(name)
        if not isinstance(c, dict):
            c = {
                "name": name,
                "domains": [],
                "appearances": 0,
                "last_seen": "",
            }
        domains = set(str(d) for d in (c.get("domains") or []))
        if domain:
            domains.add(domain)
        c["domains"] = sorted(domains)
        c["appearances"] = int(c.get("appearances", 0)) + 1
        c["last_seen"] = _now_iso()
        concepts[name] = c

    def consolidate(
        self,
        field: FieldSurface,
        *,
        max_episodes: int = 40,
        strict_min_evidence: float = 0.65,
    ) -> dict[str, Any]:
        """
        Consolidate episodic traces into semantic memory and concept knowledge.
        """
        episodes = self._load_episodes()
        unconsolidated = [e for e in episodes if not bool(e.get("consolidated"))]
        semantic = self._load_semantic()
        facts = dict(semantic.get("facts") or {})
        concepts = dict(semantic.get("concepts") or {})
        dialogue_facts = dict(semantic.get("dialogue_facts") or {})
        semantic_before = len(facts)
        uncon_before = len(unconsolidated)

        target = unconsolidated[: max(1, int(max_episodes))]
        processed_eps = 0
        consolidated_relations = 0
        dialogue_promotions = 0
        touched_episodes: list[str] = []

        for ep in target:
            ep_id = str(ep.get("id") or "")
            rels = list(ep.get("relations") or [])
            pair = self._extract_dialogue_pair(str(ep.get("text_excerpt") or ""))
            if pair:
                question, answer = pair
                if len(answer) >= _DIALOGUE_PROMOTION_MIN_ANSWER_CHARS:
                    dkey = self._dialogue_key(question, answer)
                    item = dialogue_facts.get(dkey)
                    if not isinstance(item, dict):
                        item = {
                            "question": question,
                            "answer": answer,
                            "support_count": 0,
                            "first_seen": _now_iso(),
                            "last_seen": "",
                            "evidence_refs": [],
                            "promoted": False,
                        }
                    old_support = int(item.get("support_count", 0) or 0)
                    new_support = old_support + 1
                    item["support_count"] = new_support
                    item["last_seen"] = _now_iso()
                    refs = list(item.get("evidence_refs") or [])
                    refs.append(f"episodic:{ep_id}")
                    item["evidence_refs"] = refs[-20:]

                    if (
                        new_support >= _DIALOGUE_PROMOTION_MIN_SUPPORT
                        and not bool(item.get("promoted"))
                    ):
                        claim = (
                            f"Dialogminne: Fragan '{_clip(question, 140)}' "
                            f"har upprepat svaret '{_clip(answer, 200)}'."
                        )
                        ev_ref = f"episodic:{ep_id}:dialogue_support={new_support}"
                        try:
                            if hasattr(field, "add_concept"):
                                field.add_concept(
                                    "dialog_memory",
                                    "dialog",
                                    source="memory_consolidation",
                                    ensure_knowledge=True,
                                )
                            field.upsert_concept_knowledge(
                                "dialog_memory",
                                claim=claim,
                                evidence_ref=ev_ref,
                                related_terms=[
                                    "dialogue_pattern",
                                    _clip(question, 80),
                                    _clip(answer, 80),
                                ],
                                uncertainty=0.36,
                            )
                            item["promoted"] = True
                            dialogue_promotions += 1
                        except Exception:
                            # Promotion is best-effort and must not block consolidation.
                            pass
                    dialogue_facts[dkey] = item

            if not rels:
                ep["consolidated"] = True
                ep["consolidated_at"] = _now_iso()
                touched_episodes.append(ep_id)
                processed_eps += 1
                continue

            for r in rels:
                src = str(r.get("src") or "").strip()
                rel_type = str(r.get("type") or "").strip()
                tgt = str(r.get("tgt") or "").strip()
                if not src or not rel_type or not tgt:
                    continue
                key = f"{src}|{rel_type}|{tgt}"
                why = str(r.get("why") or "").strip()
                ev = _safe_float(r.get("evidence_score"), default=0.5)

                item = facts.get(key)
                if not isinstance(item, dict):
                    item = {
                        "src": src,
                        "type": rel_type,
                        "tgt": tgt,
                        "support_count": 0,
                        "avg_evidence": 0.0,
                        "why_samples": [],
                        "evidence_refs": [],
                        "last_seen": "",
                    }

                old_support = int(item.get("support_count", 0))
                old_avg = _safe_float(item.get("avg_evidence"), default=0.0)
                new_support = old_support + 1
                new_avg = ((old_avg * old_support) + ev) / max(1, new_support)
                item["support_count"] = new_support
                item["avg_evidence"] = round(new_avg, 4)
                item["last_seen"] = _now_iso()

                why_samples = list(item.get("why_samples") or [])
                if why:
                    why_samples.append(_clip(why, 160))
                item["why_samples"] = why_samples[-6:]

                evidence_refs = list(item.get("evidence_refs") or [])
                evidence_refs.append(f"episodic:{ep_id}")
                item["evidence_refs"] = evidence_refs[-20:]
                facts[key] = item

                src_domain = str(r.get("domain_src") or "okänd")
                tgt_domain = str(r.get("domain_tgt") or "okänd")
                self._touch_semantic_concept(concepts, name=src, domain=src_domain)
                self._touch_semantic_concept(concepts, name=tgt, domain=tgt_domain)

                claim = f"{src} --[{rel_type}]--> {tgt}"
                ev_ref = f"episodic:{ep_id}:{rel_type}:ev={ev:.2f}"
                if bool(r.get("assumption_flag")):
                    ev_ref += ":assumption"
                uncertainty = 0.42 if ev >= float(strict_min_evidence) else 0.58
                field.upsert_concept_knowledge(
                    src,
                    claim=claim,
                    evidence_ref=ev_ref,
                    related_terms=[tgt, rel_type, tgt_domain],
                    uncertainty=uncertainty,
                )
                field.upsert_concept_knowledge(
                    tgt,
                    claim=claim,
                    evidence_ref=ev_ref,
                    related_terms=[src, rel_type, src_domain],
                    uncertainty=uncertainty,
                )
                consolidated_relations += 1

            ep["consolidated"] = True
            ep["consolidated_at"] = _now_iso()
            touched_episodes.append(ep_id)
            processed_eps += 1

        if len(facts) > self.semantic_fact_cap:
            ranked = sorted(
                facts.values(),
                key=lambda x: (int(x.get("support_count", 0)), _safe_float(x.get("avg_evidence"), 0.0)),
                reverse=True,
            )
            keep = ranked[: self.semantic_fact_cap]
            facts = {f"{row['src']}|{row['type']}|{row['tgt']}": row for row in keep if all(k in row for k in ("src", "type", "tgt"))}

        semantic["facts"] = facts
        semantic["concepts"] = concepts
        semantic["dialogue_facts"] = dialogue_facts
        self._save_semantic(semantic)
        self._save_episodes(episodes)

        after = self.audit(limit=12)
        return {
            "requested_episodes": len(target),
            "processed_episodes": processed_eps,
            "consolidated_relations": consolidated_relations,
            "semantic_facts_before": semantic_before,
            "semantic_facts_after": len(facts),
            "unconsolidated_before": uncon_before,
            "unconsolidated_after": int(after.get("unconsolidated_total", 0) or 0),
            "dialogue_promotions": dialogue_promotions,
            "dialogue_facts": len(dialogue_facts),
            "touched_episode_ids": touched_episodes,
        }

    def get_procedural_stats(self) -> dict[str, Any]:
        """
        Return actionable procedural statistics for Cerebellum empowerment signal.
        """
        procedural = self._load_procedural()
        patterns = list(procedural.get("recent_patterns") or [])

        # Compute effectiveness per domain pair
        pair_stats: dict[tuple[str, str], dict[str, Any]] = {}
        for p in patterns:
            d_a = str(p.get("domain_hint") or "okänd")
            d_b = str(p.get("domain_hint_B") or d_a)
            pair_key = (min(d_a, d_b), max(d_a, d_b))

            if pair_key not in pair_stats:
                pair_stats[pair_key] = {"attempts": 0, "successes": 0, "last_ts": ""}

            pair_stats[pair_key]["attempts"] += 1
            if p.get("externally_confirmed", False):
                pair_stats[pair_key]["successes"] += 1
            if str(p.get("ts") or "") > pair_stats[pair_key]["last_ts"]:
                pair_stats[pair_key]["last_ts"] = str(p.get("ts") or "")

        # Convert tuple keys to string for JSON serialization
        pair_stats_serializable = {
            f"{k[0]}||{k[1]}": v for k, v in pair_stats.items()
        }

        # Compute cross-domain effectiveness (different domains in pair)
        cross_domain_attempts = 0
        cross_domain_successes = 0
        for (d_a, d_b), stats in pair_stats.items():
            if d_a != d_b:
                cross_domain_attempts += stats["attempts"]
                cross_domain_successes += stats["successes"]

        cross_domain_effectiveness = (
            cross_domain_successes / max(1, cross_domain_attempts)
        )

        return {
            "source_counts": dict(procedural.get("source_counts") or {}),
            "relation_type_counts": dict(procedural.get("relation_type_counts") or {}),
            "recent_patterns": patterns,
            "pair_effectiveness": pair_stats_serializable,
            "cross_domain_effectiveness": round(cross_domain_effectiveness, 4),
            "cross_domain_attempts": cross_domain_attempts,
            "cross_domain_successes": cross_domain_successes,
            "pattern_count": len(patterns),
            "updated": _now_iso(),
        }

    def empowerment_signal(
        self,
        domain_A: str,
        domain_B: str,
        relation_type: str | None = None,
    ) -> float:
        """
        Compute empowerment signal for exploring domain_A ↔ domain_B.
        Tracks (domain_A, domain_B) pairs, not single domains.

        Formula: effectiveness × recency_weight × cross_domain_bonus × rigidity_penalty

        Returns float in [0.0, 1.0] where higher = more empowered to explore.
        """
        procedural = self._load_procedural()
        patterns = list(procedural.get("recent_patterns") or [])

        # Order-independent pair key
        d_a_norm = str(domain_A or "okänd").strip()
        d_b_norm = str(domain_B or "okänd").strip()
        pair_key = (min(d_a_norm, d_b_norm), max(d_a_norm, d_b_norm))

        # Filter patterns matching this domain pair
        pair_patterns: list[dict[str, Any]] = []
        for p in patterns:
            p_a = str(p.get("domain_hint") or "okänd")
            p_b = str(p.get("domain_hint_B") or p_a)
            p_pair = (min(p_a, p_b), max(p_a, p_b))
            if p_pair == pair_key:
                pair_patterns.append(p)

        # Prior: unexplored pair = moderate empowerment (curiosity bonus)
        if not pair_patterns:
            return 0.4

        # Calculate effectiveness
        successes = [p for p in pair_patterns if p.get("externally_confirmed", False)]
        attempts = len(pair_patterns)

        if attempts == 0:
            return 0.4

        effectiveness = len(successes) / attempts

        # Recency weight: newer successes = stronger signal
        def _recency_weight(success_list: list[dict[str, Any]]) -> float:
            if not success_list:
                return 0.5  # Neutral if no confirmed successes yet
            # Use most recent success timestamp
            most_recent = max(
                str(p.get("ts") or "1970-01-01T00:00:00") for p in success_list
            )
            try:
                from datetime import datetime
                recent_dt = datetime.fromisoformat(most_recent.replace("Z", "+00:00"))
                now_dt = datetime.now(timezone.utc)
                age_hours = (now_dt - recent_dt).total_seconds() / 3600
                # Decay: 1.0 at age 0, ~0.5 at 24h, ~0.25 at 48h
                import math
                return 1.0 / (1.0 + math.log1p(max(0, age_hours)))
            except Exception:
                return 0.5

        recency_weight = _recency_weight(successes)

        # Cross-domain bonus: bisociation premium
        cross_domain_bonus = 1.3 if d_a_norm != d_b_norm else 1.0

        # Rigidity penalty: approaching k_sweet reduces empowerment
        # (simplified: reduce signal if many attempts already)
        if attempts > 20:
            rigidity_penalty = 0.7
        elif attempts > 10:
            rigidity_penalty = 0.85
        else:
            rigidity_penalty = 1.0

        # Calculate final empowerment signal
        raw = effectiveness * recency_weight * cross_domain_bonus * rigidity_penalty
        return float(max(0.0, min(1.0, raw)))

    def audit(self, *, limit: int = 20) -> dict[str, Any]:
        episodes = self._load_episodes()
        uncon = [e for e in episodes if not bool(e.get("consolidated"))]
        working = self._load_working()
        semantic = self._load_semantic()
        procedural = self._load_procedural()

        relation_types = dict(procedural.get("relation_type_counts") or {})
        top_types = sorted(relation_types.items(), key=lambda kv: int(kv[1]), reverse=True)[:10]
        source_counts = dict(procedural.get("source_counts") or {})
        top_sources = sorted(source_counts.items(), key=lambda kv: int(kv[1]), reverse=True)[:10]

        safe_limit = max(1, int(limit))
        uncon_preview = [
            {
                "id": str(e.get("id") or ""),
                "ts": str(e.get("ts") or ""),
                "source": str(e.get("source") or ""),
                "domain_hint": str(e.get("domain_hint") or ""),
                "relation_count": int(e.get("relation_count", 0) or 0),
            }
            for e in uncon[:safe_limit]
        ]

        return {
            "paths": {
                "root": str(self.root),
                "working": str(self.working_path),
                "episodic": str(self.episodes_path),
                "semantic": str(self.semantic_path),
                "procedural": str(self.procedural_path),
            },
            "episodes_total": len(episodes),
            "unconsolidated_total": len(uncon),
            "working_items": len(working.get("items") or []),
            "semantic_facts": len((semantic.get("facts") or {})),
            "semantic_dialogue_facts": len((semantic.get("dialogue_facts") or {})),
            "semantic_concepts": len((semantic.get("concepts") or {})),
            "top_relation_types": [{"type": k, "count": int(v)} for k, v in top_types],
            "top_sources": [{"source": k, "count": int(v)} for k, v in top_sources],
            "unconsolidated_preview": uncon_preview,
            "updated": _now_iso(),
        }
