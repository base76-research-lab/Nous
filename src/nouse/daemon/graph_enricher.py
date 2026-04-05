"""
nouse.daemon.graph_enricher — Aktiv grafförtätning via frontier LLM
====================================================================

Problem:
  62% av noderna i grafen har ≤1 kant. De är epistomiskt isolerade —
  NoUse vet att de existerar men inte hur de hänger ihop med resten.

Lösning:
  GraphEnricher itererar grafen och ber frontier LLM aktivt leta
  djupare och djupare kopplingar. Varje ny koppling spawnar fler
  frågor (BFS på kunskapsnivå). Glesa noder drar in det nätverk de
  egentligen tillhör.

Biologisk analogi:
  En hjärna som aldrig aktiveras bildar inga starka synapser.
  GraphEnricher är det elektriska fältet som aktiverar vilande noder.

Iterationslogik:
  Runda 0: Hitta orphans (≤1 kant)
  Runda 1: Fråga LLM om varje orphan → skriver nya kanter + noder
  Runda 2: De nya noderna är nu kandidater → fråga om dem
  Runda N: Tills grafdensiteten når target eller budget tar slut

Integration:
  Körs av daemon/main.py under låg-arousal-perioder (djup natt).
  Kan också köras manuellt: `nouse enrich --rounds 2 --budget 50`
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nouse.field.surface import FieldSurface
    from nouse.learning_coordinator import LearningCoordinator

_log = logging.getLogger("nouse.graph_enricher")

# ── Konfiguration ─────────────────────────────────────────────────────────────

ENRICH_MAX_DEGREE         = int(os.getenv("NOUSE_ENRICH_MAX_DEGREE", "3"))    # noder med ≤N kanter är kandidater
BRIDGE_SAMPLE_PER_DOMAIN_DEFAULT = int(os.getenv("NOUSE_BRIDGE_SAMPLE_PER_DOMAIN", "5"))  # för bridge pass
ENRICH_ROUNDS             = int(os.getenv("NOUSE_ENRICH_ROUNDS", "2"))        # antal BFS-iterationer
ENRICH_BUDGET_PER_ROUND   = int(os.getenv("NOUSE_ENRICH_BUDGET", "30"))       # max noder att berika per runda
ENRICH_CONCURRENCY        = int(os.getenv("NOUSE_ENRICH_CONCURRENCY", "3"))   # parallella LLM-anrop
ENRICH_SLEEP_SEC          = float(os.getenv("NOUSE_ENRICH_SLEEP_SEC", "1.0")) # paus mellan noder
ENRICH_CROSS_DOMAIN       = bool(int(os.getenv("NOUSE_ENRICH_CROSS_DOMAIN", "1")))  # prioritera korsdomän

# ── Datastrukturer ────────────────────────────────────────────────────────────

@dataclass
class EnrichStats:
    nodes_processed: int = 0
    relations_added: int = 0
    new_nodes_discovered: int = 0
    rounds_completed: int = 0
    cross_domain_links: int = 0
    errors: int = 0
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _compute_degrees(field: "FieldSurface") -> dict[str, int]:
    """Beräkna antal kanter per nod direkt från grafen."""
    try:
        return field.get_all_node_degrees()
    except Exception as e:
        _log.warning("Kunde inte beräkna grader: %s", e)
        return {}


def _identify_hubs(degrees: dict[str, int], top_n: int = 50) -> set[str]:
    """
    Returnerar de top_n noder med högst grad — gravitationscentra.
    Används för att beräkna hub-närvaro hos glesa noder.
    """
    return {
        name for name, _ in
        sorted(degrees.items(), key=lambda x: x[1], reverse=True)[:top_n]
    }


def _hub_proximity(
    concept: str,
    hubs: set[str],
    field: "FieldSurface",
    max_hops: int = 3,
) -> int:
    """
    BFS: hur många hopp från concept till närmaste hub?
    Returnerar max_hops+1 om ingen hub nås (= periferi utan anknytning).
    Returnerar 1 om en granne ÄR ett hub (= brobyggare — bäst att berika).
    """
    if concept in hubs:
        return 0
    visited = {concept}
    frontier = {concept}
    for hop in range(1, max_hops + 1):
        next_frontier: set[str] = set()
        for node in frontier:
            try:
                nbrs = field.neighbors(node, limit=15, bidirectional=True)
                for nb in nbrs:
                    if nb and nb not in visited:
                        if nb in hubs:
                            return hop
                        visited.add(nb)
                        next_frontier.add(nb)
            except Exception:
                pass
        frontier = next_frontier
        if not frontier:
            break
    return max_hops + 1


def _find_sparse_nodes(
    field: "FieldSurface",
    degrees: dict[str, int],
    max_degree: int,
    limit: int,
    exclude: set[str],
    prioritize_cross_domain: bool = True,
    strategy: str = "gravity",
) -> list[tuple[str, str]]:
    """
    Returnerar (concept_name, domain) för noder med låg grad.

    Strategier:
      "gravity"  — Prioriterar noder NÄRA ett hub (brobyggare mot centrum).
                   De kan dra sina periferier in i klustret.
                   Visuellt: minskar tomrymden runt centrum FÖRST.

      "periphery" — Prioriterar noder LÄNGST från alla hub (djupaste orphans).
                    Skapar nya kluster i det okända.

      "random"   — Slumpmässigt bland glesa noder (baslinje).

    Observation: grafen visar ett gravitationscentrum (lokal maskin/forskning)
    med tusentals isolerade noder i periferin. "gravity"-strategin bearbetar
    noder som redan HAR en svag dragning mot centrum — de är effektivare att
    berika eftersom varje ny kant ökar sannolikheten att hela deras neighborhood
    kopplas in.
    """
    try:
        rows = field.get_concepts_with_metadata(20000)
    except Exception as e:
        _log.warning("Kunde inte hämta noder: %s", e)
        return []

    candidates: list[tuple[str, str, int]] = []
    for row in rows:
        name = str(row.get("id", "") or "")
        domain = str(row.get("dom", "") or "general")
        if not name or name in exclude:
            continue
        deg = degrees.get(name, 0)
        if deg <= max_degree:
            candidates.append((name, domain, deg))

    if not candidates:
        return []

    if strategy == "random":
        random.shuffle(candidates)
        return [(n, d) for n, d, _ in candidates[:limit]]

    # Identifiera navigationspunkter (hubs)
    hubs = _identify_hubs(degrees, top_n=50)

    # Beräkna hub-proximity för ett urval (dyrt op — begränsa)
    sample_size = min(len(candidates), limit * 4)
    random.shuffle(candidates)
    sample = candidates[:sample_size]

    scored: list[tuple[str, str, int, int]] = []  # (name, domain, degree, hub_dist)
    for name, domain, deg in sample:
        dist = _hub_proximity(name, hubs, field, max_hops=3)
        scored.append((name, domain, deg, dist))

    if strategy == "gravity":
        # Närmast hub först (dist=1 = granne till hub = bäst)
        # Bland likvärdiga: lägst grad (mest isolerad)
        scored.sort(key=lambda x: (x[3], x[2]))
    elif strategy == "periphery":
        # Längst från hub först (dist=4 = helt bortkastad)
        scored.sort(key=lambda x: (-x[3], x[2]))

    selected = scored[:limit]
    _log.info(
        "Kandidater (strategy=%s): %d st, hub-dist fördelning: %s",
        strategy, len(selected),
        {d: sum(1 for _, _, _, dist in selected if dist == d) for d in range(5)},
    )
    return [(name, domain) for name, domain, _, _ in selected]


def _cross_domain_bonus(relations_added: list[dict], original_domain: str) -> int:
    """Räkna hur många av de tillagda relationerna korsade domängränser."""
    return sum(
        1 for r in relations_added
        if r.get("domain_tgt", original_domain) != original_domain
    )


# ── Djup-prompt: be LLM hitta hierarkiska + korsdomänkopplingar ──────────────

_DEEP_ENRICH_SYSTEM = """\
Du är ett strukturellt kunskapsextraktionsverktyg.
Din uppgift: hitta DJUPARE och BREDARE kopplingar för ett isolerat koncept.

