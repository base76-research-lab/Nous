"""
nouse.llm.agent — Single-model sub-agent routing for NoUse.

Instead of dispatching workloads to different models (deepseek for extraction,
groq for synthesis, etc.), NouseAgent routes every workload to the same capable
local model using role-specific system prompts.

One model. Multiple epistemic roles. No external API dependencies.

    agent = NouseAgent("gemma4:e2b")
    relations = await agent.extract("NoUse uses a typed knowledge graph...")
    answer    = await agent.synthesize(query="What is NoUse?", context=nodes)
    questions = await agent.curiosity("epistemic memory")
    facts     = await agent.bootstrap("climate science")
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

from nouse.ollama_client.client import AsyncOllama
from nouse.llm.policy import get_workload_policy

_log = logging.getLogger("nouse.agent")

# ── System prompts per role ───────────────────────────────────────────────────

_ROLES: dict[str, str] = {
    "extractor": """You are a knowledge graph relation extractor.

Given text, extract typed semantic relations as a JSON array.
Each relation: {"src": "...", "rel_type": "...", "tgt": "...", "confidence": 0.0-1.0}

Rules:
- src and tgt are short noun phrases (2-5 words max)
- rel_type is a snake_case verb phrase: causes, is_part_of, modulates, produces, describes, strengthens, is_analogous_to
- confidence: 1.0 = stated fact, 0.7 = implied, 0.5 = inferred
- Extract 3-12 relations per text
- Return ONLY the JSON array, no explanation, no markdown fences""",

    "synthesizer": """You are an epistemic synthesizer.

You receive a query and a set of knowledge graph nodes with confidence scores.
Produce a concise, grounded answer. Rules:
- Only use what is present in the provided nodes
- State confidence level for your answer
- Flag what is uncertain or unknown
- 2-4 sentences max
- Do not hallucinate facts not in the nodes""",

    "curiosity": """You are a knowledge gap detector.

Given a concept or domain, generate exactly 3 high-value questions that would
most strengthen a knowledge graph about this topic.

Return a JSON array of 3 strings. Example:
["What mechanism causes X?", "How does X relate to Y?", "What are the limits of X?"]

Return ONLY the JSON array.""",

    "bootstrap": """You are a domain knowledge structurer.

Given a topic, explain its core structure using typed relational facts.
Return a JSON array of relations:
{"src": "...", "rel_type": "...", "tgt": "...", "confidence": 0.0-1.0}

Focus on:
- Core definitional relations (is_a, is_part_of)
- Causal relations (causes, produces, modulates)
- Structural relations (contains, requires, enables)

Return 8-15 relations. Return ONLY the JSON array.""",

    "validator": """You are an epistemic validator.

Given a claim and optional evidence, assess confidence on a 0-1 scale.
Return JSON: {"confidence": 0.0-1.0, "reasoning": "one sentence", "status": "confirmed|uncertain|contradicted"}

Return ONLY the JSON object.""",

    "chat": """You are NoUse — an epistemic AI assistant with persistent memory.

You have access to a typed knowledge graph. Your answers are grounded in what
is known with confidence. You clearly distinguish between what you know,
what you infer, and what is uncertain. Your memory persists across sessions.""",
}

# ── Default model resolution ──────────────────────────────────────────────────

def _default_model() -> str:
    """Resolve default model from policy or env."""
    env_model = (os.getenv("NOUSE_AGENT_MODEL") or os.getenv("NOUSE_OLLAMA_MODEL") or "").strip()
    if env_model:
        return env_model
    policy = get_workload_policy("extract")
    candidates = policy.get("candidates") or []
    if candidates:
        return candidates[0]
    return "gemma4:e2b"


# ── NouseAgent ────────────────────────────────────────────────────────────────

class NouseAgent:
    """
    Single-model sub-agent router. One Ollama model, all NoUse workloads.

    Usage:
        agent = NouseAgent()                    # uses model_policy.json
        agent = NouseAgent("gemma4:e2b")        # explicit model
        agent = NouseAgent("gemma4:26b")        # upgrade for better quality
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        timeout: float = 45.0,
    ) -> None:
        self.model = model or _default_model()
        self.timeout = timeout
        self._client = AsyncOllama(timeout_sec=timeout)

    async def _call(self, role: str, user_prompt: str) -> str:
        system = _ROLES.get(role, _ROLES["chat"])
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            b76_meta={"workload": role},
        )
        return (resp.message.content or "").strip()

    def _call_sync(self, role: str, user_prompt: str) -> str:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, self._call(role, user_prompt))
                    return future.result(timeout=self.timeout + 5)
            return loop.run_until_complete(self._call(role, user_prompt))
        except Exception:
            return asyncio.run(self._call(role, user_prompt))

    # ── Extraction ────────────────────────────────────────────────────────────

    async def extract(self, text: str) -> list[dict[str, Any]]:
        """Extract typed relations from text. Returns list of {src, rel_type, tgt, confidence}."""
        raw = await self._call("extractor", f"Text:\n{text}")
        return _parse_json_array(raw)

    # ── Synthesis ─────────────────────────────────────────────────────────────

    async def synthesize(self, *, query: str, context: str) -> str:
        """Synthesize an answer from graph context nodes."""
        prompt = f"Query: {query}\n\nKnowledge graph context:\n{context}"
        return await self._call("synthesizer", prompt)

    # ── Curiosity ─────────────────────────────────────────────────────────────

    async def curiosity(self, topic: str) -> list[str]:
        """Generate 3 high-value questions to strengthen graph knowledge."""
        raw = await self._call("curiosity", f"Topic: {topic}")
        parsed = _parse_json_array(raw)
        if parsed and isinstance(parsed[0], str):
            return parsed[:3]
        return [str(x) for x in parsed[:3]] if parsed else []

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    async def bootstrap(self, topic: str) -> list[dict[str, Any]]:
        """Seed knowledge graph with relational facts about a domain topic."""
        raw = await self._call("bootstrap", f"Topic: {topic}")
        return _parse_json_array(raw)

    # ── Validation ────────────────────────────────────────────────────────────

    async def validate(self, claim: str, evidence: str = "") -> dict[str, Any]:
        """Assess confidence for a claim. Returns {confidence, reasoning, status}."""
        prompt = f"Claim: {claim}"
        if evidence:
            prompt += f"\nEvidence: {evidence}"
        raw = await self._call("validator", prompt)
        try:
            return json.loads(_strip_fences(raw))
        except Exception:
            return {"confidence": 0.5, "reasoning": raw[:200], "status": "uncertain"}

    # ── Chat ──────────────────────────────────────────────────────────────────

    async def chat(self, message: str, *, context: str = "") -> str:
        """Full NoUse chat response, optionally grounded in graph context."""
        if context:
            prompt = f"Graph context:\n{context}\n\nUser: {message}"
        else:
            prompt = message
        return await self._call("chat", prompt)


# ── JSON parsing helpers ──────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text.strip(), flags=re.MULTILINE)
    return text.strip()


def _parse_json_array(raw: str) -> list[Any]:
    text = _strip_fences(raw)
    # Try direct parse first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass
    # Try extracting first [...] block
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    _log.debug("NouseAgent: failed to parse JSON array from: %s", raw[:200])
    return []


# ── Module-level singleton for convenience ────────────────────────────────────

_default_agent: NouseAgent | None = None
_agent_lock = __import__("threading").Lock()


def get_agent(model: str | None = None) -> NouseAgent:
    """Return the module-level NouseAgent singleton."""
    global _default_agent
    with _agent_lock:
        if _default_agent is None or (model and _default_agent.model != model):
            _default_agent = NouseAgent(model)
        return _default_agent
