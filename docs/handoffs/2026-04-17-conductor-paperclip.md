# Handoff 2026-04-17 — Conductor-arkitektur + Paperclip-integration

## Vad som gjordes denna session

### 1. Autonomisk homeostas implementerad
- `src/nouse/daemon/homeostasis.py` — ny modul
- Anropas varje 6:e brain_loop-cykel (~1h)
- Auto-seedar regioner <5% av total (Hippocampus 0.4%, Frontal 0.3%, Amygdala 0.2%, Cerebellum 0.1%)
- Loggar varning vid >40% (Parietal 59.1%)
- Committat: e6aefd2

### 2. Chess ELO benchmark
- `eval/chess_elo_bench.py` — FNC-Bench proxy-mätning
- Resultat: ELO 767, 86% failure rate, 0 Nous-kontext → slagsida diagnosticerad
- Kimi-k2.5:cloud som modell (15s per drag)

### 3. Dispatch-skript (Ollama conductor)
- `scripts/dispatch.py` — Claude skriver task-fil → Ollama kör → resultat sparas
- Testat: FNC-Bench GDP physics-dataset genererat av kimi (142s, 20 frågor, korrekt format)
- `eval/tasks/` — task-filer, `eval/dispatch_results/` — resultat

### 4. Paperclip-integration
- Paperclip installerat och igång på `localhost:3100`
- Company: BAS (acb0c9e6-27f4-4bdb-8867-bc2b92c1359c)
- Agenter patchade:
  - CTO: process/kimi-k2.5:cloud (0 Claude-tokens)
  - ResearchScientist: process/kimi-k2.5:cloud (0 Claude-tokens)
  - CEO: claude-haiku-4-5 (~5% av Sonnet-kostnad)
- `scripts/paperclip_ollama_agent.py` — process-adapter skript

### 5. Papers genomlästa (hela korpusen)
Alla 18 papers i `/media/bjorn/iic/workspace/02_WRITING/papers/publicerade/` lästa.
FNC-Bench draft (`/media/bjorn/iic/workspace/02_WRITING/papers/pågående/fnc-bench/draft.md`) är KLAR — behöver bara empiriska resultat från Nous.

## Kritiska insikter från denna session

### Benchmark-insikten (SPARA DETTA)
TruthfulQA är fel instrument. FNC-Bench är rätt.
LPI = 0.0 för alla stateless LLM:er av arkitektonisk nödvändighet.
Memory: `feedback_benchmark_wrong_instrument.md`

### Paperclip + Nous = levande Larynx Problem-demo
Paperclip = larynxen (exekvering)
Nous = hjärnan (epistemisk grundning)
Nästa steg: Nous goal_registry → Paperclip issues automatiskt

### Corpus-syntes
18 papers = ett sammanhängande forskningsprogram i 7 lager:
SMT → Bell → Savant/Autism → Epistemic Circuits → Applied AI Phil → Precautionary Subjectivity → FNC-Bench/Larynx Problem

## Nästa session: prioritetsordning

1. **Testa Paperclip + Ollama-agenten** — tilldela en issue till CTO/ResearchScientist, verifiera att kimi kör och postar tillbaka
2. **FNC-Bench GDP-dataset komplettera** — kör dispatch för alla 12 domäner (physics done)
3. **Nous → Paperclip bridge** — goal_registry.py postar active goals som Paperclip issues via REST API
4. **Daemon-omstart** med homeostasis aktiv (ny kod i e6aefd2, daemon kör gammal version)
5. **FNC-Bench LPI-protokoll** — implementera `eval/fnc_bench/lpi.py`

## Teknisk status

| Komponent | Status |
|-----------|--------|
| Homeostasis (auto-seeding) | ✅ Committat, ej omstartad daemon |
| Chess ELO benchmark | ✅ Kör, diagnostikerar slagsida |
| Dispatch-skript | ✅ Testat, fungerar |
| Paperclip | ✅ Igång, agenter patchade till Ollama |
| FNC-Bench GDP physics | ✅ 20 frågor genererade |
| FNC-Bench övriga domäner | ❌ Ej påbörjat |
| LPI-protokoll | ❌ Ej implementerat |
| Nous → Paperclip bridge | ❌ Planerat, ej byggt |

## Ollama-modeller tillgängliga
kimi-k2.5:cloud, minimax-m2.7:cloud, gemma4:e2b, llava:7b
Weekly usage: 59.4% (återställs om 2 dagar)
