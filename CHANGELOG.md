# changelog

Use the `/bumpversion` skill to update this file and the version.toml file and manage the changelog. When you're done implementing on a branch, use this to update and maintain the changelog.

```
/bumpversion <major|minor|patch> include all updates in the branch.
```

## [1.2.5] - 2026-10-30

canvas indexing no longer writes the latest marker, and mint jobs index into an os requests canvas.

### changed
- canvas: thread lines no longer carry the latest label on the satellite or primary canvas. the database latest flag is unchanged.
- mint group: a repeat live job that posts nothing still rewrites the channel index. assets already threaded in the channel are indexed from their spoke records when the local database has no group.

### fixed
- mint group: indexing uses an existing os requests or legacy index canvas, or creates an os requests tab when neither exists. other channel canvases are left alone.

## [1.2.4] - 2026-10-16

a mint group job keeps its slack posts when the share will not let sent.json or failed.json be replaced.

### fixed
- jobs: sent.json and failed.json are rewritten in place when the share denies replacing them with the temp file. no .tmp file is left behind.
- mint group: a sent.json write error is reported as an issue. it no longer fails the job and deletes the group message and asset threads it just posted.

## [1.2.3] - 2026-10-15

a thread message is posted at most once. restarting the worker no longer repeats a message whose sent ledger failed to save.

### fixed
- worker: claim the thread message before calling slack. the same job id, or the same body and images in the same thread, is not posted again.
- worker: if sent.json cannot be replaced after a successful post, the job still leaves the inbox.

## [1.2.2] - 2026-10-07

a multi-name asset cell keeps a clickable shotgrid link on each name.

### fixed
- messages: each line of an asset name is its own shotgrid link, so a newline in the cell no longer leaves the url as plain text.

## [1.2.1] - 2026-10-06

a mint_group job that fails no longer leaves a partial post in slack.

### fixed
- worker: the new group row is saved before the first slack post. messages posted by an attempt that then fails are deleted.

## [1.2.0] - 2026-10-02

drain flightdeck mint_group inbox jobs: create or join the slack group post and mint one thread per request form asset, with live, test-channel, and dry-run modes. people are resolved from sheet chips to slack users by email, then by unique exact name.

### added
- worker: process `kind: mint_group` jobs from the slack_jobs inbox and write `done/{job_id}.result.json` with per-asset outcomes.
- worker: test mode posts to a test channel with plain-text names instead of mentions and records threads under `slack_threads_test`; dry run records posts in `done/{job_id}.preview.json` without writing.
- worker: shared-thread assets get an "also tracked here" reply in the target asset's thread instead of a new thread.
- people: resolve request form people to slack users by email, falling back to a unique exact name match when the email scope is missing.
- config: `SLACK_PEOPLE_TEAM_ID` sets the enterprise grid team used for user lookups.

### changed
- messages: asset thread roots can label the requestor line; mint_group roots use "ic poc".

## [1.1.0] - 2026-09-18

drain ReviewPrep thread_message inbox jobs and reply in the existing slack thread as one post: body plus images, with @mentions. no mint. leftover post cl json is failed and moved off the inbox.

### added
- worker: drain `kind: thread_message` inbox jobs and reply in the existing spoke without minting.
- worker: post body and images together on one slack message and rewrite `@username` to channel-member mentions.

### changed
- worker: `sent.json` stores job id strings for thread_message jobs.

### fixed
- slack gateway: `files_upload_v2` uses `channel=` so uploads do not fail and retry-spam the thread.
- worker: fail leftover post cl json with `unsupported job; send thread message`.

## [0.0.3] - 2026-09-10

drain ReviewPrep slack_jobs inbox on the worker: mint a spoke when missing, reply with the canned cl body, and upload the submission image. first numbered release of this app (version.toml was 0.0.0).

### added
- slack gateway: upload a file into a thread via files_upload_v2 (`files:write`).
- worker: poll `{external_links_root}/slack_jobs/inbox`, stamp `sent.json`, record `failed.json`, move completed jobs to `done`.
- worker: join an existing group or mint a one-asset spoke (`source=mint`), then post the cl reply and image.

### fixed
- parse ReviewPrep job json (integer `asset_id`, `cls` as `{label, number}`) and stamp digit cl strings ReviewPrep can read.
