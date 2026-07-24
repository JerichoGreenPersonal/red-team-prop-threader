---
name: read-handoff
description: Use when the user runs /read-handoff or starts a session and wants to resume from the most recent handoff. Loads the latest doc in docs/handoffs/ into context to seed the session.
---

# Read Handoff

## Overview

Seed the session by reading the **single most recent** handoff in `docs/handoffs/`. Always the latest -- no arguments, no asking which one.

## Steps

1. **Find the latest handoff.** Filenames are `YYMMDD-HHMMSS-<slug>.md`, so a lexical sort is chronological. Take the last entry:
   - Git Bash / Linux / macOS: `ls docs/handoffs/*.md | sort | tail -1`
   - PowerShell: `Get-ChildItem docs/handoffs/*.md | Sort-Object Name | Select-Object -Last 1`

   If the directory is missing or empty, tell the user there is no handoff and stop.
2. **Read the whole file** with the Read tool -- do not skim or summarize from the filename.
3. **Seed the session:** give the user a short summary of the current state, the spec/branch in play, and the first next step from the handoff, so work can continue immediately.
4. **Read-only.** Never modify or delete the handoff.

## Common mistakes

- Reading an older handoff. Sort by the timestamped filename and take the most recent.
- Summarizing without actually reading the file -- you will miss the detail that matters.
- Asking the user which handoff to load. `/read-handoff` always takes the latest.
