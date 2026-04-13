"""
NightRun — Konsolidering (Slow-Wave Sleep)
==========================================

Bearbetar NodeInbox → konsoliderar till FieldSurface.

Analogt med hippocampal replay under sömn:
  1. Replay: läs alla okonsoliderade inbox-poster
  2. Evaluera: är evidensen tillräcklig?
  3. Konsolidera: starka noder → permanent i FieldSurface
  4. Kasta: svaga noder → kasseras (eller behåller assumption_flag)
  5. Bisociation: leta korsdomän-kopplingar i nya noder
  6. Pruning: rensa svaga gamla kanter

Schema (konfigureras av användaren):
  "idle:N"  → kör om ingen aktivitet på N minuter
  "night"   → kör 22:00–06:00
  "always"  → kör kontinuerligt (kräver stor hårdvara)
  "never"   → manuellt via: b76 nightrun now

Konfigurationsfil: ~/.local/share/nouse/nightrun_config.json
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from nouse.config.paths import path_from_env

_log = logging.getLogger("nouse.nightrun")

CONFIG_FILE  = path_from_env("NOUSE_NIGHTRUN_CONFIG_FILE", "nightrun_config.json")
STATUS_FILE  = path_from_env("NOUSE_NIGHTRUN_STATUS_FILE", "nightrun_status.json")

# Konsoliderings-trösklar
CONSOLIDATION_MIN_EVIDENCE  = float(os.getenv("NOUSE_NIGHTRUN_MIN_EVIDENCE",  "0.45"))
CONSOLIDATION_MIN_SUPPORT   = int(os.getenv("NOUSE_NIGHTRUN_MIN_SUPPORT",     "1"))
STRONG_CONSOLIDATION        = float(os.getenv("NOUSE_NIGHTRUN_STRONG_EVIDENCE","0.65"))
# Grace period: nya koncept (< GRACE_HOURS gamla) konsolideras vid lägre tröskel
GRACE_HOURS                 = int(os.getenv("NOUSE_NIGHTRUN_GRACE_HOURS",     "48"))
GRACE_MIN_EVIDENCE          = float(os.getenv("NOUSE_NIGHTRUN_GRACE_EVIDENCE", "0.15"))

NightRunMode = Literal["idle", "night", "always", "never"]


# ── Konfiguration ─────────────────────────────────────────────────────────────

@dataclass
class NightRunConfig:
    mode:          NightRunMode = "idle"
    idle_minutes:  int   = 30       # för mode="idle"
    night_start:   int   = 22       # timme 0–23
    night_end:     int   = 6        # timme 0–23
    max_runtime_minutes: int = 60   # maximal körtid per session

    def save(self) -> None:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls) -> "NightRunConfig":
        if CONFIG_FILE.exists():
            try:
                return cls(**json.loads(CONFIG_FILE.read_text()))
            except Exception:
                pass
        return cls()

    def should_run_now(self, last_activity_ts: float) -> bool:
        now = datetime.now(timezone.utc)
        if self.mode == "never":
            return False
        if self.mode == "always":
            return True
        if self.mode == "idle":
            idle_sec = time.time() - last_activity_ts
            return idle_sec >= self.idle_minutes * 60
        if self.mode == "night":
            h = now.hour
            if self.night_start > self.night_end:
                return h >= self.night_start or h < self.night_end
            return self.night_start <= h < self.night_end
        return False


@dataclass
class NightRunStatus:
    last_run_ts:        float = 0.0
    last_run_duration:  float = 0.0
    total_consolidated: int   = 0
    total_discarded:    int   = 0
    total_bisociations: int   = 0
    total_pruned:       int   = 0
    last_error:         str   = ""

    def save(self) -> None:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls) -> "NightRunStatus":
        if STATUS_FILE.exists():
            try:
                return cls(**json.loads(STATUS_FILE.read_text()))
            except Exception:
                pass
        return cls()


# ── Konsolideringslogik ───────────────────────────────────────────────────────

@dataclass
class ConsolidationResult:
    consolidated:    int = 0
    discarded:       int = 0
    bisociations:    int = 0
    pruned:          int = 0
    enriched:        int = 0    # noder berikat med kontext
    axioms_committed: int = 0   # axiom från deepdive som skrevs direkt
    axioms_flagged:  int = 0    # axiom flaggade för vidare granskning
    reviews_promoted: int = 0   # flaggade axiom som befordrades via deep review
    reviews_discarded: int = 0  # flaggade axiom som kasserades via deep review
    ghost_q_queries: int = 0    # Ghost Q: antal LLM-anrop
    ghost_q_relations: int = 0  # Ghost Q: antal nya relationer
    ghost_q_new_topics: int = 0 # Ghost Q: dangling edges som fylldes
    contradiction_caught: int = 0   # contradiction events caught since last cycle
    contradiction_severity_mean: float = 0.0
    contradiction_acted_on: int = 0
    crystallization_rate: float = 0.0   # % av kanter med w > 0.55
    evidence_quality: float = 0.0       # medel-ev på kristalliserade kanter
    evidence_promoted: int = 0         # kanter promovisade i evidens
    evidence_demoted: int = 0          # kanter demoverade i evidens
    goals_active: int = 0              # D6: aktiva mål efter goal cycle
    goals_satisfied: int = 0           # D6: mål som uppnåtts denna cykel
    goals_new: int = 0                 # D6: nya mål genererade denna cykel
    duration:        float = 0.0


async def run_night_consolidation(
    field,         # FieldSurface
    inbox,         # NodeInbox
    limbic,        # LimbicState
    *,
    max_minutes: int = 60,
    dry_run: bool = False,
) -> ConsolidationResult:
    """
    Huvudfunktion för NightRun-konsolidering.

    1. Hämta okonsoliderade inbox-poster
    2. Evaluera evidens per relation
    3. Konsolidera starka → mark as consolidated
    4. Kasta svaga (lämnar dem unconsolidated = glöms)
    5. Bisociation-pass på nya noder
    6. Pruning av svaga gamla kanter
    """
    from nouse.orchestrator.compaction import should_run, run_compaction
    from nouse.learning_coordinator import LearningCoordinator
    from nouse.daemon.storage_tier import get_tier

    tier_limits = get_tier().limits()
    min_evidence = tier_limits.nightrun_min_evidence   # respekterar small/medium/large

    t0 = time.monotonic()
    deadline = t0 + max_minutes * 60
    result = ConsolidationResult()

    coordinator = LearningCoordinator(field, limbic)
    entries = inbox.read_window()

    if not entries:
        _log.info("NightRun: inbox tom — inget att konsolidera")
        return result

    _log.info("NightRun: %d okonsoliderade poster att bearbeta", len(entries))

    consolidated_ids: set[str] = set()

    # ── Steg 0: Konsolidera modelsessions (Hebbian replay & co-occurrence) ────
    try:
        from nouse.memory import modelsessions
        sessions = modelsessions.iter_sessions(limit=1000)
        # Hebbian strengthening: stärk paths för återkommande queries
        query_counts = {}
        for s in sessions:
            q = s.get("query")
            if not q:
                continue
            query_counts[q] = query_counts.get(q, 0) + 1
        for q, count in query_counts.items():
            if count > 1:
                # Stärk alla edges som matchar queryn
                nodes = field.node_context_for_query(q, limit=6)
                for node in nodes:
                    name = node.get("name", "")
                    if not name:
                        continue
                    rels = field.out_relations(name)
                    for rel in rels:
                        tgt = rel.get("target")
                        typ = rel.get("type")
                        if tgt and typ:
                            field.strengthen(name, tgt, delta=0.05 * (count-1))
        # Bygg co_occurs_with-relationer mellan topics som ofta förekommer ihop
        for s in sessions:
            nodes_used = s.get("nodes_used") or []
            for i, a in enumerate(nodes_used):
                for b in nodes_used[i+1:]:
                    if a != b:
                        field.add_relation(a, "co_occurs_with", b, why="modelsessions", strength=0.5)
        _log.info("NightRun: modelsessions replay och co-occurrence klar")
    except Exception as e:
        _log.warning("NightRun: modelsessions replay/co-occurrence misslyckades: %s", e)

    # ── Steg 1+2+3: Evaluera och konsolidera ──────────────────────────────────
    now_ts = time.time()
    grace_cutoff = now_ts - (GRACE_HOURS * 3600)

    for entry in entries:
        if time.monotonic() > deadline:
            _log.warning("NightRun: tidsgräns nådd (%d min)", max_minutes)
            break

        ev = entry.evidence_score

        # Grace period: nya poster (< GRACE_HOURS gamla) får lägre tröskel
        try:
            entry_ts = datetime.fromisoformat(entry.ts).timestamp()
            is_recent = entry_ts > grace_cutoff
        except (ValueError, OSError):
            is_recent = True  # vid parse-fel — var generös

        effective_threshold = GRACE_MIN_EVIDENCE if is_recent else min_evidence

        if ev >= effective_threshold:
            # Stärk kanten i grafen — med evidens-skalat delta
            if not dry_run:
                coordinator.on_fact(
                    entry.src, entry.rel_type, entry.tgt,
                    why=entry.why,
                    evidence_score=ev,
                    support_count=CONSOLIDATION_MIN_SUPPORT,
                )
            consolidated_ids.add(entry.id)
            result.consolidated += 1
            _log.debug(
                "Konsoliderar: %s─[%s]→%s  ev=%.2f%s",
                entry.src, entry.rel_type, entry.tgt, ev,
                " (grace)" if is_recent and ev < min_evidence else ""
            )
        else:
            # Svag evidens — lämna unconsolidated, den försvinner vid prune_old()
            result.discarded += 1
            _log.debug(
                "Kasserar (ev=%.2f < %.2f): %s→%s",
                ev, effective_threshold, entry.src, entry.tgt
            )

        await asyncio.sleep(0)  # yield till event loop

    # ── Steg 4: Markera konsoliderade ────────────────────────────────────────
    if not dry_run and consolidated_ids:
        inbox.mark_consolidated(consolidated_ids)

    # ── Steg 5: Bisociation-pass på nya noder ─────────────────────────────────
    new_nodes = {e.src for e in entries} | {e.tgt for e in entries}
    new_domains = {e.domain_src for e in entries} | {e.domain_tgt for e in entries}
    new_domains.discard("okänd")  # okänd domän ger inga meningsfulla bisociationer

    if not dry_run and new_domains:
        # Hämta befintliga domäner och jämför nya mot dem — inte bara nya sinsemellan
        try:
            existing_domains = set(field.domains()) - new_domains
            existing_domains.discard(None)
        except Exception:
            existing_domains = set()

        # Kombinera: nya mot nya + nya mot befintliga (max 10 befintliga för perf)
        compare_domains = list(existing_domains)[:10]
        all_domains = list(new_domains) + compare_domains

        for i, da in enumerate(list(new_domains)):
            for db in all_domains:
                if da == db:
                    continue
                if time.monotonic() > deadline:
                    break
                try:
                    path = field.find_path(da, db, max_hops=5)
                    if path:
                        result.bisociations += 1
                        _log.info(
                            "NightRun bisociation: %s ↔ %s (%d hopp)",
                            da, db, len(path)
                        )
                except Exception:
                    pass
                await asyncio.sleep(0)

    # ── Steg 6: Pruning ───────────────────────────────────────────────────────
    if not dry_run and should_run(0):
        try:
            pruned = run_compaction(field)
            result.pruned = pruned
        except Exception as e:
            _log.warning("NightRun pruning misslyckades: %s", e)

    # ── Steg 7: Nod-kontext-berikning (medium/large tier) ─────────────────────
    if not dry_run and time.monotonic() < deadline:
        try:
            from nouse.daemon.node_context import enrich_nodes
            remaining_min = (deadline - time.monotonic()) / 60
            enrich_result = await enrich_nodes(
                field,
                max_nodes=100,
                max_minutes=min(remaining_min, 15.0),
            )
            result.enriched = enrich_result.enriched
        except Exception as e:
            _log.warning("NightRun nod-berikning misslyckades: %s", e)

    # ── Steg 8: Indikerade granskning — ReviewQueue flush ─────────────────────
    # Flaggade axiom som nått REVIEW_INDICATION_THRESHOLD granskas djupare.
    # Utfall: PROMOTE (stärks), KEEP (stannar flaggad), DISCARD (kasseras).
    if not dry_run and time.monotonic() < deadline:
        try:
            from nouse.daemon.node_deepdive import get_review_queue, REVIEW_PROMOTE, REVIEW_DISCARD
            rq = get_review_queue()
            pending = rq.pending_count()
            if pending:
                _log.info("NightRun [8/9] ReviewQueue: %d väntande granskningar", pending)
                remaining_min = (deadline - time.monotonic()) / 60
                max_reviews = max(1, min(pending, int(remaining_min / 2)))
                verdicts = await rq.flush_pending(
                    field,
                    max_reviews=max_reviews,
                    dry_run=dry_run,
                )
                for v in verdicts:
                    if v.outcome == REVIEW_PROMOTE:
                        result.reviews_promoted += 1
                    elif v.outcome == REVIEW_DISCARD:
                        result.reviews_discarded += 1
                _log.info(
                    "NightRun [8/9] ReviewQueue klar: promoted=%d discarded=%d kept=%d",
                    result.reviews_promoted,
                    result.reviews_discarded,
                    len(verdicts) - result.reviews_promoted - result.reviews_discarded,
                )
        except Exception as e:
            _log.warning("NightRun ReviewQueue flush misslyckades: %s", e)

    # ── Steg 9: DeepDive — axiom-discovery på top-N noder ─────────────────────
    # Körs på noder med hög gradtal men svag faktabas.
    # Starka axiom skrivs direkt; svaga hamnar i ReviewQueue för steg 8 nästa cykel.
    if not dry_run and time.monotonic() < deadline:
        try:
            from nouse.daemon.node_deepdive import deepdive_batch
            remaining_min = (deadline - time.monotonic()) / 60
            if remaining_min >= 2.0:
                _log.info("NightRun [9/10] DeepDive: %.1f min kvar", remaining_min)
                batch = await deepdive_batch(
                    field,
                    max_nodes=10,
                    max_minutes=min(remaining_min * 0.8, 20.0),
                    dry_run=dry_run,
                )
                result.axioms_committed = batch.total_committed
                result.axioms_flagged   = batch.total_flagged
                _log.info(
                    "NightRun [9/10] DeepDive klar: noder=%d committed=%d flagged=%d",
                    batch.nodes_processed, batch.total_committed, batch.total_flagged,
                )
        except Exception as e:
            _log.warning("NightRun DeepDive misslyckades: %s", e)

    # ── Steg 10: Ghost Q — graf-crawling + modell-crawling ────────────────────
    # Fördjupar svaga noder och expanderar grafen längs dangling edges.
    # Kör sist i cykeln — efter konsolidering, review och deepdive.
    if not dry_run and time.monotonic() < deadline:
        try:
            from nouse.daemon.ghost_q import run_ghost_q
            from nouse.llm.model_router import ModelRouter
            remaining_min = (deadline - time.monotonic()) / 60
            if remaining_min >= 5.0:
                _log.info("NightRun [10/10] Ghost Q: %.1f min kvar", remaining_min)
                router = ModelRouter(field)
                ghost_result = await run_ghost_q(
                    field, router,
                    max_queries=min(10, int(remaining_min / 2)),
                )
                _log.info(
                    "NightRun [10/10] Ghost Q klar: queries=%d +rels=%d "
                    "new_topics=%d deepened=%d skipped=%d (%.1fs)",
                    ghost_result.queries_run,
                    ghost_result.relations_added,
                    ghost_result.new_topics,
                    ghost_result.deepened_topics,
                    ghost_result.skipped,
                    ghost_result.duration,
                )
        except Exception as e:
            _log.warning("NightRun Ghost Q misslyckades: %s", e)

    # ── Steg 11 — Rekursiv Epistemisk Nedbrytning (mycel-axiom) ──────────────
    # Bearbeta inkubationskön (F_bisoc^τ) + kör en nedbrytningsburst
    # om det finns tid och rätt arousal.
    try:
        from nouse.daemon.decomposition import (
            process_incubation_queue,
            promote_axioms_to_graph,
            run_decomposition_burst,
        )
        from nouse.limbic.signals import load_state as _load_limbic

        limbic_state = _load_limbic()

        # Bearbeta inkubationskön
        matured_axioms = process_incubation_queue(field, limbic_state.cycle)
        if matured_axioms:
            n_matured = promote_axioms_to_graph(field, matured_axioms)
            _log.info("NightRun [11a] Inkubation: %d axiom mognat → %d kanter", len(matured_axioms), n_matured)
            result.axioms_committed += n_matured

        # Kör nedbrytningsburst om det finns tid kvar
        remaining_min = (max_minutes * 60 - (time.monotonic() - t0)) / 60
        if remaining_min > 3:
            n_new = await run_decomposition_burst(field, limbic_state)
            if n_new > 0:
                _log.info("NightRun [11b] Decomposition: %d nya axiom-kanter", n_new)
                result.axioms_committed += n_new
    except Exception as e:
        _log.warning("NightRun Decomposition misslyckades: %s", e)

    # ── Steg 12: Contradiction metrics (since last cycle) ────────────────────
    try:
        from nouse.daemon.journal import count_contradiction_events
        prev_status = NightRunStatus.load()
        since_ts = (
            datetime.fromtimestamp(prev_status.last_run_ts, tz=timezone.utc).isoformat()
            if prev_status.last_run_ts > 0
            else ""
        )
        cc = count_contradiction_events(since_ts) if since_ts else {"caught": 0, "severity_mean": 0.0, "acted_on": 0}
        result.contradiction_caught = cc["caught"]
        result.contradiction_severity_mean = cc["severity_mean"]
        result.contradiction_acted_on = cc["acted_on"]
    except Exception as e:
        _log.warning("NightRun contradiction count misslyckades: %s", e)

    # ── Steg 13: Evidence pass + crystallization metrics ──────────────────────
    try:
        from nouse.daemon.evidence import run_evidence_pass, measure_crystallization
        ev_result = run_evidence_pass(field, max_items=500)
        result.evidence_promoted = ev_result.promoted
        result.evidence_demoted = ev_result.demoted
        cryst = measure_crystallization(field)
        result.crystallization_rate = cryst.crystallization_rate
        result.evidence_quality = cryst.evidence_quality
        _log.info(
            "NightRun [13] Evidence pass: promoted=%d demoted=%d "
            "crystallization=%.1f%% ev_quality=%.3f tiers=%s",
            ev_result.promoted, ev_result.demoted,
            cryst.crystallization_rate * 100, cryst.evidence_quality,
            cryst.tier_counts,
        )
    except Exception as e:
        _log.warning("NightRun evidence pass misslyckades: %s", e)

    # ── Steg 14: Goal cycle (Intrinsic Drive Engine) ────────────────────────────
    try:
        from nouse.daemon.goal_registry import (
            active_goals, expire_stale_goals, evaluate_satisfaction,
            satisfy_goals, goal_metrics, rewrite_goals,
        )
        from nouse.daemon.goal_generator import generate_goals

        cycle_num = result.cycle if hasattr(result, 'cycle') else 0
        # Använd brain.stats() för att få cycle
        try:
            cycle_num = field.cycle if hasattr(field, 'cycle') else 0
        except Exception:
            pass

        # 14a: Expire stale goals
        expired = expire_stale_goals(cycle_num)
        _log.info("NightRun [14a] Expired %d stale goals", expired)

        # 14b: Evaluate satisfaction of active goals
        eval_entries = None
        try:
            from nouse.daemon.eval_log import read_eval_entries
            eval_entries = read_eval_entries(limit=5)
        except Exception:
            pass

        goals_before = active_goals()
        satisfied_ids: list[str] = []
        for goal in goals_before:
            new_status = evaluate_satisfaction(goal, field, cycle_num, eval_entries=eval_entries)
            if new_status == "satisfied":
                satisfied_ids.append(goal.id)
                _log.info("NightRun [14b] Goal %s SATISFIED: %s", goal.id, goal.title[:60])
            elif new_status == "expired":
                # Redan hanterat av expire_stale_goals
                pass

        if satisfied_ids:
            n_satisfied = satisfy_goals(satisfied_ids, cycle=cycle_num)
            result.goals_satisfied = n_satisfied
            _log.info("NightRun [14b] Satisfied %d goals", n_satisfied)

        # 14c: Generate new goals from graph topology
        new_goals = generate_goals(
            field, cycle_num,
            eval_entries=eval_entries,
            max_total=10,
        )
        result.goals_new = len(new_goals)
        _log.info("NightRun [14c] Generated %d new goals", len(new_goals))

        # 14d: Apply goal weights to graph nodes
        all_active = active_goals()
        result.goals_active = len(all_active)
        if hasattr(field, 'apply_goal_weights'):
            updated = field.apply_goal_weights(all_active)
            _log.info("NightRun [14d] Updated %d node goal_weights", updated)

        # 14e: Log goal metrics to eval_log
        try:
            gm = goal_metrics()
            _log.info(
                "NightRun [14e] Goal metrics: active=%d satisfied=%d rate=%.2f progress_mean=%.2f",
                gm["goals_active"], gm["goals_satisfied_total"],
                gm["goal_satisfaction_rate"], gm["goal_progress_mean"],
            )
        except Exception:
            pass

    except Exception as e:
        _log.warning("NightRun goal cycle misslyckades (non-fatal): %s", e)

    result.duration = round(time.monotonic() - t0, 2)
    _log.info(
        "NightRun klar: konsoliderat=%d kasserat=%d bisociationer=%d pruning=%d "
        "berikat=%d axiom_committed=%d axiom_flagged=%d "
        "reviews_promoted=%d reviews_discarded=%d "
        "ghost_q=%d +rels=%d new_topics=%d "
        "contradictions=%d(acted=%d,sev=%.2f) "
        "crystallization=%.1f%% ev_quality=%.3f ev_promoted=%d ev_demoted=%d "
        "goals_active=%d goals_new=%d goals_satisfied=%d (%.1fs)",
        result.consolidated, result.discarded,
        result.bisociations, result.pruned, result.enriched,
        result.axioms_committed, result.axioms_flagged,
        result.reviews_promoted, result.reviews_discarded,
        result.ghost_q_queries, result.ghost_q_relations, result.ghost_q_new_topics,
        result.contradiction_caught, result.contradiction_acted_on,
        result.contradiction_severity_mean,
        result.crystallization_rate * 100, result.evidence_quality,
        result.evidence_promoted, result.evidence_demoted,
        result.goals_active, result.goals_new, result.goals_satisfied,
        result.duration,
    )
    return result


# ── Schema-vakt (körs i daemon-loop) ─────────────────────────────────────────

class NightRunScheduler:
    """
    Körs som bakgrundsuppgift i brain_loop.
    Kollar om NightRun ska triggas baserat på config.
    """

    def __init__(self):
        self.config = NightRunConfig.load()
        self.status = NightRunStatus.load()
        self._running = False
        self._last_activity = time.time()

    def touch_activity(self) -> None:
        """Anropa vid varje användarinteraktion (chat, ingest etc.)."""
        self._last_activity = time.time()

    def reload_config(self) -> None:
        self.config = NightRunConfig.load()

    @property
    def is_running(self) -> bool:
        return self._running

    async def maybe_run(
        self,
        field,
        inbox,
        limbic,
    ) -> ConsolidationResult | None:
        """
        Anropa regelbundet från brain_loop (t.ex. var 5:e minut).
        Kör NightRun om schemat säger det — annars noop.
        """
        if self._running:
            return None

        # Ladda om config om den ändrats
        self.reload_config()

        if not self.config.should_run_now(self._last_activity):
            return None

        # Minst 30 min sedan senaste körning
        if time.time() - self.status.last_run_ts < 1800:
            return None

        self._running = True
        _log.info(
            "NightRun startar (mode=%s, idle=%.0fmin)",
            self.config.mode,
            (time.time() - self._last_activity) / 60,
        )

        try:
            result = await run_night_consolidation(
                field, inbox, limbic,
                max_minutes=self.config.max_runtime_minutes,
            )
            self.status.last_run_ts        = time.time()
            self.status.last_run_duration  = result.duration
            self.status.total_consolidated += result.consolidated
            self.status.total_discarded    += result.discarded
            self.status.total_bisociations += result.bisociations
            self.status.total_pruned       += result.pruned
            self.status.last_error         = ""
            self.status.save()

            # ── Evalving: logga eval-entry + trendanalys ─────────────────────
            try:
                from nouse.daemon.eval_log import (
                    write_eval_entry, read_eval_entries, generate_policy_suggestion,
                    feedback_summary,
                )
                stats = field.stats() if hasattr(field, "stats") else {}
                cc_rate = (
                    result.contradiction_caught / max(1, result.contradiction_caught + result.contradiction_acted_on)
                    if (result.contradiction_caught + result.contradiction_acted_on) > 0
                    else 0.0
                )
                # Hämta goal metrics för eval_log
                gm = {}
                try:
                    from nouse.daemon.goal_registry import goal_metrics as _gm
                    gm = _gm()
                except Exception:
                    pass
                write_eval_entry(
                    cycle=int(self.status.total_consolidated),
                    crystallization_rate=result.crystallization_rate,
                    evidence_quality=result.evidence_quality,
                    gap_map_shrink_rate=0.0,
                    contradiction_catch_rate=cc_rate,
                    contradiction_caught=result.contradiction_caught,
                    contradiction_acted_on=result.contradiction_acted_on,
                    graph_concepts=stats.get("concepts", 0),
                    graph_relations=stats.get("relations", 0),
                    goals_active=result.goals_active,
                    goals_satisfied_total=gm.get("goals_satisfied_total", 0),
                    goal_satisfaction_rate=gm.get("goal_satisfaction_rate", 0.0),
                    goal_progress_mean=gm.get("goal_progress_mean", 0.0),
                    extra={
                        "consolidated": result.consolidated,
                        "discarded": result.discarded,
                        "bisociations": result.bisociations,
                        "duration": result.duration,
                        "evidence_promoted": result.evidence_promoted,
                        "evidence_demoted": result.evidence_demoted,
                        "goals_new": result.goals_new,
                        "goals_satisfied": result.goals_satisfied,
                        "feedback": feedback_summary(),
                    },
                )
                # Trendanalys — generera policyförslag om mätvärden sjunker
                entries = read_eval_entries(limit=10)
                if len(entries) >= 4:
                    suggestion = generate_policy_suggestion(entries)
                    if suggestion:
                        _log.info("Evalving policy-förslag: %s", suggestion)
                        # Applicera evalving-förslag via cognitive_policy
                        try:
                            from nouse.daemon.cognitive_policy import evaluate_and_apply
                            # D6: inkludera goal-mätvärden för policy-triggers
                            goals_active_n = result.goals_active
                            goals_sat_total = 0
                            goals_sat_rate = 0.0
                            try:
                                from nouse.daemon.goal_registry import goal_metrics as _gm
                                _gm_data = _gm()
                                goals_active_n = _gm_data.get("goals_active", goals_active_n)
                                goals_sat_total = _gm_data.get("goals_satisfied_total", 0)
                                goals_sat_rate = _gm_data.get("goal_satisfaction_rate", 0.0)
                            except Exception:
                                pass
                            eval_metrics = {
                                "crystallization_rate": result.crystallization_rate,
                                "evidence_quality": result.evidence_quality,
                                "gap_map_shrink_rate": suggestion.get("gap_map_shrink_rate", 0.0),
                                "energy": 0.5,  # default — living_core styr energy-trigger
                                "goals_active": float(goals_active_n),
                                "goal_satisfaction_rate": float(goals_sat_rate),
                            }
                            # Mappa förslagsnycklar till metrics
                            if "reason_crystallization" in suggestion:
                                eval_metrics["crystallization_rate"] = -1.0  # tvinga trigger
                            if "reason_evidence" in suggestion:
                                eval_metrics["evidence_quality"] = -1.0
                            if "reason_gap" in suggestion:
                                eval_metrics["gap_map_shrink_rate"] = -1.0
                            policy, audit = evaluate_and_apply(
                                eval_metrics, source="evalving",
                            )
                            if audit:
                                _log.info("Evalving policy applicerad: %s", audit)
                        except Exception as ep:
                            _log.warning("Evalving policy applicering misslyckades: %s", ep)
            except Exception as e:
                _log.warning("Evalving loggning misslyckades: %s", e)

            return result
        except Exception as e:
            self.status.last_error = str(e)
            self.status.save()
            _log.error("NightRun fel: %s", e)
            return None
        finally:
            self._running = False
