# Nous ROADMAP

> Single source of truth for project state. Next LLM session: read THIS file + latest handoff, then start working.
> Updated: 2026-04-17

---

## Current Focus

**Conductor-arkitektur: Claude = dirigent, Ollama/Paperclip = workers**

Homeostasis implementerad (auto-seeds underrepresenterade hjärnregioner varje 6:e cykel).
Paperclip installerat som orchestration-lager — CTO + ResearchScientist kör nu via Ollama
(kimi-k2.5:cloud, 0 Claude-tokens). CEO kör Haiku.
FNC-Bench GDP physics-dataset genererat (20 frågor via dispatch.py).
Nästa: Nous goal_registry → Paperclip issues bridge, LPI-protokoll, daemon-omstart.

Daemon kör fulla kognitiva cykler med D3 goal-directed execution. Brain atlas avslöjar "slagsida": 88% av koncept i Parietal+Brainstem, <1% i Frontal/Hippocampus/Amygdala. Sweet spot calibration visar alla 200 nervbanor har k=1 mot k_min=8.6. Kamera (Occipital Lobe) + llava:7b fungerar. Speech-modul (Temporal+Frontal) byggd men TTS/STT inte aktiverad.

D3 verified working in main loop: goal_weights applied to 39 nodes, self-knowledge logging active, curiosity directed toward bridge domains (philosophy of mind prio=0.93).

Next: activate camera in daemon, use brain atlas for D3 goal prioritization (underrepresented regions), spatial embedding for signal decay.

---

## System Health

| Check | Status |
|-------|--------|
| Daemon | active (running), D3 goal-directed execution verified in main loop |
| Percolation module | `daemon/percolation.py` — density + bridge + sweet spot + nervbana axion density |
| Brain atlas | `daemon/brain_atlas.py` — 8 regions, slagsida diagnostic, domain → region classifier |
| Bisociation readiness | 6.0% (35,428 concepts, 4,648 domains, 36,887 edge deficit) |
| Sweet spot | 0/200 nervbanor i sweet zone, alla i isolerad (k=1 vs k_min=8.6) |
| Camera | `daemon/camera.py` — /dev/video0 + llava:7b, working |
| Speech | `daemon/speech.py` — STT (Whisper) + TTS (Piper/edge-tts), built but not enabled |
| Vision | `daemon/vision.py` — llava → Gemini → heuristic, JSON parsing fixed |
| PyPI | v0.4.0 published |
| Core imports | brain, surface, inject, limbic, mcp — OK |
| Extract model | `gemma4:e2b` (primary), `minimax-m2.7:cloud`/`glm-5.1:cloud` (fallback) |
| Test suite | 8 collection errors (web modules) |
| Git remote | github.com/base76-research-lab/Nous.git |
| Total commits | 90 |

### Fixed: `nouse.persona` import

Created `src/nouse/persona.py` stub with sensible defaults:
- `persona_identity_seed()` returns dict (name, greeting, mission, personality, values, boundaries)
- `assistant_entity_name()` returns "Nous"
- `agent_identity_policy()`, `assistant_greeting()`, `persona_prompt_fragment()` all implemented
- All values configurable via `NOUSE_*` environment variables

---

## P1-P5 Roadmap (cognitive self-regulation)

- [x] P1 Contradiction Detection (commit 8e30315)
- [x] P2 Evidence Accumulation (commit 8e30315)
- [x] P3 Causal Reflection — reflection-to-policy bridge (commit 435af2d)
- [x] P4 Substrate→LLM Direction — focus agenda, gap questions, hallucination block (commit c67641d)
- [x] P5 Evalving Harness + Operator Feedback (commits 8e30315, b717b25)

## Drive Engine (D1-D6) — autonomous goal system

