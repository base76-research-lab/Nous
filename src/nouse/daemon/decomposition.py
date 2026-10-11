"""
nouse.daemon.decomposition — Rekursiv Epistemisk Nedbrytning
=============================================================
Implementerar "nollanalys": ta en insikt och bryt ner den rekursivt
tills den når universella primitiver (domänagnostiska atomkoncept).

På vägen uppstår axiom: sub-koncept som förekommer i 2+ domäner är
naturliga bryggor. Dessa läggs till grafen som strukturellt motiverade
kanter — inte extraherade från text, utan EMERGENTA ur topologi.

Myceliemetaforen:
  Domäner = träd i skogen (synliga, domänspecifika)
  Sub-koncept = rötter (djupare, delvis domänöverskridande)
  Universella primitiver = mycel (osynligt, kopplar allt)
  Axiom = mykorrhiza-kopplingar (explicita broar via mycelet)

Nollpunkten:
  Ett koncept har nått "noll" när det inte längre tillhör EN domän —
  när det är ett universellt primitiv som entropi, gradient, feedback.
  Dessa är inte tomma. De är det som kopplar allt.

Skillnaden mot en relationsdatabas:
  En relations-db lagrar den ENKLASTE vägen mellan två punkter.
  Denna modul hittar EMERGENS — broar som inte var lagrade men
  som finns i topologin om man gräver tillräckligt djupt.

Koppling till F_bisoc^τ (Creative Free Energy):
  Partial decompositions läggs i en inkubationskö.
  NightRun bearbetar kön efter T* cykler (incubation threshold).
  Vid tillräcklig inkubation → temporal bisociation kan uppstå.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nouse.field.surface import FieldSurface
    from nouse.limbic.signals import LimbicState

from nouse.llm.model_router import order_models_for_workload, record_model_result
from nouse.llm.policy import resolve_model_candidates
from nouse.llm.default_models import is_missing_model_error, model_for_role
from nouse.ollama_client.client import AsyncOllama

_log = logging.getLogger("nouse.decomposition")

# ── Konfiguration ─────────────────────────────────────────────────────────────

DECOMP_MODEL = (
    os.getenv("NOUSE_MODEL_DECOMP")
    or os.getenv("NOUSE_DECOMP_MODEL")
    or os.getenv("NOUSE_OLLAMA_MODEL")
    or os.getenv("NOUSE_MODEL_DEFAULT")
    or "qwen3.5:9b"
).strip()


def resolve_decomp_model() -> str:
    """Dynamisk decomp-modell (samma kedja, evaluerad vid anrop)."""
    return model_for_role(
        "decomp",
        os.getenv("NOUSE_DECOMP_MODEL"),
        os.getenv("NOUSE_OLLAMA_MODEL"),
    )
DECOMP_TIMEOUT_SEC = float(os.getenv("NOUSE_DECOMP_TIMEOUT_SEC", "20"))
MAX_DEPTH = int(os.getenv("NOUSE_DECOMP_MAX_DEPTH", "5"))
MIN_DOMAIN_CONVERGENCE = int(os.getenv("NOUSE_DECOMP_MIN_CONVERGENCE", "2"))

_INCUBATION_FILE = Path.home() / ".local" / "share" / "nouse" / "decomp_incubation.json"

# ── Universella primitiver (seedade, utökas automatiskt) ─────────────────────
# Dessa är myceliets knutpunkter: domänagnostiska axiom som förekommer överallt.
# När ett sub-koncept uppnår MIN_DOMAIN_CONVERGENCE domäner → promoveras hit.

_SEED_PRIMITIVES: set[str] = {
    "entropi", "entropy",
    "gradient", "gradient descent",
    "oscillation", "oscillation", "svängning",
    "feedback", "återkoppling",
    "prediktionsfel", "prediction error",
    "tröskel", "threshold",
    "symmetri", "symmetry",
    "emergens", "emergence",
    "självorganisering", "self-organization",
    "information", "information content",
    "energi", "energy",
    "fas", "phase",
    "cykel", "cycle",
    "attraktor", "attractor",
    "komplexitet", "complexity",
    "rekursion", "recursion",
    "hierarki", "hierarchy",
    "nätverk", "network",
    "signal", "noise",
    "invariant",
}


# ── Datastrukturer ────────────────────────────────────────────────────────────

@dataclass
class DecompositionNode:
    concept: str
    domain: str
    depth: int
    sub_concepts: list["DecompositionNode"] = field(default_factory=list)
    is_primitive: bool = False
    cross_domain_appearances: list[str] = field(default_factory=list)  # andra domäner


@dataclass
class AxiomCandidate:
    """Ett sub-koncept som förekommer i 2+ domäner — en potentiell brygga."""
    concept: str
    domains: list[str]                  # alla domäner det förekommer i
    bridge_score: float                 # antal domäner / MAX_DEPTH (normaliserat)
    discovery_depth: int                # på vilket djup i nedbrytningen det hittades
    source_insight: str                 # ursprungskonceptet
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PartialDecomposition:
    """En påbörjad nedbrytning som läggs i inkubationskön."""
    concept: str
    domain: str
    partial_tree: dict[str, Any]        # serialiserat DecompositionNode-träd
    axiom_candidates: list[dict]        # serialiserade AxiomCandidates
    cycles_in_graph: int                # hur många brain-cykler sen skapandet
    topo_similarity: float              # τ till närmaste domän (för T*-beräkning)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Primitiv-registret ────────────────────────────────────────────────────────

class UniversalPrimitiveRegistry:
    """
    Spårar universella primitiver — myceliets knutpunkter.
    Seedat med kända primitiver. Utökas när sub-koncept
    når tillräcklig domänkonvergens.
    """

    def __init__(self) -> None:
        self._primitives: set[str] = set(_SEED_PRIMITIVES)
        self._candidate_count: dict[str, list[str]] = {}  # koncept → domänlista

    def is_primitive(self, concept: str) -> bool:
        return concept.lower() in self._primitives

    def record_appearance(self, concept: str, domain: str) -> bool:
        """
        Registrera att ett koncept förekommer i en domän.
        Returnerar True om konceptet just promoverades till primitiv.
        """
        key = concept.lower()
        if key not in self._candidate_count:
            self._candidate_count[key] = []
        if domain not in self._candidate_count[key]:
            self._candidate_count[key].append(domain)

        if (
            len(self._candidate_count[key]) >= MIN_DOMAIN_CONVERGENCE
            and key not in self._primitives
        ):
            self._primitives.add(key)
            _log.info(f"Ny universell primitiv: '{concept}' (förekommer i {self._candidate_count[key]})")
            return True
        return False

    def get_domains(self, concept: str) -> list[str]:
        return self._candidate_count.get(concept.lower(), [])

    @property
    def all_primitives(self) -> set[str]:
        return set(self._primitives)


# Singleton-registry
_registry = UniversalPrimitiveRegistry()


# ── Kärnlogik ─────────────────────────────────────────────────────────────────

_DECOMP_PROMPT = """\
Du är en analytisk kunskapsdekomp ositör. Din uppgift är att bryta ner ett koncept \
till dess STRUKTURELLA beståndsdelar — inte synonymer, inte exempel, utan \
faktiska mekanistiska eller ontologiska sub-komponenter.

