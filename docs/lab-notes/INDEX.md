# Nous Lab Notes

Dated research notes, strategic documents, and external communications for the Nous project.

## Convention

- **Filename:** `YYYY-MM-DD-slug.{md|pdf}`
- **One topic per note** — split rather than bundle
- **PDF companions** where formatting matters (external-facing notes)
- **Master = repo.** Wiki mirrors as public index.

---

## 2026

| Date | Note | Format |
|------|------|--------|
| 2026-08-23 | [Björns hjärndokument mot Nous — vad stämmer, vad saknas](2026-08-23-brain-document-synthesis.md) | md |
| 2026-04-15 | [The Larynx Problem — LessWrong Post](2026-04-15-larynx-problem-lesswrong.md) | md |
| 2026-04-15 | [Morning Research Sweep](2026-04-15-morning-research.md) | md |
| 2026-04-14 | [The Percolation Problem in Autonomous Knowledge Graphs](2026-04-14-percolation-problem.md) | md |
| 2026-04-14 | [Daemon Cognitive Cycle Fix](2026-04-14-daemon-cognitive-cycle-fix.md) | md |
| 2026-04-14 | [Language Models Are the Larynx, Not the Mind](2026-04-14-language-models-are-the-larynx-not-the-mind.md) | md + [html](2026-04-14-language-models-are-the-larynx-not-the-mind.html) |
| 2026-04-14 | [Larynx Problem — Substack Positioning Draft](2026-04-14-larynx-problem-substack-positioning.md) | md + [html](2026-04-14-larynx-problem-substack-positioning.html) + [pdf](2026-04-14-larynx-problem-substack-positioning.pdf) |
| 2026-04-13 | [Intrinsic Drive Engine](2026-04-13-intrinsic-drive-engine.md) | md |
| 2026-04-13 | [P1-P5 Roadmap Implementation](2026-04-13-p1-p5-roadmap.md) | md |
| 2026-04-13 | [A Note to Google DeepMind](2026-04-13-deepmind-note.md) | md + [pdf](2026-04-13-deepmind-note.pdf) |
| 2026-04-13 | DeepMind note — social draft | [md](2026-04-13-deepmind-note-social.md) |
| 2026-04-12 | [Reframing as Epistemic Substrate](2026-04-12-reframing-epistemic-substrate.md) | md |
| 2026-04-11 | [Limbic System and SemanticModulation](2026-04-11-limbic-semantic-modulation.md) | md |
| 2026-04-11 | Core package spec | [md](2026-04-11-core-package.md) |
| 2026-04-11 | Node evolves v2 | [md](2026-04-11-node-evolves-v2.md) |
| 2026-04-06 | [The Larynx Problem](2026-04-06-the-larynx-problem.md) | md |
| 2026-04-05 | [KuzuDB→SQLite Migration](2026-04-05-kuzudb-to-sqlite.md) | md |
| 2026-04-02 | [b76→Nous Migration](2026-04-02-b76-to-nous-migration.md) | md |
| 2026-04-13 | [A Note to Google DeepMind](2026-04-13-deepmind-note.md) | md + [pdf](2026-04-13-deepmind-note.pdf) |
| 2026-04-13 | DeepMind note — social draft | [md](2026-04-13-deepmind-note-social.md) |
| 2026-04-11 | Core package spec | [md](2026-04-11-core-package.md) |
| 2026-04-11 | Node evolves v2 | [md](2026-04-11-node-evolves-v2.md) |

---

## Adding a new note

1. Create `YYYY-MM-DD-slug.md` in this directory
2. If external-facing for Substack, render HTML preview: `python scripts/render_substack_html.py docs/lab-notes/YYYY-MM-DD-slug.md` (see `docs/SUBSTACK_WORKFLOW.md`)
3. If external-facing and print-style matters, generate PDF: `pandoc YYYY-MM-DD-slug.md -o YYYY-MM-DD-slug.pdf --pdf-engine=xelatex -V mainfont="DejaVu Sans" -V monofont="DejaVu Sans Mono"`
4. Add entry to the table above
5. Update wiki index (see CONTRIBUTING.md)
