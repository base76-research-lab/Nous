<p align="center">
  <img src="IMG/nous-header.png" alt="Nous" width="100%">
</p>

<p align="center">
  <a href="https://pypi.org/project/nouse/"><img src="https://img.shields.io/pypi/v/nouse" alt="PyPI"></a>
  <a href="https://github.com/base76-research-lab/Nous/actions/workflows/tests.yml"><img src="https://github.com/base76-research-lab/Nous/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.13+-blue.svg" alt="Python 3.13+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>

---

# Nous

Nous is a small research project asking one question:

> Does a language model become more reliable if, before it speaks, it can consult
> a persistent, structured record of what is known — typed relations with graded
> confidence, tracked contradictions, and explicit boundaries around what is not
> known?

Current answer: **unknown.** There is a working prototype (SQLite WAL + NetworkX,
Hebbian edge weighting, TDA-based gap detection) and a results ledger. As of
today, no complete, independently scored run demonstrates a reliability
improvement over the bare model — see
[eval/RESULTS_INDEX.md](eval/RESULTS_INDEX.md).

Everything else in this repository — the plasticity dynamics, the daemon, the
benchmarks under construction — exists to test that question. This is a
research project, not a product. It becomes a product if and when the research
holds up.

The theoretical framing (language models as the expression channel for
intelligence, not intelligence itself) is argued at length in Wikström (2026),
cited in [Position & prior work](#position--prior-work) below.

---

## Evidence status

The repository contains working components and reproducible unit tests, but
does **not yet establish a general accuracy gain** over a bare language model.

| Run | Status | Model | Summary |
| --- | --- | --- | --- |
| `truthfulqa_run2_20260824` | exploratory, incomplete judge records | NVIDIA Nemotron 3.5 Lightning | MC1: bare 50.0%, RAG 50.0%, Nous-meta 47.5% |
| `longmemeval_20260824_000702` | valid negative result for this task shape | GPT-OSS 120B via Groq | bare 4.2%, Nous 0.0% — the adapter's relation vocabulary represents thematic/conceptual relations, not atomic personal facts; this run bounds the task shape rather than showing a regression to chase |
| `run_20260403_094211` | historical pilot, incomplete provenance | Cerebras Llama 3.1 8B / Groq Llama 3.3 70B | 46.1% bare, 96.1% Nous, 46.7% larger baseline — no immutable manifest, dataset hash, or independent scorer behind these numbers; not treated as evidence |

Full ledger, reproduction requirements, and the rule that governs it (no public
numeric claim without a run ID in this table): [eval/RESULTS_INDEX.md](eval/RESULTS_INDEX.md).

The `confidence` value returned by a query is a mean over graph evidence, not a
calibrated probability — see [docs/EVIDENCE_MODEL.md](docs/EVIDENCE_MODEL.md).

---

## Install & minimal demo

Deterministic local path, no daemon, no network dependency once installed:

```bash
git clone https://github.com/base76-research-lab/Nous
cd Nous
pip install -e .
python examples/grounded_memory.py
```

This runs explicit relation queries against a local graph and prints context
blocks, confidence, and contradiction checks — the same primitives every
benchmark run in this repo uses.

For the daemon-backed path (background learning loop, `attach()` over HTTP):

```bash
pip install nouse
nouse daemon start
nouse run       # interactive REPL with memory
nouse status    # graph stats
```

Requires Python 3.13+. Graph stored in `~/.local/share/nouse/`.

---

## System overview

```text
Your documents, conversations, research
           ↓
    Nous knowledge graph
    (SQLite WAL + NetworkX + Hebbian learning + evidence scoring)
           ↓
    brain.query("your question")
           ↓
    Structured context injected into any LLM prompt:
      — what is known (relations + confidence)
      — why it is known (evidence chain)
      — what is NOT known (gap map from TDA)
```

```python
import nouse

brain = nouse.attach()  # daemon if running, direct graph access otherwise
result = brain.query("transformer attention mechanism")

print(result.context_block())
print(result.confidence)
```

`brain.query(...)` first, provider call second — the pattern is the same for
OpenAI, Anthropic, Groq, and Ollama. One worked example, `examples/with_openai.py`;
`examples/`, `examples/with_ollama.py`, `examples/groq_example.py` cover the rest.

Implemented mechanisms, each additive to the base Hebbian graph — none touch
existing ranking, pruning, or dormancy logic:

- **Relation-based, not chunk-based.** Extracts typed, evidence-scored relations
  between concepts rather than retrieving text chunks. Every relation carries a
  trust tier (hypothesis / indication / validated), a rationale, and a
  contradiction flag.
- **Hebbian plasticity.** Every interaction strengthens or weakens graph paths.
  No retraining, no gradient descent.
- **Multi-timescale relation strength.** A fast-decaying strength signal
  (~6h half-life) layered on top of the long-term Hebbian weight — recent
  relevance and durable structure tracked separately.
- **Energy-gated cognition.** A finite, replenishing energy pool bounds how much
  the bisociation engine (cross-domain connection search) can do per cycle.
- **Predictive-surprise tasking.** A rising-edge surprise signal crossing a
  threshold spawns a human-in-the-loop research task about what surprised the
  system and why.
- **Personalization (`user_model`).** A scoped, sensitive subgraph tracks how a
  specific user communicates, learns, and works — seeded from structured
  parsing of their own notes (not free-form LLM extraction), kept separate from
  general recall.

```text
nouse/
├── inject.py          # Public API: attach(), NouseBrain, Axiom, QueryResult
├── field/surface.py    # SQLite WAL + NetworkX graph interface
├── daemon/
│   ├── main.py          # Autonomous learning loop
│   ├── nightrun.py      # Nightly consolidation
│   └── node_deepdive.py # Concept extraction
├── orchestrator/         # Global Workspace arbitration (contract built; real
│                          # valuation policy still legacy WTA behind it)
├── limbic/              # Neuromodulation signals
├── memory/              # Episodic + procedural + semantic memory
├── metacognition/       # Self-monitoring and confidence calibration
└── search/escalator.py  # Knowledge escalation
```

---

## Reproducing runs

```bash
python eval/generate_questions.py --n 60
python eval/run_eval.py --small cerebras/llama3.1-8b --large groq/llama-3.3-70b-versatile --n 60 --no-judge
```

`run_eval.py` prints a results table but does not write a claim anywhere. A run
becomes citable only after a human reviews it and adds a line to
[eval/RESULTS_INDEX.md](eval/RESULTS_INDEX.md) recording: commit SHA and package
version, dataset identifier and hash, model/provider/prompts/sampling/seed,
isolated graph state, raw model and judge responses, scorer version, and
invalid-record count.

Why standard LLM benchmarks (MMLU, ARC, HumanEval) don't directly apply: they
measure output quality at a single moment. Nous is not a language model — it's
a substrate that changes structure over time. FNC-Bench (`eval/fnc_bench/`) is
built around epistemic honesty, contradiction resistance, and confidence
calibration instead. No established benchmark measures longitudinal epistemic
state directly; FNC-Bench and TruthfulQA are partial proxies, not a complete
answer.

---

## Reports, figures, log

- [`docs/log/`](docs/log/) — a dated research log, five lines per entry: what
  was tried, what happened, what's next.
- [`docs/reports/`](docs/reports/) — numbered technical reports (1–3 pages,
  dated, tied to a commit SHA, status draft/stable/superseded) once a result
  is substantial enough to write up.
- [`eval/results/`](eval/results/) — raw run outputs; `failed/` for runs that
  hit an infrastructure problem, `archive/` for superseded artifacts.

---

## Position & prior work

- Wikström, B. (2026). **The Larynx Problem: Why Large Language Models Are Not
  Artificial Intelligence.** [Zenodo](https://zenodo.org/records/19413234) ·
  [PhilPapers](https://philpapers.org/rec/WIKTLP) — argues that LLMs model the
  expression channel for intelligence (language), not intelligence itself, and
  that epistemic grounding via structured, plastic knowledge graphs is
  necessary.
- Quattrociocchi, W. et al. (2025). **Epistemia: Structural Fault Lines in
  Generative AI.** [arXiv:2512.19466](https://arxiv.org/abs/2512.19466) —
  introduces "epistemia" to describe the structural gap where linguistic
  credibility substitutes for actual epistemic evaluation, and identifies
  seven epistemological fault lines between human and machine judgment.

Nous differs from chunk-based RAG and conversation-memory systems (MemGPT/Letta,
Mem0, key-value memory) mainly in unit and epistemics: it stores typed relations
with graded confidence and explicit unknowns, not retrieved chunks or opaque
memory objects. That difference is a design choice, not a demonstrated result —
see [Evidence status](#evidence-status).

---

## Contributing

Domain-specific question banks for the benchmark are the most valuable
contribution right now. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Citation · License · Contact

If you use this software, see [CITATION.cff](CITATION.cff).

MIT — see [LICENSE](LICENSE).

Björn Wikström / [Base76 Research Lab](https://github.com/base76-research-lab) —
[bjorn@base76research.com](mailto:bjorn@base76research.com) ·
[GitHub Issues](https://github.com/base76-research-lab/Nous/issues) ·
[Discussions](https://github.com/base76-research-lab/Nous/discussions)

For security vulnerabilities, see [SECURITY.md](SECURITY.md).
