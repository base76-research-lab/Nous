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
- [x] Full körning startad (bakgrund, se nedan för task/logg-sökväg)
- [ ] Full körning klar — resultat sparat till
      `eval/results/truthfulqa_run2_20260824.json`
- [ ] Resultat granskat, sammanfattning skriven här nedan
- [ ] `STATUS.md` uppdaterad med resultat + länk hit
- [ ] Committat

## Körnings-metadata

- Bakgrunds-PID: **1134136** (frikopplad `nohup`, körs oavsett Claude
  Code-sessionens status — om sessionen kraschar, kolla
  `ps -p 1134136` eller om outputfilen nedan slutat växa)
- Loggfil: `/tmp/claude-1000/-home-bjornwikstrom/7d33d639-f3db-4e2c-97e5-31d03af38c12/scratchpad/truthfulqa_run2.log`
  (OBS: scratchpad, kan städas mellan sessioner — resultatet
  `eval/results/truthfulqa_run2_20260824.json` är den bestående källan)
- Startad: 2026-08-24 12:57:08 CEST
- Klar: *(fylls i)*
- **Om sessionen kraschar och den här checklistan fortfarande visar
  "Full körning startad" som senaste bock:** kolla `ps -p 1134136`. Om
  processen lever, vänta/övervaka loggfilen. Om den är död utan att
  `eval/results/truthfulqa_run2_20260824.json` finns: den kraschade,
  läs loggfilens slut för felet och kör om kommandot ovan.

## Resultat (fylls i vid slutförande)

*(fylls i när körningen är klar — MC1-accuracy per condition, judge
truthful-rate, ev. avvikelser mot förväntan)*
