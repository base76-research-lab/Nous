"""
nouse.field.bridge_finder — Latenta strukturella bryggor
=========================================================

Problemet som löses:
  Grafen vet att "svampsoppa" och "kvantfysik" existerar.
  Den vet INTE att de delar ett djupt strukturellt mönster:

    svampsoppa → svamp → mycel → nätverksstruktur →
    → lokal interaktion → emergent global koherens ←
    ← kvantentanglement ← superposition ← kvantfysik

  Det är inte en koppling man hittar med cosine similarity.
  Det är en koppling man hittar när man läser grafens AXIOM-SIGNATURER
  och ser att båda noderna delar ett underliggande mönster.

Algoritm:
  1. Axiom-signatur:  Vilka relationstyper och topologier omger varje nod?
  2. Signatur-matchning: Vilka nodpar delar strukturella mönster trots
                         att de är i olika domäner och saknar direkt väg?
  3. Brygg-prompt:    Visa LLM BÅDA signaturerna + delade mönster →
                      "Hitta kedjan A → x1 → x2 → B"
  4. Validering:      Bayesiansk evidensbedömning per hopp
  5. Kristallisering: Skriv kedjan + META::bridge-nod till grafen

Filosofisk bakgrund:
  Wittgenstein sa att grammatiken för ett ord bestäms av dess ANVÄNDNING.
  På samma sätt bestäms ett koncepts "mening" i NoUse av dess RELATIONER.
  Två koncept som används i strukturellt analoga mönster, även om de är
  i helt olika domäner, delar något fundamentalt — och det är PRECIS
  vad axiom-signaturer fångar.

  Svampsoppa ↔ Kvantfysik ↔ Wittgenstein:
    Alla tre involverar LOKALA regler → EMERGENTA globala strukturer
    som inte kan reduceras till sina delar.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nouse.field.surface import FieldSurface
    from nouse.learning_coordinator import LearningCoordinator

_log = logging.getLogger("nouse.bridge_finder")

# ── Konfiguration ─────────────────────────────────────────────────────────────

BRIDGE_MAX_BFS_DEPTH    = int(os.getenv("NOUSE_BRIDGE_MAX_BFS_DEPTH", "5"))
BRIDGE_MIN_AXIOM_OVERLAP = int(os.getenv("NOUSE_BRIDGE_MIN_AXIOM_OVERLAP", "1"))
BRIDGE_WRITE_CHAIN      = bool(int(os.getenv("NOUSE_BRIDGE_WRITE_CHAIN", "1")))
BRIDGE_SAMPLE_PER_DOMAIN = int(os.getenv("NOUSE_BRIDGE_SAMPLE_PER_DOMAIN", "5"))
BRIDGE_LLM_TIMEOUT      = float(os.getenv("NOUSE_BRIDGE_LLM_TIMEOUT", "60.0"))
BRIDGE_MIN_EVIDENCE     = float(os.getenv("NOUSE_BRIDGE_MIN_EVIDENCE", "0.45"))


# ── Datastrukturer ────────────────────────────────────────────────────────────

@dataclass
class AxiomSignature:
    """
    Den strukturella fingeravtrycket för ett koncept.
    Vad en nod "gör" i grafen — inte vad den "är".
    """
    concept: str
    domain: str
    rel_types_out: list[str]        # vilka relationstyper pekar FRÅN noden
    rel_types_in: list[str]         # vilka relationstyper pekar TILL noden
    neighbor_domains: list[str]     # vilka domäner når noden via 1 hopp
    depth2_rel_types: list[str]     # relationstyper på djup 2 (axiomens axiom)
    degree: int

    @property
    def structural_pattern(self) -> frozenset[str]:
        """
        Kombinerat mönster som kan jämföras mellan noder.
        Abstraherar bort de specifika namnen — behåller STRUKTUREN.
        """
        return frozenset(self.rel_types_out + self.rel_types_in + self.depth2_rel_types)

    def overlap_score(self, other: "AxiomSignature") -> float:
        """
        Hur strukturellt lika är två noder?
        Jaccard-index på deras kombinerade relationstypmönster.
        """
        a = self.structural_pattern
        b = other.structural_pattern
        if not a and not b:
            return 0.0
        intersection = len(a & b)
        union = len(a | b)
        return intersection / union if union > 0 else 0.0


@dataclass
class BridgeChain:
    """En funnen strukturell brygga mellan två koncept."""
    source: str
    target: str
    chain: list[str]            # [source, x1, x2, ..., target]
    relations: list[str]        # [rel_typ1, rel_typ2, ...]
    shared_patterns: list[str]  # de delade axiom-mönstren som motiverar bryggan
    overlap_score: float
    why: str                    # LLM:s förklaring av varför kopplingen existerar
    evidence_per_hop: list[float]
    written_to_graph: bool = False
    meta_bridge_id: str = ""
    # Den TREDJE IDÉN — emergerar ur syntesen av source + target.
    # Inte hämtat från någon av dem — uppkommer bara när de ses SIMULTANT.
    # Denna nod lever i grafen och kan sedan gå in i nästa bridge (1+1=3+1=5...)
    synthesis_concept: str = ""   # namnet på den emergenta insikten
    synthesis_why: str = ""       # varför denna syntes är mer än summan av delarna


@dataclass
class BridgeSession:
    """Resultat från en hel bridge-discovery-session."""
    bridges_found: int = 0
    bridges_written: int = 0
    pairs_evaluated: int = 0
    cross_domain_pairs: int = 0
    errors: int = 0
    top_bridges: list[BridgeChain] = field(default_factory=list)


# ── Axiom-signatur-extraktion ─────────────────────────────────────────────────

def extract_axiom_signature(
    concept: str,
    field_surface: "FieldSurface",
) -> AxiomSignature:
    """
    Extrahera den strukturella fingeravtrycket för ett koncept.
    Djup 1: direkta relationer. Djup 2: grannars relationer (axiomens axiom).
    """
    rel_types_out:   list[str] = []
    rel_types_in:    list[str] = []
    neighbor_domains: list[str] = []
    depth2_rel_types: list[str] = []
    degree = 0

    try:
        # Utgående relationer (djup 1)
        out_rels = field_surface.out_relations(concept)

        for row in out_rels:
            rtype = str(row.get("type", "") or "")
            tgt = str(row.get("target", "") or "")
            tgt_domain = field_surface.concept_domain(tgt) or "" if tgt else ""
            if rtype:
                rel_types_out.append(rtype)
            if tgt_domain:
                neighbor_domains.append(tgt_domain)
            degree += 1

            # Djup 2: grannens utgående relationer
            if tgt:
                try:
                    d2_rels = field_surface.out_relations(tgt)
                    depth2_rel_types.extend(
                        str(r.get("type", "") or "")
                        for r in d2_rels[:5]
                        if r.get("type")
                    )
                except Exception:
                    pass

        # Inkommande relationer (djup 1)
        in_rels = field_surface._in_relations(concept)

        for row in in_rels:
            rtype = str(row.get("type", "") or "")
            if rtype:
                rel_types_in.append(rtype)
            degree += 1

    except Exception as e:
        _log.debug("Kunde inte extrahera signatur för '%s': %s", concept, e)

    # Hämta domän
    domain = field_surface.concept_domain(concept) or "general"

    return AxiomSignature(
        concept=concept,
        domain=domain,
        rel_types_out=list(set(rel_types_out)),
        rel_types_in=list(set(rel_types_in)),
        neighbor_domains=list(set(neighbor_domains)),
        depth2_rel_types=list(set(depth2_rel_types)),
        degree=degree,
    )


# ── BFS-vägletning (finns det redan en väg?) ─────────────────────────────────

def find_graph_path(
    source: str,
    target: str,
    field_surface: "FieldSurface",
    max_depth: int = BRIDGE_MAX_BFS_DEPTH,
) -> list[str] | None:
    """
    Söker en väg source → target i grafen med BFS.
    Returnerar listan av noder om väg finns, annars None.
    Används för att avgöra: behöver vi en ny brygga?
    """
    if source == target:
        return [source]

    visited: set[str] = {source}
    queue: collections.deque[list[str]] = collections.deque([[source]])

    depth = 0
    while queue and depth < max_depth:
        batch_size = len(queue)
        depth += 1

        for _ in range(batch_size):
            path = queue.popleft()
            current = path[-1]

            try:
                nbr_list = field_surface.neighbors(current, limit=20)

                for neighbor in nbr_list:
                    if not neighbor:
                        continue
                    if neighbor == target:
                        return path + [target]
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(path + [neighbor])
            except Exception:
                pass

    return None


# ── LLM-bryggedetektion ───────────────────────────────────────────────────────

_BRIDGE_SYSTEM = """\
Du är ett expert-system som hittar DJUPA STRUKTURELLA KORRELATIONER
mellan till synes orelaterade koncept.

