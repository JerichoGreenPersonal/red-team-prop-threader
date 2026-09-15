# Thread Message (manual Slack reply)

**Date:** 2026-09-11 (grilled through 2026-09-14)
**Status:** Approved (grilled through 2026-09-14)
**Parent:** `docs/superpowers/specs/2026-09-03-slack-spoke-open-thread-design.md` (permalink / spoke cache)
**Replaces (ReviewPrep send UX):** card **Post CL** in `docs/superpowers/specs/2026-09-09-slack-cl-auto-message-design.md`. Morning queue in that spec stays parked.
**Related:** Threader EAV drain of `kind: thread_message` jobs (same drop; **no mint**). Parked backfill mill: `docs/superpowers/specs/2026-09-10-request-form-z-slack-routing-design.md` and handoff `docs/handoffs/260911-212834-threader-z-batch-threads.md`.
**Target Release:** ReviewPrep **2.4.3** on the Slack train (PR #17 / `feature/os-rundown-slack-spoke-glyph`). Do **not** merge `feature/request-form-z-slack-routing`. Threader on **EAV1089717** updates in the same drop. Laptop Threader stays off.

## Problem

Post CL required a Daily Review Version with a parsed P4 CL and a submission image, plus Request Form mint when no spoke existed. Artists with a real Slack hash still could not send. Nested Slack submenu clicks dropped on Windows (`QMenu.exec` returned None).

Send should be manual: if the card has an official thread, the user writes a message, attaches images, confirms, and Prop Threader posts the reply.

## Goals

1. Slack submenu on Daily Review and OS Rundown: **Open thread** and **Thread Message**.
2. Thread Message enabled whenever that card has a Slack permalink. No CL, image, or Request Form checks. No inbox lock.
3. Composer: typed body, multi-file attach, clipboard paste, optional **Attach {Task}**.
4. Confirm titled **Schedule Prop Threader Message** with body preview and 256px thumbnails. Nothing queued until Confirm.
5. Confirm writes `{external_links_root}/slack_jobs/inbox/` JSON plus image copies. ReviewPrep never holds a Slack token and never creates threads.
6. Threader replies **in the existing thread** as Prop Threader (text + 0..n files). Fail leftover Post CL JSON. Do not mint.

## Non-goals

- Creating threads in ReviewPrep (Create thread, mint-if-missing, Z parse, `ic_poc` on the send job).
- Threader Z batch backfill (separate Threader design).
- Canned templates, CL checkboxes, `{cl}` tokens, morning queue.
- Channel-root posts when there is no permalink.
- ReviewPrep Slack token, HTTP to EAV, new Slack app.
- Windows toasts.
- Merging `feature/request-form-z-slack-routing`.
- Canceling an in-flight inbox job from the UI.

## Locked decisions

| Topic | Choice |
| --- | --- |
| Poster | RED Team Prop Threader on EAV1089717 |
| Menu | Slack -> **Thread Message** (replaces **Post CL**) |
| Enable | Permalink present. Asset-backed card on both tabs. |
| Disable | No permalink. Tooltip `No official Slack thread`. Inbox jobs do **not** disable the menu. |
| Missing R: | Menu still follows permalink. Confirm write failure names the error. |
| Composer | Empty text box; **Add files...** multi-select; Ctrl+V; each item removable |
| Paste | Clipboard **image** attaches (even if the text box is focused). Clipboard **text** pastes into the message. Image wins if both are present. |
| Attach {Task} | One button. Newest Version that has an `image` (`created_at`, tie: higher Version id). Label is that Version's Task (`Attach Hi Poly`). Blank Task: `Attach latest image`. |
| Disk vs SG | Prefer the **local staged still** (full res to Slack). If never prepped, attach the ShotGrid Version **thumbnail** so confirm is not empty. Hide the button only if neither exists. Duplicate click is a no-op. |
| Slack file quality | 256px is **confirm preview only**. Job copies the real attached files. Prepped stills go full res; un-prepped fallback may be the SG thumbnail. |
| Image types | png, jpg, jpeg, gif, webp. Picker filters to those; other files skipped. |
| Send (composer) | Enabled if body has text, or at least one image, or both. |
| Confirm | Title **Schedule Prop Threader Message**. Body plus each image in a **256px** box (long edge <= 256, keep aspect, scroll if several). Text-only: body only. **Back** returns to composer. **Confirm** writes the job. |
| Queue | Jobs stack. Status `Thread Message queued (N)` while any this session (or inbox) is in-flight. Opening Thread Message lists **this Asset's** pending jobs (short body preview + waiting). Wait-only; no Cancel. |
| Copy | Never `CL posted` or `CL post queued`. Success: `Posted to Slack thread`. |
| Destination | Reply on cached spoke (`spoke_channel_id`, `spoke_thread_ts`) |
| Job folder | `{external_links_root}/slack_jobs/inbox/` |
| Job JSON | `kind: thread_message`, `job_id`, `asset_id`, `body`, `images` (filenames), `spoke_channel_id`, `spoke_thread_ts`. No `cls`, mint fields, or `template_id`. |
| Image copies | `{job_id}_0{suffix}`, `{job_id}_1{suffix}`, ... |
| Empty images | Allowed when body has text |
| Threader (this drop) | Drain `thread_message` only. Reply + upload files in order. Stamp `sent.json` / `failed.json`; move to `done/`. Fail if spoke ids missing. **Do not mint.** Old Post CL JSON: `failed.json` with `Unsupported job; send Thread Message`. |
| sent.json | On success, append this `job_id` under that asset id (no CL numbers) |
| Nested menu | Record `QMenu.triggered` (`action_from_menu_exec`) |
| Version | ReviewPrep **2.4.3** on the glyph / PR #17 train |

## Architecture

```
Card Slack -> Thread Message
        │  permalink required (no mint)
        ▼
  composer (body, files, paste, Attach {Task}, pending list)
        │  Send
        ▼
  confirm (body + 256px thumbs)
        │  Confirm
        ▼
  inbox/{job_id}.json + {job_id}_N.ext
        │  Threader EAV (same drop, reply only)
        ▼
  Slack thread reply (Prop Threader) + files
        │
        ▼
  sent.json / failed.json / done/
```

## Menu and flags

Enable Thread Message when `has_asset` and permalink. Drop payload, mint, and inbox-queued gates.

Keep Open thread as today. Slack parent stays enabled whenever the card has an Asset.

Wire Daily Review and OS Rundown through `action_from_menu_exec`.

## Composer and confirm

- Window title **Thread Message**.
- Pending list at the top for this Asset's inbox jobs; drops off as Threader finishes.
- Attach list is in-memory paths (disk, pasted temps, Attach {Task} local or SG thumbnail).
- Add files / paste: skip unreadable or non-image files. Clipboard with neither image nor text is a no-op.
- Composer Send opens confirm; it does not write.
- Confirm write failure: stay on confirm; no partial inbox JSON.

## Threader (same drop, sibling repo)

New consume path for `kind: thread_message` only. Bounce EAV worker. Laptop off. Mint / Z backfill is a later Threader design.

## Error handling

| Case | Behavior |
| --- | --- |
| No permalink | Thread Message disabled; `No official Slack thread` |
| Empty composer | Send disabled |
| Confirm write fail | Stay on confirm; no inbox JSON |
| Old Post CL JSON | Threader fails that job; does not post |
| Threader fail | `failed.json`; status shows error; can send again |
| Threader success | `Posted to Slack thread` |

## Testing

- Flags: permalink on => enabled; no permalink => disabled; inbox jobs do not disable.
- `action_from_menu_exec`: submenu action survives parent `exec` None.
- `write_job`: `kind: thread_message`; 0 images with body; N images; no write until Confirm; no `cls`.
- Queue: two jobs for one Asset both sit in inbox; composer lists both; no Cancel control.
- Attach {Task}: prefers staged local file; SG thumbnail if none; hide if neither.
- Confirm: 256px thumbs; Back does not write.
- Copy: no `CL posted`.
- Threader: reply + 0..n files; fail without spoke ids; fail old Post CL JSON; `sent.json` stores `job_id`.

## Out of this ReviewPrep version

Z / Create thread / mint. Morning queue. Canned CL templates. ReviewPrep 2.4.3 Z branch.
