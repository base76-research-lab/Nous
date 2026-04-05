"""
LearningCoordinator — kopplar limbic-state till Hebbisk inlärning.

Detta är den saknade länken i Nouse:
  LimbicState → modulerar Δw → FieldSurface.strengthen()

P1: Limbic-modulerat delta        Δw = BASE_DELTA × (1 + noradrenaline)
P2: Spreading activation          grannar stärks med Δw × SPREAD_DECAY
P3: Assumption flag evolution     rensas när evidence_score ≥ CONFIDENCE_GATE
P4: Granularity update            1 + min(4, floor(log2(support_count)))

Integrering i daemon:
    coordinator = LearningCoordinator(field, limbic_state)
    field.add_relation(src, rel_type, tgt, why=why, ...)
    coordinator.on_fact(src, rel_type, tgt, why=why,
                        evidence_score=ev, support_count=n)
"""
from __future__ import annotations

import math
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nouse.field.surface import FieldSurface
    from nouse.limbic.signals import LimbicState

_log = logging.getLogger("nouse.learning")

BASE_DELTA      = float(os.getenv("NOUSE_LEARN_BASE_DELTA", "0.05"))
SPREAD_DECAY    = float(os.getenv("NOUSE_LEARN_SPREAD_DECAY", "0.4"))
CONFIDENCE_GATE = float(os.getenv("NOUSE_LEARN_CONFIDENCE_GATE", "0.65"))


class LearningCoordinator:
    """
    Anropas efter varje add_relation() — genomför alla plasticitets-operationer.
    Är stateless förutom referenserna till field och limbic_state.
    """

    def __init__(self, field: "FieldSurface", limbic: "LimbicState"):
        self.field = field
        self.limbic = limbic

    # ── P1: Limbic-modulerat delta ─────────────────────────────────────────

    def _compute_delta(self) -> float:
        """
        Δw = BASE_DELTA × (1 + noradrenaline)

        Noradrenalin mäter överraskning/nyhet.
        Vid baseline (0.3): Δw = 0.05 × 1.3 = 0.065
        Vid max nyhet (1.0): Δw = 0.05 × 2.0 = 0.10
        Vid vila (0.0):      Δw = 0.05 × 1.0 = 0.05
        """
        return BASE_DELTA * (1.0 + self.limbic.noradrenaline)

    # ── P2: Spreading activation ───────────────────────────────────────────

    def _spread(self, node: str, delta: float) -> None:
        """
        Stärk befintliga grannar med avtagande delta (ett hopp).
        spread_delta = delta × SPREAD_DECAY

        Simulerar temporal summation: noder som nyligen haft aktivitet
        är mer mottagliga för förstärkning (eligibility trace).
        """
        spread_delta = delta * SPREAD_DECAY
        if spread_delta < 0.001:
            return
        for rel in self.field.out_relations(node):
            try:
                self.field.strengthen(node, rel["target"], spread_delta)
            except Exception:
                pass

    # ── P3: Assumption flag evolution ─────────────────────────────────────

    def _evolve_assumption(self, src: str, tgt: str, evidence_score: float) -> None:
        """
        Rensa assumption_flag = True → False när evidence_score ≥ CONFIDENCE_GATE.

        I b76 sätts assumption_flag=True när 'why' saknas vid skapandet.
        Den rensas aldrig automatiskt — detta fixar det.
        """
        if evidence_score < CONFIDENCE_GATE:
            return
        try:
            self.field.clear_assumption_flags(src, tgt)
        except Exception:
            pass

    # ── P4: Granularity update ─────────────────────────────────────────────

    def _update_granularity(self, name: str, support_count: int) -> None:
        """
        granularity = 1 + min(4, floor(log2(support_count)))

        support_count  →  granularity
             1         →     1  (ny/osäker)
             2-3       →     2
             4-7       →     3
             8-15      →     4
            16+        →     5  (konsoliderad)
        """
        g = 1 + min(4, int(math.floor(math.log2(max(1, support_count)))))
        try:
            self.field.set_concept_granularity(name, g)
        except Exception:
            pass

    # ── Huvud-ingångspunkt ────────────────────────────────────────────────

    def on_fact(
        self,
        src: str,
        rel_type: str,
        tgt: str,
        *,
        why: str = "",
        evidence_score: float = 0.35,
        support_count: int = 1,
    ) -> None:
        """
        Anropas direkt efter field.add_relation() med samma argument.

        Ordning är viktig:
          1. Beräkna delta (limbic-modulerat)
          2. Stärk direktkanten (P1)
          3. Sprid aktivering till grannar (P2)
          4. Rensa assumption_flag om evidensen håller (P3)
          5. Uppdatera granularitet för båda noderna (P4)
        """
        delta = self._compute_delta()
        _log.debug(
            "on_fact %s─[%s]→%s  Δw=%.4f  NA=%.2f  ev=%.2f  support=%d",
            src, rel_type, tgt, delta, self.limbic.noradrenaline,
            evidence_score, support_count,
        )

        # P1: Stärk direktkanten
        self.field.strengthen(src, tgt, delta)

        # P2: Spreading activation från båda ändar
        self._spread(src, delta)
        self._spread(tgt, delta)

        # P3: Rensa assumption_flag om evidensen räcker
        self._evolve_assumption(src, tgt, evidence_score)

        # P4: Uppdatera granularitet
        self._update_granularity(src, support_count)
        self._update_granularity(tgt, support_count)

        # Emit: kant tillagd → realtidsvisualisering
        try:
            from nouse.field.events import emit as _emit
            _emit(
                "edge_added",
                src=src, rel=rel_type, tgt=tgt,
                evidence_score=round(evidence_score, 3),
                delta=round(delta, 4),
            )
        except Exception:
            pass
