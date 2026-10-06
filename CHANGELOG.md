# changelog

Use the `/bumpversion` skill to update this file and the version.toml file and manage the changelog. When you're done implementing on a branch, use this to update and maintain the changelog.

```
/bumpversion <major|minor|patch> include all updates in the branch.
```

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
