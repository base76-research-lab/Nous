# Nous — status

**2026-08-24, integritet, watchdog och MCP 2.0 stabiliserade:**

- Daemonens relationsextraktor har nu en hård lokalmodellspärr för
  `research_plg`, `personal_health` och `user_model`. Molnkandidater tas bort
  före första modellanropet, även om de ligger först i tjänstens kandidatlista;
  diagnostiken redovisar policy och blockerade modeller.
- `status.json` skrivs atomiskt och uppdateras med fas/dokumentprogress under
  source-ingest, inte bara vid cykelgränser. Watchdoggens reservtröskel höjdes
  från 600 till 1200 sekunder. Live verifierat efter daemon-omstart: heartbeat
  avancerade inom samma cykel, enbart lokala Ollama-anrop syntes, watchdog gav
  `OK` och daemonen stod kvar på samma PID med `NRestarts=0`.
- MCP-servern är migrerad från borttagna `mcp.server.fastmcp.FastMCP` till
  `mcp.server.mcpserver.MCPServer` och använder MCP 2.0:s HTTP-parametrar.
  Full verifiering: `404 passed, 1 skipped`; de tre tidigare MCP-felen är borta.

**2026-08-24, ICM/Larynx agent-pipeline (Jarvis), första vertikala skivan
klar och verifierad:**

Björns krav: "Folders over agents. Methodology over tools." Grundat direkt
i källmaterialet han pekade på —
`IIC/01_PROJECTS/icm-source-study/source-material/icm-courses/ICM-Larynx-multiAgents.v2.md`
(hans egna ICM- och Larynx-papper, med ett färdigt compatibility-kontrakt:
femlagersmodell, exakt stage-pipeline, exakta CONTEXT.md-mallar). Byggt
enligt det kontraktet, inte uppfunnet från scratch.

- **Nytt, publikt (denna repo):** `ICM-agents.md` (Layer 0-kärnregel:
  LLM:en parsar och verbaliserar, aldrig routar eller validerar sig själv),
  `stages/01-05_*/CONTEXT.md`, `_config/{error_codes,validation_rules,
  executor_registry}.md`, `references/{larynx_policy,icm_stage_conventions}.md`,
  och `src/nouse/agent_system/{contract,folder_loader,pipeline,executors}.py`.
  `cli/commands/agent.py` fylld i (var placeholder), registrerad i
  `cli/main.py` som `nouse agent run "<text>"`.
- **Nytt, privat (`IIC/04_SYSTEM/agents/`, pushas aldrig):**
  `jarvis-policy.md` (Björns hårdregler — forskning stannar lokalt m.m.)
  plus tre agentkort (`local-routine`, `code-delegation`, `research-guard`)
  i samma YAML-frontmatter-format som redan bevisat fungerar i
  `Work/autonomous-income-lab/agents/*.yaml`.
- **Återanvänt, inget nytt uppfunnet:** `capability/graph.py::build_route_plan()`
  för intent-klassificering, `ollama_client`s multi-provider-klient för
  alla modellanrop, `session/relay.py` för eskalering till Claude/Codex,
  `mcp_gateway`s kernel-funktioner för grundning och loggning tillbaka in i
  Nous minnesgraf.
- **Verifierat end-to-end, tre scenarier:** (1) småprat → `local-routine`,
  `gemma4:e2b`, svar på ~2s. (2) stort uppdrag → `code-delegation`,
  `nouse relay`-session öppnad, Jarvis svarar direkt utan att blockera
  (relay-öppningen syns via `nouse relay show`). (3) uppdrag som nämner
  forskningsnyckelord (`NOUSE_RESEARCH_LOCAL_MARKERS` i `.env`) →
  `RESEARCH_LOCAL_VIOLATION`, blockerad oavsett uppdragsstorlek. Läcksökning
  bekräftad: noll träffar på "bjorn/IIC/02_LIBRARY" i något publikt-sidigt
  filträd.
