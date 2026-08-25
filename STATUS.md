# Nous — status

## 2026-08-25T15:00Z — Kritisk fix: aktivering/NightRun kunde höja evidence_score utan nytt bevis

Björn: "skickar en dialog till codex om hur ni tillsammans bäst uppnår
mina mål... målet är en plan" + "det är viktigt att ni debatterar,
ifrågasätter och konkurrerar för att få fram vem som har rätt." Ett
tredje, öppet relay:codex-samtal (2 rundor) om Nous hela riktning, inte
en avgränsad buggfråga. Full dialog: `IIC/04_SYSTEM/agents/
nous-codex-dialogue-2026-08-25-evidence-circularity.md`.

**Det viktigaste fyndet, verifierat av mig oberoende innan det
accepterades:** `activate_relation()` (aktiveras vid varje query-träff)
höjde `evidence_score` — samma fält `source_support`/
`parametric_hypothesis`-arbetet tidigare samma kväll bygger på — utan
något nytt oberoende bevis. En ren Hebbisk gissning kunde klättra över
`is_strong`-gränsen (0.75) genom 50 upprepade återhämtningar, noll ny
verifiering. Läste `_bump_evidence()` direkt för att bekräfta: skriver
rakt in i `relation.evidence_score`-kolumnen.

**Blast radius-kollen gav en viktig nyans:** `activate_relation()` och
`confirm_relation()` hade NOLL faktiska anropare — död kod, ofarlig
hittills. Den RIKTIGA, LIVE buggen satt i `run_evidence_pass()`
(NightRun-anropad): SQL:ens `WHERE`-sats begränsade redan raderna till
mitten-bandet, vilket gjorde promote/demote-grenarna i loopen
matematiskt onåbara — varje vald rad fick alltid samma ovillkorliga
`+0.01` per cykel, oavsett nytt bevis. Verifierat genom att läsa hela
funktionskroppen själv, inte antaget.

**Fixat (`src/nouse/daemon/evidence.py`):**
- `activate_relation()`: `_bump_evidence()`-anropet borttaget (höjer nu
  bara `strength`/salience, aldrig `evidence_score`). Samtidigt fixad:
  ett trasigt `rel_type`-argument (refererat i kroppen, saknades i
  signaturen — tyst `NameError` fångad av ett bart `except`).
- `run_evidence_pass()`: gjord till en avsiktlig no-op (fail-closed) —
  ingen automatisk promotion förrän en riktig bekräftelse-händelse-logg
  finns. Gammal, död kod RADERAD, inte kvarlämnad/omdöpt.
- 4 nya tester (`tests/daemon/test_evidence.py`). 516 gröna, 0 failed.

**Medvetet uppskjutet (Tier 2):** Codex sex-vägs-proveniens-taxonomi
(källobservation/modelltolkning/parametrisk hypotes/strukturellt
härledd hypotes/användarpåstående/verifierad-korroborerad) —
bekräftat kompatibel med dagens fix, inte byggd. Bisociation- och
Global Workspace-kritiken (citerad med radnummer, INTE oberoende
verifierad av mig på samma sätt) — trovärdig, egen framtida fråga.

**Den avgörande frågan och svaret:** ska `source_support` vara omutabel
under användning/topologi/modell-samstämmighet? Codex: entydigt ja.
Mitt svar efter egen verifiering: håller med — det är inte en
stilfråga, det är exakt garantin `parametric_hypothesis`-arbetet redan
skulle ge, som läckte igenom en väg ingen stängt.

## 2026-08-25T14:37Z — Codex-dialogens tre buggar fixade + kod-brus-filter, wiki omgenererad (commit 9ccc802)

Björn: "bygg det och åtgärda problemen som codex hittade; du kan be
codex fixa buggarna medans du bygger ut och förfinar." Arbetsdelning:
Codex skrev fix-koden för de tre buggarna det själv hittade (fortfarande
`--sandbox read-only`, skrev bara i sitt textsvar, ingen direktskrivning
till repot), jag byggde `is_code_only_concept()` parallellt och
granskade/tillämpade Codex kod efteråt.

**Tre Codex-fixade buggar, granskade och applicerade:**
- `concept_depth()`: räknar nu distinkta grannar, inte MultiDiGraph-
  kantrader. Verifierat oberoende mot den levande grafen INNAN Codex
  kod accepterades: ROOT hade 84 filtrerade rader men bara 15 distinkta
  grannar — matchade Codex siffror exakt.
- `concept_top_of_mind_score()`: exkluderar nu beroende-sökvägar,
  konsekvent med `concept_depth()`.
- `wiki_generator.py`: en delad `_is_qualifying_source_tag()`-regel
  (återanvänder `salience.looks_like_dependency_source()`) i stället
  för två olika, inkonsekventa filter — även `render_wiki_page()`s
  starka/osäkra-uppdelning använder nu samma regel.

**Byggt parallellt, mitt eget uppdrag:** `is_code_only_concept()` —
exkluderar koncept vars NAMNGIVNA bevis uteslutande är kodfiler, aldrig
någon gång förankrat i prosa. Björns ram: "Nous behöver förstå sin
egen uppsättning för att kunna utvecklas" — men det är arkitektonisk
självkännedom (redan inflödande via STATUS.md/designdokument), inte
råa kodsymboler. Hittade en riktig bugg i min EGEN första version via
riktig data, inte antaget: den räknade "auto"-taggade relationer
(obestämt ursprung, varken prosa eller kod) som bevis MOT kod-brus,
vilket skyddade ROOT trots att 100% av dess namngivna bevis var kod.
Fixat: bara namngivna relationer bedöms.

**9 nya/uppdaterade tester (Codex 4 regressionstester + mina egna),
512 gröna totalt.**

**Wiki omgenererad från grunden** (gamla exporten raderad först — helt
regenererbar, gitignorad, ingen anledning att försöka förena gammalt
med nytt när kvalificeringsreglerna ändrats i grunden):
**8702 → 590 kvalificerande sidor.** Stor minskning, verifierad inte
bara accepterad: stickprov visar riktigt, varierat innehåll (forsknings-
PDF:er, projekt-READMEs, IIC-dokument, `curiosity_loop`-taggat
material) — inte kollateral skada. `ROOT`/`text`/`str`/`Exception`
korrekt exkluderade. Finkornig precision bekräftad: `CONTEXT` (riktig
grund) behölls medan `Context`/`context` (samma slug, ingen grund)
exkluderades; `version` (ordet, riktig grund) behölls medan
`__version__`/`VERSION` (kodsymboler) exkluderades — filtret skiljer
på enskilda namn, inte en trubbig stoppslista.

**Inte löst, medvetet:** den bredare frågan om VARFÖR grafen har så
många kod-symbol-varianter i första taget (extraktorns 2200-tecken-
gräns, ingen kanonisering vid inskrivning) — Codex föreslog SKOS-
liknande alias-modellering som ett separat, större spår, inte byggt.

## 2026-08-25T14:05Z — relay:codex inkopplat, delegerings-svaret pollas nu tillbaka (commit 6707da3)

