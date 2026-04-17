"""
brain_topology.py — Spatial mapping: NoUse domains → brain regions → 3D coordinates.

The knowledge graph is laid out AS a brain:
  - Frontal cortex   : logic, planning, formal systems        (+z = forward)
  - Parietal cortex  : integration, spatial causality         (+y = top)
  - Temporal lobes   : language/music (left), creativity (right)
  - Occipital        : pattern recognition, classification    (-z = back)
  - Prefrontal       : meta-cognition, synthesis nodes
  - Hippocampus      : new connections, episodic memory
  - Amygdala         : emotional weighting, values, arousal
  - Cerebellum       : procedural, automatic, skill knowledge
  - Brainstem        : axiomatic constants, fundamental states
  - Corpus callosum  : cross-domain bridges (center)

Coordinate system: right-hand, Y-up, Z-forward (same as Three.js scene).
All positions are rough radial offsets from center — force-graph will settle
nodes around these attractors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

# ── Region definitions ────────────────────────────────────────────────────────

@dataclass
class BrainRegion:
    name: str
    label_sv: str
    position: Tuple[float, float, float]   # (x, y, z)
    color_hex: str
    description: str
    domains: list[str] = field(default_factory=list)
    # Loose keyword matching for unlabelled domains
    keywords: list[str] = field(default_factory=list)


BRAIN_REGIONS: dict[str, BrainRegion] = {
    "prefrontal": BrainRegion(
        name="prefrontal",
        label_sv="Prefrontal cortex",
        position=(0.0, 25.0, 105.0),
        color_hex="#ffd700",
        description="Metakognition, syntes, planering på hög abstraktionsnivå",
        domains=["meta", "metacognition", "metakognition", "syntes", "synthesis",
                 "självreflektion", "epistemologi", "medvetande", "consciousness",
                 "självorganisering", "metakognition_och_syntes"],
        keywords=["meta", "synth", "reflex", "plan", "abstract", "strategi"],
    ),
    "frontal": BrainRegion(
        name="frontal",
        label_sv="Frontallob",
        position=(0.0, 0.0, 85.0),
        color_hex="#4e9af1",
        description="Logik, matematik, formella system, beslut, resonemang",
        domains=["matematik", "logik", "formella_system", "formell_logik",
                 "bevisföring", "algebra", "aritmetik", "sats", "theorem",
                 "beslutsfattande", "reasoning", "inference", "deduktion",
                 "induktion", "statistik", "sannolikhet", "probability",
                 "logik_och_beslut"],
        keywords=["math", "logic", "formal", "proof", "axiom_app", "calcul",
                  "algebra", "theorem", "decision", "reason", "beslut"],
    ),
    "parietal": BrainRegion(
        name="parietal",
        label_sv="Parietallob",
        position=(0.0, 65.0, 40.0),
        color_hex="#4ef1c4",
        description="Rumslig integration, kausalitet, sensorisk syntes, relationer",
        domains=["kognition", "kausalitet", "rumslig_kognition", "integration",
                 "systemteori", "nätverk", "topologi", "geometri",
                 "fysiologi", "biomekanik", "perception","physics","fysik"],
        keywords=["spatial", "causal", "integrat", "relation", "system",
                  "network", "topolog", "geometr", "physic", "fysik",
                  "data", "datavet", "datahanter", "systemteori",
                  "konfiguration", "process", "sträng", "typ"],
    ),
    "temporal_left": BrainRegion(
        name="temporal_left",
        label_sv="Temporallob (vänster) — språk",
        position=(-85.0, 0.0, 0.0),
        color_hex="#b04ef1",
        description="Språk, semantik, lingvistik, minne för fakta",
        domains=["lingvistik", "språk", "semantik", "syntax", "pragmatik",
                 "kommunikation", "retorik", "semiotik", "narrativ", "berättande",
                 "text", "litteratur", "poesi", "skrivande", "läsning",
                 "språk_och_semantik"],
        keywords=["lingu", "lang", "semant", "syntax", "narrat", "text",
                  "liter", "communic", "rhetoric", "semiot"],
    ),
    "temporal_right": BrainRegion(
        name="temporal_right",
        label_sv="Temporallob (höger) — kreativitet",
        position=(85.0, 0.0, 0.0),
        color_hex="#f14eb0",
        description="Kreativitet, musik, spontan association, humor",
        domains=["kreativitet", "musik", "konst", "estetik", "poesi",
                 "improvisation", "analogi", "metafor", "humor",
                 "fantasi", "imagination", "design", "arkitektur",
                 "kreativitet_och_bisociation"],
        keywords=["creat", "music", "art", "aesth", "improv", "humor",
                  "design", "analogi", "metaphor", "fantasi", "bisociation"],
    ),
    "occipital": BrainRegion(
        name="occipital",
        label_sv="Occipitallob",
        position=(0.0, 0.0, -85.0),
        color_hex="#f1c44e",
        description="Mönsterigenkänning, klassificering, perceptuell kategorisering",
        domains=["mönsterigenkänning", "klassificering", "maskininlärning",
                 "neurala_nätverk", "datorseende", "igenkänning",
                 "kategorisering", "taxonomi", "typologi","ml","ai"],
        keywords=["pattern", "classif", "recog", "vision", "neural",
                  "ml", "deep_learn", "categ", "taxonom", "igenkänning"],
    ),
    "hippocampus": BrainRegion(
        name="hippocampus",
        label_sv="Hippocampus",
        position=(0.0, -40.0, 10.0),
        color_hex="#4ef160",
        description="Nya kopplingar, episodiskt minne, navigation, inlärning",
        domains=["episodiskt_minne", "minne", "inlärning", "associationer",
                 "brygga", "bridge", "ny_kunskap", "förvärv",
                 "navigation", "kartläggning", "konsolidering",
                 "minne_och_lärande"],
        keywords=["memory", "episod", "learn", "bridge", "assoc",
                  "navigat", "new_", "acquis", "lärande"],
    ),
    "amygdala": BrainRegion(
        name="amygdala",
        label_sv="Amygdala",
        position=(32.0, -52.0, 12.0),
        color_hex="#f16b4e",
        description="Emotionell viktning, värden, arousal, belöningssystem",
        domains=["emotion", "känslor", "värde", "etik", "moral",
                 "motivation", "belöning", "arousal", "stress",
                 "välmående", "psykologi", "affekt",
                 "risk_och_etik"],
        keywords=["emot", "value", "ethic", "moral", "motiv",
                  "reward", "arousal", "stress", "psych", "affekt",
                  "risk"],
    ),
    "cerebellum": BrainRegion(
        name="cerebellum",
        label_sv="Lillhjärnan",
        position=(0.0, -82.0, -55.0),
        color_hex="#8af14e",
        description="Procedurellt vetande, automatik, teknisk skicklighet",
        domains=["motorik", "procedurellt", "algoritm", "automatisering",
                 "teknik", "ingenjörsvetenskap", "programmering",
                 "verktyg", "metod", "praxis", "implementation",
                 "procedural_och_automatisering"],
        keywords=["procedur", "automat", "algorit", "techni", "engineer",
                  "program", "implement", "method", "praxis", "tool",
                  "python", "python3", "java", "javascript", "js", "c ", "cpp",
                  "golang", "rust", "ruby", "php", "swift", "kotlin",
                  "kod", "kodstruktur", "klass", "klassstruktur", "objekt",
                  "funktion", "metod", "modul", "bibliotek", "package",
                  "server", "client", "http", "tcp", "ip", "socket",
                  "webbutveckling", "webbutv", "html", "css", "frontend",
                  "backend", "fullstack", "api", "rest", "graphql",
                  "testning", "unittest", "pytest", "integrationstest",
                  "mjauvaruutveckling", "mjukvara", "programvara",
                  "datastruktur", "algoritm", "kompilator", "interpret",
                  "shell", "bash", "script", "automatisering"],
    ),
    "brainstem": BrainRegion(
        name="brainstem",
        label_sv="Hjärnstam",
        position=(0.0, -105.0, 0.0),
        color_hex="#f14e4e",
        description="Axiom, fundamentala konstanter, ursprungliga tillstånd",
        domains=["axiom", "fundamental", "bas", "ursprung", "konstant",
                 "grundprincip", "ontologi", "väsen", "existens",
                 "kvanttillstånd", "entropi",
                 "axiom_och_grundläggande",
                 "neurovetenskap"],
        keywords=["axiom", "fundament", "base", "origin", "constant",
                  "ontolog", "exist", "entrop", "quantum", "grundläggande",
                  "neuro", "neuron", "synaps", "hjärna", "hjärn"],
    ),
    "corpus_callosum": BrainRegion(
        name="corpus_callosum",
        label_sv="Corpus callosum",
        position=(0.0, 0.0, 0.0),
        color_hex="#ffffff",
        description="Korsdomän-bryggor, META-syntes, gränsöverskridande noder",
        domains=["korsdomän", "tvärvetenskap", "interdisciplinär",
                 "integration", "synkronisering"],
        keywords=["cross", "inter", "trans", "META::", "bridge", "syntes_"],
    ),
}

# ── Domain → Region lookup ────────────────────────────────────────────────────

def _build_index() -> dict[str, str]:
    """Build a flat domain_name → region_name index."""
    idx: dict[str, str] = {}
    for region_name, region in BRAIN_REGIONS.items():
        for d in region.domains:
            idx[d.lower()] = region_name
    return idx

_DOMAIN_INDEX: dict[str, str] = _build_index()


def classify_domain(domain: str) -> str:
    """
    Return the brain region name for a given domain string.
    Falls back to keyword matching, then 'corpus_callosum' for unknown.
    """
    if not domain:
        return "corpus_callosum"

    d = domain.lower().strip()

    # META:: prefix always → prefrontal
    if d.startswith("meta::") or d.startswith("meta_"):
        return "prefrontal"

    # bridge / syntes nodes → hippocampus / corpus_callosum
    if "bridge" in d or "syntes_" in d or "brygga" in d:
        return "hippocampus"

    # Exact match
    if d in _DOMAIN_INDEX:
        return _DOMAIN_INDEX[d]

    # Keyword matching
    for region_name, region in BRAIN_REGIONS.items():
        for kw in region.keywords:
            if kw in d:
                return region_name

    return "corpus_callosum"


def get_position(domain: str) -> Tuple[float, float, float]:
    """Return the 3D attractor position for a domain."""
    region_name = classify_domain(domain)
    return BRAIN_REGIONS[region_name].position


def get_color(domain: str) -> str:
    """Return the hex color for a domain's brain region."""
    region_name = classify_domain(domain)
    return BRAIN_REGIONS[region_name].color_hex