Koncept: "{concept}"
Domän: "{domain}"
Nuvarande nedbrytningsdjup: {depth}/{max_depth}

Svara ENBART med ett JSON-objekt:
{{
  "sub_concepts": ["koncept1", "koncept2", "koncept3"],
  "reasoning": "kort motivering varför dessa är de atomära beståndsdelarna"
}}

Regler:
- Max 4 sub-koncept
- Sub-koncepten ska vara MER atomära än originalet
- Undvik synonymer och omformuleringar
- Om konceptet inte kan brytas ned meningsfullt: returnera tom lista
- Tänk mekanistiskt: vad MÖJLIGGÖR detta koncept?
"""


async def _decompose_one(
    concept: str,
    domain: str,
    depth: int,
    client: AsyncOllama,
    model: str,
) -> list[str]:
    """Anropa LLM för att bryta ner ett enskilt koncept."""
    prompt = _DECOMP_PROMPT.format(
        concept=concept,
        domain=domain,
        depth=depth,
        max_depth=MAX_DEPTH,
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            b76_meta={"workload": "decomposition"},
        )
        raw = resp.message.content or ""
        # Extrahera JSON
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
            subs = data.get("sub_concepts", [])
            return [str(s).strip() for s in subs if str(s).strip()]
    except Exception as e:
        if is_missing_model_error(e):
            _log.warning(f"Decomposition: modell saknas ({model}) — hoppar över ({e})")
        else:
            _log.debug(f"Decomposition LLM-fel ({concept}): {e}")
    return []


async def decompose_concept(
    field: "FieldSurface",
    concept: str,
    domain: str,
    max_depth: int = MAX_DEPTH,
) -> tuple[DecompositionNode, list[AxiomCandidate]]:
    """
    Rekursivt bryt ner ett koncept till universella primitiver.

    Returnerar:
      - DecompositionNode: hela nedbrytningsträdet
      - list[AxiomCandidate]: alla hittade bryggor (sub-koncept i 2+ domäner)
    """
    client = AsyncOllama(timeout_sec=DECOMP_TIMEOUT_SEC)
    candidates: list[str] = [resolve_decomp_model()]
    candidates = order_models_for_workload("decomposition", candidates) or candidates

    axioms: list[AxiomCandidate] = []
    model = candidates[0] if candidates else DECOMP_MODEL

    # Hämta befintliga domäner i grafen för korsdomän-kontroll
    try:
        known_domains = set(field.domains())
    except Exception:
        known_domains = {domain}

    async def _recurse(node: DecompositionNode) -> None:
        if node.depth >= max_depth or _registry.is_primitive(node.concept):
            node.is_primitive = _registry.is_primitive(node.concept)
            return

        sub_names = await _decompose_one(node.concept, node.domain, node.depth, client, model)
        if not sub_names:
            return

        for sub_name in sub_names:
            sub_node = DecompositionNode(
                concept=sub_name,
                domain=node.domain,
                depth=node.depth + 1,
            )

            # Korsdomän-kontroll: förekommer detta sub-koncept i andra domäner?
            cross_domains: list[str] = []
            for d in known_domains:
                if d == node.domain:
                    continue
                try:
                    existing = field.find_concept(sub_name, domain=d)
                    if existing:
                        cross_domains.append(d)
                        _registry.record_appearance(sub_name, d)
                except Exception:
                    pass

            # Registrera även i nuvarande domän
            _registry.record_appearance(sub_name, node.domain)
            all_domains = [node.domain] + cross_domains

            if len(all_domains) >= MIN_DOMAIN_CONVERGENCE:
                # Axiom funnet — detta är ett mycel-knutpunkt
                bridge_score = min(1.0, len(all_domains) / 5.0)
                axiom = AxiomCandidate(
                    concept=sub_name,
                    domains=all_domains,
                    bridge_score=bridge_score,
                    discovery_depth=node.depth + 1,
                    source_insight=concept,
                )
                axioms.append(axiom)
                sub_node.cross_domain_appearances = cross_domains
                _log.info(
                    f"Axiom funnet: '{sub_name}' bridges {all_domains} "
                    f"(djup={node.depth+1}, score={bridge_score:.2f})"
                )

            node.sub_concepts.append(sub_node)

            # Rekursera om inte primitiv
            if not _registry.is_primitive(sub_name):
                await _recurse(sub_node)

    root = DecompositionNode(concept=concept, domain=domain, depth=0)
    await _recurse(root)
    record_model_result("decomposition", model, success=True, timeout=False)
    return root, axioms


def promote_axioms_to_graph(
    field: "FieldSurface",
    axioms: list[AxiomCandidate],
    coordinator: "Any | None" = None,
) -> int:
    """
    Lägg till bekräftade axiom som kanter i grafen.
    Returnerar antal tillagda kanter.

    Axiom är INTE textextraherade relationer — de är strukturellt
    motiverade broar som uppstår ur topologin. De skrivs därför med
    provenance_class="structural_derivation" och takas av add_relation()
    till det parametriska taket; högre evidens kräver en separat
    confirm_relation() med namngiven källa.

    Om coordinator skickas med körs AxonGrowthCone efter att axiom lagts till
    i grafen — growth cone söker korsdomän-isomorfer för varje nytt axiom.
    """
    import asyncio
    from nouse.field import axon_growth_cone

    added = 0
    new_axiom_nodes: list[tuple[str, str]] = []   # (concept, domain) för growth cone

    for axiom in axioms:
        if axiom.bridge_score < 0.3:
            continue
        # Skapa korsdomän-kanter för varje domänpar
        for i, d_a in enumerate(axiom.domains):
            for d_b in axiom.domains[i+1:]:
                try:
                    field.add_relation(
                        f"{d_a}::{axiom.concept}",
                        "är_universellt_primitiv_i",
                        f"{d_b}::{axiom.concept}",
                        why=(
                            f"Axiom: '{axiom.concept}' förekommer i '{d_a}' och '{d_b}'. "
                            f"Hittades via rekursiv nedbrytning av '{axiom.source_insight}' "
                            f"på djup {axiom.discovery_depth}."
                        ),
                        evidence_score=0.6 + axiom.bridge_score * 0.3,
                        domain_src=d_a,
                        domain_tgt=d_b,
                        assumption_flag=False,
                        source_tag="decomposition_axiom",
                        provenance_class="structural_derivation",
                    )
                    added += 1
                    # Registrera axiom-nod för growth cone-körning efter loopen
                    new_axiom_nodes.append((axiom.concept, d_a))
                except Exception as e:
                    _log.debug(f"Kunde inte lägga till axiom-kant: {e}")

    # AxonGrowthCone — aktiveras om coordinator är satt
    if coordinator is not None and new_axiom_nodes:
        unique_axioms = list({(c, d) for c, d in new_axiom_nodes})
        _log.info(
            "AxonGrowthCone: startar för %d unika axiom-noder", len(unique_axioms)
        )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Vi är redan inuti en event loop (t.ex. daemon) → skapa task
                asyncio.ensure_future(
                    axon_growth_cone.grow_from_axioms(unique_axioms, field, coordinator)
                )
            else:
                loop.run_until_complete(
                    axon_growth_cone.grow_from_axioms(unique_axioms, field, coordinator)
                )
        except Exception as e:
            _log.warning("AxonGrowthCone misslyckades: %s", e)

    return added


# ── Inkubationskö (F_bisoc^τ) ─────────────────────────────────────────────────

def _load_incubation() -> list[dict]:
    if _INCUBATION_FILE.exists():
        try:
            return json.loads(_INCUBATION_FILE.read_text())
        except Exception:
            pass
    return []


def _save_incubation(queue: list[dict]) -> None:
    _INCUBATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    _INCUBATION_FILE.write_text(json.dumps(queue, indent=2))


def queue_for_incubation(partial: PartialDecomposition) -> None:
    """Lägg en partiell nedbrytning i inkubationskön för senare bearbetning."""
    queue = _load_incubation()
    queue.append(asdict(partial))
    _save_incubation(queue)
    _log.info(f"Inkubationskö: '{partial.concept}' lagt till (τ={partial.topo_similarity:.2f})")


def incubation_ready(partial: dict, current_cycle: int) -> bool:
    """
    Beräkna T* och avgör om en partiell nedbrytning är redo för temporal bisociation.

    T* = (T_min / γ) × ln(1 / (1 - topo_similarity))
    Från Creative Free Energy paper (Wikström, 2026).
    """
    import math
    T_MIN = float(os.getenv("NOUSE_FBISOC_T_MIN", "9"))
    GAMMA = float(os.getenv("NOUSE_FBISOC_GAMMA", "0.5"))
    tau = float(partial.get("topo_similarity", 0.5))

    if tau >= 1.0:
        return True  # alltid redo
    if tau <= 0.0:
        return False  # aldrig redo

    try:
        t_star = (T_MIN / GAMMA) * math.log(1.0 / (1.0 - tau))
    except (ValueError, ZeroDivisionError):
        return False

    cycles_since = current_cycle - int(partial.get("cycles_in_graph", 0))
    return cycles_since >= t_star


def process_incubation_queue(
    field: "FieldSurface",
    current_cycle: int,
) -> list[AxiomCandidate]:
    """
    Bearbeta inkubationskön under NightRun.
    Returnerar axiom som mognat och är redo att läggas till grafen.
    """
    queue = _load_incubation()
    ready_axioms: list[AxiomCandidate] = []
    remaining: list[dict] = []

    for partial in queue:
        if incubation_ready(partial, current_cycle):
            for ac in partial.get("axiom_candidates", []):
                ready_axioms.append(AxiomCandidate(**ac))
            _log.info(
                f"Inkubation klar: '{partial.get('concept')}' "
                f"(τ={partial.get('topo_similarity', '?')}, "
                f"cykler={current_cycle - partial.get('cycles_in_graph', 0)})"
            )
        else:
            remaining.append(partial)

    _save_incubation(remaining)
    return ready_axioms


# ── Offentligt API ────────────────────────────────────────────────────────────

async def run_decomposition_burst(
    field: "FieldSurface",
    limbic: "LimbicState",
    concept: str | None = None,
    domain: str | None = None,
) -> int:
    """
    Kör en nedbrytningsburst: välj ett koncept, bryt ner det,
    hitta axiom, lägg till i grafen.

    Returnerar antal nya axiom som lades till grafen.
    """
    # Välj koncept om inget angivet
    if not concept or not domain:
        try:
            domains = field.domains()
            if not domains:
                return 0
            # Välj domän med flest obearbetade high-confidence-koncept
            import random
            domain = random.choice(domains)
            concepts = field.concepts(domain=domain)
            if not concepts:
                return 0
            # Välj ett "hub"-koncept (hög grad)
            sorted_concepts = sorted(
                concepts,
                key=lambda c: len(field.relations(src=c["name"], domain=domain)),
                reverse=True,
            )
            concept = sorted_concepts[0]["name"] if sorted_concepts else concepts[0]["name"]
        except Exception as e:
            _log.warning(f"Decomposition: Kunde inte välja koncept: {e}")
            return 0

    _log.info(f"Decomposition burst: '{concept}' i '{domain}'")

    try:
        tree, axioms = await decompose_concept(field, concept, domain)
    except Exception as e:
        _log.error(f"Decomposition misslyckades ({concept}): {e}")
        return 0

    if not axioms:
        _log.info(f"Decomposition: inga axiom hittades för '{concept}'")
        return 0

    # Hög limbic arousal → lägg till direkt. Låg arousal → inkubera.
    if limbic.arousal >= 0.4:
        added = promote_axioms_to_graph(field, axioms)
        _log.info(f"Decomposition: {added} nya axiom-kanter tillagda för '{concept}'")
        return added
    else:
        # Lägg i inkubationskön (F_bisoc^τ)
        try:
            from nouse.tda.bridge import compute_betti, compute_distance_matrix
            # Enkel τ-uppskattning baserat på axiom-score
            avg_score = sum(a.bridge_score for a in axioms) / len(axioms)
        except Exception:
            avg_score = 0.5

        partial = PartialDecomposition(
            concept=concept,
            domain=domain,
            partial_tree={},
            axiom_candidates=[asdict(a) for a in axioms],
            cycles_in_graph=limbic.cycle,
            topo_similarity=avg_score,
        )
        queue_for_incubation(partial)
        _log.info(
            f"Decomposition: '{concept}' inkuberas "
            f"(arousal={limbic.arousal:.2f}, τ≈{avg_score:.2f})"
        )
        return 0
