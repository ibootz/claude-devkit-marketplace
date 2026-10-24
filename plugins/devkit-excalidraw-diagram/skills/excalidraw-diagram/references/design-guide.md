# Design Guide: Accurate, Readable, Polished

Read this at Design Process Step 4, before any JSON exists. SKILL.md decides *which* visual pattern carries the concept; this file decides whether the result is **true**, **legible**, and **polished**.

Each rule is tagged:
- **[sourced]** — the source states it; key in brackets, URLs at the end.
- **[inferred]** — derived from a sourced principle; the number or Excalidraw mapping is ours.
- **[heuristic]** — a working value with no authoritative source; the render loop overrides it.

---

## 1. Accuracy — what the diagram claims

1. **One abstraction level per diagram.** Services and the functions inside one service never share a canvas; to show both, draw two diagrams. [sourced: Ilograph-1, IcePanel]
2. **Split by perspective, never a master diagram.** Cut along runtime vs deploy, static vs dynamic, core path vs background jobs. Each diagram tells one story. [sourced: Ilograph-3]
3. **Nesting is a claim of containment.** Draw A inside B only when A truly runs in or belongs to B. A PaaS service reached over a private endpoint does not go inside the subnet box. [sourced: Ilograph-1, Azure]
4. **Real names, never placeholders.** Every node carries its real name (service, table, endpoint), its type, and at most one line of responsibility; containers add their tech stack. "Service A" / "Database" teaches nothing. [sourced: C4-notation, Ilograph-2]
5. **One direction per arrow.** Point from the initiator to what it depends on. A two-way exchange is two arrows, or one arrow labelled "request / response". Double-headed arrows read as mutual dependency. [sourced: C4-notation, Azure]
6. **Arrow labels are verb + object and agree with the arrow's direction** ("读取订单", "publishes OrderPlaced"). A bare "uses" / "调用" is no label. Protocols (HTTP, gRPC, AMQP) appear on container-level arrows and below, not on context diagrams. [sourced: C4-notation, C4-checklist, C4-context]
7. **Round trips stay round trips.** Request/response, retries, and orchestration flattened into a left→right pipeline mislead (the "conveyor belt"). Draw the return arrow or the loop, or use a sequence layout. [sourced: Ilograph-2]
8. **Hubs must not erase who talks to whom.** When several producers reach several consumers through one bus / gateway / queue and the pairing matters, split the hub per pairing or label each path (the "fan trap"). [sourced: Ilograph-2]
9. **Simplify by deleting, never by rewiring.** Removing a node must not change how the remaining nodes connect. Every node answers "does this diagram's argument need me?"; if not, delete it rather than shrink it. [sourced: Azure, Fowler]
10. **The "why" lives outside the diagram.** Rationale goes in the caption or surrounding prose; in-diagram text is short labels. [sourced: Ilograph-1, AWS, Google-TW]
11. **Title and legend.** The title names diagram type + scope ("订单服务 · 容器图"). A legend lists every color, line style, shape, and icon that carries meaning. [sourced: C4-notation, C4-checklist]
12. **Context diagrams**: the subject system sits in the center with an explicit boundary; people and external systems surround it. [sourced: C4-context, Azure]

---

## 2. Layout

