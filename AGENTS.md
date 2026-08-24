# AGENTS.md — Nous

Instruktioner för alla AI-agenter/verktyg i det här repot (Claude Code,
Codex, eller andra). Claude Code-specifika detaljer (hooks, skills) står i
`CLAUDE.md` — läs den också om du är Claude Code.

## Läs först

**`STATUS.md`** — den enda "var är vi"-filen, uppdaterad i varje session.
Läs den innan du gör något annat. Vid konflikt med `ROADMAP.md`,
`docs/NOUS_NEXT_GENERATION_PLAN.md` eller `docs/handoffs/*`: STATUS.md
vinner — de andra filerna är historik/vision, inte aktuellt läge.

## Innan du avslutar en session i det här repot

1. Om du ändrat något: uppdatera `STATUS.md` — vad hände, varför, vad är
   nästa steg. Var specifik om resultat (siffror, filnamn), inte bara
   "arbetade på X".
2. Committa ändringarna. Om du medvetet lämnar dem okommitterade, skriv
   varför i `STATUS.md` så nästa session inte behöver gissa.
3. Lämna aldrig ett benchmark-/experimentresultat okommitterat och
   odokumenterat samtidigt — det är precis vad som hände natten
   2026-08-23 och krävde en hel session att rekonstruera (git-diff,
   sqlite-inspektion, journal-loggar).

## "Fria händer" gäller aldrig åtgärder mot den levande daemonen

Björn kan ge fria händer att bygga och fatta tekniska beslut självständigt
— det gäller kod, tester, dokumentation, allt som går att committa och
granska i efterhand. Det gäller ALDRIG daemon-omstart, migrationer mot
produktionsgrafen, eller ändringar av systemd-enheter — de kräver alltid
ett uttryckligt "kör" i sessionen. Dokumentera väntande sådana åtgärder
som en checklista i `STATUS.md`s "Planerade actions"-avsnitt (vad / varför
/ risk / verifieringssteg / status) i stället för att köra dem, så bygg-
arbetet inte blockeras men åtgärden förblir synlig och granskningsbar.

## Rör aldrig produktionsgrafen från eval/test-kod

En daemon (`nouse daemon web --port 8767`) kan köra som långlivad
bakgrundsprocess mot `~/.local/share/nouse/field.sqlite`. All engångskod
(eval, benchmark, manuell testning) måste använda en isolerad
`FieldSurface` vid en temp-path — se `eval/longmemeval_adapter.py`.

## Miljövariabler

`.env` i repo-roten har API-nycklar men laddas inte automatiskt av
`eval/run_eval.py` (ingen dotenv). Kör `set -a && source .env && set +a`
manuellt innan molnmodeller används.

`NOUSE_EXTRACT_MODEL` defaultar till en Ollama-modell som inte är
installerad (`deepseek-r1:1.5b`, 404 verifierat 2026-08-24). Sätt den
explicit (`gemma4:e2b` fungerar) i fristående skript, annars misslyckas
extraktion tyst.
