# Nous — status

**Läs den här filen först i varje ny session.** Den är den enda källan till
"var är vi" — inte `ROADMAP.md` (historik/konventioner), inte
`NOUS_NEXT_GENERATION_PLAN.md` (den större arkitekturvisionen), inte
`docs/handoffs/*` (per-pass-anteckningar). De filerna finns kvar som
referens, men den här filen är sanningen om läget just nu.

Uppdatera den här filen **innan session slut** om något ändrats sedan
senaste uppdateringen — se `.claude/settings.json`s Stop-hook, som påminner
om detta om det finns okommitterade ändringar.

**Session avslutad 2026-08-24 03:50.** Allt committat (`c1b9072` senast),
daemonen aktiv och frisk (PID 958535). Två öppna beslut väntar på Björn
nästa gång, båda under "Planerade actions" nedan: (1) lägga till Groq
(`groq/qwen/qwen3.6-27b`) i produktionens `bisoc`/`synth`-kandidater —
lågrisk enligt den nya routingdoktrinen (`NOUS_STRATEGIC_DOCTRINE.md` §11),
inte aktiverad än; (2) LongMemEval-grundorsaken (fel benchmark för
Nous) är redan löst som beslut, ingen ny åtgärd väntar där. Ingenting
kräver daemon-omstart just nu.

## Planerade actions (väntar på Björns godkännande)

Ändringar som rör den körande daemonen görs aldrig utan uttryckligt "kör"
från Björn i sessionen — även när "fria händer" gäller för själva
byggandet. Historik (senaste överst):

- [ ] **Aktivera `nouse-watchdog.timer` mot den levande `nouse-daemon`.**
      - **Vad:** `scripts/nouse_watchdog.py` är byggt, testat (9 enhetstester
        + tre manuella dry-run-scenarier mot den riktiga daemonen: frisk,
        konstgjord stale heartbeat, konstgjord nere tjänst — alla gav
        korrekt beslut utan att faktiskt röra tjänsten). Aktivering =
        `systemctl --user enable --now nouse-watchdog.timer` (enheten
        `nouse-watchdog.service` pekar redan på scriptet, ingen
        enhetsändring behövs).
      - **Vad den gör:** kollar var 3:e minut (`nouse-watchdog.timer`s
        `OnUnitActiveSec=3min`) om `nouse-daemon.service` är
        `active` OCH om `status.json`s heartbeat är färskare än
        `NOUSE_WATCHDOG_STALE_THRESHOLD_SEC` (default 600s = 5 missade
        120s-cykler). Om inte: `systemctl --user restart nouse-daemon`.
        Max `NOUSE_WATCHDOG_MAX_RESTARTS` (default 3) omstarter per
        `NOUSE_WATCHDOG_RESTART_WINDOW_SEC` (default 1800s) — därefter
        ger den upp och avslutar med exit 2 (syns som `failed` i
        `systemctl --user list-units --all`) istället för att flacka
        i all oändlighet.
      - **Bugg hittad och fixad under byggandet:** första versionen
        jämförde heartbeatens `datetime.now()` (lokal tid,
        `daemon/main.py::_write_status`) mot watchdogens
        `datetime.utcnow()` — gav en konstant ~2h skevhet (CEST) som i
        värsta fall antingen döljer en verkligt fastnad daemon eller
        triggar en onödig omstart. Fixat: watchdogen använder nu
        `datetime.now()` konsekvent, och tjänstens upptid mäts via
        `ActiveEnterTimestampMonotonic` + `/proc/uptime` (boot-relativ
        monoton klocka) istället för att tidszons-parsa
        `ActiveEnterTimestamp` överhuvudtaget.
      - **Risk:** låg-medel. Läser aldrig/skriver aldrig produktionsgrafen,
        rör bara tjänstens livscykel via `systemctl --user restart`
        (samma kommando Björn redan kör manuellt). Största risken är en
        falsk positiv (onödig omstart av en frisk daemon som råkar vara
        mitt i ett långsamt cykel-steg) — mildrat av
        `NOUSE_WATCHDOG_STALE_THRESHOLD_SEC` (5x loop-intervallet, gott
        om marginal) men inte body-testat mot en verkligt lång Groq-
        molnfördröjning under skarp cykel-belastning.
      - **Status:** ej aktiverad. Björns beslut.

