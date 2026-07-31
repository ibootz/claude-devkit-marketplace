---
name: find-skills
description: Discovers and installs new skills from the open agent skills ecosystem. Use when the user asks "how do I do X", "find a skill for X", "is there a skill that can...", "can you do X" for a specialized capability, wants to search for tools/templates/workflows, or names a domain they wish they had help with (design, testing, deployment, etc.) and no matching skill is installed yet. Not for an already-installed skill that errors, is outdated, or behaves wrong — that's the heal skill's job, not this one.
---

# Find Skills

Discovers and installs skills from the open agent skills ecosystem via the Skills CLI (`npx skills`), a package manager for modular skill packages.

## Not This Skill When

If the user's own already-installed skill is erroring, outdated, or behaving wrong, use `heal` instead — this skill only searches for and installs skills that aren't installed yet.

## Skills CLI Commands

- `npx skills find [query]` — search interactively or by keyword
- `npx skills add <owner/repo@skill>` — install a skill from GitHub or other sources
- `npx skills check` / `npx skills update` — check / apply updates for already-installed skills
- Browse: https://skills.sh/

## Workflow

### Step 1: Understand What They Need

1. The domain (e.g., React, testing, design, deployment)
2. The specific task (e.g., writing tests, creating animations, reviewing PRs)
3. Whether this is a common enough task that a skill likely exists

### Step 2: Check the Leaderboard First

Before running a CLI search, check the [skills.sh leaderboard](https://skills.sh/) to see if a well-known skill already exists for the domain. The leaderboard ranks skills by total installs, surfacing the most popular and battle-tested options.

For example, top skills for web development include:
- `vercel-labs/agent-skills` — React, Next.js, web design (100K+ installs each)
- `anthropics/skills` — Frontend design, document processing (100K+ installs)

### Step 3: Search for Skills

If the leaderboard doesn't cover the user's need, run the find command. Use specific multi-word queries — "react performance" beats plain "testing"; if a term returns nothing, try a synonym (e.g. "deploy" → "deployment" or "ci-cd").

```bash
npx skills find [query]
```

For example:

- User asks "how do I make my React app faster?" → `npx skills find react performance`
- User asks "can you help me with PR reviews?" → `npx skills find pr review`
- User asks "I need to create a changelog" → `npx skills find changelog`

### Step 4: Verify Quality Before Recommending

**Do not recommend a skill based solely on search results.** Always verify:

1. **Install count** — Prefer skills with 1K+ installs. Be cautious with anything under 100.
2. **Source reputation** — Official sources (`vercel-labs`, `anthropics`, `microsoft`) are more trustworthy than unknown authors.
3. **GitHub stars** — Check the source repository. A skill from a repo with <100 stars should be treated with skepticism.

### Step 5: Present Options to the User

When you find relevant skills, present them to the user with:

1. The skill name and what it does
2. The install count and source
3. The install command they can run
4. A link to learn more at skills.sh

Example response:

```
I found a skill that might help! The "react-best-practices" skill provides
React and Next.js performance optimization guidelines from Vercel Engineering.
(185K installs)

To install it:
npx skills add vercel-labs/agent-skills@react-best-practices

Learn more: https://skills.sh/vercel-labs/agent-skills/react-best-practices
```

### Step 6: Offer to Install

If the user wants to proceed, you can install the skill for them:

```bash
npx skills add <owner/repo@skill> -g -y
```

The `-g` flag installs globally (user-level) and `-y` skips confirmation prompts.

## Common Skill Categories

| Category        | Example Queries                          |
| --------------- | ---------------------------------------- |
| Web Development | react, nextjs, typescript, css, tailwind |
| Testing         | testing, jest, playwright, e2e           |
| DevOps          | deploy, docker, kubernetes, ci-cd        |
| Documentation   | docs, readme, changelog, api-docs        |
| Code Quality    | review, lint, refactor, best-practices   |
| Design          | ui, ux, design-system, accessibility     |
| Productivity    | workflow, automation, git                |

Popular sources beyond the leaderboard: `vercel-labs/agent-skills`, `ComposioHQ/awesome-claude-skills`.

## When No Skills Are Found

If no relevant skills exist:

1. Say so plainly — don't imply a match exists.
2. Offer to help with the task directly using your general capabilities.
3. Suggest the user could create their own skill with `npx skills init`.

Example:

```
I searched for skills related to "xyz" but didn't find any matches.
I can still help you with this task directly! Would you like me to proceed?

If this is something you do often, you could create your own skill:
npx skills init my-xyz-skill
```
