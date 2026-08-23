# Björns hjärndokument mot Nous — vad stämmer, vad saknas

Läst: `~/Downloads/brain.pdf` ("Den mänskliga hjärnan — en djup teknisk
orientering", v1.0, 23 aug 2026), källkopia bevarad som
[2026-08-23-human-brain-source.pdf](2026-08-23-human-brain-source.pdf).
Detta är en syntes mot Nous faktiska kod, inte en läsanteckning — varje
punkt är kopplad till en verklig fil/mekanism.

## Vad dokumentet bekräftar att Nous redan gör rätt

- **§8, "börja inte med en vuxen statisk kopplingsmatris"** — Nous hela
  filosofi (organisk grafiväxt från ett litet frö, aldrig förtränad) matchar
  detta rakt av. Ingen ändring behövs, bara en bekräftelse att riktningen är
  biologiskt motiverad, inte bara pragmatisk.
- **§5, neuromodulation** — `limbic/state_modulator.py` + `limbic/signals.py`
  implementerar redan dopamine/noradrenaline/acetylcholine/arousal som
  distinkta signaler med olika roller (dopamine→belöning, noradrenaline→
  pruning-aggressivitet, arousal→Yerkes-Dodson). Grovkornigt men riktningen
  är rätt — det är exakt det dokumentet efterlyser (§5: "samma substans kan
  ge olika resultat beroende på receptor").
- **§4, predictive coding + Friston [ref 9]** — redan explicit grund för
  Fas 3 i `docs/NOUS_NEXT_GENERATION_PLAN.md` ("predictive coding driver
  faktiska beslut, inte bara UI"). Dokumentet ger extra tyngd åt att detta är
  rätt nästa steg, inte bara en trendig idé.
- **§7, "metastabila tillstånd, inte ett enda stabilt läge"** — matchar
  cykel-baserad `brain_loop` där `limbic_state` och `living_core.homeostasis`
  skiftar läge (`mode=steady/focus/recovery`) i stället för att konvergera
  mot ett fixpunktsläge.

## Konkreta luckor — rangordnade efter hävstång

### 1. `relation.strength` är "en enda vikt per koppling" — §3 och §13 varnar uttryckligen för detta

§13 ("Vanliga felslut"): *"Neuronen är bara en vikt. Neuronen har tillstånd,
dendritisk beräkning, plasticitet och neuromodulatorisk kontext."* §3: *"En
enda vikt per koppling räcker inte om målet är biologisk realism."*

Nous `relation.strength` (en REAL-kolumn, 0.05–3.5, ändras av
`strengthen()`/`weaken()`) är exakt denna förenkling. Biologin skiljer på
minst tre tidsskalor som i dag är hopblandade i en siffra:
- **Korttidsfacilitering/depression** — snabb, glömmer inom sekunder-minuter
  om inget upprepar den
- **Långtidspotentiering (LTP)** — kräver upprepad samaktivering över tid,
  ändras långsamt
- **Homeostatisk plasticitet** — håller helheten stabil (Nous har redan en
  svag version av detta i `pruning_aggression` + den nya
  `consolidate_dormant_concepts()` från ikväll)

**Möjlig nästa åtgärd (inte gjord, kräver eget beslut):** separera
`strength` i en snabb komponent (senaste aktivering, decayar mellan cykler)
och en långsam komponent (konsoliderad styrka, ändras bara efter upprepad
samaktivering över flera cykler — verklig LTP-analogi, inte bara ett
strength-hopp per `add_relation`-anrop).

### 2. Ingen energibudget — §6 kallar detta inte en "efterhandsdetalj"

§6: *"Lägg in ett energibudgetlager. Aktivitet bör ha kostnad, återhämtning
och lokala begränsningar. Annars tillåter modellen orealistiskt hög
aktivitet, oändlig precision och ingen fysiologisk tradeoff mellan
beräkning och överlevnad."*

Verifierat att detta saknas helt: `cognitive_policy.json` styr
extraktionströsklar, inte kostnad. Ingen `energy_budget`/`token_budget` finns
i koden (`grep` gav noll träffar). Daemonen gör obegränsat många LLM-anrop
per cykel (bisociation-motorn, curiosity loop, extraction) utan något
begrepp om att detta har ett pris — vilket det bokstavligen har (tid, tokens,
i vissa fall pengar via Cerebras/OpenRouter).

**Möjlig nästa åtgärd:** en `energy`-signal i limbic-laget, sjunker med
LLM-anropskostnad per cykel, återhämtar sig långsamt (motsvarar metabol
återhämtning). Skulle naturligt reglera hur ofta t.ex.
`scheduled_bisociation_pass()` eller curiosity-loopen faktiskt kör, i stället
för bara cykel-modulo som i dag.

### 3. Thalamus och basala ganglier saknas som namngivna regioner

`brain_topology.py` har 10 regioner men ingen thalamus (§7: "relä, selektion,
rytmisk koordinering") eller basala ganglier (§7: "val, vana, action
selection, gating"). Nous har redan funktionella motsvarigheter utan att
namnge dem så: `_capability_route_plan`/model-routern fungerar som en
thalamus-relä (väljer vilken skill/modell/provider som ska hantera en
förfrågan), och goal-weighting/curiosity-loopen fungerar som basala
ganglier (val mellan konkurrerande handlingar/mål). Lägre prioritet — det
här är mest en namngivnings-/kartläggningsfråga, ingen funktionell lucka.

## Vad som INTE är en lucka (medveten avgränsning)

§13 varnar också: *"Fler parametrar löser det. Mer detalj utan rätt koppling
mellan nivåer kan ge en större men inte bättre modell."* Detta är ett skäl
att **inte** hastigt lägga till fler limbic-signaler eller fler
hjärnregioner bara för att dokumentet nämner dem — varje tillägg ovan
(multi-timescale strength, energibudget) motiveras av en konkret, redan
identifierad brist i Nous (single-scalar weight, obegränsad LLM-kostnad),
inte av att dokumentet råkar nämna det.

## Status

Detta är research/syntes, inget är byggt. Kandidat för Fas 3/4 i
`docs/NOUS_NEXT_GENERATION_PLAN.md` — särskilt punkt 1 (multi-timescale
strength) hänger ihop med Fas 3 punkt 8 (predictive coding som
beslutsdrivare) och bör beslutas tillsammans, inte separat.