1. **Plan coordinates as a table before writing JSON**: columns → x, rows → y, then derive element positions arithmetically. For diagrams beyond ~15 nodes, generate the JSON from a short Python script so spacing stays uniform. Deciding content and hand-placing coordinates in one pass is what produces crossed arrows and stacked labels. [inferred: DevTo-layout]
2. **20px grid.** All `x`, `y`, `width`, `height` are multiples of 20 — Excalidraw's own grid (`DEFAULT_GRID_SIZE = 20`), so the file stays aligned when the user edits it. Gaps come from the ladder 20 / 40 / 60 / 80 / 120 / 160. (Carbon's 8pt grid is the same idea; 20 wins here because the editor snaps to it.) [sourced: Excalidraw-src; ladder heuristic]
3. **Proximity defines groups.** Gap inside a group ≤ half the gap between groups (e.g., 40 inside, 80+ between). Proximity overrides color, so color groups must match spatial groups. [sourced: NNg-proximity; ratio inferred]
4. **Clearance for arrows.** Unlabelled connections: shapes ≥ 60 apart. Labelled connections: gap ≥ label width + 40 — a 4-character CJK label at fontSize 16 needs 120. Render test 2026-10-24: at an 80px gap, "转发 HTTP" and "发布事件" ran into the target shapes; at 120 both cleared. [heuristic: Skill-guides; CJK value render-verified]
5. **Zero edge crossings is the first layout goal**; reorder nodes or add a tier before anything else. Then minimize bends: ≤ 2 per arrow. Of five layout aesthetics tested, fewer crossings helped comprehension "by far" the most. [sourced: Purchase-1997; bend limit inferred]
6. **Same role, same size.** Shapes of the same role share identical width and height. [heuristic: Skill-guides]
7. **Size containers from the text, not the other way round.** Width ≈ characters × fontSize × 0.6 for Latin, × 1.0 for CJK, plus ≥ 40 padding; Excalidraw itself pads bound text by only 5px (`BOUND_TEXT_PADDING`). Multi-line height ≈ lines × fontSize × 1.25 + 40. [heuristic; padding sourced: Excalidraw-src]
8. **Capacity is counted in groups.** At one level of the canvas, show ≤ 4–5 sibling groups; more nodes are fine inside a group. Past that, group first or split into an overview plus detail diagrams. Working memory holds about 3–5 meaningful chunks; the older "7 boxes" figure has no diagram-specific support. [sourced: Cowan-2001, Cowan-2010; mapping inferred]

---

## 3. Color

All values come from `color-palette.md`; this section is about *how much* and *where*.

