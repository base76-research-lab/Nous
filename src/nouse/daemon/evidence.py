"""
nouse.daemon.evidence — heuristic evidence model + activation accumulator
=========================================================================
Ger varje föreslagen relation:
    - evidence_score (0..1)  — heuristic score inspired by Bayesian updating
  - trust_tier             — hypotes | indikation | validerad
  - rationale              — spårbar motiveringskedja

Bayesian-inspired heuristic model:
  Prior P(true) baseras på strukturella signaler (har motivering, domänkorsning, etc.)
  Likelihood-uppdatering med bekräftande och motstridiiga relationer i grafen:
    P(true | k bekräftningar, m motstridigheter) ∝ prior × LR^k × (1-LR)^m
  LR = likelihood ratio (satt till 3.0 för bekräftning, 0.4 för motbevisning)

Aktiveringsackumulator (P2 — evidenspromotion):
  - activate_relation(): varje aktivering (query-träff, bisociation) → w+=0.02, u-=0.01
  - confirm_relation(): ny källa bekräftar → ev+=0.05
  - run_evidence_pass(): NightRun-granskning av kanter 0.35 < ev < 0.65
  - measure_crystallization(): kristalliseringsgrad + evidenskvalitet
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
import math
import re
from typing import Any

_log = logging.getLogger("nouse.evidence")


_NUMERIC_CUE_RE = re.compile(r"\b\d+([.,]\d+)?(%|x| gånger| fold)?\b", re.IGNORECASE)

# Likelihood ratio för en bekräftande respektive motstridig relation
_LR_CONFIRM     = 3.0   # en bekräftande relation tredubblar oddsen
_LR_CONTRADICT  = 0.4   # en motstridig relation mer än halverar oddsen

# Maximalt bidrag från graph-signaler (förhindrar att grafen ensam driver till 1.0)
_MAX_GRAPH_BOOST = 0.25


@dataclass(frozen=True)
class EvidenceAssessment:
    score: float
    tier: str
    rationale: str


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _tier(score: float) -> str:
    if score >= 0.78:
        return "validerad"
    if score >= 0.52:
        return "indikation"
    return "hypotes"


def _prior_from_signals(
    why: str,
    rel_type: str,
    domain_src: str,
    domain_tgt: str,
    task: dict[str, Any] | None,
    src: str,
    tgt: str,
) -> tuple[float, list[str]]:
    """
    Beräkna prior P(true) från strukturella signaler.
    Returnerar (prior, reasons).
    """
    score = 0.35
    reasons: list[str] = []

    if why:
        reasons.append("har motivering")
        score += 0.12
        if len(why) >= 80:
            score += 0.08
            reasons.append("detaljrik motivering")
        if _NUMERIC_CUE_RE.search(why):
            score += 0.10
            reasons.append("kvantitativ signal")
    else:
        score -= 0.10
        reasons.append("saknar motivering")

    if domain_src and domain_tgt and domain_src != domain_tgt:
        score += 0.07
        reasons.append("domänkorsning")

    if rel_type in {"orsakar", "reglerar", "producerar"} and not why:
        score -= 0.08
        reasons.append("stark relationstyp utan evidens")

    if task:
        focus = {str(c).lower() for c in (task.get("concepts") or [])}
        if src.lower() in focus or tgt.lower() in focus:
            score += 0.08
            reasons.append("träffar explicit gap-koncept")

    return _clamp(score), reasons


def _bayesian_update(
    prior: float,
    confirming: int,
    contradicting: int,
) -> tuple[float, list[str]]:
    """
    Uppdatera prior med handvalda likelihood-ratio-vikter.

    Använder log-odds representation för numerisk stabilitet:
      log_odds_posterior = log_odds_prior + k*log(LR_c) + m*log(LR_m)
    """
    if confirming == 0 and contradicting == 0:
        return prior, []

    reasons: list[str] = []
    log_odds_prior = math.log(prior / (1.0 - prior + 1e-9) + 1e-9)

    if confirming > 0:
        log_odds_prior += confirming * math.log(_LR_CONFIRM)
        reasons.append(f"{confirming} bekräftande relation(er) i grafen")

    if contradicting > 0:
        log_odds_prior += contradicting * math.log(_LR_CONTRADICT)
        reasons.append(f"{contradicting} motstridig(a) relation(er) i grafen")

    posterior = 1.0 / (1.0 + math.exp(-log_odds_prior))

    # Begränsa bidraget från graph-signaler
    delta = _clamp(posterior - prior, lo=-_MAX_GRAPH_BOOST, hi=_MAX_GRAPH_BOOST)
    return _clamp(prior + delta), reasons


def assess_relation(
    relation: dict[str, Any],
    task: dict[str, Any] | None = None,
    confirming_relations: int = 0,
    contradicting_relations: int = 0,
) -> EvidenceAssessment:
    """
    Bayesian-inspired heuristic assessment for a proposed relation.

    Args:
        relation:               Relationsdict med src, tgt, type, why, domain_src, domain_tgt.
        task:                   Aktivt research-task (om någon), för gap-matchning.
        confirming_relations:   Antal befintliga grafstigar som stödjer denna relation.
        contradicting_relations: Antal befintliga grafstigar som motstrider denna relation.
    """
    why       = str(relation.get("why") or "").strip()
    src       = str(relation.get("src") or "")
    tgt       = str(relation.get("tgt") or "")
    rel_type  = str(relation.get("type") or relation.get("rel_type") or "")
    domain_src = str(relation.get("domain_src") or "")
    domain_tgt = str(relation.get("domain_tgt") or "")

    prior, prior_reasons = _prior_from_signals(
        why, rel_type, domain_src, domain_tgt, task, src, tgt
    )
    posterior, graph_reasons = _bayesian_update(prior, confirming_relations, contradicting_relations)

    all_reasons = prior_reasons + graph_reasons
    rationale = "; ".join(all_reasons) if all_reasons else "basbedömning"
    tier = _tier(posterior)

    return EvidenceAssessment(
        score=round(posterior, 3),
        tier=tier,
        rationale=rationale,
    )


def format_why_with_evidence(original_why: str, assessment: EvidenceAssessment) -> str:
    prefix = (
        f"[trust:{assessment.tier} evidence:{assessment.score:.3f}] "
        f"[rationale:{assessment.rationale}]"
    )
    body = (original_why or "").strip()
    if body:
        return f"{prefix} {body}"
    return prefix


# ── Aktiveringsackumulator (P2 — evidenspromotion) ────────────────────────────
# Trösklar för kristallisering och evidenspass
CRYSTAL_STRENGTH_FLOOR   = 0.55      # w > denna → kristalliserad
EVIDENCE_PROMOTE_FLOOR   = 0.65      # ev > denna → stark/validerad
EVIDENCE_DEMOTE_CEILING  = 0.35      # ev < denna → svag/hypotes
CONFIRMATION_DELTA        = 0.05     # ev-ökning per bekräftelse
ACTIVATION_W_DELTA        = 0.02     # styrkeökning per aktivering
ACTIVATION_EV_DELTA       = 0.01     # ev-ökning per aktivering
EVIDENCE_CAP              = 1.0
STRENGTH_CAP              = 3.5


@dataclass
class AccumulationResult:
    """Resultat av en ackumulerings- eller evidenspass-cykel."""
    activated: int = 0          # antal aktiverade relationer
    confirmed: int = 0          # antal bekräftade relationer
    promoted: int = 0          # antal som gick upp i evidenskategori
    demoted: int = 0           # antal som gick ner i evidenskategori


@dataclass
class CrystallizationMetrics:
    """Mätvärden för grafkristallisering."""
    total_relations: int = 0
    crystallized: int = 0            # w > CRYSTAL_STRENGTH_FLOOR
    crystallization_rate: float = 0.0   # crystallized / total
    evidence_quality: float = 0.0      # medel-ev på kristalliserade
    mean_evidence: float = 0.0          # medel-ev på alla relationer
    tier_counts: dict[str, int] = field(default_factory=dict)


def activate_relation(
    field,
    src: str,
    tgt: str,
    *,
    source: str = "query",
) -> bool:
    """
    Styrk en relation vid aktivering (query-träff, bisociation, etc.).
    w_delta = +0.02 (Hebbisk förstärkning)
    ev_delta = +0.01 (liten evidensboost)
    """
    try:
        field.strengthen(src, tgt, delta=ACTIVATION_W_DELTA,
                         rel_type=rel_type, ceiling=STRENGTH_CAP)
        _bump_evidence(field, src, tgt, delta=ACTIVATION_EV_DELTA,
                       rel_type=rel_type)
        _log.debug("Aktiverade: %s→%s (källa=%s)", src, tgt, source)
        return True
    except Exception as e:
        _log.warning("Aktiveringsfel för %s→%s: %s", src, tgt, e)
        return False


def confirm_relation(
    field,
    src: str,
    tgt: str,
    *,
    rel_type: str | None = None,
    confidence: float = 0.0,
    source: str = "corroboration",
) -> bool:
    """
    Bekräfta en relation från ny källa.

    evidence_score += CONFIRMATION_DELTA (eller confidence om angivet)
    Styrkan förstärks proportionellt.
    """
    delta = confidence if confidence > 0 else CONFIRMATION_DELTA
    try:
        _bump_evidence(field, src, tgt, delta=delta, rel_type=rel_type)
        field.strengthen(src, tgt, delta=delta * 0.4,
                         rel_type=rel_type, ceiling=STRENGTH_CAP)
        _log.debug("Bekräftade: %s→%s (ev+%.3f, källa=%s)", src, tgt, delta, source)
        return True
    except Exception as e:
        _log.warning("Bekräftelsefel för %s→%s: %s", src, tgt, e)
        return False


def run_evidence_pass(
    field,
    *,
    max_items: int = 500,
) -> AccumulationResult:
    """
    NightRun evidens-pass: granska kanter med 0.35 < ev < 0.65.

    För varje sådan relation:
      - ev >= 0.65: promovisera (ev += 0.05)
      - ev < 0.35: demovera (ev -= 0.05)
      - annars: liten boost (ev += 0.01)
    """
    result = AccumulationResult()

    try:
        rows = field._sql.execute(
            "SELECT src, type, tgt, evidence_score FROM relation "
            "WHERE evidence_score > ? AND evidence_score < ? "
            "ORDER BY evidence_score DESC LIMIT ?",
            (EVIDENCE_DEMOTE_CEILING, EVIDENCE_PROMOTE_FLOOR, max_items),
        ).fetchall()
    except Exception as e:
        _log.warning("Evidence pass: kunde inte hämta kandidater: %s", e)
        return result

    for row in rows:
        src = row["src"]
        tgt = row["tgt"]
        rel_type = row.get("type") or row.get("rel_type")
        old_ev = float(row.get("evidence_score", 0.5) or 0.5)
        old_tier = _tier(old_ev)

        if old_ev >= EVIDENCE_PROMOTE_FLOOR:
            new_ev = min(EVIDENCE_CAP, old_ev + CONFIRMATION_DELTA)
        elif old_ev < EVIDENCE_DEMOTE_CEILING:
            new_ev = max(0.0, old_ev - CONFIRMATION_DELTA)
        else:
            new_ev = min(EVIDENCE_CAP, old_ev + 0.01)

        new_tier = _tier(new_ev)
        _set_evidence(field, src, tgt, new_ev, rel_type=rel_type)

        if new_tier != old_tier:
            if new_tier > old_tier:
                result.promoted += 1
            else:
                result.demoted += 1

        result.activated += 1

    _log.info(
        "Evidence pass: granskade=%d promoted=%d demoted=%d",
        result.activated, result.promoted, result.demoted,
    )
    return result


def measure_crystallization(field) -> CrystallizationMetrics:
    """
    Beräkna kristalliseringsgrad och evidenskvalitet för grafen.

    crystallization_rate = kanter med w > 0.55 / totalt antal kanter
    evidence_quality = medel-evidence_score på kristalliserade kanter
    """
    metrics = CrystallizationMetrics()
    tier_counts: dict[str, int] = {"hypotes": 0, "indikation": 0, "validerad": 0}

    try:
        rows = field.query_all_relations_with_metadata(
            limit=50000, include_evidence=True,
        )
    except Exception as e:
        _log.warning("Crystallization: kunde inte hämta relationer: %s", e)
        metrics.tier_counts = tier_counts
        return metrics

    total = len(rows)
    crystallized = 0
    ev_sum_crystallized = 0.0
    ev_sum_all = 0.0

    for row in rows:
        ev = float(row.get("evidence_score", 0.5) or 0.5)
        strength = float(row.get("strength", 1.0) or 1.0)
        ev_sum_all += ev

        tier_key = _tier_label_accum(ev)
        tier_counts[tier_key] = tier_counts.get(tier_key, 0) + 1

        if strength > CRYSTAL_STRENGTH_FLOOR:
            crystallized += 1
            ev_sum_crystallized += ev

    metrics.total_relations = total
    metrics.crystallized = crystallized
    metrics.crystallization_rate = round(crystallized / total, 4) if total > 0 else 0.0
    metrics.evidence_quality = round(ev_sum_crystallized / crystallized, 4) if crystallized > 0 else 0.0
    metrics.mean_evidence = round(ev_sum_all / total, 4) if total > 0 else 0.0
    metrics.tier_counts = tier_counts

    _log.info(
        "Crystallization: %d/%d kanter kristalliserade (%.1f%%), "
        "ev_quality=%.3f, tiers=%s",
        crystallized, total, metrics.crystallization_rate * 100,
        metrics.evidence_quality, tier_counts,
    )
    return metrics


# ── Interna hjälpfunktioner ────────────────────────────────────────────────────

def _bump_evidence(field, src, tgt, delta, *, rel_type=None):
    """Öka evidence_score på en relation med delta, taket 1.0."""
    try:
        with field._lock:
            cur = field._sql.execute(
                "SELECT evidence_score FROM relation WHERE src = ? AND tgt = ?",
                (src, tgt),
            )
            row = cur.fetchone()
            if row is None:
                return
            old_ev = float(row["evidence_score"] or 0.5)
            new_ev = min(EVIDENCE_CAP, old_ev + delta)
            field._sql.execute(
                "UPDATE relation SET evidence_score = ? WHERE src = ? AND tgt = ?",
                (new_ev, src, tgt),
            )
            field._sql.commit()

        # Synka NetworkX
        if hasattr(field, "_G") and field._G.has_edge(src, tgt):
            for key in field._G[src][tgt]:
                if rel_type and field._G[src][tgt][key].get("type") != rel_type:
                    continue
                field._G[src][tgt][key]["evidence_score"] = new_ev
    except Exception as e:
        _log.debug("Evidence bump-fel för %s→%s: %s", src, tgt, e)


def _set_evidence(field, src, tgt, evidence_score, *, rel_type=None):
    """Sätt evidence_score direkt på en relation."""
    try:
        with field._lock:
            field._sql.execute(
                "UPDATE relation SET evidence_score = ? WHERE src = ? AND tgt = ?",
                (evidence_score, src, tgt),
            )
            field._sql.commit()

        if hasattr(field, "_G") and field._G.has_edge(src, tgt):
            for key in field._G[src][tgt]:
                if rel_type and field._G[src][tgt][key].get("type") != rel_type:
                    continue
                field._G[src][tgt][key]["evidence_score"] = evidence_score
    except Exception as e:
        _log.debug("Evidence set-fel för %s→%s: %s", src, tgt, e)


def _tier_label_accum(ev: float) -> str:
    """Evidenskategori som sträng (för ackumulatorns mätvärden)."""
    if ev >= EVIDENCE_PROMOTE_FLOOR:
        return "validerad"
    if ev >= EVIDENCE_DEMOTE_CEILING:
        return "indikation"
    return "hypotes"
