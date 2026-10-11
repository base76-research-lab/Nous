"""
nouse.field.axon_growth_cone — Strukturell resonanssökning
===========================================================

Biologisk analogi:
  Axon growth cone = spetsen på en växande nervtråd.
  Den samplar aktivt kemiska gradienter i omgivningen och
  söker kompatibla målnoder för synaptogenesi.

NoUse-implementering:
  En axiom (ny insikt från decomposition) söker aktivt i grafen
  efter noder med STRUKTURELLT ISOMORFT MÖNSTER — inte semantisk
  likhet (cosine), utan topologisk ekvivalens.

  Strukturell isomorfism = samma in/out-relationsmönster,
  oavsett domän.

  Exempel:
    "fas-kohérens" (neurovetenskap)
    "fas-kohérens" (kvantmekanik)
    → Samma mönster: [oscillerar_med, kopplar, dekohererar_vid]
    → Growth cone bildar kant: "är_strukturellt_isomorf_med"
    → Meta-axiom crystalliseras: "distribuerad koherens"

Meta-lagret:
  Varje gång två axiom kopplas via strukturell resonans
  emergerar ett meta-axiom — en abstraktion ovanpå abstraktionen.
  Det är det tredje lagret:
    Lager 1: Konceptgraf (svamp, mycel, signaltransport)
    Lager 2: Axiom-lager (signaltransport ≅ fas-kohérens)
    Lager 3: Meta-axiom (distribuerad koherens utan central kontroll)

Varför omträning aldrig behövs:
  Modellens vikter är larynxen — de förändras inte.
  Grafen + growth cone är hjärnan — den växer kontinuerligt.
  Ny kunskap läggs till. Ingenting glöms. Allt är spårbart.

Referens: Larynx-problemet (Wikström, 2026), F_bisoc^τ (Wikström, 2026)
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nouse.field.surface import FieldSurface
    from nouse.learning_coordinator import LearningCoordinator

_log = logging.getLogger("nouse.axon_growth_cone")

# ── Konfiguration ─────────────────────────────────────────────────────────────

MIN_RESONANCE_SCORE    = float(os.getenv("NOUSE_GROWTH_MIN_RESONANCE", "0.35"))
META_AXIOM_THRESHOLD   = float(os.getenv("NOUSE_GROWTH_META_THRESHOLD", "0.70"))
MAX_CANDIDATES         = int(os.getenv("NOUSE_GROWTH_MAX_CANDIDATES", "50"))
MAX_SYNAPSES_PER_AXIOM = int(os.getenv("NOUSE_GROWTH_MAX_SYNAPSES", "5"))


# ── Datastrukturer ────────────────────────────────────────────────────────────

@dataclass
class ResonanceMatch:
    """En nod som strukturellt resonerar med axiomet."""
    target_node: str
    target_domain: str
    score: float
    shared_rel_types: list[str]      # gemensamma relationstyper
    shared_primitives: list[str]     # gemensamma universella primitiver i grannskap
    rationale: str


@dataclass
class Synapse:
    """En nybildad koppling mellan axiom och resonerande nod."""
    src: str
    tgt: str
    resonance_score: float
    is_meta_axiom: bool = False
    meta_concept: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class GrowthResult:
    """Resultat av en growth cone-cykel."""
    axiom: str
    domain: str
    candidates_scanned: int = 0
    synapses_formed: list[Synapse] = field(default_factory=list)
    meta_axioms_crystallized: list[str] = field(default_factory=list)


# ── Strukturell resonansmätning ───────────────────────────────────────────────

def _relation_signature(relations: list[dict]) -> set[str]:
    """
    Extrahera relationstyp-signaturen för en nod.
    Två noder med liknande signatur är kandidater för strukturell isomorfism.
    """
    return {str(r.get("type", "")).lower() for r in relations if r.get("type")}


def _neighbor_concepts(relations: list[dict]) -> set[str]:
    """Alla grannkoncept för en nod."""
    return {str(r.get("target", "")).lower() for r in relations if r.get("target")}


def _resonance_score(
    axiom_sig: set[str],
    axiom_neighbors: set[str],
    candidate_sig: set[str],
    candidate_neighbors: set[str],
) -> tuple[float, list[str], list[str]]:
    """
    Beräkna strukturell resonans mellan axiom och kandidatnod.

    Resonans = viktat genomsnitt av:
      1. Relationstyp-överlapp (Jaccard) — mäter funktionell likhet
      2. Grannkoncept-överlapp (Jaccard) — mäter kontextuell likhet

    Returnerar (score, delade_relationstyper, delade_grannar)
    """
    if not axiom_sig or not candidate_sig:
        return 0.0, [], []

    # Jaccard för relationstyper
    shared_rels = axiom_sig & candidate_sig
    union_rels = axiom_sig | candidate_sig
    jaccard_rels = len(shared_rels) / max(1, len(union_rels))

    # Jaccard för grannkoncept
    shared_neighbors = axiom_neighbors & candidate_neighbors
    union_neighbors = axiom_neighbors | candidate_neighbors
    jaccard_neighbors = len(shared_neighbors) / max(1, len(union_neighbors))

    # Viktad kombination — relationstyper väger tyngre (funktionell struktur)
    score = 0.65 * jaccard_rels + 0.35 * jaccard_neighbors

    return (
        round(score, 4),
        sorted(shared_rels),
        sorted(shared_neighbors),
    )


# ── Meta-axiom ────────────────────────────────────────────────────────────────

def _crystallize_meta_axiom(
    axiom: str,
    target: str,
    shared_rels: list[str],
    shared_neighbors: list[str],
) -> str:
    """
    Generera ett meta-axiom från en stark resonansbrygga.

    Meta-axiomet är en ny abstrakt nod som representerar den
    strukturella egenskapen som de två noderna delar.

    Namnkonvention: "META::[delad_rel_1]+[delad_rel_2]"
    """
    if shared_rels:
        core = "+".join(sorted(shared_rels)[:2])
    elif shared_neighbors:
        core = "+".join(sorted(shared_neighbors)[:2])
    else:
        core = f"{axiom[:12]}_{target[:12]}"

    return f"META::{core}"


# ── Growth Cone ────────────────────────────────────────────────────────────────

async def grow(
    axiom: str,
    domain: str,
    field: "FieldSurface",
    coordinator: "LearningCoordinator",
    *,
    min_resonance: float = MIN_RESONANCE_SCORE,
    meta_threshold: float = META_AXIOM_THRESHOLD,
    max_synapses: int = MAX_SYNAPSES_PER_AXIOM,
) -> GrowthResult:
    """
    Growth cone-cykel för ett axiom.

    Söker grafen efter strukturellt isomorfa noder,
    bildar synapser (kanter) vid resonans och
    crystalliserar meta-axiom vid stark resonans.

    Args:
        axiom:        Startkonceptet (ny insikt/axiom)
        domain:       Domän för axiomet
        field:        FieldSurface — grafen att söka och skriva till
        coordinator:  LearningCoordinator — hebbisk plastisitet
        min_resonance: Minsta resonanspoäng för synapsbildning
        meta_threshold: Minsta poäng för meta-axiom-crystallisering
        max_synapses:  Max antal synapser per growth cone-cykel
    """
    result = GrowthResult(axiom=axiom, domain=domain)

    # Hämta axionets egna relationer (signatur)
    try:
        axiom_rels = field.out_relations(axiom)
    except Exception as e:
        _log.warning("Kunde inte hämta relationer för axiom '%s': %s", axiom, e)
        return result

    axiom_sig = _relation_signature(axiom_rels)
    axiom_neighbors = _neighbor_concepts(axiom_rels)

    if not axiom_sig:
        _log.debug("Axiom '%s' har ingen relationssignatur — growth cone avbruten", axiom)
        return result

    # Hämta alla koncept i grafen (exkl. samma domän för korsdomän-fokus)
    try:
        all_concepts = field.concepts()  # lista av {name, domain, ...}
    except Exception as e:
        _log.warning("Kunde inte hämta koncept: %s", e)
        return result

    # Filtrera: hoppa över axiomet självt och noder i samma domän
    candidates = [
        c for c in all_concepts
        if c.get("name") != axiom
        and c.get("domain", "") != domain
    ][:MAX_CANDIDATES]

    result.candidates_scanned = len(candidates)
    _log.info(
        "Growth cone '%s' (%s): skannar %d kandidater",
        axiom, domain, len(candidates)
    )

    # Emit: growth cone startar — animera skannerring i UI
    try:
        from nouse.field.events import emit as _emit
        _emit("growth_probe", axiom=axiom, domain=domain, candidates=len(candidates))
    except Exception:
        pass

    # Beräkna resonans för varje kandidat
    matches: list[ResonanceMatch] = []

    for concept in candidates:
        name = concept.get("name", "")
        c_domain = concept.get("domain", "general")
        if not name:
            continue

        try:
            c_rels = field.out_relations(name)
        except Exception:
            continue

        c_sig = _relation_signature(c_rels)
        c_neighbors = _neighbor_concepts(c_rels)

        score, shared_rels, shared_primitives = _resonance_score(
            axiom_sig, axiom_neighbors,
            c_sig, c_neighbors,
        )

        if score >= min_resonance:
            rationale = (
                f"Strukturell ekvivalens: delade relationstyper={shared_rels}, "
                f"gemensamma grannar={shared_primitives[:3]}"
            )
            matches.append(ResonanceMatch(
                target_node=name,
                target_domain=c_domain,
                score=score,
                shared_rel_types=shared_rels,
                shared_primitives=shared_primitives,
                rationale=rationale,
            ))

    # Sortera efter resonansstyrka, ta topp-N
    matches.sort(key=lambda m: m.score, reverse=True)
    top_matches = matches[:max_synapses]

    _log.info(
        "Growth cone '%s': %d resonansmatcher (av %d kandidater)",
        axiom, len(top_matches), len(candidates)
    )

    # Bilda synapser och crystallisera meta-axiom
    for match in top_matches:
        synapse = Synapse(
            src=axiom,
            tgt=match.target_node,
            resonance_score=match.score,
        )

        why = (
            f"[axon_growth_cone] Strukturell isomorfism detekterad. "
            f"{match.rationale}. "
            f"Domän-brygga: {domain} ↔ {match.target_domain}. "
            f"Resonanspoäng: {match.score:.3f}."
        )

        # Skriv korsdomän-kant till grafen
        try:
            field.add_relation(
                src=axiom,
                rel_type="är_strukturellt_isomorf_med",
                tgt=match.target_node,
                why=why,
                evidence_score=min(1.0, match.score + 0.1),  # resonans är stark signal
                source_tag="axon_growth_cone",
                provenance_class="structural_derivation",
            )

            # Aktivera hebbisk plastisitet
            coordinator.on_fact(
                axiom,
                "är_strukturellt_isomorf_med",
                match.target_node,
                why=why,
                evidence_score=match.score,
                support_count=1,
            )

            result.synapses_formed.append(synapse)
            _log.info(
                "Synaps: %s ↔ %s (score=%.3f, %s→%s)",
                axiom, match.target_node, match.score, domain, match.target_domain,
            )
            # Emit: synaps bildad — blixta ny kant i UI
            try:
                from nouse.field.events import emit as _emit
                _emit(
                    "synapse_formed",
                    src=axiom, tgt=match.target_node,
                    score=match.score,
                    domain_src=domain, domain_tgt=match.target_domain,
                    shared_rels=match.shared_rel_types,
                )
            except Exception:
                pass

        except Exception as e:
            _log.warning("Synapsbildning misslyckades: %s", e)
            continue

        # Meta-axiom vid stark resonans
        if match.score >= meta_threshold:
            meta_name = _crystallize_meta_axiom(
                axiom, match.target_node,
                match.shared_rel_types, match.shared_primitives,
            )
            synapse.is_meta_axiom = True
            synapse.meta_concept = meta_name

            try:
                # Meta-axiomet blir en egen nod i grafen
                field.add_concept(
                    meta_name,
                    domain="meta",
                    granularity=4,          # hög granularitet — abstrakt insikt
                    source="axon_growth_cone",
                )
                # Koppla båda noderna till meta-axiomet
                meta_why = (
                    f"[meta_axiom] '{axiom}' och '{match.target_node}' "
                    f"convergerar i strukturell egenskap: {meta_name}. "
                    f"Domäner: {domain} + {match.target_domain}."
                )
                field.add_relation(
                    src=axiom,
                    rel_type="convergerar_i",
                    tgt=meta_name,
                    why=meta_why,
                    evidence_score=match.score,
                    source_tag="axon_growth_cone",
                    provenance_class="structural_derivation",
                )
                field.add_relation(
                    src=match.target_node,
                    rel_type="convergerar_i",
                    tgt=meta_name,
                    why=meta_why,
                    evidence_score=match.score,
                    source_tag="axon_growth_cone",
                    provenance_class="structural_derivation",
                )

                # Hebbisk inlärning för meta-axiomet
                coordinator.on_fact(
                    axiom, "convergerar_i", meta_name,
                    why=meta_why, evidence_score=match.score, support_count=2,
                )

                result.meta_axioms_crystallized.append(meta_name)
                _log.info("Meta-axiom crystalliserat: '%s'", meta_name)
                # Emit: meta-axiom — guldstjärna dyker upp i UI
                try:
                    from nouse.field.events import emit as _emit
                    _emit(
                        "meta_axiom",
                        name=meta_name,
                        src=axiom, tgt=match.target_node,
                        score=match.score,
                        domain_src=domain, domain_tgt=match.target_domain,
                    )
                except Exception:
                    pass

            except Exception as e:
                _log.warning("Meta-axiom crystallisering misslyckades: %s", e)

    return result


# ── Batch-körning ────────────────────────────────────────────────────────────

async def grow_from_axioms(
    axioms: list[tuple[str, str]],    # [(concept, domain), ...]
    field: "FieldSurface",
    coordinator: "LearningCoordinator",
    *,
    min_resonance: float = MIN_RESONANCE_SCORE,
    meta_threshold: float = META_AXIOM_THRESHOLD,
) -> list[GrowthResult]:
    """
    Kör growth cone för en lista axiom — t.ex. alla nya axiom
    från en decompose_concept()-körning.

    Körs sekventiellt för att undvika lock-konflikter i grafen.
    """
    results = []
    for concept, domain in axioms:
        result = await grow(
            concept, domain, field, coordinator,
            min_resonance=min_resonance,
            meta_threshold=meta_threshold,
        )
        results.append(result)

        # Kort paus mellan growth cone-cykler
        await asyncio.sleep(0.05)

    total_synapses = sum(len(r.synapses_formed) for r in results)
    total_meta = sum(len(r.meta_axioms_crystallized) for r in results)
    _log.info(
        "grow_from_axioms klar: %d axiom, %d synapser, %d meta-axiom",
        len(axioms), total_synapses, total_meta,
    )
    return results
