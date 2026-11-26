# Themes

All seven themes live in `themes/themes.json`, one object per theme. `render.py` reads it at start; a new key there is a new theme, with no code change.

## Shared rules

- Text on every fill passes WCAG 4.5:1. A changed fill or text color must be re-checked (formula: relative luminance, `(L1 + 0.05) / (L2 + 0.05)`).
- `mac` and `isometric` share one palette: pale tinted fill, a hairline stroke of the same hue (1.2–1.5:1 against the fill, on purpose: the card reads from fill and shadow, not outline), accent colors only for one emphasized edge.
- The element geometry follows Excalidraw's own SVG export: corner radius `min(radius, radius_ratio × short side)`, rounded corners drawn as curves, labels sitting in a gap cut out of the edge. Keep that geometry when adding a theme; change colors and sizes.
- `ligne` and `dark` also keep outlines, edges and arrows at 3:1 or more against the canvas and the zone fill: their cards have no shadow or tint contrast to lean on.
- `ligne` has one hue, so its ten roles differ by fill gray level (white, light gray, mid gray, black, accent) and by outline (thin, thick, long dash, short accent dash, dotted). Keep every pair of roles apart in a grayscale render when tuning it.
- Roles are the same ten names in every theme, so a spec switches theme without edits.

## Theme object

| Key | Meaning |
|---|---|
| `label` | Name printed by `render.py --themes`. |
| `bg` | Canvas color. |
| `font` | `family`, `code` (code blocks), `latin_w` (Latin glyph width in em, for layout estimates), weights, `embed` (bundled families `to_png.py` subsets into the SVG: `Nunito`, `Cascadia`, `Excalifont`, `Xiaolai`). Put the bundled family first, then fonts preinstalled on macOS and Windows (`'Helvetica Neue',Arial`, `Menlo,Consolas`, `'PingFang SC','Microsoft YaHei'`, `'Kaiti SC',STKaiti,KaiTi`): characters outside the bundled set (Nunito has no CJK glyphs, so Chinese in the `mac`, `isometric` and `dark` themes is always drawn by PingFang SC / Microsoft YaHei; Xiaolai covers GB 2312 only) and SVGs never passed through `to_png.py` fall back to them. |
| `layout` | Sizes and gaps in px: text sizes, card padding, column bounds `col_min`/`col_max`, zone gutter, grid gaps. |
| `card` | `radius` (upper bound), `radius_ratio` (share of the short side, Excalidraw uses 0.25), `stroke_width`, `dash`, `dash_width` (outline width of dashed cards), `text_align` (`middle` or `start`), optional `accent_bar` width. |
| `zone` | `fill`, `stroke`, `radius`, `radius_ratio`; `style: "rule"` draws a heavy top rule instead of a box (swiss); `highlight` puts a marker swipe behind zone titles (sketchnote). |
| `shadow` | `kind`: `offset` (a copy of the shape moved by `dx`/`dy`, filled `color` at `opacity`, no blur), `extrude` (side face, `depth`, per-role `side` color), `none`. |
| `rough` | Present = hand-drawn: every outline, fill, arrow shaft and arrowhead is drawn as jittered curves (two strokes per segment, like Excalidraw's sketch mode); `amp` is the jitter in px. Deterministic: the same spec gives the same SVG. |
| `edge` | Line `color`, `width`, arrowhead `head` length, `head_ratio` (half-width ÷ length, default 0.46), `dash`; swiss adds `accent_wider`. |
| `edge_label` | `style: "gap"` cuts the label's box out of the edge line and prints the text in the gap (Excalidraw style); `style: "chip"` draws a filled pill (`fill`, `stroke`, `radius`, `-1` = fully round). `text` is the label color. |
| `text` | `title`, `desc`, `zone` colors; swiss adds `accent` for the title rule. |
| `code` | Code block colors; `dots: true` draws window buttons. |
| `roles` | Per role: `fill`, `stroke`, `accent`; optional `text`/`desc` (text on dark fills), `side` (isometric), `dashed`, `stroke_width` (overrides `card.stroke_width`), `dash` (dash pattern, overrides `card.dash`; `"0.1 5"` gives round dots). |

## The `mac` shadow

Taken from Excalidraw's export: the same rounded shape, moved 5 px down, black at opacity 0.07, no blur. It shows as a thin gray crescent under the bottom edge and never as a halo. Raise `opacity` toward 0.12 for more lift; past that, or with a blur, it competes with the content. `brutal` uses the same mechanism at `5/5`, opacity 1.

## Adding a theme

1. Copy the closest theme object under a new key.
2. Change colors and sizes; keep all ten roles.
3. Render `examples/*.json` with `--theme <new>`, run `to_png.py`, read every PNG.
4. Check text contrast on every role fill, and outline / edge contrast against `bg` and the zone fill.
5. Add the theme to the table in `SKILL.md` and to the description if users will ask for it by name.
