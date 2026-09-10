# changelog

Use the `/bumpversion` skill to update this file and the version.toml file and manage the changelog. When you're done implementing on a branch, use this to update and maintain the changelog.

```
/bumpversion <major|minor|patch> include all updates in the branch.
```

## [0.0.3] - 2026-09-10

drain ReviewPrep slack_jobs inbox on the worker: mint a spoke when missing, reply with the canned cl body, and upload the submission image. first numbered release of this app (version.toml was 0.0.0).

### added
- slack gateway: upload a file into a thread via files_upload_v2 (`files:write`).
- worker: poll `{external_links_root}/slack_jobs/inbox`, stamp `sent.json`, record `failed.json`, move completed jobs to `done`.
- worker: join an existing group or mint a one-asset spoke (`source=mint`), then post the cl reply and image.

### fixed
- parse ReviewPrep job json (integer `asset_id`, `cls` as `{label, number}`) and stamp digit cl strings ReviewPrep can read.
