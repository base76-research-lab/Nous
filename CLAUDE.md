# CLAUDE.md — Nous

## Läs först

**`STATUS.md`** — den enda "var är vi"-filen. Läs den innan du gör något
annat i det här repot. `ROADMAP.md` är historik/konventioner,
`docs/NOUS_NEXT_GENERATION_PLAN.md` är den större arkitekturvisionen
(Fas 1–3), `docs/handoffs/*` är gamla per-pass-anteckningar (senast
använda april 2026, ersatta av STATUS.md-konventionen 2026-08-24). Vid
konflikt mellan filerna: STATUS.md vinner, och de andra bör rättas.

## Innan sessionen avslutas

1. Om något ändrats sedan STATUS.md senast uppdaterades: uppdatera den —
   vad hände, varför, vad är nästa steg.
2. Committa ändringarna, eller skriv i STATUS.md uttryckligen varför de
   lämnas okommitterade.
3. En Stop-hook i `.claude/settings.json` påminner om detta automatiskt
   om `git status --short` inte är tomt vid sessionsslut — den blockerar
   inte, den bara skriver en påminnelse. Om den triggar, gör steg 1–2
   innan du faktiskt slutar.

Det här ersätter det gamla mönstret ("Added Stop hooks: handoff reminder +
git push check", commit 2026-04-14) som tystnade när `.claude/settings.json`
återställdes till `"hooks": {}` någon gång innan 2026-08-23 — se
`git log --oneline -- .claude/settings.json` om exakt när blir relevant.

## Körande daemon — rör aldrig produktionsgrafen från eval/test-kod

`nouse daemon web --port 8767` körs som en långlivad bakgrundsprocess
(`.venv/bin/nouse daemon web`). Dess graf ligger i
`~/.local/share/nouse/field.sqlite`. All eval-/benchmark-/test-kod måste
använda en isolerad `FieldSurface` vid en temp-path — se mönstret i
`eval/longmemeval_adapter.py::build_isolated_field()`. Skriv aldrig till
produktionsgrafen från ett engångsskript.

## Miljövariabler

`.env` i repo-roten har API-nycklar (`CEREBRAS_API_KEY`,
`OPENROUTER_API_KEY`, `GROQ_API_KEY`). De laddas INTE automatiskt —
`eval/run_eval.py` läser bara `os.getenv(...)` utan dotenv. Kör
`set -a && source .env && set +a` innan du kör något i `eval/` som
använder en molnmodell, annars faller anrop tyst tillbaka på tomma
`Authorization`-headers.

`NOUSE_EXTRACT_MODEL` default (`deepseek-r1:1.5b` i `extractor.py`) är
inte installerad i Ollama — verifierat 404 2026-08-24. Sätt den explicit
(t.ex. `gemma4:e2b`, samma som den körande daemonen använder) i allt som
anropar `extract_relations()` fristående från daemonen, annars misslyckas
extraktionen tyst (`except Exception: rels = []`) utan felmeddelande i
resultatet.

## Nous-specifikt

- `brain.py` och `field/surface.py` är kärnan — ändra försiktigt.
- `daemon/main.py` är komplex men fungerar — var konservativ.
- Kod är sammanflätad med FNC-teorin — varje ändring har filosofiska
  implikationer, se `docs/NOUS_STRATEGIC_DOCTRINE.md`.
- Språk: kod + docs på engelska, strategiska dokument (ROADMAP, STATUS,
  planer) på svenska.
