---
description: Interview the user about a project topic and produce a human-readable writeup at Executive, Manager, and/or Engineering density levels (saved to docs/topics/)
argument-hint: <optional topic>
---

Read `.agents/skills/topic-documentation/SKILL.md` and follow it exactly.

Topic suggested by user: $ARGUMENTS

If $ARGUMENTS is empty, start the interview by asking what topic to document. If $ARGUMENTS is provided, treat it as the initial answer to question 1a (the topic) and continue with the rest of the interview from question 1b onward.
