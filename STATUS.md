# Nous — status

**Läs den här filen först i varje ny session.** Den är den enda källan till
"var är vi" — inte `ROADMAP.md` (historik/konventioner), inte
`NOUS_NEXT_GENERATION_PLAN.md` (den större arkitekturvisionen), inte
`docs/handoffs/*` (per-pass-anteckningar). De filerna finns kvar som
referens, men den här filen är sanningen om läget just nu.

Uppdatera den här filen **innan session slut** om något ändrats sedan
senaste uppdateringen — se `.claude/settings.json`s Stop-hook, som påminner
om detta om det finns okommitterade ändringar.

## Planerade actions (väntar på Björns godkännande)

Ändringar som rör den körande daemonen görs aldrig utan uttryckligt "kör"
från Björn i sessionen — även när "fria händer" gäller för själva
byggandet. Historik (senaste överst):

- [ ] **Starta om `nouse-daemon` för att köra user_relevance-viktningen
      på riktigt (curiosity + predictive-surprise, commit `378c1a2`).**
      - **Vad:** kör `systemctl --user restart nouse-daemon`.
      - **Varför:** ren kodändring i `goal_generator.py`/`daemon/main.py`
        (ingen migration) — daemonen måste starta om för att köra den.
      - **Risk:** låg. Additiv, degraderar säkert till oförändrat
        beteende om profilen saknas, 20 nya tester. Enda praktiska
        effekten: mål/HITL-uppgifter vars koncept kopplar till
        `scope="user_model"` (nu seedad, se raden nedan) får något högre
        prioritet än innan.
      - **Verifiering efter omstart:** `journalctl --user -u nouse-daemon -f`
        tills en cykel loggas felfritt.
      - **Status:** ej gjord. Säg till när du vill köra den.

- [x] **Seeda `scope="user_model"`-subgrafen i produktionsgrafen — klar
      2026-08-24 03:05.** Körd på Björns explicita "kör". 17 relationer
      tillagda (`Björn Wikström → kommunikationsstil/lärstil/
      kognitivt_behov/personmönster/arbetssätt`). Daemonen (PID 936012,
      SQLite WAL) opåverkad, ingen fel i loggen efteråt.
      - **Bugg hittad och fixad samma pass:** `Björn Wikström`-konceptet
        fanns redan (scope="general", från tidigare vanlig
        fil-ingestion). `add_concept()`s `INSERT OR IGNORE` uppdaterar
        tyst inte scope för redan existerande koncept — hubb-noden
        förblev alltså oskyddad även om de nya bullet-koncepten fick
        rätt scope. Fixat i `seed_user_model()` (explicit
        `set_concept_scope()`-anrop, commit `25468fa`) + tillämpat direkt
        på produktionsgrafen. Ny regressionstest fångar scenariot.

- [x] Starta om `nouse-daemon` för att köra Fas 3 punkt 8 (predictive
      surprise → HITL-task) — klar 2026-08-24 02:53, PID 936012. Körd på
      Björns explicita "kör", bekräftat felfri cykel efter omstart
      (`Limbic [cykel 3]`, ingen krasch).

- [x] **Starta om `nouse-daemon` för att köra multi-timescale-migrationen
      (Fas 3 punkt 9, slice 1) — klar 2026-08-24 02:45, PID 931901.**
      Körd på Björns explicita "kör". Migrationen bekräftad:
      `PRAGMA table_info(relation)` visar `strength_fast` (kolumn 12) och
      `strength_fast_updated` (kolumn 13); alla 7056 befintliga relationer
      backfyllda (0 NULL). Inga fel i loggen efter omstart.

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
  - **Beslut 2026-08-24 (Björn gav fria händer att bygga vidare på egen
    bedömning):** bygg INTE ett fakta/värde-extraktionsspår för att jaga
    LongMemEval-poäng. `RELATION_TYPES`-vokabulären (modulerar, orsakar,
    är_del_av, m.fl.) är byggd för tematiska/konceptuella relationer —
    exakt vad bisociationsmotorn/FNC-teorin faktiskt gör. LongMemEval
    testar atomära personliga fakta ur vardagskonversation — en annan
    uppgift. Grinden räknas som uppfylld genom detta beslut, inte genom
    ett förbättrat resultat. Riktig empirisk validering förblir
    TruthfulQA/FNC-bench (se `docs/NOUS_NEXT_GENERATION_PLAN.md`, avsnitt
    "LongMemEval-grinden — beslut 2026-08-24" för fullt resonemang).
  - Resultatfilerna + `eval/longmemeval_adapter.py`-fixen är committade
    (`75286b0`).

