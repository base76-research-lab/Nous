"""
daemon.cognitive_policy — Kognitiv policy-styrning
====================================================
Sparar och läser aktiv policy-state som justerar systembeteende
baserat på reflektioner och evalving-trender.

Policy-parametrar:
  - extraction_threshold:  hur selektiv ingestion ska vara (0.0–1.0)
  - evidence_floor:        lägsta evidens för konsolidering (0.0–1.0)
  - lam_override:         kreativitetsparameter override (None = auto)
  - curiosity_priority:    prioritet för kunskapsgap ("low"|"normal"|"high")

Standardvärden hämtas från miljövariabler med fallback.
Ändringar loggas som audit-trail i journal.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nouse.config.paths import path_from_env

_log = logging.getLogger("nouse.cognitive_policy")

POLICY_PATH = path_from_env("NOUSE_COGNITIVE_POLICY", "cognitive_policy.json")


@dataclass
class CognitivePolicy:
    """Aktiv kognitiv policy — justerar daemon-beteende per cykel."""
    extraction_threshold: float = 0.35
    evidence_floor: float = 0.45
    lam_override: float | None = None     # None = använd limbic auto
    curiosity_priority: str = "normal"    # "low"|"normal"|"high"
    # Audit-spår
    last_change_ts: str = ""
    last_change_reason: str = ""
    change_count: int = 0

    def effective_lam(self, limbic_lam: float) -> float:
        """Returnera lam_override om satt, annars limbic auto-värde."""
        if self.lam_override is not None:
            return self.lam_override
        return limbic_lam


# ── Persistence ────────────────────────────────────────────────────────────────

def load_policy(path: Path | None = None) -> CognitivePolicy:
    """Läs policy från fil, returnera default om fil saknas."""
    target = path or POLICY_PATH
    if not target.exists():
        return CognitivePolicy()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            # Filtrera bort okända nycklar
            known = {f.name for f in CognitivePolicy.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in known}
            return CognitivePolicy(**filtered)
    except Exception as e:
        _log.warning("Kunde inte läsa cognitive_policy: %s — använder default", e)
    return CognitivePolicy()


def save_policy(policy: CognitivePolicy, path: Path | None = None) -> Path:
    """Skriv policy till fil."""
    target = path or POLICY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(policy)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _log.debug("Policy sparad: %s", target)
    return target


# ── Policy-triggers ────────────────────────────────────────────────────────────

# Trigger-regler: mätvärde → (villkor, parameter, delta)
# Utlöses av living_core-reflektioner OCH evalving-trender.

TRIGGER_RULES: list[dict[str, Any]] = [
    {
        "metric": "energy",
        "condition": "below",
        "threshold": 0.30,
        "param": "extraction_threshold",
        "delta": +0.10,
        "reason": "energy < 0.3 → var mer selektiv",
    },
    {
        "metric": "contradiction_catch_rate",
        "condition": "below",
        "threshold": 0.10,
        "param": "evidence_floor",
        "delta": -0.05,
        "reason": "contradiction_catch_rate < 0.1 → sänk tröskel, fler granskas",
    },
    {
        "metric": "bisociation_quality",
        "condition": "below",
        "threshold": 0.30,
        "param": "lam_override",
        "delta": +0.10,
        "reason": "bisociation_quality < 0.3 → öka kreativitet",
    },
    {
        "metric": "gap_map_shrink_rate",
        "condition": "below",
        "threshold": 0.0,
        "param": "curiosity_priority",
        "value": "high",
        "reason": "gap_map_shrink_rate < 0 → prioritera kunskapsgap",
    },
    {
        "metric": "goal_satisfaction_rate",
        "condition": "below",
        "threshold": 0.20,
        "param": "curiosity_priority",
        "value": "high",
        "reason": "goal_satisfaction_rate < 0.2 → prioritera kunskapsgap",
    },
    {
        "metric": "goals_active",
        "condition": "above",
        "threshold": 15,
        "param": "extraction_threshold",
        "delta": +0.05,
        "reason": "too many active goals → var mer selektiv med nya mål",
    },
]


def evaluate_triggers(
    metrics: dict[str, float | str],
    policy: CognitivePolicy | None = None,
) -> list[dict[str, Any]]:
    """
    Evaluera trigger-regler mot nuvarande mätvärden.

    Returnerar lista med avfyrade triggers (inklusive föreslagen ändring).
    Uppdaterar INTE policy automatiskt — anroparen bestämmer.
    """
    policy = policy or load_policy()
    fired: list[dict[str, Any]] = []

    for rule in TRIGGER_RULES:
        metric = rule["metric"]
        value = metrics.get(metric)
        if value is None:
            continue

        threshold = rule["threshold"]
        condition = rule["condition"]

        if condition == "below" and float(value) < threshold:
            fired.append(rule)
        elif condition == "above" and float(value) > threshold:
            fired.append(rule)

    return fired


def apply_triggers(
    triggers: list[dict[str, Any]],
    policy: CognitivePolicy | None = None,
    source: str = "reflection",
) -> tuple[CognitivePolicy, list[dict[str, Any]]]:
    """
    Tillämpa avfyrade triggers på policy.

    Returnerar (uppdaterad policy, audit-logg-entries).
    Begränsar ändringar per parameter till max ±0.3 från default.
    """
    policy = policy or load_policy()
    defaults = CognitivePolicy()
    audit: list[dict[str, Any]] = []
    ts = datetime.now(timezone.utc).isoformat()

    for trigger in triggers:
        param = trigger["param"]
        old_val = getattr(policy, param)
        delta = trigger.get("delta", 0)
        new_val = trigger.get("value")

        if new_val is not None:
            # Sträng-param (t.ex. curiosity_priority)
            if old_val == new_val:
                continue  # ingen ändring
            setattr(policy, param, new_val)
        else:
            # Numerisk parameter — applicera delta med gränser
            default_val = getattr(defaults, param)
            default_num = float(default_val) if default_val is not None else 0.5
            base_val = float(old_val) if old_val is not None else default_num
            proposed = base_val + float(delta)
            # Klampa till max ±0.3 från default
            lo = default_num - 0.30
            hi = default_num + 0.30
            new_val = max(lo, min(hi, proposed))
            # Avrunda till 2 decimaler
            new_val = round(new_val, 2)
            old_num = float(old_val) if old_val is not None else default_num
            if abs(float(new_val) - old_num) < 0.005:
                continue  # för liten ändring
            setattr(policy, param, new_val)

        audit.append({
            "ts": ts,
            "source": source,
            "param": param,
            "old_value": old_val,
            "new_value": new_val,
            "reason": trigger["reason"],
            "metric": trigger["metric"],
        })

    if audit:
        policy.last_change_ts = ts
        policy.last_change_reason = audit[-1]["reason"]
        policy.change_count += 1

    return policy, audit


def evaluate_and_apply(
    metrics: dict[str, float | str],
    policy: CognitivePolicy | None = None,
    source: str = "reflection",
) -> tuple[CognitivePolicy, list[dict[str, Any]]]:
    """
    Fullständig evaluerings- och tillämpningscykel.

    1. Evaluera triggers mot mätvärden
    2. Tillämpa avfyrade triggers på policy
    3. Spara policy om ändringar gjordes
    4. Logga audit-trail till journal

    Returnerar (uppdaterad policy, audit-entries).
    """
    policy = policy or load_policy()
    triggers = evaluate_triggers(metrics, policy)
    policy, audit = apply_triggers(triggers, policy, source=source)

    if audit:
        save_policy(policy)
        _log_audit(audit)

    return policy, audit


# ── Audit-trail ────────────────────────────────────────────────────────────────

def _log_audit(entries: list[dict[str, Any]]) -> None:
    """Skriv audit-entries till journal."""
    try:
        from nouse.daemon.journal import write_cycle_trace
        for entry in entries:
            write_cycle_trace(
                cycle=0,  # okänd cykel här
                stage="policy_change",
                thought=entry.get("reason", ""),
                action=f"{entry['param']}: {entry['old_value']} → {entry['new_value']}",
                result=f"metric={entry['metric']} source={entry['source']}",
                details=entry,
            )
    except Exception as e:
        _log.warning("Audit-trail loggning misslyckades: %s", e)


def reset_policy(path: Path | None = None) -> CognitivePolicy:
    """Återställ policy till default-värden."""
    policy = CognitivePolicy()
    save_policy(policy, path)
    _log.info("Policy återställd till default")
    return policy