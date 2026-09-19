# HANDOFF: Thread Message Drain 1.1.0

**Date:** 2026-09-18 | **Agent:** Cursor Grok 4.6 | **Branch:** main | **Status:** Complete
**Goal:** Land Thread Message drain on Threader main as 1.1.0 (body + images on one Slack post, @mentions, no mint) and leave EAV deploy as a host-only bounce.

---

## COMPLETED

- [x] **thread_message drain** -> `C:\DEPOT\Respawn\red-team-prop-threader\src\red_team_prop_threader\thread_message_jobs.py` | Tested
- [x] **combined text+images + mentions** -> `C:\DEPOT\Respawn\red-team-prop-threader` commit `d2b4d4d` | Live Slack test succeeded
- [x] **channel= upload fix** -> `C:\DEPOT\Respawn\red-team-prop-threader` commit `af65e2c` | Stops retry spam
- [x] **version 1.1.0 bump** -> `C:\DEPOT\Respawn\red-team-prop-threader\version.toml` | Implemented
- [x] **VERSION 1.1.0** -> `C:\DEPOT\Respawn\red-team-prop-threader\VERSION` | Implemented
- [x] **changelog 1.1.0** -> `C:\DEPOT\Respawn\red-team-prop-threader\CHANGELOG.md` | Implemented
- [x] **focused tests** -> `tests/test_thread_message_jobs.py`, `tests/test_cl_jobs.py`, `tests/test_slack_gateway_unit.py`, `tests/test_worker.py` | 44 passed
- [x] **PR #3 merge** -> `https://github.com/JerichoGreenPersonal/red-team-prop-threader/pull/3` | MERGED `c884cb7`
- [x] **local main == origin/main** -> `c884cb786d83a9c2ecd0e2ada36b8b75ba8ecf35` | VERSION 1.1.0
- [x] **permanent local R:** -> `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\DOS Devices` `R:` = `\??\C:\DEPOT\Respawn\Rdrive_Clone` | This machine only

## INCOMPLETE

- [ ] **EAV1089717 checkout main @ 1.1.0 and bounce** -> `C:\users\jgreen2\documents\github\red-team-prop-threader` | Issue: laptop must not bounce; after merge EAV still needed `git checkout main && pull --ff-only` then `.\bin\run-local.ps1`. Confirm `Get-Content VERSION` is `1.1.0` on that host.
- [ ] **handoff skill stash** -> `git stash` on this clone (`wip: handoff skill from 2026-09-18 session`) | Issue: `/handoff` skill files were stashed off `main` before slack-cl-jobs checkout; not part of 1.1.0

## CURRENT STATE

- **Working:** `origin/main` is 1.1.0 Thread Message drain. Worker drains `kind: thread_message` jobs, posts body+images as one `files_upload_v2` (`channel=`, `initial_comment`), rewrites `@username`, fails old Post CL JSON, stamps `sent.json` with job ids, moves failures to `done/`. This machine has local `R:` mapped to the clone.
- **Broken:** N/A on git. EAV bounce after 1.1.0 merge is unverified from this session.

## FAILED APPROACHES (Don't Repeat)

- **Treat `/handoff` as read-latest** -> Failed: skill writes a new `Handoff_Docs/` file | Latest prior handoff to *read* was `C:\DEPOT\Respawn\red-team-review-prep\docs\handoffs\260915-192518-thread-message-2.4.4-remote.md` plus Threader `docs/handoffs/260915-192030-thread-message-drain.md`
- **Work from `main` or `feature/red-team-prop-threader` before merge** -> Failed: drain lived on `feature/slack-cl-jobs` | Now merged; continue from `main` @ 1.1.0
- **EAV at `af65e2c`** -> Failed: two-post build (text then image) | Pull at least `d2b4d4d`; production main is `c884cb7` / 1.1.0
- **`files_upload_v2(channel_id=...)`** -> Failed: `files_completeUploadExternal() got multiple values for keyword argument 'channel_id'` then inbox retry spam | Use `channel=`
- **Non-elevated HKLM DOS Devices write** -> Failed: `Requested registry access is not allowed.` | Elevate for permanent `R:`
- **`git commit-tree` as bare `git commit-tree` in PowerShell** -> Failed: parsed as `git commit -tree` (`could not read 'ree'`) | Call `& git.exe @('commit-tree', $tree, '-p', $parent)`
- **Mechanical minor from 0.0.3 -> 0.1.0** -> Failed: user locked Threader ship version to 1.1.0 | `version.toml` major=1 minor=1 patch=0
- **ReviewPrep 2.4.4 as this project's version** -> Failed: wrong product | Threader is 1.1.0 only

## KEY DECISIONS

| Decision | Rationale |
|----------|-----------|
| Ship 1.1.0 not 0.1.0 or 2.4.4 | User lock: this product is 1.1.0; 2.4.x is ReviewPrep |
| PR #3 merge commit into `main` | Do not push `main` for the feature; no CI workflows existed; focused tests 44 passed |
| Do not re-implement drain | Behavior already on `d2b4d4d`; live Slack test succeeded |
| One Slack post for text+images | `upload_files` / `files_upload_v2` `file_uploads` + `initial_comment`; no separate `chat.postMessage` |
| Laptop Threader off while EAV live | Same Slack tokens; one Socket Mode instance |
| Keep `C:\DEPOT\Respawn\Rdrive_Clone` name | Already studio-root layout (`Departments\...`) |
| Park Z / Request Form / PR #2 people-naming | Out of this drop |

