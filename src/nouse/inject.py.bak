"""
nouse.inject — One-line cognitive substrate for any LLM.

The simplest possible entry point:

    brain = nouse.attach()
    enriched_prompt = brain.recall_context(user_input)
    brain.learn(user_input, llm_response)

Supports hooks, middleware, and direct API wrapping.
"""
from __future__ import annotations
from pathlib import Path
from typing import Callable, Any


class NouseBrain:
    """
    Lightweight facade over FieldSurface + LLM autodiscovery.
    Designed to be injected into any LLM pipeline with minimal friction.
    """
    def __init__(self, db_path: str | Path | None = None):
        from nouse.field.surface import FieldSurface
        self._field = FieldSurface(db_path=db_path)
        self._input_hooks: list[Callable] = []
        self._output_hooks: list[Callable] = []

    def recall(self, query: str, top_k: int = 5) -> str:
        """Retrieve relevant context from the knowledge graph."""
        results = self._field.node_context_for_query(query, limit=top_k)
        if not results:
            return ""
        lines = [f"- {r.get('name')}: {r.get('context', '')[:200]}" for r in results]
        return "Relevant context from memory:\n" + "\n".join(lines)

    def learn(self, prompt: str, response: str, source: str = "conversation") -> None:
        """Extract and store knowledge from a prompt/response pair."""
        import asyncio
        from nouse.daemon.extractor import extract_relations
        asyncio.run(extract_relations(prompt + "\n" + response, 
                                      self._field, source_tag=source))

    def on_input(self, fn: Callable) -> Callable:
        """Decorator: enrich prompt before it reaches the LLM."""
        self._input_hooks.append(fn)
        return fn

    def on_output(self, fn: Callable) -> Callable:
        """Decorator: process response after LLM returns."""
        self._output_hooks.append(fn)
        return fn

    @property
    def field(self):
        """Direct access to the KuzuDB FieldSurface."""
        return self._field


def attach(db_path: str | Path | None = None) -> NouseBrain:
    """
    One-line entry point. Opens (or creates) the nouse knowledge graph.
    
        brain = nouse.attach()
    """
    return NouseBrain(db_path=db_path)
