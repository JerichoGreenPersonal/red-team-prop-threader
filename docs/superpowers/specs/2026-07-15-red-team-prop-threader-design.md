# RED Team Prop Threader Design

## Summary

RED Team Prop Threader is an internal Slack app that imports up to 30 assets from an API-exportable ShotGrid page, collects group-level and asset-level context in a paginated Slack modal, creates one Slack root message per asset, and maintains a thread index in the channel canvas.

The Slack app is named **RED Team Prop Threader** and exposes `/create-prop-threads`. The first release is installed in the Electronic Arts Slack workspace. Users must invoke it while viewing the target Slack Connect channel from that workspace.

## Goals

- Import a standard ShotGrid page without copying each asset manually.
- Create one discoverable Slack root message/thread per selected asset.
- Notify group contacts once and asset contacts in their relevant messages.
- Keep `INDEX OF PROP REQUESTS` current without overwriting unrelated canvas content.
- Handle duplicate asset threads, partial failures, retries, and post-creation edits safely.
- Support local Windows development and later deployment to approved internal HTTPS hosting.
- Provide an importable Slack app manifest and a detailed administrator setup runbook.
- Replace in-repository template and `rspn-production-tool` identifiers with `red-team-prop-threader`, including package metadata, IDE/workspace files, and documentation.

## Non-goals

- Supporting more than 30 exported assets in one run.
- Scraping ShotGrid HTML pages.
- Allowing arbitrary ShotGrid hosts.
- Editing ShotGrid data.
- Supporting Respawn-workspace invocation in the first release.
- Cancelling a batch after final confirmation.
- Providing user-configurable message templates.

## External prerequisites

- The ShotGrid page is marked **API Exportable**.
- The exported layout includes stable Asset Name and Entity ID columns. Additional columns are ignored unless a later design explicitly adopts them.
- A dedicated read-only ShotGrid script account is available.
- EA IT approves and installs the Slack app from its manifest.
- The bot is invited to each private channel where it will be used.
- Development has an approved configurable HTTPS tunnel.
- Production has approved internal HTTPS hosting and PostgreSQL.

The development pilot channel is `C0B4GJSA1G8`. The production channel ID must be recorded during setup rather than inferred from a channel name.

## User workflow

### Start and canvas preflight

1. An EA-workspace user invokes `/create-prop-threads` in the target channel. A ShotGrid page URL may follow the command.
2. The app verifies that it is invited to the channel and that the user is a channel member.
3. The app retrieves the channel's built-in canvas.
4. If no channel canvas exists, the app asks for confirmation and creates one titled `INDEX OF PROP REQUESTS`.
5. If a channel canvas exists with another title, the app offers to rename it. Declining ends the workflow without changes.

Canvas preflight happens before ShotGrid import or data entry so permission and plan-tier problems fail early.

### Import and validation

1. The app opens a modal with the command's URL prefilled when provided.
2. It accepts only HTTPS page URLs on the configured Respawn ShotGrid host.
3. It extracts the page ID and calls ShotGrid's official CSV page-export API.
4. It requires Asset Name and Entity ID columns.
5. It deduplicates repeated Entity IDs, preserving the first exported occurrence and reporting the removed count.
6. It rejects zero-row exports and exports containing more than 30 rows. Users must narrow the ShotGrid page and rerun.
7. It constructs each individual asset URL from the configured host, entity type, and stable Entity ID.
8. It preserves exported row order throughout the form, message creation, and canvas updates.

Imported asset names, IDs, and links are read-only. Users may exclude individual assets before submission.

### Group-title inference

- If all selected asset titles share one `S<number>` token, the app proposes `SEASON <number> PROP REQUEST THREADS:`.
- The proposed title is editable.
- If inference finds no common season or finds multiple seasons, the title is blank and required.
- Canvas heading matching ignores letter case, surrounding whitespace, and an optional trailing colon. When an existing heading matches, its displayed formatting is preserved.

### Data-entry wizard

Slack modals permit at most 100 blocks. The wizard therefore displays no more than 15 assets per screen and supports at most two asset screens.

Group fields:

- Required Animator: one Slack user.
- Optional Additional People: multiple Slack users.
- Optional Supporting Links: multiline `Label: https://...` entries.

Asset fields:

- Included/excluded state.
- Required Animator: one Slack user for every included asset.
- Optional Additional People: multiple Slack users.
- Optional Supporting Links: multiline `Label: https://...` entries.

Supporting-link labels must be nonempty and URLs must use HTTPS. Duplicate labels are allowed. Every selected person must be a current member of the target channel.

**Next** and **Back** save each screen into a server-side draft. One private draft is retained per user and channel for 24 hours. A later invocation offers **Resume** or **Start Over**.

### Confirmation and processing

The final screen shows:

- Target channel.
- Group title.
- Included asset count.
- Deduplicated-row count.
- Existing assets that will receive another thread.
- Validation warnings.

The user must confirm before public messages are created. Processing cannot be cancelled after confirmation.

