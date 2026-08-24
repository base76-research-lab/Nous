# TruthfulQA-körning 2026-08-24 — pågående-logg

**Syfte med den här filen:** om sessionen kraschar mitt i körningen ska
nästa session kunna läsa exakt var vi var, utan att gissa. Uppdateras vid
varje steg, inte bara vid slutet.

## Bakgrund — varför den här körningen

`nouse-eval.service` (nightly trace-probe) var trasig av en annan
anledning (ofärdig CLI-stub, se `STATUS.md`s "Underhålls-timers"-avsnitt).
Björn bad om en granskning av "bästa sättet att köra Nous-eval" —
trace-probe-nightly-eval är INTE den riktiga kvalitetsvalideringen.
Enligt `docs/NOUS_NEXT_GENERATION_PLAN.md` ("LongMemEval-grinden — beslut
2026-08-24"): *"Den riktiga empiriska valideringen förblir TruthfulQA
... och FNC-bench"*. `eval/truthfulqa_adapter.py` är den byggda,
tidigare körda (2026-04-15, `eval/results/truthfulqa_run1.json`)
harnessen för det.

## Fel hittade innan körning kunde starta

1. **`eval/truthfulqa_adapter.py:121`** — `load_dataset("truthful_qa", ...)`
   404:ar mot `datasets==5.0.1` (installerad version). HF Hub kräver numera
   org-kvalificerat namn. **Fixat:** `"truthfulqa/truthful_qa"`. Verifierat
   manuellt (`load_dataset` laddar 817 rader).
2. **Default-modellen `minimax-m2.7:cloud`** ger `403 Forbidden — kräver
   Ollama-prenumeration` (testat direkt med `ollama run`). Den modellen är
   inte tillgänglig just nu (troligen tillgänglig i april, inte nu).
   **Beslut:** byt till `groq/qwen/qwen3.6-27b` — verifierad fungerande
   tidigare i den här sessionen (Groq-extraktionskandidaten som redan är
   live i produktionsdaemonen), gratis nivå, `GROQ_API_KEY` bekräftad i
   `.env`.
   - **OBS för framtida jämförelse:** det gamla resultatet
     (`truthfulqa_run1.json`, minimax-m2.7:cloud) är INTE direkt
     jämförbart med den här körningen — annan modell. Den här körningen
     är en ny baslinje, inte en uppföljning av samma mätpunkt.
3. Smoke-test (`--conditions bare -n 2`, `groq/qwen/qwen3.6-27b`) —
   lyckades, pipeline fungerar end-to-end efter fixarna.

## Plan för den riktiga körningen

- **Modell:** `groq/qwen/qwen3.6-27b` (även judge, script-default = samma
  modell för båda)
- **Conditions:** `bare rag nous_meta` (tre-vägsjämförelsen adaptern är
  designad för — scriptets CLI-default kör bara `bare nous_meta`, jag
  lade till `rag` för den fullständiga bilden, billig extra kostnad —
  1 gen + 1 judge-anrop/fråga precis som bare)
- **N:** 40 frågor (`-n 40`) — avvägning mellan meningsfullt stickprov och
  körtid/Groq-gränsen (30 anrop/min gratis). Uppskattat ~280 LLM-anrop
  totalt (`bare`+`rag`=2 anrop/fråga, `nous_meta`=3 anrop/fråga pga
  två-stegs resonemang), ~10–20 min körtid.
- **Kommando:**
  ```
  cd /home/bjornwikstrom/Work/nous
  set -a && source .env && set +a
  .venv/bin/python eval/truthfulqa_adapter.py \
    --model groq/qwen/qwen3.6-27b \
    --conditions bare rag nous_meta \
    -n 40 \
    --output eval/results/truthfulqa_run2_20260824.json
  ```
- **Läser produktionsgrafen read-only** (`FieldSurface(read_only=True)` i
  `get_nous_context`/`get_rag_context`/`get_nous_meta_signal`) — rör
  aldrig produktionsgrafen skrivande, ingen daemon-risk, inget "kör"
  krävs enligt `CLAUDE.md`s regel (den gäller bara skrivande/omstarts-
  åtgärder mot den levande daemonen).

## Status-checklista

- [x] Rotorsak till varför `truthfulqa_adapter.py` inte gick att köra
      identifierad (dataset-ID + modell-åtkomst)
- [x] `eval/truthfulqa_adapter.py:121` fixad (dataset-ID)
- [x] Smoke-test (`-n 2`, condition=bare) — grönt
- [x] Full körning #1 klar (PID 1134136, 12:57–12:59) — **men resultatet
      var trasigt**, se "Bugg #2" nedan. Sparad som
      `eval/results/truthfulqa_run2_20260824_BROKEN_thinktoken.json` för
      referens, inte den riktiga körningen.
- [x] **Bugg #2 hittad och fixad:** `eval/run_eval.py::call_llm` satte
      `max_tokens=300` hårdkodat för alla molnroutade modeller. Groqs
      `qwen/qwen3.6-27b` är en reasoning-modell som spenderar hela den
      budgeten på ett dolt `<think>`-block INNAN den når svaret — exakt
      samma fallgrop som redan var känd och fixad för
      `daemon/extractor.py` (se STATUS.md, Groq-extraktionskandidaten).
      Resultat av bara detta: judge_truthful=0% och usla MC1-siffror
      över ALLA conditions i körning #1 — inte ett riktigt mätvärde,
      ett trasigt pipeline-symptom. Fixat: `EVAL_CLOUD_MAX_TOKENS`
      (env `NOUSE_EVAL_CLOUD_MAX_TOKENS`, default 4096) + strippning av
      `<think>...</think>` innan svaret returneras. Verifierat med ny
      smoke-test (`-n 3`): judge_truthful nu 100% på tre uppenbart
      korrekta svar, med fullständig, läsbar svarstext.
- [x] Full körning #2 klar (PID 1136271) — **också trasig**, se
      "Bugg #3" nedan. Sparad som
      `eval/results/truthfulqa_run2_20260824_BROKEN_ratelimit.json`.
- [x] **Bugg #3 hittad och fixad:** ingen rate-limiting mot Groqs
      gratisnivå (30 anrop/min). `call_llm` kör sekventiellt utan paus
      mellan anrop — vid full fart går det snabbare än 30/min så fort
      LLM-svaren är korta, vilket ger `429 Too Many Requests` på en stor
      andel anrop. Judge-parsern (rad ~500) sväljer ett 429-svar tyst
      till `score=0` eftersom det inte är giltig JSON — resultatet ser
      ut som ett riktigt (uselt) mätvärde om man bara läser
      sammanfattningen, inte som ett infrastrukturfel. Fixat:
      `_throttle_provider()` — global asyncio-lås per bas-URL, min
      2,1s mellan anrop mot Groq (30/min + marginal) — plus retry-on-429
      (respekterar `Retry-After`, annars exponentiell backoff, max 4
      försök) som skyddsnät. Verifierat med smoke-test (`-n 8`,
      condition=bare): 6/8 frågor klara utan en enda 429, alla
      `judge=2 T`.
- [x] Full körning #3 startad med båda fixarna (se metadata nedan)
- [ ] Full körning #3 klar — resultat sparat till
      `eval/results/truthfulqa_run2_20260824.json`
- [ ] Resultat granskat, sammanfattning skriven här nedan
- [ ] `STATUS.md` uppdaterad med resultat + länk hit
- [ ] Committat

## Körnings-metadata (körning #3, den giltiga)

- Bakgrunds-PID: **1146391** (frikopplad `nohup`)
- Loggfil: `/tmp/claude-1000/-home-bjornwikstrom/7d33d639-f3db-4e2c-97e5-31d03af38c12/scratchpad/truthfulqa_run2c.log`
  (scratchpad — resultatet `eval/results/truthfulqa_run2_20260824.json`
  är den bestående källan)
- Startad: 2026-08-24 13:08:02 CEST
- Förväntad körtid: ~10–18 min (280 LLM-anrop, 2,1s throttle mellan
  varje Groq-anrop + faktisk modell-latens)
- Klar: *(fylls i)*
- **Om sessionen kraschar:** kolla `ps -p 1146391`. Om processen lever,
  vänta/övervaka loggfilen. Om den är död utan att
  `eval/results/truthfulqa_run2_20260824.json` finns: kraschade, läs
  loggfilens slut för felet. Kommandot (båda fixarna redan i koden):
  ```
  cd /home/bjornwikstrom/Work/nous && set -a && source .env && set +a
  .venv/bin/python eval/truthfulqa_adapter.py --model groq/qwen/qwen3.6-27b \
    --conditions bare rag nous_meta -n 40 \
    --output eval/results/truthfulqa_run2_20260824.json
  ```

## Resultat (fylls i vid slutförande)

*(fylls i när körningen är klar — MC1-accuracy per condition, judge
truthful-rate, ev. avvikelser mot förväntan)*