1. **Grayscale first.** Lay the diagram out in neutrals; add a fill only where it marks a role. Color that does not encode meaning is removed. [sourced: Google-TW, RefactoringUI-color]
2. **≤ 3–4 semantic fills per diagram**, plus neutral. Same role → same color across every diagram in a set. [heuristic: Skill-guides, Thornton]
3. **Light fill, same-hue dark stroke.** The lightest shades are fills only — never strokes, never text. [sourced: RefactoringUI-color, WCAG-contrast]
4. **Contrast floors**: text ≥ 4.5:1 against what it sits on, at every size (Excalifont strokes are thin, so the 3:1 large-text allowance is not used); strokes and arrows ≥ 3:1 against the canvas. The palette is pre-checked; a custom color must be checked before use. [sourced: WCAG-contrast, WCAG-non-text; strict text floor inferred]
5. **Color is never the only cue.** Pair it with shape, `strokeStyle`, or a text label. Avoid hue pairs of equal brightness, and never red/green as the sole distinction. [sourced: WCAG-color, Okabe-Ito, AWS, Azure]
6. **Line style has fixed meaning**: `solid` = synchronous / primary path; `dashed` = asynchronous / event / optional; `dotted` = weak dependency or annotation leader. Whatever is used goes in the legend. [sourced: Azure, AWS]
7. **No pure black.** Text and dark strokes use `#1e1e1e` (Excalidraw's own black). [sourced: RefactoringUI-color, Excalidraw-src]
8. **Author in light mode only.** Excalidraw derives dark mode by filtering the whole canvas (`invert(93%) hue-rotate(180deg)`); a hand-made dark palette fights that filter. [sourced: Excalidraw-src]

---

## 4. Typography and emphasis

1. **≤ 3 font sizes per diagram**, from Excalidraw's presets 16 / 20 / 28 / 36 — e.g. title 28 (36 for a single-diagram poster), section labels 20, body 16. Nothing below 16. [sourced: NNg-hierarchy; preset mapping inferred]
2. **≤ 2 dominant elements**: the title and one focal element. Everything else is visibly smaller. [sourced: NNg-hierarchy]
3. **One accent.** Exactly one element or group breaks the pattern — the accent color, or the only `strokeWidth: 4`. An eye lands on the single thing that differs; emphasis everywhere is emphasis nowhere. [sourced: SWD; "only strokeWidth 4" inferred]
4. **Emphasize by quieting the rest.** Push secondary text to the body color and secondary lines to `strokeWidth: 1` instead of enlarging the hero. Opacity stays 100 (SKILL.md rule). [sourced: RefactoringUI-review]
5. **Fonts.** `fontFamily: 5` (Excalifont) by default, `3` for code. For a clean look use `2` (Helvetica) for all prose. One prose family per diagram. [sourced: Excalidraw-src, HN-thread]
6. **Squint test after render.** Look at the PNG as a thumbnail: the first place the eye lands must be the intended focal element. If it lands elsewhere, lower the contrast *there*; do not add more weight to the focal element. [sourced: NNg-hierarchy, SWD]

---

## 5. Containers, borders, icons

1. **Fewer borders.** Group zones use a light fill with `strokeColor: "transparent"`, or a dashed `strokeWidth: 1` gray outline. Put the zone's title in a separate free-floating text at its top-left — bound text auto-centers into the middle of the zone, on top of the shapes inside. Draw zones first (lowest z-order) and bind arrows by explicit element id, so arrows never attach to the zone. [sourced: RefactoringUI-home; zone mechanics heuristic: Skill-guides]
2. **Stroke widths are Excalidraw's presets: 1 / 2 / 4** (thin / medium / bold). [sourced: Excalidraw-src]
3. **Icons always carry a text label**, placed under or beside the icon (gap 20). Library icons stand for concrete products; a generic concept (a queue, a gateway) gets a generic shape, not a vendor logo. Never distort an icon's aspect ratio — `excalidraw_lib.py insert` scales proportionally. [sourced: NNg-icons, Azure, AWS]
4. **Self-drawn icons use the five primitives**: square, circle, triangle, line, dot — 3–4 elements each. [sourced: Rohde; element count inferred]

---

## 6. Arrows

1. **Orthogonal routing for architecture and flow diagrams.** Use `"elbowed": true`, `"roundness": null`, right-angle `points`, and bindings with `fixedPoint` on edge midpoints: right `[1, 0.5]`, left `[0, 0.5]`, top `[0.5, 0]`, bottom `[0.5, 1]`. Fewer turns read cleaner; the path never crosses its own endpoints' shapes. Rendered correctly with this skill's renderer on 2026-10-24. [sourced: Excalidraw-elbow]

   ```json
   {
     "type": "arrow", "elbowed": true, "roundness": null,
     "points": [[0, 0], [80, 0], [80, 200], [160, 200]],
     "startBinding": {"elementId": "a", "focus": 0, "gap": 1, "fixedPoint": [1, 0.5]},
     "endBinding":   {"elementId": "b", "focus": 0, "gap": 1, "fixedPoint": [0, 0.5]},
     "fixedSegments": null, "startIsSpecial": null, "endIsSpecial": null
   }
   ```
2. **Labels are short verb phrases** (2–6 CJK characters, 1–3 English words), placed beside the longest straight segment. [sourced: C4-notation; length heuristic]
3. **Open arrowheads** (`"arrow"`), not large filled triangles. [sourced: AWS]

---

## 7. Where hand-drawn stops

1. **`roughness: 1` on every element, never 2, never mixed in one diagram.** Hand-drawn looks cheap when sketchiness piles up (jitter + handwriting + decoration everywhere), not because it is hand-drawn. [inferred: Budd, Wood-2012]
2. **Quantity by area → `roughness: 0`.** When shape size itself encodes a number, sketchy rendering measurably hurts area judgment. [sourced: Wood-2012]
3. **Clean look on request.** Hand-drawn reads as "draft / idea". When the user asks for a clean, formal, or client-facing look, switch the whole diagram to `roughness: 0` + `fontFamily: 2`. When the audience is external and the user has not said, keep the default and mention in the reply that a clean version is one switch away. [sourced: HN-thread]
4. **No decoration.** No ornamental doodles, stars, or filler shapes. [inferred: Budd]

---

## Sources

| Key | URL |
|---|---|
| C4-notation | https://c4model.com/diagrams/notation |
| C4-checklist | https://c4model.com/diagrams/checklist |
| C4-context | https://c4model.com/diagrams/system-context |
| Ilograph-1 | https://www.ilograph.com/blog/posts/diagram-mistakes/ |
| Ilograph-2 | https://www.ilograph.com/blog/posts/more-common-diagram-mistakes/ |
| Ilograph-3 | https://www.ilograph.com/blog/posts/breaking-up-the-master-diagram/ |
| IcePanel | https://icepanel.io/blog/common-diagramming-mistakes |
| Azure | https://learn.microsoft.com/en-us/azure/well-architected/architect-role/design-diagrams |
| AWS | https://aws.github.io/aws-networking-best-practices/community/conventions/ |
| Fowler | https://martinfowler.com/bliki/UmlAsSketch.html |
| Google-TW | https://developers.google.com/tech-writing/two/illustrations |
| NNg-proximity | https://www.nngroup.com/articles/gestalt-proximity/ |
| NNg-hierarchy | https://www.nngroup.com/articles/visual-hierarchy-ux-definition/ |
| NNg-icons | https://www.nngroup.com/articles/icon-usability/ |
| Purchase-1997 | https://research.monash.edu/en/publications/which-aesthetic-has-the-greatest-effect-on-human-understanding/ |
| Cowan-2001 | https://pubmed.ncbi.nlm.nih.gov/11515286/ |
| Cowan-2010 | https://pmc.ncbi.nlm.nih.gov/articles/PMC2864034 |
| WCAG-contrast | https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html |
| WCAG-non-text | https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html |
| WCAG-color | https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html |
| Okabe-Ito | https://jfly.uni-koeln.de/color/ |
| RefactoringUI-home | https://refactoringui.com/ |
| RefactoringUI-color | https://refactoringui.com/previews/building-your-color-palette/ |
| RefactoringUI-review | https://dev.to/updivision/book-review-refactoring-ui-by-adam-wathan-steve-schoger-2f7m (secondary: book review) |
| SWD | https://www.storytellingwithdata.com/blog/whereareyoureyesdrawn |
| Rohde | https://imagethink.net/sketchnoting-ask-the-expert-fireside-chat-with-mike-rhode |
| Wood-2012 | https://openaccess.city.ac.uk/id/eprint/1274/ |
| Budd | https://www.andybudd.com/archives/2009/04/my_first_impressions_of_balsamiq |
| Excalidraw-src | https://github.com/excalidraw/excalidraw/blob/master/packages/common/src/constants.ts and `colors.ts` (checked 2026-10-24) |
| Excalidraw-elbow | https://plus.excalidraw.com/blog/building-elbow-arrows-part-one |
| HN-thread | https://news.ycombinator.com/item?id=47571376 |
| DevTo-layout | https://dev.to/agasta/i-got-tired-of-ai-diagram-slop-so-i-built-an-open-source-ai-diagram-generator-on-excalidraw-32c4 |
| Skill-guides | https://skills.cat/skills/opencoredev/excalidraw-cli/excalidraw-design-guide, https://skills.cat/skills/sammcj/agentic-coding/excalidraw-diagrams (third-party agent skills, unvalidated numbers) |
| Thornton | https://thomasthornton.cloud/creating-diagrams-with-an-excalidraw-agent-skill-and-excalidraw-mcp/ |
