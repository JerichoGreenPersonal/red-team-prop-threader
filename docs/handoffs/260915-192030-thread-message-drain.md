# Handoff: thread-message-drain (2026-09-15 19:20)

## Design Docs and Specs

- Threader drain spec: `docs/superpowers/specs/2026-09-11-thread-message-design.md` (Threader section)
- Threader drain plan: `docs/superpowers/plans/2026-09-14-thread-message-threader.md`
- Copied from sibling ReviewPrep; do not build the parked Z-batch mill
- Remote host: `docs/admin/remote-host.md`
- Prior Post CL handoff (stale for drain): `docs/handoffs/260910-202331-post-cl-cs-handle.md`

## Current state

Thread Message drain is on **`feature/slack-cl-jobs`**. Live EAV1089717 was pulled to **`af65e2c`** (`fix: upload thread images with channel= and stop retry spam`). That build posted body and image as **two Slack posts**, and typed `@ayeager` / `@jgreen2` did **not** notify.

This session's uncommitted follow-up (committed with this handoff) makes text+images **one** `files_upload_v2` (`initial_comment` + `file_uploads`) and rewrites `@username` to `<@U...>` from channel member `name` / display_name. EAV has **not** pulled that follow-up yet.

Earlier live incident (2026-09-14): `files_upload_v2(channel_id=...)` TypeError (`files_completeUploadExternal got multiple values for keyword argument channel_id`). Drain posted the body, left JSON in inbox, worker tick re-posted every poll. Inbox JSON `52acba19-cff7-44bb-80df-7c7bf73da450.json` was moved to `done/` from the laptop via the R: share. User killed the EAV app to stop spam, then restarted on `af65e2c`. Inbox had no JSON after that.

Laptop Threader stays **off**. Do not bounce `C:\Users\jgreen2\Documents\GitHub\red-team-prop-threader` on the laptop (`RSPN-JGREEN2-R5`). That clone is people-naming / PR #2 and does not have this drain.

## Next steps

1. On **EAV1089717** (RDP, not the laptop clone), pull HEAD of `feature/slack-cl-jobs` and bounce:

```powershell
cd C:\users\jgreen2\documents\github\red-team-prop-threader
$git = (Get-ChildItem "$env:LOCALAPPDATA\GitHubDesktop\app-*\resources\app\git\cmd\git.exe" | Select-Object -Last 1).FullName
& $git fetch origin
& $git checkout feature/slack-cl-jobs
& $git pull origin feature/slack-cl-jobs
& $git --no-pager log -1 --oneline
.\bin\run-local.ps1
Invoke-WebRequest http://127.0.0.1:3000/healthz -UseBasicParsing
```

`git log -1` must show the commit that includes one-post uploads and @mention rewrite (on top of `af65e2c`). Keep laptop stack off.

2. Live-test a **new** Thread Message (do not restore leftover inbox JSON/PNGs):
   - Body + image: one Slack post, not two
   - `@ayeager` and `@jgreen2` notify as `<@U...>` if they are in that spoke channel
3. If upload fails again: JSON must land in `done/` (not stay in inbox). Check `slack_jobs/failed.json` and `local\logs\worker.log` on EAV.
4. Parked / out of scope until asked: Z batch mill, Request Form, `ic_poc` on the send job, ReviewPrep UI, merge people-naming PR #2 into slack-cl-jobs.

## Active branch & repo state

