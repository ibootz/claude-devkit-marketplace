# Domain docs

This repository uses a single-context domain documentation layout.

## Before exploring

- Read root `CONTEXT.md` when it exists.
- Read ADRs under `docs/adr/` that concern the area being changed.
- If either location does not exist, continue silently. Domain-modeling skills create them lazily when terms or decisions are resolved.

## Layout

- `CONTEXT.md`: domain glossary and shared model for the repository.
- `docs/adr/`: architecture decision records.

## Vocabulary

Use terms as defined in `CONTEXT.md` in issue titles, specifications, hypotheses, refactor proposals, and test names. Avoid synonyms that the glossary rejects.

If a required concept is absent, first consider whether the proposed term is invented language. If the gap is real, record it for domain modeling rather than silently establishing a new term.

## ADR conflicts

Surface any conflict with an existing ADR. Name the ADR, state the contradiction, and explain why reopening the decision may be justified. Do not silently override it.
