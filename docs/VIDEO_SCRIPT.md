# Nous — Video Script
### "The AI Memory That Makes Small Models Beat Big Ones"
**Format:** Text-to-video (AI narration)
**Duration:** ~90 seconds
**Tone:** Calm, technical confidence — no hype

---

## Scene 1 — Hook

**Visual:** Dark screen. Two numbers appear: `8B` vs `70B`

> What if a tiny 8-billion parameter model could consistently outperform a 70-billion parameter model? Not with better training. Not with fine-tuning. Just by giving it memory.

---

## Scene 2 — The Problem

**Visual:** Chat interface — user asks a question, AI gives a generic wrong answer

> Every time you start a new conversation with an AI, it forgets everything. Your projects, your domain, your terminology — gone. You repeat yourself constantly. And big models still get it wrong because they don't know *your* context.

---

## Scene 3 — Introduce Nous

**Visual:** Logo animation — "Nous" — Greek letters νοῦς fade in

> Meet Nous. Named after the Greek word for mind. Nous is a persistent, self-growing knowledge graph that attaches to any language model as a memory substrate. It works with OpenAI, Anthropic, Groq, Ollama — any model you already use.

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

> Three lines of code. Query your memory graph, get back a structured context block, inject it into any LLM call. You keep your existing setup. Nous just makes it smarter.

---

## Scene 7 — The Idea

**Visual:** Clean typography on dark background

> This is not about retrieval. It's about disambiguation. A small, precise memory signal redirects the model's existing knowledge onto the correct frame. We call this the **Intent Disambiguation Effect**.

---

## Scene 8 — Call to Action

**Visual:** GitHub URL + PyPI badge on screen

> Nous is open source, MIT licensed, and available today. Install with pip, run the benchmark yourself, or contribute your own domain question bank. The hypothesis is clear — small model plus Nous beats big model alone. Help us prove it at scale.

```
pip install nouse
github.com/base76-research-lab/Nous
```

---

*Script by Base76 Research Lab — Björn Wikström*
