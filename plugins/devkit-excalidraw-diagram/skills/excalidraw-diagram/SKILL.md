---
name: excalidraw-diagram
description: "把概念、架构、流程画成 Excalidraw 图：生成 `.excalidraw` JSON（按概念选扇出、汇聚、时间线等视觉模式，技术图嵌真实代码与数据片段），再用 Playwright 渲染成 PNG 回看、迭代修版。用户点名要 Excalidraw 图、`.excalidraw` 文件，或要一张能在 excalidraw.com / Obsidian Excalidraw 里继续拖拽编辑的白板图时使用，如「用 excalidraw 画个架构图」「生成一个 .excalidraw 文件」「出张能拖拽改的白板图」「draw this as an Excalidraw diagram」。只说「画个图 / 可视化一下」而没提 Excalidraw 或可编辑白板时，走 devkit-tool:show-me。"
---

# Excalidraw Diagram Creator

Generate `.excalidraw` JSON files that **argue visually**, not just display information.

**Setup:** If the renderer has not been set up yet, or the user asks to set it up, follow **First-Time Setup** under Render & Validate below.

**Skill directory:** In the commands below, `<skill-dir>` is the absolute "Base directory for this skill" path shown when this skill loads. Use it in full; this skill ships inside a plugin cache, not under `.claude/skills/`.

## Customization

**All colors and brand-specific styles live in one file:** `references/color-palette.md`. Read it before generating any diagram and use it as the single source of truth for all color choices — shape fills, strokes, text colors, evidence artifact backgrounds, everything.

To make this skill produce diagrams in your own brand style, edit `color-palette.md`. Everything else in this file is universal design methodology and Excalidraw best practices.

---

## Core Philosophy

**Diagrams should ARGUE, not DISPLAY.**

A diagram isn't formatted text. It's a visual argument that shows relationships, causality, and flow that words alone can't express. The shape should BE the meaning.

**The Isomorphism Test**: If you removed all text, would the structure alone communicate the concept? If not, redesign.

**The Education Test**: Could someone learn something concrete from this diagram, or does it just label boxes? A good diagram teaches—it shows actual formats, real event names, concrete examples.

---

## Depth Assessment (Do This First)

Before designing, determine what level of detail this diagram needs:

### Simple/Conceptual Diagrams
Use abstract shapes when:
- Explaining a mental model or philosophy
- The audience doesn't need technical specifics
- The concept IS the abstraction (e.g., "separation of concerns")

### Comprehensive/Technical Diagrams
Use concrete examples when:
- Diagramming a real system, protocol, or architecture
- The diagram will be used to teach or explain (e.g., YouTube video)
- The audience needs to understand what things actually look like
- You're showing how multiple technologies integrate

**For technical diagrams, you MUST include evidence artifacts** (see below).

---

## Research Mandate (For Technical Diagrams)

**Before drawing anything technical, research the actual specifications.**

If you're diagramming a protocol, API, or framework:
1. Look up the actual JSON/data formats
2. Find the real event names, method names, or API endpoints
3. Understand how the pieces actually connect
4. Use real terminology, not generic placeholders

Bad: "Protocol" → "Frontend"
Good: "AG-UI streams events (RUN_STARTED, STATE_DELTA, A2UI_UPDATE)" → "CopilotKit renders via createA2UIMessageRenderer()"

**Research makes diagrams accurate AND educational.**

---

## Evidence Artifacts

Evidence artifacts are concrete examples that prove your diagram is accurate and help viewers learn. Include them in technical diagrams.

