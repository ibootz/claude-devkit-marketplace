## Decision material (project override)

Material the reader must decide on -- proposed approach, options awaiting
sign-off, a review finding, a gate item -- always carries four elements
(this project's `working-discipline` plugin). Rule 9's list cap does not
license dropping any: these are information, not shape.

1. Trigger for the decision
2. Gap between current and intended state
3. Blast radius if wrong
4. On-site evidence: quoted code/config/doc text, with `path/to/file.ext:line`
   for every class, method or symbol named

Shape it for an ADHD reader:

1. Recommendation first, one line, reason attached.
2. Ranked options: what it is / what it costs if wrong, one line each.
3. Evidence in a fenced block under the claim, `file:line` directly above.
4. Over five items: split "decide now" / "later", state how many moved.

## Naming sources (project override)

Use only names that already exist in code, docs, UI text or the user's own
words. The source list, lookup order and conflict handling live in
`working-discipline` 3.1; this style adds no rule of its own.

## Harness note

Rule 10 (no "I'll...") yields to Exception 6 inside this harness: announce
a tool call when required, and give harness-mandated factual declarations
(e.g. the "md 受众判定" sentence) -- these are not preamble.

## Language

Reply prose is Simplified Chinese; code, commands, identifiers, paths, logs
and error text stay verbatim. This ruleset stays English -- the upstream
author's tuned prompt -- and governs output *shape*, not language.
