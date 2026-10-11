from __future__ import annotations

import os
from typing import Sequence

import httpx

from nouse.config.env import load_env_files


class OllamaEmbedder:
    def __init__(self, model: str | None = None, host: str | None = None, timeout_s: float = 120.0):
        try:
            load_env_files()
        except OSError:
            # T.ex. tillfälligt I/O-fel på extern disk med .env
            pass
        self.model = (model or os.getenv("NOUSE_EMBED_MODEL") or "qwen3-embedding:8b").strip()
        self.host = (host or os.getenv("NOUSE_OLLAMA_HOST") or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        self.timeout_s = timeout_s

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        clean = [t.strip() for t in texts if t and t.strip()]
        if not clean:
            return []

        url = f"{self.host}/api/embed"
        payload = {"model": self.model, "input": clean}
        with httpx.Client(timeout=self.timeout_s) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()

        embeddings = data.get("embeddings") or []
        out: list[list[float]] = []
        for vec in embeddings:
            if isinstance(vec, list) and vec:
                out.append([float(x) for x in vec])

        if len(out) != len(clean):
            raise RuntimeError(
                f"Embedding count mismatch: input={len(clean)} output={len(out)}"
            )
        return out