## RESUME INSTRUCTIONS

Step-by-step for the next agent to continue:

1. **If EAV not on 1.1.0** -> `C:\users\jgreen2\documents\github\red-team-prop-threader` | Expected: `git checkout main`; `git pull --ff-only origin main`; `Get-Content VERSION` prints `1.1.0`; `git log -1` is `c884cb7` or later
2. **Bounce EAV only** -> `.\bin\run-local.ps1` | Expected: `/healthz` 200; worker pid/log fresh; laptop stack off
3. **Live check** -> ReviewPrep Thread Message with body + image | Expected: one Slack thread reply, not two
4. **Do not start this clone's stack** if EAV is live -> `C:\DEPOT\Respawn\red-team-prop-threader\bin\run-local.ps1` | Expected: no second Socket Mode client

**Future (once unblocked):**

- [ ] **Confirm EAV `VERSION` is 1.1.0 and worker is on `c884cb7`** -> Host-only
- [ ] **Optional: apply stashed `/handoff` skill** -> `git stash list` then pop onto a docs branch if still wanted

Verification: `git fetch origin; git rev-parse HEAD origin/main; Get-Content VERSION` (both SHAs equal, file `1.1.0`)

## HOW IT WORKS

- **Flow:** ReviewPrep Confirm writes one inbox JSON + `{job_id}_N` images -> EAV worker `drain_thread_message_inbox` -> one Slack reply (`post_message` if text-only, else `upload_files` with `initial_comment`) -> `sent.json` / `failed.json` / `done/`
- **State/Storage:** jobs on `R:\Departments\Artists\R5_RED\RED_Team_ReviewPrep\SyncedData\SG_Card_Links\slack_jobs\`; this machine aliases that path via `R:` -> `C:\DEPOT\Respawn\Rdrive_Clone`

## SETUP REQUIRED

- Slack tokens in `.env` (`SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_APP_TOKEN`)
- `REVIEWPREP_EXTERNAL_LINKS_ROOT` defaults to `R:\Departments\Artists\R5_RED\RED_Team_ReviewPrep\SyncedData\SG_Card_Links`
- One live Threader: EAV1089717
- EAV git is often GitHub Desktop bundled `git.exe`, not on PATH
- This laptop/dev clone: do not `.\bin\run-local.ps1` while EAV is up

## CODE CONTEXT

Key signatures, API shapes, or snippets the next agent needs:

```
ThreadMessageJob: job_id, asset_id, body, image_filenames, spoke_channel_id, spoke_thread_ts
parse_job(path) -> ThreadMessageJob | None   # None => unsupported / old Post CL
process_thread_message_job(...)              # never mint
drain_thread_message_inbox(jobs_root, slack)
SlackGateway.upload_files(channel_id, file_paths=, thread_ts=, initial_comment=)
  -> files_upload_v2(channel=..., file_uploads=[...], thread_ts=..., initial_comment=...)
stamp_sent(root, asset_id: int, job_id: str)  # job id strings, not CL numbers
fail old JSON: "Unsupported job; send Thread Message"

origin/main @ c884cb7  VERSION=1.1.0
PR https://github.com/JerichoGreenPersonal/red-team-prop-threader/pull/3
```

## WARNINGS

- `2.4.4` / ReviewPrep `VERSION` -> wrong repo; this product is 1.1.0
- `feature/red-team-prop-threader` and `feature/request-form-z-slack-routing` -> do not merge into this drop
- `files_upload_v2` `channel_id=` -> TypeError + inbox retry spam
- `.\bin\run-local.ps1` on laptop while EAV live -> duplicate Slack app connection
- `C:\DEPOT\Respawn\Rdrive_Clone` move/rename -> breaks this machine's boot `R:`
- `list_inbox` only `*.json` -> orphan `{job_id}_0.png` does not post
- Cursor `Co-authored-by` -> strip with `git.exe commit-tree` before push
- This repo has no `.github/workflows` CI

## KEY FILES

- `C:\DEPOT\Respawn\red-team-prop-threader\src\red_team_prop_threader\thread_message_jobs.py` -> drain + mention rewrite
- `C:\DEPOT\Respawn\red-team-prop-threader\src\red_team_prop_threader\cl_jobs.py` -> parse / sent / failed / done
- `C:\DEPOT\Respawn\red-team-prop-threader\src\red_team_prop_threader\slack_gateway.py` -> `upload_file` / `upload_files` with `channel=`
- `C:\DEPOT\Respawn\red-team-prop-threader\src\red_team_prop_threader\worker.py` -> tick calls drain, not mint
- `C:\DEPOT\Respawn\red-team-prop-threader\VERSION` -> `1.1.0`
- `C:\DEPOT\Respawn\red-team-prop-threader\version.toml` -> major 1 minor 1 patch 0
- `C:\DEPOT\Respawn\red-team-prop-threader\CHANGELOG.md` -> 1.1.0 entry
- `C:\DEPOT\Respawn\red-team-prop-threader\docs\handoffs\260915-192030-thread-message-drain.md` -> prior drain handoff
- `C:\DEPOT\Respawn\red-team-review-prep\docs\handoffs\260915-192518-thread-message-2.4.4-remote.md` -> ReviewPrep sibling (2.4.4 is that product)
