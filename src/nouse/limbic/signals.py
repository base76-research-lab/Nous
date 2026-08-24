"""
Limbic Layer — Neuromodulering
===============================
Implementerar de tre neurotransmittorerna från HANDOFF_BrainGroundedAI.md:

  Dopamin      = TD error δ = r + γV(s') - V(s)
                 Styr belöningssignal och λ (kreativitetskofficient)

  Noradrenalin = Surprise = -log P(x)
                 Styr uppmärksamhet och pruning-aggressivitet

  Acetylkolin  = β (attention temperature i WTA softmax)
                 Styr hur "fokuserat" Global Workspace väljer vinnare

Signalerna körs PARALLELLT med alla lager — de sätter gain, inte content.
Tillståndet är persistent mellan brain-cykler (hemeostatisk kontroll).

Yerkes-Dodson: performance = -k(arousal - optimal)² + max
"""
from __future__ import annotations

import math
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path

log = logging.getLogger("nouse.limbic")

_STATE_FILE = Path.home() / ".local" / "share" / "nouse" / "limbic_state.json"

# ── Homeostasparametrar ───────────────────────────────────────────────────────

DOPAMINE_BASELINE      = 0.5    # neutral belöningsnivå
NORADRENALINE_BASELINE = 0.3    # neutral surprisenivå
ACETYLCHOLINE_BASELINE = 1.0    # neutral β (attention temp)

DOPAMINE_DECAY         = 0.15   # TD-error avtar per cykel
NORADRENALINE_DECAY    = 0.20   # surprise avtar snabbare
ACETYLCHOLINE_DECAY    = 0.10   # β återgår till baseline

AROUSAL_OPTIMAL        = 0.6    # Yerkes-Dodson optimal arousal
AROUSAL_K              = 2.0    # kurvskärpa

# λ-intervall (kreativitetskoefficient i F_bisoc)
LAMBDA_MIN = 0.1
LAMBDA_MAX = 0.9

# Energibudget (Fas 3 punkt 10, docs/NOUS_NEXT_GENERATION_PLAN.md): sjunker
# med faktiska LLM-anrop denna cykel, återhämtar sig långsamt mot 1.0.
# Distinkt från self_layer/living_core.pys "energy" (en homeostas-blandning
# av dopamin/arousal/kö-tryck) — den här signalen mäter faktisk kostnad,
# inte upplevd belastning.
ENERGY_BUDGET_BASELINE = 1.0
ENERGY_BUDGET_COST_PER_CALL = 0.03   # ~33 anrop dränerar budgeten till 0 i en cykel
ENERGY_BUDGET_RECOVERY = 0.08        # återhämtning mot baslinjen per cykel


# ── Tillståndsmodell ─────────────────────────────────────────────────────────

# Tonic EMA-koefficient: hur snabbt baslinjen anpassar sig
# α=0.002 → ~500 cykler för att nå ny baslinje (ca 17h vid 2min/cykel)
TONIC_EMA_ALPHA = 0.002


@dataclass
class LimbicState:
    dopamine:       float = DOPAMINE_BASELINE
    noradrenaline:  float = NORADRENALINE_BASELINE
    acetylcholine:  float = ACETYLCHOLINE_BASELINE
    cycle:          int   = 0
    lam:            float = 0.5   # nuvarande λ (kreativitetskoefficient)
    energy_budget:  float = ENERGY_BUDGET_BASELINE  # faktisk anropskostnad, se update_energy_budget

    # Tonic baslinjer — rör sig långsamt, representerar "personlighetsdisposition"
    tonic_dopamine:      float = DOPAMINE_BASELINE
    tonic_noradrenaline: float = NORADRENALINE_BASELINE

    @property
    def arousal(self) -> float:
        """Sammanvägd arousal-nivå [0, 1]."""
        return 0.4 * self.dopamine + 0.4 * self.noradrenaline + 0.2 * self.acetylcholine

    @property
    def performance(self) -> float:
        """Yerkes-Dodson prestationsindex [0, 1]."""
        a = self.arousal
        return max(0.0, 1.0 - AROUSAL_K * (a - AROUSAL_OPTIMAL) ** 2)

    @property
    def pruning_aggression(self) -> float:
        """
        Hög noradrenalin (surprise) → mer aggressiv pruning.
        [0.1 (varsam) → 0.9 (aggressiv)]
        """
        return max(0.1, min(0.9, self.noradrenaline * 1.5))

    @property
    def wta_beta(self) -> float:
        """WTA softmax temperature för Global Workspace."""
        return self.acetylcholine * 2.0   # β ∈ [0, ~4]

    @property
    def phasic_dopamine(self) -> float:
        """Phasic signal: avvikelse från tonic baslinje. Positiv = belöning, negativ = besvikelse."""
        return self.dopamine - self.tonic_dopamine

    @property
    def phasic_noradrenaline(self) -> float:
        """Phasic signal: avvikelse från tonic baslinje. Positiv = oväntat, negativ = tråkigt."""
        return self.noradrenaline - self.tonic_noradrenaline

    @property
    def disposition_label(self) -> str:
        """
        Beskriver systemets nuvarande karaktärsdisposition baserat på tonic-nivåer.
        Emergerar ur erfarenhet — inte hårdkodat.
        """
        if self.tonic_dopamine > 0.65 and self.tonic_noradrenaline > 0.45:
            return "nyfiken-entusiastisk"
        if self.tonic_dopamine > 0.65:
            return "belöningsorienterad"
        if self.tonic_noradrenaline > 0.45:
            return "vaksam-kritisk"
        if self.tonic_dopamine < 0.35:
            return "konservativ-konsoliderande"
        return "balanserad"


