---
description: Initialize this template into a real project — interviews the user, runs setup scripts, patches config, and updates documentation
argument-hint: <optional project name>
---

Read `.agents/skills/project-setup/SKILL.md` and follow it exactly.

Project name suggested by user: $ARGUMENTS

Before anything else:

1. Check the guard: if `pyproject.toml` exists, tell the user the project is already initialized and stop.
2. If $ARGUMENTS is non-empty, treat it as the initial answer to interview question 1b (project name) and continue with question 1a (description) first, then 1c onward.
3. If $ARGUMENTS is empty, start the interview at question 1a (what are you building?).

Do not run any setup scripts until the user has approved the setup summary in step 2 of the skill.
