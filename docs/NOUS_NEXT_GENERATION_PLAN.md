# Nous — plan för nästa generation

**Status: FAS 1 KLAR (2026-08-23).** Beslutsunderlag 2026-08-23. Kombinerar extern
forskning (Google, Nvidia, akademisk 2026-litteratur) med
neurovetenskapen i Björns egen uppsats *The Larynx Problem*.
Fas 1 är godkänd riktning och nästa konkreta arbete — väntar bara på
att faktiskt påbörjas i en session, inte på ett nytt beslut. Fas 2–3
väntar fortfarande på egna beslutstillfällen.

**Nästa konkreta steg (Fas 1, i ordning):**
1. [x] Lägg `valid_from`/`valid_until` + `supersedes`-relationstyp i schemat (Zep-mönster) — klart 2026-08-23: kolumner + migration i `field/surface.py` (`_migrate_relation_temporal_columns`), `add_relation()` sätter `valid_from` automatiskt, ny `supersede_relation()` stänger gamla relationen (`valid_until`) och skapar `new_tgt -[supersedes]-> old_tgt`. Exponerat i `/api/graph`-payloaden. 8 nya tester i `tests/field/test_relation_temporal.py`, alla 81 tester i `tests/field`+`tests/web` gröna.
2. [x] Gör `why`-fältet till en länkad kedja i stället för fritext (Eywa-mönster) — klart 2026-08-23: ny kolumn `derived_from` (relation.id) i schemat, `add_relation(..., derived_from=...)`, `supersede_relation()` sätter automatiskt den nya relationens `derived_from` till den relation den ersatte, och ny `relation_chain(relation_id)` går bakåt genom hela kedjan till roten. `why` kvarstår som den mänskligt läsbara motiveringen per steg — det som ändrats är att kedjan mellan stegen nu är en riktig länk (relation.id), inte bara text. Exponerat i `/api/graph`. 5 tester totalt i `tests/field/test_relation_temporal.py`, alla 83 tester i `tests/field`+`tests/web` gröna.
3. [x] Schemalägg `bisociative_solver.py` som återkommande bakgrundsuppgift, logga fynd — klart 2026-08-23: ny `scheduled_bisociation_pass()` hämtar grafens egna TDA-kandidater (`/api/bisoc`), formulerar dem som problem åt `solve()`, undviker att köra samma domänpar två gånger (`bisoc_explored_pairs.json`), och matar tillbaka fynd via `solve()`s befintliga `/api/ingest`-feedback. Kopplad in i `daemon/main.py`s cykel-loop (`cycle % NOUSE_BISOC_SOLVER_EVERY_CYCLES`, default var 48:e cykel, `asyncio.to_thread` så LLM-anropet inte blockerar loopen). Varje fynd loggas till forskningsjournalen via ny `write_bisociation_finding_event()`/`count_bisociation_finding_events()` i `daemon/journal.py`. 9 nya tester (`tests/tools/test_bisociative_solver_scheduled.py`, `tests/daemon/test_journal_bisociation_events.py`), 292 tester gröna totalt (3 förbefintliga fel saknar `mcp`-paketet, orört av detta arbete).

**Fas 1 färdig.** Alla tre steg klara 2026-08-23. Fas 2 (självhanterat minne, skopat minne, extern benchmarking) väntar på ett eget beslutstillfälle, inte en fortsättning i samma pass.

## Vad omvärlden faktiskt gör 2026 (verifierat, inte gissat)

