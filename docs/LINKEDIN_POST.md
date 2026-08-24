🧠 Nous is a research system for epistemic memory in long-running AI agents.

The current evidence is deliberately modest: a 40-question TruthfulQA pilot
did not establish an improvement over a bare model, and its judge records were
incomplete. That result is being used to improve the method, not hidden.

The research question is whether explicit evidence, uncertainty and
contradiction state can improve **disambiguation**.

When a model doesn't know *your* domain, it generates fluent, confident answers in the wrong frame. A small, structured memory signal fixes that — redirecting the model's existing knowledge onto the correct frame.

We call this the **Intent Disambiguation Effect**.

---

Today I'm releasing **Nous** (νοῦς — Greek for *mind*) as open source.

Nous is a persistent, self-growing knowledge graph that attaches to any LLM as a domain memory substrate.

→ It runs a background daemon that watches your files, conversations, and research
→ Extracts typed, weighted relations between concepts (not chunks — *relations*)
→ Learns continuously via Hebbian plasticity — no retraining, no gradient descent
→ Injects a structured context block into any LLM prompt at query time

**It works with any model. Any provider.**

```
pip install nouse

brain = nouse.attach()
context = brain.query("your question").context_block()
# inject into OpenAI, Anthropic, Groq, Ollama — whatever you use
```

---

The hypothesis is simple:

> **small model + Nous[domain] > large model without Nous**

We have evidence. We need more domains, more models, more contributors to stress-test it.

If you work at **@OpenAI**, **@Anthropic**, **@Google DeepMind**, **@Meta AI**, **@Mistral**, **@Groq**, **@Cerebras**, **@Ollama**, **@Hugging Face**, **@Cohere**, or **@NVIDIA** — I'd love to hear what you think. This either changes how you think about memory in LLM pipelines, or it doesn't. Either way, let's talk.

📦 pip install nouse
🔗 github.com/base76-research-lab/Nous
📖 Full benchmark + methodology in the repo

#AI #LLM #OpenSource #MachineLearning #KnowledgeGraph #RAG #LocalAI #Ollama #ArtificialIntelligence #Python
