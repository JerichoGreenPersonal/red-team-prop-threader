# Handoff: multiline ShotGrid links 1.2.2 (2026-10-07 10:36)

## Design Docs and Specs

- Spec: `docs/superpowers/specs/2026-10-02-slack-threads-from-request-form-design.md`
- Prior release note: `docs/handoffs/261006-151525-mint-group-1.2.1-shipped.md`
- Flightdeck sibling on `main`: PR #23, version 2.7.1. This fix is Threader only.

## Current state

Prop Threader 1.2.2 is on `main`. PR #6 squash-merged at 2026-10-07T17:35:52Z, merge commit `64401e266a45144476f3adfcf416f253c23f1436`: https://github.com/JerichoGreenPersonal/red-team-prop-threader/pull/6

A multi-name Asset Name cell now renders one ShotGrid link per line. Slack mrkdwn drops a link when the label contains a newline, which is why the TAAL Batch 6 floorpanel and Cambodia posts showed the URL as plain text. `render_asset_root` in `messages.py` was wrapping the whole cell, newlines included, in one `<url|label>`.

Verification before the merge: `pytest` 641 passed, 7 skipped; `ruff check` and `ruff format --check` on the changed files. No CI checks were reported on the PR.

EAV is still on 1.2.1 until it pulls `main` and restarts. Posts already in Slack are not rewritten.

## Next steps

1. On EAV, stop the running web and worker, then:

```powershell
$git = (Get-ChildItem "$env:LOCALAPPDATA\GitHubDesktop" -Filter git.exe -Recurse | Where-Object { $_.FullName -match '\\cmd\\git.exe$' } | Sort-Object FullName -Descending | Select-Object -First 1).FullName
Set-Location C:\users\jgreen2\documents\github\red-team-prop-threader
& $git fetch origin
& $git checkout main
& $git pull --ff-only
& $git rev-parse --short HEAD
Get-Content VERSION
.\uv.exe sync
.\bin\run-local.ps1
```

`VERSION` must be `1.2.2`. `git merge-base --is-ancestor 64401e2 HEAD` must succeed. `64401e2` is the link fix. Later handoff commits on `main` are fine.

2. One `run-local.ps1` is already web plus worker. Do not start Threader on the other PC while EAV is running.
3. The next multi-name asset send gets one clickable ShotGrid link per name. The TAAL posts already in `C02PR101SGH` stay as they were sent. Assets 40217 (signs), 40218 (pipes), 40223 (floorpanels), and 40224 (Cambodia) are the rows with this shape.

## Active branch & repo state

- Worktree: `C:\Users\jgreen2\Documents\CURSOR\RED_Team_ReviewPrep\.worktrees\threader-mint-group-jobs` on `main`.
- Link fix: PR #6, squash `64401e2`. This handoff follows it on `main`.
- Main clone on this PC: `C:\Users\jgreen2\Documents\GitHub\red-team-prop-threader` was left on `feature/red-team-prop-threader`. EAV uses `C:\users\jgreen2\documents\github\red-team-prop-threader`.
- `.env` is gitignored. Do not print it or commit it.
- `uv.exe` in the worktree is gitignored and required by `bin/run-local.ps1`.

## What we're building

Drain `kind: mint_group` jobs. Live posts to the sheet channel and updates canvas **INDEX OF PROP REQUESTS**. A thread root's ShotGrid link is `<url|one asset name line>`. Several names in one cell share one ShotGrid URL and become several links.

## Recent decisions (newest first)

- Patch 1.2.2. The 1.2.1 handoff stays as the record of that release.
- Do not edit the TAAL messages already in Slack. The fix applies on the next send.
- Squash-merged PR #6. No CI checks were reported.
- 1.2.1 still stands: no partial Slack post. Flush the group insert before `chat.postMessage`. `discard_posts` on failure.

## Key files & locations

- `src/red_team_prop_threader/messages.py` -- `_shotgrid_name_links`, used by `render_asset_root`.
- `tests/test_messages.py` -- `test_asset_root_multiline_name_is_one_shotgrid_link_per_line`.
- TAAL job `2438cd58` in `slack_jobs\done`. Assets 40223 and 40224 are the floorpanel and Cambodia examples. URLs were already `https://respawn.shotgunstudio.com/detail/Asset/<id>`.
- Inbox: `R:\Departments\Artists\R5_RED\RED_Team_ReviewPrep\SyncedData\SG_Card_Links\slack_jobs`.

## Gotchas & constraints

- A running worker polls the inbox every 2 seconds. If the worker window is closed, files sit in the inbox until `run-local.ps1` starts it again. The web window does not drain the inbox. `run-local.ps1` replaces `local\logs\worker.log` on start.
- `database is locked` is SQLite giving up after 5 seconds. Web plus worker is the normal pair. A second `run-local.ps1` makes it worse.
- EAV has no `git` on PATH. Use the GitHub Desktop `git.exe`. The command above picks the newest `cmd\git.exe`.
- PowerShell: use the absolute worktree path. `cd .worktrees\threader-mint-group-jobs` fails when the shell is already inside another worktree.
- `origin/feature/daily-review-prep` on this remote is old ReviewPrep history. Do not merge it into Threader `main`.
