# RED Team Prop Threader — user guide

How to create and manage prop-request threads in Slack from a ShotGrid asset page.

**Audience:** channel members who run `/create-prop-threads` or edit posted threads  
**Related:** [Slack app setup](admin/slack-app-setup.md) (admins), [pilot test checklist](admin/pilot-test.md) (QA)

**Confluence:** open [user-guide-confluence.html](user-guide-confluence.html) in a browser, select the page body, copy, and paste into a Confluence page editor.

---

## What this app does

Prop Threader turns an API-exportable ShotGrid asset page into:

1. One **group summary** message in the channel
2. One **asset thread root** per included asset (people can reply in the thread)
3. An entry on the channel canvas **INDEX OF PROP REQUESTS** so threads stay findable

Nothing is posted until you confirm. You review people, links, and included assets in a private modal first.

---

## Before you start

- You are in the **target Slack channel** (the bot must already be a member).
- You are using the **EA workspace**, not only a connected external workspace.
- You have an **API-exportable ShotGrid Asset page** (grid/list of assets), not a ShotGrid Canvas page.
- The channel canvas is titled **INDEX OF PROP REQUESTS**, or you are ready to let the bot create or rename it when asked.

Example page shape (IDs vary by project):

```text
https://respawn.shotgunstudio.com/page/<page-id>
```

---

## Terms (modals and messages use the same names)

| Term | Where you set it | What it means |
| --- | --- | --- |
| **Group title** | Create modal | Heading for this batch (for example a season or package name) |
| **Creative Stakeholder** | Group fields / group summary | Primary group-level contact (notifies in the group summary) |
| **Additional stakeholders** | Group fields | Extra group-level contacts |
| **Group links** | Group fields / group summary | Links that apply to the whole batch |
| **Requestor** | Per-asset fields / asset thread | Primary person for that asset (notifies on the asset root) |
| **Additional requestors** | Per-asset fields | Extra people for that asset |
| **Links** | Per-asset fields / asset thread | Links that apply to that asset only |
| **Group POCs** | Shown on asset threads | Plain-text names of the group Creative Stakeholder and additional stakeholders (no @-notify) |
| **Latest** | Asset roots and canvas | The current active thread for an asset when the same asset is posted again later |

Link format in modals (one per line):

```text
Label: https://example.com/path
```

Example: `Miro: https://miro.com/app/board/...`

People pickers only list **people already in the channel**, shown as `Real Name (@username)`.

---

## Create prop threads

### 1. Run the command

In the target channel:

```text
/create-prop-threads
```

Or with a page URL so you can skip pasting it later:

```text
/create-prop-threads https://respawn.shotgunstudio.com/page/<page-id>
```

### 2. Canvas check

If the channel canvas is missing or mistitled, the bot asks you to create or rename it to **INDEX OF PROP REQUESTS**. Confirm to continue, or decline to stop with no threads posted.

### 3. Import assets

If you did not pass a URL, paste the ShotGrid page URL and continue. The bot exports the page, keeps the first row per Entity ID, and opens the asset editor (up to 15 assets per page, up to 30 total).

### 4. Fill group and asset fields

**Group (once per batch)**

- Group title
- Creative Stakeholder (optional)
- Additional stakeholders (optional)
- Group links (optional)

**Each asset**

- Include or exclude the asset (at least one must stay included)
- Requestor (optional)
- Additional requestors (optional)
- Links (optional; asset-only)

Use **Next** / **Back** on multi-page imports. Your edits are kept as you page.

### 5. Confirm

Review the confirmation screen (channel, title, included count, warnings). Confirm only when you are ready to post.

After confirm:

- A private progress DM updates while work runs
- The group summary and asset roots appear in the channel
- The canvas index updates under the group title
- Mid-batch work cannot be cancelled; failures are reported privately when something goes wrong

---

## What gets posted

### Group summary

- Group title
- Creative Stakeholder and Additional (Slack mentions when set)
- Group Links (when set)
- Included asset count
- Completed / failed counts when the batch finishes
- Canvas link when available
- **Edit Group Details** (on the latest summary only)

### Asset thread root

Four tight header lines:

1. Asset (ShotGrid link and ID; `(latest thread)` when a prior thread exists)
2. Group
3. Requestor (and Additional when set)
4. Group POCs

Then, only if you entered asset-level links: **Links**.

Group links are **not** repeated on each asset thread.

Button: **Edit POCs** (latest root only).

### Channel canvas

Under **INDEX OF PROP REQUESTS**, each confirmed batch has a group heading with Creative Stakeholder, Group Links, and per-asset thread links. New groups are added at the top, separated from older groups.

Each group is an **H2** heading (collapse it to hide all assets in that batch). Each asset is an **H3** heading (collapse it to hide ShotGrid and Slack thread links underneath).

---

## Primary asset index

Satellite channels keep their local **INDEX OF PROP REQUESTS** canvas as today. The app also mirrors each batch to a **PRIMARY ASSET INDEX** canvas in a dedicated primary channel configured by admins (`PRIMARY_ASSET_INDEX_CHANNEL_ID`, default `C04H4QZEYUE`).

Primary updates are best-effort: if the primary write fails, your channel threads and local index still succeed. Primary sections use the same H2/H3 collapse layout and add **Source channel** plus a channel name in the group heading so batches from different channels stay distinct.

The bot must be a member of the primary channel. Ask an admin to invite it if local indexes update but the primary canvas does not.

---

## Edit after posting

Any channel member (from the EA workspace) can edit **Latest** messages only.

| Button | Opens | Typical changes |
| --- | --- | --- |
| **Edit Group Details** | Group edit modal | Creative Stakeholder, additional stakeholders, group links |
| **Edit POCs** | Asset edit modal | Requestor, additional requestors, asset links |

Edits update the latest messages and the canvas group section **without** sending new @ notifications.

If you click edit on an older (non-Latest) root or summary, the bot refuses and points you to the current Latest message.

---

## Re-running the same assets

Confirming a later batch with the same Entity IDs:

- Posts **new** asset roots
- Marks the new roots as Latest
- Updates prior bot-authored roots so they are no longer Latest
- Updates the canvas so each asset keeps one Latest thread link (prior links may still appear under the asset when known)

Use a clear **group title** so each batch is easy to spot on the canvas.

---

## Tips and common issues

**Wrong ShotGrid page type**  
Canvas-type ShotGrid pages cannot be exported. Use an Asset grid/list page.

**Empty or wrong people list**  
Only channel members appear. Invite the person to the channel first, then reopen the modal.

**Canvas did not update**  
Confirm the canvas title is exactly **INDEX OF PROP REQUESTS** (the bot can create or rename it during preflight). Ask an admin if the app is missing canvas scopes or was not reinstalled after a scope change.

**Nothing posted**  
You may have closed or declined before confirmation. Run the command again; drafts can be resumed within the retention window when offered.

**Mentions did not notify on edit**  
That is intentional. Create-time mentions notify; later edits update quietly.

**Busy channel**  
Only one create flow can hold the channel at a time. Wait for the other run to finish, or try again after the short lease expires.

---

## Quick reference

```text
/create-prop-threads [ShotGrid page URL]
```

1. Canvas ready → import → fill group + assets → confirm  
2. Read group summary + asset roots + canvas index  
3. Use **Edit Group Details** / **Edit POCs** on Latest messages only  

For install, scopes, and secrets, see [admin/slack-app-setup.md](admin/slack-app-setup.md).
