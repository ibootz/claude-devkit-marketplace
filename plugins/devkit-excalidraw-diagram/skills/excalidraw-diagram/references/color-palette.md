# Color Palette & Brand Style

**This is the single source of truth for all colors and brand-specific styles.** To customize diagrams for your own brand, edit this file — everything else in the skill is universal.

The shared palette is a macOS flat look: very pale tinted fills, hairline strokes in the same hue, Apple-style gray text, a soft drop shadow under cards (the shadow rule is in SKILL.md **Styles**, row `mac`). Every style except `brutal` uses it. Its hexes are not Excalidraw picker swatches; a user editing by hand enters them through the picker's hex field.

Contrast, computed 2026-11-21 with the WCAG formula:
- Text: `#1d1d1f` ≥ 14:1, `#3a3a3c` ≥ 9.5:1, `#636366` ≥ 5.0:1, `#0060c0` ≥ 5.1:1 on every fill below.
- Arrows and structural lines `#8e8e93`: 3.3:1 on white. Accent colors: each ≥ 3.6:1 on white.
- Hairline strokes are 1.2–1.5:1 **by design**: a card is read from its fill, its shadow, and its title, not its outline. So every card keeps a title, and a white card always gets the `mac` shadow or sits on a gray zone.

A replacement color must pass the same text and arrow checks (see `design-guide.md` §3).

The **Brutal Style** section at the end replaces these tables for `brutal` only.

---

## Shape Colors (Semantic)

Colors encode meaning, not decoration. Each semantic purpose has a fill, a hairline stroke, and an accent.

| Semantic Purpose | Fill | Stroke (hairline) | Accent |
|------------------|------|-------------------|--------|
| Primary/Neutral | `#e8f1fd` | `#d3e3f8` | `#0a84ff` |
| Secondary (plain card) | `#ffffff` | `#e5e5ea` | `#0a84ff` |
| Tertiary / infrastructure | `#f2f2f7` | `#dcdce1` | `#8e8e93` |
| Start/Trigger | `#fdeedd` | `#f3d4ae` | `#c75f00` |
| End/Success | `#e4f5e9` | `#c7e7d0` | `#248a3d` |
| Warning/Reset | `#fce8f1` | `#f2c9dc` | `#e8508f` |
| Decision | `#fdf3dc` | `#f1dfb3` | `#9a6700` |
| AI/LLM | `#efe9fb` | `#dcd0f5` | `#8e5cf7` |
| Inactive/Disabled | `#ffffff` | `#aeaeb2` (dashed) | `#8e8e93` |
| Error | `#fde8e7` | `#f4c9c6` | `#ff453a` |
| Group zone | `#f5f5f7` | `#f5f5f7` (no visible edge) | — |

**Rules**:
- Pair each fill with its own hairline stroke. Shapes `strokeWidth: 1` (hand-drawn: `2`, or the rough line disappears).
- The accent is for small things only: marker dots, the one emphasized arrow (checklist item 32), a single highlighted word. Never fill a card with it.
- The tints are close to each other, so a diagram where fills carry meaning needs a legend. Use at most 3–4 purposes per diagram, plus Tertiary for infrastructure.

---

## Text Colors (Hierarchy)

Hierarchy comes from size first (see SKILL.md Text Rules), color second.

| Level | Color | Use For |
|-------|-------|---------|
| Title | `#1d1d1f` | Diagram title, section and zone headings, card titles |
| Subtitle | `#0060c0` | Subheadings, secondary labels that need a hue |
| Body | `#3a3a3c` | Annotations, metadata |
| Secondary | `#636366` | Description line under a card title, arrow labels, legend captions |
| On fills | `#1d1d1f` | Text inside any fill above |

---

## Evidence Artifact Colors

Code snippets, data examples, and other concrete evidence inside technical diagrams. The block is light so it does not become the heaviest thing on a pale diagram.

| Artifact | Background | Stroke | Text Color |
|----------|-----------|--------|------------|
| Code snippet | `#f5f5f7` | `#e5e5ea`, `strokeWidth: 1` | `#1d1d1f`; keywords `#9b2393`, strings `#c41a16`, numbers `#1c00cf`, comments `#5d6c79` |
| JSON/data example | `#f5f5f7` | `#e5e5ea`, `strokeWidth: 1` | `#1d1d1f`; keys `#0b4f79`, values `#c41a16` |

---

## Default Stroke & Line Colors

| Element | Color |
|---------|-------|
| Arrows | `#8e8e93`, `strokeWidth: 2`; the one emphasized arrow takes its source's accent |
| Structural lines (dividers, trees, timelines) | `#8e8e93`; secondary lines `#c7c7cc` at `strokeWidth: 1` |
| Group zones | Fill `#f5f5f7`, stroke `#f5f5f7`; out-of-scope zones: white fill, dashed `#aeaeb2` |
| Marker dots (fill + stroke) | The role's accent; `#0a84ff` when no role applies |
| Card shadow (`mac` only) | `#000000` at `opacity: 7` |

---

## Background

| Property | Value |
|----------|-------|
| Canvas background | `#ffffff` |

---

## Brutal Style (only when Styles picks `brutal`)

Neo-brutalism: thick pure-black outlines, a solid black offset shadow under every shape, square corners, flat saturated fills. It keeps its own palette because saturated fills under black outlines are what make the style; on the pale shared tints it reads as a broken `mac`. Replaces the shared tables above for that diagram.

| Role | Fill | Stroke |
|------|------|--------|
| Primary / core | `#74c0fc` | `#1e1e1e` |
| Decision / shared platform | `#ffd43b` | `#1e1e1e` |
| End / new | `#8ce99a` | `#1e1e1e` |
| Start | `#ffa94d` | `#1e1e1e` |
| Error / risk | `#ff8787` | `#1e1e1e` |
| AI | `#b197fc` | `#1e1e1e` |
| Manual / human step | `#f783ac` | `#1e1e1e` |
| Neutral card, external (dashed) | `#ffffff` | `#1e1e1e` |
| Infrastructure / data | `#dee2e6` | `#1e1e1e` |
| Zone | `#f8f9fa` | `#1e1e1e` |

| Element | Color |
|---------|-------|
| All text | `#1e1e1e` |
| Arrow labels | `#ffffff` text on a `#1e1e1e` rectangle (label chip) |
| Shadows | `#1e1e1e` fill and stroke |
| Arrows and connectors | `#1e1e1e` |
| Canvas background | `#ffffff` |

Every fill is an Excalidraw picker swatch; `#1e1e1e` text is ≥ 6.9:1 on each of them (lowest: `#b197fc`).
