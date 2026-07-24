# Primary Asset Index — Design

Date: 2026-07-24  
Status: approved

## Problem

Prop-request threads are created in satellite Slack channels. Each channel already maintains a local **INDEX OF PROP REQUESTS** canvas. There is no cross-channel ledger, so operators cannot see all current groups/assets in one place.

## Goals

- Maintain a **PRIMARY ASSET INDEX** canvas in a dedicated channel that mirrors satellite index updates.
- Keep per-channel indexes working as today (dual-write).
- Improve canvas scannability with collapsible H2/H3 structure and clear `:Slack:` / `:shotgrid:` link markers.
- Keep existing `:threadparrot:` decoration on in-channel asset root threads.

## Non-goals

- Replacing satellite canvases with primary-only indexing.
- Hard-failing satellite work when the primary index write fails.
- Rebuilding the primary canvas from DB on a timer (no projector job in this iteration).
- In-app UI to change the primary channel (env/config only).

## Decisions (locked)

| Topic | Decision |
| --- | --- |
| Dual-write | Satellite local index **and** primary index |
| Primary channel | `C04H4QZEYUE` |
| Config | `PRIMARY_ASSET_INDEX_CHANNEL_ID` (default `C04H4QZEYUE`) |
| Naming | Use **PRIMARY_ASSET_INDEX** / `INDEX_PRIMARY_ASSET` — never `MASTER_*` |
| Primary canvas title | `PRIMARY ASSET INDEX` |
| Satellite canvas title | unchanged: `INDEX OF PROP REQUESTS` |
| Layout | Same group/asset shape on both canvases; primary adds **Source channel** |
| Sort | New groups inserted at top; later updates replace in place (creation order) |
| Primary failure | Best-effort; log and continue; manual paste is acceptable |
| Same-channel | If slash command runs in the primary channel, write local canvas once only (skip duplicate primary op) |
| Emojis | `:shotgrid:` on ShotGrid links; `:Slack:` on Slack thread permalinks; keep `:threadparrot:` on asset roots |

## Approach

**Extra durable worker op after each local index write** (Approach 1).

After required `INDEX_ASSET` (satellite canvas), enqueue `INDEX_PRIMARY_ASSET` as best-effort. Lazy ensure/rename of the primary channel canvas on first primary write (not in the slash-command modal).

Rejected alternatives:

- Dual-write inside `CanvasService.index_batch` — harder retries/partial failure.
- Async DB projector — overkill for pilot.

## Architecture

```text
/create-prop-threads (satellite)
  → post threads + INDEX_ASSET (INDEX OF PROP REQUESTS)     [required]
  → INDEX_PRIMARY_ASSET (PRIMARY ASSET INDEX in C04H4QZEYUE) [best-effort]

Edits / re-runs
  → update satellite index
  → INDEX_PRIMARY_ASSET in-place replace (no bump to top)
```

### Components

| Unit | Responsibility |
| --- | --- |
| `Settings` / `.env` | `PRIMARY_ASSET_INDEX_CHANNEL_ID` |
| `CanvasService` (+ shared render) | Shared markdown for both canvases; primary-specific source-channel line; ensure primary canvas titled `PRIMARY ASSET INDEX` |
| `BatchPlanner` / `EditService` | Plan `INDEX_PRIMARY_ASSET` after satellite index when channel ≠ primary |
| `BatchExecutor` | Execute primary index; on failure mark failed/skipped without failing the batch |
| `messages.render_asset_root` | Keep `:threadparrot:`; add `:shotgrid:` on ShotGrid asset link |

### Canvas markdown

**Satellite (`INDEX OF PROP REQUESTS`):**

```markdown
## {Group title}

**Creative Stakeholder:** …

**Group Links:**
- …

### {Asset name}
- :shotgrid: [ShotGrid](https://…)
- :Slack: [YYYY-MM-DD HH:MM PDT](thread-permalink) — Latest
- :Slack: [prior stamp](prior-permalink)
```

**Primary (`PRIMARY ASSET INDEX`):**

```markdown
## {Group title} ({channel display})

**Source channel:** #satellite-channel

**Creative Stakeholder:** …

**Group Links:**
- …

### {Asset name}
- :shotgrid: [ShotGrid](https://…)
- :Slack: [YYYY-MM-DD HH:MM PDT](thread-permalink) — Latest
- :Slack: [prior stamp](prior-permalink)
```

- **H2** = group of assets (collapse hides all assets).
- **H3** = asset name as plain text (collapse hides SG + Slack links under it).
- ShotGrid URL is **not** embedded in the H3 heading text.

### Primary insert vs replace

1. Lookup existing group section on primary canvas by normalized group heading.
2. **Missing** → `insert_at_start` (newest groups at top).
3. **Present** → `replace` in place (no reorder on update).

### Identity of a “group” on the primary canvas

Satellite canvases keep H2 as `{normalized group title}` only.

On the primary canvas, H2 is `## {normalized group title} ({channel display})` so two satellites with the same group title never merge into one section. Section lookup uses that full H2 string. The body still includes `**Source channel:**` with a channel mention/link for humans.

## Error handling

| Case | Behavior |
| --- | --- |
| Bot not in primary channel | Primary op fails; log; satellite success unchanged |
| Primary canvas missing / wrong title | Lazy create/rename; if that fails, same as above |
| Slack API error on primary edit | Log; do not fail batch |
| Primary == satellite channel | Skip `INDEX_PRIMARY_ASSET` |

No user-blocking modal for primary canvas preflight in v1.

## Testing

- Unit: `render_group_markdown` H2/H3 + emoji lines; primary variant includes source channel and disambiguated H2.
- Unit: planner emits `INDEX_PRIMARY_ASSET` after satellite index; skips when channels equal.
- Unit: executor primary failure does not fail overall batch success path.
- Unit: asset root still includes `:threadparrot:` and gains `:shotgrid:` on the SG link.
- Optional integration: mocked Slack gateway dual edit calls.

## Rollout (EAV)

1. Ensure bot is a member of `C04H4QZEYUE`.
2. Set `PRIMARY_ASSET_INDEX_CHANNEL_ID=C04H4QZEYUE` in `.env` (or rely on default).
3. Deploy/restart web+worker on EAV.
4. Create a prop batch in a satellite channel; confirm local + primary canvas updates.
5. Re-run/edit; confirm primary section updates in place (no bump).

## Open implementation notes (for the plan, not blockers)

- Exact Slack custom emoji names must exist in the EA workspace (`:Slack:`, `:shotgrid:`). If either is missing, Slack will show raw shortcodes — confirm on first pilot write.
- Whether `Group Links` on canvases also get `:Slack:` / `:shotgrid:` by URL host heuristic.
- Persistence of primary `canvas_id` (discover each time vs cache in settings/DB).