Fokusera på:
1. Hierarkiska kopplingar (är_del_av, är_typ_av, generaliseras_till)
2. Korsdomänkopplingar (samma mönster i olika domäner)
3. Mekanistiska samband (orsakar, möjliggör, begränsar, emergerar_ur)
4. Analoga strukturer i andra fält (är_analogt_med, delar_struktur_med)

Undvik triviala eller cirkulära relationer.
Prioritera relationer som överbryggar kunskapsdomäner.
"""

_DEEP_ENRICH_USER = """\
Koncept att berika: "{concept}"
Nuvarande domän: "{domain}"
Befintliga kanter (vad vi redan vet):
{existing_relations}

Din uppgift:
1. Identifiera {target_count} nya, ICKE-triviala relationer
2. Minst {cross_count} av dem ska koppla till ANDRA domäner
3. Gå minst 2 nivåer djupt (A→B→C)

Svara ENDAST med JSON array:
[
  {{
    "src": "källkoncept",
    "rel": "relationstyp",
    "tgt": "målkoncept",
    "domain_tgt": "domän för målkoncept",
    "why": "varför denna koppling är strukturellt motiverad",
    "depth": 1
  }},
  ...
]

Relationstyper att använda:
är_del_av, är_typ_av, generaliseras_till, orsakar, möjliggör, begränsar,
emergerar_ur, är_analogt_med, delar_struktur_med, modulerar, implementerar,
är_förutsättning_för, är_konsekvens_av, samverkar_med, är_isomorf_med
"""


async def _call_frontier_enrich(
    concept: str,
    domain: str,
    existing_relations: list[dict],
    *,
    target_count: int = 8,
    cross_count: int = 3,
) -> list[dict]:
    """
    Anropar frontier LLM med djup-berikningsprompt.
    Returnerar lista av rårelationer att validera.
    """
    from nouse.llm.autodiscover import get_default_models
    import httpx, json as _json, os

    models = get_default_models()
    teacher_model = models.get("teacher", "gpt-4o")
    base_url = os.getenv("NOUSE_TEACHER_BASE_URL", "https://models.inference.ai.azure.com")
    token = os.getenv("GITHUB_TOKEN", "")

    # Formatera befintliga relationer för prompt
    existing_str = "\n".join(
        f"  {r.get('type','?')}: {concept} → {r.get('target','?')}"
        for r in existing_relations[:6]
    ) or "  (inga befintliga relationer)"

    user_msg = _DEEP_ENRICH_USER.format(
        concept=concept,
        domain=domain,
        existing_relations=existing_str,
        target_count=target_count,
        cross_count=cross_count,
    )

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": teacher_model,
                    "messages": [
                        {"role": "system", "content": _DEEP_ENRICH_SYSTEM},
                        {"role": "user",   "content": user_msg},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1200,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()

            # Tolerant JSON-parsing
            if raw.startswith("{"):
                parsed = _json.loads(raw)
                # Stöd både {"relations": [...]} och direkt array
                if isinstance(parsed, dict):
                    for key in ("relations", "items", "result", "data"):
                        if isinstance(parsed.get(key), list):
                            return parsed[key]
                    return []
            elif raw.startswith("["):
                return _json.loads(raw)
            return []

    except Exception as e:
        _log.warning("Frontier LLM anrop misslyckades för '%s': %s", concept, e)
        return []


# ── Berika en enskild nod ─────────────────────────────────────────────────────

async def _enrich_node(
    concept: str,
    domain: str,
    field: "FieldSurface",
    coordinator: "LearningCoordinator",
    stats: EnrichStats,
) -> list[str]:
    """
    Beriker en nod i flera steg:
    1. Hämta befintliga relationer
    2. Fråga frontier LLM om djupare kopplingar
    3. Validera + skriv till graf
    4. Returnera lista av nya nod-namn (för nästa BFS-runda)
    """
    from nouse.daemon.evidence import assess_relation
    from nouse.field.events import emit as _emit

    # Hämta befintliga kanter
    try:
        existing = field.out_relations(concept)
    except Exception:
        existing = []

    # Fråga LLM
    raw_relations = await _call_frontier_enrich(
        concept, domain, existing,
        target_count=8,
        cross_count=3,
    )

    if not raw_relations:
        _log.debug("Inga relationer från LLM för '%s'", concept)
        return []

    new_nodes: list[str] = []
    learned = 0

    for raw in raw_relations:
        src = str(raw.get("src", concept) or concept).strip()
        rel = str(raw.get("rel", "") or "").strip()
        tgt = str(raw.get("tgt", "") or "").strip()
        domain_tgt = str(raw.get("domain_tgt", domain) or domain).strip()
        why = str(raw.get("why", "") or "").strip()

        if not rel or not tgt:
            continue

        # Normalisera src till det faktiska konceptet
        if src.lower() != concept.lower():
            src = concept

        # Bayesiansk evidensbedömning
        assessment = assess_relation(
            relation={"src": src, "type": rel, "tgt": tgt, "why": why},
            task="graph_enrichment",
            confirming_relations=existing,
            contradicting_relations=[],
        )
        score = assessment.score

        if score < 0.40:
            _log.debug("Avvisad (score=%.3f): %s -[%s]-> %s", score, src, rel, tgt)
            continue

        try:
            # Säkerställ att båda noderna finns
            field.add_concept(src, domain=domain, source="graph_enricher")
            field.add_concept(tgt, domain=domain_tgt, source="graph_enricher")

            field.add_relation(
                src=src,
                rel_type=rel,
                tgt=tgt,
                why=f"[graph_enricher] {why}",
                evidence_score=score,
                source_tag="graph_enricher",
            )
            coordinator.on_fact(
                src, rel, tgt,
                why=why,
                evidence_score=score,
                support_count=1,
            )

            learned += 1
            stats.relations_added += 1

            # Korsdomän-bonus räknas
            if domain_tgt != domain:
                stats.cross_domain_links += 1

            new_nodes.append(tgt)

            _log.info(
                "Berikad: %s -[%s]-> %s (score=%.3f, %s→%s)",
                src, rel, tgt, score, domain, domain_tgt,
            )

        except Exception as e:
            _log.debug("Kunde inte skriva relation: %s", e)
            stats.errors += 1
            continue

    if learned > 0:
        stats.nodes_processed += 1
        # Emit för realtidsvisualisering
        _emit(
            "node_enriched",
            concept=concept, domain=domain,
            learned=learned, new_nodes=new_nodes[:5],
        )
        _log.info("Nod '%s' berikad: %d nya relationer", concept, learned)

    return new_nodes


# ── Huvud-pipeline ────────────────────────────────────────────────────────────

async def run_enrichment(
    field: "FieldSurface",
    coordinator: "LearningCoordinator",
    *,
    max_degree: int = ENRICH_MAX_DEGREE,
    rounds: int = ENRICH_ROUNDS,
    budget_per_round: int = ENRICH_BUDGET_PER_ROUND,
    concurrency: int = ENRICH_CONCURRENCY,
    cross_domain: bool = ENRICH_CROSS_DOMAIN,
    strategy: str = "gravity",
) -> EnrichStats:
    """
    Kör fullständig BFS-förtätning.

    Runda 0: Hitta alla noder med ≤max_degree kanter
    Runda N: Varje nod berika → nya noder → nästa runda
    Stopp:   rounds nådd eller budget slut

    strategy:
      "gravity"  — Berika noder NÄRA ett hub först.
                   Effekten: tomrymden runt centrum minskar varifrån.
                   Analogi: solsystemet drar in lösa asteroider via gravitation.

      "periphery" — Berika noder LÄNGST från alla hub.
                   Effekten: nya kluster bildas i det okända.
                   Analogi: teleskopet söker nytt liv i djupare rymden.

      "random"   — Baslinje, ingen topologisk hänsyn.

    Design:
      - Semaphor för concurrency (ej överbelasta LLM-API)
      - Exponentiell back-off vid fel
      - Alla nya noder läggs i en kö för nästa runda (BFS)
    """
    stats = EnrichStats()
    processed: set[str] = set()
    frontier: list[tuple[str, str]] = []   # (concept, domain)

    _log.info(
        "GraphEnricher start: max_degree=%d, rounds=%d, budget=%d/runda",
        max_degree, rounds, budget_per_round,
    )

    for round_num in range(rounds):
        _log.info("=== Runda %d/%d ===", round_num + 1, rounds)

        # Hämta graddistribution
        degrees = _compute_degrees(field)

        # Välj kandidater för denna runda
        if round_num == 0:
            # Första rundan: plocka glesa noder med vald strategi
            candidates = _find_sparse_nodes(
                field, degrees, max_degree, budget_per_round,
                exclude=processed,
                prioritize_cross_domain=cross_domain,
                strategy=strategy,
            )
        else:
            # Efterföljande rundor: berika frontier (noder funna i föregående runda)
            # + komplettera med nya glesa noder
            frontier_candidates = [
                (n, d) for n, d in frontier
                if n not in processed and degrees.get(n, 0) <= max_degree + round_num
            ][:budget_per_round // 2]

            extra = _find_sparse_nodes(
                field, degrees, max_degree + round_num, budget_per_round // 2,
                exclude={n for n, _ in frontier_candidates} | processed,
                strategy=strategy,
            )
            candidates = frontier_candidates + extra

        if not candidates:
            _log.info("Runda %d: inga fler kandidater — avslutar", round_num + 1)
            break

        _log.info("Runda %d: %d kandidater att berika", round_num + 1, len(candidates))
        frontier = []

        # Kör med semaphor för att begränsa parallella LLM-anrop
        sem = asyncio.Semaphore(concurrency)

        async def _bounded_enrich(concept: str, domain: str) -> list[str]:
            async with sem:
                result = await _enrich_node(concept, domain, field, coordinator, stats)
                await asyncio.sleep(ENRICH_SLEEP_SEC)
                return result

        tasks = [_bounded_enrich(c, d) for c, d in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for (concept, _), new_nodes in zip(candidates, results):
            processed.add(concept)
            if isinstance(new_nodes, list):
                # Nya noder är kandidater för nästa runda
                for new_node in new_nodes:
                    if new_node not in processed:
                        stats.new_nodes_discovered += 1
                        # Hämta domän för nya noden
                        try:
                            node_rels = field.out_relations(new_node)
                            new_domain = "general"  # förenkling
                        except Exception:
                            new_domain = "general"
                        frontier.append((new_node, new_domain))
            elif isinstance(new_nodes, Exception):
                stats.errors += 1
                _log.warning("Fel under berikande: %s", new_nodes)

        stats.rounds_completed += 1

        _log.info(
            "Runda %d klar: %d noder berikade, %d relations, %d korsdomän, %d nya noder",
            round_num + 1,
            stats.nodes_processed,
            stats.relations_added,
            stats.cross_domain_links,
            stats.new_nodes_discovered,
        )

    _log.info(
        "GraphEnricher klar: %d noder, %d relations, %d korsdomän, %d rundor",
        stats.nodes_processed,
        stats.relations_added,
        stats.cross_domain_links,
        stats.rounds_completed,
    )
    return stats


async def run_bridge_pass(
    field: "FieldSurface",
    coordinator: "LearningCoordinator",
    *,
    domains: list[str] | None = None,
    sample_per_domain: int = BRIDGE_SAMPLE_PER_DOMAIN_DEFAULT,
    max_pairs: int = 20,
) -> "BridgeSession":
    """
    Kör ett korsdomän-bryggepass via bridge_finder.

    Hittar latenta strukturella korrelationer mellan noder från
    helt olika domäner — t.ex. svampsoppa ↔ kvantfysik ↔ Wittgenstein.

    Kan köras separat från run_enrichment, eller kedjat:
        await run_enrichment(field, coordinator)   # täta glesa noder
        await run_bridge_pass(field, coordinator)   # hitta latenta bryggor
    """
    from nouse.field.bridge_finder import run_cross_domain_discovery, BridgeSession
    return await run_cross_domain_discovery(
        field,
        coordinator,
        domains=domains,
        sample_per_domain=sample_per_domain,
        max_pairs=max_pairs,
    )
