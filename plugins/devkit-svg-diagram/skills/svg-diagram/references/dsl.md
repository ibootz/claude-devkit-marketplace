# Spec reference

A spec is one JSON object. One top-level layout key picks the layout: `zones`, `nodes`, `participants`, `tree`, `lanes`, `tasks`, `entities`, `matrix` or `canvas`. Give exactly one; with two or more the first in that order is drawn and a LINT names the rest.

Every layout colors through the theme roles below, `canvas` included. A spec never names a color: `fill`, `stroke`, `color`, `background` and hex / `rgb()` values are reported.

## Top level

| Field | Type | Notes |
|---|---|---|
| `theme` | string | `mac` (default), `brutal`, `swiss`, `isometric`, `sketchnote`, `ligne`, `dark`. `--theme` on the command line wins. |
| `title` | string | Diagram title, top left. |
| `subtitle` | string | One gray line under the title. |
| layout key | array / object | One of the nine; see the layout sections below. |
| `legend` | array | `{"role": "<role>", "label": "..."}` for a color swatch, `{"edge": "solid" \| "dashed", "label": "..."}` for a line sample. Drawn at the bottom. |
| `code` | array | Code or data blocks drawn under the diagram: `{"title": "// comment line", "lines": ["...", "..."]}`. Lines starting with `//`, `#`, `--` render in the comment color. |
| `col_width` | number | Card width in px. Default: fits the widest single-line title or desc, between 160 and 240. Raise it instead of wrapping long titles. |

## Node (card)

Used in `zones[].nodes`, `nodes`, and `participants`.

| Field | Type | Notes |
|---|---|---|
| `id` | string | Required, unique across the spec. Edges and messages refer to it. |
| `title` | string | A few words. Wraps when wider than the card. |
| `desc` | string | One short line in the secondary color under the title. `\n` forces a break. |
| `role` | string | Color role; see Roles. Default `plain`. |
| `shape` | string | `card` (default), `pill` (start / end), `diamond` (decision), `circle`, `ellipse`, `text` (bare text, no outline). |
| `dashed` | bool | Dashed outline, no shadow. Role `external` is dashed already. |
| `span` | int | Card covers this many columns. Default 1. |

### Roles

| Role | Means |
|---|---|
| `plain` | Ordinary part, channel, client. White card. |
| `primary` | The system or apps the diagram is about. |
| `ai` | Model, agent, anything AI. |
| `platform` | Shared service, middle platform, decision diamond. |
| `success` | End state, result, new part. |
| `start` | Trigger, entry, start state. |
| `warn` | Error, risk, failure path. |
| `manual` | Human step. |
| `data` | Storage, queue, infrastructure. |
| `external` | Outside the system boundary. Dashed. |

An unknown role draws as `plain` and is reported. Two or more non-`plain` roles without a `legend` are reported.

## Layers layout: `zones`

```json
"zones": [
  {"title": "业务应用", "desc": "面向场景的功能", "nodes": [ {node}, {node} ]},
  {"title": "外部依赖", "nodes": [ ... ], "align": "center"}
]
```

Zones stack top to bottom as full-width gray bands; each band's title and `desc` sit in a left gutter, its cards in one row to the right. All zones share one column grid, so cards line up across bands.

| Zone field | Notes |
|---|---|
| `title`, `desc` | Gutter text. Keep `desc` under about 12 CJK characters. |
| `nodes` | Cards, left to right. |
| `align` | `"center"` centers a short row; default left. |
| `equal_height` | Default `true`: every card in the band takes the tallest card's height. |
| `dashed` | Dashed outline instead of a gray fill (out-of-scope band). |

`edges` also work here, but rows are dense: an edge between non-adjacent bands crosses cards and gets reported. Draw cross-layer calls as a separate grid or sequence diagram.

## Grid layout: `nodes` + `edges`

Each node takes `"row"` and `"col"` (0-based). Row heights fit their tallest card; columns are `col_width` wide with `grid_gap_x` between them.

```json
"nodes": [
  {"id": "a", "title": "学员交卷", "shape": "pill", "role": "start", "row": 0, "col": 0},
  {"id": "b", "title": "有主观题？", "shape": "diamond", "role": "platform", "row": 0, "col": 1}
],
"groups": [ {"title": "自动阶段", "nodes": ["a", "b"]} ],
"edges": [ {"from": "a", "to": "b", "label": "提交"} ]
```

