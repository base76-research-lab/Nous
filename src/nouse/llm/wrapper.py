"""Reusable Nous-first wrapper helpers for any model call."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from inspect import Parameter, signature
from typing import Any, Callable

from nouse.inject import ContradictionResult, QueryResult
from nouse.limbic.state_modulator import SemanticModulation

_log = logging.getLogger("nouse.wrapper")


DEFAULT_SYSTEM_PREAMBLE = """You are wrapped by Nous, a persistent epistemic brain layer.

Always read the Nous memory block before answering.
Use validated relations as primary grounding.
Call out uncertainty, missing knowledge, and weak evidence explicitly.
Do not present unsupported claims as if Nous had validated them.
"""


@dataclass
class WrappedLLMResponse:
    """Result from a Nous-wrapped model call."""

    user_prompt: str
    system_prompt: str
    answer: str
    memory: QueryResult
    raw_response: Any = None
    contradiction: ContradictionResult | None = None
    semantic_modulation: SemanticModulation | None = None


def _build_focus_agenda(brain: Any, user_prompt: str, max_nodes: int = 3) -> str | None:
    """
    P4.1: Bygg en focus agenda från grafens högsta goal_weight-noder.

    Returnerar en instruktionssträng som "Fokusera på: X, Y, Z.
    Grafen anser dessa som prioriterade." eller None om ingen agenda hittades.
    """
    try:
        field = getattr(brain, "_field", None)
        if field is None:
            return None
        nodes = field.node_context_for_query(user_prompt, limit=max_nodes * 2)
        if not nodes:
            return None
        # Sortera efter goal_weight eller evidence_score som proxy
        scored = []
        for node in nodes:
            name = node.get("name", "")
            if not name:
                continue
            goal_w = float(node.get("goal_weight", 0) or 0)
            ev = float(node.get("evidence_score", 0) or 0)
            # goal_weight är primär, evidence som sekundär sortering
            scored.append((name, goal_w, ev))
        scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
        top = [name for name, _, _ in scored[:max_nodes]]
        if not top:
            return None
        return f"Fokusera på: {', '.join(top)}. Grafen anser dessa som prioriterade."
    except Exception as e:
        _log.debug("Focus agenda misslyckades (non-fatal): %s", e)
        return None


def _build_gap_questions(brain: Any, user_prompt: str, max_gaps: int = 2) -> list[str]:
    """
    P4.2: Identifiera kunskapsgap (höga u-noder) och formulera frågor.

    Returnerar en lista med clarifying questions baserade på osäkra noder.
    """
    questions: list[str] = []
    try:
        field = getattr(brain, "_field", None)
        if field is None:
            return questions
        # Hämta noder med hög osäkerhet via gap_map
        gap = field.gap_map() if hasattr(field, "gap_map") else {}
        weak_nodes = gap.get("weak_nodes", []) if isinstance(gap, dict) else []
        if not weak_nodes:
            return questions
        # Filtrera mot användarens fråga — prioritera noder som är relaterade
        query_terms = set(user_prompt.lower().split())
        for node in weak_nodes[:max_gaps * 2]:
            name = node.get("node_id", "")
            uncertainty = float(node.get("uncertainty", 0) or 0)
            # Prioritera noder som överlappar med frågan
            name_terms = set(name.lower().replace("_", " ").split())
            overlap = len(query_terms & name_terms)
            if overlap > 0 or uncertainty > 0.8:
                questions.append(
                    f"Hur relaterar {name} till denna fråga? (osäkerhet: {uncertainty:.0%})"
                )
            if len(questions) >= max_gaps:
                break
    except Exception as e:
        _log.debug("Gap questions misslyckades (non-fatal): %s", e)
    return questions


def build_system_prompt(
    user_prompt: str,
    *,
    brain: Any | None = None,
    top_k: int = 6,
    max_axioms: int = 15,
    preamble: str = DEFAULT_SYSTEM_PREAMBLE,
    include_metadata: bool = True,
) -> tuple[str, QueryResult]:
    """Build a Nous-first system prompt for a user query."""
    if brain is None:
        import nouse

        brain = nouse.attach()

    memory = brain.query(user_prompt, top_k=top_k)
    context_block = memory.context_block(max_axioms=max_axioms).strip()

    if not context_block:
        context_block = (
            "[Nous memory]\n"
            "No grounded memory was found for this query. "
            "Answer carefully and make uncertainty explicit."
        )

    parts = [preamble.strip(), context_block]
    if include_metadata:
        parts.append(_format_memory_metadata(memory))

    # ── P4.1: Graf-prioriterad focus agenda ──────────────────────────────────
    agenda = _build_focus_agenda(brain, user_prompt)
    if agenda:
        parts.append(f"[Focus agenda]\n{agenda}")

    # ── P4.2: Gap-driven clarifying questions ─────────────────────────────────
    gap_questions = _build_gap_questions(brain, user_prompt)
    if gap_questions:
        questions_text = "\n".join(f"- {q}" for q in gap_questions)
        parts.append(
            f"[Open questions — graph uncertainty]\n"
            f"Answer these if relevant, or acknowledge them:\n{questions_text}"
        )

    return "\n\n".join(part for part in parts if part), memory


def run_with_nouse(
    user_prompt: str,
    call_model: Callable[..., Any],
    *,
    brain: Any | None = None,
    top_k: int = 6,
    max_axioms: int = 15,
    preamble: str = DEFAULT_SYSTEM_PREAMBLE,
    include_metadata: bool = True,
    learn: bool = True,
    source: str = "nouse-wrapper",
    model: str | None = None,
    check_contradictions: bool = True,
    contradiction_threshold: float = 0.75,
) -> WrappedLLMResponse:
    """Run a model call through Nous grounding, then learn from the answer."""
    # ── Läs limbisk modulering ────────────────────────────────────────────────
    semantic_mod: SemanticModulation | None = None
    try:
        from nouse.limbic.signals import load_state as _load_limbic
        from nouse.limbic.state_modulator import modulate as _modulate
        semantic_mod = _modulate(_load_limbic())
        # Injicera tillståndsläge i systemprompten
        if semantic_mod.response_mode not in ("balanced", "optimal"):
            _MODE_HINTS = {
                "corrective":      "IMPORTANT: Correction mode — prioritize identifying errors and inconsistencies.",
                "defensive":       "IMPORTANT: Degraded state — be concise and conservative. Avoid speculation.",
                "emergency":       "IMPORTANT: Emergency state — minimal output, flag critical issues only.",
                "consolidating":   "NOTE: Consolidation mode — prefer grounded, well-evidenced assertions.",
                "deep_processing": "NOTE: Focused mode — high signal/noise priority. Filter irrelevant content.",
                "exploratory":     "NOTE: Exploratory mode — welcome novel connections and low-confidence bridges.",
                "insight_capture": "NOTE: Insight mode — capture the full structure of emerging insights precisely.",
                "goal_directed":   "NOTE: Goal-directed mode — stay closely aligned with operator mission.",
                "conservative":    "NOTE: Conservative mode — low resources, minimal elaboration.",
                "strategy_shift":  "NOTE: Strategy-shift mode — suggest alternative approaches if current is blocked.",
            }
            hint = _MODE_HINTS.get(semantic_mod.response_mode, "")
            if hint:
                preamble = preamble.rstrip() + f"\n\n{hint}"
        if semantic_mod.wants_hitl:
            _log.warning(
                "HITL hint in run_with_nouse: state=%s flags=%s",
                semantic_mod.dominant_state,
                list(semantic_mod.flags.keys()),
            )
    except Exception as _e:
        _log.debug("Limbic modulation unavailable (non-fatal): %s", _e)

    system_prompt, memory = build_system_prompt(
        user_prompt,
        brain=brain,
        top_k=top_k,
        max_axioms=max_axioms,
        preamble=preamble,
        include_metadata=include_metadata,
    )

    raw_response = _call_model(
        call_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        memory=memory,
    )
    answer = extract_response_text(raw_response)

    # ── Epistemic authority check ─────────────────────────────────────────────
    contradiction: ContradictionResult | None = None
    active_brain = brain
    if check_contradictions:
        if active_brain is None:
            try:
                import nouse
                active_brain = nouse.attach()
            except Exception:
                active_brain = None
        if active_brain is not None:
            try:
                contradiction = active_brain.check_contradiction(
                    answer, threshold=contradiction_threshold
                )
                if contradiction.has_conflict:
                    active_brain.log_contradiction_event(contradiction, query=user_prompt)
                    annotation = contradiction.as_annotation()
                    if contradiction.recommendation == "block":
                        answer = answer + f"\n\n{annotation}"
                        _log.warning(
                            "BLOCK: contradiction severity=%.2f — annotated answer. "
                            "query=%r concepts=%s",
                            contradiction.severity,
                            user_prompt[:60],
                            contradiction.checked_concepts[:4],
                        )
                    elif contradiction.recommendation in ("flag", "warn"):
                        answer = answer + f"\n\n{annotation}"
                        _log.info(
                            "CONTRADICTION %s: severity=%.2f query=%r",
                            contradiction.recommendation,
                            contradiction.severity,
                            user_prompt[:60],
                        )
            except Exception as e:
                _log.debug("check_contradiction failed (non-fatal): %s", e)

    # ── P4.3: Hallucination block — assumption_flag check ────────────────────────
    # Om grafen har flaggat påståenden som osäkra (assumption_flag=True),
    # och LLM-svaret nämner dem, injicera varning.
    if active_brain is not None and answer:
        try:
            answer_lower = answer.lower()
            flagged_warnings: list[str] = []
            for concept in memory.concepts:
                name = getattr(concept, "name", "")
                if not name:
                    continue
                # Kontrollera om konceptet har assumption_flag i grafen
                field = getattr(active_brain, "_field", None)
                if field is None:
                    continue
                rels = field.out_relations(name, limit=10)
                for rel in rels:
                    if _as_bool(rel.get("assumption_flag")):
                        why = rel.get("why", "")[:60]
                        tgt = rel.get("target", "")
                        rel_type = rel.get("type", "")
                        # Kontrollera om LLM-svaret nämner target-konceptet
                        if tgt.lower() in answer_lower:
                            flagged_warnings.append(
                                f"'{name} —{rel_type}→ {tgt}' är flaggat som osäkert antagande"
                                + (f" ({why})" if why else "")
                            )
            if flagged_warnings:
                warning = (
                    "[Hallucination block]\n"
                    "Grafen har flaggat följande som osäkra antaganden — "
                    "källhänvisning saknas:\n"
                    + "\n".join(f"- {w}" for w in flagged_warnings[:3])
                )
                answer = answer + f"\n\n{warning}"
                _log.info("HALLUCINATION BLOCK: %d flaggade antaganden i svar", len(flagged_warnings))
        except Exception as e:
            _log.debug("Hallucination block misslyckades (non-fatal): %s", e)

    # ── Learn from exchange (write-back gated by limbic state) ───────────────
    _gate = (semantic_mod.write_back_gate if semantic_mod else "open")
    if _gate == "blocked":
        learn = False
        _log.info("write_back_gate=blocked — learning skipped (state=%s)",
                  semantic_mod.dominant_state if semantic_mod else "unknown")
    elif _gate == "minimal":
        # Learn with halved confidence weight to reduce graph pollution during fatigue
        if active_brain is None:
            try:
                import nouse
                active_brain = nouse.attach()
            except Exception:
                active_brain = None

    if learn:
        if active_brain is None:
            try:
                import nouse
                active_brain = nouse.attach()
            except Exception:
                active_brain = None
        if active_brain is not None:
            active_brain.learn(
                user_prompt,
                answer,
                source=source,
                model=model,
                context_block=memory.context_block(max_axioms=max_axioms),
                confidence_in=memory.confidence,
                nodes_used=[concept.name for concept in memory.concepts],
            )

    return WrappedLLMResponse(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        answer=answer,
        memory=memory,
        raw_response=raw_response,
        contradiction=contradiction,
        semantic_modulation=semantic_mod,
    )


def extract_response_text(response: Any) -> str:
    """Extract text from common model response shapes."""
    if isinstance(response, str):
        return response

    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text:
        return output_text

    choices = getattr(response, "choices", None)
    if choices:
        first = choices[0]
        message = getattr(first, "message", None)
        if message is not None:
            content = getattr(message, "content", None)
            if isinstance(content, str) and content:
                return content
        text = getattr(first, "text", None)
        if isinstance(text, str) and text:
            return text

    content = getattr(response, "content", None)
    if isinstance(content, str) and content:
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
            else:
                text = getattr(item, "text", None)
            if isinstance(text, str) and text:
                parts.append(text)
        if parts:
            return "\n".join(parts)

    if isinstance(response, dict):
        for key in ("output_text", "content", "text"):
            value = response.get(key)
            if isinstance(value, str) and value:
                return value
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] or {}
            if isinstance(first, dict):
                message = first.get("message") or {}
                content = message.get("content")
                if isinstance(content, str) and content:
                    return content
                text = first.get("text")
                if isinstance(text, str) and text:
                    return text

    raise TypeError("Could not extract text from model response")


def _call_model(
    call_model: Callable[..., Any],
    *,
    system_prompt: str,
    user_prompt: str,
    memory: QueryResult,
) -> Any:
    params = signature(call_model).parameters
    accepts_kwargs = any(
        param.kind == Parameter.VAR_KEYWORD for param in params.values()
    )

    kwargs: dict[str, Any] = {}
    if accepts_kwargs or "system_prompt" in params:
        kwargs["system_prompt"] = system_prompt
    if accepts_kwargs or "user_prompt" in params:
        kwargs["user_prompt"] = user_prompt
    if accepts_kwargs or "memory" in params:
        kwargs["memory"] = memory
    if kwargs:
        return call_model(**kwargs)

    positional_arity = sum(
        param.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
        for param in params.values()
    )
    if positional_arity >= 3:
        return call_model(system_prompt, user_prompt, memory)
    if positional_arity == 2:
        return call_model(system_prompt, user_prompt)
    if positional_arity == 1:
        return call_model(user_prompt)
    return call_model()


def _as_bool(value: Any) -> bool:
    """Konvertera olika truthy-representationer till bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return False


def _format_memory_metadata(memory: QueryResult) -> str:
    domains = ", ".join(memory.domains) if memory.domains else "unknown"
    return (
        "[Nous meta]\n"
        f"confidence={memory.confidence:.2f}\n"
        f"axioms={len(memory.axioms)}\n"
        f"domains={domains}\n"
        f"has_knowledge={str(memory.has_knowledge).lower()}"
    )
