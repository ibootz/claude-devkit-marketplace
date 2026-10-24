# Color Palette & Brand Style

**This is the single source of truth for all colors and brand-specific styles.** To customize diagrams for your own brand, edit this file — everything else in the skill is universal.

Every hex below is a swatch in Excalidraw's own color picker (open-color shades from `packages/common/src/colors.ts`), so a user who opens the file and edits it by hand picks from the same colors. Contrast was checked against WCAG on 2026-10-24: every stroke is ≥ 3:1 against the white canvas, and `#1e1e1e` text is ≥ 9.9:1 on every fill. A replacement color must pass the same two checks (see `design-guide.md` §3).

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
