from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schema import SCHEMA_VERSION


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _safe_softmax(logits: dict[str, float], temperature: float) -> dict[str, float]:
    t = max(1e-6, temperature)
    scaled = {k: v / t for k, v in logits.items()}
    m = max(scaled.values()) if scaled else 0.0
    exps = {k: math.exp(v - m) for k, v in scaled.items()}
    z = sum(exps.values()) or 1.0
    return {k: v / z for k, v in exps.items()}


@dataclass
class NodeStateSpace:
    node_id: str
    node_type: str = "concept"
    label: str = ""
    states: dict[str, float] = field(default_factory=dict)  # prior amplitudes
    uncertainty: float = 0.80
    evidence_score: float = 0.0
    goal_weight: float = 0.0
    attrs: dict[str, Any] = field(default_factory=dict)

    def normalized_states(self) -> dict[str, float]:
        if not self.states:
            return {"default": 1.0}
        total = sum(max(0.0, v) for v in self.states.values()) or 1.0
        return {k: max(0.0, v) / total for k, v in self.states.items()}


@dataclass
class ResidualEdge:
    edge_id: str
    src: str
    rel_type: str
    tgt: str
    w: float = 0.02
    r: float = 0.0
    u: float = 0.80
    evidence_score: float = 0.0
    provenance: str = "unknown"
    created_at: str = ""
    updated_at: str = ""
    crystallized: bool = False
    crystallized_at_cycle: int | None = None

    def __post_init__(self) -> None:
        self.w = _clamp(self.w, 0.0, 1.0)
        self.u = _clamp(self.u, 0.0, 1.0)
        self.r = _clamp(self.r, -2.0, 2.0)
        self.evidence_score = _clamp(self.evidence_score, 0.0, 1.0)
        now = _now_iso()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    @property
    def path_signal(self) -> float:
        return self.w + 0.45 * self.r - 0.25 * self.u


@dataclass
class NeuromodulatorState:
    dopamine: float = 0.5
    noradrenaline: float = 0.5
    acetylcholine: float = 0.5

    @property
    def arousal(self) -> float:
        return _clamp(0.65 * self.noradrenaline + 0.35 * self.dopamine, 0.0, 1.0)

    @property
    def focus(self) -> float:
        return _clamp(0.70 * self.acetylcholine + 0.30 * self.noradrenaline, 0.0, 1.0)

    @property
    def risk(self) -> float:
        return _clamp(0.55 * (1.0 - self.acetylcholine) + 0.45 * self.noradrenaline, 0.0, 1.0)


@dataclass
class FieldEvent:
    edge_id: str
    src: str
    rel_type: str
    tgt: str
    w_delta: float = 0.0
    r_delta: float = 0.0
    u_delta: float = 0.0
    evidence_score: float | None = None
    provenance: str | None = None