- **Google Memory Bank** (Gemini Enterprise Agent Platform, I/O 2026): identitetsskopat minne över sessioner. Nous har ingen formell identitets-/skopgräns — allt ligger i en graf.
- **Nvidia AVO** (Agentic Variation Operators): persistent minne + övervakning + verktygsanvändning som ett system höjde Claude Opus 5 från 30% till 100% på ARC-AGI-3. Bekräftar tesen från idag: substratet runt modellen avgör mer än modellen själv.
- **Zep**: temporal kunskapsgraf — fakta har giltighetsintervall (`valid_from`/`valid_until`), inte bara sant/falskt för alltid. Leder benchmarken LongMemEval.
- **Letta** (f.d. MemGPT): agenten hanterar sitt eget minne — arkiverar, komprimerar, redigerar sina egna minnesblock. Nous `living_core` har drivkrafter/reflektion men ackumulerar bara, glömmer aldrig.
- **Eywa** (arxiv 2605.30771): proveniens som en **bakåtlänkad kedja**, inte en textrad — minne B härlett från minne A härlett från observation C. Möjliggör att spåra och uppdatera hela härledningskedjan om en källa visar sig fel.
- **MemGuard** (arxiv 2605.28009): minneskontaminering — obekräftade eller felaktiga minnen som förorenar senare resonemang — är ett erkänt, namngivet forskningsproblem 2026, inte en ovanlig invändning.
- **Standardbenchmarks**: LoCoMo, LongMemEval, BEAM. Nous har ingen extern jämförelsepunkt, bara intern självutvärdering.

## Vad den mänskliga hjärnan faktiskt gör (från Björns egen uppsats, verifierat mot neurovetenskap)

- **Kontinuerlig, gradvis inlärning** — synaptisk styrka justeras varje vaket ögonblick (long-term potentiation/depression). Inget "omträningstillfälle".
- **Minnen konsolideras under sömn** — korttidsminne flyttas till långtidsminne genom repetition av aktiveringsmönster (hippocampus → cortex), inte genom överskrivning.
- **Gradvis degradering, aldrig katastrofal överskrivning** — biologiskt minne bleknar genom interferens, försvinner aldrig i en enda kollaps som en ANN:s vikter kan göra.
- **Topologisk plasticitet, inte bara viktjustering** — genuin insikt (bisociation) kräver att **nya kopplingar bildas** i en arkitektur som inte redan innehöll dem, inte bara att befintliga stärks. Det är själva definitionen av kreativitet i uppsatsen.
- **Global Workspace Theory** — medvetande är konkurrerande representationer som vinner tillträde till en gemensam arbetsyta. Nous har `TypedGlobalWorkspace` beskrivet i arkitekturen men den körande instansen använder idag en enklare extraktionsloop, inte fullständig konkurrerande arbitrering.
- **Predictive coding / Free Energy Principle** (Friston) — hjärnan minimerar överraskning genom att ständigt jämföra förutsägelse mot verklighet. Nous `arousal`-signal är redan en enkel version av detta (Yerkes-Dodson), men det driver bara UI-glöd, inte faktiska minnesbeslut ännu.

## Prioriterad plan

### Fas 1 — Billigt, stänger verkliga luckor (närmast)
1. **Temporal giltighet** (Zep): lägg `valid_from`/`valid_until` + en `supersedes`-relationstyp i schemat. Utan detta kan grafen aldrig skilja "sant då" från "sant nu".
2. **Proveniens som kedja, inte textrad** (Eywa): `why`-fältet blir en länk till den relation/källa det härleddes från, inte bara fritext. Möjliggör bakåtspårning och korrigering i kaskad.
3. **Aktivera bisociation-motorn på riktigt**: kör `bisociative_solver.py` som en schemalagd bakgrundsuppgift (samma mönster som `nouse-daemon.timer`), logga genuina fynd. Det här är Nous enda verkliga skillnad mot Mem0/Zep/Letta — ingen av dem gör detta.