# ── Full region map (for JS serialization) ───────────────────────────────────

def regions_as_dict() -> dict:
    """Serialize all regions for the /api/brain_regions endpoint."""
    return {
        name: {
            "label": r.label_sv,
            "position": list(r.position),
            "color": r.color_hex,
            "description": r.description,
        }
        for name, r in BRAIN_REGIONS.items()
    }


# ---------------------------------------------------------------------------
# Region balance / slagsida diagnostic
# ---------------------------------------------------------------------------

def region_report(field: Any = None) -> dict[str, dict]:
    """Generate a region balance report from the live graph.

    Shows how domains/concepts are distributed across brain regions,
    identifying "slagsida" (lopsidedness) where some regions are
    over- or under-represented.
    """
    import math as _math

    if field is None:
        return {}

    region_data: dict[str, dict] = {name: {"domains": [], "concepts": 0, "domain_count": 0}
                                    for name in BRAIN_REGIONS}

    for domain in field.domains():
        region_name = classify_domain(domain)
        if region_name not in region_data:
            region_data[region_name] = {"domains": [], "concepts": 0, "domain_count": 0}
        n_concepts = len(field.concepts(domain=domain))
        region_data[region_name]["domains"].append(domain)
        region_data[region_name]["concepts"] += n_concepts
        region_data[region_name]["domain_count"] = len(region_data[region_name]["domains"])

    total_concepts = sum(d["concepts"] for d in region_data.values())
    n_regions = len(BRAIN_REGIONS)
    ideal_pct = 100.0 / max(1, n_regions)

    # Add balance metrics
    for name, data in region_data.items():
        pct = 100.0 * data["concepts"] / max(1, total_concepts)
        data["pct"] = round(pct, 1)
        data["balance"] = "over" if pct > ideal_pct * 2.5 else "under" if pct < ideal_pct * 0.3 else "ok"
        data["label"] = BRAIN_REGIONS[name].label_sv if name in BRAIN_REGIONS else name
        data["color"] = BRAIN_REGIONS[name].color_hex if name in BRAIN_REGIONS else "#888"
        data["position"] = list(BRAIN_REGIONS[name].position) if name in BRAIN_REGIONS else [0, 0, 0]

    return region_data


def region_distance(a: str, b: str) -> float:
    """Euclidean distance between two brain regions in 3D space."""
    ra = BRAIN_REGIONS.get(a)
    rb = BRAIN_REGIONS.get(b)
    if not ra or not rb:
        return 200.0  # large default
    return math.sqrt(
        (ra.position[0] - rb.position[0]) ** 2 +
        (ra.position[1] - rb.position[1]) ** 2 +
        (ra.position[2] - rb.position[2]) ** 2
    )


import math