class Brain:
    """Canonical Brain Kernel.

    The kernel is both storage and computation substrate:
    - live topology in memory
    - field dynamics via step()
    - topology growth via crystallize()
    - persistence via save()/load() brain image
    """

    FORMAT_VERSION = "brain-image-v1"

    def __init__(
        self,
        *,
        w_threshold: float = 0.60,
        u_ceiling: float = 0.40,
        r_decay: float = 0.89,
        non_local_strength: float = 0.06,
        seed: int = 76031,
    ) -> None:
        self.schema_version = SCHEMA_VERSION
        self.format_version = self.FORMAT_VERSION
        self.w_threshold = w_threshold
        self.u_ceiling = u_ceiling
        self.r_decay = r_decay
        self.non_local_strength = non_local_strength
        self.cycle = 0
        self.seed = seed
        self._rng = random.Random(seed)

        self.nodes: dict[str, NodeStateSpace] = {}
        self.edges: dict[str, ResidualEdge] = {}
        self.signals = NeuromodulatorState()

    def add_node(
        self,
        node_id: str,
        *,
        node_type: str = "concept",
        label: str = "",
        states: dict[str, float] | None = None,
        uncertainty: float = 0.80,
        evidence_score: float = 0.0,
        goal_weight: float = 0.0,
        attrs: dict[str, Any] | None = None,
    ) -> NodeStateSpace:
        node = NodeStateSpace(
            node_id=node_id,
            node_type=node_type,
            label=label or node_id,
            states=states or {"default": 1.0},
            uncertainty=_clamp(uncertainty, 0.0, 1.0),
            evidence_score=_clamp(evidence_score, 0.0, 1.0),
            goal_weight=_clamp(goal_weight, 0.0, 1.0),
            attrs=attrs or {},
        )
        self.nodes[node_id] = node
        return node

    def upsert_edge(
        self,
        edge_id: str,
        *,
        src: str,
        rel_type: str,
        tgt: str,
        w: float = 0.02,
        r: float = 0.0,
        u: float = 0.80,
        evidence_score: float = 0.0,
        provenance: str = "unknown",
    ) -> ResidualEdge:
        edge = self.edges.get(edge_id)
        if edge is None:
            edge = ResidualEdge(
                edge_id=edge_id,
                src=src,
                rel_type=rel_type,
                tgt=tgt,
                w=w,
                r=r,
                u=u,
                evidence_score=evidence_score,
                provenance=provenance,
            )
            self.edges[edge_id] = edge
            return edge

        edge.w = _clamp(w, 0.0, 1.0)
        edge.r = _clamp(r, -2.0, 2.0)
        edge.u = _clamp(u, 0.0, 1.0)
        edge.evidence_score = _clamp(evidence_score, 0.0, 1.0)
        edge.provenance = provenance
        edge.updated_at = _now_iso()
        return edge

    def apply_event(self, event: FieldEvent) -> ResidualEdge:
        edge = self.edges.get(event.edge_id)
        if edge is None:
            edge = self.upsert_edge(
                event.edge_id,
                src=event.src,
                rel_type=event.rel_type,
                tgt=event.tgt,
            )

        edge.w = _clamp(edge.w + event.w_delta, 0.0, 1.0)
        edge.r = _clamp(edge.r + event.r_delta, -2.0, 2.0)
        edge.u = _clamp(edge.u + event.u_delta, 0.0, 1.0)
        if event.evidence_score is not None:
            edge.evidence_score = _clamp(event.evidence_score, 0.0, 1.0)
        if event.provenance is not None:
            edge.provenance = event.provenance
        edge.updated_at = _now_iso()
        return edge

    def step(self, events: list[FieldEvent] | None = None) -> None:
        for event in events or []:
            self.apply_event(event)

        # Local field dynamics: residual decay each cycle.
        for edge in self.edges.values():
            edge.r = _clamp(edge.r * self.r_decay, -2.0, 2.0)

        # Non-local term: low-rank style global coherence broadcast.
        if self.edges:
            coherence = sum(max(0.0, e.path_signal) for e in self.edges.values()) / len(self.edges)
            for edge in self.edges.values():
                coupling = (1.0 - edge.u) * self.non_local_strength * coherence
                edge.r = _clamp(edge.r + coupling, -2.0, 2.0)
                edge.updated_at = _now_iso()

        self.cycle += 1

    def crystallize(self) -> list[ResidualEdge]:
        crystallized: list[ResidualEdge] = []
        for edge in self.edges.values():
            if edge.crystallized:
                continue
            if edge.w > self.w_threshold and edge.u < self.u_ceiling:
                edge.crystallized = True
                edge.crystallized_at_cycle = self.cycle
                edge.updated_at = _now_iso()
                crystallized.append(edge)
        return crystallized

    def collapse(
        self,
        node_id: str,
        *,
        context_mismatch: dict[str, float] | None = None,
        temperature: float = 1.0,
        sample: bool = False,
    ) -> tuple[str, dict[str, float]]:
        node = self.nodes[node_id]
        states = node.normalized_states()
        mismatch = context_mismatch or {}
        field_support = self._node_field_support(node_id)
        logits: dict[str, float] = {}
        for state_name, prior in states.items():
            m = _clamp(mismatch.get(state_name, 0.5), 0.0, 1.0)
            energy = (
                1.00 * m
                + 0.90 * node.uncertainty
                - 0.85 * field_support
                - 0.70 * node.evidence_score
                - 0.55 * node.goal_weight
                - 0.20 * prior
            )
            logits[state_name] = -energy

        probs = _safe_softmax(logits, temperature=temperature)
        if sample:
            chosen = self._sample_from_probs(probs)
        else:
            chosen = max(probs.items(), key=lambda kv: kv[1])[0]
        return chosen, probs

    def _sample_from_probs(self, probs: dict[str, float]) -> str:
        x = self._rng.random()
        acc = 0.0
        last_key = "default"
        for key, p in probs.items():
            last_key = key
            acc += p
            if x <= acc:
                return key
        return last_key

    def _node_field_support(self, node_id: str) -> float:
        touching = [
            edge.path_signal
            for edge in self.edges.values()
            if edge.src == node_id or edge.tgt == node_id
        ]
        if not touching:
            return 0.0
        return _clamp(sum(max(0.0, x) for x in touching) / len(touching), 0.0, 1.0)

    def gap_map(self) -> dict[str, Any]:
        weak_nodes = [
            {
                "node_id": node.node_id,
                "uncertainty": round(node.uncertainty, 4),
                "evidence_score": round(node.evidence_score, 4),
            }
            for node in self.nodes.values()
            if node.evidence_score < 0.35 or node.uncertainty > 0.65
        ]
        weak_edges = [
            {
                "edge_id": edge.edge_id,
                "path_signal": round(edge.path_signal, 4),
                "u": round(edge.u, 4),
                "crystallized": edge.crystallized,
            }
            for edge in self.edges.values()
            if edge.path_signal < 0.15 or edge.u > 0.65
        ]
        return {
            "cycle": self.cycle,
            "weak_nodes": weak_nodes,
            "weak_edges": weak_edges,
        }

    def _node_activation_scores(self) -> dict[str, float]:
        scores: dict[str, float] = {node_id: 0.0 for node_id in self.nodes}
        for edge in self.edges.values():
            signal = max(0.0, edge.path_signal)
            if signal <= 0:
                continue
            scores[edge.src] = scores.get(edge.src, 0.0) + signal
            scores[edge.tgt] = scores.get(edge.tgt, 0.0) + (0.85 * signal)
        return scores

    def top_active_nodes(self, limit: int = 12) -> list[dict[str, Any]]:
        scores = self._node_activation_scores()
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[: max(1, limit)]
        out: list[dict[str, Any]] = []
        for node_id, activation in ranked:
            node = self.nodes.get(node_id)
            if node is None:
                out.append(
                    {
                        "node_id": node_id,
                        "label": node_id,
                        "node_type": "unknown",
                        "activation": round(activation, 6),
                        "evidence_score": 0.0,
                        "uncertainty": 1.0,
                    }
                )
                continue
            out.append(
                {
                    "node_id": node_id,
                    "label": node.label or node.node_id,
                    "node_type": node.node_type,
                    "activation": round(activation, 6),
                    "evidence_score": round(node.evidence_score, 6),
                    "uncertainty": round(node.uncertainty, 6),
                }
            )
        return out

    def top_active_edges(self, limit: int = 16) -> list[dict[str, Any]]:
        ranked = sorted(
            self.edges.values(),
            key=lambda edge: edge.path_signal,
            reverse=True,
        )[: max(1, limit)]
        return [
            {
                "edge_id": edge.edge_id,
                "src": edge.src,
                "rel_type": edge.rel_type,
                "tgt": edge.tgt,
                "path_signal": round(edge.path_signal, 6),
                "w": round(edge.w, 6),
                "r": round(edge.r, 6),
                "u": round(edge.u, 6),
                "crystallized": edge.crystallized,
            }
            for edge in ranked
        ]

    def live_view(self, *, limit_nodes: int = 12, limit_edges: int = 16) -> dict[str, Any]:
        gap = self.gap_map()
        return {
            "cycle": self.cycle,
            "signals": asdict(self.signals),
            "counts": {
                "nodes": len(self.nodes),
                "edges": len(self.edges),
                "crystallized_edges": sum(1 for edge in self.edges.values() if edge.crystallized),
                "weak_nodes": len(gap["weak_nodes"]),
                "weak_edges": len(gap["weak_edges"]),
            },
            "active_nodes": self.top_active_nodes(limit=limit_nodes),
            "active_edges": self.top_active_edges(limit=limit_edges),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "schema_version": self.schema_version,
            "cycle": self.cycle,
            "seed": self.seed,
            "params": {
                "w_threshold": self.w_threshold,
                "u_ceiling": self.u_ceiling,
                "r_decay": self.r_decay,
                "non_local_strength": self.non_local_strength,
            },
            "signals": asdict(self.signals),
            "nodes": {k: asdict(v) for k, v in self.nodes.items()},
            "edges": {k: asdict(v) for k, v in self.edges.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Brain:
        if data.get("format_version") != cls.FORMAT_VERSION:
            raise ValueError(
                f"unsupported format_version={data.get('format_version')} expected={cls.FORMAT_VERSION}"
            )
        params = data.get("params", {})
        brain = cls(
            w_threshold=float(params.get("w_threshold", 0.60)),
            u_ceiling=float(params.get("u_ceiling", 0.40)),
            r_decay=float(params.get("r_decay", 0.89)),
            non_local_strength=float(params.get("non_local_strength", 0.06)),
            seed=int(data.get("seed", 76031)),
        )
        brain.cycle = int(data.get("cycle", 0))
        s = data.get("signals", {})
        brain.signals = NeuromodulatorState(
            dopamine=float(s.get("dopamine", 0.5)),
            noradrenaline=float(s.get("noradrenaline", 0.5)),
            acetylcholine=float(s.get("acetylcholine", 0.5)),
        )
        for node_id, node_raw in data.get("nodes", {}).items():
            brain.nodes[node_id] = NodeStateSpace(
                node_id=node_raw.get("node_id", node_id),
                node_type=node_raw.get("node_type", "concept"),
                label=node_raw.get("label", node_id),
                states=dict(node_raw.get("states", {"default": 1.0})),
                uncertainty=float(node_raw.get("uncertainty", 0.8)),
                evidence_score=float(node_raw.get("evidence_score", 0.0)),
                goal_weight=float(node_raw.get("goal_weight", 0.0)),
                attrs=dict(node_raw.get("attrs", {})),
            )
        for edge_id, edge_raw in data.get("edges", {}).items():
            brain.edges[edge_id] = ResidualEdge(
                edge_id=edge_raw.get("edge_id", edge_id),
                src=edge_raw["src"],
                rel_type=edge_raw["rel_type"],
                tgt=edge_raw["tgt"],
                w=float(edge_raw.get("w", 0.02)),
                r=float(edge_raw.get("r", 0.0)),
                u=float(edge_raw.get("u", 0.8)),
                evidence_score=float(edge_raw.get("evidence_score", 0.0)),
                provenance=edge_raw.get("provenance", "unknown"),
                created_at=edge_raw.get("created_at", ""),
                updated_at=edge_raw.get("updated_at", ""),
                crystallized=bool(edge_raw.get("crystallized", False)),
                crystallized_at_cycle=edge_raw.get("crystallized_at_cycle"),
            )
        return brain

    def apply_goal_weights(self, goals: list[Any]) -> int:
        """
        D3: Uppdatera goal_weight på noder baserat på aktiva mål.

        Varje aktivt måls target_concepts får goal_weight = max(existerande, mål-prioritet).
        Returnerar antal uppdaterade noder.
        """
        updated = 0
        for goal in goals:
            if getattr(goal, "status", "") != "active":
                continue
            priority = float(getattr(goal, "priority", 0.5))
            for concept in getattr(goal, "target_concepts", []):
                node = self.nodes.get(concept)
                if node is not None:
                    new_gw = max(float(node.goal_weight), priority)
                    if new_gw != float(node.goal_weight):
                        node.goal_weight = _clamp(new_gw, 0.0, 1.0)
                        updated += 1
        return updated

    def save(self, path: str | Path) -> Path:
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return out_path

    @classmethod
    def load(cls, path: str | Path) -> Brain:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw)