### Fas 2 — Kräver mer arbete, verklig strukturförändring
4. [x] **Självhanterat minne** (Letta + biologisk gradvis degradering) — klart 2026-08-23: ny kolumn `concept.dormant_since` (migration i `field/surface.py`), ny `consolidate_dormant_concepts()` tystar (raderar INTE) koncept som är äldre än `min_age_days` OCH aldrig fått en relation starkare än `strength_ceiling` — dvs. aldrig träffade av `strengthen()`. `add_concept()` väcker automatiskt ett dormant koncept så fort det berörs igen (reversibelt, som biologiskt minne som bleknar men aldrig försvinner i en kollaps), plus manuell `revive_concept()`. Detta är ett separat, mjukare spår vid sidan av `orchestrator/compaction.py`s befintliga hårda delete-baserade pruning — den ändrades inte. Kopplad in i daemon-cykeln (`cycle % NOUSE_DORMANCY_CONSOLIDATION_EVERY_CYCLES`, default var 20:e cykel), exponerad i `/api/graph`. 7 nya tester i `tests/field/test_dormancy_consolidation.py`, 299 tester gröna totalt (samma 3 förbefintliga miljöfel, orörda).
5. [x] **Skopat minne** (Google Memory Bank + Mem0) — klart 2026-08-23: ny kolumn `concept.scope` (`KNOWN_SCOPES` = personal_health/nous_system/research_plg/voice_notes/general, `SENSITIVE_SCOPES` = {personal_health}) i `field/surface.py`, formell gräns vid sidan av den fria `domain`-taxonomin. `add_concept`/`add_relation` tar `scope`/`scope_src`/`scope_tgt`, `set_concept_scope()` för manuell omklassning. **Faktisk enforcement, inte bara en tagg:** `domain_tda_profile()` (som matar `bisociation_candidates()` → `bisociative_solver.py` → extern LLM) exkluderar `SENSITIVE_SCOPES` som standard; `/api/context` (dokumenterat använd av "externa agenter") gör detsamma, med `include_sensitive: bool` för uttrycklig lokal override. Sökvägsbaserad `scope_from_path()` i `daemon/sources.py` taggar filer automatiskt vid ingestion (t.ex. `halsa-glp1/` → `personal_health`, `Work/nous/` → `nous_system`) — löser integritetsfrågan konkret, inte bara principiellt: Björns hälsodata kan nu strukturellt inte nå Cerebras/Ollama via bisociation-motorn eller `/api/context` utan uttrycklig override. 17 nya tester (`tests/field/test_scoped_memory.py`, `tests/daemon/test_sources_scope.py`, `tests/web/test_context_scope_filtering.py`), 316 tester gröna totalt (samma 3 förbefintliga miljöfel, orörda).
6. [ ] **Extern benchmarking** — pågående 2026-08-23, ej klar. `eval/longmemeval_adapter.py` byggd och rökt-testad mot oracle-datasetet (`eval/data/longmemeval_oracle.json`, 500 frågor, hämtat från `xiaowu0162/longmemeval-cleaned`). Isolerad `FieldSurface` per fråga (rör ALDRIG produktionsgrafen), återanvänder daemonens riktiga `extract_relations()`. **Hittat och olöst:** `lfm2.5` (5B, snabb) är för svag som domare — hallucinerade att "jag vet inte" matchade specifika facit ("nio månader", "43 år") i 2/2 testfrågor. `qwen3.5:9b` (IIC:s standardmodell) verkar korrekt GPU-accelererad (CUDA, 36/36 lager, `nvidia-smi` visar 88% util) men tog >120s för en enda fråga, sannolikt VRAM-trångt (7.6GB totalt, 2.4GB ledigt vid testtillfället — eviction-loggar i `journalctl -u ollama`). Ett obevakat smoke-test (`-n 2 --model ollama/qwen3.5:9b`) kördes i bakgrunden vid sessionsslut — resultat okänt, kolla `eval/results/` för en `longmemeval_*.json` med tidsstämpel efter 2026-08-23 22:12. **Nästa steg:** verifiera qwen3.5:9b-resultatet, avgör om VRAM-trycket är en engångskostnad (modellladdning) eller ett strukturellt problem, kör sedan en full delmängd (adaptern defaultar till n=24, stratifierat 4/kategori över 6 frågetyper).

