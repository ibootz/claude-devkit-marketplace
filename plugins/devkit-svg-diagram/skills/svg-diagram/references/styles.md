# Named styles

Read this only when the user names a visual style that is not a theme key, or asks which styles exist. The default stays `mac`; nothing here picks a style on its own.

The names below come from a 20-style catalogue (S01–S20) the user brought in. Each maps to a theme, or to the closest theme when the style needs effects `render.py` does not draw (gradients, blur, texture, halftone, 45° transit routing).

| Code | Style the user may name | Theme | Gap when not exact |
|---|---|---|---|
| S01 | Swiss international / ligne claire, 清线风 | `ligne` | exact |
| S02 | Bento modular grid, 便当盒 | `mac` | no bento tile sizing |
| S03 | Linear dark, 暗黑极客 | `dark` | no gradient stroke, no glow |
| S04 | Hand-drawn whiteboard, 手绘白板 | `sketchnote` | exact |
| S05 | 2.5D isometric, 等距轴测 | `isometric` | exact |
| S06 | Neo-brutalism pop, 新粗野主义 | `brutal` | exact |
| S07 | Liquid glass / glassmorphism, 毛玻璃 | `mac` | no blur or translucency |
| S08 | Transit map (Beck), 地铁图 | `ligne` | edges stay orthogonal, no 45° lines |
| S09 | Song-dynasty ink, 宋画水墨 | `ligne` | no paper texture or seal |
| S10 | Ukiyo-e woodblock, 浮世绘 | `ligne` | no woodblock texture |
| S11 | Da Vinci codex, 达芬奇手稿 | `sketchnote` | no parchment, no mirror script |
| S12 | Bauhaus / Mondrian, 包豪斯 | `swiss` | exact |
| S13 | Art Deco black-gold, 装饰艺术 | `dark` | no gold ornament |
| S14 | Old-master oil, 油画 | `mac` | no chiaroscuro |
| S15 | 19th-c. natural-history engraving, 铜版画 | `ligne` | no hatching |
| S16 | Cyanotype blueprint, 蓝图 | `dark` | no blueprint grid |
| S17 | 70s NASA / cassette futurism | `brutal` | no stripe bands |
| S18 | Wild-west woodcut, 西部木刻 | `ligne` | no wood grain, no rail ties |
| S19 | Pop-art halftone, 波普网点 | `brutal` | no halftone dots |
| S20 | Editorial press / financial chart, 财经报刊 | `ligne` | exact for diagrams; data charts are out of scope |

## Rules

- **Exact match**: use the theme and say nothing more.
- **Closest only**: render with the mapped theme and tell the user in one line which part of the style is missing (the "Gap" column). The fix for a missing effect is a theme or renderer change, made as its own task; hand-edited SVG is lost on the next render.
- **Instruction diagrams** (specs, schedules, wiring, construction drawings): a style changes only the carrier layer (background, line weight, font). Notation, line types and proportions stay as the domain standard defines them. Data charts keep a lie factor of 1: no perspective, no hand-drawn distortion.
- **One document, one theme.** A named style applies to every figure in that document.
