"""REFLEKTORN — read-only kandidatreflektion över Field-grafen (task #12).

Kontrakt (får inte brytas):
- authority=read på grafen: endast SELECT-läsning via FieldSurface
  read-metoder (stats, query_all_relations_with_metadata,
  get_concepts_with_metadata, dormant_concepts, neighbors, ...).
  Aldrig INSERT/UPDATE/DELETE, aldrig strengthen/weaken/bump/promote.
- Skriver ENDAST sin egen append-only loggfil (prognos före visning,
  utfall efter). Ändrar ingen policy/auktoritet.
- Max 5 förslag. Tystnad hellre än osäkert förslag.
- Inga modellanrop: deterministiska heuristiker (gateway finns inte ännu).
- Ingen daemon-koppling, ingen timer, ingen auto-körning.
  Förslagsrätt endast (A-004). ledger-executor: agent:reflector.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

EXECUTOR = "agent:reflector"

#: Hårt tak: aldrig fler förslag än så, oavsett anroparens limit.
MAX_SUGGESTIONS = 5

#: Högsta tillåtna konfidens för en kandidat (kalibrerad lågt, utan modell).
MAX_CONFIDENCE = 0.6

#: Relevansgolv: kandidater under detta tröskelvärde visas aldrig.
#: Tomt är ärligt — under golvet returneras [] + loggad tystnad.
MIN_CONFIDENCE = 0.25

OUTCOME_VERDICTS = frozenset({"keep", "refute"})


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_log_path() -> Path:
    """Default-logg under NOUSE_HOME (aldrig hårdkodad hemkatalog här)."""
    from nouse.config.paths import nouse_home_root

    return nouse_home_root() / "reflector_log.jsonl"


def _resolve_log_path(log_path: str | os.PathLike | None) -> Path:
    if log_path is not None:
        return Path(log_path).expanduser()
    return default_log_path()


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def read_log(log_path: str | os.PathLike) -> list[dict]:
    """Läs (aldrig skriv) prognos-/utfallshistoriken. Read-only helper."""
    path = Path(log_path).expanduser()
    if not path.exists():
        return []
    entries = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


# ── Read-only grafavläsning ──────────────────────────────────────────────
# Endast rena SELECT-getters. Listan nedan är avsiktligt sluten: om en
# metod saknas på fältobjektet hoppas det steget över i stället för att
# falla tillbaka på privata (_sql/_G) eller skrivande metoder.

def _read_stats(field) -> dict:
    stats = field.stats()
    return {
        "concepts": int(stats.get("concepts", 0)),
        "relations": int(stats.get("relations", 0)),
    }


def _read_relations(field, cap: int = 5000) -> list[dict]:
    """Alla relationer med metadata (inkl. id) via read-only getter."""
    getter = getattr(field, "query_all_relations_with_metadata", None)
    if getter is None:
        fallback = getattr(field, "query_all_relations", None)
        if fallback is None:
            return []
        rows = fallback(limit=cap) or []
        return [
            {
                "id": None,
                "src": r.get("src"),
                "type": r.get("rel_type", r.get("type")),
                "tgt": r.get("tgt"),
                "strength": r.get("strength"),
                "evidence_score": None,
            }
            for r in rows
        ]
    try:
        rows = getter(limit=cap, include_evidence=True) or []
    except TypeError:
        rows = getter() or []
    out = []
    for r in rows:
        out.append({
            "id": r.get("id"),
            "src": r.get("src"),
            "type": r.get("rel", r.get("type")),
            "tgt": r.get("tgt"),
            "strength": r.get("strength"),
            "evidence_score": r.get("evidence_score"),
            "why": r.get("why", ""),
        })
    return out


def _read_concepts(field, cap: int = 5000) -> list[dict]:
    getter = getattr(field, "get_concepts_with_metadata", None)
    if getter is None:
        names_getter = getattr(field, "concepts", None)
        if names_getter is None:
            return []
        return [{"id": r.get("name"), "dom": r.get("domain", ""),
                 "dormant_since": None} for r in (names_getter() or [])]
    rows = getter(limit=cap) or []
    return [
        {"id": r.get("id"), "dom": r.get("dom") or "",
         "dormant_since": r.get("dormant_since")}
        for r in rows
    ]


def _read_dormant(field, cap: int = 200) -> list[dict]:
    getter = getattr(field, "dormant_concepts", None)
    if getter is None:
        return []
    try:
        rows = getter(limit=cap) or []
    except TypeError:
        rows = getter() or []
    return [{"name": r.get("name"), "domain": r.get("domain") or ""}
            for r in rows]


# ── Deterministiska kandidatheurstiker (ingen modell) ────────────────────

def _candidate(kind: str, summary: str, refs: list,
               confidence: float, reason: str, alternates: list[str]) -> dict:
    return {
        "kind": kind,
        "summary": summary,
        "refs": list(refs),
        "confidence": min(float(confidence), MAX_CONFIDENCE),
        "reason": reason,
        "alternates": list(alternates),
    }


def _isolated_candidates(concepts, relations, domains: dict) -> list[dict]:
    """Lösa noder utan cross-domain-koppling."""
    linked: dict[str, set[str]] = {}
    for rel in relations:
        for node in (rel["src"], rel["tgt"]):
            if node:
                linked.setdefault(node, set())
        if rel["src"] and rel["tgt"]:
            linked[rel["src"]].add(rel["tgt"])
            linked[rel["tgt"]].add(rel["src"])
    out = []
    for concept in sorted(concepts):
        nbrs = linked.get(concept, set())
        if len(nbrs) > 1:
            continue
        dom = domains.get(concept, "")
        cross = {domains.get(n, "") for n in nbrs} - {dom, ""}
        if cross:
            continue  # har cross-domain-koppling: inte lös
        if not nbrs:
            reason = f"'{concept}' saknar helt kopplingar (grad 0)."
        else:
            only = sorted(nbrs)[0]
            reason = (f"'{concept}' har endast en koppling (till '{only}') "
                      f"och ingen cross-domain-brygga.")
        out.append(_candidate(
            kind="isolated_node",
            summary=f"Lös nod utan cross-domain-koppling: {concept}",
            refs=[],
            confidence=0.30,
            reason=reason,
            alternates=[
                f"'{concept}' kan vara avsiktligt avgränsad — isolering "
                f"är inte alltid en brist.",
                f"'{concept}' kan höra hemma i ett material som ännu inte "
                f"fångats; kolla inbox innan länkning.",
            ],
        ))
    return out


def _cooccurrence_candidates(concepts, relations) -> list[dict]:
    """Starka samförekomstpar utan direkt relation.

    Par som delar >= 2 gemensamma grannar men saknar direkt kant:
    möjlig saknad länk. Deterministiskt (sorterad iteration).
    """
    succ: dict[str, set[str]] = {}
    for rel in relations:
        if rel["src"] and rel["tgt"]:
            succ.setdefault(rel["src"], set()).add(rel["tgt"])
            succ.setdefault(rel["tgt"], set()).add(rel["src"])
    direct = {frozenset((r["src"], r["tgt"])) for r in relations
              if r["src"] and r["tgt"]}
    names = sorted(concepts)
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if frozenset((a, b)) in direct:
                continue
            shared = sorted(succ.get(a, set()) & succ.get(b, set()))
            if len(shared) < 2:
                continue
            out.append(_candidate(
                kind="cooccurrence_gap",
                summary=f"Möjlig saknad länk: {a} — {b} "
                        f"(delar {len(shared)} grannar)",
                refs=[],
                confidence=0.35,
                reason=(f"'{a}' och '{b}' delar grannarna "
                        f"{', '.join(shared[:4])} men saknar direkt relation."),
                alternates=[
                    f"Paret kan vara indirekt relaterat via grannarna — "
                    f"ingen direkt länk behövs.",
                    f"Gemensamma grannar kan vara tillfälliga (samma "
                    f"källa, olika sak); verifiera mot källmaterial.",
                ],
            ))
    return out


def _contradiction_candidates(relations) -> list[dict]:
    """Motsägelsekandidater: delade grannar med olika rel_type.

    Två olika källor som relaterar till samma mål med olika
    relationstyper kan signalera divergerande beskrivningar.
    """
    by_target: dict[str, dict[str, set[str]]] = {}
    for rel in relations:
        if not rel["src"] or not rel["tgt"] or not rel["type"]:
            continue
        by_target.setdefault(rel["tgt"], {}).setdefault(
            rel["type"], set()).add(rel["src"])
    out = []
    for tgt in sorted(by_target):
        types = sorted(by_target[tgt])
        if len(types) < 2:
            continue
        # Deterministiskt: första två typerna alfabetiskt.
        t1, t2 = types[0], types[1]
        s1 = sorted(by_target[tgt][t1])[0]
        s2 = sorted(by_target[tgt][t2])[0]
        if s1 == s2:
            continue
        out.append(_candidate(
            kind="contradiction_candidate",
            summary=f"Divergerande typing mot '{tgt}': {t1} vs {t2}",
            refs=[],
            confidence=0.30,
            reason=(f"'{s1}' relaterar till '{tgt}' som '{t1}' medan "
                    f"'{s2}' relaterar till samma mål som '{t2}'."),
            alternates=[
                f"Typerna kan vara komplementära snarare än motsägande "
                f"(olika aspekter av '{tgt}').",
                f"En av typningarna kan vara föråldrad — kontrollera "
                f"proveniens innan slutsats.",
            ],
        ))
    return out


def _dormant_candidates(field, dormant: list[dict]) -> list[dict]:
    """Vilande koncept som återaktiverats (dormant men med grad > 0)."""
    neighbors = getattr(field, "neighbors", None)
    out = []
    for row in sorted(dormant, key=lambda r: r["name"] or ""):
        name = row["name"]
        if not name:
            continue
        degree = 0
        if neighbors is not None:
            try:
                degree = len(neighbors(name, limit=5000, bidirectional=True) or [])
            except TypeError:
                degree = len(neighbors(name) or [])
        if degree == 0:
            continue  # fortfarande vilande: ingen signal
        out.append(_candidate(
            kind="dormant_reactivated",
            summary=f"Vilande koncept med ny aktivitet: {name} ({degree} grannar)",
            refs=[],
            confidence=0.30,
            reason=(f"'{name}' är markerat dormant_since men har "
                    f"{degree} grannar — möjlig återaktivering."),
            alternates=[
                f"Aktiviteten kan vara brus (svaga/legacy-kanter) — "
                f"granska kantstyrkor först.",
                f"Konceptet kan ha väckts av misstag via en bred "
                f"fångst; överväg återtystnad.",
            ],
        ))
    return out


# ── Publik API ───────────────────────────────────────────────────────────

def reflect(field, *, limit: int = 5, log_path=None) -> list[dict]:
    """Läs grafen (read-only), returnera max `limit` förslagskandidater.

    Prognosraden append:as till loggen FÖRE return. Vid tom/irrelevant
    graf returneras [] och tystnaden loggas (samma princip som Field:
    tomt är ärligt). Rör aldrig grafen, policyn eller auktoriteter.
    """
    try:
        effective_limit = max(0, min(int(limit), MAX_SUGGESTIONS))
    except (TypeError, ValueError):
        effective_limit = MAX_SUGGESTIONS

    log = _resolve_log_path(log_path)
    entry_id = uuid.uuid4().hex
    now = _utcnow_iso()

    counts = _read_stats(field)
    relations = _read_relations(field)
    concepts_meta = _read_concepts(field)
    concepts = [c["id"] for c in concepts_meta if c["id"]]
    domains = {c["id"]: c["dom"] for c in concepts_meta if c["id"]}
    dormant = _read_dormant(field)

    rel_ids = sorted(r["id"] for r in relations if r["id"] is not None)
    fingerprint = {
        "concepts": counts["concepts"],
        "relations": counts["relations"],
        "latest_ids": rel_ids[-10:],
    }

    candidates: list[dict] = []
    silence_reason = ""
    if counts["relations"] == 0 or len(concepts) < 2:
        silence_reason = (
            "tom/irrelevant graf: "
            f"{counts['concepts']} koncept, {counts['relations']} relationer "
            "(under relevansgolvet)"
        )
    else:
        pool: list[dict] = []
        pool.extend(_isolated_candidates(set(concepts), relations, domains))
        pool.extend(_cooccurrence_candidates(set(concepts), relations))
        pool.extend(_contradiction_candidates(relations))
        pool.extend(_dormant_candidates(field, dormant))
        # Relevansgolv + deterministisk ordning + tak.
        pool = [c for c in pool if c["confidence"] >= MIN_CONFIDENCE]
        pool.sort(key=lambda c: (-c["confidence"], c["kind"], c["summary"]))
        candidates = pool[:effective_limit]
        if not candidates:
            silence_reason = (
                "inga kandidater nådde relevansgolvet "
                f"(min {MIN_CONFIDENCE}, pool tom efter filtrering)"
            )

    _append_jsonl(log, {
        "entry_id": entry_id,
        "time": now,
        "event": "forecast",
        "executor": EXECUTOR,
        "input_fingerprint": fingerprint,
        "candidates": [
            {"kind": c["kind"], "summary": c["summary"],
             "probability": c["confidence"], "refs": c["refs"]}
            for c in candidates
        ],
        "silence": not candidates,
        "silence_reason": silence_reason,
    })
    return candidates


def record_outcome(log_path, entry_id: str, verdict: str, reason: str) -> dict:
    """Append:a ett utfall (keep/refute + skäl) utan att mutera historik.

    Svar utan skäl avvisas (ValueError). Skriver aldrig om tidigare rader.
    """
    if verdict not in OUTCOME_VERDICTS:
        raise ValueError(
            f"verdict måste vara en av {sorted(OUTCOME_VERDICTS)}, fick {verdict!r}"
        )
    clean_reason = str(reason or "").strip()
    if not clean_reason:
        raise ValueError("outcome kräver ett skäl (tom reason avvisas)")
    clean_id = str(entry_id or "").strip()
    if not clean_id:
        raise ValueError("outcome kräver ett entry_id")
    log = _resolve_log_path(log_path)
    record = {
        "entry_id": clean_id,
        "time": _utcnow_iso(),
        "event": "outcome",
        "executor": EXECUTOR,
        "verdict": verdict,
        "reason": clean_reason,
    }
    _append_jsonl(log, record)
    return record