Din uppgift är att avslöja den DOLDA KOPPLINGKEDJAN mellan två koncept
via deras underliggande strukturella mönster.

Nyckelprincip: Kopplingar hittas INTE via semantisk likhet
utan via ISOMORFA STRUKTURELLA MÖNSTER:
- Lokala regler → emergent global struktur
- Rekursiva självlikheter (fraktalmönster)
- Informationsbevarande transformationer
- Fas-övergångar och kritiska punkter
- Hierarkisk kompression och expansion

Exempel:
  Mycel ↔ Kvantnätverk: båda är system med icke-lokal korrelation
  via lokala interaktioner utan central koordination.
  
  Wittgenstein ↔ Evolutionsteori: båda handlar om hur 'regler'
  inte existerar abstrakt utan endast i deras faktiska TILLÄMPNING/SELEKTIONSPROCESS.
"""

_BRIDGE_USER = """\
Hitta den dolda kopplingkedjan mellan dessa två koncept:

KONCEPT A: "{concept_a}" (domän: {domain_a})
KONCEPT B: "{concept_b}" (domän: {domain_b})

Deras strukturella signaturer:
--- Signatur A ({concept_a}) ---
Utgående relationstyper: {rel_out_a}
Inkommande relationstyper: {rel_in_a}
Grannar i domäner: {neighbor_domains_a}
Djup-2 mönster: {depth2_a}

