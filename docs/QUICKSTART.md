# NoUse — 5-minute Quickstart

> **NoUse** gives an LLM agent structured memory that knows what is known, how confidently it is known, and where knowledge ends.

## What you will do in 5 minutes

1. Install the package.
2. Attach to a local NoUse brain.
3. Query it for grounded context.
4. Inject that context into the model you already use.

## Install

```bash
pip install nouse
```

## Fastest path

```python
import nouse

brain = nouse.attach()
result = brain.query("transformer attention mechanism")

print(result.context_block())
print(result.confidence)
```

`attach()` auto-detects the local daemon if it is already running. If not, it falls back to direct local graph access.

## What you get back

`brain.query(...)` returns a structured result, not just raw text.

```text
[Nouse memory]
• transformer attention: mechanism for routing token influence across context

Validated relations:
  transformer —[uses]→ attention  [ev=0.92]
  attention —[modulates]→ token relevance  [ev=0.81]

Uncertain / under review:
  attention —[is_equivalent_to]→ memory routing  [ev=0.41] ⚑
```

That is the product surface: a model gets a grounded epistemic frame before it answers.

## Use it with your provider

### OpenAI

```python
from openai import OpenAI
import nouse

client = OpenAI()
brain = nouse.attach()

question = "How does attention affect token relevance?"
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

question = "What do we know about topological plasticity?"
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

## If you want the daemon running

```bash
# Start the learning daemon
nouse-brain

# Optional: expose the HTTP API used by attach() auto-detection
nouse-server

# Optional: expose NoUse as an MCP server
nouse-mcp
```

## If you want the future cloud path

The local-first path is the default. The planned upgrade path is a managed cloud brain:

```python
brain = nouse.attach(api_key="nouse_sk_...")
```

That is the direction for users who want larger hosted memory graphs, shared project memory, or less local setup.

## Core idea in one diagram

```text
your docs / chats / research
            ↓
      NoUse graph memory
            ↓
    confidence + relations + gaps
            ↓
      injected into any LLM
```

## When to use NoUse

- When a coding or research agent needs persistent project memory
- When confidence and uncertainty matter as much as the answer itself
- When you want the system to expose what is unknown instead of bluffing
- When you want local-first memory instead of hidden hosted state

## If you want the lower-level brain kernel

NoUse also exposes a deeper kernel API with residual streams, crystallization, and explicit field events. That path is still available, but it is not the fastest way to get value from the package.

See the full docs and source for the lower-level kernel, daemon, and graph internals.
