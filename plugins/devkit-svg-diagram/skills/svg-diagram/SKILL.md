---
name: svg-diagram
description: "画架构图、流程图、状态图、时序图、组织架构树、泳道图、甘特图、ER 图、四象限图的默认工具：写一份简短 JSON 描述，脚本按固定主题渲染成 SVG 与 PNG，自带重叠与溢出检查；没有现成布局时用自由坐标。七套主题：mac（默认）、brutal 新野兽派、swiss 瑞士、isometric 伪等轴测、sketchnote 手绘、ligne 黑白单强调色、dark 深色。用户说「画架构图 / 流程图 / 时序图 / 泳道 / 甘特 / ER / 组织架构」「出张图放文档里」「换成手绘 / 深色风格」，或 devkit-tool:show-me 判定要出成品图时使用。用户点名 Excalidraw、要 .excalidraw 文件或可拖拽白板时走 devkit-excalidraw-diagram。"
---

# SVG Diagram

Write a small JSON **spec**; `scripts/render.py` lays it out and draws it in a fixed **theme**. Every color, font, radius and shadow comes from the theme (element geometry copied from Excalidraw's SVG export) and every layout but `canvas` computes its own coordinates, so two diagrams drawn a month apart look like one set, and the spec costs a fraction of the tokens of hand-written SVG. Spend the effort on what the diagram argues, not on pixels.

`<skill-dir>` below is the absolute "Base directory for this skill" path shown when this skill loads.

## Steps

1. **Pick the layout** from what the diagram has to show:

   | The reader needs to see | Layout | Spec key |
   |---|---|---|
   | Layers or groups of parts (product architecture, tech stack, module map) | layers | `zones` |
   | Steps, branches, states and the transitions between them | grid | `nodes` + `edges` |
   | Who calls whom, in what order | sequence | `participants` + `messages` |
   | A hierarchy (org chart, module breakdown) | tree | `tree` |
   | Who does which step of a process (cross-team flow, approval) | swimlane | `lanes` + `steps` + `edges` |
   | Tasks, milestones and dependencies over time (schedule, release plan) | gantt | `tasks` |
   | Tables, their fields and cardinalities (data model) | ER | `entities` + `relations` |
   | Items placed on two axes (priority, effort vs. value) | quadrant | `matrix` |

   Use `canvas` free coordinates when no row above fits; it still colors through the theme roles.

   One diagram, one layout. A system that needs both its layers and a request path gets two diagrams.

2. **Write the spec** to `<name>.json` next to where the figure will live. Read [`references/dsl.md`](references/dsl.md) for every field; start from the closest file in `examples/`:
   - `examples/layers-architecture.json`: layered product architecture.
   - `examples/grid-flow.json`: flow with a decision, a group, a code block.
   - `examples/sequence-login.json`: sequence with a self-call and dashed returns.
   - `examples/tree-org.json`, `lanes-approval.json`, `tasks-release.json`, `entities-exam.json`, `matrix-priority.json`, `canvas-freeform.json`: one per remaining layout.

   Give every card a `title` of a few words; put the detail in `desc` (one short line). Use roles for meaning, not decoration: 2–4 roles per diagram plus `plain`, and a `legend` entry for each role used.

   Write every label for a reader new to the system: the main text says what happens in business terms, and the code name rides underneath. A label made only of an endpoint, method, table or field (`tag/adopt(tagCode+tagId)`, `adopt_status=1`) tells that reader nothing. In sequence diagrams put the business sentence in `label` and the endpoint / table / field in the message's `desc`; in flows keep edge labels to a short business word and move the explanation into the node's `desc`. Give a status value its meaning (`adopt=0（未采纳）`). Give each participant a `desc` saying what it is ("AI 打标服务"), since service names alone rarely say.

3. **Render**:

   ```bash
   python3 <skill-dir>/scripts/render.py <name>.json -o <name>.svg [--theme mac]
   uv run <skill-dir>/scripts/to_png.py <name>.svg          # writes <name>.png beside it
   ```

   `to_png.py` also embeds the theme's fonts into the SVG: it cuts the bundled fonts in `assets/fonts/` (Cascadia, Excalifont, Xiaolai; OFL) down to the characters the diagram uses, so the SVG looks the same on any machine. Nothing is downloaded. Always run it before sharing an SVG; `--no-embed-fonts` leaves the SVG relying on system fonts.

   Exit 2 from either script means it drew the diagram but found problems, printed as `LINT ...` or `OVERFLOW ...` lines on stderr. Fix the spec and render again until both exit 0. The findings and their usual fixes are in `references/dsl.md` § Findings. First run of `to_png.py` on a machine: `uv run <skill-dir>/scripts/to_png.py --install-browser`. Windows: `python` or `py -3` instead of `python3`.

4. **Look at the PNG** with Read before handing it over. Lint cannot see a misleading grouping, a missing step, or an arrow that points the wrong way. Fix the spec, not the SVG: hand edits are lost on the next render.

Done when both scripts exit 0 and the PNG, read back, shows every part and relation the diagram was meant to show.

## Themes

Use `mac` unless the user names another style. The theme goes in the spec (`"theme": "brutal"`) or on the command line (`--theme`), which overrides the spec. One document keeps one theme for all its figures.

| Theme | Look | Pick when the user says |
|---|---|---|
| `mac` | Gray zones, pale tinted cards, hairline edge, faint shadow under the bottom edge, monospace | default |
| `brutal` | Saturated fills, thick black outlines, hard offset shadow | 新野兽派、neo-brutalism、醒目 |
| `swiss` | Bauhaus blue / yellow / red blocks, square corners, black rules, no shadow | 瑞士、包豪斯、极简、海报感 |
| `isometric` | `mac` colors plus a tinted side face on each card | 伪等轴测、立体、2.5D |
| `sketchnote` | Paper background, hand-drawn lines and arrowheads, handwriting font, highlighter zone titles | 手绘、草图感、速写笔记、sketchnote、手账 |
| `ligne` | White, black hairlines and one blue accent; roles told apart by gray level and line style, so it survives grayscale print | 黑白、线稿、打印、单色 |
| `dark` | Near-black background, dark tinted cards, mid-tone outlines, flat (no glow, no gradient) | 深色、暗色、dark mode、黑底 |

Role colors per theme, and how to add or tune a theme, are in [`references/themes.md`](references/themes.md). Read it only when changing `themes/themes.json`.

When the user names a style that is not in this table (bento, glassmorphism, blueprint, ukiyo-e, Art Deco…), or asks which styles exist, read [`references/styles.md`](references/styles.md) for the theme it maps to and what it lacks.

## Editing an existing diagram

The spec travels inside every SVG, with `theme` set to the theme actually used (so a `--theme` override survives). When only the SVG is at hand, recover the spec, edit it, and re-render:

```bash
python3 <skill-dir>/scripts/render.py --extract old.svg > old.json
```

## Where files go

Keep `<name>.json`, `<name>.svg` and `<name>.png` together: in a document's `figures/` directory when the figure belongs to a document, otherwise where `devkit-tool:show-me` says. Markdown references the PNG (renders everywhere) or the SVG (sharper, browsers and most md previews). Subagents check that the PNG's modification time is later than the render they just ran before reading it.
