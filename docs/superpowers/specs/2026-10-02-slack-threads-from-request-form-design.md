# Slack Threads from the Request Form

**Date:** 2026-10-02
**Status:** Draft for user review (brainstormed and grilled 2026-10-02)
**Target Release:** RED OS Flightdeck **2.7.0** (minor). Prop Threader **1.2.0** in the sibling repo `red-team-prop-threader`, own PR.
**Branch:** `feature/slack-threads-request-form` from `main` @ 2.6.3.
**Related:** `docs/superpowers/specs/2026-09-11-thread-message-design.md` (same `slack_jobs/` inbox, same product lock); `docs/superpowers/specs/2026-09-03-slack-spoke-open-thread-design.md` (season spoke JSON). Supersedes the never-committed `2026-09-10-request-form-z-slack-routing-design.md` and branch `feature/request-form-z-slack-routing`.

## Problem

Artists and leads fill in the Asset Request Form. Each tab is one Slack group: a channel, a group title, stakeholders, and per-asset IC POCs. Today someone has to rebuild that by hand in Threader (`/create-prop-threads`) after the sheet is done. The sheet already holds the routing in a **slack routing** column; nothing reads it.

## Goals

1. Anyone with Flightdeck can mint official Slack threads for one Request Form tab with little Flightdeck knowledge.
2. Flightdeck reads the tab, pairs each request to its POCs, and shows a summary that looks like the Slack posts it will produce.
3. The user can toggle each asset on or off before sending.
4. Threader on EAV does the Slack work from an inbox job. Flightdeck never holds a Slack token; Threader never reads Google.
5. Safe testing: a dry run with no Slack, and a test channel that never pings anyone or touches official thread records.

## Non-goals

- Editing the sheet from Flightdeck (read-only).
- More than one group per tab.
- Changing stakeholders on a group that already exists.
- Thread Message changes. Post CL stays removed.
- A permission gate on who may send (anyone with Flightdeck, for now).
- Resolving Slack users inside Flightdeck.
- Tabs without a `slack routing` column (for example `S32 Tempest Props`).

## Live sheet findings (2026-10-02 read-only pull, 14 visible tabs)

- Column **Z** header is `slack routing` on 7 tabs. Column positions move (`S32 Arcade - Lunar New Year` has `SG Task Template` after it). Match by header text.
- Each request is a block of rows. Asset Name in **B** and SG Link in **Y** sit on the first row; the rest of the block is blank in A..Y.
- Routing cells hold `Key: value` text in one cell: `Group title`, `Channel`, `Creative stakeholder`, `Additional stakeholders`, `IC POC`, `Additional ICs`, `Shared thread`.
- People are **Google Sheets people chips**. `chipRuns[].chip.personProperties.email` holds the email, which matches Slack. Display text alone cannot be split (`Ryan Lastimosa Eric Barrios Mike Renner` is three chips).
- **Y** is a hyperlinked asset name. Identity is the hyperlink: `/detail/Asset/<id>` or `/page/<n>#Asset_<id>` (`S31.1 ALGS!Y42`). The current parser misses the `#Asset_` form.
- Extra group blocks with empty values are leftover templates (`S31.0 BR_Assets` r74, `32.1 Arcade` r10). Only one group per tab is valid.
- A group block may sit below already-started requests (`S31.1 ALGS` r42). Those requests are OMIT / have no SG link, or already have threads.
- Some emails are off the `respawn.com` domain (`jbosse@ea.com`).

## Locked decisions

