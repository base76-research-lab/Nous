"""
NodeDeepDive — Axiom-discovery pipeline
=========================================

5-stegs pipeline som körs på en nod och letar efter underliggande
förståelse och nya axiom:

  Steg 1: LLM-kunskapsverifiering
    → "Vad vet LLM om denna nod baserat på träningsdata?"
    → Jämför med vad grafen säger — hitta luckor och möjliga fel

  Steg 2: Webb-korscheck
    → Sök aktuell data via Brave/DDG/Serper
    → Verifiera befintliga claims, hitta ny information
    → Uppdatera evidence_score på berörda relationer

  Steg 3: Claim-kontrastering
    → Leta motsägelser i grafen (A säger X, B säger ¬X)
    → Flagga motstridiga noder med assumption_flag

  Steg 4: Korrelationsanalys
    → Hitta noder med strukturellt liknande relationssmönster
    → Identifiera "shadow nodes" — noder som beter sig identiskt
      men aldrig är explicit kopplade

  Steg 5: Axiom-kandidater
    → Mönster som upprepas i grafen → generalisera till axiom
    → Starka (ev >= 0.75): skrivs direkt till FieldSurface
    → Svaga (ev < 0.75): flaggas för granskning (assumption_flag=True)

Autonom policy:
  - Starka axiom: läggs in direkt
  - Svaga / kontroversiella: assumption_flag=True, hamnar i ReviewQueue

ReviewQueue — Indikerad granskning (minnerekonsolidering):
  Varje gång ett flaggat axiom traverseras (i queries, path-finding,
  nya relationer) registreras en "indikation". När hit-count når
  REVIEW_INDICATION_THRESHOLD triggas deep_review_axiom():

    Deep review:
      A. Devil's advocate  — LLM argumenterar MOT axiom
      B. Multi-source webb — 10 resultat, kräver 3+ träffar
      C. Graf-korroboration — 2-hop grannars stöd
      D. Majority vote     — 3 LLM-anrop, röstning

    Utfall:
      PROMOTE  → assumption_flag=False, evidence_score höjs (+0.15)
      KEEP     → stannar flaggad, hit-counter nollställs
      DISCARD  → markeras för pruning (evidence_score=0.0)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nouse.field.surface import FieldSurface

_log = logging.getLogger("nouse.deepdive")

AXIOM_STRONG_THRESHOLD      = 0.75   # läggs in direkt
AXIOM_WEAK_THRESHOLD        = 0.45   # flaggas för granskning
MAX_WEB_RESULTS             = 5
MAX_WEB_RESULTS_DEEP        = 10     # djup granskning
MAX_CORRELATION_HOPS        = 3
MAX_SHADOW_NODES            = 10
REVIEW_INDICATION_THRESHOLD = 3      # antal indikationer → trigger deep review
DEEP_REVIEW_VOTE_ROUNDS     = 3      # antal LLM-röster i majority vote


# ── Datamodeller ──────────────────────────────────────────────────────────────

@dataclass
class AxiomCandidate:
    src:            str
    rel_type:       str
    tgt:            str
    why:            str
    evidence_score: float
    source:         str           # "llm_training" | "web" | "correlation" | "contradiction"
    auto_commit:    bool          # True = stark nog att lägga in direkt
    assumption_flag: bool         # True = osäker, kräver granskning


@dataclass
class DeepDiveResult:
    node:              str
    llm_verified:      list[str]  = dc_field(default_factory=list)
    llm_challenged:    list[str]  = dc_field(default_factory=list)
    web_new_facts:     list[str]  = dc_field(default_factory=list)
    contradictions:    list[str]  = dc_field(default_factory=list)
    shadow_nodes:      list[str]  = dc_field(default_factory=list)
    axiom_candidates:  list[AxiomCandidate] = dc_field(default_factory=list)
    committed:         int  = 0
    flagged:           int  = 0
    duration:          float = 0.0


@dataclass
class DeepDiveBatch:
    nodes_processed: int   = 0
    total_committed: int   = 0
    total_flagged:   int   = 0
    duration:        float = 0.0
    results:         list[DeepDiveResult] = dc_field(default_factory=list)


# Utfall från djup granskning
REVIEW_PROMOTE = "promote"
REVIEW_KEEP    = "keep"
REVIEW_DISCARD = "discard"


@dataclass
class ReviewVerdict:
    key:           str    # "{src}||{rel_type}||{tgt}"
    outcome:       str    # REVIEW_PROMOTE | REVIEW_KEEP | REVIEW_DISCARD
    new_score:     float
    rationale:     str
    votes_for:     int = 0
    votes_against: int = 0


# ── ReviewQueue — indikerad granskning (minnerekonsolidering) ─────────────────

class ReviewQueue:
    """
    Spårar hur ofta flaggade axiom refereras ("indikeras").
    När hit-count >= REVIEW_INDICATION_THRESHOLD triggas deep_review_axiom().

    Analogin: ett svagt minne som aktiveras upprepade gånger genomgår
    rekonsolidering — det antingen stärks eller kasseras.

    Singleton per process, thread-safe via asyncio.Lock.
    Persisteras till JSONL i b76 data-dir för att överleva daemon-restart.
    """

    _instance: "ReviewQueue | None" = None

    def __init__(self) -> None:
        self._hits: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()
        self._pending_review: list[str] = []   # keys väntande på djup granskning
        self._state_file = (
            Path.home() / ".local" / "share" / "nouse" / "review_queue.json"
        )
        self._load()

    @classmethod
    def get(cls) -> "ReviewQueue":
        if cls._instance is None:
            cls._instance = ReviewQueue()
        return cls._instance

    def _load(self) -> None:
        try:
            if self._state_file.exists():
                data = json.loads(self._state_file.read_text())
                self._hits = defaultdict(int, data.get("hits", {}))
                self._pending_review = data.get("pending", [])
        except Exception as e:
            _log.debug("ReviewQueue load misslyckades: %s", e)

    def _save(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps({
                "hits":    dict(self._hits),
                "pending": self._pending_review,
            }))
        except Exception as e:
            _log.debug("ReviewQueue save misslyckades: %s", e)

    @staticmethod
    def _key(src: str, rel_type: str, tgt: str) -> str:
        return f"{src}||{rel_type}||{tgt}"

    async def indicate(
        self, src: str, rel_type: str, tgt: str
    ) -> bool:
        """
        Registrera en indikation (användning) av ett flaggat axiom.
        Returnerar True om granskning ska triggas nu.
        """
        key = self._key(src, rel_type, tgt)
        async with self._lock:
            self._hits[key] += 1
            count = self._hits[key]
            _log.debug("ReviewQueue indicate: %s  hits=%d", key, count)
            if count >= REVIEW_INDICATION_THRESHOLD and key not in self._pending_review:
                self._pending_review.append(key)
                _log.info(
                    "ReviewQueue: '%s -[%s]-> %s' nått %d indikationer → kö för djup granskning",
                    src, rel_type, tgt, count,
                )
                self._save()
                return True
            self._save()
        return False

    async def flush_pending(
        self,
        field: "FieldSurface",
        *,
        max_reviews: int = 10,
        dry_run: bool = False,
    ) -> list[ReviewVerdict]:
        """
        Granska alla väntande axiom. Anropas från NightRun.
        """
        async with self._lock:
            to_review = self._pending_review[:max_reviews]
            self._pending_review = self._pending_review[max_reviews:]
            self._save()

        verdicts: list[ReviewVerdict] = []
        for key in to_review:
            parts = key.split("||", 2)
            if len(parts) != 3:
                continue
            src, rel_type, tgt = parts
            try:
                v = await deep_review_axiom(src, rel_type, tgt, field, dry_run=dry_run)
                verdicts.append(v)
                # Nollställ hit-counter efter granskning
                async with self._lock:
                    self._hits[key] = 0
                    self._save()
            except Exception as e:
                _log.warning("deep_review_axiom misslyckades för %s: %s", key, e)

        return verdicts

    def pending_count(self) -> int:
        return len(self._pending_review)

    def hit_count(self, src: str, rel_type: str, tgt: str) -> int:
        return self._hits.get(self._key(src, rel_type, tgt), 0)


def get_review_queue() -> ReviewQueue:
    return ReviewQueue.get()


# ── deep_review_axiom — 4-parts djup granskning ───────────────────────────────

async def deep_review_axiom(
    src: str,
    rel_type: str,
    tgt: str,
    field: "FieldSurface",
    *,
    dry_run: bool = False,
) -> ReviewVerdict:
    """
    Djup granskning av ett flaggat axiom vid indikerad användning.

    Del A: Devil's advocate — LLM argumenterar MOT axiom
    Del B: Multi-source webb — 10 resultat, kräver 3+ träffar
    Del C: Graf-korroboration — 2-hop grannars stöd
    Del D: Majority vote — DEEP_REVIEW_VOTE_ROUNDS LLM-röster

    Utfall:
      promote  → assumption_flag=False, evidence_score += 0.15
      keep     → stannar flaggad, hit-counter nollställs
      discard  → evidence_score=0.0, markeras för pruning
    """
    from nouse.ollama_client.client import AsyncOllama

    key = ReviewQueue._key(src, rel_type, tgt)
    _log.info("deep_review_axiom: %s -[%s]-> %s", src, rel_type, tgt)

    llm            = AsyncOllama()
    votes_for      = 0
    votes_against  = 0
    rationale_parts: list[str] = []

    # Hämta nuvarande evidence_score från grafen
    current_score  = 0.5
    try:
        ev = field.relation_evidence_score(src, rel_type, tgt)
        if ev is not None:
            current_score = ev
    except Exception:
        pass

    axiom_stmt = f"'{src}' {rel_type} '{tgt}'"

    # ── Del A: Devil's advocate ───────────────────────────────────────────────
    devil_prompt = (
        f"Du är en kritisk vetenskaplig granskare. Påstående: {axiom_stmt}\n"
        "Argumentera MOT detta påstående. Lista de starkaste motargumenten.\n"
        'Svara i JSON: {"strong_against": true/false, "arguments": ["arg1", ...]}\n'
        "strong_against=true om du tror påstående är felaktigt eller vilseledande."
    )
    try:
        resp = await llm.chat.completions.create(
            model=None,
            messages=[{"role": "user", "content": devil_prompt}],
            workload="extract",
        )
        raw  = _parse_json_response(resp.message.content or "")
        data = json.loads(raw) if raw else {}
        if data.get("strong_against"):
            votes_against += 1
            args = "; ".join(str(a) for a in data.get("arguments", [])[:2])
            rationale_parts.append(f"Motargument: {args}")
            _log.debug("  [A] Devil's advocate: MOT  args=%s", args[:80])
        else:
            votes_for += 1
            _log.debug("  [A] Devil's advocate: FÖR")
    except Exception as e:
        _log.debug("  [A] Devil's advocate misslyckades: %s", e)

    # ── Del B: Multi-source webb ──────────────────────────────────────────────
    try:
        from nouse.mcp_gateway.gateway import web_search
        query   = f"{src.replace('_', ' ')} {rel_type} {tgt.replace('_', ' ')}"
        result  = await asyncio.get_event_loop().run_in_executor(
            None, lambda: web_search(query, max_results=MAX_WEB_RESULTS_DEEP)
        )
        snippets = [
            str(r.get("snippet") or r.get("body") or "")
            for r in result.get("results", [])
        ]
        keywords = (
            [w for w in src.lower().split("_") if len(w) > 3]
            + [w for w in tgt.lower().split("_") if len(w) > 3]
        )
        web_hits = sum(
            1 for s in snippets
            if any(kw in s.lower() for kw in keywords)
        )
        if web_hits >= 3:
            votes_for += 1
            rationale_parts.append(f"Webb: {web_hits} källor stöder axiom")
            _log.debug("  [B] Webb: %d träffar → FÖR", web_hits)
        elif web_hits == 0:
            votes_against += 1
            rationale_parts.append("Webb: ingen källa stöder axiom")
            _log.debug("  [B] Webb: 0 träffar → MOT")
        else:
            _log.debug("  [B] Webb: %d träffar → neutral", web_hits)
    except Exception as e:
        _log.debug("  [B] Webb misslyckades: %s", e)

    # ── Del C: Graf-korroboration ─────────────────────────────────────────────
    try:
        # Hitta grannar 2 hopp bort — stöder de liknande relationer?
        neighbors_src = [r.get("target") for r in field.out_relations(src)[:6]]
        neighbors_tgt = [r.get("source") for r in field._in_relations(tgt)[:6]]
        overlap = set(str(n) for n in neighbors_src if n) & \
                  set(str(n) for n in neighbors_tgt if n)
        if len(overlap) >= 2:
            votes_for += 1
            rationale_parts.append(f"Graf: {len(overlap)} gemensamma grannar corroborerar")
            _log.debug("  [C] Graf: %d överlappande grannar → FÖR", len(overlap))
        elif len(overlap) == 0:
            rationale_parts.append("Graf: inga gemensamma grannar")
            _log.debug("  [C] Graf: 0 överlapp → neutral")
    except Exception as e:
        _log.debug("  [C] Graf-korroboration misslyckades: %s", e)

    # ── Del D: Majority vote (DEEP_REVIEW_VOTE_ROUNDS LLM-anrop) ─────────────
    vote_prompt = (
        f"Är påstående '{axiom_stmt}' korrekt och vetenskapligt välgrundad? "
        "Svara bara: JA eller NEJ."
    )
    for i in range(DEEP_REVIEW_VOTE_ROUNDS):
        try:
            resp = await llm.chat.completions.create(
                model=None,
                messages=[{"role": "user", "content": vote_prompt}],
                workload="extract",
            )
            answer = (resp.message.content or "").strip().upper()
            if answer.startswith("JA") or answer.startswith("YES"):
                votes_for += 1
            else:
                votes_against += 1
            _log.debug("  [D] Röst %d: %s", i + 1, answer[:10])
        except Exception as e:
            _log.debug("  [D] Röst %d misslyckades: %s", i + 1, e)

    # ── Verdict ───────────────────────────────────────────────────────────────
    total_votes = votes_for + votes_against
    ratio       = votes_for / total_votes if total_votes else 0.5

    if ratio >= 0.70:
        outcome   = REVIEW_PROMOTE
        new_score = min(0.95, current_score + 0.15)
        rationale_parts.insert(0, f"Djup granskning: PROMOTE ({votes_for}/{total_votes} röster)")
    elif ratio <= 0.30:
        outcome   = REVIEW_DISCARD
        new_score = 0.0
        rationale_parts.insert(0, f"Djup granskning: DISCARD ({votes_against}/{total_votes} mot)")
    else:
        outcome   = REVIEW_KEEP
        new_score = current_score
        rationale_parts.insert(0, f"Djup granskning: KEEP ({votes_for}/{total_votes} röster)")

    verdict = ReviewVerdict(
        key=key, outcome=outcome, new_score=new_score,
        rationale="; ".join(rationale_parts),
        votes_for=votes_for, votes_against=votes_against,
    )
    _log.info(
        "deep_review_axiom: %s → %s  score %.2f→%.2f  for=%d against=%d",
        key, outcome, current_score, new_score, votes_for, votes_against,
    )

    if not dry_run:
        await _apply_verdict(verdict, src, rel_type, tgt, field)

    return verdict


async def _apply_verdict(
    verdict: ReviewVerdict,
    src: str, rel_type: str, tgt: str,
    field: "FieldSurface",
) -> None:
    """Skriv verdict till grafen."""
    if verdict.outcome == REVIEW_PROMOTE:
        # Uppdatera befintlig relation: ta bort assumption_flag, höj score
        try:
            field.promote_relation(src, rel_type, tgt, verdict.new_score)
            _log.info(
                "Verdict PROMOTE: %s -[%s]-> %s, ev=%.2f, assumption_flag=False",
                src, rel_type, tgt, verdict.new_score,
            )
        except Exception as e:
            _log.warning("Kunde inte applicera PROMOTE: %s", e)

    elif verdict.outcome == REVIEW_DISCARD:
        # Sätt evidence_score=0 och assumption_flag=True (markerar för pruning)
        try:
            field.discard_relation(src, rel_type, tgt)
            _log.info("Verdict DISCARD: %s -[%s]-> %s  markerad för pruning", src, rel_type, tgt)
        except Exception as e:
            _log.warning("Kunde inte applicera DISCARD: %s", e)
    # KEEP: ingen förändring


def _parse_json_response(raw: str) -> str:
    """Extrahera JSON från LLM-svar som kan innehålla markdown-block."""
    raw = raw.strip()
    if "```" in raw:
        parts = raw.split("```")
        for p in parts[1::2]:
            candidate = p.lstrip("json").strip()
            if candidate.startswith(("{", "[")):
                return candidate
    if raw.startswith(("{", "[")):
        return raw
    return ""


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

async def _llm_verify(
    node: str,
    domain: str,
    existing_claims: list[str],
    llm,
) -> tuple[list[str], list[str], list[str]]:
    """
    Steg 1: Fråga LLM vad det vet om noden.
    Returnerar (verified_claims, challenged_claims, new_claims)
    """
    claims_text = "\n".join(f"- {c}" for c in existing_claims[:8]) or "(inga ännu)"

    prompt = (
        f"Du är ett faktaverifieringssystem. Noden '{node}' (domän: {domain}) "
        f"har följande påståenden i kunskapsgrafen:\n{claims_text}\n\n"
        "Baserat på din träningsdata, svara i exakt detta JSON-format:\n"
        '{\n'
        '  "verified": ["påståenden du bekräftar"],\n'
        '  "challenged": ["påståenden som troligen är fel eller missvisande"],\n'
        '  "new": ["viktiga fakta om noden som saknas i listan ovan"]\n'
        '}\n\n'
        "Max 4 items per lista. Svara bara med JSON."
    )
    try:
        resp = await llm.chat.completions.create(
            model=None,
            messages=[{"role": "user", "content": prompt}],
            workload="extract",
        )
        raw = (resp.message.content or "").strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        return (
            [str(x) for x in data.get("verified", [])],
            [str(x) for x in data.get("challenged", [])],
            [str(x) for x in data.get("new", [])],
        )
    except Exception as e:
        _log.debug("LLM-verifiering av '%s' misslyckades: %s", node, e)
        return [], [], []


async def _web_verify(
    node: str,
    domain: str,
    existing_claims: list[str],
) -> tuple[list[str], list[AxiomCandidate]]:
    """
    Steg 2: Sök på webben, returnera (new_facts, axiom_candidates).
    """
    from nouse.mcp_gateway.gateway import web_search
    query = f"{node.replace('_', ' ')} {domain} facts"
    new_facts: list[str] = []
    candidates: list[AxiomCandidate] = []

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: web_search(query, max_results=MAX_WEB_RESULTS)
        )
        snippets = []
        for r in result.get("results", []):
            snippet = str(r.get("snippet") or r.get("body") or "").strip()
            if snippet:
                snippets.append(snippet)
                new_facts.append(snippet[:200])

        if snippets and existing_claims:
            # Hitta webb-bekräftade claims → higher evidence
            for claim in existing_claims[:4]:
                claim_lower = claim.lower()
                key_words = [w for w in claim_lower.split() if len(w) > 4]
                hits = sum(
                    1 for s in snippets
                    if any(kw in s.lower() for kw in key_words)
                )
                if hits >= 2:
                    candidates.append(AxiomCandidate(
                        src=node,
                        rel_type="webb_bekräftad",
                        tgt=claim[:80],
                        why=f"Bekräftat av {hits} webbkällor",
                        evidence_score=0.70 + min(0.15, hits * 0.05),
                        source="web",
                        auto_commit=False,  # webb-bekräftat stärker men lägger inte in ny nod
                        assumption_flag=False,
                    ))
    except Exception as e:
        _log.debug("Webb-sökning för '%s' misslyckades: %s", node, e)

    return new_facts[:5], candidates


def _find_contradictions(
    field: "FieldSurface",
    node: str,
    out_rels: list[dict],
) -> list[str]:
    """
    Steg 3: Hitta relationer som pekar på motstridiga påståenden.
    Ex: A --[orsakar]--> B  och  A --[förhindrar]--> B
    """
    contradictions: list[str] = []
    # Gruppen relationer per mål-nod
    by_target: dict[str, list[str]] = {}
    for rel in out_rels:
        tgt = str(rel.get("target") or "")
        typ = str(rel.get("type") or "")
        if tgt:
            by_target.setdefault(tgt, []).append(typ)

    OPPOSING = {
        ("orsakar", "förhindrar"), ("ökar", "minskar"),
        ("aktiverar", "inhiberar"), ("stärker", "försvagar"),
        ("drives", "blocks"), ("enables", "prevents"),
        ("promotes", "inhibits"), ("increases", "decreases"),
    }
    for tgt, types in by_target.items():
        type_set = set(types)
        for a, b in OPPOSING:
            if a in type_set and b in type_set:
                contradictions.append(
                    f"'{node}' har både [{a}] och [{b}] mot '{tgt}' — möjlig motsägelse"
                )
    return contradictions


def _find_shadow_nodes(
    field: "FieldSurface",
    node: str,
    out_rels: list[dict],
) -> list[str]:
    """
    Steg 4: Hitta noder med liknande relations-fingeravtryck.
    "Shadow nodes" = noder som beter sig strukturellt lika men ej är kopplade.
    """
    my_targets  = {str(r.get("target") or "") for r in out_rels}
    my_types    = {str(r.get("type") or "") for r in out_rels}

    if not my_targets:
        return []

    candidates: dict[str, int] = {}

    for tgt in list(my_targets)[:5]:
        try:
            in_rels = field._in_relations(tgt)
            for rel in in_rels:
                src = str(rel.get("source") or "")
                typ = str(rel.get("type") or "")
                if src and src != node and typ in my_types:
                    candidates[src] = candidates.get(src, 0) + 1
        except Exception:
            pass

    # Noder med >= 2 gemensamma relationstyper mot samma mål
    shadows = [
        n for n, count in candidates.items()
        if count >= 2 and n != node
    ]
    shadows.sort(key=lambda n: -candidates[n])
    return shadows[:MAX_SHADOW_NODES]


async def _discover_axioms(
    node: str,
    domain: str,
    shadow_nodes: list[str],
    new_llm_facts: list[str],
    contradictions: list[str],
    field: "FieldSurface",
    llm,
) -> list[AxiomCandidate]:
    """
    Steg 5: Generalisera mönster till axiom-kandidater.

    Logik:
    - Shadow nodes med liknande mönster → gemensam abstrakt princip
    - Nya LLM-fakta som inte finns i grafen → ny relation
    - Korrelationsmönster → ny nod (abstraktionsnivå ovan nuvarande)
    """
    candidates: list[AxiomCandidate] = []

    # 5a: Shadow-node axiom — om A och B beter sig likt → kanske de delar princip C
    if len(shadow_nodes) >= 2:
        shadow_sample = shadow_nodes[:4]
        prompt = (
            f"Noderna {shadow_sample + [node]} i domänen '{domain}' har strukturellt "
            f"liknande relationer i en kunskapsgraf.\n"
            "Finns det en underliggande princip, mekanism eller abstrakt begrepp "
            "som förklarar varför dessa noder beter sig likt? "
            "Om ja, ge ett kort namn på principen och varför.\n"
            'Svara i JSON: {"principle": "namn", "why": "förklaring", "confidence": 0.0-1.0}\n'
            "Om ingen tydlig princip finns: {}"
        )
        try:
            resp = await llm.chat.completions.create(
                model=None,
                messages=[{"role": "user", "content": prompt}],
                workload="synthesize",
            )
            raw = (resp.message.content or "").strip()
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json")
            data = json.loads(raw)
            if data and data.get("principle") and float(data.get("confidence", 0)) > 0.4:
                principle = str(data["principle"]).strip()
                why       = str(data.get("why", "")).strip()
                conf      = float(data.get("confidence", 0.5))
                ev_score  = min(0.90, 0.50 + conf * 0.4)
                # Noden → principen (ny abstrakt nod)
                candidates.append(AxiomCandidate(
                    src=node,
                    rel_type="instans_av",
                    tgt=principle,
                    why=f"Shadow-analys: {', '.join(shadow_sample[:2])} delar mönster. {why}",
                    evidence_score=ev_score,
                    source="correlation",
                    auto_commit=ev_score >= AXIOM_STRONG_THRESHOLD,
                    assumption_flag=ev_score < AXIOM_STRONG_THRESHOLD,
                ))
                # Shadow-noder → samma princip
                for sn in shadow_sample[:2]:
                    candidates.append(AxiomCandidate(
                        src=sn,
                        rel_type="instans_av",
                        tgt=principle,
                        why=f"Delar strukturellt mönster med {node}",
                        evidence_score=ev_score * 0.9,
                        source="correlation",
                        auto_commit=(ev_score * 0.9) >= AXIOM_STRONG_THRESHOLD,
                        assumption_flag=(ev_score * 0.9) < AXIOM_STRONG_THRESHOLD,
                    ))
        except Exception as e:
            _log.debug("Axiom shadow-analys misslyckades: %s", e)

    # 5b: Nya LLM-fakta → möjliga nya relationer
    if new_llm_facts:
        prompt = (
            f"Dessa påståenden om '{node}' saknas i kunskapsgrafen:\n"
            + "\n".join(f"- {f}" for f in new_llm_facts[:4])
            + "\n\nExtrahera de viktigaste som relationer i JSON-format:\n"
            '[{"src": "nod_a", "rel_type": "relationstyp", "tgt": "nod_b", '
            '"why": "motivering", "evidence_score": 0.5-0.9}]\n'
            "Max 3 relationer. Använd korta nod-namn (snake_case). Svara bara JSON."
        )
        try:
            resp = await llm.chat.completions.create(
                model=None,
                messages=[{"role": "user", "content": prompt}],
                workload="extract",
            )
            raw = (resp.message.content or "").strip()
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json")
            rels = json.loads(raw)
            if isinstance(rels, list):
                for r in rels[:3]:
                    ev = float(r.get("evidence_score", 0.5))
                    candidates.append(AxiomCandidate(
                        src=str(r.get("src", node)),
                        rel_type=str(r.get("rel_type", "relaterar_till")),
                        tgt=str(r.get("tgt", "")),
                        why=str(r.get("why", "LLM-träningskunskap")),
                        evidence_score=ev,
                        source="llm_training",
                        auto_commit=ev >= AXIOM_STRONG_THRESHOLD,
                        assumption_flag=ev < AXIOM_STRONG_THRESHOLD,
                    ))
        except Exception as e:
            _log.debug("LLM ny-relation-extraktion misslyckades: %s", e)

    return [c for c in candidates if c.tgt]


# ── Huvudfunktion ──────────────────────────────────────────────────────────────

async def deepdive_node(
    node_name: str,
    field: "FieldSurface",
    *,
    dry_run: bool = False,
) -> DeepDiveResult:
    """
    Kör hela 5-stegs DeepDive-pipeline på en nod.
    """
    from nouse.ollama_client.client import AsyncOllama
    from nouse.learning_coordinator import LearningCoordinator
    from nouse.limbic.signals import load_state

    t0     = time.monotonic()
    result = DeepDiveResult(node=node_name)
    llm    = AsyncOllama()

    # Hämta nod-metadata
    knowledge  = field.concept_knowledge(node_name)
    out_rels   = field.out_relations(node_name)
    domain     = "okänd"
    try:
        d = field.concept_domain(node_name)
        if d:
            domain = d
    except Exception:
        pass

    existing_claims = knowledge.get("claims") or []

    # ── Steg 1: LLM-verifiering ───────────────────────────────────────────────
    _log.info("DeepDive [1/5] LLM-verifiering: %s", node_name)
    verified, challenged, new_llm = await _llm_verify(
        node_name, domain, existing_claims, llm
    )
    result.llm_verified   = verified
    result.llm_challenged = challenged

    # Flagga challengade claims i grafen
    if challenged and not dry_run:
        try:
            field.upsert_concept_knowledge(
                node_name,
                claims=[f"[IFRÅGASATT] {c}" for c in challenged],
                uncertainty=0.7,
            )
        except Exception:
            pass

    # ── Steg 2: Webb-korscheck ────────────────────────────────────────────────
    _log.info("DeepDive [2/5] Webb-sökning: %s", node_name)
    web_facts, web_axioms = await _web_verify(node_name, domain, existing_claims)
    result.web_new_facts = web_facts

    # Uppdatera evidence på webb-bekräftade claims
    if not dry_run:
        limbic = load_state()
        coord  = LearningCoordinator(field, limbic)
        for ax in web_axioms:
            if ax.evidence_score >= AXIOM_WEAK_THRESHOLD:
                # Stärk befintliga relationer som webb bekräftar
                for rel in out_rels[:8]:
                    tgt = str(rel.get("target") or "")
                    if tgt and any(kw in ax.tgt for kw in tgt.split("_")[:2]):
                        coord.on_fact(
                            node_name, rel.get("type", "relaterar_till"), tgt,
                            why=ax.why,
                            evidence_score=ax.evidence_score,
                            support_count=2,
                        )

    # ── Steg 3: Claim-kontrastering ───────────────────────────────────────────
    _log.info("DeepDive [3/5] Kontrastering: %s", node_name)
    result.contradictions = _find_contradictions(field, node_name, out_rels)
    if result.contradictions and not dry_run:
        try:
            field.upsert_concept_knowledge(
                node_name,
                claims=[f"[KONFLIKT] {c}" for c in result.contradictions],
                uncertainty=0.8,
            )
        except Exception:
            pass

    # ── Steg 4: Korrelationsanalys ────────────────────────────────────────────
    _log.info("DeepDive [4/5] Korrelation: %s", node_name)
    result.shadow_nodes = _find_shadow_nodes(field, node_name, out_rels)
    if result.shadow_nodes:
        _log.info("  Shadow nodes: %s", result.shadow_nodes[:4])

    # ── Steg 5: Axiom-discovery ───────────────────────────────────────────────
    _log.info("DeepDive [5/5] Axiom-discovery: %s", node_name)
    axioms = await _discover_axioms(
        node_name, domain,
        result.shadow_nodes, new_llm,
        result.contradictions, field, llm,
    )
    result.axiom_candidates = axioms

    # Commit/flagga axiom
    if not dry_run and axioms:
        limbic = load_state()
        coord  = LearningCoordinator(field, limbic)
        for ax in axioms:
            if ax.evidence_score < AXIOM_WEAK_THRESHOLD:
                continue
            try:
                field.add_relation(
                    ax.src, ax.rel_type, ax.tgt,
                    why=ax.why,
                    source_tag="deepdive_axiom",
                    evidence_score=ax.evidence_score,
                    assumption_flag=ax.assumption_flag,
                )
                coord.on_fact(
                    ax.src, ax.rel_type, ax.tgt,
                    why=ax.why,
                    evidence_score=ax.evidence_score,
                    support_count=1,
                )
                if ax.auto_commit:
                    result.committed += 1
                    _log.info(
                        "  Axiom COMMIT: %s -[%s]-> %s  ev=%.2f",
                        ax.src, ax.rel_type, ax.tgt, ax.evidence_score,
                    )
                else:
                    result.flagged += 1
                    _log.info(
                        "  Axiom FLAG: %s -[%s]-> %s  ev=%.2f (assumption)",
                        ax.src, ax.rel_type, ax.tgt, ax.evidence_score,
                    )
            except Exception as e:
                _log.warning("  Kunde inte spara axiom: %s", e)

    result.duration = round(time.monotonic() - t0, 2)
    _log.info(
        "DeepDive klar: %s  verified=%d challenged=%d shadow=%d "
        "axioms=%d committed=%d flagged=%d (%.1fs)",
        node_name, len(verified), len(challenged),
        len(result.shadow_nodes), len(axioms),
        result.committed, result.flagged, result.duration,
    )
    return result


async def deepdive_batch(
    field: "FieldSurface",
    *,
    max_nodes: int = 20,
    max_minutes: float = 30.0,
    dry_run: bool = False,
    focus_domain: str | None = None,
) -> DeepDiveBatch:
    """
    Kör DeepDive på top-N noder (valda på låg strong_facts + hög grad).
    Anropas från NightRun steg 8.
    """
    batch    = DeepDiveBatch()
    t0       = time.monotonic()
    deadline = t0 + max_minutes * 60

    # Välj noder: hög gradtal, låg strong_facts
    try:
        audit   = field.knowledge_audit(limit=max_nodes * 4, strict=True)
        missing = [
            n for n in audit.get("nodes", [])
            if not n.get("has_strong_facts")
        ]
        if focus_domain:
            missing = [n for n in missing if n.get("domain") == focus_domain]

        # Sortera: flest relationer i grafen = mest intressanta
        def _degree(n: dict) -> int:
            try:
                rels = field.out_relations(n.get("name", ""))
                return len(rels)
            except Exception:
                return 0

        missing.sort(key=_degree, reverse=True)
        targets = missing[:max_nodes]
    except Exception as e:
        _log.warning("deepdive_batch: knowledge_audit misslyckades: %s", e)
        return batch

    _log.info("DeepDive batch: %d noder att bearbeta", len(targets))

    for node_info in targets:
        if time.monotonic() > deadline:
            _log.warning("DeepDive batch: tidsgräns nådd")
            break

        name = node_info.get("name", "")
        if not name:
            continue

        try:
            result = await deepdive_node(name, field, dry_run=dry_run)
            batch.results.append(result)
            batch.nodes_processed += 1
            batch.total_committed += result.committed
            batch.total_flagged   += result.flagged
        except Exception as e:
            _log.warning("DeepDive misslyckades för '%s': %s", name, e)

        await asyncio.sleep(0)

    batch.duration = round(time.monotonic() - t0, 2)
    _log.info(
        "DeepDive batch klar: noder=%d committed=%d flagged=%d (%.1fs)",
        batch.nodes_processed, batch.total_committed,
        batch.total_flagged, batch.duration,
    )
    return batch
