# Color Palette & Brand Style

**This is the single source of truth for all colors and brand-specific styles.** To customize diagrams for your own brand, edit this file — everything else in the skill is universal.

Every hex below is a swatch in Excalidraw's own color picker (open-color shades from `packages/common/src/colors.ts`), so a user who opens the file and edits it by hand picks from the same colors. Contrast was checked against WCAG on 2026-10-24: every stroke is ≥ 3:1 against the white canvas, and `#1e1e1e` text is ≥ 9.9:1 on every fill. A replacement color must pass the same two checks (see `design-guide.md` §3).

The **Pastel Style** section at the end is the one exception to both claims: its hexes are not picker swatches, and its container strokes are below 3:1. It applies only when SKILL.md Styles picks `pastel`; every other style uses the tables before it.

---

## Shape Colors (Semantic)

Colors encode meaning, not decoration. Each semantic purpose has a fill/stroke pair.

| Semantic Purpose | Fill | Stroke |
|------------------|------|--------|
| Primary/Neutral | `#a5d8ff` | `#1971c2` |
| Secondary | `#e7f5ff` | `#1971c2` |
| Tertiary / infrastructure | `#e9ecef` | `#343a40` |
| Start/Trigger | `#ffd8a8` | `#e8590c` |
| End/Success | `#b2f2bb` | `#2f9e44` |
| Warning/Reset | `#fcc2d7` | `#c2255c` |
| Decision | `#ffec99` | `#e8590c` |
| AI/LLM | `#d0bfff` | `#6741d9` |
| Inactive/Disabled | `#f8f9fa` | `#868e96` (use dashed stroke) |
| Error | `#ffc9c9` | `#e03131` |

**Rules**:
- Always pair the darker stroke with the lighter fill. The fills are fills only — never use them as stroke or text color.
- Decision shares Start's stroke on purpose: Excalidraw's yellow stroke `#f08c00` is only 2.5:1 on white. The diamond shape keeps the two apart.
- Use at most 3–4 of these purposes in one diagram, plus Tertiary for neutral infrastructure.

---

## Text Colors (Hierarchy)

Hierarchy comes from size first (see SKILL.md Text Rules), color second.

| Level | Color | Use For |
|-------|-------|---------|
| Title | `#1e1e1e` | Diagram title, section headings |
| Subtitle | `#1971c2` | Subheadings, secondary labels |
| Body/Detail | `#343a40` | Descriptions, annotations, metadata, arrow labels |
| On fills | `#1e1e1e` | Text inside any fill above |
| On dark fills | `#ffffff` | Text inside evidence artifacts |

---

## Evidence Artifact Colors

Used for code snippets, data examples, and other concrete evidence inside technical diagrams.

| Artifact | Background | Text Color |
|----------|-----------|------------|
| Code snippet | `#1e293b` | Syntax-colored (language-appropriate) |
| JSON/data example | `#1e293b` | `#22c55e` (green) |

---

## Default Stroke & Line Colors

| Element | Color |
|---------|-------|
| Arrows | Use the stroke color of the source element's semantic purpose |
| Structural lines (dividers, trees, timelines) | `#343a40`; secondary lines `#868e96` at `strokeWidth: 1` |
| Group zones | Fill `#f8f9fa` with `strokeColor: "transparent"`, or dashed `#868e96` outline at `strokeWidth: 1` |
| Marker dots (fill + stroke) | `#1971c2` |

---

## Background

| Property | Value |
|----------|-------|
| Canvas background | `#ffffff` |

---

## Pastel Style (only when Styles picks `pastel`)

Low-saturation fills with a same-hue, slightly darker stroke. Replaces every table above for that diagram. Users editing by hand enter these through the picker's hex field.

| Role | Fill | Stroke |
|------|------|--------|
| Zone / card: green | `#eaf4ef` | `#bbd6c7` |
| Zone / card: blue-gray | `#f2f5fb` | `#c5d2e5` |
| Zone / card: violet | `#f1ecfb` | `#c3b3e6` |
| Zone / card: amber | `#fff4e0` | `#e0bf7f` |
| Zone / card: white (outer frame, neutral zone) | `#ffffff` | `#c5d2e5` |
| Tag chip (small label block) | `#f6f7f9` | `#c9ced6` |
| Out-of-scope / planned (dashed) | `#ffffff` | `#c5d2e5` |

| Element | Color |
|---------|-------|
| Titles (diagram, zone, card) | `#1e1e1e` |
| Description line under a card title | `#53647c` |
| Arrows and connectors | `#718096` |
| Canvas background | `#ffffff` |

Contrast, computed 2026-11-19 with the WCAG formula: `#1e1e1e` ≥ 14.4:1 and `#53647c` ≥ 5.2:1 on every fill; arrows `#718096` 4.0:1 on white. Container strokes are 1.5–1.9:1 by design: the zone is read from its fill and its title text, not its outline, so keep a title inside every zone and card.
