from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nouse.config.paths import path_from_env
from nouse.field.surface import FieldSurface


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _tier(score: float, evidence: float, support: int) -> str:
    if score >= 0.72 and evidence >= 0.70 and support >= 2:
        return "validerad"
    if score >= 0.52 and evidence >= 0.52:
        return "indikation"
    return "hypotes"


def _insight_id(parts: list[str]) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _normalize_relation_rows(
    field: FieldSurface,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    rows = field.query_all_relations_with_metadata(limit=limit, include_evidence=True)
    if not rows:
        return []

    names: set[str] = set()
    for row in rows:
        src = str(row.get("src") or "").strip()
        tgt = str(row.get("tgt") or "").strip()
        if src:
            names.add(src)
        if tgt:
            names.add(tgt)

    domains: dict[str, str] = {}
    for name in names:
        domains[name] = str(field.concept_domain(name) or "okänd")

    out: list[dict[str, Any]] = []
    for row in rows:
        src = str(row.get("src") or "").strip()
        rel = str(row.get("rel") or "").strip()
        tgt = str(row.get("tgt") or "").strip()
        if not src or not rel or not tgt:
            continue
        strength = _safe_float(row.get("strength"), default=0.0)
        ev = _safe_float(row.get("evidence_score"), default=strength if strength > 0.0 else 0.35)
        why = str(row.get("why") or "").strip()
        out.append(
            {
                "src": src,
                "rel": rel,
                "tgt": tgt,
                "strength": _clamp01(strength),
                "evidence": _clamp01(ev),
                "why": why,
                "src_domain": domains.get(src, "okänd"),
                "tgt_domain": domains.get(tgt, "okänd"),
                "created": str(row.get("created") or ""),
            }
        )
    return out


def _make_relation_ref(row: dict[str, Any]) -> str:
    src = str(row.get("src") or "").strip()
    rel = str(row.get("rel") or "").strip()
    tgt = str(row.get("tgt") or "").strip()
    ev = _clamp01(_safe_float(row.get("evidence"), default=0.0))
    created = str(row.get("created") or "").strip()
    base = f"relation_edge:{src}|{rel}|{tgt}:ev={ev:.2f}"
    if created:
        return f"{base}:ts={created[:19]}"
    return base


def _relation_candidates(
    rows: list[dict[str, Any]],
    *,
    min_evidence: float,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["src"], row["rel"], row["tgt"])
        item = groups.get(key)
        if item is None:
            item = {
                "src": row["src"],
                "rel": row["rel"],
                "tgt": row["tgt"],
                "src_domain": row["src_domain"],
                "tgt_domain": row["tgt_domain"],
                "support": 0,
                "ev_sum": 0.0,
                "max_ev": 0.0,
                "strength_sum": 0.0,
                "why_samples": [],
                "rows": [],
            }
            groups[key] = item

        item["support"] += 1
        item["ev_sum"] += row["evidence"]
        item["max_ev"] = max(float(item["max_ev"]), float(row["evidence"]))
        item["strength_sum"] += row["strength"]
        why = str(row.get("why") or "").strip()
        if why and why not in item["why_samples"]:
            item["why_samples"].append(why[:220])
        if len(item["rows"]) < 8:
            item["rows"].append(
                {
                    "src": row["src"],
                    "rel": row["rel"],
                    "tgt": row["tgt"],
                    "evidence": round(float(row["evidence"]), 4),
                    "strength": round(float(row["strength"]), 4),
                    "why": why[:220] if why else "",
                    "src_domain": row["src_domain"],
                    "tgt_domain": row["tgt_domain"],
                    "created": str(row.get("created") or ""),
                }
            )

    out: list[dict[str, Any]] = []
    for item in groups.values():
        support = int(item["support"])
        mean_ev = float(item["ev_sum"]) / max(1, support)
        if mean_ev < min_evidence and support < 2:
            continue
        support_norm = min(1.0, support / 3.0)
        cross_domain = (
            item["src_domain"] != "okänd"
            and item["tgt_domain"] != "okänd"
            and item["src_domain"] != item["tgt_domain"]
        )
        novelty = 0.85 if cross_domain else 0.45
        actionability = _clamp01(
            0.25
            + 0.45 * support_norm
            + 0.20 * (1.0 if item["why_samples"] else 0.0)
            + 0.10 * (1.0 if cross_domain else 0.0)
        )
        score = _clamp01(
            0.45 * mean_ev
            + 0.25 * support_norm
            + 0.20 * novelty
            + 0.10 * actionability
        )
        tier = _tier(score, mean_ev, support)
        score_components = {
            "evidence": round(mean_ev, 4),
            "support": round(support_norm, 4),
            "novelty": round(novelty, 4),
            "actionability": round(actionability, 4),
        }
        sample_rows = list(item["rows"])[:5]
        refs_seen: set[str] = set()
        basis_evidence_refs: list[str] = []
        for sample in sample_rows:
            ref = _make_relation_ref(sample)
            if ref in refs_seen:
                continue
            refs_seen.add(ref)
            basis_evidence_refs.append(ref)
        for why in (item.get("why_samples") or [])[:2]:
            ref = f"why:{why[:120]}"
            if ref in refs_seen:
                continue
            refs_seen.add(ref)
            basis_evidence_refs.append(ref)
        statement = (
            f"{item['src']} --[{item['rel']}]--> {item['tgt']} "
            f"(ev={mean_ev:.2f}, support={support})"
        )
        insight_id = _insight_id(
            [
                "relation_pattern",
                item["src"],
                item["rel"],
                item["tgt"],
                f"{support}",
                f"{mean_ev:.3f}",
            ]
        )
        out.append(
            {
                "kind": "relation_pattern",
                "insight_id": insight_id,
                "anchor": item["src"],
                "statement": statement,
                "score": round(score, 4),
                "tier": tier,
                "support": support,
                "mean_evidence": round(mean_ev, 4),
                "max_evidence": round(float(item["max_ev"]), 4),
                "novelty": round(novelty, 4),
                "actionability": round(actionability, 4),
                "cross_domain": cross_domain,
                "src": item["src"],
                "rel": item["rel"],
                "tgt": item["tgt"],
                "src_domain": item["src_domain"],
                "tgt_domain": item["tgt_domain"],
                "why_samples": list(item["why_samples"])[:3],
                "basis": {
                    "method": "relation_grouping",
                    "support_rows": support,
                    "distinct_why": len(item["why_samples"]),
                    "sample_rows": sample_rows,
                    "score_components": score_components,
                },
                "basis_evidence_refs": basis_evidence_refs[:12],
                "related_terms": [
                    item["src"],
                    item["rel"],
                    item["tgt"],
                    item["src_domain"],
                    item["tgt_domain"],
                ],
                "created_at": _now_iso(),
            }
        )

    out.sort(
        key=lambda x: (
            float(x.get("score", 0.0)),
            float(x.get("mean_evidence", 0.0)),
            int(x.get("support", 0)),
        ),
        reverse=True,
    )
    return out


def _bridge_candidates(
    rows: list[dict[str, Any]],
    *,
    min_evidence: float,
) -> list[dict[str, Any]]:
    by_src: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if float(row["evidence"]) >= min_evidence:
            by_src[row["src"]].append(row)

    out: list[dict[str, Any]] = []
    for src, edges in by_src.items():
        if len(edges) < 3:
            continue
        src_domain = str(edges[0].get("src_domain") or "okänd")
        tgt_domains = sorted(
            {
                str(edge.get("tgt_domain") or "okänd")
                for edge in edges
                if str(edge.get("tgt_domain") or "okänd") != "okänd"
            }
        )
        if len(tgt_domains) < 2:
            continue
        rel_types = sorted({str(edge.get("rel") or "") for edge in edges if str(edge.get("rel") or "")})
        mean_ev = sum(float(edge["evidence"]) for edge in edges) / max(1, len(edges))
        support_norm = min(1.0, len(edges) / 8.0)
        breadth_norm = min(1.0, len(tgt_domains) / 4.0)
        novelty = _clamp01(0.55 + 0.45 * breadth_norm)
        actionability = _clamp01(
            0.30
            + 0.35 * support_norm
            + 0.20 * (1.0 if len(rel_types) > 1 else 0.0)
            + 0.15 * (1.0 if src_domain != "okänd" else 0.0)
        )
        score = _clamp01(
            0.40 * mean_ev
            + 0.20 * support_norm
            + 0.25 * novelty
            + 0.15 * actionability
        )
        ranked_edges = sorted(edges, key=lambda edge: float(edge.get("evidence", 0.0)), reverse=True)
        sample_rows = [
            {
                "src": str(edge.get("src") or ""),
                "rel": str(edge.get("rel") or ""),
                "tgt": str(edge.get("tgt") or ""),
                "evidence": round(float(edge.get("evidence", 0.0) or 0.0), 4),
                "strength": round(float(edge.get("strength", 0.0) or 0.0), 4),
                "why": str(edge.get("why") or "")[:220],
                "src_domain": str(edge.get("src_domain") or "okänd"),
                "tgt_domain": str(edge.get("tgt_domain") or "okänd"),
                "created": str(edge.get("created") or ""),
            }
            for edge in ranked_edges[:6]
        ]
        score_components = {
            "evidence": round(mean_ev, 4),
            "support": round(support_norm, 4),
            "novelty": round(novelty, 4),
            "actionability": round(actionability, 4),
        }
        refs_seen: set[str] = set()
        basis_evidence_refs: list[str] = []
        for sample in sample_rows:
            ref = _make_relation_ref(sample)
            if ref in refs_seen:
                continue
            refs_seen.add(ref)
            basis_evidence_refs.append(ref)
        tier = _tier(score, mean_ev, len(edges))
        statement = (
            f"{src} fungerar som domänbro från {src_domain} till "
            f"{', '.join(tgt_domains[:3])} via {', '.join(rel_types[:3])}."
        )
        insight_id = _insight_id(
            [
                "domain_bridge",
                src,
                src_domain,
                ",".join(tgt_domains),
                f"{len(edges)}",
                f"{mean_ev:.3f}",
            ]
        )
        out.append(
            {
                "kind": "domain_bridge",
                "insight_id": insight_id,
                "anchor": src,
                "statement": statement,
                "score": round(score, 4),
                "tier": tier,
                "support": len(edges),
                "mean_evidence": round(mean_ev, 4),
                "max_evidence": round(max(float(edge["evidence"]) for edge in edges), 4),
                "novelty": round(novelty, 4),
                "actionability": round(actionability, 4),
                "cross_domain": True,
                "src": src,
                "rel": "domain_bridge",
                "tgt": ",".join(tgt_domains[:3]),
                "src_domain": src_domain,
                "tgt_domain": ",".join(tgt_domains),
                "why_samples": [],
                "basis": {
                    "method": "domain_bridge_detection",
                    "support_rows": len(edges),
                    "distinct_domains": len(tgt_domains),
                    "sample_rows": sample_rows,
                    "score_components": score_components,
                },
                "basis_evidence_refs": basis_evidence_refs[:14],
                "related_terms": [src, src_domain, *tgt_domains[:4], *rel_types[:4]],
                "created_at": _now_iso(),
            }
        )

    out.sort(
        key=lambda x: (
            float(x.get("score", 0.0)),
            float(x.get("mean_evidence", 0.0)),
            int(x.get("support", 0)),
        ),
        reverse=True,
    )
    return out


def extract_insight_candidates(
    field: FieldSurface,
    *,
    limit: int = 8000,
    top_k: int = 12,
    min_evidence: float = 0.52,
    include_bridges: bool = True,
) -> dict[str, Any]:
    safe_limit = max(100, min(int(limit), 50000))
    safe_top_k = max(1, min(int(top_k), 200))
    safe_min_ev = _clamp01(float(min_evidence))

    rows = _normalize_relation_rows(field, limit=safe_limit)
    relation_candidates = _relation_candidates(rows, min_evidence=safe_min_ev)
    bridge_candidates: list[dict[str, Any]] = []
    if include_bridges:
        bridge_candidates = _bridge_candidates(rows, min_evidence=safe_min_ev)

    selected: list[dict[str, Any]] = []
    relation_quota = max(1, int(round(safe_top_k * (0.7 if include_bridges else 1.0))))
    bridge_quota = max(0, safe_top_k - relation_quota)

    selected.extend(relation_candidates[:relation_quota])
    if include_bridges and bridge_quota > 0:
        selected.extend(bridge_candidates[:bridge_quota])

    if len(selected) < safe_top_k:
        used_ids = {str(item.get("insight_id") or "") for item in selected}
        for candidate in relation_candidates + bridge_candidates:
            cid = str(candidate.get("insight_id") or "")
            if cid in used_ids:
                continue
            selected.append(candidate)
            used_ids.add(cid)
            if len(selected) >= safe_top_k:
                break

    selected.sort(
        key=lambda x: (
            float(x.get("score", 0.0)),
            float(x.get("mean_evidence", 0.0)),
            int(x.get("support", 0)),
        ),
        reverse=True,
    )

    return {
        "generated_at": _now_iso(),
        "total_relation_rows": len(rows),
        "relation_candidates": len(relation_candidates),
        "bridge_candidates": len(bridge_candidates),
        "selected_count": len(selected),
        "min_evidence": safe_min_ev,
        "candidates": selected,
    }


def save_insight_candidates(
    candidates: list[dict[str, Any]],
    *,
    destination: str | Path | None = None,
    source: str = "cli:extract-insights",
) -> dict[str, Any]:
    if destination is None:
        path = path_from_env("NOUSE_MEMORY_DIR", "memory") / "insights.jsonl"
    else:
        path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    ts = _now_iso()
    for candidate in candidates:
        payload = {
            "ts": ts,
            "source": source,
            **candidate,
        }
        lines.append(json.dumps(payload, ensure_ascii=False))

    if lines:
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    return {"path": str(path), "written": len(lines)}


def promote_insight_candidates(
    field: FieldSurface,
    candidates: list[dict[str, Any]],
    *,
    max_items: int = 8,
    min_score: float = 0.74,
) -> dict[str, Any]:
    safe_max = max(1, min(int(max_items), 200))
    safe_min_score = _clamp01(float(min_score))

    promoted: list[dict[str, Any]] = []
    for candidate in sorted(
        candidates,
        key=lambda x: float(x.get("score", 0.0)),
        reverse=True,
    ):
        if len(promoted) >= safe_max:
            break
        score = _safe_float(candidate.get("score"), default=0.0)
        if score < safe_min_score:
            continue
        anchor = str(candidate.get("anchor") or candidate.get("src") or "").strip()
        statement = str(candidate.get("statement") or "").strip()
        if not anchor or not statement:
            continue
        tier = str(candidate.get("tier") or "hypotes").strip() or "hypotes"
        kind = str(candidate.get("kind") or "insight").strip() or "insight"
        insight_id = str(candidate.get("insight_id") or "").strip() or _insight_id(
            [kind, anchor, statement]
        )
        evidence_ref = f"insight:{kind}:{insight_id}:score={score:.2f}:tier={tier}"
        raw_refs = candidate.get("basis_evidence_refs") or []
        basis_refs = [str(x).strip() for x in raw_refs if str(x).strip()]
        related_terms = [str(x).strip() for x in (candidate.get("related_terms") or []) if str(x).strip()]
        uncertainty = round(max(0.05, 1.0 - score), 3)
        field.upsert_concept_knowledge(
            anchor,
            claim=statement,
            evidence_ref=evidence_ref,
            evidence_refs=basis_refs[:20],
            related_terms=related_terms[:10],
            uncertainty=uncertainty,
        )
        promoted.append(
            {
                "insight_id": insight_id,
                "anchor": anchor,
                "score": round(score, 4),
                "tier": tier,
            }
        )

    return {
        "requested": len(candidates),
        "promoted": len(promoted),
        "min_score": safe_min_score,
        "items": promoted,
    }