| Edge field | Notes |
|---|---|
| `from`, `to` | Node ids. |
| `label` | Short pill on the longest segment that leaves it clear of cards; a detour's label may sit beside the line. Keep under about 6 CJK characters, in business words (「通过」「退回修改」), not a code name; the detail of what a step does goes in the target node's `desc`. |
| `dashed` | Async, return, optional. |
| `accent` | A role name (`"success"`): the edge takes that role's accent color. Use on one edge at most, the one the reader should follow. |
| `both` | Arrowheads at both ends. |

Routing: same row → straight horizontal; same column → straight vertical; otherwise an elbow. When that path would cross a third card or a zone title, the router tries other elbows (into the target's side instead of its top, turning nearer one end) and then a detour round the outside of the blocking cards; the canvas grows to fit. Only when every option crosses does `LINT ... crosses node` fire. Still plan the grid so connected nodes share a row or column: a straight edge reads faster than a detour.

`groups` draw a zone behind the listed nodes with the title above them. Keep groups to contiguous rectangles of cells.

## Sequence layout: `participants` + `messages`

```json
"participants": [ {"id": "user", "title": "浏览器"}, {"id": "app", "title": "智测平台", "role": "primary"} ],
"messages": [
  {"from": "user", "to": "app", "label": "打开考试页", "desc": "GET /exam"},
  {"from": "app", "to": "user", "label": "未登录，转去企业登录页", "desc": "302 → SSO", "dashed": true},
  {"from": "app", "to": "app", "label": "核对登录凭证是否有效", "desc": "校验 token 签名与过期时间"}
]
```

Participants sit in a row; messages go top to bottom in array order and are numbered (`"numbered": false` at top level turns numbering off). `from` equal to `to` draws a self-call loop.

| Message field | Notes |
|---|---|
| `label` | Above the arrow, one line: what happens, in business words a newcomer understands ("管理员采纳推荐标签"). Must fit between the two lifelines. |
| `desc` | Under the arrow in the secondary color, wraps to the gap: the technical handle — endpoint, table, field, status value with its meaning (`tag/adopt，带 tagCode + tagId`). The row grows to fit. |
| `dashed` | Replies and callbacks. |
| `accent` | A role name: the arrow takes that role's accent color. |

## Tree layout: `tree`

`tree` is the root node; each node may carry `children`. Parent-child links are orthogonal elbows. Use it for org charts, module breakdowns, mind-map style hierarchies.

```json
"tree": {"id": "cto", "title": "技术负责人", "role": "primary", "children": [
  {"id": "fe", "title": "前端组", "children": [{"id": "fe1", "title": "考试端"}]},
  {"id": "be", "title": "后端组", "edge_label": "兼管", "edge_dashed": true}
]}
```

| Field | Where | Notes |
|---|---|---|
| node fields | each tree node | As in Node (card); `id` required. |
| `children` | each tree node | Array of child nodes, left to right (top to bottom with `direction: "right"`). |
| `edge_label`, `edge_dashed` | child node | Label / dash on the link from its parent. |
| `direction` | top level | `"down"` (default) or `"right"`. |
| `arrows` | top level | `true` adds arrowheads on parent→child links; default none. |

## Swimlane layout: `lanes` + `steps` + `edges`

Lanes are horizontal bands, one per actor, with the title in a left gutter. Steps sit in a lane at a column; `edges` route as in the grid layout. Use it for cross-team processes and approval flows.

```json
"lanes": [ {"id": "stu", "title": "学员"}, {"id": "sys", "title": "智测平台"} ],
"steps": [
  {"id": "apply", "title": "申请复核", "lane": "stu", "col": 0, "shape": "pill", "role": "start"},
  {"id": "check", "title": "校验时限", "lane": "sys", "col": 1, "role": "primary"}
],
"edges": [ {"from": "apply", "to": "check"} ]
```

| Field | Notes |
|---|---|
| `lanes[]` | `id` (required), `title`, `desc`, `dashed` (outlined band for an outside party). Top to bottom in array order. |
| `steps[]` | Node fields plus `lane` (a lane `id`) and `col` (0-based). |
| `edges` | As in Grid layout. Keep connected steps in the same lane or the same column. |

## Gantt layout: `tasks`

One row per task in array order, a time axis on top. Bars span `start`..`end`; `milestone: true` draws a diamond at `start`; `after` draws dependency arrows. Times are either all `YYYY-MM-DD` dates (an `end` date is included in the bar) or all numbers (`end` is exclusive, unit set by `axis.format`). Nothing depends on today's date: mark "now" with `marker`.

```json
"tasks": [
  {"id": "dev", "title": "开发", "start": "2026-11-05", "end": "2026-11-13", "role": "primary"},
  {"id": "test", "title": "联调", "start": "2026-11-16", "duration": 5, "after": ["dev"]},
  {"id": "ship", "title": "上线", "start": "2026-11-23", "milestone": true, "role": "success", "after": ["test"]}
],
"marker": {"at": "2026-11-09", "label": "今天"}
```

| Field | Notes |
|---|---|
| `tasks[]` | `id`, `title` (left label column), `start`; then `end`, `duration` (days or units) or `milestone: true`. Optional `role`, `desc` (text right of the bar), `after` (array of task ids). |
| `axis` | Top level, optional: `step` (tick spacing in days / units; default picks ≤12 ticks), `format` (number ticks only, `{n}` is the value, e.g. `"W{n}"`), `width` (axis length in px). |
| `marker` | Top level, optional: `at` (a date or number), `label`, `role` (default `warn`). Draws a vertical line. |

## ER layout: `entities` + `relations`

Cards with a colored header (the entity name) and one row per field. Relations route between cards with a cardinality label near each end.

```json
"entities": [
  {"id": "exam", "title": "exam", "role": "primary", "row": 0, "col": 0,
   "fields": [{"key": "PK", "name": "id", "type": "bigint"}, "title"]},
  {"id": "paper", "title": "paper", "row": 0, "col": 1, "fields": ["id", "exam_id"]}
],
"relations": [ {"from": "exam", "to": "paper", "from_card": "1", "to_card": "N", "label": "包含"} ]
```

| Field | Notes |
|---|---|
| `entities[]` | `id`, `title`, `role` (header color), `fields`: each a string or `{key, name, type}` (`key` such as `PK` / `FK`). Optional `row` / `col`; without them entities fill `columns` (top level, default √n rounded up) left to right. |
| `relations[]` | `from`, `to` (entity ids), `from_card`, `to_card` (e.g. `"1"`, `"N"`, `"0..1"`), `label`, `dashed`, `arrow` (`true` adds an arrowhead at `to`). |
| `col_width` | Top level: card width; raise it when a field row is reported. |

## Quadrant layout: `matrix`

A 2×2 plot on two labelled axes. Items sit at `x`, `y` in 0..1, where 0 is the `low` end of the axis.

```json
"matrix": {
  "x": {"label": "投入", "low": "小", "high": "大"},
  "y": {"label": "价值", "low": "低", "high": "高"},
  "quadrants": [ {"title": "马上做", "role": "success"}, {"title": "规划做"}, {"title": "顺手做"}, {"title": "不做", "role": "warn"} ],
  "items": [ {"id": "a", "title": "AI 预评分", "role": "ai", "x": 0.25, "y": 0.72} ]
}
```

| Field | Notes |
|---|---|
| `x`, `y` | `label`, `low`, `high` axis text. |
| `quadrants` | Exactly 4, in order top-left, top-right, bottom-left, bottom-right: `title`, `desc`, `role` (tints the quadrant). |
| `items[]` | `id`, `title`, `desc`, `role`, `x`, `y`. `dot: true` draws a dot with the title beside it instead of a card; `w` fixes the card width. |
| `cell` | Quadrant side in px; default 300 or wider. |

## Free-coordinate layout: `canvas`

The fallback when no layout above fits. Place each element by `x`, `y`, `w` (and `h`) in px from the canvas top left. Shapes, padding, fonts and colors still come from the theme.

```json
"canvas": {"width": 900, "height": 380, "elements": [
  {"id": "q", "shape": "circle", "title": "一道题", "role": "start", "x": 0, "y": 146, "w": 140},
  {"id": "z", "shape": "zone", "title": "判分引擎", "x": 220, "y": 0, "w": 420, "h": 380},
  {"id": "sub", "title": "主观题", "desc": "AI 预评分", "role": "ai", "x": 260, "y": 170, "w": 340},
  {"id": "tip", "shape": "arrow", "points": [[640, 40], [720, 40]], "role": "warn"}
]},
"edges": [ {"from": "q", "to": "sub"} ]
```

| Field | Notes |
|---|---|
| `width`, `height` | Canvas size; elements past it are reported. Omit both to size to the content. |
| `elements[]` box shapes | `card`, `pill`, `diamond`, `circle` (`w` = `h`), `ellipse`, `text`: `id`, `x`, `y`, `w`, optional `h` (default fits the text), `title`, `desc`, `role`, `dashed`. |
| `elements[]` `zone` | Gray container with its title top left: `x`, `y`, `w`, `h` required. Elements go fully inside a zone and below its title. |
| `elements[]` `line`, `arrow` | `points`: ≥2 `[x, y]` pairs in canvas px. `role` takes that role's accent color; `dashed`; `both` (arrow only). |
| `edges` | Top level, as in Grid layout; `from` / `to` are element ids. |

`edges` route like the grid layout, detours included: a fan-out to a column of boxes routes without crossings, and elbows leaving the same side overlap into one trunk. For full control of a bus's trunk position, draw it with `line` and `arrow` elements, as `examples/canvas-freeform.json` does.

## Findings

Exit 2 means the SVG was written and the stderr lines below need fixing. Fix the spec and re-render; do not ship a diagram with findings.

| Line starts with | Cause | Fix |
|---|---|---|
| `LINT edge X->Y crosses node` | Every path the router tried runs through a third card. | Move nodes so X and Y share a row or column, or move the blocker. |
| `LINT edges X and Y end at the same point` | Two arrows reach one card at the same spot; their heads draw as one. | Move one source to another row / column, or merge the two edges into one with a two-line label. |
| `LINT label ... overlaps` | Edge label collides with a card or another label. | Shorten the label, or leave an empty row / column between the nodes. |
| `LINT node ...: line ... is a single character on its own line` | A wrapped title or desc leaves one CJK character (plus punctuation) alone on its last line; the renderer already tried pulling one more character down. | Reword, put a `\n` earlier, or raise `col_width`. |
| `LINT nodes ... share row/col` | Two grid nodes in one cell. | Give one a free cell. |
| `LINT ... unknown node id` / `unknown participant id` | Typo in `from` / `to` / group. | Use an existing `id`. |
| `LINT ... unknown role` | Role not in the table above. | Pick a listed role. |
| `LINT roles [...] carry meaning but there is no legend` | Colors mean something the reader cannot decode. | Add a `legend` entry per role. |
| `LINT message label ... wider than the gap` | Sequence label longer than the space between lifelines. | Shorten it or raise `col_width`. |
| `LINT no layout key` | No layout key, a misspelled one (`node`, `zone`), or an empty list; the SVG is blank. | Use one of the nine keys with a non-empty value. |
| `LINT more than one layout key` | Two layout keys in one spec. | Keep one; move the rest to another spec. |
| `LINT ... sets a color` | A color key or value in the spec. | Delete it; pick a `role`. |
| `LINT tree X->Y crosses` / `relation X->Y crosses` / `dependency X->Y crosses` | A link runs through a third box. | Reorder children, move entities, or reorder tasks. |
| `LINT steps ... share lane/col` / `entities ... share row/col` | Two boxes in one cell. | Give one a free cell. |
| `LINT ... unknown lane` / `unknown dependency` / `unknown entity id` | Typo in `lane` / `after` / `from` / `to`. | Use an existing `id`. |
| `LINT ... wider than` / `does not fit the card` | Lane title, task title or ER field too long. | Shorten it, or raise `col_width`. |
| `LINT task ... starts before its dependency ... ends` / `ends before it starts` / `mix dates and numbers` | Schedule contradicts itself. | Fix the dates. |
| `LINT item ... straddles` / `sticks out` / `covers the quadrant title` / `items ... overlap` | Matrix item badly placed. | Move `x` / `y` into one quadrant, away from the title corner and other items. |
| `LINT elements X and Y overlap` | Two canvas boxes intersect. | Move one or shrink it. |
| `LINT element ... goes past the canvas` / `has a negative x or y` | Element outside the canvas. | Move it in or enlarge `width` / `height`. |
| `LINT element ... straddles the edge of zone` / `covers the title of zone` | Element half in a zone, or on its title. | Put it fully inside, below the title, or fully outside. |
| `LINT element ...: text needs Npx of height` | Fixed `h` too small for the text. | Raise `h` or `w`, or shorten the text. |
| `LINT element ...: a circle needs w == h` / `unknown shape` / `needs numeric 'x', 'y' and 'w'` | Malformed element. | Fix as the message says. |
| `OVERFLOW ...` (to_png.py) | Real browser text width exceeds the card. | Shorten, add `\n` to `desc`, or raise `col_width`. |
| `ERROR ...`, exit 1 | Invalid JSON, duplicate ids, missing id, unknown theme. | Fix as the message says; nothing was written. |
