"""
nouse.daemon.homeostasis — Autonomic brain region balancing
===========================================================
Checks brain region distribution every N cycles and auto-seeds
underrepresented regions. Mirrors biological homeostasis: the system
maintains balance even with biased input sources.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger("nouse.homeostasis")

# Atlas region name → SEED_DOMAINS key (from seed_cmd.py)
ATLAS_TO_SEED: dict[str, str] = {
    "frontal_lobe": "frontal",
    "hippocampus": "hippocampus",
    "amygdala": "amygdala",
    "temporal_lobe": "temporal_left",
    "occipital_lobe": "occipital",
    "cerebellum": "cerebellum",
}

HOMEOSTASIS_LOW_PCT = float(os.getenv("NOUSE_HOMEOSTASIS_LOW_PCT", "0.05"))
HOMEOSTASIS_HIGH_PCT = float(os.getenv("NOUSE_HOMEOSTASIS_HIGH_PCT", "0.40"))
HOMEOSTASIS_MODEL = os.getenv("NOUSE_HOMEOSTASIS_MODEL", "minimax-m2.7:cloud")


async def _seed_region_async(
    field: Any,
    atlas_region: str,
    seed_key: str,
    *,
    model: str,
) -> dict:
    """Async seed — safe to call from inside brain_loop."""
    from nouse.cli.commands.seed_cmd import (
        SEED_DOMAINS,
        SEED_PROMPT,
        call_llm_for_seed,
    )
    from nouse.field.brain_topology import classify_domain

    if seed_key not in SEED_DOMAINS:
        return {"error": f"no SEED_DOMAINS entry for {seed_key}"}

    region_info = SEED_DOMAINS[seed_key]
    domain = region_info["domain"]

    existing_names: set[str] = {c["name"] for c in field.concepts()}
    existing_in_region = [
        c["name"] for c in field.concepts()
        if classify_domain(c.get("domain", "unknown")) == atlas_region
    ]
    existing_str = ", ".join(existing_in_region[:30]) if existing_in_region else "(empty)"

    new_predefined = [c for c in region_info["key_concepts"] if c not in existing_names]

    added = 0
    for name in new_predefined:
        try:
            field.add_concept(
                name, domain=domain, granularity=1,
                source="homeostasis_bootstrap", ensure_knowledge=True,
            )
            added += 1
        except Exception:
            pass

    llm_generated = 0
    if model:
        prompt = SEED_PROMPT.format(
            domain=domain,
            region=seed_key,
            description=region_info["description"],
            existing=existing_str,
        )
        try:
            response = await call_llm_for_seed(model, prompt, timeout=90.0)
            cleaned = response.strip()
            if cleaned.startswith("```"):
                nl = cleaned.find("\n")
                cleaned = cleaned[nl + 1:] if nl >= 0 else cleaned
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3].strip()
            parsed = json.loads(cleaned)
            for concept_data in parsed.get("concepts", []):
                name = concept_data.get("name", "")
                if not name or name in existing_names:
                    continue
                try:
                    field.add_concept(
                        name, domain=domain, granularity=1,
                        source="homeostasis_bootstrap", ensure_knowledge=True,
                    )
                    for rel in concept_data.get("relations", []):
                        target = rel.get("target", "")
                        if target:
                            field.add_relation(
                                name, rel.get("type", "påverkar"), target,
                                why=rel.get("why", "homeostasis bootstrap"),
                                strength=0.5,
                                source_tag="homeostasis_bootstrap",
                                evidence_score=0.5,
                                assumption_flag=True,
                                domain_src=domain,
                                domain_tgt="unknown",
                            )
                    llm_generated += 1
                except Exception:
                    pass
        except (json.JSONDecodeError, Exception) as e:
            log.debug("Homeostasis LLM-seed misslyckades (%s): %s", seed_key, e)

    return {
        "region": atlas_region,
        "seed_key": seed_key,
        "domain": domain,
        "predefined_added": added,
        "llm_generated": llm_generated,
    }


async def run_homeostasis_check(
    field: Any,
    cycle: int,
    *,
    model: str = HOMEOSTASIS_MODEL,
) -> dict[str, Any]:
    """
    Check brain region balance and auto-seed underrepresented regions.
    Call every N cycles (e.g., every 6th ≈ every hour at 600s interval).

    Returns dict with actions taken per region.
    """
    from nouse.daemon.brain_atlas import region_report

    try:
        stats = region_report(field)
    except Exception as e:
        log.warning("Homeostasis region_report misslyckades: %s", e)
        return {}

    total = sum(s.concept_count for s in stats.values())
    if total == 0:
        return {}

    results: dict[str, Any] = {}
    for atlas_region, s in stats.items():
        pct = s.concept_count / total

        if pct < HOMEOSTASIS_LOW_PCT:
            seed_key = ATLAS_TO_SEED.get(atlas_region)
            if seed_key is None:
                log.debug("Homeostas: ingen seed-definition för %s, hoppar", atlas_region)
                continue
            log.info(
                "Homeostas: %s underrepresenterad (%.1f%%) → seedar '%s'",
                s.name, pct * 100, seed_key,
            )
            try:
                result = await _seed_region_async(
                    field, atlas_region, seed_key, model=model
                )
                results[atlas_region] = {"action": "seeded", **result}
                log.info(
                    "Homeostas: %s seedat — predefined=%d llm=%d",
                    s.name,
                    result.get("predefined_added", 0),
                    result.get("llm_generated", 0),
                )
            except Exception as e:
                log.warning("Homeostas seed misslyckades för %s: %s", atlas_region, e)

        elif pct > HOMEOSTASIS_HIGH_PCT:
            log.warning(
                "Homeostas: %s överrepresenterad (%.1f%%) ⚠",
                s.name, pct * 100,
            )
            results[atlas_region] = {"action": "overrepresented", "pct": round(pct, 4)}

    return results
