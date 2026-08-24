# NoUse Examples

Runnable examples showing how to use NoUse.

| Example | Description | Requirements |
|---------|-------------|-------------|
| [basic_query.py](basic_query.py) | Query the knowledge graph | `pip install nouse` |
| [grounded_memory.py](grounded_memory.py) | Deterministic local path: relations, source/target queries, context, contradiction check | `pip install -e .` |
| [with_openai.py](with_openai.py) | Use with OpenAI models | `pip install nouse openai` |
| [with_ollama.py](with_ollama.py) | Use with local Ollama models | `pip install nouse ollama` |
| [ingest_document.py](ingest_document.py) | Add knowledge from text | NoUse daemon running |

## Quick Start

```bash
pip install nouse
python basic_query.py
```

For a deterministic local demonstration with no model, API key, daemon, or
network prerequisite:

```bash
pip install -e .
python examples/grounded_memory.py
```

For daemon-dependent examples, start the daemon first:

```bash
nouse daemon start
```
