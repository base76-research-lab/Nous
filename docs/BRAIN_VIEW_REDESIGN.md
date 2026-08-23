# Brain View — evidensdriven redesign

Beslutad 2026-08-23. Grundprincip: varje visuellt lager måste kunna svara
"vilken datapunkt är det här?" Annars är det dekoration, inte evidens.
Futuristiskt får aldrig betyda påhittat rörligt.

## Lager

1. **Ljus/glöd = konfidens.** Nodens ljusstyrka mappas direkt till
   `evidence_score`. ev=1.0 lyser skarpt, ev=0.45 är matt/nästan
   genomskinlig. Implementerar `living_core.json`s egna `boundaries`:
   "flag uncertainty explicitly" — visuellt, inte bara i text.

2. **Färgmättnad = validerat vs. hypotetiskt.** Behåll regionfärgerna.
   Lägg mättnad ovanpå: full mättnad = `assumption_flag=0`, urblekt =
   `assumption_flag=1`.

3. **Rörelse triggas av verkliga händelser, aldrig av en loop.**
   Nervbanepulser vid faktiska `edge_added`-events (redan i SSE-strömmen).
   Bisociation-flash bara vid verkliga `bisoc_candidates`-fynd — inte
   ambient bakgrundsanimation.

4. **Storlek = grad, position = struktur.** Nodstorlek redan kopplad
   till kantantal — behåll. Regionpositioner i 3D bör på sikt spegla
   faktiska TDA-avstånd (H0-fragmentering) i stället för hårdkodade
   koordinater — då blir layouten själv ett bevis.

5. **Tankeström i stället för tomma mätare.** `living_core.last_reflection.thought`
   är redan äkta text, uppdaterad varje cykel, aldrig visad i UI:t. En
   löpande textrad slår vilken stapel som helst — den är sann i realtid.

6. **Typografi orörd.** Serif-display (Yu Mincho) mot sans-UI ger redan
   rätt känsla ("levande arkiv", inte "AI-startup-dashboard").

## Korrigerad förståelse (2026-08-23)

Arousal/dopamine/synapser-mätarna är INTE trasiga. Arousal är en
beräknad Yerkes-Dodson-signal (överraskning/nyhet, `limbic/signals.py`),
default 0.0 vid stabil, väntad tillväxt — korrekt beteende, inte en bugg.
Dopamine speglar redan verklig belöningssignal (1.0 = stadig framgång).
"Synapser/min" är en avsiktlig sessionslokal räknare för den sällsynta
`synapse_formed`-händelsen, nollställs vid sidladdning. Innan vidare
"fixar" här: verifiera vad metriken faktiskt mäter innan den ändras.

## Status

- [x] Designprinciper beslutade
- [x] Lager 1 (evidens→glöd) implementerat i `index.html` (Concept Atlas-vyn:
      `_avgEvidence` per nod, `MeshStandardMaterial` med emissiv glöd,
      verifierat visuellt i webbläsare 2026-08-23). Kvar: samma princip i
      `brain_view.js` (regionvyn) och `city.js`.
- [x] Lager 2 (mättnad→validering): `assumption_flag` tillagd i SQL
      (`field/surface.py`) och API-svaret (`web/server.py`), `desaturateHex()`
      i frontend kopplad till både `.nodeColor()` och `nodeThreeObject`.
      Verifierat via `/api/graph` att fältet faktiskt skickas, och visuellt
      i webbläsaren 2026-08-23.
- [x] Lager 3 (händelsestyrd rörelse): `synapse_formed`-eventet (verklig
      strukturell isomorfi mellan domäner, `axon_growth_cone.py`) kopplat
      till den redan kodade men tidigare oanvända `bisociationFlash()` i
      stället för ett generiskt hippocampus-pulse. Kvarstår: samma koppling
      för `bisoc_candidates` (kandidater innan de blir riktiga synapser —
      loggas idag bara i journalen, emittas aldrig som SSE-event).
- [x] Lager 4 (TDA-baserad positionering) — klart 2026-08-23:
      `region_tda_positions()` (`field/brain_topology.py`) kör klassisk MDS
      på regioners koncept-centroid-avstånd, ny `/api/brain_regions/
      tda_positions`, `brain_view.js` hämtar och slår om innan regionerna
      byggs, tyst fallback till hårdkodade positioner vid otillräcklig
      täckning. Blockerades först av en tyst bugg: standard-embed-modellen
      (`nomic-embed-text-v2-moe`) var inte installerad (404 mot Ollama),
      så `domain_tda_profile()` föll alltid tillbaka till topologiska
      pseudo-vektorer i stället för semantiska embeddings — ingen centroid
      någonsin beräknad. Fixat via `NOUSE_EMBED_MODEL=nomic-embed-text:latest`
      i daemonens systemd-tjänst (det som faktiskt är `ollama pull`:at).
      Detta blockerade även semantisk bisociation, inte bara Brain View —
      2493 embeddings beräknade inom sekunder efter omstart. Verifierat
      live mot skarpa grafen: full täckning (11/11 regioner).
- [x] Lager 5 (tankeström-panel) — klart 2026-08-23:
      `living_core.last_reflection.thought` exponerad i heartbeat-SSE:t
      (`/api/events`), visas som en enkel rad i UI:t (`#thought-stream`).

## Status: alla fem lager klara (2026-08-23)