Only one batch may process in a channel at a time. A second attempt is rejected with:

> RED Team Prop Threader is currently creating threads for @user.

The lock is channel-scoped and uses a renewable 10-minute lease. An expired job becomes failed, releases the channel, and can be retried safely.

The submitting user receives one private status message updated at major stages: creating messages, updating the canvas, and complete. The final status reports successes and failures and offers **Retry Failed**.

## Slack message design

### Group summary

The app posts the group summary before all asset roots so the batch remains visually adjacent in the channel. It contains:

- Group title.
- Notifying mentions for the group Animator and Additional People.
- Group supporting links.
- Included asset count.
- Processing status.
- **Edit group details** button.

After processing, the app updates the summary with completion and failure counts and a link to the channel canvas.

### Asset root

The app posts one root message per included asset in ShotGrid row order. A separate starter reply is not created.

Each root contains:

- `Latest`.
- A Slack-localized creation timestamp.
- Asset name and individual ShotGrid link.
- Group title.
- Required asset Animator as a notifying mention.
- Optional asset Additional People as notifying mentions.
- Group people as non-notifying display names.
- Group supporting links.
- Asset supporting links.
- **Edit details** button.

The app uses a fixed, version-controlled Block Kit template.

### Post-completion editing

Any current EA-workspace member of the channel may use the edit buttons. As with the slash command, first-release users must interact with the app while viewing the channel from the EA workspace.

- **Edit details** changes asset Animator, Additional People, and supporting links.
- **Edit group details** changes group people and supporting links.
- Group edits update the canvas group summary and the current `Latest` root for every asset in the group.
- Historical roots remain snapshots.
- Edits do not send new notifications.
- Edited roots display the last editor and a Slack-localized update timestamp.
- Asset identity, original creation timestamp, and thread URL are immutable.

## Canvas design

The app edits only the channel's built-in canvas titled `INDEX OF PROP REQUESTS`.

Each normalized group has:

- A season/group heading.
- Group people and supporting links.
- One asset subsection per ShotGrid Entity ID.

Each asset subsection contains:

- Asset name linked to ShotGrid.
- One or more timestamped Slack thread links.
- Exactly one entry marked `Latest`.

When a new thread is created for an asset already in the index:

1. The new root and canvas entry receive their creation timestamp and `Latest`.
2. The prior root retains its original timestamp but loses `Latest`.
3. The prior canvas entry loses `Latest`.

Users may manually edit generated canvas content. The app uses narrow section lookup and replacement rather than replacing a whole group or canvas. If manual changes prevent a precise update, the app preserves surrounding content, appends the new entry, and warns the submitter which prior marker needs manual cleanup.

## Duplicate and idempotency rules

- Duplicate Entity IDs within one export collapse to one asset.
- Reimporting an Entity ID in a later confirmed run intentionally creates a new root.
- Every side effect has an operation record and stable idempotency key.
- Retrying a failed batch never recreates successful summary or asset messages.
- Canvas insertion, prior-root updates, and prior-canvas-marker updates retry independently.
- Exactly one `Latest` marker is the desired state. A manual-edit conflict may temporarily violate it and must be disclosed.

## Partial failures

- Failure for one asset does not stop other assets.
- Successfully posted roots are never deleted automatically.
- If a canvas update fails, the root remains and indexing is marked pending.
- **Retry Failed** processes only missing or incomplete operations.
- A stale lock retry resumes from persisted operation state.
- Errors shown to users identify the affected assets and actionable remediation without exposing credentials or raw API payloads.

## Architecture

The Python 3.11+ project is initialized as `red-team-prop-threader`, with import package `red_team_prop_threader`.

Initialization renames all in-repository template and `rspn-production-tool` identifiers to the new project name. This includes generated package metadata, IDE/workspace files, documentation, and configuration references. The local checkout directory and GitHub repository are not renamed.

The backend is divided into bounded components:

- **Slack transport:** signed HTTPS endpoints, acknowledgement deadlines, command handling, modal navigation, button interactions, and response rendering.
- **ShotGrid adapter:** authentication, page-ID parsing, CSV export, and individual asset URL construction.
- **Import service:** schema validation, deduplication, title inference, selection, and domain-model creation.
- **Draft service:** 24-hour form state and modal pagination.
- **Job service:** confirmation, channel leases, operation planning, progress, retry, and retention.
- **Message service:** deterministic summary/root rendering and safe message updates.
- **Canvas service:** preflight, creation/rename confirmation, heading lookup, narrow edits, and conflict reporting.
- **Persistence interface:** drafts, installations, batches, assets, operations, leases, and audit metadata.
- **Worker:** database-backed job polling and leased execution without a separate Redis dependency.

The HTTPS request process acknowledges Slack promptly and delegates long-running work to the worker.

## Persistence

SQLite is the default local database. Production uses PostgreSQL through the same persistence interface and migrations.

Minimum durable records:

- Slack installation and workspace configuration.
- Channel and channel-canvas identifiers.
- ShotGrid asset identity.
- Batch and group identity.
- Summary and root message timestamps/permalinks.
- Canvas update metadata.
- Operation status and idempotency keys.
- Channel lease owner and expiry.
- Last editor and edit timestamp.

Retention:

- Drafts: 24 hours.
- Detailed completed/failed job payloads: 30 days.
- Minimal asset-to-thread/canvas history: retained indefinitely for duplicate handling.

## Security

- Verify every Slack request signature and reject stale requests.
- Use an EA-workspace Slack installation for the first release.
- Store Slack tokens, signing secret, ShotGrid script name, and ShotGrid script key only in environment/deployment secrets.
- Give the ShotGrid script account read-only access sufficient for page export.
- Restrict ShotGrid input to the configured Respawn HTTPS host.
- Require labelled HTTPS supporting links.
- Validate users against target-channel membership.
- Do not log secrets, full modal payloads, or authentication headers.
- Redact sensitive query strings from logged URLs.
- Apply database migrations explicitly during deployment.

## Slack app configuration deliverables

The repository must include:

- An importable Slack app manifest for **RED Team Prop Threader**.
- Slash command `/create-prop-threads`.
- Description: `Create prop-request threads from a ShotGrid page`.
- A setup step that prompts the administrator to enter the Usage Hint, recommended as `[ShotGrid page URL]`.
- Signed HTTPS request URLs for commands and interactivity.
- The minimum scopes justified method-by-method.
- Instructions for inviting the bot to private channels.
- EA IT review and approval steps.
- Development-tunnel URL update instructions.
- Post-install verification and token-rotation instructions.

The exact scope list must be verified against the Slack methods used during implementation. Expected capabilities include command handling, posting/updating bot messages, reading private-channel metadata and membership, reading user display data, and creating/editing channel canvases. Unused scopes must not be requested.

## Development and deployment

### Local development

- Python 3.11+ and repository-managed `uv`.
- SQLite.
- Configurable external HTTPS tunnel command.
- PowerShell launcher as the maintained implementation.
- Thin `.bat` wrapper for double-click startup.
- Launcher checks dependencies, stops prior owned processes safely, optionally runs tests, starts the web process and worker, starts or validates the configured tunnel, retains readable logs, and displays the Slack request URL.

### Production

- Approved internal HTTPS hosting.
- PostgreSQL.
- Separate web and worker processes.
- Health/readiness endpoints.
- Secret injection through the approved platform.
- Structured logs and operational alerting.
- Database backups appropriate for durable thread mappings.

The service design must not depend on a particular cloud vendor.

## Testing

Automated tests cover:

- ShotGrid URL and page-ID parsing.
- CSV schema aliases, missing required columns, zero rows, and exports over 30 rows.
- Entity-ID deduplication and stable order.
- Season inference and normalized heading matching.
- Supporting-link parsing and validation.
- Channel-member validation.
- Modal pagination, back navigation, draft resume, and draft expiry.
- Deterministic summary and root rendering.
- Duplicate `Latest` transitions.
- Idempotent retries after each possible partial side effect.
- Lease acquisition, renewal, expiry, and channel isolation.
- Retention cleanup.
- Slack signature verification and authorization checks.
- Manual canvas-edit conflict behavior.
- Post-completion asset and group edits.

Contract tests use fake Slack and ShotGrid adapters and recorded, sanitized response shapes. PostgreSQL integration tests verify behavior that differs from SQLite.

End-to-end pilot tests in development channel `C0B4GJSA1G8` cover:

- 1-, 15-, and 30-asset imports.
- Optional command URL prefill.
- More-than-30 rejection.
- Excluding assets.
- Duplicate rows in one export.
- Duplicate assets across runs.
- Manual canvas edits.
- Partial Slack and canvas failures.
- Expired lock recovery.
- Draft resume.
- Asset and group edits.
- Use from the EA workspace in the Slack Connect channel.

## Acceptance criteria

The feature is ready for production review when:

1. A permitted EA user can complete the workflow entirely within Slack.
2. A standard API-exportable ShotGrid page produces the expected individual asset links.
3. Up to 30 selected assets create ordered, correctly mentioned root messages.
4. The group summary appears before those roots and updates on completion.
5. The channel canvas receives a concise, navigable index without unrelated content loss.
6. Duplicate runs create new roots and leave exactly one `Latest` marker when no manual conflict exists.
7. Retries do not duplicate successful work.
8. Post-completion edits update the intended current messages and preserve history.
9. A 10-minute stale lease recovers safely.
10. The manifest and runbook pass EA IT review.
11. The full automated suite and development-channel pilot pass.
12. No active in-repository package, workspace, or documentation identifier retains a template or `rspn-production-tool` project name unless it is part of migration history.

## Deferred decisions

- The approved development tunnel vendor and command.
- The exact internal production hosting platform.
- Whether a later release also installs into the Respawn workspace.
- Adjustments requested by intended-user review before implementation.

These decisions do not change the domain boundaries or first-release Slack workflow.
