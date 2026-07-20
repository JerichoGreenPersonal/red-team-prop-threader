# Pilot Test — RED Team Prop Threader

Procedure for the first development-channel pilot in Electronic Arts Slack. Run this after the app is installed per [slack-app-setup.md](slack-app-setup.md) and local services are up via `bin/run-local.ps1`.

## Prerequisites

- Bot invited to private development channel `C0B4GJSA1G8`.
- You are viewing that channel from the **EA workspace** (not only a connected external workspace).
- `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, ShotGrid script credentials, and `SLACK_PUBLIC_BASE_URL` are loaded.
- Web and worker processes are running; `GET /healthz` and `GET /readyz` succeed.
- Channel canvas titled `INDEX OF PROP REQUESTS` is ready, or you are prepared to accept create/rename confirmation in the slash-command flow.

## Optional contract checks (opt-in)

These hit live Slack/ShotGrid and are skipped unless explicitly enabled:

```powershell
$env:RUN_SLACK_CONTRACT = "1"
.\uv run pytest tests/contract/test_slack_gateway.py -v

$env:RUN_SHOTGRID_CONTRACT = "1"
.\uv run pytest tests/contract/test_shotgrid_export.py -v
```

Do not leave these environment variables set for routine unit runs.

## Pilot ShotGrid page

Optional documented input (not hard-coded in the app):

```text
https://respawn.shotgunstudio.com/page/23280
```

Use smaller curated exports when you need exact 1 / 15 / 30 row counts.

## Non-destructive preflight

1. In `C0B4GJSA1G8`, run `/create-prop-threads` with no URL.
2. Confirm canvas preflight opens and does not create threads yet.
3. Decline or close without confirming a batch.
4. Confirm no new asset-root messages were posted.

## Scenario checklist

Record pass/fail and notes for each item.

### Import sizes

| # | Scenario | Expected |
| --- | --- | --- |
| 1 | Import **1** included asset, confirm | One summary + one latest root; canvas indexed |
| 2 | Import **15** assets (one modal page), confirm | All roots posted; progress DM updates; summary finalizes |
| 3 | Import **30** assets (two pages), navigate Next/Back, confirm | Order preserved; both pages saved; full batch completes |

### Selection and duplicates

| # | Scenario | Expected |
| --- | --- | --- |
| 4 | Exclude one asset before confirm | Excluded asset has no root |
| 5 | Export with duplicate Entity IDs in one file | Collapsed to one asset in the draft |
| 6 | Re-run the same Entity ID in a later confirmed batch | New root created; prior root loses `Latest`; canvas shows one `Latest` |

### Canvas and failures

| # | Scenario | Expected |
| --- | --- | --- |
| 7 | Manually edit canvas near a managed section, then import a duplicate | Narrow update or safe append + private cleanup warning; unmanaged neighbors preserved |
| 8 | Force a partial failure (for example temporary Slack/canvas denial on one asset) | Other assets continue; successful roots kept; **Retry Failed** only retries incomplete ops |
| 9 | Hold the channel busy / wait out a stale 10-minute lease | Busy copy names the owner without leaking lease tokens; expired lease can be reacquired and resumed from persisted ops |

### Resume and edits

| # | Scenario | Expected |
| --- | --- | --- |
| 10 | Start a draft, close the modal, resume within 24 hours | Draft restored; no duplicate import required |
| 11 | Edit details on a **Latest** asset root | Root updates; last editor + Slack-localized time; no new notification message |
| 12 | Click **Edit** on a historical (non-Latest) root | Refused with link to the current Latest root |
| 13 | Edit group details on the Latest summary | Summary, all Latest roots, and canvas group people/links update without new notifications |

### Workspace boundary

| # | Scenario | Expected |
| --- | --- | --- |
| 14 | Invoke `/create-prop-threads` while viewing the channel from EA | Command works |
| 15 | Attempt the same flow only from a non-EA connected workspace view | First-release behavior remains EA-workspace invocation (document any refusal/UX) |

## Completion criteria

The pilot is ready for IT scope sign-off and broader use when:

- All automated unit/integration checks on the branch are green.
- Scenarios 1–14 pass in `C0B4GJSA1G8` with notes for any accepted limitations.
- Secrets remain only in approved storage (not committed).
- Manifest hostnames still use the approved stable tunnel/production URLs (never an unedited `.example.invalid` in a live app).

## Related docs

- [Slack app setup](slack-app-setup.md)
- Design: `docs/superpowers/specs/2026-07-15-red-team-prop-threader-design.md`