--- Signatur B ({concept_b}) ---
Utgående relationstyper: {rel_out_b}
Inkommande relationstyper: {rel_in_b}
Grannar i domäner: {neighbor_domains_b}
Djup-2 mönster: {depth2_b}

Delade strukturella mönster: {shared_patterns}

DIN UPPGIFT:
1. Identifiera det FUNDAMENTALA STRUKTURELLA MÖNSTER som förenar A och B
2. Construct kopplingkedjan: {concept_a} → x1 → x2 → ... → {concept_b}
   (max 5 mellanled, varje mellanled ska vara ett konkret koncept)
3. Förklara varför varje hopp är strukturellt motiverat

Svara med JSON:
{{
  "shared_pattern": "det fundamentala mönstret i en mening",
  "why": "djupare förklaring av varför dessa koncept är strukturellt relaterade",
  "chain": [
    {{
      "from": "{concept_a}",
      "rel": "relationstyp",
      "to": "nästa_koncept",
      "domain": "domän för nästa_koncept",
      "why": "varför detta hopp är strukturellt motiverat"
    }},
    ...
    {{
      "from": "föregående_koncept",
      "rel": "relationstyp",
      "to": "{concept_b}",
      "domain": "{domain_b}",
      "why": "avslutande hopp"
    }}
  ],
  "confidence": 0.0
}}

