---
title: "b76→Nous Migration"
subtitle: "From Research Framework to Cognitive Substrate"
author: "Björn Wikström"
date: "2026-04-02"
abstract: |
  This note documents the migration of the cognitive substrate from the b76 MCP-based research framework into Nous as a standalone Python package (v0.2.0). The migration was driven by b76's architectural limitation: as an MCP server, it could only operate through external tool calls, making autonomous daemon behavior, persistent storage, and background consolidation impossible. Nous (νοῦς) — Greek for intellect — was the natural home for a system that knows, not just processes.
---

# b76→Nous Migration

**From Research Framework to Cognitive Substrate**

Björn Wikström\
Base76 Research Lab

*2 April 2026*

---

## 1. Why b76 Was Not Sufficient

b76 was designed as an MCP (Model Context Protocol) server — a tool layer that LLMs could call into via structured tool calls (`kernel_propose_fact_tool`, `kernel_execute_self_update_tool`, etc.). This worked well for interactive sessions where a human or external LLM drove the conversation.

The limitation was architectural: b76 had no standalone existence. Without an external caller, it did nothing. There was no:

- **Daemon loop** — no way to run autonomous background processes
- **Persistence model** — no structured storage for concepts, relations, or evidence
- **Consolidation pipeline** — no mechanism to process episodes into knowledge outside of explicit tool calls
- **Self-regulation** — no internal state that could drive behavior independently

b76 was a fine tool. But a cognitive substrate is not a tool — it is the system that persists, learns, and directs. These are different functions, and they could not be performed within the MCP-only architecture.

## 2. What v0.2.0 Introduced

The migration created a standalone Python package with five core modules:

| Module | Role |
|--------|------|
| **FieldSurface** | Persistent concept graph with evidence-weighted relations |
| **NodeInbox** | Episodic input buffer for raw observations before consolidation |
| **Brain** | In-memory graph engine with traversal, resonance, and bisociation |
| **Ghost Q** | Weak-node interrogation — identifies knowledge gaps and generates LLM queries |
| **LimbicState** | Arousal and resource signals for cognitive state classification |
| **NightRun** | Slow-wave consolidation pipeline (hippocampal replay analogy) |

The key architectural decision: **the LLM serves the substrate, not the other way around.** In b76, the LLM called the kernel. In Nous, the substrate calls the LLM — to fill gaps, resolve contradictions, and expand domains.

## 3. The Philosophical Motivation

Nous (νοῦς) is Greek for intellect — the faculty that grasps first principles, not through reasoning from premises, but directly. The naming was deliberate: this system does not merely process language (a larynx function); it represents knowledge and monitors its own epistemic state.

The b76 kernel retains its role as an MCP integration layer — the point of contact for external LLMs and tools. But the cognitive substrate now exists independently, capable of autonomous operation between external interactions.

## 4. Architecture

```
┌─────────────────────────────────────────────┐
│              b76 kernel (MCP)                │
│   External LLM/tool integration layer        │
│   kernel_propose_fact, kernel_reflect,       │
│   kernel_link_concepts, ...                  │
└──────────────────┬──────────────────────────┘
                   │ episodes
                   ▼
┌─────────────────────────────────────────────┐
│           Nous (νοῦς) v0.2.0                 │
│                                              │
│  ┌──────────┐   ┌───────────┐   ┌────────┐  │
│  │NodeInbox │──▶│NightRun   │──▶│Brain   │  │
│  │(episodes)│   │(consolid.)│   │(graph) │  │
│  └──────────┘   └───────────┘   └────────┘  │
│       │              │              │        │
│       ▼              ▼              ▼        │
│  ┌──────────────────────────────────────┐   │
│  │         FieldSurface (persist.)      │   │
│  │   concept graph + evidence scores    │   │
│  └──────────────────────────────────────┘   │
│       │              │                        │
│       ▼              ▼                        │
│  ┌──────────┐   ┌───────────┐                 │
│  │Ghost Q   │   │LimbicState│                 │
│  │(gaps)    │   │(arousal)  │                 │
│  └──────────┘   └───────────┘                 │
└─────────────────────────────────────────────┘
```

## 5. What Remained in b76 vs. What Moved

| Stayed in b76 | Moved to Nous |
|---|---|
| MCP server protocol | FieldSurface, Brain, Ghost Q |
| Tool call handlers | NodeInbox, NightRun consolidation |
| External API surface | LimbicState, evidence scoring |
| Session management | Concept/relation persistence |
| — | Autonomous daemon loop |

b76 remains the integration point. Nous is the substrate that integrates with.

*Commit: f6f4305 — feat: nouse v0.2.0 — full cognitive substrate framework migrated from b76*