**Fas 3 (`docs/NOUS_NEXT_GENERATION_PLAN.md`, punkterna 7–10) är godkänd
av Björn. Byggordning: 10 → 9 → 8 → 7.**

- **Punkt 10 (energibudget) — klar 2026-08-24, LIVE.** Daemonen
  omstartad 02:24 (PID 921187), `energy_budget` bekräftat loggas felfritt
  i cykel-raden. Gate:ar nu bisociation-motorns cykel-pass utöver den
  gamla modulon.
- **Punkt 9 (multi-timescale styrka), slice 1 — klar 2026-08-24, LIVE.**
  Daemonen omstartad 02:45 (PID 931901), migrationen bekräftad körd
  (`strength_fast`/`strength_fast_updated` finns, 7056/7056 relationer
  backfyllda). Ny `strength_fast`-kolumn, decayar 6h-halveringstid,
  additiv/observationell (rör inte `strength` eller några befintliga
  beslut som dormancy/pruning/ranking — det är slice 2, medvetet
  uppskjutet). 320 tester gröna totalt, inga regressioner.
- **Punkt 8 (predictive coding som beslutsdrivare) — klar 2026-08-24 i
  kod, INTE live än.** Stigande flank i noradrenalin över tröskeln
  (0.75 default) skapar nu en riktig HITL-forskningsuppgift om vilka
  domän-par som överraskade systemet, via samma kö/interrupt-mekanism
  curiosity-loopen redan använder. 8 nya tester, 328 gröna totalt. Se
  "Planerade actions" ovan för omstart.
- Punkt 7 väntar på 8, som planerat.

**Björn-profilen ("systemet bör känna mig", 2026-08-24-konversation) —
klar och LIVE i produktion.** Ny `scope="user_model"` (`field/surface.py`,
sensitiv likt `personal_health`) + ny modul `daemon/user_model_seed.py`:
strukturerad parsning (INTE `extract_relations()`s LLM-extraktion — samma
grundorsak som LongMemEval-lärdomen, precisa meningar ska inte spädas ut
till vaga tematiska relationer) av `IIC/04_SYSTEM/system/PERSON.md` och
Claude-minnesfiler (`metadata.type` ∈ {user, feedback}) till relationer
typade `kommunikationsstil`/`lärstil`/`kognitivt_behov`/`personmönster`/
`arbetssätt`. Idempotent. `scope_from_path()` i `daemon/sources.py`
taggar också dessa filvägar automatiskt vid vanlig fil-ingestion, som
skyddsnät. 10 nya tester, 340 gröna totalt. **Seedad i produktionsgrafen
2026-08-24 03:05** (17 relationer + en bugfix, se "Planerade actions").

**Kopplad till curiosity/predictive-viktning — klar 2026-08-24 i kod
(commit `378c1a2`), INTE live än.** `goal_generator.py::compute_priority()`
har fått en femte signal `user_relevance` (vikt 0.20, övriga fyra
ombalanserade), inkopplad på alla 5 anropsställen med ett konkret koncept
tillgängligt. Predictive-surprise-seed-tasken (punkt 8) får en modifierare
(+0.15 max) om de överraskande domänerna kopplar till profilen — ren
överraskning förblir huvuddrivaren. 20 nya tester, 352 gröna totalt. Se
"Planerade actions" för omstart.

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
