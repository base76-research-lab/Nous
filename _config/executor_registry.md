# Executor registry

An `AGENT.md`'s `executor` field is one of two shapes:

1. **A bare model ref**, passed as-is to
   `nouse.ollama_client.client.AsyncOllama().chat.completions.create(model=...)`.
   The client itself decides local vs. cloud routing via `_split_provider_model_ref`:
   - `gemma4:e2b` (no `/`) — plain local Ollama call.
   - `nvidia/nemotron-3.5-lightning-30b-a3b`, `groq/<model>`,
     `openrouter/<model>`, `cerebras/<model>` — cloud, via
     `_KNOWN_CLOUD_PROVIDERS`. Adding a new cloud provider means adding it
     there (code change), not here.
2. **`relay:claude` / `relay:codex`** — a sentinel, not a model ref. Never
   passed to `ollama_client`. Opens a `nouse.session.relay` session and
   hands off to an external orchestrator instead of calling a model
   directly.