- [x] D1 Goal Registry — `daemon/goal_registry.py` (419 lines)
- [x] D2 Goal Generator — `daemon/goal_generator.py` (585 lines)
- [ ] D3 Goal-Directed Execution — direct Ghost Q + curiosity toward active goals
  - [x] D3.1 goal-directed Ghost Q — goal_weight in brain.py collapse() (commit 8e30315)
  - [x] D3.2 goal-directed curiosity (initiative.py) — D3 primary path with percolation awareness
  - [x] D3.3 goal_weight dynamics (brain.py) — apply + decay_goal_weights per cycle
  - [ ] D3.4 NightRun integration — generate_from_percolation in nightrun
  - [x] D3.5 Cerebellum bridge — empowerment_signal from procedural layer → curiosity scoring (2026-04-16)
- [ ] D4 Satisfaction & Feedback — close the goal loop
  - [ ] D4.1 evaluate_satisfaction() in goal_registry.py
  - [ ] D4.2 CLI: `nouse goal add/list/status`
  - [ ] D4.3 eval_log goal metrics
- [ ] D5 Policy Integration — goal metrics drive cognitive_policy
  - [ ] D5.1 new trigger rules in cognitive_policy.py
  - [ ] D5.2 goal-driven living_core drives
- [ ] D6 Hierarchical goals + multi-step plans (future)

## Frontier Plan (external positioning)

- [ ] Fas 0: System ready — `pytest tests/` passes clean
  - blocker: persona import errors, 8 collection errors
- [ ] Fas 1: Intellectual priority — Larynx Problem on Zenodo (DOI)
  - sub: also Academia.edu + PhilPapers
  - sub: sister paper (Creative Free Energy / F_bisoc)
  - sub: GitHub README presentation
- [ ] Fas 2: Empirical validation — TruthfulQA benchmark
  - 8B without Nous: ~46% | 8B with Nous: ~96% (small test set, not universal)
  - need: lm-eval integration, proper benchmark run
- [ ] Fas 3: Institutional presence — ESA paper + HuggingFace Space
- [ ] Fas 4: Frontier radar — conference submission, researcher outreach

## Publications

- 18 papers on PhilPapers
- Larynx Problem: complete draft, pending Nous DOI
- Age of No Resistance: R&R revision submitted to Acta Sociologica (2026-03-31)

---

## Architecture Quick Reference

```
LLM (Larynx) + Nous (Brain) = Bisociationsmotor

Residual stream edges: w (structural weight) + r (residual signal) + u (uncertainty)
path_signal = w + 0.45*r - 0.25*u
Crystallization: w>0.55 AND u<0.35 → permanent
Decay: r *= 0.89 per step

Memory levels: working → episodic → semantic → procedural
18-step daemon loop in daemon/main.py
Limbic: arousal = 0.4*DA + 0.4*NA + 0.2*ACh (Yerkes-Dodson inverted-U)
F_bisoc = prediction_error + lam * complexity_blend; threshold=0.45
```

## Key Conventions

- brain.py and field/surface.py are the core — change carefully
- daemon/main.py is complex but works — be conservative
- Lab notes: `docs/lab-notes/YYYY-MM-DD-slug.md`
- Handoffs: `docs/handoffs/YYYY-MM-DD-NN.md`
- Code is intertwined with FNC theory — every change has philosophical implications
- Language: code + docs in English, strategic docs in Swedish

## Open Questions / Blockers

1. Ollama model `deepseek-r1:1.5b` not installed (404) — `minimax-m2.7:cloud` works as primary
2. TruthfulQA benchmark — needs GPU time and lm-eval adapter (`src/nouse/eval/lm_eval_adapter.py` does not exist yet)
3. Fas 0 (pytest clean) — web modules still have collection errors
4. `bisoc_candidates=0→164` — percolation threshold not met (6% readiness, ~37K edge deficit); D3 now drives curiosity toward thin/bridge domains; bridge_bisociation_search finds cross-domain pairs; **D3 goal_weights now active on FieldSurface** (was silently skipped because `hasattr(field, "decay_goal_weights")` returned False)
5. LLM timeouts: `gemma4:e2b` and `glm-5.1:cloud` consistently timing out at 45s; `minimax-m2.7:cloud` works

