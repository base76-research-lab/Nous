"""
b76.daemon.initiative — Den autonoma nyfikenhetsloopen (Curiosity Loop)
========================================================================
När arousal/acetylkolin är optimalt och systemet hittar fragmenterad
kunskap (H0 > 1) triggas ett autonomt informationssökande. Systemet använder
MCP-verktyg för web, lokala filer och URL-hämtning för att fylla gap i grafen.

Returnerar en text (en "själv-skriven rapport") som main-loopen sedan
extraherar relationer ifrån.
"""
from __future__ import annotations

import json
import logging
import asyncio
import os
import threading
from typing import Any

from nouse.field.surface import FieldSurface
from nouse.limbic.signals import LimbicState
from nouse.llm.model_router import order_models_for_workload, record_model_result
from nouse.llm.policy import resolve_model_candidates
from nouse.ollama_client.client import AsyncOllama
from nouse.mcp_gateway.gateway import MCP_TOOLS, is_mcp_tool, execute_mcp_tool
from nouse.tda.bridge import identify_knowledge_gaps

log = logging.getLogger("nouse.curiosity")

CHAT_MODEL = os.getenv("NOUSE_OLLAMA_MODEL", os.getenv("NOUSE_CHAT_MODEL", "qwen3.5:latest")).strip()
CHAT_FALLBACK_MODEL = (os.getenv("NOUSE_CURIOSITY_FALLBACK_MODEL") or "").strip()
GLOBAL_CANDIDATES_RAW = (os.getenv("NOUSE_MODEL_CANDIDATES") or "").strip()
CURIOSITY_CANDIDATES_RAW = (os.getenv("NOUSE_MODEL_CANDIDATES_CURIOSITY") or "").strip()
AUTO_DISCOVER_MODELS = (
    (os.getenv("NOUSE_MODEL_AUTODISCOVER") or "1").strip().lower() in {"1", "true", "yes", "on"}
)
try:
    CURIOSITY_TIMEOUT_SEC = max(
        1.0,
        float((os.getenv("NOUSE_CURIOSITY_TIMEOUT_SEC") or os.getenv("NOUSE_LLM_TIMEOUT_SEC") or "45").strip()),
    )
except ValueError:
    CURIOSITY_TIMEOUT_SEC = 45.0

_AUTO_DISCOVERY_LOCK = threading.Lock()
_AUTO_DISCOVERED_MODELS: list[str] | None = None


