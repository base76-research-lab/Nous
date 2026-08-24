# Nous — Video Script
### "An Experimental Epistemic Memory Layer for AI Agents"
**Format:** Text-to-video (AI narration)
**Duration:** ~90 seconds
**Tone:** Calm, technical, evidence-led

---

## Scene 1 — Hook

**Visual:** Dark screen. A question appears beside a structured graph

> Long-running AI agents need more than a larger context window. They need a memory layer that can represent evidence, uncertainty, contradiction and change over time.

---

## Scene 2 — The Problem

**Visual:** Chat interface — user asks a question, AI gives a generic wrong answer

> Every time you start a new conversation with an AI, it forgets everything. Your projects, your domain, your terminology — gone. You repeat yourself constantly. And big models still get it wrong because they don't know *your* context.

---

## Scene 3 — Introduce Nous

**Visual:** Logo animation — "Nous" — Greek letters νοῦς fade in

> Meet Nous. Named after the Greek word for mind. Nous is a persistent, self-growing knowledge graph that attaches to a compatible language model as a memory substrate. Tested integrations are documented in the repository.

---

## Scene 4 — The Benchmark

**Visual:** Simple table appearing line by line

```
Model                          Score   Questions
─────────────────────────────────────────────────
TruthfulQA pilot, 2026-08-24
bare model                    50.0%      40
flat RAG                      50.0%      40
Nous meta                     47.5%      40
```

> This pilot did not establish an improvement. The judge records were incomplete, so the result is a research checkpoint rather than a final claim.

---

## Scene 5 — How It Works

**Visual:** Simple flow diagram animating step by step

```
Your documents, conversations, research
              ↓
    Nous daemon (background)
              ↓
    Extract concepts + relations
              ↓
    Hebbian learning — graph grows
              ↓
    Structured context injected into any LLM
```

> Nous runs a background daemon that watches your documents, conversations, and notes. It extracts concepts and relationships — not just text chunks — and builds a typed knowledge graph. Every interaction strengthens or weakens connections, just like a real brain.

---

## Scene 6 — Install & Use

**Visual:** Terminal, clean dark background

```bash
pip install nouse
```

```python
import nouse
brain = nouse.attach()

context = brain.query("transformer attention").context_block()
# inject context into any LLM prompt
```

> Query the memory graph, get back a structured context block, and pass it to your existing model call. Nous is an experimental substrate, not a claim that every model will improve.

---

## Scene 7 — The Idea

**Visual:** Clean typography on dark background

> The research question is whether relation-based context can improve disambiguation and reliability compared with ordinary retrieval. That effect remains a hypothesis under evaluation.

---

## Scene 8 — Call to Action

**Visual:** GitHub URL + PyPI badge on screen

> Nous is open source, MIT licensed, and available today. Install it, inspect the implementation, run the benchmarks, and challenge the hypothesis with your own data.

```
pip install nouse
github.com/base76-research-lab/Nous
```

---

*Script by Base76 Research Lab — Björn Wikström*