def load_state() -> LimbicState:
    if _STATE_FILE.exists():
        try:
            d = json.loads(_STATE_FILE.read_text())
            return LimbicState(**d)
        except Exception:
            pass
    return LimbicState()


def save_state(state: LimbicState) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(asdict(state), indent=2))


# ── Signalberäkningar ────────────────────────────────────────────────────────

def update_dopamine(state: LimbicState, new_relations: int,
                    discoveries: int) -> None:
    """
    TD error: δ = reward - baseline
    Belöning = nya relationer + bisociations-discoveries.
    Decay mot baseline exponentiellt.
    """
    reward = math.log1p(new_relations + discoveries * 3) / 5.0
    td_error = reward - DOPAMINE_BASELINE
    state.dopamine = DOPAMINE_BASELINE + (
        (state.dopamine - DOPAMINE_BASELINE + td_error) * (1 - DOPAMINE_DECAY)
    )
    state.dopamine = max(0.0, min(1.0, state.dopamine))


def update_noradrenaline(state: LimbicState,
                          bisociation_candidates: int,
                          novel_domains: int) -> None:
    """
    Surprise = -log P(x).
    Fler bisociation-kandidater = fler oväntade strukturer = mer noradrenalin.
    """
    surprise = math.log1p(bisociation_candidates + novel_domains) / 6.0
    state.noradrenaline = NORADRENALINE_BASELINE + (
        (state.noradrenaline - NORADRENALINE_BASELINE + surprise)
        * (1 - NORADRENALINE_DECAY)
    )
    state.noradrenaline = max(0.0, min(1.0, state.noradrenaline))


def update_acetylcholine(state: LimbicState,
                          active_domains: int) -> None:
    """
    β stiger vid högt fokus (få aktiva domäner → mer selektivt).
    Fler domäner = bredare attention = lägre β.
    """
    focus = 1.0 / max(1, active_domains / 3)
    state.acetylcholine = ACETYLCHOLINE_BASELINE + (
        (state.acetylcholine - ACETYLCHOLINE_BASELINE + focus * 0.3)
        * (1 - ACETYLCHOLINE_DECAY)
    )
    state.acetylcholine = max(0.1, min(2.0, state.acetylcholine))


def update_energy_budget(state: LimbicState, llm_calls: int) -> None:
    """
    Energibudget: sjunker med faktiska LLM-anrop denna cykel (kostnad),
    återhämtar sig långsamt mot baslinjen oavsett belastning — biologisk
    trötthet/återhämtning, inte en cykel-modulo-räknare.
    """
    cost = max(0, int(llm_calls)) * ENERGY_BUDGET_COST_PER_CALL
    recovered = state.energy_budget + ENERGY_BUDGET_RECOVERY * (
        ENERGY_BUDGET_BASELINE - state.energy_budget
    )
    state.energy_budget = max(0.0, min(ENERGY_BUDGET_BASELINE, recovered - cost))


def update_lambda(state: LimbicState) -> None:
    """
    λ (kreativitetskoefficient i F_bisoc) styrs av dopamin och noradrenalin.

    Hög dopamin (belöning) + hög noradrenalin (surprise)
      → hög λ → systemet trycker mot eleganta kors-domänsyntser

    Låg dopamin + låg noradrenalin
      → låg λ → systemet konservativt, konsoliderar
    """
    raw_lam = (state.dopamine * 0.6 + state.noradrenaline * 0.4)
    state.lam = LAMBDA_MIN + raw_lam * (LAMBDA_MAX - LAMBDA_MIN)


# ── Cykel-uppdatering ────────────────────────────────────────────────────────

def run_limbic_cycle(
    state: LimbicState,
    new_relations: int,
    discoveries: int,
    bisociation_candidates: int,
    novel_domains: int,
    active_domains: int,
    llm_calls: int = 0,
) -> LimbicState:
    """
    Kör en full limbisk cykel och returnerar uppdaterat tillstånd.
    Anropas av brain-loopen en gång per cykel.

    llm_calls: antal faktiska LLM-anrop denna cykel (t.ex.
    sum(source_attempted_models.values()) i daemon/main.py) — driver
    energy_budget. 0 = ingen kostnadsdata tillgänglig, budgeten återhämtar
    sig bara.
    """
    state.cycle += 1

    update_dopamine(state, new_relations, discoveries)
    update_noradrenaline(state, bisociation_candidates, novel_domains)
    update_acetylcholine(state, active_domains)
    update_energy_budget(state, llm_calls)
    update_lambda(state)

    # Tonic EMA — uppdatera långsamma baslinjer (personlighetsdisposition)
    state.tonic_dopamine = (
        TONIC_EMA_ALPHA * state.dopamine
        + (1 - TONIC_EMA_ALPHA) * state.tonic_dopamine
    )
    state.tonic_noradrenaline = (
        TONIC_EMA_ALPHA * state.noradrenaline
        + (1 - TONIC_EMA_ALPHA) * state.tonic_noradrenaline
    )

    log.info(
        f"Limbic [cykel {state.cycle}]: "
        f"DA={state.dopamine:.2f}(tonic={state.tonic_dopamine:.2f}) "
        f"NA={state.noradrenaline:.2f}(tonic={state.tonic_noradrenaline:.2f}) "
        f"ACh={state.acetylcholine:.2f} "
        f"λ={state.lam:.2f} "
        f"energy_budget={state.energy_budget:.2f} "
        f"arousal={state.arousal:.2f} "
        f"perf={state.performance:.2f} "
        f"disposition={state.disposition_label}"
    )

    save_state(state)
    return state
