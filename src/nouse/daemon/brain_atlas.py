"""
nouse.daemon.brain_atlas — Structural brain atlas for domain placement
=========================================================================

Maps Nous knowledge domains to brain regions based on functional similarity.
This isn't metaphorical — it determines:
1. Where data flows (which domain → which region)
2. How signals propagate (decay based on region distance)
3. What happens when a region is under/over-connected
4. How to prevent "slagsida" (lopsided topology)

Based on biological brain organization:
- Frontal Lobe: decision-making, planning, speech
- Parietal Lobe: sensory processing, spatial awareness
- Temporal Lobe: hearing, language, memory
- Occipital Lobe: visual processing, pattern recognition
- Cerebellum: balance, coordination, fine-tuning
- Brainstem: vital functions, heartbeat, breathing
- Hippocampus: memory formation, consolidation
- Amygdala: emotion, fear, risk assessment

Each region has:
- A spatial position (for wire-length optimization)
- A function (what type of data it processes)
- Connectivity patterns (which regions it connects to)
- Signal properties (decay rate, priority)
- Damage effects (what breaks when it's under-connected)

The atlas is used during domain registration to assign each new domain
to the appropriate brain region, ensuring that the knowledge graph
has the same structural organization as the biological brain.
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("nouse.brain_atlas")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Enable brain atlas-based domain placement
ATLAS_ENABLED = bool(int(os.getenv("NOUSE_ATLAS_ENABLED", "1")))


# ---------------------------------------------------------------------------
# Brain regions
# ---------------------------------------------------------------------------

@dataclass
class BrainRegion:
    """A brain region with spatial position and functional properties.

    Position is in a 2D coordinate system inspired by cortical layout:
      - x-axis: posterior (-) to anterior (+)
      - y-axis: ventral (-) to dorsal (+)

    This gives natural distances:
      - Frontal ↔ Occipital = long distance (anterior ↔ posterior)
      - Temporal ↔ Hippocampus = short distance (both ventral)
      - Amygdala ↔ Hippocampus = very short (adjacent in medial temporal)
    """
    name: str
    primary_function: str
    effect_of_damage: str
    x: float  # posterior (-) to anterior (+)
    y: float  # ventral (-) to dorsal (+)
    signal_decay_rate: float = 0.89  # how fast signals decay leaving this region
    max_domains: int = 0  # 0 = unlimited
    domain_keywords: list[str] = field(default_factory=list)

    def distance_to(self, other: BrainRegion) -> float:
        """Euclidean distance between two brain regions."""
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)


# The canonical brain atlas — positions inspired by cortical layout
BRAIN_ATLAS: dict[str, BrainRegion] = {
    "frontal_lobe": BrainRegion(
        name="Frontal Lobe",
        primary_function="Decision-making, planning, speech production",
        effect_of_damage="Personality change, poor judgment, loss of planning",
        x=3.0, y=1.0,  # anterior, dorsal
        signal_decay_rate=0.85,
        domain_keywords=[
            # Planning & decision-making
            "goal", "plan", "decision", "strategy", "policy", "initiative",
            "curiosity", "drive", "priority", "task", "agenda",
            # Speech & output
            "speech", "language_output", "articulation", "larynx", "expression",
            "response", "generation", "synthesis",
            # Executive function
            "executive", "control", "regulation", "cognitive_policy",
            "attention", "working_memory", "inhibition",
        ],
    ),
    "parietal_lobe": BrainRegion(
        name="Parietal Lobe",
        primary_function="Sensory processing, spatial awareness, integration",
        effect_of_damage="Difficulty with touch perception, spatial disorientation",
        x=0.0, y=2.0,  # central, very dorsal
        signal_decay_rate=0.87,
        domain_keywords=[
            # Spatial & structural
            "spatial", "topology", "structure", "geometry", "graph", "network",
            "percolation", "density", "domain", "mapping", "layout",
            # Sensory integration
            "integration", "association", "bridge", "cross_domain",
            "multimodal", "synthesis", "binding",
            # Mathematics & abstraction
            "mathematics", "logic", "abstraction", "formal", "computation",
            "algorithm", "complexity", "information",
        ],
    ),
    "temporal_lobe": BrainRegion(
        name="Temporal Lobe",
        primary_function="Hearing, language comprehension, memory storage",
        effect_of_damage="Hearing loss, memory problems, language deficits",
        x=0.0, y=-1.0,  # central, ventral
        signal_decay_rate=0.88,
        domain_keywords=[
            # Language & comprehension
            "language", "linguistics", "semantics", "syntax", "grammar",
            "meaning", "comprehension", "translation", "nlp", "text",
            # Memory & knowledge
            "memory", "knowledge", "episodic", "semantic", "procedural",
            "storage", "retrieval", "recall", "consolidation",
            # Hearing & audio
            "audio", "speech_recognition", "phonetics", "acoustics",
            # Documents & sources
            "document", "source", "ingestion", "extraction", "content",
        ],
    ),
    "occipital_lobe": BrainRegion(
        name="Occipital Lobe",
        primary_function="Visual processing, pattern recognition, embedding",
        effect_of_damage="Vision loss, hallucinations, inability to recognize patterns",
        x=-3.0, y=1.0,  # posterior, dorsal
        signal_decay_rate=0.86,
        domain_keywords=[
            # Visual & pattern
            "visual", "vision", "image", "pattern", "recognition",
            "embedding", "vector", "representation", "feature", "perception",
            # Data representation
            "data", "signal", "encoding", "dimension", "projection",
            "clustering", "classification", "detection",
        ],
    ),
    "cerebellum": BrainRegion(
        name="Cerebellum",
        primary_function="Balance, coordination, fine-tuning, error correction",
        effect_of_damage="Ataxia, tremors, loss of balance, poor coordination",
        x=-2.0, y=-2.0,  # posterior, very ventral
        signal_decay_rate=0.90,
        domain_keywords=[
            # Coordination & balance
            "coordination", "balance", "homeostasis", "regulation",
            "limbic", "arousal", "tonic", "performance",
            # Error correction
            "error", "correction", "calibration", "feedback", "adjustment",
            "tuning", "optimization", "convergence",
            # Fine-tuning
            "precision", "accuracy", "refinement", "iteration",
        ],
    ),
    "brainstem": BrainRegion(
        name="Brainstem",
        primary_function="Vital functions, heartbeat, breathing, sleep cycle",
        effect_of_damage="Respiratory failure, coma, loss of consciousness",
        x=-3.0, y=-2.5,  # very posterior, very ventral
        signal_decay_rate=0.95,  # vital signals propagate strongly
        domain_keywords=[
            # Vital functions
            "daemon", "heartbeat", "cycle", "loop", "service",
            "startup", "shutdown", "health", "vitals",
            # Sleep & rhythm
            "sleep", "rhythm", "nightrun", "schedule", "timer",
            "interval", "periodicity",
            # Core infrastructure
            "infrastructure", "config", "environment", "system",
        ],
    ),
    "hippocampus": BrainRegion(
        name="Hippocampus",
        primary_function="Memory formation, consolidation, spatial mapping",
        effect_of_damage="Short-term memory loss, inability to form new memories",
        x=1.0, y=-1.5,  # medial anterior, ventral
        signal_decay_rate=0.88,
        domain_keywords=[
            # Memory formation
            "crystallization", "consolidation", "evidence", "proof",
            "confidence", "belief", "fact", "truth", "knowledge_formation",
            # Spatial mapping
            "mapping", "navigation", "route", "path", "bfs",
            "search", "exploration",
            # Learning
            "learning", "adaptation", "plasticity", "novelty",
            "prediction", "surprise", "prediction_error",
        ],
    ),
    "amygdala": BrainRegion(
        name="Amygdala",
        primary_function="Emotion, fear response, risk assessment, threat detection",
        effect_of_damage="Emotional instability, inability to assess risk, fear responses",
        x=1.5, y=-1.8,  # medial anterior, very ventral (near hippocampus)
        signal_decay_rate=0.92,
        domain_keywords=[
            # Emotion & fear
            "emotion", "fear", "threat", "danger", "risk",
            "contradiction", "conflict", "uncertainty", "anxiety",
            # Risk & assessment
            "assessment", "evaluation", "priority", "urgency",
            "safety", "boundary", "protection", "guard",
            # Alarm & alert
            "alarm", "alert", "warning", "critical", "attention",
        ],
    ),
    "basal_ganglia": BrainRegion(
        # 2026-08-25 (neurotorium.org regional neuroscience, see
        # docs/EVIDENCE_MODEL.md-adjacent IIC note
        # nous-neurobiology-grounding.md): the real anatomical seat of
        # reward-driven HABIT formation — distinct from hippocampus's
        # declarative/episodic memory below. strength/strength_fast
        # (field/surface.py) and the dopamine signal (limbic/signals.py)
        # already implement exactly this mechanism; it never had a home
        # region. Not a new function — a correct name for one that
        # already exists.
        name="Basal Ganglia",
        primary_function="Reward-driven habit formation, action selection, procedural (not declarative) memory",
        effect_of_damage="Loss of automatic/habitual behavior, impaired action selection, motor rigidity",
        x=0.5, y=-0.6,  # deep, slightly anterior, mid-ventral — near hippocampus/amygdala
        signal_decay_rate=0.91,  # reinforced patterns should persist strongly, like amygdala/cerebellum
        domain_keywords=[
            # Habit & procedure — the core distinction from hippocampus's declarative memory
            "habit", "routine", "procedural", "automaticity", "repetition",
            "vana", "rutin",
            # Reward & reinforcement
            "reward", "reinforcement", "dopamine", "belöning", "förstärkning",
            # Action selection
            "action_selection", "gating", "motor_control", "striatum",
        ],
    ),
    "thalamus": BrainRegion(
        # 2026-08-25 (same source as basal_ganglia above): the central
        # sensory/signal relay — every existing "route this request
        # somewhere" mechanism (MCP gateway, capability/graph.py routing,
        # the Tools panel's Route Control) had no region either.
        name="Thalamus",
        primary_function="Central relay station — routes signals to the appropriate region",
        effect_of_damage="Sensory processing failure, inability to route/prioritize incoming signals",
        x=0.0, y=0.0,  # the literal center — matches its real anatomical position
        signal_decay_rate=0.94,  # a relay hub should lose little in transit, close to brainstem's 0.95
        domain_keywords=[
            "relay", "routing", "route", "dispatch", "gateway",
            "channel", "relä", "forward", "mcp",
        ],
    ),
}


# ---------------------------------------------------------------------------
# Region distance matrix
# ---------------------------------------------------------------------------

def region_distance(a: str, b: str) -> float:
    """Distance between two brain regions by name."""
    ra = BRAIN_ATLAS.get(a)
    rb = BRAIN_ATLAS.get(b)
    if not ra or not rb:
        return 5.0  # default large distance for unknown regions
    return ra.distance_to(rb)


# Pre-computed distance matrix for all region pairs
DISTANCE_MATRIX: dict[tuple[str, str], float] = {}
for _a_name, _a_region in BRAIN_ATLAS.items():
    for _b_name, _b_region in BRAIN_ATLAS.items():
        if _a_name != _b_name:
            key = tuple(sorted([_a_name, _b_name]))
            if key not in DISTANCE_MATRIX:
                DISTANCE_MATRIX[key] = _a_region.distance_to(_b_region)


# ---------------------------------------------------------------------------
# Domain → Region classification
# ---------------------------------------------------------------------------

def classify_domain(domain_name: str) -> str:
    """Classify a domain name into a brain region.

    Uses keyword matching against domain_keywords in each BrainRegion.
    Falls back to temporal_lobe for language/knowledge domains,
    or parietal_lobe for unknown domains (default integrative region).
    """
    domain_lower = domain_name.lower()

    # Score each region by keyword match
    scores: dict[str, float] = {}
    for region_name, region in BRAIN_ATLAS.items():
        score = 0.0
        for kw in region.domain_keywords:
            if kw in domain_lower:
                score += 1.0
            # Also check if domain name contains key parts of keyword
            kw_parts = kw.split("_")
            if len(kw_parts) > 1:
                matches = sum(1 for part in kw_parts if part in domain_lower)
                if matches == len(kw_parts):
                    score += 0.8  # slightly less than full match
                elif matches > 0:
                    score += 0.3 * matches / len(kw_parts)

        if score > 0:
            scores[region_name] = score

    if scores:
        # Return region with highest score
        best = max(scores, key=scores.get)
        return best

    # Fallback heuristics based on domain naming patterns
    if any(w in domain_lower for w in ["programmering", "kod", "python", "api", "system"]):
        return "brainstem"  # infrastructure
    if any(w in domain_lower for w in ["vetenskap", "forskning", "teori", "research"]):
        return "temporal_lobe"  # knowledge storage
    if any(w in domain_lower for w in ["kognitiv", "neuro", "brain", "hjärna"]):
        return "hippocampus"  # brain science
    if any(w in domain_lower for w in ["språk", "language", "text", "doc"]):
        return "temporal_lobe"  # language
    if any(w in domain_lower for w in ["data", "statistik", "stat"]):
        return "occipital_lobe"  # pattern/data

    # Default: parietal lobe (integrative, general knowledge)
    return "parietal_lobe"


def classify_all_domains(field: Any) -> dict[str, str]:
    """Classify all domains in the field into brain regions.

    Returns: dict of domain_name → region_name
    """
    domains = field.domains()
    result = {}
    for d in domains:
        result[d] = classify_domain(d)
    return result


# ---------------------------------------------------------------------------
# Region report
# ---------------------------------------------------------------------------

@dataclass
class RegionStats:
    """Statistics for a brain region."""
    name: str
    domain_count: int
    domains: list[str]
    concept_count: int
    avg_concepts: float
    signal_decay: float
    connectivity: int = 0  # number of connections to other regions


def region_report(field: Any) -> dict[str, RegionStats]:
    """Generate a brain region report for the current knowledge graph.

    Shows how domains are distributed across brain regions, identifying
    over/under-represented regions (potential "slagsida").
    """
    domain_regions = classify_all_domains(field)

    # Build per-region stats
    region_data: dict[str, dict] = {name: {"domains": [], "concepts": 0}
                                     for name in BRAIN_ATLAS}
    for domain, region_name in domain_regions.items():
        if region_name not in region_data:
            region_data[region_name] = {"domains": [], "concepts": 0}
        region_data[region_name]["domains"].append(domain)
        n_concepts = len(field.concepts(domain=domain))
        region_data[region_name]["concepts"] += n_concepts

    results: dict[str, RegionStats] = {}
    for region_name, data in region_data.items():
        n_domains = len(data["domains"])
        n_concepts = data["concepts"]
        region_def = BRAIN_ATLAS.get(region_name)

        results[region_name] = RegionStats(
            name=region_def.name if region_def else region_name,
            domain_count=n_domains,
            domains=sorted(data["domains"]),
            concept_count=n_concepts,
            avg_concepts=n_concepts / max(1, n_domains),
            signal_decay=region_def.signal_decay_rate if region_def else 0.89,
        )

    return results


def format_region_report(stats: dict[str, RegionStats]) -> str:
    """Format a brain region report as human-readable text."""
    lines = [
        "═══ BRAIN ATLAS REPORT ═══",
        f"{'Region':20s} {'Domains':>8s} {'Concepts':>10s} {'Avg/Domain':>12s} {'Decay':>6s}",
        "─" * 60,
    ]

    # Sort by concept count descending
    sorted_stats = sorted(stats.values(), key=lambda s: -s.concept_count)
    for s in sorted_stats:
        lines.append(
            f"{s.name:20s} {s.domain_count:8d} {s.concept_count:10d} "
            f"{s.avg_concepts:12.1f} {s.signal_decay:6.2f}"
        )

    # Detect "slagsida" — regions with disproportionate share
    total_concepts = sum(s.concept_count for s in stats.values())
    total_domains = sum(s.domain_count for s in stats.values())
    if total_concepts > 0:
        lines.append("")
        lines.append("Slagsida check (ideal: each region ~12.5% of concepts):")
        for s in sorted_stats:
            pct = 100.0 * s.concept_count / max(1, total_concepts)
            marker = "⚠ " if pct > 30.0 or pct < 2.0 else "  "
            lines.append(f"  {marker}{s.name:20s} {pct:5.1f}%")

    return "\n".join(lines)