---

## Recent Decisions

| Date | Decision |
|------|----------|
| 2026-04-15 | Brain atlas: 8 regions (frontal, parietal, temporal, occipital, cerebellum, brainstem, hippocampus, amygdala) with spatial coordinates, domain → region classifier, slagsida diagnostic |
| 2026-04-15 | Sweet spot calibration: nervbana axion density (k_min, k_sweet, k_rigid), domain rigidity metric, Yerkes-Dodson curve for knowledge graphs |
| 2026-04-15 | Sensorimotor loop: camera module (Occipital Lobe) with llava:7b, speech module (Temporal+Frontal) with Whisper/Piper, vision module with JSON parsing |
| 2026-04-15 | Slagsida diagnostic: 88% concepts in Parietal+Brainstem, <1% in Frontal/Hippocampus/Amygdala — structural cause of missing bisociation |
| 2026-04-15 | Larynx Problem posted on LessWrong (rejected — AI detection flag, needs rewrite with concrete Nous results) |
| 2026-04-14 | Fixed daemon source loop: 50 doc cap, 600s timeout, batched state saves, DOC_EVERY=20 |
| 2026-04-14 | Created nouse.persona stub module (fixes 5-file import blocker) |
| 2026-04-14 | Switched extraction model to minimax-m2.7:cloud (5.8s vs 26s for gemma4) |
| 2026-04-14 | Reset model router state, daemon now reaches bridge_synthesis + curiosity stages |
| 2026-04-14 | Added handoff system (ROADMAP.md + docs/handoffs/) |
| 2026-04-14 | Added Stop hooks: handoff reminder + git push check |
| 2026-04-15 | Percolation module: domain density monitoring, bridge domains, targeted ingestion tasks |
| 2026-04-15 | Fixed bisociation detection: priority_domains param + KuzuDB 1-hop path fix + bridge_bisociation_search() |
| 2026-04-16 | Seed command (`nouse seed`): bootstrap underrepresenterade brain regions med LLM-genererad kunskap, source=llm_bootstrap |
| 2026-04-16 | Reasoning benchmark: nous 31.6% cross_domain vs 15.8% bare — dubbelt så hög bisociation accuracy |
| 2026-04-16 | Brain topology: Swedish underscore-domains (metakognition_och_syntes, logik_och_beslut, etc.) |
| 2026-04-16 | Substack workflow: Markdown → HTML render → copy/paste (semi-automatiserad) |
| 2026-04-16 | Nous.wiki cloned, daemon restart 08:02:55 (Apr 16) |
| 2026-04-16 | Cerebellum Problem drafted: procedural memory som missing substrate för kreativ empowerment; empowerment_signal saknas i Nous; implementering skissad |
| 2026-04-15 | D3 goal-directed execution: identify_loose_nodes(), generate_from_percolation(), goal-directed curiosity primary path, goal_weight decay, meta-cognitive logging |
| 2026-04-15 | Fixed D3 goal_weights: added apply_goal_weights() + decay_goal_weights() to FieldSurface (was silently skipped — only existed on Brain) |
| 2026-04-15 | Research sweep: Sartori's Bidirectional Coherence Paradox validates Larynx Problem; Kim's SCL mirrors Nous; zero recent AI bisociation papers |
| 2026-04-14 | Added MCP servers: nous-sqlite, arxiv, nouse-mcp |
| 2026-04-14 | Scheduled morning research agent (weekdays 06:17) |
| 2026-04-12 | Rename NoUse → Nous |
| 2026-04-13 | Drive Engine workplan (D1-D5) created |
| 2026-04-13 | P1-P5 implementation documented + 41 tests added |
| 2026-04-13 | DeepMind research note drafted |