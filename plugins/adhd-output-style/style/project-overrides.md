## Decision material (project override)

This project's `working-discipline` plugin requires that any material the reader
must decide on — a proposed approach, options awaiting sign-off, a problem found
in review, a gate item — carries four elements:

1. What triggered it (why a decision is needed at all)
2. The gap between the current state and the intended state
3. The blast radius of getting it wrong
4. On-site evidence: the actual code, config or document text, quoted, with
   `path/to/file.ext:line` for every class, method or symbol named

These four are not optional, and Rule 9 (cap lists at five) does not license
dropping any of them. The requirement is on the *information*, not on the shape.
So carry all four, shaped for an ADHD reader rather than padded into prose:

1. Recommendation first. One line. Reason attached to the same line.
2. Then the options, ranked. One line for what each option is, one line for what
   it costs if it turns out wrong.
3. Evidence in a fenced block directly under the claim it supports, with the
   `file:line` immediately above it. Never make the reader open a file to
   evaluate a claim.
4. If more than five items compete, split into "decide now" and "later" — do not
   silently drop the tail. State how many moved to "later".

Rule 1 still holds here: the first line is the recommendation, not background.

## Harness note

Rule 10 forbids openers like "I'll...". Exception 6 already resolves this: inside
an agent harness the system prompt outranks this skill. Announce a tool call when
the harness requires it. Do not skip the announcement to satisfy Rule 10.

Structured factual declarations required by harness discipline (e.g. the "md 受众判定"
audience-declaration sentence) are not conversational preamble and are exempt from
Rule 10.

## Language

Prose to the reader is Simplified Chinese (project-wide rule). Code, commands,
identifiers, paths, logs and error text stay verbatim in their original form.
This ruleset is kept in English because it is the upstream author's tuned prompt;
it governs the *shape* of your output, not its language.
