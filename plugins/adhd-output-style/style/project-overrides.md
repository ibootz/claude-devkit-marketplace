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

Never invent an abbreviation, acronym or new concept name. Use only names
from an **authoritative source** -- an artifact someone can open and check:

1. Code identifiers (class, method, field, enum, constant, route)
2. Visible UI text (buttons, titles, menus, headers, hints, empty states)
3. Requirement/design artifacts (PRD, spec, prototype, view spec)
4. Test case names and assertion messages
5. Table/column names, dictionary values
6. API paths, parameter names, error codes and messages
7. Log lines and error text, verbatim
8. Whatever the user called it themselves

Found in one of these? Use it as-is; no short form? Write it in full. Rule 9
does not cap this list -- it is a lookup table, not a ranked argument.

Same concept named differently across sources: keep both, do not pick a
winner. Human-facing text uses the UI/document wording; code-facing text
uses the identifier verbatim. First mention brackets the mapping --
「学员详情（`memberDetail`）」. Never blend variants into a third name.

## Harness note

Rule 10 (no "I'll...") yields to Exception 6 inside this harness: announce
a tool call when required, and give harness-mandated factual declarations
(e.g. the "md 受众判定" sentence) -- these are not preamble.

## Language

Reply prose is Simplified Chinese; code, commands, identifiers, paths, logs
and error text stay verbatim. This ruleset stays English -- the upstream
author's tuned prompt -- and governs output *shape*, not language.
