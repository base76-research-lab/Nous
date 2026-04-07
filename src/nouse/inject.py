"""
nouse.inject — One-line cognitive substrate for any LLM.

Basic usage:
    brain = nouse.attach()
    context = brain.context_block(user_input)   # formatted for LLM prompt
    brain.learn(user_input, llm_response)

Eval usage:
    axioms = brain.recall_axioms("mesoscale eddies")
    # → [Axiom(src=..., rel=..., tgt=..., evidence=0.82, flagged=False), ...]

    result = brain.query("What causes ocean heat transport?")
    # → QueryResult(axioms=[...], concepts=[...], confidence=0.81, domains=[...])
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Any


# ── Structured types ──────────────────────────────────────────────────────────

@dataclass
class Axiom:
    """A single relation in the knowledge graph with full metadata."""
    src: str
    rel: str
    tgt: str
    evidence: float          # 0.0–1.0, from evidence_score
    flagged: bool            # assumption_flag — pending deep review
    why: str = ""            # motivation / provenance
    strength: float = 0.5   # Hebbian strength

    @property
    def is_strong(self) -> bool:
        return self.evidence >= 0.75 and not self.flagged

    @property
    def is_uncertain(self) -> bool:
        return self.evidence < 0.45 or self.flagged

    def as_text(self) -> str:
        flag = " ⚑" if self.flagged else ""
        return f"{self.src} —[{self.rel}]→ {self.tgt}  [ev={self.evidence:.2f}]{flag}"


@dataclass
class ConceptProfile:
    """What the graph knows about a single concept."""
    name: str
    summary: str
    claims: list[str]
    evidence_refs: list[str]
    related_terms: list[str]
    uncertainty: float | None
    revision_count: int
    axioms: list[Axiom] = field(default_factory=list)


@dataclass
class QueryResult:
    """Full structured response from brain.query() — for eval harness."""
    query: str
    concepts: list[ConceptProfile]
    axioms: list[Axiom]
    confidence: float          # mean evidence of strong axioms, or 0.0
    domains: list[str]
    has_knowledge: bool

    def context_block(self, max_axioms: int = 15) -> str:
        """Format as LLM-ready context string."""
        return _format_context_block(self.concepts, self.axioms, max_axioms)

    def strong_axioms(self) -> list[Axiom]:
        return [a for a in self.axioms if a.is_strong]

    def flagged_axioms(self) -> list[Axiom]:
        return [a for a in self.axioms if a.flagged]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_context_block(
    concepts: list[ConceptProfile],
    axioms: list[Axiom],
    max_axioms: int = 15,
) -> str:
    if not concepts and not axioms:
        return ""

    parts: list[str] = ["[Nouse memory]"]

    # Concept summaries
    for c in concepts[:5]:
        if c.summary:
            flag = f"  (uncertainty={c.uncertainty:.2f})" if c.uncertainty else ""
            parts.append(f"• {c.name}: {c.summary[:200]}{flag}")
        if c.claims:
            for claim in c.claims[:2]:
                parts.append(f"  claim: {claim[:150]}")

    # Strong axioms first, then uncertain
    strong = [a for a in axioms if a.is_strong][:max_axioms]
    uncertain = [a for a in axioms if not a.is_strong][:max(0, max_axioms - len(strong))]

    if strong:
        parts.append("\nValidated relations:")
        for a in strong:
            parts.append(f"  {a.as_text()}")
    if uncertain:
        parts.append("\nUncertain / under review:")
        for a in uncertain:
            parts.append(f"  {a.as_text()}")

    return "\n".join(parts)


def _rows_to_axioms(src_name: str, rows: list[dict]) -> list[Axiom]:
    out = []
    for r in rows:
        raw_ev = r.get("evidence_score")
        strength = float(r.get("strength") or 1.0)
        flagged = bool(r.get("assumption_flag") or False)

        if raw_ev is not None:
            ev = float(raw_ev)
        else:
            # Normalisera Hebbian strength → [0.45, 0.95]
            # strength 1.0 = aldrig traverserat extra = 0.45
            # strength 2.0 = ~20 traversals = 0.72
            # strength 3.0+ = mycket traverserat = 0.90+
            ev = min(0.95, 0.45 + (strength - 1.0) * 0.25)

        out.append(Axiom(
            src=src_name,
            rel=str(r.get("type") or "related_to"),
            tgt=str(r.get("target") or ""),
            evidence=ev,
            flagged=flagged,
            why=str(r.get("why") or ""),
            strength=strength,
        ))
    return out


# ── NouseBrain ────────────────────────────────────────────────────────────────

class NouseBrain:
    """
    Cognitive substrate facade — inject into any LLM pipeline.

    Quick start:
        brain = nouse.attach()
        ctx   = brain.context_block("mesoscale eddies")
        # inject ctx into system prompt, then call your LLM

    Eval:
        result = brain.query("What causes X?")
        print(result.confidence, result.strong_axioms())
    """

    def __init__(self, db_path: str | Path | None = None, read_only: bool = False):
        from nouse.field.surface import FieldSurface
        self._field = FieldSurface(db_path=db_path, read_only=read_only)
        self._read_only = read_only
        self._input_hooks: list[Callable] = []
        self._output_hooks: list[Callable] = []

    # ── Primary query API ─────────────────────────────────────────────────────

    def recall_axioms(self, concept_or_query: str, top_k: int = 8) -> list[Axiom]:
        """
        Return structured Axiom objects for a concept or free-text query.
        Sorted by evidence score descending.
        """
        axioms: list[Axiom] = []
        nodes = self._field.node_context_for_query(concept_or_query, limit=top_k)
        for node in nodes:
            name = node.get("name", "")
            if not name:
                continue
            try:
                rows = self._field.out_relations(name)
                axioms.extend(_rows_to_axioms(name, rows))
            except Exception:
                pass
        axioms.sort(key=lambda a: -a.evidence)
        return axioms

    def query(self, question: str, top_k: int = 6, model: str = None) -> QueryResult:
        """
        Full structured query — for eval harness.
        Returns concepts + axioms + confidence score + domains.
        Checks modelsessions for replay before querying graph.
        """
        try:
            from nouse.memory import modelsessions
        except ImportError:
            modelsessions = None

        # Zero-token replay: check modelsessions
        if modelsessions is not None:
            found = modelsessions.find_session(question, model=model)
            if found:
                # Minimal QueryResult from session log
                return QueryResult(
                    query=found.get("query", question),
                    concepts=[],
                    axioms=[],
                    confidence=found.get("confidence_out") or 0.0,
                    domains=[],
                    has_knowledge=True,
                )

        # Normal path
        nodes = self._field.node_context_for_query(question, limit=top_k)
        profiles: list[ConceptProfile] = []
        all_axioms: list[Axiom] = []
        domains: set[str] = set()

        for node in nodes:
            name = node.get("name", "")
            if not name:
                continue
            k = self._field.concept_knowledge(name)
            try:
                rel_rows = self._field.out_relations(name)
                node_axioms = _rows_to_axioms(name, rel_rows)
            except Exception:
                node_axioms = []

            # domain from concept
            try:
                concepts = self._field.concepts()
                for c in concepts:
                    if c.get("name") == name and c.get("domain"):
                        domains.add(c["domain"])
            except Exception:
                pass

            profiles.append(ConceptProfile(
                name=name,
                summary=k.get("summary", "") or node.get("summary", ""),
                claims=k.get("claims", []),
                evidence_refs=k.get("evidence_refs", []),
                related_terms=k.get("related_terms", []),
                uncertainty=k.get("uncertainty"),
                revision_count=k.get("revision_count", 0),
                axioms=node_axioms,
            ))
            all_axioms.extend(node_axioms)

        all_axioms.sort(key=lambda a: -a.evidence)
        strong = [a for a in all_axioms if a.is_strong]
        confidence = (sum(a.evidence for a in strong) / len(strong)) if strong else 0.0

        return QueryResult(
            query=question,
            concepts=profiles,
            axioms=all_axioms,
            confidence=confidence,
            domains=sorted(domains),
            has_knowledge=bool(profiles),
        )

    def context_block(self, query: str, top_k: int = 6, max_axioms: int = 15) -> str:
        """
        Return a formatted context string ready to inject into an LLM system prompt.
        Empty string if nothing relevant found.
        """
        result = self.query(query, top_k=top_k)
        return result.context_block(max_axioms=max_axioms)

    # ── Legacy / convenience API ──────────────────────────────────────────────

    def recall(self, query: str, top_k: int = 5) -> str:
        """Backwards-compatible: return context as plain text."""
        return self.context_block(query, top_k=top_k)

    def recall_relations(self, concept: str) -> list[dict]:
        """Return raw graph relations for a concept (dict format)."""
        try:
            return self._field.out_relations(concept)
        except Exception:
            return []

<<<<<<< Updated upstream
    def learn(self, prompt: str, response: str, source: str = "conversation",
              domain_hint: str = "") -> None:
        """Extract and store knowledge from a prompt/response pair."""
=======
    def learn(self, prompt: str, response: str, source: str = "conversation", model: str = None, context_block: str = "", confidence_in: float = None, confidence_out: float = None, nodes_used: list = None, tokens_saved: int = 0) -> None:
        """Extract and store knowledge from a prompt/response pair. Also logs to modelsessions."""
>>>>>>> Stashed changes
        import asyncio
        import logging
        from nouse.daemon.extractor import extract_relations
        _log = logging.getLogger("nouse.brain.learn")
        metadata = {"source": source, "domain_hint": domain_hint or source}
        text = (prompt + "\n" + response).strip()

        async def _run() -> None:
            try:
                relations = await extract_relations(text, metadata)
                for rel in relations:
                    src = rel.get("src", "")
                    tgt = rel.get("tgt", "")
                    rel_type = rel.get("type", "relates_to")
                    why = rel.get("why", "")
                    ev = float(rel.get("evidence_score", rel.get("ev", 0.6)))
                    d_src = rel.get("domain_src", "external")
                    d_tgt = rel.get("domain_tgt", "external")
                    if src and tgt and len(src) > 1 and len(tgt) > 1:
                        self._field.add_relation(
                            src, rel_type, tgt,
                            why=why, evidence_score=ev,
                            source_tag=source,
                            domain_src=d_src, domain_tgt=d_tgt,
                        )
                if relations:
                    _log.debug("learn(): %d relations from '%s'", len(relations), source)
            except Exception as e:
                _log.debug("learn() extraction failed (%s): %s", source, e)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    ex.submit(asyncio.run, _run()).result(timeout=45)
            else:
                loop.run_until_complete(_run())
        except Exception as e:
            logging.getLogger("nouse.brain.learn").debug("learn() runner failed: %s", e)

    def domain_bootstrap(
        self,
        topic: str,
        *,
        model: str | None = None,
        evidence_score: float = 0.65,
    ) -> int:
        """
        Seed the graph with LLM knowledge for an unknown topic.

        Asks the configured model to describe the topic as structured relations,
        then stores them as hypothesis-tier nodes. Returns number of relations added.

        Uses the same extraction pipeline as ghost_q but fires reactively on a
        query miss rather than nightly.
        """
        import asyncio
        import logging
        _log = logging.getLogger("nouse.brain.bootstrap")

        BOOTSTRAP_SYSTEM = (
            "You are a knowledge distiller. Extract structured factual knowledge. "
            "State facts as concrete relations: 'X is Y', 'X causes Z', 'X relates to Y'. "
            "Cover key concepts, subdomains, and their connections. Be specific. Max 350 words."
        )
        prompt = (
            f"Explain the topic '{topic}': its main concepts, key relations, "
            f"and how they connect to each other. Focus on verifiable facts."
        )

        async def _run() -> int:
            from nouse.daemon.extractor import extract_relations
            try:
                model_router = getattr(self, "_model_router", None)
                if model_router is not None:
                    response = await model_router.complete(
                        prompt, system=BOOTSTRAP_SYSTEM, max_tokens=450
                    )
                else:
                    # Fallback: use Ollama directly with configured model
                    import os, httpx
                    _model = model or os.getenv("NOUSE_OLLAMA_MODEL", "deepseek-r1:1.5b")
                    ollama_base = os.getenv("OLLAMA_HOST", "http://localhost:11434")
                    payload = {
                        "model": _model,
                        "messages": [
                            {"role": "system", "content": BOOTSTRAP_SYSTEM},
                            {"role": "user", "content": prompt},
                        ],
                        "stream": False,
                    }
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        r = await client.post(f"{ollama_base}/api/chat", json=payload)
                        r.raise_for_status()
                        response = r.json().get("message", {}).get("content", "")

                if not response:
                    return 0

                relations = await extract_relations(
                    f"Topic: {topic}\n\n{response}",
                    {"source": "domain_bootstrap", "domain_hint": topic},
                )
                count = 0
                for rel in relations:
                    src = rel.get("src", "")
                    tgt = rel.get("tgt", "")
                    rel_type = rel.get("type", "relates_to")
                    why = rel.get("why", "bootstrapped from model weights")
                    ev = float(rel.get("evidence_score", rel.get("ev", evidence_score)))
                    if src and tgt and len(src) > 1 and len(tgt) > 1:
                        self._field.add_relation(
                            src, rel_type, tgt,
                            why=why, evidence_score=ev,
                            source_tag="domain_bootstrap",
                        )
                        count += 1
                _log.info("domain_bootstrap('%s'): %d relations seeded", topic, count)
                return count
            except Exception as e:
                _log.warning("domain_bootstrap('%s') failed: %s", topic, e)
                return 0

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    return ex.submit(asyncio.run, _run()).result(timeout=60)
            return loop.run_until_complete(_run())
        except Exception as e:
            logging.getLogger("nouse.brain.bootstrap").warning(
                "domain_bootstrap runner failed: %s", e
            )
            return 0

        # Log session to modelsessions
        try:
            from nouse.memory import modelsessions
            modelsessions.log_session(
                model=model or "unknown",
                query=prompt,
                answer=response,
                context_block=context_block,
                confidence_in=confidence_in,
                confidence_out=confidence_out,
                nodes_used=nodes_used or [],
                tokens_saved=tokens_saved,
                extra={"source": source}
            )
        except Exception:
            pass

    def add(
        self,
        src: str,
        rel_type: str,
        tgt: str,
        *,
        why: str = "",
        evidence_score: float = 0.6,
    ) -> None:
        """Directly add a relation to the knowledge graph."""
        self._field.add_relation(src, rel_type, tgt, why=why, evidence_score=evidence_score)

    # ── Session relay API ─────────────────────────────────────────────────────

    def relay_open(self, goal: str, *, model: str = "unknown") -> dict:
        """Start a new cross-model relay session. Returns session dict with session_id."""
        from nouse.session.relay import relay_open
        return relay_open(goal, model=model)

    def relay_update(
        self,
        session_id: str,
        *,
        decision: str | None = None,
        decision_why: str = "",
        decision_confidence: float = 0.8,
        open_question: str | None = None,
        file_touched: str | None = None,
        node_used: str | None = None,
        summary: str | None = None,
        model: str | None = None,
    ) -> dict | None:
        """Update an active relay session with new work context."""
        from nouse.session.relay import relay_update
        return relay_update(
            session_id,
            decision=decision,
            decision_why=decision_why,
            decision_confidence=decision_confidence,
            open_question=open_question,
            file_touched=file_touched,
            node_used=node_used,
            summary=summary,
            model=model,
        )

    def relay_continue(self, session_id: str, *, model: str = "unknown") -> str:
        """Return a compact context block for the next model picking up this session."""
        from nouse.session.relay import relay_continue
        return relay_continue(session_id, model=model)

    def relay_list(self, *, status: str | None = None, limit: int = 10) -> list:
        """List relay sessions."""
        from nouse.session.relay import relay_list
        return relay_list(status=status, limit=limit)

    def on_input(self, fn: Callable) -> Callable:
        """Decorator: enrich prompt before it reaches the LLM."""
        self._input_hooks.append(fn)
        return fn

    def on_output(self, fn: Callable) -> Callable:
        """Decorator: process response after LLM returns."""
        self._output_hooks.append(fn)
        return fn

    def process_input(self, prompt: str) -> str:
        for hook in self._input_hooks:
            try:
                prompt = hook(prompt)
            except Exception:
                pass
        return prompt

    def process_output(self, prompt: str, response: str) -> None:
        for hook in self._output_hooks:
            try:
                hook(prompt, response)
            except Exception:
                pass

    # ── Escalation API ────────────────────────────────────────────────────────

    async def escalate(
        self,
        query: str,
        *,
        threshold: float = 0.5,
        learn: bool = True,
    ):
        """
        Escalating query — graf first, web fallback if confidence is low.

        Returns EscalationResult with .context_block ready for LLM injection.

        Usage:
            result = await brain.escalate("vad är KuzuDB?")
            # result.escalated == True  → web was used
            # result.context_block      → inject into LLM prompt
        """
        from nouse.search.escalator import escalate_query
        return await escalate_query(
            query, self, threshold=threshold, learn=learn
        )

    def escalate_sync(
        self,
        query: str,
        *,
        threshold: float = 0.5,
        learn: bool = True,
    ):
        """Synchronous version of escalate() for non-async contexts."""
        from nouse.search.escalator import escalate_query_sync
        return escalate_query_sync(
            query, self, threshold=threshold, learn=learn
        )

    def stats(self) -> dict:
        return self._field.stats()

    @property
    def field(self):
        return self._field


# ── NouseBrainHTTP ────────────────────────────────────────────────────────────

class NouseBrainHTTP:
    """
    HTTP client for NouseBrain — returned by attach() when the daemon is running.

    Avoids opening KuzuDB directly (write-lock conflict) by routing all calls
    through the daemon's REST API at localhost:8765.

    The interface is identical to NouseBrain so callers need no changes.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8765", api_key: str | None = None) -> None:
        import httpx
        self._base = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(timeout=30.0, headers=headers)

    # ── Primary query API ─────────────────────────────────────────────────────

    def query(self, question: str, top_k: int = 6) -> QueryResult:
        r = self._client.post(
            f"{self._base}/api/brain/query",
            json={"question": question, "top_k": top_k},
        )
        r.raise_for_status()
        data = r.json()
        axioms = [
            Axiom(
                src=a["src"], rel=a["rel"], tgt=a["tgt"],
                evidence=a["evidence"], flagged=a["flagged"],
                why=a.get("why", ""), strength=a.get("strength", 1.0),
            )
            for a in data.get("axioms", [])
        ]
        concepts = [
            ConceptProfile(
                name=c["name"],
                summary=c.get("summary", ""),
                claims=c.get("claims", []),
                evidence_refs=c.get("evidence_refs", []),
                related_terms=c.get("related_terms", []),
                uncertainty=c.get("uncertainty"),
                revision_count=c.get("revision_count", 0),
                axioms=[a for a in axioms if a.src == c["name"]],
            )
            for c in data.get("concepts", [])
        ]
        return QueryResult(
            query=data.get("query", question),
            concepts=concepts,
            axioms=axioms,
            confidence=float(data.get("confidence", 0.0)),
            domains=data.get("domains", []),
            has_knowledge=bool(data.get("has_knowledge", False)),
        )

    def recall_axioms(self, concept_or_query: str, top_k: int = 8) -> list[Axiom]:
        return self.query(concept_or_query, top_k=top_k).axioms

    def context_block(self, query: str, top_k: int = 6, max_axioms: int = 15) -> str:
        return self.query(query, top_k=top_k).context_block(max_axioms=max_axioms)

    def recall(self, query: str, top_k: int = 5) -> str:
        return self.context_block(query, top_k=top_k)

    def recall_relations(self, concept: str) -> list[dict]:
        return [
            {"type": a.rel, "target": a.tgt,
             "evidence_score": a.evidence, "why": a.why, "strength": a.strength}
            for a in self.query(concept).axioms
        ]

    # ── Write API ─────────────────────────────────────────────────────────────

    def learn(self, prompt: str, response: str, source: str = "conversation") -> None:
        try:
            self._client.post(
                f"{self._base}/api/brain/learn",
                json={"prompt": prompt, "response": response, "source": source},
            )
        except Exception:
            pass

    def add(
        self,
        src: str,
        rel_type: str,
        tgt: str,
        *,
        why: str = "",
        evidence_score: float = 0.6,
    ) -> None:
        try:
            self._client.post(
                f"{self._base}/api/brain/add",
                json={"src": src, "rel_type": rel_type, "tgt": tgt,
                      "why": why, "evidence_score": evidence_score},
            )
        except Exception:
            pass

    # ── Misc ──────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        try:
            return self._client.get(f"{self._base}/api/status").json()
        except Exception:
            return {}

    @property
    def field(self):
        raise AttributeError(
            "Direct .field access is not available in HTTP mode. "
            "Use brain.query() / brain.recall_axioms() instead."
        )


# ── Entry point ───────────────────────────────────────────────────────────────

def attach(
    db_path: str | Path | None = None,
    read_only: bool = False,
    *,
    port: int = 8765,
    prefer_http: bool = True,
    api_key: str | None = None,
    base_url: str | None = None,
) -> "NouseBrain | NouseBrainHTTP":
    """
    One-line entry point.  Auto-detects a running daemon and connects via HTTP
    so the caller never needs to worry about KuzuDB write-lock conflicts.

        brain = nouse.attach()               # auto: HTTP if daemon running
        brain = nouse.attach(prefer_http=False)  # always direct KuzuDB
        brain = nouse.attach(read_only=True) # eval / direct read
        brain = nouse.attach(api_key="nsk-xxx", base_url="https://api.nouse.ai")  # SaaS cloud
    """
    if api_key and base_url:
        return NouseBrainHTTP(base_url=base_url, api_key=api_key)
    if prefer_http:
        try:
            import httpx
            r = httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=1.0)
            if r.status_code == 200:
                return NouseBrainHTTP(base_url=f"http://127.0.0.1:{port}")
        except Exception:
            pass
    return NouseBrain(db_path=db_path, read_only=read_only)
