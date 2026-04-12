# Nous Style Doctrine

**Status:** Working visual doctrine  
**Purpose:** Keep `Nous` visually coherent across README, GitHub, wiki, screenshots, and product UI

---

## 1. First Principle

`Nous` should not look like a generic AI dashboard.

The visual system must reinforce the category claim:

- calm rather than loud
- philosophical rather than hype-driven
- precise rather than ornamental
- architectural rather than product-busy

The outside of the project should feel like **thought**.

The inside of the project may still feel like **living cognition**.

---

## 2. Core Palette

### Base

- `--nous-bg: #fcfaf5;`
- `--nous-surface: #f6f1e6;`
- `--nous-surface-soft: #efe6d6;`
- `--nous-line: #d9cfbf;`

These colors should carry most of the interface.

The repo and public-facing surfaces should feel primarily white / parchment / ivory, not dark.

### Text

- `--nous-ink: #14110f;`
- `--nous-ink-soft: #4f473f;`
- `--nous-muted: #8b8278;`
- `--nous-ai-grey: #c9cbd0;`

Text should be dark and warm, not blue-grey and not pure black everywhere.

### Accent

- `--nous-accent: #daa42d;`
- `--nous-accent-soft: #eab876;`

`#daa42d` is the primary accent.

`#eab876` is a support tone, not a second brand color.

Use it only when a lighter expression of the same family is needed.

### Field / Interior Mode

For atlas and deep internal views, the exterior palette may invert into a dark field, but the accent must stay continuous:

- `--nous-field-bg: #151018;`
- `--nous-field-surface: rgba(246, 241, 230, 0.92);`
- `--nous-field-line: rgba(218, 164, 45, 0.22);`
- `--nous-field-node: #daa42d;`

This lets the atlas feel like the inside of the mind while still belonging to the same identity system.

---

## 3. Ratio Rule

The palette should be used roughly like this:

- 90% base / neutral
- 8% text structure
- 2% accent

If the accent starts feeling common, it is being overused.

The accent exists to mark significance, not to decorate everything.

---

## 4. Accent Usage Rules

Use `#daa42d` for:

- active tabs
- selected states
- key dividers
- small node highlights
- important calls to action
- section-eyebrow labels
- diagram emphasis
- critical navigation moments

Use `#eab876` for:

- hover states
- soft background highlights
- subtle chips or badges
- supporting emphasis under the main accent

Do **not** use the accent for:

- large page backgrounds
- long-form paragraph text
- every button on a page
- every border in the system
- decorative gradients

---

## 5. Typography Direction

`Nous` should feel typographic before it feels interface-driven.

### Logo / Hero

- serif-led
- quiet spacing
- black `νοῦς`
- soft grey `AI`

### UI copy

- legible, restrained sans for controls and operational text
- serif only for high-signal display moments: logo, key pull quotes, doctrine statements

### Tone rule

No “AI slop” typography.

Avoid default product stacks as the whole identity. If a sans is used for UI, it should disappear behind the structure rather than define the brand.

---

## 6. Public Surface Rules

### README / GitHub / Wiki

These should be mostly light:

- warm white background
- dark ink
- one accent color
- lots of whitespace

The public surface should communicate:

- seriousness
- clarity
- category definition

It should not communicate:

- gamified SaaS
- neon AI aesthetic
- benchmark-chasing

### Hero Rule

At the top of public surfaces, show:

1. the wordmark
2. the core sentence
3. the architectural inversion

Only after that:

- demo
- benchmark
- integrations

---

## 7. Product Surface Rules

### Atlas / cockpit / deep views

These can remain dark and immersive, but they should still obey the doctrine:

- keep the outer shell light when possible
- let the graph field carry darkness, not every panel
- use the accent to mark attention, not volume
- reduce visible provider plumbing in public screenshots

The product should visually imply:

`the intelligence lives in the field`

not:

`this is a model router UI`

### Public screenshot rule

If a screenshot is meant for public persuasion, prioritize:

- graph structure
- district names
- finding stream
- contradiction / relevance / epistemic cues

De-prioritize:

- provider selectors
- model candidates
- implementation clutter

---

## 8. Diagram Rule

Every canonical diagram should follow the same visual grammar:

- neutral background
- dark structural text
- accent only for the decisive difference

Example:

```text
Industry:
LLM -> tools -> wrappers

Nous:
Nous -> LLM -> tools
```

Only the decisive inversion should glow.

---

## 9. CSS Tokens

Use this as the starting token set for web work:

```css
:root {
  --nous-bg: #fcfaf5;
  --nous-surface: #f6f1e6;
  --nous-surface-soft: #efe6d6;
  --nous-line: #d9cfbf;

  --nous-ink: #14110f;
  --nous-ink-soft: #4f473f;
  --nous-muted: #8b8278;
  --nous-ai-grey: #c9cbd0;

  --nous-accent: #daa42d;
  --nous-accent-soft: #eab876;

  --nous-field-bg: #151018;
  --nous-field-surface: rgba(246, 241, 230, 0.92);
  --nous-field-line: rgba(218, 164, 45, 0.22);
  --nous-field-node: #daa42d;
}
```

---

## 10. The One-Line Summary

If the visual doctrine needs to be compressed to one sentence:

> `Nous` should look like a philosophical instrument with a living interior: mostly light, typographic, and disciplined on the outside, with a darker cognitive field inside, all bound together by one controlled accent color.

