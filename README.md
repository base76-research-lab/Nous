# Nouse

![Nouse](IMG/Nouse.png)

**Structured memory for LLM agents that knows not only what it knows, but how confidently it knows it and where knowledge runs out.**

Epistemic grounding for any model.

[![PyPI](https://img.shields.io/pypi/v/nouse)](https://pypi.org/project/nouse/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Benchmark](https://img.shields.io/badge/benchmark-96%25_vs_46%25-brightgreen)](eval/RESULTS.md)

[Quick Start](#quick-start) · [Why It Matters](#why-it-matters) · [What You Get](#what-you-get) · [Benchmark](#run-the-benchmark-yourself)

![Nouse demo](IMG/demo.gif)

Repo social preview asset: [IMG/nouse-social-preview.svg](IMG/nouse-social-preview.svg)

---

## Try NoUse In 60 Seconds

```bash
pip install nouse
python - <<'PY'
import nouse

brain = nouse.attach()
result = brain.query("What does this project know about epistemic grounding?")

print(result.context_block())
print("confidence:", round(result.confidence, 2))
PY
```

If NoUse already knows something relevant, you get back a grounded context block with validated relations, uncertainty, and explicit boundaries instead of a generic answer blob.

If that output feels more useful than plain chat history or chunk retrieval, then the project is doing its job.

---

## Why It Matters

NoUse gives an LLM agent a persistent epistemic memory layer.

- It stores relations, not just retrieved chunks.
- It carries confidence, rationale, and uncertainty with the memory itself.
- It makes the boundary between known, probable, and unknown visible to the model.

That changes agent behavior in the place that actually matters: when a model is close to hallucinating but still sounds fluent.

## The Result That Triggered This

```text
Model                               Score   Questions
─────────────────────────────────────────────────────
llama3.1-8b  (no memory)            46%     60
llama-3.3-70b  (no memory)          47%     60
llama3.1-8b  + Nouse memory  →      96%     60
```

**An 8B model with Nouse outperforms a 70B model without it.**

The effect is not about retrieval. It is about *epistemic grounding* — a small, precise knowledge signal
redirects the model's existing priors onto the correct frame, with confidence and evidence attached.
We call this the **Intent Disambiguation Effect**.

LLMs are stateless formal systems: they process symbol strings without epistemic commitment.
They cannot distinguish what they know from what they hallucinate. Nouse is the missing layer:
it gives any LLM a persistent, structured account of what is known, why, with what confidence,
and — critically — what is *not* yet known.

→ Full benchmark: [eval/RESULTS.md](eval/RESULTS.md)

---

## What You Get

| Capability | What it does |
| --- | --- |
| Structured memory | Stores typed relations between concepts instead of plain text chunks |
| Confidence-aware retrieval | Returns what is known, with evidence and uncertainty attached |
| Gap awareness | Surfaces where knowledge ends instead of bluffing through it |
| Continuous learning | Strengthens or weakens graph paths over time via Hebbian plasticity |
| Local-first runtime | Runs as a local graph and daemon, then injects context into any LLM |

---

## What Nouse is

Nouse (νοῦς, Gk. *mind*) is a **persistent, self-growing epistemic substrate** that attaches to any LLM.

It is informed by brain-inspired plasticity, cognitive research, and the practical failure modes of LLM memory.

```text
Your documents, conversations, research
           ↓
    Nouse knowledge graph
    (KuzuDB + Hebbian learning + evidence scoring)
           ↓
    brain.query("your question")
           ↓
    Structured context injected into any LLM prompt:
      — what is known (relations + confidence)
      — why it is known (evidence chain)
      — what is NOT known (gap map from TDA)
```

It is **not** a RAG system. RAG retrieves chunks. Nouse extracts *relations* — typed, weighted,
evidence-scored connections between concepts — and injects a compact, structured context block.

It is **not** just a memory system. Memory stores and retrieves. Nouse maintains an epistemic
account: every relation carries a trust tier (hypothesis / indication / validated), a rationale,
and a contradiction flag. The system knows the difference between what it has evidence for
and what it is guessing.

It **learns continuously**. Every interaction strengthens or weakens connections (Hebbian plasticity).
There is no retraining. No gradient descent. The graph grows — and the gaps become visible.

---

## Why It Feels Different From RAG

| System | Main unit | Knows confidence | Knows what is missing | Learns structurally over time |
| --- | --- | ---: | ---: | ---: |
| Basic RAG | text chunk | No | No | No |
| Vector memory | embedding | Partial | No | No |
| NoUse | typed relation + evidence | Yes | Yes | Yes |

NoUse is not trying to replace the model. It gives the model a brain-like memory substrate it can query before speaking.

---

## Quick start

```bash
pip install nouse
```

```python
import nouse

# Auto-detects the local daemon if it is running.
# Otherwise falls back to direct local graph access.
brain = nouse.attach()

result = brain.query("transformer attention mechanism")

print(result.context_block())
print(result.confidence)
print(result.strong_axioms())
```

If the daemon is already running, `attach()` talks to it over HTTP instead of opening KuzuDB directly. That means the same quickstart works whether the user is in local-only mode or daemon mode.

Works with any provider — OpenAI, Anthropic, Groq, Cerebras, Ollama:

```python
# You handle the LLM call. Nouse handles the memory.
context = brain.query(user_question).context_block()
response = openai.chat(messages=[
    {"role": "system", "content": context},
    {"role": "user",   "content": user_question},
])
```

## Use With OpenAI, Anthropic, Or Ollama

### OpenAI

```python
from openai import OpenAI
import nouse

client = OpenAI()
brain = nouse.attach()

question = "How does residual attention affect token relevance?"
context = brain.query(question).context_block()

response = client.chat.completions.create(
       model="gpt-4.1-mini",
       messages=[
              {"role": "system", "content": context},
              {"role": "user", "content": question},
       ],
)

print(response.choices[0].message.content)
```

### Anthropic

```python
from anthropic import Anthropic
import nouse

client = Anthropic()
brain = nouse.attach()

question = "What does this repo know about topological plasticity?"
context = brain.query(question).context_block()

response = client.messages.create(
       model="claude-3-7-sonnet-latest",
       max_tokens=800,
       system=context,
       messages=[
              {"role": "user", "content": question},
       ],
)

print(response.content[0].text)
```

### Ollama

```python
import ollama
import nouse

brain = nouse.attach()

question = "Summarize what is known about epistemic grounding."
context = brain.query(question).context_block()

response = ollama.chat(
       model="qwen3.5:latest",
       messages=[
              {"role": "system", "content": context},
              {"role": "user", "content": question},
       ],
)

print(response["message"]["content"])
```

The pattern is always the same: `brain.query(...)` first, provider call second.

---

## Managed NoUse

NoUse is local-first today. A natural next step is a managed cloud brain:

```python
brain = nouse.attach(api_key="nouse_sk_...")
```

That would give users a hosted NoUse brain with larger managed memory graphs, shared project memory across agents and teams, and less local setup.

For individual users, it is a simpler paid upgrade. For researchers, it is persistent shared memory across runs and collaborators. For larger companies, it is a path to API access, team memory, and managed deployment.

---

## What A Grounded Answer Looks Like

When you query NoUse, the model does not just get a blob of context. It gets an epistemic frame:

```text
[Nouse memory]
• transformer attention: mechanism for routing token influence across context
       claim: attention modulates token relevance based on learned relational patterns

Validated relations:
       transformer —[uses]→ attention  [ev=0.92]
       attention —[modulates]→ token relevance  [ev=0.81]

Uncertain / under review:
       attention —[is_equivalent_to]→ memory routing  [ev=0.41] ⚑
```

That is the real product surface: not storage, but a more honest and better-calibrated answer path.

---

## Run the benchmark yourself

```bash
git clone https://github.com/base76-research-lab/NoUse
cd NoUse
pip install -e .

# Generate questions from your own graph
python eval/generate_questions.py --n 60

# Run benchmark (requires Cerebras or Groq API key, or use Ollama)
python eval/run_eval.py \
  --small cerebras/llama3.1-8b \
  --large groq/llama-3.3-70b-versatile \
  --n 60 --no-judge
```

The current benchmark is domain-specific and intentionally small. Its purpose is to test whether a grounded memory signal can redirect the model onto the right frame, not to claim a universal leaderboard win.

---

## How the graph grows

```text
Read a document / have a conversation
           ↓
    nouse daemon (background)
           ↓
    DeepDive: extract concepts + relations
           ↓
    Hebbian update: strengthen confirmed paths
           ↓
    NightRun: consolidate, prune weak edges
           ↓
    Ghost Q (nightly): ask LLM about weak nodes → enrich graph
```

The daemon runs as a systemd service. It watches your files, chat history,
browser bookmarks — anything you configure. You never manually curate the graph.

---

## Good Fits

- Coding agents that need stable project memory across sessions
- Research copilots that must preserve terminology, evidence, and uncertainty
- Domain-specific assistants where bluffing is worse than saying "unknown"
- Local-first AI workflows where you want observability instead of hidden memory state

---

## Architecture

```text
nouse/
├── inject.py          # Public API: attach(), NouseBrain, Axiom, QueryResult
├── field/
│   └── surface.py     # KuzuDB graph interface
├── daemon/
│   ├── main.py        # Autonomous learning loop
│   ├── nightrun.py    # Nightly consolidation (9 phases)
│   ├── node_deepdive.py  # 5-step concept extraction
│   └── ghost_q.py     # LLM-driven graph enrichment
└── search/
    └── escalator.py   # 3-level knowledge escalation
```

---

## The hypothesis (work in progress)

```text
small model + Nouse[domain]  >  large model without Nouse
```

We have evidence for this in our benchmark. The next step is to test across
more domains, more models, and with an LLM judge instead of keyword scoring.

Contributions welcome — especially domain-specific question banks.

---

## Install & run daemon

```bash
pip install -e ".[dev]"

# Start the learning daemon
nouse daemon start

# Interactive REPL with memory
nouse run

# Check graph stats
nouse status
```

Requires Python 3.11+. Graph stored in `~/.local/share/nouse/field.kuzu`.

---

## License

MIT — Björn Wikström / Base76 Research Lab

---

## Contact

- 𝕏 / Twitter: [@Q_for_qualia](https://x.com/Q_for_qualia)
- LinkedIn: [bjornshomelab](https://www.linkedin.com/in/bjornshomelab/)
- Email: [bjorn@base76research.com](mailto:bjorn@base76research.com)
- Issues: [github.com/base76-research-lab/NoUse/issues](https://github.com/base76-research-lab/NoUse/issues)
