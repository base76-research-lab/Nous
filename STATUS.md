# Nous — status

**Läs den här filen först i varje ny session.** Den är den enda källan till
"var är vi" — inte `ROADMAP.md` (historik/konventioner), inte
`NOUS_NEXT_GENERATION_PLAN.md` (den större arkitekturvisionen), inte
`docs/handoffs/*` (per-pass-anteckningar). De filerna finns kvar som
referens, men den här filen är sanningen om läget just nu.

Uppdatera den här filen **innan session slut** om något ändrats sedan
senaste uppdateringen — se `.claude/settings.json`s Stop-hook, som påminner
om detta om det finns okommitterade ändringar.

## Nuläge (2026-08-24)

**Fas 1 av `NOUS_NEXT_GENERATION_PLAN.md` är klar** (temporal giltighet,
proveniens-kedjor, schemalagd bisociation).

**Fas 2 steg 6 (extern benchmarking, LongMemEval) är delvis klar — och gav
ett negativt men substantiellt resultat, inte ett trasigt mätvärde:**

- `eval/longmemeval_adapter.py` byggd, isolerad `FieldSurface` per fråga.
- **Fixad 2026-08-24:** default-extraktionsmodellen (`deepseek-r1:1.5b`) är
  inte installerad i Ollama → 404 → `extract_relations()` misslyckades tyst
  hela natten 2026-08-23, så "nous"-villkoret testade i praktiken en tom
  graf i alla tidigare körningar. Fix: `longmemeval_adapter.py` sätter nu
  `NOUSE_EXTRACT_MODEL=gemma4:e2b` (samma modell den körande daemonen
  faktiskt använder framgångsrikt) om inget annat är satt.
- **Efter fixen, riktig full körning (n=24, `groq/openai/gpt-oss-120b`,
  `eval/results/longmemeval_20260824_000702.json`):**
  - BARE: 4,2% (bara `single-session-assistant` gav träffar)
  - NOUS: 0,0% — ingen förbättring
  - **Grundorsak identifierad, inte gissad:** extraktionen fångar
    tematiska/semantiska relationer (`Eggs modulerar Cream`), inte
    atomära fakta/värden ("30 dussin ägg" → senare "20"). LongMemEvals
    knowledge-update/multi-session-frågor kräver exakt den typen av
    värdefakta. Nous grafschema är inte byggt för det ännu.
  - **Öppen fråga för Björn:** är det värt att bygga ett
    fakta/värde-extraktionsspår vid sidan av relationsextraktionen innan
    LongMemEval körs igen, eller är LongMemEval fel benchmark för det
    Nous faktiskt är byggt att göra (semantisk grafgrundning, inte
    QA-över-transkript)?
  - Resultatfilen + `eval/longmemeval_adapter.py`-ändringen är
    **okommitterade** i skrivande stund.

**Fas 3 (`docs/NOUS_NEXT_GENERATION_PLAN.md`, punkterna 7–10: energibudget,
multi-timescale styrka, predictive coding, full Global Workspace) är
godkänd av Björn. Byggordning: 10 → 9 → 8 → 7.**

- **Punkt 10 (energibudget) — klar 2026-08-24 i kod, INTE live än.**
  `LimbicState.energy_budget` sjunker med faktiska LLM-anrop/cykel,
  återhämtar sig långsamt, gate:ar nu bisociation-motorns cykel-pass
  utöver den gamla modulon. 8 nya tester, 310 gröna totalt. **Den körande
  daemonen (`nouse daemon web`, port 8767) måste startas om för att plocka
  upp ändringen — inte gjort, kräver Björns godkännande (levande
  process).**
- Punkt 9 (multi-timescale styrka) var spärrad tills LongMemEval "faktiskt
  kör en full delmängd och mäter kvalitet" — det är nu gjort (ovan), men
  resultatet väcker grundorsaksfrågan om extraktionsschemat snarare än ger
  grönt ljus rakt av. **Vänta på Björns beslut om den frågan innan punkt 9
  påbörjas.**
- Punkt 8 och 7 väntar på 9 respektive 8–10, som planerat.

## Körande processer

- `nouse daemon web --port 8767` kör som en långlivad process
  (`.venv/bin/nouse daemon web`), separat från denna sessions arbete.
  Rör inte dess produktionsgraf (`~/.local/share/nouse/field.sqlite`) —
  all eval-körning måste använda isolerade `FieldSurface`-instanser
  (se `eval/longmemeval_adapter.py`s docstring).

## Konventioner (se även CLAUDE.md/AGENTS.md)

- Innan sessionsslut: uppdatera det här avsnittet, committa (eller skriv
  uttryckligen här varför inte).
- `.env` i repo-roten har API-nycklar (Cerebras/OpenRouter/Groq) — måste
  `source .env` manuellt, laddas INTE automatiskt (ingen dotenv-import i
  `eval/run_eval.py`).
