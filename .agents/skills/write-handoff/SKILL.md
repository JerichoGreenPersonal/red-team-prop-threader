---
name: write-handoff
description: Use when the user runs /write-handoff or asks to save the current session's context so a fresh session can resume. Captures the live session to a timestamped doc in docs/handoffs/.
---

# Write Handoff

## Overview

Capture the live session into one Markdown handoff so a new session with zero memory can resume. **Recent context carries the most weight** -- the reader must learn the current state and the next action first; history goes last.

## Steps

1. **Review the whole conversation**, but weight the most recent exchanges heaviest. The top of the doc describes what is true _now_; older background sinks to the bottom.
2. **Pick a topic slug** -- short kebab-case for the current focus (e.g. `auth-refactor`, `deploy-pipeline`), it should align with what the current context is based on.
3. **Get the real timestamp** as `YYMMDD-HHMMSS` (local). Run `date +%y%m%d-%H%M%S` (Git Bash / Linux / macOS) or `Get-Date -Format "yyMMdd-HHmmss"` (PowerShell). Do not guess it.
4. **Ensure `docs/handoffs/` exists** (create it if missing), then write `docs/handoffs/<YYMMDD-HHMMSS>-<topic-slug>.md`.
5. **Fill the structure below.** Include every heading that applies, omit the rest. Be concrete -- branch names, PR numbers, file paths, commands -- never vague.
6. **Report the written path** back to the user.

## Document structure

Order is deliberate: most actionable first, history last.

```markdown
# Handoff: <topic> (<YYYY-MM-DD HH:MM>)

## Design Docs and Specs

A pointer to any active designed specs, plans, or summaries that will help the read-handoff skill when loading the written out handoff. Only reference docs that have been built, discussed, or planned within the context.

## Current state

One short paragraph: what is true right now, what just happened, what is in flight.

## Next steps

Ordered and specific. Item 1 is what to do first on resume.

## Active branch & repo state

Current branch, open PRs (number + title + status), uncommitted work, anything mid-merge or mid-deploy.

## What we're building

The goal and why it matters. Link the spec/plan path if one exists.

## Recent decisions (newest first)

Decision + one-line rationale. Newest on top.

## Key files & locations

Spec paths, important source files, config, secrets touched, external resources.

## Gotchas & constraints

Tool quirks, workflow rules, environment notes -- anything that will bite a fresh session.
```

## Style

- **Match the repo's writing conventions.** If the house style is ASCII-only, keep it ASCII: straight quotes, `--` not em-dash, no smart quotes.
- **Specific over general:** "PR #50 merged, prod deploy verified via the deploy job" beats "made progress on deploys".
- Assume the reader has **no memory of this session** and must act from the doc alone.

## Common mistakes

- Vague summaries ("worked on stuff"). Name the branch, PR, file, command.
- Chronological wall with the current state buried at the bottom. Now/next goes first.
- Guessing the timestamp instead of reading the clock.
- Writing outside `docs/handoffs/` or with a filename that breaks the `YYMMDD-HHMMSS-slug.md` pattern (it is what /read-handoff sorts on).