Föddes ur ett `@tanke`-samtal om att skicka en fråga till Codex i
bakgrunden för en andra åsikt, och en fråga om det hänger ihop med
eval-idén. Verifierat innan något byggdes, inte antaget: `jarvis-
policy.md` beskrev redan `relay:claude`/`relay:codex` som två skilda
executor-val, men `pipeline.py`s dispatch (`executor.startswith
("relay:")`) läste aldrig vad som stod efter kolonet — `open_relay_
executor()` hade inget `engine`-argument alls, spawnade alltid Claude.

**Byggt:**
- `spawn_codex_headless()` — samma säkerhetsnivå som den befintliga
  `spawn_claude_headless()`: `codex exec --sandbox read-only`
  (verifierat via `codex exec --help`) är Codex motsvarighet till
  Claudes plan-läge, ren läsning/analys, ingen sidoeffekt. `-o <fil>`
  ger en ren slutresultat-fil i stället för att behöva parsa en
  JSONL-händelseström.
- `open_relay_executor(..., engine="claude"|"codex")` — dispatchar nu
  faktiskt till rätt spawn-funktion. `pipeline.py` skickar igenom
  `executor`-strängens del efter kolonet.
- `check_relay_delegation()` — stänger luckan `spawn_claude_headless()`s
  egen docstring redan flaggade ("nothing polls it back into the relay
  session yet"). Kollar om processen avslutats (`os.kill(pid, 0)`),
  läser resultatet (Codex: `-o`-filen, Claude: `result`-fältet i JSON-
  loggen, verifierat mot en riktig `claude -p --output-format json`-
  körning samma dag), flyttar relay-sessionen till `relay_ready` —
  återanvänder ett statusvärde som redan fanns i schemat, ingen ny
  status uppfunnen.

**Verifierat end-to-end mot RIKTIGA processer, inte bara mockat:** en
riktig Codex-körning spawnad, väntat på att processen faktiskt
avslutades, `check_relay_delegation()` läste rätt resultat och flyttade
sessionen till `relay_ready` korrekt. En riktig `claude -p` testkörning
gjordes tidigare samma dag för att verifiera JSON-formen (kostade
~$0.08, litet men verkligt). Testartefakter (relay-sessionsfil,
scratch-katalog) städade bort efteråt.

8 nya tester (mockad subprocess/filsystem för de deterministiska
fallen), 500 gröna totalt.

**Inte gjort:** ingen ny agentkort/hårdregel i `jarvis-policy.md` —
detta ändrar inte auktoritetsnivån (fortfarande read-only/plan-läge på
båda modellerna), bara vilka modeller den redan existerande, redan
godkända mekanismen kan nå. Inget UI/kommando kopplar in
`check_relay_delegation()` i en faktisk polling-loop än — den finns och
är verifierad, men något (Jarvis-cykeln, ett CLI-kommando, eller Björn
manuellt) behöver faktiskt anropa den periodiskt för att "få tillbaks
insikten" ska hända utan att någon kommer ihåg att fråga.

## 2026-08-25T13:50Z — Första riktiga wiki-körningen mot den levande grafen, klar och verifierad

Björns "då kan vi starta den nu... sätt en lokal övervakning" — kört
manuellt (`scripts/run_wiki_generation.py`, read-only `FieldSurface`,
rör aldrig produktionsgrafen), loggat till `logs/`. INTE kopplad till
NightRun än (samma väntar-läge som tidigare).

**Två riktiga buggar hittade av övervakningen själv, båda fixade och
verifierade innan de lämnades:**

1. **Tyst 5000-koncept-trunkering** (commit `8e51ed9`): alla tre
   funktionerna i `wiki_generator.py` ärvde `get_concepts_with_metadata()`s
   `limit=5000`-default. Grafen har 21 000+ koncept — 75% hade tyst
   fallit bort, både ur domän/scope-uppslagningen och ur hela körningens
   omfattning. Aldrig synlig i tester (alla använde små syntetiska
   grafer). Fångad INNAN första körningen, inte efteråt.
2. **Slug-kollisioner** (commits `b92b5ae`, föregånget av ett ofullständigt
   första försök): verifierat att namn som bara skiljer sig i
   skiftläge/interpunktion (`Context`/`CONTEXT`/`context`,
   `__version__`/`_version`/`VERSION`/... — 7 namn) kollapsar till samma
   slug. Utan särskiljning skriver den sist bearbetade tyst över de
   tidigares filer — bekräftat av att första körningen rapporterade
   "8148 genererade" men bara 8052 riktiga filer fanns. Grundorsaken satt
   djupare än den första fixen: `should_regenerate()` läste OCKSÅ den
   krockande vägen oberoende, hittade en annan koncepts nyss skrivna fil,
   och drog slutsatsen "inget har ändrats" — hoppade över skrivningen
   INNAN särskiljningslogiken ens nåddes. Fånget av ett nytt
   regressionstest, inte av produktionskörningen (som redan hade körts en
   gång och sett fel, men skadan var bara i den statiska exporten, aldrig
   i grafen).

**Slutgiltig, verifierad körning (efter båda fixarna):**
- Första passet: 8148 sidor, andra passet (efter fixen, samma graf
  minuter senare): 680 nya/tidigare-kolliderade sidor, resten korrekt
  överhoppade (redan uppdaterade, `should_regenerate()` fungerar som
  tänkt).
- **8702 riktiga filer på disk, 8703 indexerade — verifierat direkt med
  `ls`, inte bara litat på skriptets egna räknare.** 558 filer har nu
  ett särskiljande hash-suffix (`--xxxxxx`), bekräftat att alla tre
  `context`-varianterna och `version`-familjen fick egna filer.
- Övervakningsskriptets egen avvikelselarm ("ANOMALY: generated=680
  indexed=8703, >50% divergens") **var en falsk positiv** — tog inte
  höjd för att en andra körning förväntas hoppa över det mesta
  (redan uppdaterat). Bekräftat genom att faktiskt räkna filerna, inte
  bara läsa larmet. Värt att förbättra heuristiken om skriptet körs
  igen, inte kritiskt nu.

**Kvarstående, känt, inte löst:** `generate_wiki_index()` gör sin egen
oberoende särskiljningsomgång i stället för att dela state med
`generate_wiki_pages()` — matchar i praktiken (samma körning, minimal
grafdrift mellan de två anropen) men är ingen hård garanti om grafen
muterar mycket mellan dem. Den djupare frågan om VARFÖR grafen har så
många kod-interna dubbletter (`__version__` m.fl.) i första taget är
inte adresserad — det är en extraktions-/ingestion-fråga, inte en
wiki-lager-fråga, ett eget framtida spår om det blir viktigt.

## 2026-08-25T13:34Z — Salience-modell (tid × use × djup) klar: top_of_mind_score i inject.py + wiki-index

Björns "kör" (två gånger — en för designrundan, en för byggstarten),
fortsättning direkt från wiki-lagret ovan. Design i
`IIC/04_SYSTEM/agents/nous-salience-model.md` (två designrundor, den
andra löste tre öppna frågor: djup on-demand/in-degree-baserad, formeln
är TVÅ axlar inte tre, `inject.py` kompletteras men ersätter aldrig
evidens-sorteringen).

**Byggt (lokal agent-delegering igen, `qwen3.5:9b`, HTTP-API,
`think:false` — samma metod som wiki-lagret, mindre friktion denna
gång: modulen blev klar på första försöket):**

- `src/nouse/daemon/salience.py` (ny modul): `looks_like_dependency_source()`,
  `concept_depth()`, `use_component()`, `recency_decay()`,
  `top_of_mind_score()`, `concept_top_of_mind_score()`. 11 tester.
- `field/surface.py`: `out_relations()`/`in_relations()` returnerar nu
  även `created` (fanns redan i NetworkX-grafens edge-data, bara inte
  exponerat) — samma additiva mönster som `valid_from`/`valid_until`
  fick tidigare samma session.
- `inject.py`: nytt fält `Axiom.top_of_mind_score`, beräknat i
  `_rows_to_axioms()` via en egen, medvetet DUPLICERAD (inte
  importerad) formel — modulen hade noll `nouse.*`-beroenden innan,
  har det fortfarande. Evidens-sorteringen (`axioms.sort(key=lambda a:
  -a.evidence)`) rörd INTE, exakt beslutet från designrundan. 1 nytt
  test (`test_inject_attach.py`).
- `wiki_generator.py`: sidor får nu `depth`/`top_of_mind_score` i
  frontmatter. Ny funktion `generate_wiki_index()` skriver
  `wiki/_index.md`, koncept rankade efter poängen — det här är steget
  som gör Björns poäng sann (wikin blir en ögonblicksbild, inte bara en
  lista). 3 nya tester.

**491 gröna, 1 skipped, 0 failed i hela sviten** (upp från 476).

**Verifierat mot riktig data igen, inte bara syntetisk:** `str`/
`Exception` (Python-inbyggda typer som läckt in via kod-ingestion) fick
in-degree 70/61 rått, 20/22 efter kodsökvägsfiltret — filtret fungerar,
men bara delvis: `ROOT`/`System`/`text` (57-84 rått) fick NOLL
reduktion — deras uppblåsthet kommer inte från kod-sökvägar utan
troligen generiska ord som legitimt förekommer i massor av riktigt
(icke-kod-) material. Känt, dokumenterat, inte löst — djup används
bara som informativ etikett, inte för rankning, så det korrumperar inte
den faktiska poängen. Björns egna forskningskoncept (PLG-modellen,
Perceptual Legitimacy Gap, capability debt) scorar ~0.92-0.93 på
top_of_mind_score — mekanismen känner igen riktigt aktivt använt
material korrekt, vilket är det som faktiskt spelar roll.

**Inte gjort:** ingen NightRun-inkoppling för `generate_wiki_index()`
än heller (samma väntar-på-skalbeslut-läge som `generate_wiki_pages()`
redan är i). Går att köra manuellt när som helst.

## 2026-08-25T12:42Z — Markdown-wiki-lager: byggt via lokal agent-delegering, NightRun-inkoppling väntar

Björns "skicka agenterna" — första riktiga test av att delegera kod-
skrivning till en lokal Ollama-modell (`qwen3.5:9b`, per `~/CLAUDE.md`s
"AI execution routing") i stället för att skriva allt själv, per
[[feedback_delegate_coding_to_local_agents]]. Bygger på designen i
`IIC/04_SYSTEM/agents/nous-wiki-layer-design.md` (nu uppdaterad med en
korrigering, se nedan).

**Metod:** Ollamas HTTP-API (`/api/generate`, `think:false` — CLI:t
`ollama run` fastnade i ett ändlöst `<thinking>`-resonemang första
försöket och kapade av innan någon kod alls skrevs). 5 anrop totalt:
huvudmodulen (avbröts på tokengränsen två gånger, patchad tillbaka
ihop), en riktad bugfix-runda, testfilen (samma mönster). Total
lokal-modell-tid: ~6 minuter.

**Levererat:** `src/nouse/daemon/wiki_generator.py` (6 funktioner) +
`tests/daemon/test_wiki_generator.py` (9 tester). 476 gröna, 1 skipped,
0 failed i hela sviten efter tillägget.

**Tre riktiga buggar hittade vid granskning av modellens kod (inte
gissade, körda/verifierade):**
1. Fel importsökväg (`from src.nouse...` i stället för `from nouse...`).
2. `out_relations()`/`in_relations()` slogs ihop till en lista och
   försökte sedan skiljas åt igen via `if rel.get("target")` — fungerar
   inte, `in_relations()`-rader har OCKSÅ en "target"-nyckel (satt till
   konceptets eget namn). Skulle ha producerat felformaterade rader för
   varje inkommande relation.
3. En `UnboundLocalError`-krasch när ett koncept har noll "starka"
   relationer (den vanliga vägen för nya koncept) — en `*_str`-variabel
   sattes bara i en av två grenar.
   Plus en fjärde jag hittade själv vid slutmontering: `f"{score:.2f}"`
   utan None-koll, trots att specen uttryckligen la relationer med
   `evidence_score is None` i just den gren som skulle formatera
   `score` som ett tal.

**En femte, allvarligare bugg — i den ursprungliga DESIGNEN, inte bara
implementationen:** tröskeln "minst en relation där `source_support is
not None`" visade sig vara verkningslös mot riktig data. Verifierat
direkt mot `~/.local/share/nouse/field.sqlite` (read-only): 0 av 26 647
relationer har `evidence_score IS NULL` — `add_relation()` beräknar
alltid ett riktigt tal, aldrig NULL, även när anroparen skickar
`evidence_score=None` explicit. 98% av alla relationer ligger redan på
≥ 0.75. En evidence_score-baserad tröskel filtrerar bort nästan
INGENTING. Bytte till `source_tag`-baserad kvalificering (namngiven
källa vs. det generiska `"auto"`-standardvärdet) — verifierat att detta
FAKTISKT diskriminerar: 8 005/20 544 koncept (39%) kvalificerar, mot
48–98% för vilken evidence_score-tröskel som helst. Detaljer och
konsekvenser: `nous-wiki-layer-design.md`s nya "Korrigering"-avsnitt.

**Bonusfynd under samma granskning, samma commit:** `.virtualenvs`
(virtualenvwrapper-katalogkonventionen) saknades i
`daemon/sources.py::DEFAULT_EXCLUDED_DIR_NAMES` — bara `.venv`/`venv`
fanns. Förklarar varför site-packages-filer (`httpx/_exceptions.py`,
`psutil/*`, etc.) läckt in som koncept-källor i den riktiga grafen.
Tillagd, plus en rad för `wiki/`-katalogen själv (annars läser Nous
förr eller senare in sina egna genererade sidor som om de vore ny
extern text — samma cirkel som designdokumentet redan varnade för).
Städar bara FRAMÅT, rensar inte redan ingesterade koncept.

**INTE gjort, medvetet:** NightRun-inkopplingen (skulle göra
sidgenerering automatisk varje cykel) är kvar. 8 005 sidor vid första
körningen är en hel del, och source_tag-granskningen avslöjade att en
del av det är utvecklings-brus (pip-paket-internals), inte riktig
kunskap — Björns beslut om det ska strama åt ytterligare innan det
körs automatiskt, inte mitt. `generate_wiki_pages()` går att köra
manuellt när som helst utan att röra daemonen.

## 2026-08-25T12:07Z — Brain View: anatomisk 3D-modell klar

Fortsättning av checkpoint 2:s öppna task ("Brain View: ersätt klotet med
en riktig anatomisk 3D-modell", Tududi `khjbjr8bspcffy5`/`5w1i6e060mx32qw`)
— nu klar. Björn laddade ner en hjärnmodell från Sketchfab (`.glb`, 8MB,
manuellt eftersom Sketchfabs download-API kräver ett inloggat konto) och
gav filvägen; resten byggdes och verifierades i den här passen.

**Byggt:**
- `three@0.155.0` slutade skeppa en global (icke-modul) `GLTFLoader` från
  r150+ — bara `examples/jsm/` (ES-modul) finns kvar. Löst i `index.html`
  med en `importmap` + en liten `<script type="module">` som hänger
  `GLTFLoader` på samma `window.THREE` som den klassiska `three.min.js`
  redan skapar. Resten av appen (`brain_view.js`, `3d-force-graph`)
  förblir vanliga scripts, ingen modul-konvertering. Kostnad: en andra
  Three.js-instans laddas parallellt (~600KB extra, syns som "multiple
  instances"-varning i konsolen) — accepterad avvägning, fungerar
  korrekt i praktiken.
- `brain_view.js::loadAnatomicalBrainModel()`: laddar modellen asynkront
  och ersätter sfär-fallbacken när den är klar — progressiv förbättring,
  ingen blank scen medan de ~8MB hämtas. Om laddningen misslyckas
  behålls sfären tyst (samma mönster som `loadTdaRegionPositions()`).

**Tre buggar hittade via skärmdump (Playwright + `--channel=chrome`),
inte antagna:**
1. `depthWrite:false` på en tät, vikt yta (tusentals överlappande
   gyri/sulci) blandar ihop alla lager till en formlös dis vid rendering
   — såg först ut som en skalningsbugg, var det inte. Fix:
   `depthWrite:true`, opacity 0.5→0.8.
2. Skalning mot "längsta axeln" (modellens Z mot gamla sfärens Z=264)
   missade att modellen är proportionerligt rundare än den handgjorda
   0.85/1.2-sträckta sfären var — Y-axeln blev ~30% högre än sfären
   någonsin var, fyllde hela bildrutan vertikalt. Fix: contain-fit mot
   alla tre axlarna samtidigt (sfärens fulla mått 220×187×264,
   `scale = min(...)` över alla tre kvoter, inte bara en).
3. Modellen är rent reflektionsbelyst (ingen `emissive`), till skillnad
   från regionsfärerna som är self-lit — scenens point lights var för
   svaga/vinkelberoende (tänkta för en nästan osynlig 0.08-opacity-
   sfär), så sidan som inte mötte ett ljus vid given rotationsfas blev
   nästan svart. Fix: högre ljusintensitet, ett tredje kameranära ljus,
   och ett lågt `emissive`-golv (0x3a2620 @ 0.45) så formen syns
   oavsett rotationsvinkel.

**Verifierat, inte antaget:** filens tre GLB-noder (`BRAIN`, `cerebellum`,
`BRAIN_LOW`) gav först en bounding box som såg trasig ut. Isolerad
rendering (tillfällig `_debug_inspect.html`, borttagen igen efteråt)
visade att alla tre är legitima anatomiska delar — cortex, cerebellum,
hjärnstam (materialnamnet bekräftar `BRAIN_STEM_1002` trots att
nod-namnet bara säger "BRAIN"). Alla tre används i den slutgiltiga
modellen.

**Inte löst, medvetet:** en identisk `console.error 404` syns i alla
körningar, även i den allra första före några ändringar — men matchar
ingen nätverksrespons Playwright kan se (varken `response`- eller
`requestfailed`-lyssnare fångar den). Sannolikt en ofarlig
favicon-request, inte kopplad till modellen: alla texturer är
embeddade som `bufferView` i själva `.glb`:n, inte externa `uri`
(verifierat direkt i filens JSON-chunk). Inte spårat vidare.

**Öppen fråga till Björn, inte mitt beslut:** `models/human_brain.glb`
är `.gitignore`:ad i stället för committad. `Work/nous` är ett publikt
GitHub-repo och jag vet inte vilken licens den specifika Sketchfab-
modellen har för vidaredistribution. Servern fungerar identiskt lokalt
oavsett (filen ligger redan på disk), och `brain_view.js` faller
tillbaka till klotet om filen saknas — så det här blockerar inget, men
avgör om andra som klonar repot ser klotet eller den riktiga modellen.

**Kvar från checkpoint 2, oförändrat läge:** markdown-wiki-lagret
(design klar i `IIC/04_SYSTEM/agents/nous-wiki-layer-design.md`, väntar
"kör" för bygge) och ablations-sweepen (redo, väntar på N + "kör").

## CHECKPOINT 2 `2026-08-25T11:22Z` — tag `checkpoint-2026-08-25-brain-visualization`, commit `e509fcc`

Skriven för att contexttönt närmar sig och en compact är nära. Fortsättning
från checkpoint 1 nedan — allt tekniskt är committat (`git status` rent
förutom två filer som aldrig var mina). Efter checkpoint 1 hände två spår:

**Filosofiskt/design (inget kodat, tre nya IIC-dokument i
`04_SYSTEM/agents/`):** ett långt samtal om Nous grundvision landade i
`nous-prediction-and-validation-model.md` (koherens vs. korrespondens,
ekokammare i två former, distrikt-påfyllnadsloop, kopplat till Björns
egen "Larynx Problem"-tes). En session-note-mall etablerades
(`04_SYSTEM/sessions/`, yaml+id+tid+oneliner+summering).

**Tekniskt UI-fynd, inte kod ännu:** upptäckte att Nous redan har ett
levande, interaktivt 3D-webbgränssnitt (`http://127.0.0.1:8767`,
Three.js) med flera lägen (Concept Atlas, Domain Blocks, Ripple Pulse,
Thread Path, **Brain View**, Tools) — screenshotat och läst koden
(`web/static/brain_view.js`). Brain View använder redan riktiga 3D-
regioner (x/y/z, glow, live data) men "hjärnan" är en generisk
`THREE.SphereGeometry`, ingen anatomisk form. Läste sedan
neurotorium.org:s neurobiologi-grundkurs och korsade den mot
`daemon/brain_atlas.py` + `LimbicState`
(`nous-neurobiology-grounding.md`): signalämnena (dopamin/noradrenalin/
acetylkolin) är grundade i verklig neurovetenskap, men `basal_ganglia`
(den riktiga platsen för belöningsdriven vanebildning — direkt kopplat
till dagens `strengthen()`/`weaken()`-resonemang) och `thalamus` saknas
helt i regionlistan.

**Tre nya Tududi-tasks i Nous-projektet (inga körda än):**
1. Ablation-sweepen (n=40/60/100, verifierat modellpar, väntar "kör")
2. Brain View: ersätt klotet med en riktig anatomisk 3D-modell (2 subtasks)
3. Lägg till `basal_ganglia`/`thalamus` i `brain_atlas.py`

**Även gjort:** `IIC/01_PROJECTS/nous/STATUS.md` skapad (Nous saknade
helt en ingång i Björns egen projektöversikt — hittat vid en verktygs-
genomgång på Björns begäran). En visuell roadmap-artifact publicerad.
Ett minne sparat om Björns kognitiva profil (ADHD/autism/dyslexi,
grundat i `PERSON.md` — påverkar hur allt framåt bör presenteras:
visuellt, en rekommendation i taget, inte flera alternativ).

**Näst i tur, ingen ordning påtvingad:** något av de tre Tududi-tasksen
ovan, eller fortsätta det filosofiska spåret. Inget är blockerat.

## CHECKPOINT 1 `2026-08-25T09:05Z` — tag `checkpoint-2026-08-25-frontier-cleanup`, commit `007047b`

Björn bad om en summering med tidsstämpel och ID innan sessionen
fortsätter — se git-taggen ovan för exakt återvändspunkt
(`git checkout checkpoint-2026-08-25-frontier-cleanup`).

**Startpunkt:** ChatGPT:s repo-validering av `base76-research-lab/Nous`
(P0–P3-lista) + frågan "hur blir Nous hela systemets hjärna, över både
Computer och IIC?"

**Gjort, i ordning (12 commits, `565228a`..`007047b`):**
1. Strategidokument (`FRONTIER_PLAN.md` m.fl.) avpublicerade från det
   publika repot.
2. Confidence/evidence-terminologin omskriven — `source_support`,
   `provenance_class`, `confidence_breakdown`; domain_bootstrap-cirkeln
   stängd med ett evidens-tak.
3. Ablation-scaffolding byggd (`eval/ablation.py`) — fem-stegs
   ablationstrappa, riktig vector-RAG-baseline, riktig long-context-
   baseline.
4. **Säkerhetsfynd + fix:** `research_plg` saknades i `SENSITIVE_SCOPES`
   — 14 846 av 15 037 koncept (98,7%) var oskyddade mot att skickas till
   Cerebras/OpenRouter via bisociation. Backfillat och verifierat live
   (`/api/context` för "PLG" gick från fullt kontextblock till tomt).
5. Occipital-regionen fick riktigt källmaterial (PCPE, bekräftat av
   Björn).
6. Agent-pipelinens `_touches_research()` delar nu mekanism med grafens
   scope (en tidigare felaktig anteckning om att "PLG" inte skulle
   fångas rättad — `.env` hade redan täckt det, problemet var
   strukturellt: en lista som glider ur synk, inte det specifika
   exemplet).
7. `nous-agency-model.md` (IIC, inte publikt repo) — designdokument för
   handlingslagret, Axel 1 implementerad, Axel 2/3 fortfarande bara
   förslag.
8. Genererare+domare-par för sweepen verifierat mot riktiga NVIDIA-API:et
   (inte antaget): `nemotron-3.5-lightning-30b-a3b` +
   `nemotron-3-ultra-550b-a55b`. Två kandidater föll bort i test.
9. Första riktiga sweep-försöket (n=40) hängde sig — CLOSE_WAIT-buggen
   från 2026-08-24 reproducerades trots gårdagens "fix". Processen
   dödad, ingen resultatfil skriven. `keepalive_expiry`-fix insatt.
10. **Pågående just nu:** stresstest av fixen (10 sekventiella riktiga
    anrop) visar INTE hängningsbuggen längre (inga CLOSE_WAIT, rena
    anslutningar) — men avslöjade ett separat, nytt problem: den valda
    "nano"-modellen (`llama-3.1-nemotron-nano-8b-v1`, endast använd i
    detta stresstest, inte i sweep-planen) timeoutar konsekvent på ~30s.
    Ej sweepens faktiska modeller — inget som blockerar den riktiga
    körningen.
11. Obuffrad loggning + tydligare felmeddelanden (`_describe_exception`)
    — direkt orsakad av att jag inte kunde se om sweepen hade hängt sig
    eller bara jobbade långsamt.
12. Städat bort ~600 MB temporära test-snapshots ur `eval/results/`.

**Ej gjort än:** checkpointing/resume för långa sweepar (efterfrågat,
inte byggt), begränsad parallellitet, extern vakthund. Den riktiga
n=40-sweepen är inte körd färdigt — startpunkten för nästa steg.

**2026-08-25, genererare+domare-par för den riktiga sweepen verifierat mot
NVIDIA:s API på riktigt, inte gissat:**

Björn bad om två separata modeller (en genererar, en dömer/validerar) i
stället för att en modell dömer sig själv, och att jag faktiskt
verifierade valet i stället för att gå på antaganden. Testade tre
kandidater direkt mot `https://integrate.api.nvidia.com`:

- `openai/gpt-oss-120b` — **trasig via NVIDIA:s API**, timeout efter 90s,
  inget svar alls. Skulle ha spenderat pengar på genereringsanrop utan
  att producera en enda giltig dom i en riktig körning.
- `meta/llama-3.3-70b-instruct` — 503 "ResourceExhausted", överbelastad
  på gratisnivån.
- `nvidia/nemotron-3-ultra-550b-a55b` — fungerar, men 1 av 4 anrop gav
  samma 503 innan fixen nedan.

**Bifynd, fixat samtidigt:** `_resolve_provider()` i `run_eval.py`
antar att alla NVIDIA-modeller heter `nvidia/något` — tredjepartsmodeller
i katalogen (`openai/...`, `meta/...`, 100+ modeller totalt) routas fel.
Inte fixat — inte blockerande för valet ovan (som är `nvidia/`-prefixat),
flaggat som en känd begränsning.

**Fixat:** `call_llm()` retry:ade bara 429, inte 503 — samma transienta
kapacitetsproblem, borde behandlas lika. La även märke till och fixade en
latent bugg: uttömda 429-retries föll igenom till `data["choices"][0]`
med `data=None` och kastade ett kryptiskt TypeError i stället för ett
läsbart felmeddelande. 4 nya tester (mockade, inga riktiga anrop).
Verifierat efteråt mot riktiga API:t: 3/3 domar-anrop lyckades rent genom
hela harnesset efter fixen.

**Slutgiltig, verifierad konfiguration för den riktiga sweepen:**
- Genererar: `nvidia/nemotron-3.5-lightning-30b-a3b`
- Dömer: `nvidia/nemotron-3-ultra-550b-a55b`
- Reservation: Ultra är läromästaren Lightning destillerades från (samma
  familj) — inte helt oberoende, men det enda av tre testade alternativ
  som faktiskt fungerar pålitligt.

**2026-08-25, ablation-sweepen mekaniskt validerad gratis lokalt — redo
för riktig körning, inte körd på riktigt än:**

Föregick av en riktig bugg: `vector_rag`-villkoret hade kraschat tyst i
en betald körning — `OllamaEmbedder()` föll tillbaka på
`nomic-embed-text-v2-moe:latest`, inte pullad här, när skriptet körs
fristående (daemonens systemd-enhet sätter `NOUSE_EMBED_MODEL` men
`.env` gjorde det inte). Fixat: `NOUSE_EMBED_MODEL=nomic-embed-text:latest`
tillagt i `.env` (ej i git, redan skyddad fil). Verifierat mot en färsk
snapshot av produktionsgrafen (17 450 koncept): embedding + query gav
vettigt resultat.

Kört därefter: `truthfulqa_adapter.py -n 3 --model gemma4:e2b` (lokal,
gratis), alla 11 villkor. Inga krascher, ingen tyst fallback, isolerad
snapshot bekräftat använd (inte produktionsgrafen direkt). Resultatet
(`eval/results/setup_validation.json`) är **mekanisk validering, inte
evidens** — n=3, samma lilla lokala modell som både svarar och dömer sig
själv, siffrorna studsar som väntat och betyder ingenting om Nous
faktiskt hjälper. Poängen var att bevisa att rörledningen fungerar innan
en betald körning, inte att mäta något.

Grov kostnadsuppskattning för en riktig körning (alla 11 villkor,
`estimate_run_cost_usd()`, inte fakturaexakt): Groq/NVIDIA ~$0.17–0.41
för n=40–100, Cerebras ~$0.34–0.85. Väntar på Björns "kör" — se Tududi-
tasken "Introduktionsmail om Nous till X" för den villkorade planen
(kör sweepen → tvätta resultat → gate → mail).

**2026-08-25, agent-pipelinens research-local-koll delar nu mekanism med
grafens scope (Axel 1, IIC/04_SYSTEM/agents/nous-agency-model.md):**

`_touches_research()` i `agent_system/pipeline.py` anropade tidigare bara
en manuellt underhållen nyckelordslista (`.env`s
`NOUSE_RESEARCH_LOCAL_MARKERS` — redan välfylld, inklusive "plg", en
tidigare notering om att PLG inte skulle fångas var fel och rättad i
IIC-dokumentet). Problemet var strukturellt: listan glider ur synk när
nya forskningsämnen tillkommer. Anropar nu även `scope_from_path()`
(samma funktion som skyddar grafen) direkt på request-texten, som ett
andra oberoende villkor — fångar `research_plg`/`iic_general` specifikt,
inte hela `SENSITIVE_SCOPES` (personal_health/user_model/computer_general
styrs av andra regler). 5 nya tester
(`tests/agent_system/test_pipeline_research_guard.py`), 463 passed totalt.
`research-guard/AGENT.md` uppdaterad i samma pass så dokumentation och
kod stämmer överens.

Medvetet kvar: matchning mot projektnamn i `01_PROJECTS/*` kräver riktig
path-resolution i stage 01/02 (`routing_decision.json` har bara fri text
idag) — separat, större ändring.

**2026-08-25, scope-backfill applicerad och verifierad live:**

`scripts/backfill_concept_scope.py --apply` kört mot produktionsgrafen.
14 505 av 14 849 general-scopade koncept omklassificerade (7 888
`iic_general`, 5 110 `computer_general`, 1 054 `nous_system`, 453
`user_model`); 271 var faktiskt allmänna, 73 saknade spårbar källa. Kvar på
oskyddat `general`: 344 (ner från 14 846). Verifierat direkt mot den
körande daemonen: `POST /api/context {"query":"PLG"}` gav innan fixen
fullt kontextblock med PLG-forskningen, ger nu `context_block: ""`,
`nodes: []`. Ingen omstart behövdes — scope läses live från SQL.

**2026-08-25, säkerhetsfynd under "hela systemets hjärna"-diskussionen:
`research_plg` saknades i `SENSITIVE_SCOPES` — fixat i kod, INTE live än:**

- Björn frågade hur Nous blir "hela systemets hjärna och medvetande" (både
  Computer och IIC). Innan jag byggde vidare på det verifierade jag vad
  daemonen som redan bevakar hela hemkatalogen faktiskt exponerar externt.
- **Fynd:** `field/surface.py::SENSITIVE_SCOPES` innehöll bara
  `personal_health`/`user_model` — INTE `research_plg`. `/api/context` och
  `bisociative_solver.py::scheduled_bisociation_pass()` (default aktiverad
  via `BISOC_SOLVER_ENABLED`, körs periodiskt i huvudloopen,
  `daemon/main.py` rad ~1622) exkluderar bara `SENSITIVE_SCOPES` innan de
  skickar grafinnehåll till Cerebras/OpenRouter. Björns faktiska akademiska
  forskning (`research_plg`-scopat) var alltså berättigad att skickas
  externt — i strid med den tidigare uttalade regeln att IIC-forskning
  aldrig lämnar disken utan explicit tillåtelse.
- **Verifierat, inte gissat:** körande daemon-processen (PID 1314833) har
  riktiga `CEREBRAS_API_KEY`/`OPENROUTER_API_KEY` laddade (`.env` via
  `EnvironmentFile=` i den installerade systemd-enheten + `nouse/__init__.py`s
  ovillkorliga `load_env_files()`) — mekanismen är alltså live, inte
  teoretisk. Journalen för den aktuella daemon-körningen (sedan
  2026-08-24 16:09:58) visar dock INGEN faktisk "Bisociation-pass:
  N par utforskade"-rad än — bara `GET .../models`-anrop (modell-lista, inte
  chat completion). Så vitt loggen visar har inget skickats ännu i den här
  körningen, men mekanismen var laddad och riskerade att göra det.
- **Kodfix (klar, committad, INTE live förrän omstart):**
  1. `research_plg` tillagd i `SENSITIVE_SCOPES`.
  2. Computer/IIC-uppdelningen från `~/CLAUDE.md` gjord explicit i
     scope-systemet: två nya scopes, `iic_general` (allt under `~/IIC/`
     utan egen regel) och `computer_general` (allt annat i hemkatalogen
     utan egen regel) — båda sensitiva som standard, i stället för att
     tyst falla på det gamla oskyddade `"general"`.
  3. `scope_from_path()` i `daemon/sources.py` uppdaterad i samma ordning
     (specifika regler går fortfarande före zon-fallbacken).
  4. 9 nya/uppdaterade tester (`tests/field/test_scoped_memory.py`,
     `tests/daemon/test_sources_scope.py`) — inklusive ett funktionellt
     test som bevisar att en `research_plg`-scopad koncept faktiskt
     exkluderas av samma anropsform `/api/context`/bisociation använder,
     inte bara att scopet finns i en mängd.
- **Planerad action (kräver Björns explicita "kör", separat från
  scope-taxonomi-uppdraget ovan):** starta om `nouse-daemon` för att denna
  fix ska ta effekt på den körande daemonen. Risk: låg (samma mönster som
  tidigare omstarter i den här loggen, additiv scope-utökning, ingen
  schemamigration). Verifiering efter omstart: kontrollera att en
  `research_plg`-scopad koncept inte längre kommer med i ett
  `/api/context`-svar.
- **Fullständig svit:** `pytest tests/` → 450 passed, 1 skipped.

**2026-08-25, occipital-regionen får äkta källmaterial (Tududi-subtask 1):**

- Ingen katalog routades tidigare till `occipital_lobe` alls (varken via
  `daemon/sources.py::_domain_from_path()` eller `brain_atlas.py`) — inte
  en fråga om att byta ut syntetiskt material, utan frånvaro av routning.
  Björn bekräftade (fråga ställd, inte gissad) att hans eget
  perceptionsforskningsspann PCPE ("Perceptual Coherence and Perceived
  Exclusion", `IIC/02_LIBRARY/RESEARCH/papers/preprints/` +
  `papers/ongoing/PCPE/`) är rätt material.
- `_domain_from_path()` returnerar nu `"perception"` för PCPE-sökvägar
  (matchar `occipital_lobe`s `domain_keywords` i `brain_atlas.py`, verifierat
  direkt: `classify_domain("perception") == "occipital_lobe"`), placerat
  före den generella research/paper-regeln så det inte fångas som
  "AI-forskning" i stället.
- **Ingen daemon-/systemd-åtgärd behövdes.** Den installerade
  `~/.config/systemd/user/nouse-daemon.service` sätter redan
  `NOUSE_WATCH_EXTRA_PATHS=/home/bjornwikstrom` (verifierat direkt i
  filen) — hela hemkatalogen, IIC inkluderat, bevakas redan. Nästa
  fil-ingestion av PCPE-materialet (daemonens vanliga bevakningscykel,
  ingen manuell trigger) routar det till occipital utan vidare åtgärd.
- Ny testfil `tests/daemon/test_sources_domain.py` (4 tester, gröna) —
  täcker både path→domain-mappningen och hela kedjan till
  `occipital_lobe`.
- Repots committade `systemd/nouse-daemon.service`-mall är fortfarande
  inaktuell mot den installerade (annan user, andra sökvägar, andra
  modellnamn) — inte fixat i den här passen, flaggas som en separat,
  icke-gated dokumentationsstädning.

**2026-08-25, Fas 3 punkt 7 (Global Workspace): status löst, designskiss
gjord, IKKE byggd:**

- **Punkt 8-motsägelsen (rad ~567 nedan säger "INTE live än", rad ~447
  säger "klar ... PID 936012") är löst med en read-only koll, inte en
  gissning.** `systemctl --user status nouse-daemon.service` visar
  körande PID 1314833, uppe sedan 2026-08-24 16:09:58 — en SENARE omstart
  än 02:53-omstarten som aktiverade punkt 8. Rad 567 är en äldre logg-post
  som aldrig markerades inaktuell efter att omstarten faktiskt hände;
  ingen indikation i loggen om att punkt 8 reverterats däremellan.
  **Slutsats: punkt 8 är live**, och har överlevt minst en omstart sedan
  dess. Per Björns egen 10→9→8→7-ordning (beslut 2026-08-23) är punkt 7
  därmed tekniskt olåst — se nedan för vad som ändå gör att den inte
  byggs i den här passen.
- **Designskiss för punkt 7 (ingen kod ändrad):** dagens
  `orchestrator/global_workspace.py::GlobalWorkspace.competition_step()`
  (Hopfield WTA + lateral inhibition, se docstring där) är redan riktig
  och oförändrad-värd — det som saknas är att `conductor.py::
  run_cognitive_cycle()` Steg 6 (rad ~475-506) bygger sina tre
  `WorkspaceProposal` (episodic_memory, tda_bisociation,
  limbic_homeostasis) som en hårdkodad listlitteral i stället för att
  samla in dem dynamiskt. Föreslagen väg, i tre separat granskningsbara
  steg:
  1. Inför en `TypedProcessor`-protokoll (`async def propose(self, ctx)
     -> WorkspaceProposal | None`) och en registreringsmekanism på
     `GlobalWorkspace` (`register_processor()` / `collect_proposals(ctx)`
     som `asyncio.gather`:ar alla registrerade processorers `propose()`,
     med per-processor try/except så en trasig processor inte kraschar
     hela cykeln).
  2. Rena refactor: linda dagens tre hårdkodade förslag som tre konkreta
     `TypedProcessor`-klasser, byt `run_cognitive_cycle`s Steg 6 mot
     `proposals = await self.workspace.collect_proposals(ctx)`.
     Beteende ska vara identiskt före/efter — ren strukturell ändring,
     verifierbar med befintliga conductor-tester.
  3. Lägg till nya processorer en i taget (predictive-surprise/punkt 8,
     curiosity/goal-directed, ev. kamera/occipital) som egna, separat
     granskade steg — inte i samma omgång som steg 1-2.
- **Varför detta inte byggs nu:** Björn beskrev punkt 7 själv som "störst,
  mest genomgripande" och lade den sist medvetet (se
  `docs/NOUS_NEXT_GENERATION_PLAN.md` rad ~95-108). Steg 2 och 3 ovan
  ändrar vad som faktiskt körs i produktionscykeln och kräver en
  daemon-omstart för att bli live — det är precis den typen av åtgärd som
  enligt CLAUDE.md alltid kräver ett explicit "kör" i sessionen, inte bara
  en allmän "fria händer att bygga"-instruktion. Steg 1-2 (protokoll +
  ren refactor) skulle kunna byggas och committas utan gate om Björn vill
  det som nästa steg — de ändrar inte cykelns beteende.

**2026-08-25, ablation/controlled-baseline scaffolding (P1/P2, ej körd):**

Byggt utifrån samma 2026-08-25 repo-review: infrastrukturen för det
föreslagna "North Star"-experimentet (LLM only / long context / vector RAG /
Nous graph only / +evidence / +temporal validity / +contradiction /
+plasticity / full Nous). Inget betalt LLM-anrop har gjorts i den här passen.

- Nytt: `eval/ablation.py` — `NousFeatureConfig` (fyra oberoende flaggor:
  evidence/temporal_validity/contradiction/plasticity) plus en byggstege av
  fem namngivna configs, `get_nous_context_ablated()` som slår av/på exakt
  en mekanism i taget, `get_long_context_baseline()` (hela grafen, ingen
  retrieval) och en **verklig** `vector_rag`-baseline (lokal Ollama-
  embedding + cosine top-k via samma embedder Nous själv använder för
  bisociation — inte en hårdkodad textblob som gamla `rag`-villkoret).
- `benchmark_protocol.CONDITIONS` utökad med de sex nya villkoren.
- **Isoleringsbrott fixat:** `truthfulqa_adapter.py`s `nous`-familj läste
  tidigare live-produktionsgrafen direkt (`FieldSurface(read_only=True)`,
  inget `db_path`). Ersatt med `snapshot_production_field()` — en säker
  `sqlite3 .backup()`-kopia (inte en rå filkopia, som kan missa WAL-data)
  till en isolerad temp-path, öppnad `read_only=False` eftersom det är en
  privat kopia (annars körs varken schemamigrationer eller embedding-cache,
  se kommentar i koden — hittat via en snapshot-baserad smoke-test mot den
  riktiga grafen, 14 509 koncept, ingen live-skrivning).
- Bifynd samma väg: `nous_meta`-villkoret fick aldrig `field` (villkoret
  saknades i den gamla `if "nous" in conditions`-checken) — fixat som en
  del av samma omskrivning.
- **Kostnadsspärr:** `run_eval.py::estimate_run_cost_usd()` (grov
  ordning-av-storlek-uppskattning, ej billing-exakt) + `--max-cost`/
  `--i-understand-the-cost` i `truthfulqa_adapter.py`. Verifierat: en
  11-villkors-sweep med lågt `--max-cost` vägrar starta innan någon
  fält-laddning eller modellanrop sker.
- Verifierat: `pytest tests/` → 438 passed, 1 skipped (409 tidigare +
  32 nya tester för ablation/cost-estimate/confidence-breakdown över de
  senaste två passen). `--dry-run` byggde manifest för alla 11 villkor
  utan fel.
- **Kvar, medvetet inte gjort i den här passen:** att faktiskt köra
  sweepen (kostar riktiga pengar — kräver Björns "kör"), och den upptäckta
  `NOUSE_GRAPH_EMBED_MODEL`-defaulten (`nomic-embed-text-v2-moe:latest`)
  matchar inte vad som faktiskt är pullat i Ollama här (`nomic-embed-
  text:latest`, utan `-v2-moe`) — påverkar troligen produktionens
  bisociation-embedding tyst redan idag (`_get_embedder()` sväljer felet
  och stänger av embedding för den instansen), inte bara `vector_rag`.
  Fixa genom att antingen pulla v2-moe-modellen eller sätta
  `NOUSE_GRAPH_EMBED_MODEL=nomic-embed-text:latest` — inte gjort här
  eftersom det är en bredare produktionsinställning, inte scopad till
  eval-arbetet.

**2026-08-25, strategidokument avpublicerade:**

- `FRONTIER_PLAN.md` och `docs/FRONTIER_VISIBILITY_PLAN.md` är borttagna ur
  git (`git rm --cached`) och tillagda i `.gitignore`. Båda innehöll
  förhandlingsstrategi och audience-/attention-mappning ("frontier-bolag
  slåss om Nous", patent-resonemang) som en extern reviewer (ChatGPT,
  repo-validering 2026-08-25) flaggade som olämpligt att exponera publikt —
  en potentiell köpare eller arbetsgivare behöver inte se förhandlingsplanen.
  Filerna finns kvar oförändrade lokalt, bara avpublicerade.
- `docs/NOUS_STRATEGIC_DOCTRINE.md` och `docs/NOUS_NEXT_GENERATION_PLAN.md`
  (fortsatt publika) nämner `FRONTIER_PLAN.md` som källdokument i löptext —
  inga brutna länkar (ren textreferens, ingen hyperlänk), lämnade orörda.
- Kvar: committa borttagningen.

**2026-08-25, benchmark v1 protocol setup completed, awaiting review:**

- Added `eval/benchmark_protocol.py` and wired it into
  `eval/truthfulqa_adapter.py`. The protocol records dataset hash, full commit,
  package version, model/provider, prompts/configuration, seed, graph mode, and
  scorer version; it separates valid scored records, invalid judges,
  generation errors/timeouts, and missing MC1 choices.
- Dry-run stays before field loading and model execution. No paid run, daemon,
  production-graph write, external service, commit, or push was performed.
- Verified: focused eval tests `7 passed`; full suite `415 passed, 559 warnings`
  (existing datetime deprecations); changed files compile and `git diff --check`
  passes. Task card is in `review` pending protocol and cost approval.

**2026-08-25, deterministisk golden path verifierad:**

- `examples/grounded_memory.py` använder en isolerad temporär databas, lägger
  till explicita strukturerade relationer, frågar både källa och mål, skriver
  `context_block()` och visar contradiction check utan daemon, modell eller API.
- Dokumenterad körning: `pip install -e .` följt av
  `python examples/grounded_memory.py`.
- Verifierat: fokustestet passerar, demot skriver båda kontextblocken och
  `recommendation: flag` / `has_conflict: True`; full suite `411 passed,
  1 skipped`. Endast befintliga `datetime.utcnow()`-deprecation warnings.

**2026-08-25, evidens och publikt kontrakt ombyggt:**

- README, produktbeskrivning, roadmap, LinkedIn-text och videoscript använder
  inte längre den historiska 96%-claimen som aktuell evidens. README redovisar
  i stället TruthfulQA-piloten (bare 50.0%, RAG 50.0%, Nous-meta 47.5%) som
  explorativ och ofullständigt bedömd.
- `eval/RESULTS_INDEX.md` tillagd som manifest för auditerbara, explorativa och
  historiska körningar. Den saknade manifestfilen för `run_20260403_094211`
  gör att den gamla 96%-claimen inte längre behandlas som verifierad.
- TruthfulQA-joiningen markerar nu varje judge-resultat med `judge_valid`,
  sparar rå judge-output och räknar ogiltiga domar separat i metrics. Tre nya
  parser-tester täcker komplett JSON, saknat skäl och ogiltigt scoreintervall.
- Python-kontraktet är konsekvent `3.13+` i metadata, CI, README och
  produktgrafik; GitHub-URL:erna pekar på `Nous`.
- Verifierat: `407 passed, 1 skipped`, `uv lock --check` och `git diff --check`.
- Kvar: TruthfulQA-resultatfilen från 2026-08-24 är fortfarande en lokal,
  okommitterad pilotfil; den ska inte publiceras som effektbevis innan en
  komplett körning med oberoende scoring finns.

**2026-08-25, gammal explainer avpublicerad:**

- README-länken till YouTube-videon `SLDbJbEXI1g` och den tillhörande
  explainer-sektionen är borttagna. Den gamla videon innehöll en ej verifierad
  96%-claim och ska inte längre vara en del av projektets publika väg.
- En ny, saklig explainer-video är kvar som planerad task och ska länkas först
  när den är inspelad och granskad mot aktuell evidens.

**2026-08-25, kärn-API och claims granskade:**

- `NouseBrain.query()` hämtar nu både inkommande och utgående relationer. Ett
  målkoncept kan därför visa vilken källa som stöder eller motsäger det.
- HTTP-skrivningar i `NouseBrainHTTP.learn()` och `.add()` propagerar nu
  serverfel i stället för att tyst rapportera framgång.
- Nytt deterministiskt exempel: `examples/grounded_memory.py`. Det kräver
  ingen daemon, modell, API-nyckel eller produktionsgraf och visar relationer,
  evidens och contradiction handling i en isolerad databas.
- Produkt- och strategidokumentens universella kompatibilitets-, skala- och
  neuroscience-claims har tonats ned till verifierbara beskrivningar.
- Verifierat: `409 passed, 1 skipped`, full Python-kompilering, package build
  och det isolerade grounded-memory-demot.

**2026-08-24, isolerad VS Code Build-arbetsyta tillagd:**

- `.vscode/` rekommenderar Python, Ruff, rust-analyzer och TOML-stöd och
  pekar Python mot repots `.venv` samt Rust mot
  `crates/tda_engine/Cargo.toml`. Rust-tasken binder dessutom PyO3 till
  repots Python 3.13-miljö i stället för systemets inkompatibla Python 3.14.
- Tasks för Python-kompilering, pytest och Rust-tester finns under
  `Terminal: Run Task`; pytest får en isolerad fältdatabas under `/tmp`.
  Inga daemon-, systemd- eller produktionsgrafåtgärder har lagts till.
- Arbetsytan kopplas från `~/NOUS-BUILD.code-workspace` till VS Code-profilen
  `Build`. Verifierat från samma kommandon: Python-kompilering utan fel,
  `404 passed, 1 skipped` i pytest och godkänd Rust-build/test (`0 failed`).

**2026-08-24, public explainer linked from the project README:**

- Added a prominent `79-Second Explainer` section after the quick start,
  with a locally stored `IMG/nous-explainer-thumbnail.png` poster linking to
  the published YouTube video (`SLDbJbEXI1g`). The top README navigation now
  includes the explainer. This is a documentation/media-only change; runtime,
  daemon, graph, and package behavior are untouched.

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