- **2026-08-24, senare pass: fem nya agentkort + stdio MCP-klient.**
  `src/nouse/agent_system/mcp_client.py` fick stdio-transport
  (`mcp.client.stdio`) för Thunderbird, utöver HTTP-transporten för
  AgentMail — verifierad direkt mot den lokala `node`-bryggan
  (`getRecentMessages`, `listEvents`). Nya kort: `mail-triage`,
  `calendar-lookup` (läsning, Thunderbird), `voice-capture` (lokal
  filskrivning, scopad till `00_INBOX/ljudanteckningar/`, medvetet lägre
  kvalitet än Claude Codes egen `/voicenote`-skill), `mail-compose`
  (bara `saveDraft`, ringer aldrig `sendMail`), `calendar-write`
  (`createEvent`, alltid via Thunderbirds egen granskningsdialog —
  `skipReview` hårdkodat till `false` i `executors.py`, appliceras bara på
  de två verktyg som faktiskt känner till parametern efter en bugg som
  först skickade den till alla verktyg och kraschade). Ny domänklassificerare
  `_classify_domain_intent()` i `pipeline.py`, samma statiska
  substrängsmönster som `daemon/sources.py::scope_from_path()`.
  **Buggar hittade och fixade under testning:** (1) tom lista `[]`
  tolkades som falsy i Python och tappade bort kontext till
  verbaliseringsmodellen — fixat (`is not None`-kontroll). (2) modellen
  slår ofta in JSON-svar i \`\`\`json-kodblock trots instruktion att inte
  göra det — ny `_strip_json_fence()`-hjälpare, återanvänd i stage 01 och
  extraktionshjälparen. **Verifierat live, alla fem:** mail-triage och
  calendar-lookup gav korrekta "inget nytt"-svar; voice-capture skrev en
  riktig fil (innehåll bevarat, ingen annanstans rörd); mail-compose
  skapade ett äkta utkast i Thunderbirds Drafts-mapp (bekräftat via
  `searchMessages`, `folderPath` visar Drafts, inget skickat); calendar-write
  öppnade Thunderbirds granskningsdialog (bekräftat: `listEvents` visade
  inget skapat event förrän Björn godkänner).
- **Standing sändningsrätt, `nouse@agentmail.to` — Björns uttryckliga
  beslut 2026-08-24.** Till skillnad från alla andra agentkort får
  `agent-mail` nu autonomt skicka svar (`reply_to_message`) utan "kör" per
  händelse — ett medvetet, dokumenterat undantag från hårdregel 3, skopat
  till exakt den kanalen (se `jarvis-policy.md` hårdregel 3-undantaget och
  `agent-mail/AGENT.md`). `scripts/agentmail_poll.py` utökad: efter att ha
  loggat ett nytt mejl, drar den ett svar via `gemma4:e2b` (mejlinnehåll
  behandlas uttryckligen som DATA, aldrig instruktion — matchar AgentMails
  egen verktygsvarning) och skickar det via `reply_to_message`. Loggning
  sker INNAN sändning, så handlingen går att rekonstruera. **Inte
  end-to-end-testat med en riktig ny sändning än** — undvek medvetet att
  testa genom att spola tillbaka baslinjen igen (det hade skickat riktiga
  svar till gårdagens historiska mejl från Björn); väntar på att en äkta
  ny händelse kommer in via den redan aktiva 10-minuterstimern.
- **AgentMail-poller byggd, testad, INTE aktiverad än.** Björn hade redan
  testat send/receive mot `nouse@agentmail.to` manuellt 2026-08-23 (finns
  äkta korrespondens i inkorgen, inklusive en upptäckt: en tidigare session
  hade autonomt godkänt fyra forskningsbeslut och svarat självständigt,
  signerat "/Claude" — det mönstret fortsätts INTE här, bekräftat med
  Björn 2026-08-24: varje faktiskt svar från den här kanalen kräver
  explicit "kör", ingen auto-reply.). Nytt: `src/nouse/agent_system/mcp_client.py`
  (Nous första MCP-**klient** — tidigare har Nous bara varit MCP-server;
  byggd på det redan installerade officiella `mcp`-SDK:t, HTTP-transport
  via `streamable_http_client`). `scripts/agentmail_poll.py`: läser bara,
  loggar nya olästa mejl till Nous minne (`kernel_write_episode`) och en
  pending-review-kö, uppdaterar `last_checked`, ringer ALDRIG
  `send_message`/`reply_to_message`. Första körningen sätter baslinjen
  till "nu", backfyller inte 2026-08-23-historiken automatiskt (inklusive
  ett fortfarande obesvarat mejl "nu ska jag visa" — kvar för Björn/en
  session att hantera manuellt om han vill). Verifierat manuellt två
  gånger: normal körning (inget nytt), och en tillfällig bakåtflyttad
  baslinje som bekräftade att alla 5 existerande olästa mejl hittas,
  loggas och köas korrekt (state återställd efteråt, ingen data kvar
  felaktigt). `systemd/agentmail-poll.{service,timer}` skrivna (10 min
  intervall, matchar `nouse-watchdog`-mönstret) men **inte installerade/
  aktiverade** — det gör pollningen till en stående bakgrundsprocess,
  väntar på Björns separata "kör" för det steget.
  **2026-08-24, senare: aktiverad.** `systemctl --user enable --now
  agentmail-poll.timer` kört, körde direkt en gång (`status=0/SUCCESS`,
  "no new mail"). Demo-mejlet "nu ska jag visa" (bara ett test inför hans
  fru) raderat på Björns begäran via `delete_thread` — isolerad tråd, rörde
  ingen annan korrespondens.
- Nytt privat agentkort: `IIC/04_SYSTEM/agents/agent-mail/AGENT.md` —
  `forbidden` nämner uttryckligen 2026-08-23-precedensen och att den inte
  fortsätts.
- **Headless-eskalering nu riktigt inkopplad (samma session, senare pass).**
  Björn auktoriserade `claude -p --permission-mode plan`, körd som en
  detached process (`subprocess.Popen(..., start_new_session=True)`) så den
  överlever CLI-anropets egen process-livstid. Verifierat live: pid loggad
  i `runs/<run_id>/relay_delegation/meta.json`, körde ~20s, avslutade sig
  självt, `permission_denials: []` bekräftar att plan-läget varken frågade
  om eller försökte någon sidoeffekt, verklig kostnad synlig i loggen
  (~$0.12). `relay_update()` skriver pid/logg-sökväg in i relay-sessionen
  så `nouse relay show <id>` visar delegeringen. Ingen `--add-dir` mot
  riktiga projekt än (tom arbetskatalog i den här skivan, medvetet) och
  ingen automatisk poll-tillbaka in i relay-sessionen än — nästa skiva.
  Mejl/kalender-integrationer fortfarande inte inkopplade.
- **Ny `.env`-nyckel:** `NOUSE_AGENT_POLICY_DIR` (pekar på
  `IIC/04_SYSTEM/agents`) och `NOUSE_RESEARCH_LOCAL_MARKERS` (citerad —
  kommaseparerad lista med mellanslag kraschar annars `source .env`).

**Läs den här filen först i varje ny session.** Den är den enda källan till
"var är vi" — inte `ROADMAP.md` (historik/konventioner), inte
`NOUS_NEXT_GENERATION_PLAN.md` (den större arkitekturvisionen), inte
`docs/handoffs/*` (per-pass-anteckningar). De filerna finns kvar som
referens, men den här filen är sanningen om läget just nu.

Uppdatera den här filen **innan session slut** om något ändrats sedan
senaste uppdateringen — se `.claude/settings.json`s Stop-hook, som påminner
om detta om det finns okommitterade ändringar.

**2026-08-24, front-modell-benchmark för Jarvis (`eval/front_model_bench.py`,
resultat i `eval/results/front_model_bench_20260824_131301.json`):**
5 lokala modeller testade mot 4 Jarvis-relevanta scenarier (småprat,
systemmedvetenhet, enkelt kommando, ett för stort uppdrag den ska avböja).
**Kritisk metodfälla hittad och löst underveges:** Ollamas `"think": false`
saknades i första körningen — utan den gav `gemma4:e2b` och `qwen3.5:9b`
tomt `content` (all tokenbudget gick åt i det dolda `thinking`-fältet,
`done_reason: length`). Detta ifrågasätter delvis gårdagens
`extraction_model_bench.py`-slutsats att `qwen3.5:9b` "duger INTE" —
den kördes utan `think:false` och kan vara felaktigt dömd; ej omtestat än.

Resultat med `think:false`: **`gemma4:e2b`** vann tydligt — snabbast
(snitt 2,1s vs. 3,7–28s för övriga) och **enda modellen som konsekvent
avböjde det för stora uppdraget** i alla 4 körningar istället för att
försöka utföra det själv. `qwen3-8b-abliterated` hade bäst naturlig ton
men **misslyckades disciplinen** (tackade ja till att skriva om hela
artikeln). `lfm2.5` respekterar inte `think:false` — läcker rått
`<think>`-resonemang i `content`, oanvändbar som Jarvis-front utan vidare
arbete. `qwen3.5:9b` fortsatt långsam (22,7s snitt) och gav ett
osammanhängande svar även efter fixen.

**Rekommendation:** återanvänd `gemma4:e2b` som Jarvis-front istället för
en andra modell — löser samtidigt VRAM-trängseln (8 GB-kortet, daemonen
använder redan samma modell), Ollama tidsdelar en modell istället för att
ladda två. Avvägning: en fråga till Jarvis mitt i daemonens egen cykel får
kö-fördröjning, inte blockering.

**2026-08-24, senare session:** NVIDIA NIM tillagd som fjärde molnleverantör
i `ollama_client/client.py::_KNOWN_CLOUD_PROVIDERS` (`"nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY")`),
samma mönster som Groq/OpenRouter/Cerebras. `NVIDIA_API_KEY` tillagd i
`.env` (Björns build.nvidia.com-konto, gratis endpoint-tier). Verifierad
mot skarpt API med `nvidia/nemotron-3.5-lightning-30b-a3b` — 200 OK,
riktigt svar. Samma reasoning-modell-fallgrop som Groq hittades direkt:
modellen spenderar `max_tokens` på dolt `<think>`-resonemang innan den når
JSON/svar. **Redan löst, verifierat i efterhand samma session:**
`daemon/extractor.py`s `NOUSE_EXTRACT_CLOUD_MAX_TOKENS`-hantering (default
4096) är generisk — den villkoras av `model_uses_cloud_provider()`, som nu
känner igen `nvidia`-prefixet automatiskt eftersom det ligger i
`_KNOWN_CLOUD_PROVIDERS`. Omtestat med `max_tokens=4096`: `finish_reason:
stop`, riktigt svar tillbaka. **Men:** `nemotron-3.5-lightning-30b-a3b`
la 3326 av 4096 tokens på dolt resonemang för att svara "ja" på en
trivial fråga — gratis men långsam. Väg in svarstid, inte bara pris, vid
modellval för Jarvis-routing där latens känns direkt i samtalet.
Motivation: gratis exekveringskapacitet (58 gratis-endpoint-modeller,
40 anrop/min, ingen daglig gräns) för Björns planerade Jarvis-arkitektur
(lokal SLM-front + kod-router + NVIDIA/Groq för delegerad exekvering av
allt som INTE är forskning — forskningen stannar lokalt/Ollama per
uttrycklig regel). **Inte aktiverad i produktion, daemonen ej rörd.**
Städade också bort en dubblettrad `GROQ_API_KEY=` i `.env` (ofarlig,
samma värde två gånger).

**Session avslutad 2026-08-24 03:50 (tidigare pass).** Allt committat (`c1b9072` senast),
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