**Types of evidence artifacts** (choose what's relevant to your diagram):

| Artifact Type | When to Use | How to Render |
|---------------|-------------|---------------|
| **Code snippets** | APIs, integrations, implementation details | Dark rectangle + syntax-colored text (see color palette for evidence artifact colors) |
| **Data/JSON examples** | Data formats, schemas, payloads | Dark rectangle + colored text (see color palette) |
| **Event/step sequences** | Protocols, workflows, lifecycles | Timeline pattern (line + dots + labels) |
| **UI mockups** | Showing actual output/results | Nested rectangles mimicking real UI |
| **Real input content** | Showing what goes IN to a system | Rectangle with sample content visible |
| **API/method names** | Real function calls, endpoints | Use actual names from docs, not placeholders |

**Example**: For a diagram about a streaming protocol, you might show:
- The actual event names from the spec (not just "Event 1", "Event 2")
- A code snippet showing how to connect
- What the streamed data actually looks like

**Example**: For a diagram about a data transformation pipeline:
- Show sample input data (actual format, not "Input")
- Show sample output data (actual format, not "Output")
- Show intermediate states if relevant

The key principle: **show what things actually look like**, not just what they're called.

---

## Multi-Zoom Architecture

Comprehensive diagrams operate at multiple zoom levels simultaneously. Think of it like a map that shows both the country borders AND the street names.

### Level 1: Summary Flow
A simplified overview showing the full pipeline or process at a glance. Often placed at the top or bottom of the diagram.

*Example*: `Input → Processing → Output` or `Client → Server → Database`

### Level 2: Section Boundaries
Labeled regions that group related components. These create visual "rooms" that help viewers understand what belongs together.

*Example*: Grouping by responsibility (Backend / Frontend), by phase (Setup / Execution / Cleanup), or by team (User / System / External)

### Level 3: Detail Inside Sections
Evidence artifacts, code snippets, and concrete examples within each section. This is where the educational value lives.

*Example*: Inside a "Backend" section, you might show the actual API response format, not just a box labeled "API Response"

**For comprehensive diagrams, aim to include all three levels.** The summary gives context, the sections organize, and the details teach.

### Bad vs Good

| Bad (Displaying) | Good (Arguing) |
|------------------|----------------|
| 5 equal boxes with labels | Each concept has a shape that mirrors its behavior |
| Card grid layout | Visual structure matches conceptual structure |
| Icons decorating text | Shapes that ARE the meaning |
| Same container for everything | Distinct visual vocabulary per concept |
| Everything in a box | Free-floating text with selective containers |

### Simple vs Comprehensive (Know Which You Need)

| Simple Diagram | Comprehensive Diagram |
|----------------|----------------------|
| Generic labels: "Input" → "Process" → "Output" | Specific: shows what the input/output actually looks like |
| Named boxes: "API", "Database", "Client" | Named boxes + examples of actual requests/responses |
| "Events" or "Messages" label | Timeline with real event/message names from the spec |
| "UI" or "Dashboard" rectangle | Mockup showing actual UI elements and content |
| ~30 seconds to explain | ~2-3 minutes of teaching content |
| Viewer learns the structure | Viewer learns the structure AND the details |

**Simple diagrams** are fine for abstract concepts, quick overviews, or when the audience already knows the details. **Comprehensive diagrams** are needed for technical architectures, tutorials, educational content, or when you want the diagram itself to teach.

---

## Container vs. Free-Floating Text

**Not every piece of text needs a shape around it.** Default to free-floating text. Add containers only when they serve a purpose.

| Use a Container When... | Use Free-Floating Text When... |
|------------------------|-------------------------------|
| It's the focal point of a section | It's a label or description |
| It needs visual grouping with other elements | It's supporting detail or metadata |
| Arrows need to connect to it | It describes something nearby |
| The shape itself carries meaning (decision diamond, etc.) | Typography alone creates sufficient hierarchy |
| It represents a distinct "thing" in the system | It's a section title, subtitle, or annotation |

**Typography as hierarchy**: Use font size, weight, and color to create visual hierarchy without boxes. A 28px title doesn't need a rectangle around it.

**The container test**: For each boxed element, ask "Would this work as free-floating text?" If yes, remove the container.

---

## Design Process (Do This BEFORE Generating JSON)

### Step 0: Assess Depth Required
Before anything else, determine if this needs to be:
- **Simple/Conceptual**: Abstract shapes, labels, relationships (mental models, philosophies)
- **Comprehensive/Technical**: Concrete examples, code snippets, real data (systems, architectures, tutorials)

**If comprehensive**: Do research first. Look up actual specs, formats, event names, APIs.

### Step 1: Understand Deeply
Read the content. For each concept, ask:
- What does this concept **DO**? (not what IS it)
- What relationships exist between concepts?
- What's the core transformation or flow?
- **What would someone need to SEE to understand this?** (not just read about)

### Step 2: Map Concepts to Patterns
For each concept, find the visual pattern that mirrors its behavior:

| If the concept... | Use this pattern |
|-------------------|------------------|
| Spawns multiple outputs | **Fan-out** (radial arrows from center) |
| Combines inputs into one | **Convergence** (funnel, arrows merging) |
| Has hierarchy/nesting | **Tree** (lines + free-floating text) |
| Is a sequence of steps | **Timeline** (line + dots + free-floating labels) |
| Loops or improves continuously | **Spiral/Cycle** (arrow returning to start) |
| Is an abstract state or context | **Cloud** (overlapping ellipses) |
| Transforms input to output | **Assembly line** (before → process → after) |
| Compares two things | **Side-by-side** (parallel with contrast) |
| Separates into phases | **Gap/Break** (visual separation between sections) |

### Step 3: Ensure Variety
For multi-concept diagrams: **each major concept must use a different visual pattern**. No uniform cards or grids.

### Step 4: Sketch the Flow
If the request names a diagram type (C4, sequence, ER, state machine, BPMN, Gantt, mind map, Sankey…), look it up in the **Reference Gallery** below first. Pick the style from **Styles** below.

Read `references/design-guide.md` now — accuracy (one abstraction level, real names, one-direction verb-labelled arrows, nesting = containment), layout numbers (20px grid, group gaps, zero crossings), color and type limits, orthogonal arrows. Then trace how the eye moves through the diagram and plan coordinates as a column/row table. There should be a clear visual story.

### Step 5: Generate JSON
Only now create the Excalidraw elements. **See below for how to handle large diagrams.**

### Step 6: Render & Validate (MANDATORY)
After generating the JSON, you MUST run the render-view-fix loop until the diagram looks right. This is not optional — see the **Render & Validate** section below for the full process.

---

## Large / Comprehensive Diagram Strategy

**For comprehensive or technical diagrams, you MUST build the JSON one section at a time.** Do NOT attempt to generate the entire file in a single pass. This is a hard constraint — Claude Code has a ~32,000 token output limit per response, and a comprehensive diagram easily exceeds that in one shot. Even if it didn't, generating everything at once leads to worse quality. Section-by-section is better in every way.

### The Section-by-Section Workflow

**Phase 1: Build each section**

1. **Create the base file** with the JSON wrapper (`type`, `version`, `appState`, `files`) and the first section of elements.
2. **Add one section per edit.** Each section gets its own dedicated pass — take your time with it. Think carefully about the layout, spacing, and how this section connects to what's already there.
3. **Use descriptive string IDs** (e.g., `"trigger_rect"`, `"arrow_fan_left"`) so cross-section references are readable.
4. **Namespace seeds by section** (e.g., section 1 uses 100xxx, section 2 uses 200xxx) to avoid collisions.
5. **Update cross-section bindings** as you go. When a new section's element needs to bind to an element from a previous section (e.g., an arrow connecting sections), edit the earlier element's `boundElements` array at the same time.

**Phase 2: Review the whole**

After all sections are in place, read through the complete JSON and check:
- Are cross-section arrows bound correctly on both ends?
- Is the overall spacing balanced, or are some sections cramped while others have too much whitespace?
- Do IDs and bindings all reference elements that actually exist?

Fix any alignment or binding issues before rendering.

**Phase 3: Render & validate**

Now run the render-view-fix loop from the Render & Validate section. This is where you'll catch visual issues that aren't obvious from JSON — overlaps, clipping, imbalanced composition.

### Section Boundaries

Plan your sections around natural visual groupings from the diagram plan. A typical large diagram might split into:

- **Section 1**: Entry point / trigger
- **Section 2**: First decision or routing
- **Section 3**: Main content (hero section — may be the largest single section)
- **Section 4-N**: Remaining phases, outputs, etc.

Each section should be independently understandable: its elements, internal arrows, and any cross-references to adjacent sections.

### What NOT to Do

- **Don't generate the entire diagram in one response.** You will hit the output token limit and produce truncated, broken JSON. Even if the diagram is small enough to fit, splitting into sections produces better results.
- **Don't use a coding agent** to generate the JSON. The agent won't have sufficient context about the skill's rules, and the coordination overhead negates any benefit.
- **Don't write a Python generator script.** The templating and coordinate math seem helpful but introduce a layer of indirection that makes debugging harder. Hand-crafted JSON with descriptive IDs is more maintainable.

---

## Visual Pattern Library

### Fan-Out (One-to-Many)
Central element with arrows radiating to multiple targets. Use for: sources, PRDs, root causes, central hubs.
```
        ○
       ↗
  □ → ○
       ↘
        ○
```

### Convergence (Many-to-One)
Multiple inputs merging through arrows to single output. Use for: aggregation, funnels, synthesis.
```
  ○ ↘
  ○ → □
  ○ ↗
```

### Tree (Hierarchy)
Parent-child branching with connecting lines and free-floating text (no boxes needed). Use for: file systems, org charts, taxonomies.
```
  label
  ├── label
  │   ├── label
  │   └── label
  └── label
```
Use `line` elements for the trunk and branches, free-floating text for labels.

### Spiral/Cycle (Continuous Loop)
Elements in sequence with arrow returning to start. Use for: feedback loops, iterative processes, evolution.
```
  □ → □
  ↑     ↓
  □ ← □
```

### Cloud (Abstract State)
Overlapping ellipses with varied sizes. Use for: context, memory, conversations, mental states.

### Assembly Line (Transformation)
Input → Process Box → Output with clear before/after. Use for: transformations, processing, conversion.
```
  ○○○ → [PROCESS] → □□□
  chaos              order
```

### Side-by-Side (Comparison)
Two parallel structures with visual contrast. Use for: before/after, options, trade-offs.

### Gap/Break (Separation)
Visual whitespace or barrier between sections. Use for: phase changes, context resets, boundaries.

### Lines as Structure
Use lines (type: `line`, not arrows) as primary structural elements instead of boxes:
- **Timelines**: Vertical or horizontal line with small dots (10-20px ellipses) at intervals, free-floating labels beside each dot
- **Tree structures**: Vertical trunk line + horizontal branch lines, with free-floating text labels (no boxes needed)
- **Dividers**: Thin dashed lines to separate sections
- **Flow spines**: A central line that elements relate to, rather than connecting boxes

```
Timeline:           Tree:
  ●─── Label 1        │
  │                   ├── item
  ●─── Label 2        │   ├── sub
  │                   │   └── sub
  ●─── Label 3        └── item
```

Lines + free-floating text often creates a cleaner result than boxes + contained text.

---

## Shape Meaning

Choose shape based on what it represents—or use no shape at all:

| Concept Type | Shape | Why |
|--------------|-------|-----|
| Labels, descriptions, details | **none** (free-floating text) | Typography creates hierarchy |
| Section titles, annotations | **none** (free-floating text) | Font size/weight is enough |
| Markers on a timeline | small `ellipse` (10-20px) | Visual anchor, not container |
| Start, trigger, input | `ellipse` | Soft, origin-like |
| End, output, result | `ellipse` | Completion, destination |
| Decision, condition | `diamond` | Classic decision symbol |
| Process, action, step | `rectangle` | Contained action |
| Abstract state, context | overlapping `ellipse` | Fuzzy, cloud-like |
| Hierarchy node | lines + text (no boxes) | Structure through lines |

**Rule**: Default to no container. Add shapes only when they carry meaning. Aim for <30% of text elements to be inside containers.

---

## Color as Meaning

Colors encode information, not decoration. Every color choice should come from `references/color-palette.md` — the semantic shape colors, text hierarchy colors, and evidence artifact colors are all defined there.

**Key principles:**
- Each semantic purpose (start, end, decision, AI, error, etc.) has a specific fill/stroke pair
- Free-floating text uses color for hierarchy (titles, subtitles, details — each at a different level)
- Evidence artifacts (code snippets, JSON examples) use their own dark background + colored text scheme
- Always pair a darker stroke with a lighter fill for contrast

**Do not invent new colors.** If a concept doesn't fit an existing semantic category, use Primary/Neutral or Secondary.

---

## Modern Aesthetics

### Styles

Four styles. One style per diagram, applied to every element; the default is rounded-sans.

| Style | Pick when the user says | `roughness` | prose `fontFamily` | code / JSON evidence `fontFamily` |
|---|---|---|---|---|
| **rounded-sans** (default) | nothing about style; 圆体, 柔和, Nunito, rounded font, soft | 0 | 6 (Nunito) | 3 |
| **hand-drawn** | 手绘, 草图, sketch, whiteboard | 1 | 5 (Excalifont) | 3 |
| **clean** | 干净, 正式, clean, formal, client-facing | 0 | 2 (Helvetica) | 3 |
| **mono** | 等宽, 等宽圆角, 工程风, monospace, blueprint | 0 | 3 (Cascadia) | 3 |

Everything else is shared: `fillStyle: "solid"`, rounded corners as in `references/element-templates.md`, colors from `color-palette.md`. To switch an existing diagram's style, change `roughness` on every element and `fontFamily` on every text element, then re-render: widths shift between fonts.

What each style costs, measured on 2026-10-25 by rendering 4 identifier-heavy technical diagrams in every style with this skill's renderer:
- **clean and rounded-sans:** uppercase `I` and lowercase `l` are the same glyph, so `skuId` reads as `skuld`. On diagrams dense with identifiers (sequence, ER, class, API) where the user named no style, draw the default and mention in the reply that mono avoids this misreading.
- **rounded-sans:** Nunito has no CJK glyphs; Chinese falls back to the system sans-serif, so on a mostly-Chinese diagram it looks almost the same as clean. Only Latin text gets rounded letterforms.
- **mono:** every identifier stays distinct, but CJK characters take a full 1em each, so size containers from the estimate in Text Rules plus one character of slack. `O` and `0` are hard to tell apart. Cascadia draws `->` as → and `<=` as ≤ (ligatures; the text itself is unchanged).

### Stroke Width
- `strokeWidth: 1` — Thin, elegant. Good for lines, dividers, subtle connections.
- `strokeWidth: 2` — Standard. Good for shapes and primary arrows.
- `strokeWidth: 4` — Bold. Reserve for the diagram's single accent (main flow line or key connection). These three values are Excalidraw's own presets; other widths have no button in the editor.

### Opacity
**Always use `opacity: 100` for all elements.** Use color, size, and stroke width to create hierarchy instead of transparency.

### Small Markers Instead of Shapes
Instead of full shapes, use small dots (10-20px ellipses) as:
- Timeline markers
- Bullet points
- Connection nodes
- Visual anchors for free-floating text

---

## Layout Principles

### Hierarchy Through Scale
- **Hero**: 300×150 - visual anchor, most important
- **Primary**: 180×90
- **Secondary**: 120×60
- **Small**: 60×40

### Whitespace = Importance
The most important element has the most empty space around it (200px+).

### Flow Direction
Guide the eye: typically left→right or top→bottom for sequences, radial for hub-and-spoke.

### Connections Required
Position alone doesn't show relationships. If A relates to B, there must be an arrow.

---

## Text Rules

**CRITICAL**: The JSON `text` property contains ONLY readable words.

```json
{
  "id": "myElement1",
  "text": "Start",
  "originalText": "Start"
}
```

Settings: `fontFamily` from the chosen row of **Styles** (`6` for the default rounded-sans style), `textAlign: "center"`, `verticalAlign: "middle"`. Text inside code / JSON evidence artifacts uses `fontFamily: 3` (monospace) in every style so code stays aligned.

Width estimate for sizing containers: each CJK character ≈ 1 × font size, each Latin character ≈ 0.62 × font size (0.6 in monospace); add the container's padding on top.

Font sizes: at most three per diagram, from Excalidraw's presets — title `28` (`36` for a single poster-style diagram), section labels `20`, body and arrow labels `16`. Nothing below 16.

---

## JSON Structure

```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "https://excalidraw.com",
  "elements": [...],
  "appState": {
    "viewBackgroundColor": "#ffffff",
    "gridSize": 20
  },
  "files": {}
}
```

## Element Templates

See `references/element-templates.md` for copy-paste JSON templates for each element type (text, line, dot, rectangle, arrow). Pull colors from `references/color-palette.md` based on each element's semantic purpose.

---

## Reference Gallery

`references/gallery/` holds 69 finished diagrams in 11 categories: architecture (C4, layered, hexagonal, K8s, cloud network, AWS, CQRS, DDD context map, STRIDE threat model, DFD, strangler migration), UML (class, activity, state, use case, sequence), flowchart, swimlane, decision tree, BPMN, ER, data structures (B+ tree, skip list, consistent hashing, LSM), data lineage, protocols (TCP, OAuth PKCE, TLS 1.3, Raft, Saga, packet bit layout), CI/CD, git branches, trace waterfall, flame graph, incident timeline, planning (Gantt, roadmap, kanban, story map, PERT), thinking (mind map, fishbone, 2×2, SWOT, causal loop, Wardley), product (journey map, funnel, test pyramid, Venn, business model canvas, event storming), UI (wireframe, screen flow, component tree), org chart, concept map, and charts. Each entry has a one-line caption, how it was drawn, known flaws, and canvas size.

When the request names a diagram type:
1. List the entries: `grep -n '^### ' '<skill-dir>/references/gallery/README.md'` — one line each, `### NN 图名（图类型）`.
2. Read the matching entry (about 10 lines from its heading) and the PNG on its image line, `references/gallery/png/NN-slug.png`.
3. Borrow the notation, layout skeleton, drawing technique, and canvas size. The content is yours, and so is the style: the gallery is rendered all-monospace with square corners, which is none of the four **Styles**.
4. Sections `## 12` and `## 13` of the README list what Excalidraw draws badly and the better tool for each (dense dependency graphs → Graphviz / D2, data charts → ECharts / Vega-Lite, frequently changing Gantt → Mermaid, executable BPMN → bpmn.io). For those types, tell the user the better tool before drawing.

---

## Asset Libraries (.excalidrawlib)

A node that stands for a concrete, recognizable thing — database, cache, queue, load balancer, browser, mobile client, a named cloud service — reads faster as a library icon than as a labelled box. Abstract concepts keep the visual patterns above.

Libraries live in `.claude/excalidraw-libraries/` (project, searched first) and `~/.claude/excalidraw-libraries/` (user); the public catalog is libraries.excalidraw.com. Every step goes through one script — library JSON is never hand-copied (one icon is often hundreds of elements with freedraw points):

```bash
L='<skill-dir>/references/excalidraw_lib.py'
uv run "$L" list                                  # downloaded libraries
uv run "$L" search system design                  # catalog search, English keywords
uv run "$L" fetch rohanp/system-design.excalidrawlib
uv run "$L" preview rohanp__system-design         # labelled grid PNG of every item
uv run "$L" insert diagram.excalidraw rohanp__system-design '#6' --x=860 --y=-130 --height=130 --id-prefix db
```

1. `list` first; `search` + `fetch` only when nothing downloaded fits.
2. `preview`, then Read the PNG before picking: many libraries have unnamed items (`#0`, `#1`…), and names never show the drawing style. Items are addressed by `#index`, name, or a unique fragment of their name or text.
3. `insert` once per icon, with a descriptive `--id-prefix`. It edits the scene in place and prints JSON: `bbox` places nearby labels and arrows; `anchor` is the element id that arrows bind to (set the arrow's `startBinding` / `endBinding.elementId` to it and add the arrow to that element's `boundElements`). Negative coordinates take the `=` form (`--y=-130`).
4. Icons keep their own style. Pass `--roughness 1` only when a crisp icon clashes with a hand-drawn diagram.
5. Then the normal render-view-fix loop.

---

## Render & Validate (MANDATORY)

You cannot judge a diagram from JSON alone. After generating or editing the Excalidraw JSON, you MUST render it to PNG, view the image, and fix what you see — in a loop until it's right. This is a core part of the workflow, not a final check.

### How to Render

```bash
uv run '<skill-dir>/references/render_excalidraw.py' <path-to-file.excalidraw>
```

This outputs a PNG next to the `.excalidraw` file. Then use the **Read tool** on the PNG to actually view it.

### The Loop

After generating the initial JSON, run this cycle:

**1. Render & View** — Run the render script, then Read the PNG.

**2. Audit against your original vision** — Before looking for bugs, compare the rendered result to what you designed in Steps 1-4. Ask:
- Does the visual structure match the conceptual structure you planned?
- Does each section use the pattern you intended (fan-out, convergence, timeline, etc.)?
- Does the eye flow through the diagram in the order you designed?
- Is the visual hierarchy correct — hero elements dominant, supporting elements smaller?
- For technical diagrams: are the evidence artifacts (code snippets, data examples) readable and properly placed?

**3. Check for visual defects:**
- Text clipped by or overflowing its container
- Text or shapes overlapping other elements
- Arrows crossing through elements instead of routing around them
- Arrows landing on the wrong element or pointing into empty space
- Labels floating ambiguously (not clearly anchored to what they describe)
- Uneven spacing between elements that should be evenly spaced
- Sections with too much whitespace next to sections that are too cramped
- Text too small to read at the rendered size
- Overall composition feels lopsided or unbalanced
- Any arrow crossing another arrow (target is zero)
- Squint test fails: viewed as a thumbnail, the eye lands somewhere other than the intended focal element — lower the contrast where it lands

**4. Fix** — Edit the JSON to address everything you found. Common fixes:
- Widen containers when text is clipped
- Adjust `x`/`y` coordinates to fix spacing and alignment
- Add intermediate waypoints to arrow `points` arrays to route around elements
- Reposition labels closer to the element they describe
- Resize elements to rebalance visual weight across sections

**5. Re-render & re-view** — Run the render script again and Read the new PNG.

**6. Repeat** — Keep cycling until the diagram passes both the vision check (Step 2) and the defect check (Step 3). Typically takes 2-4 iterations. Don't stop after one pass just because there are no critical bugs — if the composition could be better, improve it.

### When to Stop

The loop is done when:
- The rendered diagram matches the conceptual design from your planning steps
- No text is clipped, overlapping, or unreadable
- Arrows route cleanly and connect to the right elements
- Spacing is consistent and the composition is balanced
- You'd be comfortable showing it to someone without caveats

### First-Time Setup
The render script declares its Python dependencies inline (PEP 723), so `uv run` builds and caches the environment on first use; nothing is written into the skill directory. The only one-time step is downloading Chromium for that environment's Playwright version:
```bash
uv run '<skill-dir>/references/render_excalidraw.py' --install-browser
```
The render script prints this exact command when Chromium is missing. `uv` itself must be on PATH; if `uv` is not found, tell the user to install it (https://docs.astral.sh/uv/) rather than falling back to pip. Rendering also needs network access: the HTML template loads `@excalidraw/excalidraw` from esm.sh.

---

## Quality Checklist

### Depth & Evidence (Check First for Technical Diagrams)
1. **Research done**: Did you look up actual specs, formats, event names?
2. **Evidence artifacts**: Are there code snippets, JSON examples, or real data?
3. **Multi-zoom**: Does it have summary flow + section boundaries + detail?
4. **Concrete over abstract**: Real content shown, not just labeled boxes?
5. **Educational value**: Could someone learn something concrete from this?

### Conceptual
6. **Isomorphism**: Does each visual structure mirror its concept's behavior?
7. **Argument**: Does the diagram SHOW something text alone couldn't?
8. **Variety**: Does each major concept use a different visual pattern?
9. **No uniform containers**: Avoided card grids and equal boxes?

### Container Discipline
10. **Minimal containers**: Could any boxed element work as free-floating text instead?
11. **Lines as structure**: Are tree/timeline patterns using lines + text rather than boxes?
12. **Typography hierarchy**: Are font size and color creating visual hierarchy (reducing need for boxes)?

### Structural
13. **Connections**: Every relationship has an arrow or line
14. **Flow**: Clear visual path for the eye to follow
15. **Hierarchy**: Important elements are larger/more isolated

### Technical
16. **Text clean**: `text` contains only readable words
17. **Font**: every prose text element uses the chosen style's `fontFamily` (`6` by default); code / JSON evidence uses `3`
18. **Roughness**: every element uses the chosen style's `roughness` (`0` by default); one style per diagram
19. **Opacity**: `opacity: 100` for all elements (no transparency)
20. **Container ratio**: <30% of text elements should be inside containers

### Visual Validation (Render Required)
21. **Rendered to PNG**: Diagram has been rendered and visually inspected
22. **No text overflow**: All text fits within its container
23. **No overlapping elements**: Shapes and text don't overlap unintentionally
24. **Even spacing**: Similar elements have consistent spacing
25. **Arrows land correctly**: Arrows connect to intended elements without crossing others
26. **Readable at export size**: Text is legible in the rendered PNG
27. **Balanced composition**: No large empty voids or overcrowded regions

### Accuracy & Polish (details in `references/design-guide.md`)
28. **One abstraction level**; nested shapes are real containment
29. **Arrows**: one direction each, labelled verb + object in the arrow's direction; no bare "uses"
30. **Title** names type + scope; **legend** covers every meaning-bearing color, line style, shape, icon
31. **Color is never the only cue**; ≤ 3–4 semantic fills; every color from `color-palette.md`
32. **≤ 3 font sizes**, ≤ 2 dominant elements, exactly one accent
33. **20px grid**; gaps inside a group ≤ half the gaps between groups; same-role shapes same size
34. **Zero arrow crossings**; architecture / flow arrows orthogonal (`elbowed: true`)