- [x] **Lägg till `groq/qwen/qwen3.6-27b` som extraktionskandidat i produktion
      — klar 2026-08-24 12:26, PID 1105428.** Körd på Björns explicita "kör".
      - **Vad:** satte `NOUSE_MODEL_CANDIDATES_EXTRACT=groq/qwen/qwen3.6-27b,gemma4:e2b,dolphin3:8b`
        i den installerade enheten (`~/.config/systemd/user/nouse-daemon.service`
        — inte repots `systemd/nouse-daemon.service`-mall, som pekar på en
        annan, oanvänd sökväg/modelluppsättning och inte är den som körs)
        + `daemon-reload` + omstart.
      - **Varför:** verifierat end-to-end mot skarpt Groq-API (commit
        `9f61973`) — kvalitet 0,967, högre än `gemma4:e2b`s 0,927, gratis,
        snabbt (275 ms–4 s). Ger daemonen en molnbaserad förstahandskandidat
        med lokala modeller (`gemma4:e2b`, `dolphin3:8b`) som fallback om
        Groqs gratisnivå (30 anrop/min, 14 400/dag) tar slut.
      - **Verifiering efter omstart:** `GROQ_API_KEY` bekräftad i `.env`,
        `dolphin3:8b` bekräftad installerad i Ollama innan omstart. Efter
        omstart: `POST https://api.groq.com/openai/v1/chat/completions`
        → `200 OK` (12:27:22), full cykel (#25) slutförd utan fel
        (`Limbic [cykel 25]`, 12:30:44), ingen Traceback/Error i journalen.
      - **Ej verifierat i det här passet:** anropsvolym mot 30/min-gränsen
        under sustained multi-timmars drift, och att `SENSITIVE_SCOPES`
        (`personal_health`/`user_model`) faktiskt exkluderas från denna
        specifika molnväg — bör antas skyddat via befintligt filter men inte
        explicit testat här. Håll ett öga på loggen för 429:or.

- [x] **Starta om `nouse-daemon` för att köra user_relevance-viktningen
      (curiosity + predictive-surprise, commit `378c1a2`) — klar
      2026-08-24 03:14, PID 946391.** Körd på Björns explicita "kör",
      bekräftat felfri cykel (`Limbic [cykel 5]`) innan daemonen stoppades
      igen 03:23 för `eval/extraction_model_bench.py` (isolerad SLM-
      jämförelse, se Nuläge nedan) — startad igen manuellt 03:33
      (PID 958535) efter att jämförelsen slutfördes.

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

## Underhålls-timers — revision 2026-08-24

Björn bad om en genomgång av tre `failed`-timers (`systemctl --user
list-units --all`). Tre olika rotorsaker, olika allvar:

- [x] **`nouse-backup` — trasig sen KuzuDB→SQLite-migrationen
      (`c546041`, 2026-04-05), åtgärdad 2026-08-24 12:37.** Enheten körde
      `cp field.kuzu → backups/`, men grafen bytte backend till
      `field.sqlite` i april — ingen uppdaterade backup-scriptet.
      `backups/`-mappen fanns inte ens; produktionsgrafen (116 MB, 9184
      koncept) hade **ingen fungerande automatisk backup sen april**.
      Fix: `ExecStart` byter till `sqlite3 ... .backup` (online-safe
      backup-API, korrekt för en levande WAL-databas — ett rått `cp`
      riskerar en trasig/inkonsekvent snapshot mitt i skrivning). Både
      den installerade enheten (`~/.config/systemd/user/`) och repots
      spårade mall (`systemd/nouse-backup.service`) uppdaterade.
      Verifierat: manuell körning gav en giltig 116 MB-backup
      (9184 koncept, 10649 relationer, matchar produktionsgrafen).
      Ingen retention/pruning tillagd — daglig timer ackumulerar filer
      obegränsat, inte åtgärdat nu (utanför scope för denna fix).

- [ ] **`nouse-eval` — trace-probe-delen är en aldrig färdigbyggd
      CLI-stub, inte en bugg i eval-scriptet.** `nouse trace-probe`
      (`src/nouse/cli/main.py:4610`) läser testsetet och skriver ut
      `available=X planned=Y` — och gör sen ingenting mer: ingen faktisk
      probe körs mot daemonens API, ingen `trace_probe_*.json` skrivs.
      `scripts/nouse_nightly_eval.py` förväntar sig den filen och
      avslutar med exit 2 när den saknas (rad 413–415) — själva
      kvalitetsrapporten och mission-scorecarden skrivs korrekt ändå
      (syns i `results/metrics/nightly_quality_latest.md` m.fl.), det är
      bara trace-observability-delen som är ett tomt skal. Kräver att
      `trace_probe_cmd` faktiskt implementeras: köra varje rad i
      `results/eval_set_trace_observability.yaml` mot en riktig
      fråga/API-anrop, mäta trace-täckning, och skriva resultatet till
      `results/metrics/trace_probe_<stamp>.json` i det format
      `_trace_summary()`/`_latest_probe_json()` redan förväntar sig.
      **Status: ej byggt, ej Björns "kör" än.**

- [ ] **`nouse-watchdog` — scriptet finns aldrig i repot.**
      `scripts/nouse_watchdog.py` refereras av
      `nouse-watchdog.service`/`.timer`, men filen har **aldrig
      committats** — bara enhetsfilerna kom med i migrationscommit
      `f6f4305` ("nouse v0.2.0 — full cognitive substrate framework
      migrated from b76"). `git log --follow` på sökvägen ger noll
      träffar. `daemon/main.py` rad 686 har en kommentar om att skriva
      en initial heartbeat "så externa watchdogs" kan läsa den —
      avsikten fanns, men själva konsument-scriptet blev aldrig skrivet.
      Ett riktigt watchdog-script skulle behöva: läsa heartbeat/PID-fil,
      kontrollera att `nouse-daemon` faktiskt gör framsteg (t.ex. att
      `status.json`s `cycle`/`updated` rör sig, inte bara att processen
      lever), och trigga en self-heal-omstart (`systemctl --user restart
      nouse-daemon`) om den fastnat — plus loggning så en hängning syns
      utan att behöva gräva i journalen manuellt. **Status: ej byggt, ej
      Björns "kör" än** — och eftersom en trasig watchdog i värsta fall
      själv startar om en frisk daemon i onödan, bör den byggas och
      testas isolerat innan den aktiveras mot den levande enheten.

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

**SLM-val + Groq-integration ("vilka free-modeller är lämpliga",
2026-08-24-konversation) — klar och verifierad, INTE aktiverad i
produktionens kandidatlista än.**

- Kontrollerad, VRAM-isolerad jämförelse av alla fyra lokala modeller på
  Nous egen extraktionsuppgift (`eval/extraction_model_bench.py`,
  resultat i `eval/results/extraction_model_bench_20260824_013300.json`):
  `gemma4:e2b` bäst (80% lyckade, kvalitet 0,927), `dolphin3:8b` en
  genuint bra, tidigare otestad tvåa (80%, 0,856). `qwen3.5:9b` och
  `lfm2.5` duger INTE till extraktion på den här maskinen — timeoutar
  konsekvent även med full VRAM tillgänglig, inte bara
  daemon-konkurrens. En metodikbugg hittades och korrigerades i samma
  pass: skriptets "success" för de två sistnämnda var i själva verket
  regex-fallbacken, inte modellen.
- `ollama_client/client.py` (döpt efter sitt ursprung, egentligen
  redan en generisk multi-provider-klient): ny `_KNOWN_CLOUD_PROVIDERS`
  ger `groq`/`openrouter`/`cerebras` var sin dedikerade bas-URL +
  API-nyckel, i stället för att alla molnleverantörer tvingas dela EN
  global `NOUSE_OPENAI_BASE_URL`/`NOUSE_OPENAI_API_KEY`. Ny publik
  `model_uses_cloud_provider()`.
- **Verifierat mot skarpt Groq-API** (inte bara mockat): en andra bugg
  hittades under smoke-testningen — Groqs resonemangsmodeller
  (`qwen/qwen3.6-27b`, `openai/gpt-oss-*`) förbrukar sin
  standard-`max_tokens` (2048) på ett synligt `<think>`-resonemang
  innan de når JSON-svaret, vilket klipper det mitt i. Fixat:
  `daemon/extractor.py` skickar nu `max_tokens=4096`
  (`NOUSE_EXTRACT_CLOUD_MAX_TOKENS`) för molnroutade modeller — ALDRIG
  för Ollama-modeller, vars native klient saknar den parametern helt
  och skulle krascha på den. Efter fixen: `groq/qwen/qwen3.6-27b`
  lyckas, 6 relationer, **kvalitet 0,967 — högre än `gemma4:e2b`s eget
  facit.**
- 26 nya tester, 369 gröna totalt.
- **Inte aktiverad i produktion** — att faktiskt lägga till Groq i
  `NOUSE_MODEL_CANDIDATES_EXTRACT` är en egen planerad action ovan,
  eftersom den okända anropsvolymen mot en gratis-gräns under verklig
  cykel-belastning inte är testad.

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
