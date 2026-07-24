# Handoff: daily-review-prep-plan (2026-07-23 19:22)

## Design Docs and Specs

- Design (grilled decisions folded in): `docs/superpowers/specs/2026-07-09-daily-review-prep-assistant-design.md`
- Implementation plan (16 tasks, ready to execute): `docs/superpowers/plans/2026-07-23-daily-review-prep-assistant.md`
- ShotGrid worklist: https://respawn.shotgunstudio.com/page/12787?layout=layout_3
- Sample card: https://respawn.shotgunstudio.com/page/12787#Asset_38811

## Current state

Design is approved for MVP after a full grilling pass; decisions are written into the design doc. The implementation plan is written and saved. No application code has been scaffolded yet. User was offered Subagent-Driven vs Inline Execution for the plan and has not chosen yet. Handoff skills (`read-handoff` / `write-handoff`) were installed earlier this session.

## Next steps

1. Choose execution mode for the plan: Subagent-Driven (recommended) or Inline Execution.
2. Start Task 1 of `docs/superpowers/plans/2026-07-23-daily-review-prep-assistant.md` (project scaffolding under `src/review_prep/`).
3. During Task 9, with an authenticated ShotGrid session, fill real `layout_3` filters/fields into `configs/default_shotgrid_query.json`.
4. Confirm the exact Cadet CLI/launch template string during setup (settings placeholder until then).

## Active branch & repo state

- Workspace: `C:\Users\jgreen2\Documents\CURSOR\RED_Team_ReviewPrep`
- Not a git repository yet (no `.git`). Plan Task 1 commits assume git will be initialized when implementation starts.
- Uncommitted docs present: updated design spec, new implementation plan, handoff skills under `.agents/skills/`.

## What we're building

Daily Review Prep Assistant -- Windows app that prep's the daily 3D review queue from ShotGrid (`layout_3`), downloads RAR/ZIP attachments and/or syncs P4 CLs into the artist's everyday workspace, then opens eligible DCC files via Cadet on first interactive session, with a dashboard for summary / Prepare / Open Again.

## Recent decisions (newest first)

- Implementation plan written (16 tasks: scaffold through PyInstaller + E2E checklist).
- Design doc updated with grilled MVP decisions; status = ready for implementation plan.
- Trust `layout_3` as worklist (no extra Windows-local date gate for selection).
- Slack daily list = out of scope for MVP.
- Archives from ATTACHMENTS (rar primary, zip also); P4 CLs from comments; both routes OK on one card.
- Extract via 7-Zip; Cadet/`apex_r5dev` for launches; MVP assumes Cadet running else log prompt.
- P4 everyday client; skip unsafe files only; CL defaults Source Art/Preflight/Unknown=sync only, WIP=sync and open.
- Schedule 5:00 AM + catch-up; dashboard summary auto-open + ack on close; no toasts.
- Staging root + retention N days in settings; shared ShotGrid script key in Credential Manager.
- Per-user install preferred; Python shared codebase, self-contained installer.

## Key files & locations

- `docs/superpowers/specs/2026-07-09-daily-review-prep-assistant-design.md`
- `docs/superpowers/plans/2026-07-23-daily-review-prep-assistant.md`
- `.agents/skills/read-handoff/SKILL.md`
- `.agents/skills/write-handoff/SKILL.md`
- Cadet install observed: `C:\Program Files\EA\Cadet2\` (SystemTray/Service/Watchdog)
- 7-Zip on this machine: `C:\Program Files\7-Zip\7z.exe`, `c:\depot\tools\bin\7z.exe`
- Reference Cadet log used in grilling: `c:\Users\jgreen2\Downloads\cadet log1.txt`

## Gotchas & constraints

- Workspace is not a git repo yet -- init before following plan commit steps.
- ShotGrid/Slack URLs require auth; adapters must be filled from a live session.
- User `RSPN\jgreen2` looks admin-capable but unelevated in Cursor; prefer no-elevation daily use.
- Do not call raw `maya.exe` as primary launch path -- Cadet toolset `apex_r5dev`.
- Never force/clobber P4 on the everyday client.
- Mapped drive letters are invalid for staging/worker paths (local or UNC only).
