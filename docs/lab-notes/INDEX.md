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
| 2026-04-13 | [Intrinsic Drive Engine](2026-04-13-intrinsic-drive-engine.md) | md |
| 2026-04-13 | [A Note to Google DeepMind](2026-04-13-deepmind-note.md) | md + [pdf](2026-04-13-deepmind-note.pdf) |
| 2026-04-13 | DeepMind note — social draft | [md](2026-04-13-deepmind-note-social.md) |
| 2026-04-11 | Core package spec | [md](2026-04-11-core-package.md) |
| 2026-04-11 | Node evolves v2 | [md](2026-04-11-node-evolves-v2.md) |

---

## Adding a new note

1. Create `YYYY-MM-DD-slug.md` in this directory
2. If external-facing, generate PDF: `pandoc YYYY-MM-DD-slug.md -o YYYY-MM-DD-slug.pdf --pdf-engine=xelatex -V mainfont="DejaVu Sans" -V monofont="DejaVu Sans Mono"`
3. Add entry to the table above
4. Update wiki index (see CONTRIBUTING.md)