| Topic | Choice |
| --- | --- |
| Trigger | **Slack Threads...** button on the OS Rundown tab |
| Scope of one run | One Request Form tab = one group |
| Ready flag | None on the sheet. Flightdeck infers readiness |
| Routing column | Header `slack routing` (case-insensitive), any position |
| Request | Row with a non-empty Asset Name; owns rows down to the next named row |
| Asset id | SG Link hyperlink, either URL form. No link: blocked `No SG Link` |
| People | One people chip = one person, keyed by email. Text without a chip: shown `not tagged: <text>`, not sent |
| Group | Exactly one filled `Group title:` block per tab; applies to every request on the tab wherever it sits |
| Empty template blocks | Ignored |
| Two filled blocks | Tab blocked: `2 group blocks (rows X, Y); fix the sheet` |
| Channel | Must match `^[CG][A-Z0-9]+$`; else tab blocked `Channel missing or not an ID` |
| Season | `canonical_season_key(tab_title)` (`32.1 Arcade` -> `S32.1`, `S31.0 BR_Assets` -> `S31`) |
| Already threaded | Any season file in `slack_threads/` has the asset: locked off, link shown |
| Empty IC POC | Toggle **on**, clearly flagged `No IC POC` |
| Shared thread | `Shared thread: X` -> one reply in X's thread, no new root; index lists the asset with X's Thread link; season entry points at X's thread. Needs X on this tab or already threaded |
| Existing group (same title in channel) | Join it: no new top post; edit its asset count; stakeholders unchanged; new assets added under it in the index |
| POC not in channel | Still @-mentioned; reported `mentioned, not in channel`; no auto-invite |
| Summary layout | Checklist left, Slack preview right (top post pinned, selected row's thread root below) |
| After Send | Same window shows `Queued for Threader` with **Close** and **Open Channel** |
| Queued visibility | Status bar plus the picker row (`Queued` -> `Done` / `Done with issues` / `Failed: <reason>`) |
| Double send | Allowed. Threader re-checks threads and groups at execution |
| Job split | Flightdeck writes a fully resolved `kind: mint_group` job; Threader resolves people to Slack users and posts |
| Send modes | Settings **Slack Threads send mode** (per user): `Live`, `Test channel`, `Dry run`. Default `Dry run` |
| Live gate | Anyone may pick Live. Live Send opens an extra confirm: `This posts to the real channel <channel>. Continue?` |
| People lookup | Threader: exact unique name match in Respawn now; email lookup once `users:read.email` is granted (requested in parallel) |
| Test channel | Default `C0B4GJSA1G8` (`#red-slackbot-dev`). Public channel (accepted: no pings, content not sensitive); bot membership verified 2026-10-02 |
| Test mentions | Plain text `Name (email) - would tag U…`; nobody is pinged |
| Test records | Never written to `slack_threads/` or the index; Threader writes `slack_threads_test/` |
| Version | Flightdeck 2.7.0, Threader 1.2.0 |

## Architecture

```
OS Rundown tab -- [Slack Threads...]
        |
        v
Picker   fresh read-only Request Form fetch on open + Refresh
        |  pick tab
        v
Summary  checklist + Slack preview, toggles, mode banner
        |  Send
        v
{external_links_root}/slack_jobs/inbox/{job_id}.json   kind: mint_group
        |                                   ^
        v                                   |  Flightdeck reads result / sent / failed
Threader (EAV1089717)                       |
  pick channel -> recheck -> resolve people -> join or create group
  -> thread roots -> shared-thread replies -> season JSON + index
  -> done/{job_id}.result.json, sent.json / failed.json, move to done/
```

### Flightdeck units

| Unit | Responsibility |
| --- | --- |
| `request_form_parser.py` (fix) | `parse_sg_link_cell` accepts `/detail/Asset/<id>` and `#Asset_<id>`. Shared with OS Rundown |
| `google_sheets_adapter.py` (add) | `fetch_request_form_routing_tabs(url)`: visible tabs with values, hyperlinks, and per-cell chip emails (`chipRuns`) |
| `slack_routing_parser.py` (new, pure) | One tab -> `TabRouting` (group, requests, tab problems) |
| `slack_routing_plan.py` (new, pure) | `TabRouting` + known spokes -> rows with status and default toggle; picker counts |
| `slack_cl_jobs.py` (add) | `write_mint_group_job(...)`, atomic; `read_mint_group_result(...)` |
| `slack_spoke.py` (add) | `read_all_season_spokes(root)`: every `slack_threads/*.json`, read-only |
| `settings.py` / `ui/settings_wizard.py` | `slack_threads_mode` (`live` / `test` / `dry_run`, default `dry_run`), `slack_threads_test_channel_id` (default `C0B4GJSA1G8`) |
| `ui/slack_threads_dialog.py` (new) | One window: picker, summary, queued screen |
| OS Rundown tab | **Slack Threads...** button opens the dialog |

`request_form_mint` (the removed Post CL map) is not read or changed.

### Threader units (sibling repo, own plan)

- Parse `kind: mint_group`; existing `thread_message` drain unchanged.
- People resolver: exact name match now; `users.lookupByEmail` once `users:read.email` is granted (see People resolution).
- Extend the existing, currently unused `mint_from_job.py` (Post CL era, single asset) to many assets: group find by `channel_id` + `normalized_title` else create, `render_group_summary` / `render_asset_root`, history records (keeps **Edit POCs** working), `upsert_season_spoke(source="mint")`. Add the INDEX OF PROP REQUESTS and best-effort PRIMARY index update, which `mint_from_job` lacks today.
- Mode handling: dry run (no Slack calls), test channel (plain-text people, `slack_threads_test/`), live.

## Parsing rules

Given one tab's values grid, hyperlink grid, and chip grid:

1. Header row is row 1. Find the Asset Name, SG Link, and `slack routing` columns by header text (existing fallbacks for Asset Name and SG Link). No `slack routing` column: tab state `No slack routing column`, not selectable.
2. Requests: every row from row 2 with a non-empty Asset Name. Each owns rows up to (not including) the next request row.
3. Routing lines: each non-empty routing cell is split at the first `:` into key and value. Keys are normalized (lower case, single spaces). Unknown keys are ignored. Cells without `:` are ignored.
4. Group block: a `group title` line starts a block; the following `channel`, `creative stakeholder`, `additional stakeholders` lines (until the next `group title` or `ic poc`) belong to it. A block whose group title value is empty is a template and is ignored.
5. Tab group: exactly one non-template block. Zero: `No Group title`. Two or more: `N group blocks (rows ...)`.
6. Per request: the first `ic poc` and the first `additional ics` line inside its row range. A `shared thread` line inside its range sets `shared_thread_with` to the value text (an Asset Name or asset code on the same tab).
7. People values: the chip emails inside that cell's value, in order, with their display text. Value text not covered by any chip is reported as `not tagged: <text>` and dropped from the job.
8. Asset id: SG Link hyperlink (cell `hyperlink`, else URL in the text). Skip CUT rows (existing batch-column rule) and names containing `OMIT` as blocked `Omitted`.

## Row status

| Status | Toggle | When |
| --- | --- | --- |
| Ready | On | Asset id, valid tab group, no known spoke |
| Ready - No IC POC | On, warning | Ready with empty or chip-less IC POC |
| Shared thread | On | `shared_thread_with` names a request on this tab that is toggled on, or an asset with a known spoke |
| Already threaded | Locked off | Known spoke in any season file |
| Blocked | Locked off | Omitted / CUT / TBD with no SG link, `No SG Link`, `Duplicate of row N`, `Shared thread target not found` |

- If the tab is blocked, every row is locked and Send is disabled.
- Send is disabled when no row is on.
- Turning off a shared-thread target that is not already threaded turns its dependents to `Shared thread target not sent` (locked off).

## UI

### Picker

Window title **Slack Threads**. Header shows `Sheet read <time>` and **Refresh**. One row per visible Request Form tab:

`Tab | Group | Ready (n no IC POC) | Threaded | State`

State is blank, `Queued <time>`, `Done <time>`, `Done with issues`, `Failed: <reason>`, `Still queued - check Threader on EAV` (no result 10 minutes after queue), or a tab problem. Problem tabs are grey and cannot open. Double-click or **Open** opens the summary.

### Summary

- Title `Slack Threads - <tab>`. Line `Posting to <channel id>`.
- Mode banner: Test channel (amber, `TEST MODE - posting to <test channel>, not <channel>. No one is @-mentioned. Official thread records are not changed.`) or Dry run (`DRY RUN - nothing is posted to Slack`). Live has no banner.
- Left: checklist `toggle | Asset | IC POC | Status`, sheet order.
- Right: the group top post preview, then the selected row's thread root preview. Flightdeck cannot see Threader's groups, so the top post always renders in new-group form with the note `If this group already exists in the channel, Threader joins it and skips this post.` Previews follow Threader's `render_group_summary` / `render_asset_root` text, with people shown by display name.
- Footer: `<n> threads will be created - <m> skipped`, **Cancel**, **Send to Threader** (`Send to TEST channel` / `Run dry run` by mode). In Live, Send first shows `This posts to the real channel <channel>. Continue?` (Yes / No).

### Queued screen

`Queued for Threader`, a one-line description (`<n> threads in <channel> under <group>`), **Close**, **Open Channel** (`https://respawn.slack.com/archives/<channel or test channel>`; hidden in Dry run). Status bar: `Slack threads queued for <tab> (<n>)`, later `... done: <n> created` / `... done with issues` / `... failed: <reason>`.

## Job JSON

Written to `{external_links_root}/slack_jobs/inbox/{job_id}.json` via `.tmp` + replace. Only toggled-on rows. Keys are stable; Threader must not rename them.

```json
{
  "kind": "mint_group",
  "job_id": "uuid4",
  "created_at": "2026-10-02T22:15:00Z",
  "sent_by": "<Settings user_name>",
  "flightdeck_version": "2.7.0",
  "mode": "live",
  "test_channel_id": "",
  "tab_title": "S32 KC_MU5",
  "season_id": "S32",
  "group": {
    "title": "S32 KCMU5 OS Assets",
    "channel_id": "C02PR101SGH",
    "creative_stakeholder": {"name": "Eduardo Agostini", "email": "eagostini@respawn.com"},
    "additional_stakeholders": [{"name": "Jason McKenzie", "email": "jamckenzie@respawn.com"}]
  },
  "assets": [
    {
      "asset_id": 37177,
      "name": "crypto_holo_map_canyonlands_mu5",
      "sg_url": "https://respawn.shotgunstudio.com/detail/Asset/37177",
      "ic_poc": [{"name": "Jared Bosse", "email": "jbosse@ea.com"}],
      "additional_ics": [],
      "shared_thread_with": null
    }
  ]
}
```

`mode` is `live`, `test`, or `dry_run`. `test_channel_id` is required when `mode` is `test`. `creative_stakeholder` may be null. `shared_thread_with` is the target's `asset_id` (Flightdeck resolves the name on the tab to an id before writing).

## Threader behavior

1. Destination: `test_channel_id` in test mode, else `group.channel_id`. Not a member: fail job `Bot not in channel`.
2. Recheck: assets with a spoke in any season file (live) or in `slack_threads_test/` (test) are `skipped: already threaded`.
3. People: resolve each person per **People resolution** below. Miss: plain-text name, recorded `not tagged` with the reason. Never fails the job. Test mode renders `Name (email) - would tag U… (via <method>)` or `Name (email) - not found` / `- 2 matches` for every person.
4. Group: normalized title match in the destination channel joins; else post the group top post. On join, edit the existing top post (`chat.update`) so its asset count includes the new assets; its stakeholders, links, and title are left unchanged.
5. Roots: sheet order, `render_asset_root` with the IC POC label.
6. Shared thread: after roots, post one reply in the target thread: `Also tracked here: <asset name> (ShotGrid ID: <id>)` with its ShotGrid link and IC POC line. List the asset in the index under the group with the **target's** Thread link. Write the asset's season entry with the target `channel_id` / `thread_ts` / permalink so **Open thread** on its card goes to the target thread. No root of its own.
7. Records: live -> `slack_threads/{season}.json` (`source: mint`) and the index (new group: insert its section; joined group: add the new asset entries under the existing section); test -> `slack_threads_test/{season}.json` only; dry run -> `done/{job_id}.preview.json` with every payload it would send, no Slack calls.
8. Report: `done/{job_id}.result.json` `{job_id, status: done|done_with_issues|failed, error, assets: [{asset_id, outcome: created|joined|shared|skipped|failed, reason, not_tagged: [...]}]}`. Stamp `sent.json[asset_id]` with `job_id` for created/shared assets; `failed.json` on whole-job failure; move JSON to `done/`.

A failure on one asset does not roll back others. Re-sending the tab is safe because of step 2.

### People resolution

The app is installed at the Enterprise Grid org level (`E6GDLMBCM`) and granted the **Respawn** (`T0297NTAU`) and **Electronic Arts** (`T039ZEK3W`) workspaces. `users.list` requires `team_id`; use Respawn.

1. **Email (when available).** If the app has `users:read.email`, `users.lookupByEmail(email)`. A hit wins.
2. **Name (today).** `users.list(team_id=T0297NTAU)`, cached per job. Skip deleted users, bots, and Slackbot. Normalize the chip display name and each user's `real_name` / `profile.display_name` (NFKD, strip accents, collapse spaces, lower case). Accept only when exactly one user matches.
3. Otherwise `not tagged` with reason `not found` or `N matches`.
4. **Channel membership.** A resolved person who is not a member of the destination channel is still @-mentioned (this replaces `mint_from_job`'s silent drop via `validate_channel_members`). The bot posts, so Slack shows no invite prompt and the person may not be notified; the result lists them as `mentioned, not in channel` so someone can invite them. No auto-invite.

Threader detects the email scope at startup (from the token's granted scopes) and logs which method is active. Requesting `users:read.email` (manifest edit + reinstall, possibly admin approval) happens in parallel and is not a release blocker.

Measured 2026-10-02 against Respawn (2,316 active users, 12 unique people on the 7 routing tabs): **9 of 12** matched by name, 0 wrong. Misses: `Ryan Lastimosa` (2 accounts), `Mine Yilmaz-Ulas` (`mulas@ea.com`, not found), `ryan@respawn.com` (email-format chip; no name to match). Email lookup is expected to resolve all three.

## Error handling

| Case | Behavior |
| --- | --- |
| No Google credentials / fetch error | Picker: `Couldn't read the Request Form: <reason>`; Refresh retries |
| External links root missing at Send | Summary stays: `Couldn't queue job: <error>`; no partial JSON |
| Test mode with empty test channel | Send disabled: `Set a test channel in Settings` |
| Sheet changed after read | Not detected; summary shows `Sheet read <time>` |
| Whole-job Threader failure | Picker `Failed: <reason>`; status bar same |
| Partial failure / untagged people | Picker `Done with issues`; summary shows per-asset result |
| No result after 10 minutes | Picker `Still queued - check Threader on EAV` |

## Testing

- `slack_routing_parser`: fixtures built from `S31.1 ALGS` (block at r42 after OMIT rows), `S32 KC_MU5` (shared threads, off-domain email, plain-text email chip), `S31.0 BR_Assets` (empty template block), `32.1 Arcade` (two template blocks), `S32 Tempest Props` (no routing column).
- `parse_sg_link_cell`: both URL forms; regression for OS Rundown identity.
- `slack_routing_plan`: every status, default toggles, shared-thread dependency on toggle-off, duplicate ids, picker counts.
- `write_mint_group_job`: keys, modes, atomic write, no files on failure.
- `slack_threads_dialog`: focused UI tests with `pytest-timeout` (never unbounded `uv run pytest`).
- Threader (sibling plan): mocked Slack; join vs create; recheck skip; unknown email; shared thread; partial failure; test and dry run never write `slack_threads/` or the index.
- Manual gate, in order, all through EAV (laptop Threader stays off): dry run (check `done/{job_id}.preview.json`); test-channel run into `#red-slackbot-dev`; one live tab.

## Rollout

1. Flightdeck 2.7.0 behind the send mode (default `Dry run` until the test-channel pass succeeds; then the user switches to `Live`).
2. Threader 1.2.0 deployed to EAV1089717 and bounced. Laptop Threader stays off.
3. Standalone zip rebuilt from this branch after the 2.7.0 bump (`RED_OS_Flightdeck_Standalone.zip`).

## Known risks

- `Already threaded` freshness depends on `slack_threads/*.json`; recent hand adoptions may be missed by the preview. Threader rechecks at execution, so no duplicate is posted.
- Name matching misses people whose Slack name differs, who share a name, or whose chip shows an email. They post as plain text and are reported `not tagged` until `users:read.email` is granted.
- The repo `slack-app-manifest.yaml` says `org_deploy_enabled: false`, but the live app is org-deployed. Sync the manifest when adding `users:read.email`.