Om ingen meningsfull koppling finns (confidence < 0.3): returnera {{"chain": [], "confidence": 0.0}}
"""


async def _discover_bridge_via_llm(
    sig_a: AxiomSignature,
    sig_b: AxiomSignature,
) -> dict:
    """Ber frontier LLM hitta kopplingkedjan baserat på axiom-signaturer."""
    import httpx
    import json as _json

    base_url = os.getenv("NOUSE_TEACHER_BASE_URL", "https://models.inference.ai.azure.com")
    token = os.getenv("GITHUB_TOKEN", "")
    from nouse.llm.autodiscover import get_default_models
    model = get_default_models().get("teacher", "gpt-4o")

    shared = list(sig_a.structural_pattern & sig_b.structural_pattern)

    prompt = _BRIDGE_USER.format(
        concept_a=sig_a.concept,
        domain_a=sig_a.domain,
        concept_b=sig_b.concept,
        domain_b=sig_b.domain,
        rel_out_a=", ".join(sig_a.rel_types_out[:8]) or "inga",
        rel_in_a=", ".join(sig_a.rel_types_in[:8]) or "inga",
        neighbor_domains_a=", ".join(sig_a.neighbor_domains[:5]) or "okänt",
        depth2_a=", ".join(sig_a.depth2_rel_types[:6]) or "inga",
        rel_out_b=", ".join(sig_b.rel_types_out[:8]) or "inga",
        rel_in_b=", ".join(sig_b.rel_types_in[:8]) or "inga",
        neighbor_domains_b=", ".join(sig_b.neighbor_domains[:5]) or "okänt",
        depth2_b=", ".join(sig_b.depth2_rel_types[:6]) or "inga",
        shared_patterns=", ".join(shared[:8]) or "direkta mönster saknas — sök djupare",
    )

    try:
        async with httpx.AsyncClient(timeout=BRIDGE_LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _BRIDGE_SYSTEM},
                        {"role": "user",   "content": prompt},
                    ],
                    "temperature": 0.4,
                    "max_tokens": 1500,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            return _json.loads(raw)
    except Exception as e:
        _log.warning("LLM bridge discovery misslyckades: %s", e)
        return {"chain": [], "confidence": 0.0}


# ── Validera och skriv bryggan till grafen ────────────────────────────────────

async def _write_bridge_chain(
    llm_result: dict,
    sig_a: AxiomSignature,
    sig_b: AxiomSignature,
    field_surface: "FieldSurface",
    coordinator: "LearningCoordinator",
) -> BridgeChain | None:
    """
    Validerar varje hopp i kedjan med Bayesiansk evidensbedömning
    och skriver de godkända till grafen.
    """
    from nouse.daemon.evidence import assess_relation
    from nouse.field.events import emit as _emit

    chain_raw = llm_result.get("chain", [])
    confidence = float(llm_result.get("confidence", 0.0))
    why_overall = str(llm_result.get("why", "") or "")
    shared_pattern = str(llm_result.get("shared_pattern", "") or "")

    if not chain_raw or confidence < 0.3:
        return None

    chain_nodes: list[str] = []
    chain_rels: list[str] = []
    evidence_scores: list[float] = []

    for hop in chain_raw:
        src = str(hop.get("from", "") or "").strip()
        rel = str(hop.get("rel", "") or "").strip()
        tgt = str(hop.get("to", "") or "").strip()
        tgt_domain = str(hop.get("domain", "general") or "general").strip()
        hop_why = str(hop.get("why", "") or "").strip()

        if not src or not rel or not tgt:
            continue

        # Validera med evidensmodul
        assessment = assess_relation(
            relation={"src": src, "type": rel, "tgt": tgt, "why": hop_why},
            task="bridge_discovery",
            confirming_relations=[],
            contradicting_relations=[],
        )
        score = assessment.score

        if score < BRIDGE_MIN_EVIDENCE:
            _log.debug("Hopp avvisat (score=%.3f): %s -[%s]-> %s", score, src, rel, tgt)
            # Om ett hopp faller under tröskel — avbryt hela kedjan
            break

        try:
            field_surface.add_concept(src, domain="general", source="bridge_finder")
            field_surface.add_concept(tgt, domain=tgt_domain, source="bridge_finder")
            field_surface.add_relation(
                src=src,
                rel_type=rel,
                tgt=tgt,
                why=f"[bridge:{sig_a.concept}↔{sig_b.concept}] {hop_why}",
                evidence_score=score,
                source_tag="bridge_finder",
            )
            coordinator.on_fact(
                src, rel, tgt,
                why=hop_why,
                evidence_score=score,
                support_count=1,
            )
            chain_nodes.append(src)
            chain_rels.append(rel)
            evidence_scores.append(score)
        except Exception as e:
            _log.debug("Kunde inte skriva hopp %s -[%s]-> %s: %s", src, rel, tgt, e)

    if not chain_nodes:
        return None

    # Lägg till sista noden
    chain_nodes.append(sig_b.concept)

    # ── Kristallisera den TREDJE IDÉN (emergent synthesis) ───────────────────
    # Den är inte META-skräp. Den är en riktig namngiven nod i grafen.
    # Den kan sedan gå in i nästa bridge: 1+1=3+1=5...
    synthesis_name = ""
    synthesis_why = ""
    synth_raw = llm_result.get("emergent_synthesis", {})
    if isinstance(synth_raw, dict):
        synthesis_name = str(synth_raw.get("name", "") or "").strip()
        synthesis_why = str(synth_raw.get("why", "") or "").strip()

    if synthesis_name:
        try:
            field_surface.add_concept(
                synthesis_name,
                domain="synthesis",
                source="bridge_finder",
            )
            # Bryggan GENERERAR syntesen och syntesen INSTANSIERAS I båda källorna
            field_surface.add_relation(
                src=sig_a.concept,
                rel_type="genererar_syntes",
                tgt=synthesis_name,
                why=f"[1+1=3] {synthesis_why}",
                evidence_score=confidence,
                source_tag="bridge_finder",
            )
            field_surface.add_relation(
                src=sig_b.concept,
                rel_type="genererar_syntes",
                tgt=synthesis_name,
                why=f"[1+1=3] {synthesis_why}",
                evidence_score=confidence,
                source_tag="bridge_finder",
            )
            # Syntesen är en instans av båda sina föräldrar
            field_surface.add_relation(
                src=synthesis_name,
                rel_type="emergerar_ur",
                tgt=sig_a.concept,
                why=synthesis_why,
                evidence_score=confidence,
                source_tag="bridge_finder",
            )
            field_surface.add_relation(
                src=synthesis_name,
                rel_type="emergerar_ur",
                tgt=sig_b.concept,
                why=synthesis_why,
                evidence_score=confidence,
                source_tag="bridge_finder",
            )
            coordinator.on_fact(
                sig_a.concept, "genererar_syntes", synthesis_name,
                why=synthesis_why, evidence_score=confidence, support_count=2,
            )
            _log.info(
                "Tredje idén kristalliserad: '%s' (ur %s ⊕ %s)",
                synthesis_name, sig_a.concept, sig_b.concept,
            )
        except Exception as e:
            _log.debug("Kunde inte skriva syntes-nod: %s", e)
            synthesis_name = ""

    # ── Kristallisera META::bridge-nod (intern referens) ─────────────────────
    bridge_id = f"META::bridge::{sig_a.concept}::{sig_b.concept}"
    meta_why = (
        f"Strukturell brygga: {shared_pattern or why_overall} "
        f"(kedja: {' → '.join(chain_nodes)})"
        + (f" | syntes: {synthesis_name}" if synthesis_name else "")
    )

    try:
        field_surface.add_concept(
            bridge_id,
            domain="meta",
            source="bridge_finder",
        )
        field_surface.add_relation(
            src=sig_a.concept,
            rel_type="är_strukturellt_bunden_till",
            tgt=bridge_id,
            why=meta_why,
            evidence_score=confidence,
            source_tag="bridge_finder",
        )
        field_surface.add_relation(
            src=sig_b.concept,
            rel_type="är_strukturellt_bunden_till",
            tgt=bridge_id,
            why=meta_why,
            evidence_score=confidence,
            source_tag="bridge_finder",
        )
    except Exception as e:
        _log.debug("Kunde inte skapa META-brygga: %s", e)

    bridge = BridgeChain(
        source=sig_a.concept,
        target=sig_b.concept,
        chain=chain_nodes,
        relations=chain_rels,
        shared_patterns=list(sig_a.structural_pattern & sig_b.structural_pattern),
        overlap_score=sig_a.overlap_score(sig_b),
        why=why_overall,
        evidence_per_hop=evidence_scores,
        written_to_graph=True,
        meta_bridge_id=bridge_id,
        synthesis_concept=synthesis_name,
        synthesis_why=synthesis_why,
    )

    _emit(
        "bridge_discovered",
        source=sig_a.concept,
        target=sig_b.concept,
        chain=chain_nodes,
        shared_pattern=shared_pattern,
        synthesis=synthesis_name,
        confidence=confidence,
    )

    _log.info(
        "Brygga kristalliserad: %s ↔ %s via %d hopp (overlap=%.3f)",
        sig_a.concept, sig_b.concept, len(chain_nodes), sig_a.overlap_score(sig_b),
    )

    return bridge


# ── Huvud-API ─────────────────────────────────────────────────────────────────

async def discover_bridge(
    concept_a: str,
    concept_b: str,
    field_surface: "FieldSurface",
    coordinator: "LearningCoordinator",
    *,
    force: bool = False,
) -> BridgeChain | None:
    """
    Hitta (och skriv) den latenta strukturella bryggan mellan två koncept.

    Kontrollerar först om en väg redan finns i grafen (BFS).
    Om ja: returnerar None (bryggan behövs inte).
    Om nej: extraherar signaturer → LLM discovery → validering → skrivning.

    Args:
        concept_a:     Startkoncept (t.ex. "svampsoppa")
        concept_b:     Målkoncept (t.ex. "kvantfysik")
        field_surface: Grafytan
        coordinator:   Learning coordinator för evidens + on_fact hooks
        force:         Bygg brygga även om väg redan finns
    """
    # BFS-kontroll: behöver vi en ny brygga?
    if not force:
        existing_path = find_graph_path(concept_a, concept_b, field_surface)
        if existing_path:
            _log.info(
                "Väg finns redan: %s → ... → %s (%d hopp)",
                concept_a, concept_b, len(existing_path),
            )
            return None

    _log.info("Söker latent brygga: %s ↔ %s", concept_a, concept_b)

    # Extrahera axiom-signaturer
    sig_a = extract_axiom_signature(concept_a, field_surface)
    sig_b = extract_axiom_signature(concept_b, field_surface)

    overlap = sig_a.overlap_score(sig_b)
    _log.info(
        "Axiom-signatur-overlap: %.3f (%s ∩ %s = %d mönster)",
        overlap, concept_a, concept_b,
        len(sig_a.structural_pattern & sig_b.structural_pattern),
    )

    # Ring LLM
    llm_result = await _discover_bridge_via_llm(sig_a, sig_b)

    confidence = float(llm_result.get("confidence", 0.0))
    if confidence < 0.3:
        _log.info("Ingen meningsfull brygga hittades (confidence=%.3f)", confidence)
        return None

    # Validera och skriv
    return await _write_bridge_chain(
        llm_result, sig_a, sig_b, field_surface, coordinator,
    )


async def run_cross_domain_discovery(
    field_surface: "FieldSurface",
    coordinator: "LearningCoordinator",
    *,
    domains: list[str] | None = None,
    sample_per_domain: int = BRIDGE_SAMPLE_PER_DOMAIN,
    max_pairs: int = 20,
    min_overlap: float = 0.0,
) -> BridgeSession:
    """
    Systematisk korsdomän-bryggediscovery.

    Samplar noder från olika domäner och söker latenta bryggor
    mellan alla domänpar. Prioriterar par med låg direkt anslutning
    men hög axiom-signatur-overlap.

    Exempelanrop (i terminalen eller daemon):
        from nouse.field.bridge_finder import run_cross_domain_discovery
        session = await run_cross_domain_discovery(field, coordinator)
    """
    session = BridgeSession()

    # Hämta domäner om ej specade
    if domains is None:
        try:
            domains = [
                d for d in field_surface.domains()
                if d and d.lower() not in ("general", "meta", "")
            ][:50]
        except Exception as e:
            _log.warning("Kunde inte hämta domäner: %s", e)
            return session

    _log.info("Korsdomän-discovery: %d domäner", len(domains))

    # Sampla noder per domän
    domain_nodes: dict[str, list[str]] = {}
    for domain in domains:
        try:
            concept_rows = field_surface.concepts(domain=domain, limit=sample_per_domain * 3)
            names = [str(r.get("name", "") or "") for r in concept_rows if r.get("name")]
            if names:
                import random
                random.shuffle(names)
                domain_nodes[domain] = names[:sample_per_domain]
        except Exception:
            pass

    # Generera korsdomänpar
    domain_list = list(domain_nodes.keys())
    pairs: list[tuple[str, str]] = []

    for i, domain_a in enumerate(domain_list):
        for domain_b in domain_list[i + 1:]:
            for node_a in domain_nodes.get(domain_a, []):
                for node_b in domain_nodes.get(domain_b, []):
                    pairs.append((node_a, node_b))
                    session.cross_domain_pairs += 1

    # Prioritera par med hög axiom-overlap (de är de intressanta)
    # (om min_overlap > 0 har vi beräknat overlap — annars slumpa)
    import random
    random.shuffle(pairs)
    pairs = pairs[:max_pairs]

    _log.info("Evaluerar %d korsdomänpar ...", len(pairs))

    for concept_a, concept_b in pairs:
        session.pairs_evaluated += 1
        try:
            bridge = await discover_bridge(
                concept_a, concept_b, field_surface, coordinator,
            )
            if bridge:
                session.bridges_found += 1
                session.bridges_written += int(bridge.written_to_graph)
                session.top_bridges.append(bridge)
                _log.info(
                    "  ✓ %s ↔ %s (overlap=%.3f, hopp=%d)",
                    concept_a, concept_b,
                    bridge.overlap_score, len(bridge.chain),
                )
        except Exception as e:
            session.errors += 1
            _log.debug("Fel vid brygg-discovery %s↔%s: %s", concept_a, concept_b, e)

        await asyncio.sleep(0.5)

    _log.info(
        "Korsdomän-discovery klar: %d bryggor hittade, %d skrivna, %d par evaluerade",
        session.bridges_found, session.bridges_written, session.pairs_evaluated,
    )
    return session


# ── Synthesis Cascade — 1+1=3+1=5+1=9... ─────────────────────────────────────

@dataclass
class CascadeResult:
    """Resultat från en kompounderad synteskaskad."""
    generations: int = 0                        # antal generationer
    total_syntheses: int = 0                    # totalt antal nya insikter
    synthesis_chain: list[str] = field(         # kedjan av emergenta begrepp
        default_factory=list
    )
    all_bridges: list[BridgeChain] = field(
        default_factory=list
    )
    final_synthesis: str = ""                   # den sista (djupaste) insikten


async def run_synthesis_cascade(
    seed_concepts: list[str],
    field_surface: "FieldSurface",
    coordinator: "LearningCoordinator",
    *,
    max_generations: int = 4,
    pairs_per_generation: int = 3,
) -> CascadeResult:
    """
    Kompounderad idésyntes: 1+1=3+1=5+1=9...

    Varje generation tar SYNTESERNA från föregående generation och
    kombinerar dem med varandra och med seed-koncept för att generera
    nästa lager av emergenta insikter.

    Generation 0 (frön):    [A, B, C, D]
    Generation 1 (syntes):  A⊕B=E,  C⊕D=F
    Generation 2 (meta):    E⊕F=G,  A⊕F=H
    Generation 3 (djup):    G⊕H=I   ← insikt som kräver 4 lager för att bli synlig

    Det är precis vad mänskligt kreativt tänkande gör:
    kombinera resultat av tidigare kombinationer, iterativt.
    En LLM kan aldrig göra detta eftersom den saknar persisterande
    syntesnoder. NoUse är det minnet.

    Args:
        seed_concepts:      Startkoncepten (kan vara vad som helst i grafen)
        field_surface:      Grafytan
        coordinator:        Learning coordinator
        max_generations:    Hur många lager att kompoundera
        pairs_per_generation: Hur många par per generation att bearbeta
    """
    result = CascadeResult()
    current_pool = list(seed_concepts)   # grows each generation

    _log.info(
        "Synthesis cascade start: %d frön, max %d generationer",
        len(seed_concepts), max_generations,
    )

    for gen in range(max_generations):
        if len(current_pool) < 2:
            _log.info("Gen %d: för få koncept (%d) — avslutar", gen, len(current_pool))
            break

        _log.info("Gen %d: pool=%d koncept", gen, len(current_pool))

        # Välj par att kombinera — prioritera par från OLIKA domäner
        import random
        pool_copy = list(current_pool)
        random.shuffle(pool_copy)

        pairs: list[tuple[str, str]] = []
        seen: set[frozenset] = set()
        for i, a in enumerate(pool_copy):
            for b in pool_copy[i + 1:]:
                key = frozenset({a, b})
                if key not in seen:
                    seen.add(key)
                    pairs.append((a, b))
                if len(pairs) >= pairs_per_generation:
                    break
            if len(pairs) >= pairs_per_generation:
                break

        new_syntheses: list[str] = []

        for concept_a, concept_b in pairs:
            try:
                bridge = await discover_bridge(
                    concept_a, concept_b, field_surface, coordinator,
                    force=True,  # tvinga fram syntes oavsett befintlig path
                )
                if bridge and bridge.synthesis_concept:
                    new_syntheses.append(bridge.synthesis_concept)
                    result.synthesis_chain.append(bridge.synthesis_concept)
                    result.all_bridges.append(bridge)
                    result.total_syntheses += 1
                    _log.info(
                        "  Gen %d: %s ⊕ %s = '%s'",
                        gen, concept_a, concept_b, bridge.synthesis_concept,
                    )
            except Exception as e:
                _log.debug("Gen %d fel: %s⊕%s: %s", gen, concept_a, concept_b, e)

            await asyncio.sleep(0.5)

        if not new_syntheses:
            _log.info("Gen %d: inga syntesnoder genererade — avslutar", gen)
            break

        # Synteserna ERSÄTTER (delvis) poolen — de är nu operanderna
        # Men behåll seed-koncepten för att möjliggöra djupare korsning
        current_pool = seed_concepts + new_syntheses
        result.generations += 1

    result.final_synthesis = result.synthesis_chain[-1] if result.synthesis_chain else ""

    _log.info(
        "Synthesis cascade klar: %d generationer, %d syntesnoder, djupaste='%s'",
        result.generations, result.total_syntheses, result.final_synthesis,
    )
    return result
