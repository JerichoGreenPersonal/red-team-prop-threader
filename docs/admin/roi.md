# ROI Assessment -- RED Team Prop Threader

## Reason for creating this app

Prop-request setup was a manual Slack workflow: copy assets from ShotGrid, open one thread per asset, ping the right people, and keep a channel index up to date. That work is repetitive, easy to get inconsistent, and does not scale when a season batch has many assets. RED Team Prop Threader exists to turn an API-exportable ShotGrid page into confirmed, standardized Slack threads and a maintained canvas index in one guided pass -- with human approval before anything posts publicly.

## Quick ROI assessment

| Area | Without the app | With the app | Return |
| --- | --- | --- | --- |
| Setup time | Manual copy/paste of names, links, mentions, and index updates per asset | One `/create-prop-threads` run for up to 30 assets | High -- replaces per-asset clerical work with a single confirmed batch |
| Consistency | Thread format and index quality vary by author | Fixed message templates and canvas indexing | High -- fewer missed fields, fewer broken or missing index entries |
| Notification quality | Easy to over-ping or under-ping | Group contacts once; asset contacts on their own roots | Medium-high -- less channel noise, clearer ownership |
| Rework / risk | Typos, skipped assets, stale indexes, hard-to-find threads | Validation, dedupe, confirmation, durable retries, latest-only edits | Medium-high -- fewer redo cycles and safer corrections |
| Discovery | Stakeholders dig through channel history | Canvas `INDEX OF PROP REQUESTS` plus one root per asset | High for readers -- passive tracking without raw ShotGrid export work |
| Oversight | Ad-hoc posts | Draft + explicit confirm; no autonomous publish | Governance fit for EA IT / team standards |

**Cost side (kept intentionally small):** read-only ShotGrid script access, a narrowly scoped Slack bot, internal hosting, and IT review of an importable manifest. No ShotGrid writes, no broad channel-management scopes, and no autonomous posting.

**Bottom line:** The app pays for itself by cutting season/batch setup labor and reducing coordination defects (missed assets, noisy mentions, stale indexes). Value compounds every time a new prop-request set is opened; the first pilot in `C0B4GJSA1G8` is the right place to capture before/after timing if a quantified ROI number is needed for stakeholders.
