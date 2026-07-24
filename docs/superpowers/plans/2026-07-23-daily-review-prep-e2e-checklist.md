# Daily Review Prep Assistant — MVP End-to-End Verification Checklist

> **Purpose:** Manual smoke verification of the installed MVP on a Windows workstation with live (or staging) ShotGrid, P4, 7-Zip, and Cadet access.  
> **Spec:** `docs/superpowers/specs/2026-07-09-daily-review-prep-assistant-design.md`  
> **Plan:** `docs/superpowers/plans/2026-07-23-daily-review-prep-assistant.md`

Use checkbox syntax (`- [ ]`) while walking through each section. Record pass/fail notes inline.

---

## Prerequisites

- [ ] Windows 10/11 workstation; reviewing user account (not `SYSTEM`).
- [ ] Built and installed per README:
  - `.\packaging\build.ps1`
  - `.\packaging\install.ps1` (or `-SkipSchedule` if testing manually first)
- [ ] Binaries at `%LOCALAPPDATA%\ReviewPrep\app\`:
  - `review-prep-worker.exe` (console)
  - `review-prep.exe` (dashboard)
- [ ] Everyday P4 client configured; `p4` on PATH or set in settings.
- [ ] 7-Zip (`7z.exe`) available; path matches setup wizard default or studio install.
- [ ] ShotGrid script name + API key with read/download access.
- [ ] **`layout_3` bookmark (Task 9):** Confirm `configs/default_shotgrid_query.json` has `page_id: 12787` and `layout_name: "layout_3"` (the bookmarked worklist). The app loads that layout via ShotGrid `export_page` — you do not hand-copy filter arrays.
- [ ] Test cards identified (or create staging cards):
  - **A — Archive:** Asset with `.rar` or `.zip` attachment (no CL required).
  - **B — CL-only:** Asset with labeled CL comments only (no archive attachment).
  - **C — Unsafe P4:** CL whose submitted files include at least one locally writable/conflicting file (dry-run `-n` marks open unsafe).
  - **D — WIP open:** CL labeled `WIP` with a recognized DCC file (`.ma`/`.mb`) for Cadet launch.
- [ ] Optional: backup/remove `%LOCALAPPDATA%\ReviewPrep\settings.json` and `prep.db` for a clean first-run test.

**Key paths**

| Item | Location |
|------|----------|
| Settings | `%LOCALAPPDATA%\ReviewPrep\settings.json` |
| SQLite manifest | `%LOCALAPPDATA%\ReviewPrep\prep.db` |
| Staging root | User-chosen at setup (local or UNC) |
| Day folders | `{MON\|TUE\|…}_{MM}_{DD}_{YYYY}` under staging root |
| ShotGrid query | Path in settings (default `configs/default_shotgrid_query.json`) |
| Credential Manager | Service `review-prep`, key = ShotGrid script API key |

---

## 1. Setup wizard — script key, staging, P4, Cadet, 7z

**Goal:** First launch collects all required settings; credentials land in Credential Manager, not plain text on disk.

- [ ] Delete or rename `%LOCALAPPDATA%\ReviewPrep\settings.json` (and optionally `prep.db`) to force first-run.
- [ ] Launch `%LOCALAPPDATA%\ReviewPrep\app\review-prep.exe` (or `uv run review-prep` from dev tree).
- [ ] **Setup wizard appears** with fields:
  - ShotGrid script name
  - ShotGrid API key (password field)
  - Staging root (local or UNC path with write access)
  - P4 client (everyday workspace name)
  - 7z path (default `7z` or full path to `7z.exe`)
  - Cadet Maya template (default `{cadet_cmd} --toolset apex_r5dev --app Maya --file "{file}"`)
  - ShotGrid query path
- [ ] Enter valid values for all fields; paste API key.
- [ ] Click **Save**; wizard closes; main dashboard opens.
- [ ] Verify `%LOCALAPPDATA%\ReviewPrep\settings.json` exists with staging root, P4 client, 7z path, query path, Cadet templates — **no API key in the file**.
- [ ] Verify API key stored in Windows Credential Manager (service `review-prep`).
- [ ] Re-launch dashboard: wizard **does not** reappear.

**Pass criteria:** Settings persisted; key in Credential Manager only; dashboard usable.

---

## 2. Test query — returns `layout_3` cards

**Goal:** Setup validates ShotGrid connectivity and the shipped query returns the same worklist as page 12787 `layout_3`.

- [ ] Confirm query JSON uses `page_id: 12787` + `layout_name: "layout_3"` (bookmarked worklist).
- [ ] Open **Settings** from dashboard (or re-run wizard via Settings button).
- [ ] Click **Run test query**.
- [ ] Status shows success, e.g. `OK — N card(s): CODE(id), …` with **N > 0** on a day with review cards in `layout_3`.
- [ ] Cross-check: card codes/IDs match cards visible on [layout_3 page](https://respawn.shotgunstudio.com/page/12787?layout=layout_3) (order may differ; set should match).
- [ ] Optional dev check: `uv run python scripts/smoke_shotgun_worklist.py` with credentials configured.

**Pass criteria:** Test query succeeds; returned cards correspond to the bookmarked `layout_3` worklist.

**Fail hints:** Auth errors → script name/key. `export_page` / layout errors → confirm layout name is exactly `layout_3` on page 12787. `0 cards` on a busy review day → page empty or wrong page id.

---

## 3. Worker prep — RAR/zip attachment card

**Goal:** Scheduled/manual worker downloads archive attachments, extracts via 7-Zip, detects DCC files, updates route state.

- [ ] Ensure card **A** (archive attachment only) is in today's `layout_3` worklist.
- [ ] Run worker:
  ```powershell
  & "$env:LOCALAPPDATA\ReviewPrep\app\review-prep-worker.exe"
  ```
  (or Task Scheduler job `ReviewPrep\DailyPrep`)
- [ ] Console log shows prep run with card count; no hard failure (exit code `0`).
- [ ] Under staging root, folder exists: `{DAY}_{MM}_{DD}_{YYYY}/{asset_code}_{shotgrid_id}/`.
- [ ] Archive extracted; recognized DCC files present (not raw `.rar`/`.zip` only).
- [ ] In `prep.db` / dashboard Refresh: card **A** route state progresses to `ready_to_launch` or `synced_only` / `launched` as appropriate; attachment route kind = `attachment_archive`.

**Pass criteria:** Archive downloaded, safely extracted, staged, manifest updated.

---

## 4. Worker prep — CL-only card (Source Art sync-only, WIP sync-and-open)

**Goal:** P4 changelists parsed from delivery comments; default policies applied without archive route.

- [ ] Ensure card **B** has CL comments only (e.g. `Source Art CL 12345`, `WIP CL 67890`) and no archive attachment.
- [ ] Run worker (same as §3).
- [ ] **Source Art / Preflight / Unknown CLs:** files synced in everyday P4 client; route state `synced_only`; **not** marked `ready_to_launch` for open.
- [ ] **WIP CL:** files synced; recognized DCC files marked `ready_to_launch` (open deferred to interactive session).
- [ ] Dashboard/summary lists CL numbers and policies correctly.

**Pass criteria:** CL-only card prepped; Source Art = sync only; WIP = sync + eligible for launch.

---

## 5. Unsafe open file skipped

**Goal:** Everyday P4 client never force/clobber/revert; writable local conflicts skipped; siblings continue.

- [ ] Ensure card **C** has a CL whose submitted files include at least one **unsafe** file (local file writable / would require clobber — verify with `p4 sync -n` manually if needed).
- [ ] Run worker.
- [ ] Unsafe file **not** synced/opened; skip reason recorded in prep run errors or route detail.
- [ ] Other safe files in the same CL still sync.
- [ ] Summary / dashboard shows skip (partial or skipped route), not silent success.

**Pass criteria:** Unsafe file skipped; no `-f`/clobber flags used; remaining files processed.

---

## 6. Login summary — auto-open + acknowledge

**Goal:** After prep, first interactive dashboard session auto-opens summary for unacked run; closing acks it.

- [ ] Complete at least one successful worker prep run (§3–§5) while dashboard is **closed**.
- [ ] Confirm unacked run exists (worker logged `prep run id=…`).
- [ ] Launch `review-prep.exe` (or logon trigger `ReviewPrep\OpenDashboard`).
- [ ] **Summary dialog auto-opens** before or atop main window, listing cards/routes for that prep run's `local_date`.
- [ ] Close summary dialog.
- [ ] Re-launch dashboard: summary **does not** auto-open again for the same run.
- [ ] Optional: query `prep.db` — run marked acked.

**Pass criteria:** Unacked summary shown once per prep run; close = acknowledge; no toast/email/Slack.

---

## 7. Cadet missing — log prompt; Open Again after Cadet up

**Goal:** MVP does not auto-start Cadet; files stay ready; user prompted to enter `apex_r5dev` and retry.

- [ ] Ensure card **D** (WIP) reached `ready_to_launch` with a `.ma`/`.mb` file.
- [ ] **Quit Cadet** (no `Cadet.SystemTray` / `Cadet.Service` running).
- [ ] Launch dashboard (interactive). If auto-launch runs, or select card and **Open Again**:
- [ ] Log / UI message includes: `Cadet is not running; enter apex_r5dev then use Open Again`
- [ ] Files remain `ready_to_launch`; daily launch lease **not** consumed while Cadet blocked.
- [ ] Start Cadet with toolset `apex_r5dev`.
- [ ] Select prepared card(s) → **Open Again**.
- [ ] Cadet receives launch command; file opens; route moves to `launched` (or lease recorded).

**Pass criteria:** Blocked gracefully when Cadet down; successful launch via Open Again after Cadet up.

---

## 8. Manual Prepare + Open Again

**Goal:** Dashboard **Prepare** runs the same idempotent pipeline as the worker; **Open Again** bypasses daily leases.

- [ ] Select one or more unprepared or partially prepared cards in the dashboard table.
- [ ] Click **Prepare**; wait for completion message.
- [ ] Route states update identically to worker behavior (download/extract/sync).
- [ ] Re-click **Prepare** on already-ready cards → no-op / no duplicate work (idempotent).
- [ ] Select prepared card(s) with launchable DCC files.
- [ ] Click **Open Again** (Cadet running).
- [ ] Files launch even if daily lease already held from earlier auto-launch.
- [ ] Second **Open Again** same session still works (lease bypass).

**Pass criteria:** Prepare = worker pipeline; Open Again re-launches on demand.

---

## 9. Retention N days — dry-run then apply

**Goal:** Staging folders older than N days removed after worker run; today's folder never deleted; `None` = keep forever.

Use a **disposable test staging root** (not production art). Retention has no CLI dry-run flag — preview candidates manually, then apply.

### 9a. Preview (dry-run)

- [ ] Create test root, e.g. `C:\ReviewPrepRetentionTest`.
- [ ] Create day folders (match `{MON}_{MM}_{DD}_{YYYY}` pattern):
  - `MON_07_01_2026` (old)
  - `MON_07_10_2026` (borderline)
  - `{TODAY}` folder matching today's date (e.g. `FRI_07_24_2026`)
  - `not_a_day_folder` (should be ignored)
- [ ] Set `"retention_days": 7` in `%LOCALAPPDATA%\ReviewPrep\settings.json` and point `"staging_root"` at the test root temporarily.
- [ ] Preview deletions (no side effects) using the same parser as production:
  ```powershell
  uv run python -c "
  from datetime import date, timedelta
  from pathlib import Path
  from review_prep.retention import _parse_day_folder
  root = Path(r'C:\ReviewPrepRetentionTest')
  today = date.today()
  cutoff = today - timedelta(days=7)
  for e in sorted(root.iterdir()):
      if not e.is_dir():
          continue
      d = _parse_day_folder(e.name)
      if d is None:
          print(e.name, '-> KEEP (non-day folder)')
      elif d == today:
          print(e.name, '-> KEEP (today)')
      elif d > cutoff:
          print(e.name, '-> KEEP (within window)')
      else:
          print(e.name, '-> WOULD DELETE')
  "
  ```
  Cross-check expectations against `tests/test_retention.py`.
- [ ] Note expected deletes: old folders only; today + `not_a_day_folder` kept.

### 9b. Apply

- [ ] Run worker once against test staging root.
- [ ] Console may log `retention deleted N day folder(s)`.
- [ ] Verify old day folders removed; today's folder and non-day folders remain.
- [ ] Restore production `"staging_root"` and `"retention_days": null` (forever) when done.

**Pass criteria:** Retention honors N-day window; today never deleted; `null` retention skips cleanup entirely.

---

## 10. Sign-off

| Area | § | Pass? | Tester | Date | Notes |
|------|---|-------|--------|------|-------|
| Setup wizard | 1 | | | | |
| Test query / layout_3 | 2 | | | | |
| RAR/zip prep | 3 | | | | |
| CL-only policies | 4 | | | | |
| Unsafe P4 skip | 5 | | | | |
| Summary ack | 6 | | | | |
| Cadet missing / Open Again | 7 | | | | |
| Manual Prepare / Open Again | 8 | | | | |
| Retention N days | 9 | | | | |

**Explicit non-goals (do not test for MVP):** Slack notifications, Windows toast, Re-run action, ShotGrid write-back.

**Automated regression (dev):** `uv run pytest` — especially `tests/test_retention.py`, `tests/test_p4_adapter.py`, `tests/test_launch_coordinator.py`, `tests/test_ui_summary_ack.py`, `tests/test_scheduler_windows.py`.