### Fas 3 — Den verkliga arkitektoniska visionen (större, senare)
7. **Full konkurrerande arbitrering** (Global Workspace): de beskrivna `TypedProcessor`/`TypedGlobalWorkspace`-komponenterna aktiveras på riktigt, inte bara den enklare extraktionsloopen som körs idag.
8. [x] **Predictive coding driver faktiska beslut, inte bara UI — klar
   2026-08-24 i kod, INTE live än.** Tidigare drev noradrenalin (surprise)
   bara `limbic_spike_event` — ett UI-glöd, inget beslut
   (`daemon/main.py` "brain_sync"-blocket). Ny logik i `daemon/main.py`
   direkt efter limbic-cykeln: vid en **stigande flank** (inte "fortsatt
   högt" — noradrenalin decayar bara 20%/cykel, skulle annars trigga om
   och om igen) över `NOUSE_PREDICTIVE_SURPRISE_THRESHOLD` (default 0.75)
   byggs en seed-task av de domän-par som faktiskt utgjorde cykelns
   bisociation-kandidater (`_predictive_surprise_seed_task()`), köas via
   befintliga `enqueue_gap_tasks(..., detect_gaps=False)`, och en riktig
   HITL-interrupt skapas (`create_interrupt()` + `pause_task_for_hitl()`)
   — samma väg curiosity-loopen redan använder, inte en ny mekanism.
   Rent additivt: rör inte det befintliga `limbic_spike_event`-blocket.
   8 nya tester (`tests/daemon/test_predictive_surprise.py`), 328 tester
   gröna totalt (inga regressioner). **Kräver omstart av daemonen för att
   plockas upp — se STATUS.md "Planerade actions".**
9. [x] **Multi-timescale synaptisk styrka, slice 1 — klar 2026-08-24**
   (tillagd som kandidat 2026-08-23 efter genomläsning av Björns
   hjärndokument, se `docs/lab-notes/2026-08-23-brain-document-synthesis.md`).
   Ny kolumn `relation.strength_fast` + `strength_fast_updated`
   (`field/surface.py::_migrate_relation_multitimescale_columns()`) —
   den befintliga `strength` blir den långsamma/konsoliderade komponenten,
   **oförändrad**: `strengthen()`/`weaken()` uppdaterar den exakt som
   förut. Den nya `strength_fast` uppdateras vid samma anrop
   (`_bump_fast_strength()`), decayar exponentiellt med 6h halveringstid
   sedan senaste aktivering (`_decay_fast_value()`,
   `FAST_STRENGTH_HALF_LIFE_HOURS`), läses via `decayed_fast_strength()`.
   **Medvetet additivt/observationellt**: ingen befintlig läsväg
   (dormancy, pruning, `top_relations_by_strength`) konsulterar den än —
   att koppla in den där (slice 2) ändrar levande beslut i en körande
   daemon och kräver en egen verifieringsomgång, inte samma pass. 10 nya
   tester (`tests/field/test_multitimescale_strength.py`), 320 tester
   gröna totalt (inga regressioner). **Live sedan omstart 2026-08-24
   02:45 (PID 931901)** — migrationen bekräftad körd, 7056/7056
   relationer backfyllda, inga fel.
10. [x] **Energibudget** — klart 2026-08-24, **live sedan omstart
   2026-08-24 02:24** (PID 921187, bekräftad felfri: `energy_budget`
   loggas i cykel-raden). Ny `LimbicState.energy_budget` (`limbic/signals.py`), sjunker med `llm_calls` denna cykel (`sum(source_attempted_models.values())` i `daemon/main.py`), återhämtar sig 8%/cykel mot baslinjen 1.0 oavsett belastning — `update_energy_budget()`. Kopplad in på TVÅ ställen: (1) `run_limbic_cycle(..., llm_calls=...)` beräknar och persisterar den varje cykel, loggas i cykel-raden; (2) bisociation-motorns cykel-modulo-trigger (`cycle % BISOC_SOLVER_EVERY == 0`) har fått ett andra villkor, `limbic_state.energy_budget >= BISOC_SOLVER_MIN_ENERGY_BUDGET` (default 0.15, `NOUSE_BISOC_SOLVER_MIN_ENERGY_BUDGET`) — passet hoppas över och loggas explicit om budgeten är tömd, annars som förut. Curiosity-loopen är INTE kopplad in än (nästa steg om detta ska fortsätta). 8 nya tester (`tests/limbic/test_signals_energy_budget.py`).

