# Issue tracker: Local Markdown

Issues and specs for this repo live as Markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`; do not create a combined tickets file.
- Record triage state as a `Status:` line near the top of each issue file. Use the role strings defined in `triage-labels.md`.
- Append comments and conversation history under a `## Comments` heading at the bottom.

## When a skill says “publish to the issue tracker”

Create a file under `.scratch/<feature-slug>/`, creating the directory when needed.

## When a skill says “fetch the relevant ticket”

Read the referenced file. The user will normally provide its path or issue number.

## Wayfinding operations

`/wayfinder` uses one map and one child file per ticket.

- Map: `.scratch/<effort>/map.md`
- Child ticket: `.scratch/<effort>/issues/NN-<slug>.md`
- Record the ticket type as `Type: research|prototype|grilling|task`.
- Record wayfinding state as `Status: claimed|resolved`.
- Record dependencies as `Blocked by: NN, NN`.
- The frontier consists of open, unblocked, unclaimed tickets; lowest number wins.
- To claim, set `Status: claimed` and save before work starts.
- To resolve, append the answer under `## Answer`, set `Status: resolved`, then append a gist and link to the map’s `Decisions-so-far`.