- Worktree: `C:\Users\jgreen2\Documents\CURSOR\RED_Team_ReviewPrep\.worktrees\threader-slack-cl-jobs`
- Branch: `feature/slack-cl-jobs` tracking `origin/feature/slack-cl-jobs`
- Origin before this submit: **`af65e2c`**
- Laptop clone `C:\Users\jgreen2\Documents\GitHub\red-team-prop-threader` on **`RSPN-JGREEN2-R5`**: `feature/red-team-prop-threader` (PR #2). Do not implement drain there.
- EAV1089717 clone (same GitHub path **on that machine**): `feature/slack-cl-jobs` at `af65e2c` until it pulls again
- Remote: `https://github.com/JerichoGreenPersonal/red-team-prop-threader.git`
- No PR opened for slack-cl-jobs this session
- `main` is separate; do not merge to main unless asked
- Version on slack-cl-jobs: 0.0.3

## What we're building

ReviewPrep Confirm writes `kind: thread_message` jobs to `{REVIEWPREP_EXTERNAL_LINKS_ROOT}/slack_jobs/inbox/`. Prop Threader on EAV1089717 replies in the existing spoke as Prop Threader: body + 0..n images, no mint, no Google/Z.

ReviewPrep JSON keys (do not rename): `kind`, `job_id`, `asset_id`, `body`, `images` (filenames only), `spoke_channel_id`, `spoke_thread_ts`. No `cls`, no `image_filename`, no mint fields.

## Recent decisions (newest first)

- Text + image(s) = one Slack post via `upload_files` / `files_upload_v2` `file_uploads` + `initial_comment`. Text-only still `post_message`.
- Typed `@username` is rewritten to `<@U...>` from spoke channel members (`users.info` `name` and display_name). Unknown handles stay typed. `@here` / `@channel` / `@everyone` become `<!here>` etc.
- `files_upload_v2` must use `channel=`, never `channel_id=` (slack_sdk TypeError + retry spam).
- On Slack/upload failure: `write_failed` then `move_to_done` so the job cannot loop.
- Worker tick calls `drain_thread_message_inbox`, not `process_cl_jobs`. Never mint thread_message jobs.
- `parse_job` returns `ThreadMessageJob | None`. Old Post CL JSON returns None; drain writes `Unsupported job; send Thread Message` (ASCII hyphen-minus) and moves leftovers to `done/`.
- `stamp_sent(root, asset_id: int, job_id: str)` appends job_id strings, not CL numbers. Legacy CL stamp is `stamp_sent_cls` for mint tests only.
- Inbox path: `{REVIEWPREP_EXTERNAL_LINKS_ROOT}/slack_jobs/inbox/`. Default R: `...\SG_Card_Links`.
- Do not retry leftover `{job_id}_0.png` unless the matching JSON is put back in inbox.
- One live Socket Mode instance: EAV only. This laptop cannot WinRM/SSH/admin-share to EAV; bounce from EAV RDP.
- Cursor may inject `Co-authored-by: Cursor`; strip with `commit-tree` + `update-ref` before push.

## Key files & locations

- Drain: `src/red_team_prop_threader/thread_message_jobs.py` (`process_thread_message_job`, `drain_thread_message_inbox`, `_link_user_mentions`)
- Parse / sent / failed / done: `src/red_team_prop_threader/cl_jobs.py` (`ThreadMessageJob`, `parse_job`, `parse_cl_job`, `stamp_sent`, `stamp_sent_cls`, `move_to_done`)
- Worker tick: `src/red_team_prop_threader/worker.py`
- Upload: `src/red_team_prop_threader/slack_gateway.py` (`upload_file` single-file + `channel=`; `upload_files` multi-file)
- Mint (unused for this kind): `src/red_team_prop_threader/mint_from_job.py`
- Tests: `tests/test_thread_message_jobs.py`, `tests/test_cl_jobs.py`, `tests/test_slack_gateway_unit.py`
- Job drop: `R:\Departments\Artists\R5_RED\RED_Team_ReviewPrep\SyncedData\SG_Card_Links\slack_jobs\` (`inbox/`, `done/`, `sent.json`, `failed.json`)
- EAV logs: `local\logs\web.log`, `local\logs\worker.log`
- Spoke used in live tests: channel `C02PGV4E6KV`, asset 38864 (Loba diamond wings)

## Gotchas & constraints

- `.agents/rules/vcs-safety.md`: explicit user ask for `git commit` / `git push` / `gh pr merge`. No AI attribution in history.
- EAV git is often GitHub Desktop bundled `git.exe`, not on PATH.
- `list_inbox` only sees `*.json`. Orphan PNGs in inbox do not retry by themselves.
- Member mention rewrite only sees users in that spoke channel. If lookup fails, the original `@handle` text is posted.
- Do not start `.\bin\run-local.ps1` on the laptop while EAV is live (same Slack tokens).
- Do not mix `feature/red-team-prop-threader` (PR #2), `feature/adopt-prop-threads`, or ReviewPrep Z/Request Form into this drain.
- Parked: Z batch threads, Request Form mint-if-missing, ReviewPrep composer (already ships).
