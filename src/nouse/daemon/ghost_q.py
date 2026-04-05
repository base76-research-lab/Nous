"""
nouse.daemon.ghost_q — Autonomous Knowledge Crawling
=====================================================

Ghost Q = graf-crawler + modell-crawler.

Varje NightRun-cykel (fas 10):
  1. Hitta svaga noder (ev < 0.5, strength ≈ 1.0)  → N known topics
  2. Hitta dangling edges (X→Y där Y ej är nod)     → +1 new topic
  3. Fråga LLM om varje topic → extrahera relationer → lagra i graf
  4. Spara historik → hoppa topics som körts nyligen

Effekt:
  - Grafen fördjupas (svaga noder → starka)
  - Grafen expanderar (dangling edges → nya noder)
  - Knowledge distillation utan gradient descent
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("nouse.ghost_q")

HISTORY_FILE = Path.home() / ".local" / "share" / "nouse" / "ghost_q_history.json"

# ── Config ────────────────────────────────────────────────────────────────────

GHOST_Q_MAX_QUERIES     = int(10)   # per NightRun-session
GHOST_Q_WEAK_THRESHOLD  = 0.5       # ev under detta = svag nod
GHOST_Q_MIN_STRENGTH    = 1.0       # strength-filter för svaga noder
GHOST_Q_COOLDOWN_DAYS   = 2         # hoppa topic om kördes för < X dagar sedan
GHOST_Q_SATURATED_LIMIT = 2         # topic arkiveras om < X nya relationer

GHOST_Q_SYSTEM = """Du är en kunskapsdestillator. Din uppgift är att förklara koncept
och deras relationer på ett strukturerat sätt. Svara alltid med konkreta påståenden
i formatet: "X är Y", "X relaterar till Y", "X används för Z".
Var specifik. Undvik allmänna fraser. Max 200 ord."""


# ── Dataklasser ───────────────────────────────────────────────────────────────

@dataclass
class GhostQEntry:
    last_run: str = ""          # ISO datum
    runs: int = 0
    total_relations_added: int = 0
    saturated: bool = False     # arkiverad = hoppa alltid


@dataclass
class GhostQResult:
    queries_run: int = 0
    relations_added: int = 0
    new_topics: int = 0         # dangling edges som fylldes
    deepened_topics: int = 0    # svaga noder som förstärktes
    skipped: int = 0            # topics som hoppades pga cooldown
    duration: float = 0.0
    errors: list[str] = field(default_factory=list)


# ── Historik ──────────────────────────────────────────────────────────────────

def _load_history() -> dict[str, GhostQEntry]:
    if not HISTORY_FILE.exists():
        return {}
    try:
        raw = json.loads(HISTORY_FILE.read_text())
        return {k: GhostQEntry(**v) for k, v in raw.items()}
    except Exception:
        return {}


def _save_history(history: dict[str, GhostQEntry]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps({k: asdict(v) for k, v in history.items()}, indent=2)
    )


def _should_skip(entry: GhostQEntry) -> bool:
    if entry.saturated:
        return True
    if not entry.last_run:
        return False
    try:
        last = datetime.fromisoformat(entry.last_run).replace(tzinfo=timezone.utc)
        days_ago = (datetime.now(timezone.utc) - last).days
        return days_ago < GHOST_Q_COOLDOWN_DAYS
    except Exception:
        return False


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ── Graf-analys ───────────────────────────────────────────────────────────────

def find_weak_nodes(field, limit: int = 9) -> list[str]:
    """
    Hitta noder med låg evidens — kandidater för Ghost Q fördjupning.
    Returnerar lista med koncept-namn.
    """
    try:
        rows = field.find_weak_concepts(
            threshold=GHOST_Q_WEAK_THRESHOLD / 0.25 + 1.0,
            max_rels=3,
            limit=limit,
        )
        return [str(r["name"]) for r in rows if r.get("name")]
    except Exception as e:
        _log.debug("find_weak_nodes fallback: %s", e)
        try:
            rows = field.find_weak_concepts(threshold=1.2, limit=limit)
            return [str(r["name"]) for r in rows if r.get("name")]
        except Exception:
            return []


def find_dangling_edges(field, limit: int = 1) -> list[str]:
    """
    Hitta mål-koncept i relationer som INTE finns som egna noder.
    Dessa är kunskapsfrontieren — Nouse vet att X→Y men inget om Y.
    """
    try:
        all_concepts = {str(c.get("name") or "") for c in field.concepts() if c.get("name")}
        dangling_rows = field.find_dangling_targets(limit=5000)
        dangling = []
        seen = set()
        for row in dangling_rows:
            tgt = str(row.get("tgt") or "")
            if tgt and tgt not in all_concepts and tgt not in seen:
                dangling.append(tgt)
                seen.add(tgt)
            if len(dangling) >= limit:
                break
        return dangling
    except Exception as e:
        _log.debug("find_dangling_edges failed: %s", e)
        return []


# ── LLM-fråga ─────────────────────────────────────────────────────────────────

async def _ask_llm(topic: str, model_router) -> str:
    """Fråga LLM om ett topic. Returnerar svar-text."""
    query = (
        f"Förklara konceptet '{topic}' och beskriv dess viktigaste relationer "
        f"och kopplingar till andra koncept. Var specifik och konkret."
    )
    try:
        response = await model_router.complete(
            query,
            system=GHOST_Q_SYSTEM,
            max_tokens=400,
        )
        return response or ""
    except Exception as e:
        _log.warning("LLM call failed for topic '%s': %s", topic, e)
        return ""


# ── Huvud-funktion ────────────────────────────────────────────────────────────

async def run_ghost_q(
    field,
    model_router,
    *,
    max_queries: int = GHOST_Q_MAX_QUERIES,
) -> GhostQResult:
    """
    Kör Ghost Q — anropas från NightRun fas 10.

    field:        FieldSurface
    model_router: nouse.llm.model_router (har .complete())
    """
    from nouse.daemon.extractor import extract_relations

    t0 = time.monotonic()
    result = GhostQResult()
    history = _load_history()

    # 1. Hitta topics
    weak     = find_weak_nodes(field, limit=max_queries - 1)
    dangling = find_dangling_edges(field, limit=1)
    all_topics = weak + dangling

    if not all_topics:
        _log.info("Ghost Q: inga topics hittades")
        result.duration = time.monotonic() - t0
        return result

    _log.info("Ghost Q: %d topics (%d weak + %d dangling)",
              len(all_topics), len(weak), len(dangling))

    # 2. Kör Ghost Q per topic
    for topic in all_topics[:max_queries]:
        entry = history.get(topic, GhostQEntry())

        if _should_skip(entry):
            _log.debug("Ghost Q: skippar '%s' (cooldown/saturated)", topic)
            result.skipped += 1
            continue

        # Fråga LLM
        answer = await _ask_llm(topic, model_router)
        if not answer:
            result.errors.append(f"no_answer:{topic}")
            continue

        # Extrahera och lagra relationer
        before_stats = field.stats()
        try:
            await extract_relations(
                f"Koncept: {topic}\n\n{answer}",
                field,
                source_tag="ghost_q",
            )
        except Exception as e:
            _log.warning("extract_relations failed for '%s': %s", topic, e)
            result.errors.append(f"extract_error:{topic}")
            continue

        after_stats = field.stats()
        new_rels = (after_stats.get("relations", 0) -
                    before_stats.get("relations", 0))

        # Uppdatera historik
        entry.last_run = _today()
        entry.runs += 1
        entry.total_relations_added += new_rels
        if new_rels < GHOST_Q_SATURATED_LIMIT and entry.runs >= 3:
            entry.saturated = True
            _log.info("Ghost Q: '%s' mättad (arkiveras)", topic)
        history[topic] = entry

        result.queries_run += 1
        result.relations_added += new_rels

        if topic in dangling:
            result.new_topics += 1
        else:
            result.deepened_topics += 1

        _log.info(
            "Ghost Q: '%s' → +%d relationer (total=%d)",
            topic, new_rels, entry.total_relations_added
        )

        # Kort paus mellan LLM-anrop
        await asyncio.sleep(0.5)

    _save_history(history)
    result.duration = time.monotonic() - t0

    _log.info(
        "Ghost Q klar: %d queries, +%d relationer, %.1fs",
        result.queries_run, result.relations_added, result.duration
    )
    return result