## Vad detta INTE är

Det här är inte "bygg allt nu". Fas 1 är rimlig att göra i ett avgränsat pass.
Fas 2 och 3 är riktiga, men större — de förtjänar egna beslutstillfällen,
inte ett "kör allt" i slutet av en redan mycket lång session.

## Fas 3 — beslut 2026-08-23

Alla fyra punkter (7–10) godkända av Björn. Rekommenderad
byggordning, inte kronologisk ordning på listan:

1. **10 (energibudget)** — billigast, mest mekanisk, redan observerat
   konkret behov (VRAM-konflikt daemon vs. benchmark, 23/8 kväll). Ingen
   förutsättning behövs.
2. [x] **9 (multi-timescale strength), slice 1 — klar 2026-08-24.**
   Upplåst genom ett beslut om LongMemEval-grinden (se nedan), inte genom
   att grinden gav grönt ljus rakt av.
3. **8 (predictive coding som beslutsdrivare)** — hänger ihop med 9,
   naturlig uppföljare när arousal/strength-signalerna är skarpare.
4. **7 (full Global Workspace-arbitrering)** — störst, mest genomgripande.
   Sist, när 8–10 gett en tydligare bild av vad arbitreringen faktiskt ska
   arbitrera mellan.

## LongMemEval-grinden — beslut 2026-08-24

Grinden på punkt 9 var: "vänta tills LongMemEval faktiskt kör en full
delmängd och mäter kvalitet." Det är nu gjort (Fas 2 steg 6, se ovan):
bare=4,2%, nous=0,0%, n=24. Grundorsaken är identifierad, inte gissad:
`extractor.py`s `RELATION_TYPES`-vokabulär (modulerar, reglerar, orsakar,
konsoliderar, är_del_av, stärker, försvagar, producerar, synkroniserar,
oscillerar, är_analogt_med, motsäger, förnekar, beskriver) är byggd för
**tematiska/konceptuella relationer mellan idéer** — exakt vad Nous
faktiskt är till för (bisociationsmotorn, FNC-teorin, se
`docs/NOUS_STRATEGIC_DOCTRINE.md` och `FRONTIER_PLAN.md`). LongMemEval
testar **atomära personliga fakta ur vardagskonversation** ("hur många
dussin ägg har vi", "hur många år äldre är min mormor") — en annan
uppgift, inte en svagare version av samma uppgift.

**Beslut: bygg inte ett fakta/värde-extraktionsspår för att jaga
LongMemEval-poäng.** Det skulle optimera mot fel benchmark och späda ut
den faktiska differentiatorn (kors-domän-syntes) som hela
Frontier-planen står på. LongMemEval-resultatet räknas som grinden
uppfylld — inte som "Nous fungerar inte", utan som "fel mätsticka för det
här systemet." Den riktiga empiriska valideringen förblir TruthfulQA
(Fas 2, `FRONTIER_PLAN.md`, MC1/MC2 mot 8B-baseline) och FNC-bench
(`eval/fnc_bench/`, redan delvis kört 2026-04-17) — båda mäter
konceptuell/faktuell grundning, vilket är vad grafschemat faktiskt gör.
Det unlockar punkt 9: separationen fast/slow-styrka testas mot dessa
benchmarks framöver, inte mot LongMemEval.

Inget av punkterna 7, 8 påbörjat än.
