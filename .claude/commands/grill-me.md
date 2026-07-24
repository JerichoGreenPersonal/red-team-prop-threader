---
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree
argument-hint: <optional plan or topic to grill on>
---

Read `.agents/skills/grill-me/SKILL.md` and follow it exactly.

Subject suggested by user: $ARGUMENTS

If $ARGUMENTS is non-empty, treat it as the plan or design to interrogate and begin the grilling immediately. If $ARGUMENTS is empty, ask the user what plan or design they want to stress-test before starting.

Ask questions one at a time. For each question, provide your recommended answer. If a question can be answered by exploring the codebase, explore it instead of asking.
