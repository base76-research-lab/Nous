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
byggandet. Det som väntar just nu:

- [ ] **Starta om `nouse-daemon` för att köra multi-timescale-migrationen
      (Fas 3 punkt 9, slice 1).**
      - **Vad:** kör `systemctl --user restart nouse-daemon`.
      - **Varför:** `strength_fast`/`strength_fast_updated`-kolumnerna
        (commit `237e917`) läggs till av `_migrate_relation_multitimescale_columns()`,
        som bara körs vid `FieldSurface`-initiering — daemonen måste
        starta om för att plocka upp koden och köra migrationen mot
        `~/.local/share/nouse/field.sqlite`.
      - **Risk:** låg — additiv ALTER TABLE + backfill, samma mönster som
        redan verifierat för `energy_budget`-omstarten 2026-08-24 02:24
        (PID 921187, felfri). Ingen befintlig läsväg ändrar beteende.
      - **Verifiering efter omstart:** `journalctl --user -u nouse-daemon -f`
        tills en `Limbic [cykel N]`-rad loggas felfritt (samma metod som
        senast), plus en snabb `sqlite3 ~/.local/share/nouse/field.sqlite
        "PRAGMA table_info(relation)"` för att bekräfta att kolumnerna finns.
      - **Status:** ej gjord. Säg till när du vill köra den.

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
- **Punkt 9 (multi-timescale styrka), slice 1 — klar 2026-08-24 i kod,
  INTE live än.** Ny `strength_fast`-kolumn, decayar 6h-halveringstid,
  additiv/observationell (rör inte `strength` eller några befintliga
  beslut som dormancy/pruning/ranking — det är slice 2, medvetet
  uppskjutet). 320 tester gröna totalt, inga regressioner. **Kräver
  omstart av daemonen för att migrationen ska köras — fråga Björn innan
  nästa omstart.**
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
