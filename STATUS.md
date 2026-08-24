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

- [ ] **Starta om `nouse-daemon` för att köra Fas 3 punkt 8 (predictive
      surprise → HITL-task) på riktigt.**
      - **Vad:** kör `systemctl --user restart nouse-daemon`.
      - **Varför:** ren kodändring i `daemon/main.py` (ingen
        schemamigration den här gången) — daemonen måste starta om för
        att köra den nya modulen.
      - **Risk:** låg-medel. Additivt block, testat isolerat (8 tester),
        men det är första gången den faktiskt körs mot den levande
        curiosity-kön/HITL-kön (`research_queue.json`, `hitl_interrupts.json`)
        under verklig belastning, inte bara i tester. Om
        `NOUSE_PREDICTIVE_SURPRISE_THRESHOLD` (default 0.75) visar sig
        för lågt kan det skapa fler HITL-interrupts än väntat — enkelt
        att justera via env eller stänga av (`NOUSE_PREDICTIVE_SURPRISE_ENABLED=0`)
        utan kodändring.
      - **Verifiering efter omstart:** `journalctl --user -u nouse-daemon -f`
        tills en cykel loggas felfritt; håll ett öga på
        `hitl_interrupts.json` de första timmarna för att se om tröskeln
        känns rätt kalibrerad.
      - **Status:** ej gjord. Säg till när du vill köra den.

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