def _split_model_list(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def _autodiscovered_models() -> list[str]:
    if not AUTO_DISCOVER_MODELS:
        return []
    global _AUTO_DISCOVERED_MODELS
    if _AUTO_DISCOVERED_MODELS is not None:
        return list(_AUTO_DISCOVERED_MODELS)

    with _AUTO_DISCOVERY_LOCK:
        if _AUTO_DISCOVERED_MODELS is not None:
            return list(_AUTO_DISCOVERED_MODELS)
        models: list[str] = []
        try:
            import ollama  # type: ignore

            host = os.getenv("NOUSE_OLLAMA_HOST") or os.getenv("OLLAMA_HOST")
            client = ollama.Client(host=host) if host else ollama.Client()
            payload = client.list()
            rows = payload.get("models") if isinstance(payload, dict) else getattr(payload, "models", None)
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    name = str(row.get("model") or row.get("name") or "").strip()
                    if name:
                        models.append(name)
        except Exception:
            models = []
        _AUTO_DISCOVERED_MODELS = models
        return list(models)


def _curiosity_model_candidates(task: dict[str, Any] | None) -> list[str]:
    defaults: list[str] = []
    if task:
        custom = task.get("model_candidates")
        if isinstance(custom, list):
            defaults.extend(str(x).strip() for x in custom if str(x).strip())
        elif isinstance(custom, str):
            defaults.extend(_split_model_list(custom))
    defaults.extend(_split_model_list(CURIOSITY_CANDIDATES_RAW))
    defaults.append(CHAT_MODEL)
    if CHAT_FALLBACK_MODEL:
        defaults.append(CHAT_FALLBACK_MODEL)
    defaults.extend(_autodiscovered_models())
    defaults.extend(_split_model_list(GLOBAL_CANDIDATES_RAW))
    return resolve_model_candidates("curiosity", defaults)

def _find_h1_gap_target(
    field: FieldSurface,
    domains: list[str],
) -> tuple[str, list[str], bool]:
    """
    Letar efter H1-kunskapsluckor: konceptpar som är indirekt kopplade
    men saknar direkt relation. Returnerar (domain, concepts, h1_gap_mode).
    h1_gap_mode=True innebär att vi hittade ett H1-par att undersöka.
    """
    best_domain = ""
    best_pair: list[str] = []
    best_score = 0.0

    for d in domains:
        gaps = identify_knowledge_gaps(field, d, max_gaps=1, min_degree=2)
        if gaps:
            a, b, score = gaps[0]
            if score > best_score:
                best_score = score
                best_domain = d
                best_pair = [a, b]

    if best_domain and best_pair:
        return best_domain, best_pair, True

    return "", [], False


async def run_curiosity_burst(
    field: FieldSurface,
    limbic: LimbicState,
    task: dict[str, Any] | None = None,
) -> str | None:
    """
    Kör ett nät-sök för att fylla ett kunskapsgap i grafen.
    Returnerar en rapport-text om sökningen lyckades, eller None.
    Hög arousal/noradrenalin -> mer aggressivt sök.
    """
    # Kräver viss arousal. Om vi fått en explicit queue-task tillåter vi
    # något lägre tröskel för att inte svälta kön.
    min_arousal = 0.2 if task else 0.3
    if limbic.arousal < min_arousal:
        log.info("Curiosity: För låg arousal för autonomt sök.")
        return None

    target_domain: str
    sample_concepts: list[str]

    # D3: Goal-directed curiosity — om aktiva mål finns, prioritera dessa
    goal_context: str = ""
    if not task:
        try:
            from nouse.daemon.goal_registry import active_goals, KIND_CONTRADICTION_RESOLVE, KIND_DOMAIN_EXPAND
            goals = active_goals()
            # Välj högst prioriterade mål som är relevanta för curiosity
            for g in goals[:3]:
                if g.kind in (KIND_CONTRADICTION_RESOLVE, KIND_DOMAIN_EXPAND):
                    if g.target_domain:
                        task = {
                            "domain": g.target_domain,
                            "concepts": g.target_concepts[:4],
                            "rationale": g.title,
                            "query": f"Undersök: {g.title}",
                            "id": g.id,
                        }
                        goal_context = f"\n[Drive-mål] {g.title} (prioritet={g.priority:.2f})"
                        log.info(
                            f"Curiosity goal-directed: mål {g.id} kind={g.kind} "
                            f"domain={g.target_domain} prio={g.priority:.2f}"
                        )
                        break
        except Exception as e:
            log.debug("Goal-directed curiosity lookup misslyckades (non-fatal): %s", e)

    if task:
        target_domain = str(task.get("domain") or "okänd")
        sample_concepts = [str(c) for c in (task.get("concepts") or [])][:4]
        if not sample_concepts:
            sample_concepts = [c["name"] for c in field.concepts(domain=target_domain)[:3]]
        queue_rationale = str(task.get("rationale") or "").strip()
        queue_query = str(task.get("query") or "").strip()
        if not queue_query:
            queue_query = (
                f"Kartlägg sambanden mellan {', '.join(sample_concepts)} "
                f"i domänen '{target_domain}'."
            )
        log.info(
            f"Curiosity queue-task #{task.get('id','?')} låst på {target_domain}. "
            f"Undersöker: {', '.join(sample_concepts)}"
        )
        system_prompt = (
            "Du är B76, en autonom AI-forskningsagent.\n"
            f"Du har fått ett explicit kunskapsgap i domänen '{target_domain}'.\n"
            f"Koncept i fokus: {', '.join(sample_concepts)}.\n"
            f"Gap-rational: {queue_rationale or 'saknas'}.\n"
            f"Forskningsfråga: {queue_query}\n"
            f"{goal_context}\n\n"
            "Använd verktyg (web_search, fetch_url, list_local_mounts, "
            "find_local_files, search_local_text, read_local_file) för att samla evidens. "
            "Skriv sedan en minirapport med:\n"
            "1) verifierbara fakta,\n"
            "2) explicita antaganden,\n"
            "3) föreslagna relationer mellan koncepten."
        )
    else:
        # Fallback: välj fragmenterad domän med högst H0.
        domains = field.domains()
        if not domains:
            return None

        target_domain = ""
        target_h0 = 1
        for d in domains:
            profile = field.domain_tda_profile(d, max_epsilon=2.0)
            if profile["h0"] > target_h0:
                target_h0 = profile["h0"]
                target_domain = d

        if not target_domain:
            # H0=1 överallt — prova H1-gap-detektion istället
            log.info("Curiosity: Inga isolerade graf-öar (H0=1). Söker H1-kunskapsluckor.")
            target_domain, sample_concepts, h1_gap_mode = _find_h1_gap_target(field, domains)
            if not target_domain:
                log.info("Curiosity: Inga kunskapsluckor hittades. Inget att undersöka.")
                return None

            if h1_gap_mode:
                a, b = sample_concepts[0], sample_concepts[1]
                log.info(
                    f"Curiosity H1-gap: {a} ↔ {b} i '{target_domain}' "
                    f"(indirekt kopplade men saknar direkt relation)"
                )
                system_prompt = (
                    "Du är B76, en autonom AI-forskningsagent. "
                    f"Din topologiska analys visar att '{a}' och '{b}' i domänen '{target_domain}' "
                    f"delar gemensamma grannar i kunskapsgrafen men saknar en direkt verifierad relation. "
                    "Detta är ett H1-kunskapshål — ett topologiskt mönster som antyder att en "
                    "relation borde finnas men ännu inte har bevisats. "
                    "Bruk dina verktyg (web_search, fetch_url, find_local_files, search_local_text, "
                    "read_local_file) för att undersöka om det finns en direkt koppling. "
                    "Skriv en minirapport: finns relationen? Vad är evidensen? Vad är osäkerheten?"
                )
            else:
                import random
                random.shuffle(sample_concepts)
                sample_concepts = sample_concepts[:3]
                system_prompt = (
                    "Du är B76, en autonom AI-forskningsagent. "
                    f"Din databas visar att koncepten {', '.join(sample_concepts)} i domänen "
                    f"'{target_domain}' är matematiskt isolerade från varandra (Topologisk H0 > 1). "
                    "Bruk dina verktyg (web_search, fetch_url, list_local_mounts, "
                    "find_local_files, search_local_text, read_local_file) för att lära dig mer och "
                    f"hitta sambanden mellan dem, eller fördjupa förståelsen kring '{target_domain}'. "
                    "Skriv sedan en detaljerad faktatext (en minirapport) om vad du upptäckte. "
                    "Fokusera stenhårt på hur de relaterar och nya fakta som borde minnas."
                )
        else:
            concepts = [c["name"] for c in field.concepts(domain=target_domain)]
            if len(concepts) < 2:
                return None

            import random
            random.shuffle(concepts)
            sample_concepts = concepts[:3]
            log.info(
                f"Curiosity-mål låst på {target_domain} (H0={target_h0}). "
                f"Undersöker: {', '.join(sample_concepts)}"
            )

            system_prompt = (
                "Du är B76, en autonom AI-forskningsagent. "
                f"Din databas visar att koncepten {', '.join(sample_concepts)} i domänen "
                f"'{target_domain}' är matematiskt isolerade från varandra (Topologisk H0 > 1). "
                "Bruk dina verktyg (web_search, fetch_url, list_local_mounts, "
                "find_local_files, search_local_text, read_local_file) för att lära dig mer och "
                f"hitta sambanden mellan dem, eller fördjupa förståelsen kring '{target_domain}'. "
                "Skriv sedan en detaljerad faktatext (en minirapport) om vad du upptäckte. "
                "Fokusera stenhårt på hur de relaterar och nya fakta som borde minnas."
            )

    client = AsyncOllama(timeout_sec=CURIOSITY_TIMEOUT_SEC)
    model_candidates = order_models_for_workload("curiosity", _curiosity_model_candidates(task))
    if not model_candidates:
        model_candidates = [CHAT_MODEL]
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    
    # Första kick-off från systemet (användaren ber om rapporten internt)
    messages.append({"role": "user", "content": "Kör igång sökningen. Undersök detta noggrant med verktyg och skriv din slutrapport."})

    # Agentic tool loop
    loop_limit = 5
    report_text = ""

    for step in range(loop_limit):
        try:
            resp = None
            last_model_error: Exception | None = None
            used_model = ""
            for model in model_candidates:
                try:
                    resp = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=MCP_TOOLS,
                        b76_meta={
                            "workload": "curiosity",
                            "session_id": str((task or {}).get("session_id") or "autonomous"),
                            "run_id": (str((task or {}).get("run_id") or "").strip() or None),
                        },
                    )
                    used_model = model
                    record_model_result("curiosity", model, success=True, timeout=False)
                    break
                except Exception as e:
                    timed_out = "timeout" in str(e).lower()
                    record_model_result("curiosity", model, success=False, timeout=timed_out)
                    last_model_error = e
                    log.warning(f"  [Curiosity] model-fel ({model}): {e}")

            if resp is None:
                if last_model_error is not None:
                    raise last_model_error
                raise RuntimeError("Curiosity saknar tillgänglig modell")

            if step == 0:
                log.info(f"Curiosity model: {used_model}")
            msg = resp.message

            # Den svarar med text (färdig!)
            if msg.content and not msg.tool_calls:
                report_text = msg.content
                break

            # Svarar med verktyg
            if msg.tool_calls:
                # Ollama: serialisera assistant-meddelandet via model_dump()
                messages.append(msg.model_dump())

                for tc in msg.tool_calls:
                    name = tc.function.name
                    # Ollama returnerar arguments som dict
                    args = (tc.function.arguments
                            if isinstance(tc.function.arguments, dict)
                            else json.loads(tc.function.arguments))
                    if is_mcp_tool(name):
                        log.info(f"  [Curiosity] kör MCP: {name}(...)")
                        result = execute_mcp_tool(name, args)
                    else:
                        result = {"error": f"Okänt verktyg {name}"}

                    # Ollama: inget tool_call_id
                    messages.append({
                        "role": "tool",
                        "content": str(result),
                    })

        except Exception as e:
            log.error(f"Ett fel uppstod i autonoma sökningen: {e}")
            break

    if report_text:
        log.info(f"Curiosity: Svekfärdig minirapport (längd: {len(report_text)} tecken)")
        return report_text
    
    return None
