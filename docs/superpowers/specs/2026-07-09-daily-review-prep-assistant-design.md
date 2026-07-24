# Daily Review Prep Assistant — Design

**Date:** 2026-07-09  
**Updated:** 2026-07-23 (grilling decisions folded in)  
**Status:** Design approved for MVP; ready for implementation plan

## 0. MVP Decisions (grilled 2026-07-23)

These decisions amend or specialize the sections below for version one.

| Topic | Decision |
|-------|----------|
| Stack | Shared Python codebase (worker + dashboard), shipped as a self-contained Windows installer (no user-installed Python/Node) |
| Install | Prefer per-user install that does not require elevation for daily use; prep always runs as the reviewing Windows user (never `SYSTEM`) |
| ShotGrid auth | Reuse the existing shared script/API key (same class of key used for Slack apps); store in Windows Credential Manager; key has read/download |
| Worklist | Trust ShotGrid page [12787 `layout_3`](https://respawn.shotgunstudio.com/page/12787?layout=layout_3) as today's prep set — no extra Windows-local date gate for selection |
| Reference cards | Queue: page 12787; sample: [#Asset_38811](https://respawn.shotgunstudio.com/page/12787#Asset_38811); entity type expected to be Asset (confirm when extracting the API query) |
| Slack | Out of scope for MVP (possible later worklist source) |
| Archives | Primary archive type is `.rar`; also support `.zip`; extract via **7-Zip** CLI (`7z.exe`, auto-detect common + depot paths) |
| Deliveries | Archives from card **ATTACHMENTS**; P4 CLs from **comments**; a card may run both routes in one prep |
| Primary morning paths | P4 **or** RAR (loose DCC attachments secondary) |
| P4 client | Artist's everyday workspace; never force/clobber; skip unsafe files only; continue siblings; report skips in summary |
| CL defaults | Source Art / Preflight / Unknown → **Sync only**; WIP → **Sync and open** |
| Dependency roots | Settings exist; ship empty (opt-in) |
| Staging root | User chooses at setup (local or UNC; no mapped drive letters); disk-space preflight |
| Staging retention | User sets N days in settings; default keep forever; never auto-delete in-use/today paths |
| Schedule | Default **5:00 AM** local; catch up at next Task Scheduler opportunity same day if missed |
| Launch gateway | Cadet / toolset `apex_r5dev`; configurable Cadet launch command templates |
| Cadet MVP | Assume Cadet is running with correct toolset; if not, log a clear prompt and leave files ready for Open Again (no auto-start/enter) |
| Launch volume | No concurrency cap in MVP (setting retained for later); open all recognized DCC files; include/exclude patterns as escape hatch |
| Summary UX | Dashboard summary only (no Windows toast/email/Slack); auto-open after login/unlock when there is unacked news; closing acknowledges that prep run |
| Setup | First-run: script key → Credential Manager, staging root, P4 client, Cadet launch commands, 7z path; validate with test query + P4/path/extractor checks |
| Manual Prepare | Included; same idempotent pipeline as scheduled run; no Re-run action |

---

## 1. Purpose

Daily Review Prep Assistant is an installed Windows application that front-loads the manual work required for daily 3D art reviews.

Before a user starts work, the application finds that day's submissions in Autodesk ShotGrid / Flow Production Tracking, obtains their deliverables from attachments and/or Perforce, organizes them, and opens eligible DCC files when the user's Windows session becomes interactive. The user should return to a workstation that is ready for review.

The application also provides a dashboard for inspecting the full review queue and reopening already prepared assets later in the day.

Target machines include physical workstations, VMs, and Parsec remote sessions. Install and runtime must stay simple for those environments.

## 2. Success Criteria

A successful daily run:

1. Queries the shipped API equivalent of ShotGrid page 12787 **`layout_3`** (current day / needs review).
2. Prepares every card returned by that worklist (trust `layout_3`; do not re-filter by Windows-local calendar date).
3. For each card, processes applicable delivery routes:
   - downloadable archives from **ATTACHMENTS** (`.rar` / `.zip`);
   - labeled Perforce changelists from **comments**; and
   - loose downloadable review files when present (secondary).
4. Organizes downloaded content under the user's configured staging root.
5. Safely syncs configured Perforce content into the artist's everyday P4 client.
6. Opens eligible files exactly once when the session is interactive for that local day (Cadet gateway).
7. Auto-opens a dashboard summary of completed, skipped, partial, and failed work when there is unacknowledged news.

## 3. Product Shape

The installed application has two cooperating execution modes built from the same Python codebase.

### 3.1 Scheduled Prep Worker

The worker performs non-interactive work:

- ShotGrid queries and attachment downloads;
- delivery-comment parsing (CL labels);
- archive extraction via 7-Zip;
- file detection;
- Perforce previews and syncs;
- prep-manifest updates; and
- bounded retries.

It runs under the user's Windows identity through Windows Task Scheduler (default 5:00 AM local, catch-up on next opportunity). It may run while the session is locked, subject to network, VPN, authentication, power, and workstation policy.

Interactive DCC applications are never launched from a non-interactive Windows task.

### 3.2 Foreground Dashboard and Launcher

The foreground application:

- displays the ShotGrid review queue;
- supports group and individual asset selection;
- shows route-level prep status;
- displays actionable login summaries (auto-open when unacked);
- launches queued files through Cadet;
- provides per-asset and multi-asset **Open Again**;
- supports manual **Prepare** for selected cards; and
- exposes per-user settings.

## 4. ShotGrid Query and Dashboard

### 4.1 Query Contract

Canonical references (login required):

- Worklist layout: https://respawn.shotgunstudio.com/page/12787?layout=layout_3
- Sample card: https://respawn.shotgunstudio.com/page/12787#Asset_38811

The page URL is a navigation and setup reference. The application uses an explicit ShotGrid API query derived from `layout_3` during implementation (entity type, filters, fields, sort). Entity type is expected to be **Asset**; confirm when extracting the query.

Setup stores:

- ShotGrid site and project;
- entity type;
- filters representing the `layout_3` worklist;
- sort order; and
- fields requested for each card.

Setup must validate the query against known cards from that page (e.g. Asset 38811 shape).

Authentication uses the shared script/API key in Windows Credential Manager.

### 4.2 Dashboard Cards

Cards reflect the `layout_3` worklist. The dashboard may still show older or blocked cards for manual visibility; scheduled prep targets whatever `layout_3` returns.

Every card shows:

- thumbnail;
- asset name linked to its ShotGrid record;
- submission/status information;
- latest relevant delivery-comment summary (CL text);
- detected attachments and CLs;
- delivery methods;
- route-level prep state; and
- a derived card-level summary.

The application ships with a curated field set. Users may add optional ShotGrid fields without requiring the application to mirror the UI layout dynamically.

### 4.3 Selection

Users may:

- select or clear a complete group;
- toggle individual cards;
- manually **Prepare** cards (same idempotent pipeline as the scheduled worker); and
- select one or more prepared cards and choose **Open Again**.

There is no **Re-run** action. Preparing an already-ready card is a no-op unless the source identity changed or prepared content is missing/invalid.

## 5. Date Selection and Catch-up

**MVP worklist authority:** ShotGrid `layout_3`. Prep whatever that query returns. Do not apply an additional Windows-local-date equality gate for card selection.

Windows-local date is still used for:

- daily exactly-once launch leases;
- summary acknowledgment; and
- staging folder naming (`DAYNAME_MM_DD_YYYY`).

If the machine was off or asleep past 5:00 AM, Task Scheduler runs prep at the next opportunity the same local day. If prep finishes while the session is already interactive, eligible files launch then (still exactly-once). If `layout_3` returns nothing, record an empty/skip run and explain it in the next summary.

Comment and attachment timestamps do not determine daily eligibility. They only determine the newest relevant delivery within a card.

Slack-based daily lists are deferred (future extension).

## 6. Deliveries: Attachments and Comments

### 6.1 Archives (ATTACHMENTS)

Downloadable review archives live under the card's **ATTACHMENTS**. Recognized archive types for MVP: `.rar` and `.zip`. Screenshots and other reference attachments may be retained as context but are not launchable unless a user-defined rule classifies them as such.

### 6.2 Perforce CLs (comments)

Labeled CL references live in **comments**. The parser searches the configured comment/note thread in descending edit/creation order. A relevant delivery comment is the newest comment containing at least one labeled Perforce CL reference.

A later internal comment with no deliverable does not hide an earlier delivery comment.

CL patterns capture both a category label and numeric changelist, such as:

- `Source Art CL is 11288616`;
- `Preflight CL is 11288606`; and
- `WIP CL 11290000`.

The original comment text, comment ID, attachment IDs, parsed labels, and CL numbers are stored in the manifest. Unknown CL labels are retained and assigned the safe default policy (**Sync only**).

### 6.3 Combined routes

If a card has both attachments and CL comments, every applicable route is processed independently in the same prep run.

## 7. Attachment Acquisition

### 7.1 Storage

Downloaded content is stored beneath a user-configured root (chosen at setup):

`<staging-root>/DAYNAME_MM_DD_YYYY/<safe-asset-name>_<shotgrid-id>/`

For example:

`D:/ReviewPrep/MON_07_13_2026/destruction_kit_interior_12345/`

The human-readable name is sanitized for Windows. The stable ShotGrid ID prevents collisions between similarly named cards. Manifests use immutable ShotGrid comment and attachment identities to detect already processed content.

Existing work is never silently deleted or overwritten.

Retention: user-configurable **N days** (default: keep forever). Cleanup must never remove today's in-use staging paths.

### 7.2 Archives and Extraction

Recognized archives are downloaded and extracted with **7-Zip** (`7z.exe`). Settings store the extractor path and auto-detect common install locations (e.g. `C:\Program Files\7-Zip\7z.exe`, `c:\depot\tools\bin\7z.exe`).

Archive extraction must:

- reject absolute paths and traversal outside the asset workspace;
- impose configurable expanded-size and file-count limits;
- handle collisions explicitly;
- quarantine corrupt, encrypted, or unsupported archives;
- avoid recursive extraction unless explicitly enabled; and
- finalize from a temporary location only after successful validation.

Loose recognized review files, when present, download directly (secondary path).

## 8. File Detection and Launch Rules

Built-in recognized types include:

- Maya: `.ma`, `.mb`;
- ZBrush: `.ztl`, `.zpr`; and
- Substance 3D Painter: `.spp`.

Users may add:

- extensions;
- include/exclude path or filename patterns;
- Cadet launch command templates; and
- launch concurrency limits (MVP default: **no cap**; setting retained).

Default behavior: open **all** recognized DCC files selected by launch rules. Patterns are the escape hatch; no magic "primary file" heuristic in MVP.

### 8.1 Cadet gateway

Interactive opens go through **Cadet** with toolset **`apex_r5dev`** (not raw `maya.exe` as the primary path). Settings store per-DCC Cadet launch command templates (exact CLI captured during implementation).

**MVP Cadet policy:** Assume Cadet is already running with the correct toolset. If Cadet is missing or the toolset is wrong, log a clear prompt, do not consume a successful daily launch lease, leave files ready for **Open Again**, and do not auto-start or auto-enter Cadet.

Prep (download/sync/extract) does not require Cadet.

## 9. Perforce Acquisition

### 9.1 CL Detection and Policies

Every labeled CL in the latest relevant delivery comment is evaluated. Users configure one policy per CL category:

- **Ignore**
- **Sync only**
- **Sync and open**

Shipped defaults:

| Category | Default |
|----------|---------|
| Source Art | Sync only |
| Preflight | Sync only |
| WIP | Sync and open |
| Unknown | Sync only |

Policies are per user.

### 9.2 Workspace

MVP uses the artist's **everyday P4 client** (selected in setup/settings). A dedicated review client is not required.

Before syncing, the application:

1. Validates the P4 executable, server, user, ticket, and client.
2. Retrieves and validates each submitted CL.
3. Previews the exact-CL sync.
4. Resolves depot files to local paths through the selected client.
5. Checks mappings, opened files, writable conflicts, and overlapping CL files.
6. **Skips unsafe files only** — never force, clobber, or auto-revert. Continue sibling files/routes. Report skips in the summary.
7. Displays the planned depot-to-local mapping and records it in the manifest.

Submitted files sync at their exact CL revisions. Only files submitted in the CL are included by default; unrelated workspace files are not advanced.

When multiple CLs affect the same file, the application detects the overlap and applies deterministic numeric CL order while warning the user in the result summary.

### 9.3 Optional Dependencies

Each CL category may define optional depot dependency roots. These roots:

- are never inferred automatically;
- must be explicitly configured;
- ship **empty** in MVP (no team defaults);
- are previewed before syncing; and
- sync to `#head`, not to the submitted CL revision.

The manifest distinguishes exact submitted-file revisions from dependency files synced to head.

### 9.4 Opening P4 Files

For **Sync and open**, category-specific include/exclude rules select recognized DCC files from the files submitted in the CL. The default is to open every recognized DCC file submitted in that CL (via Cadet).

Dependency files sync but do not open unless they are also submitted files selected by the category's launch rules.

## 10. Launch Lifecycle

### 10.1 First Interactive Session of the Local Day

Launch when the Windows session becomes interactive for that user on the local date (login or unlock with an interactive session). Log which trigger fired (important for Parsec/VM debugging).

Each prepared launchable file has an exactly-once daily launch record. A persisted launch lease prevents duplicate launches caused by:

- repeated locks and unlocks;
- Parsec reconnects to an already-interactive session after the lease was consumed;
- multiple foreground instances;
- application restarts; or
- worker/foreground races.

If prep completes after the first interactive moment while the session is interactive, newly eligible files launch when prep completes.

Cadet-not-ready failures do not count as successful launches.

### 10.2 Summary Auto-Open and Acknowledgment

When there is an unacknowledged prep result for the local day (success, skip, partial, or failure), auto-open the dashboard/summary after login/unlock.

Persisting acknowledgment: closing the summary acknowledges that prep-run id for the day. Do not re-popup on later unlocks until a newer prep result exists. Manual dashboard launch and **Open Again** remain available always.

### 10.3 Open Again

**Open Again** works on one or more selected prepared cards.

It:

- performs no ShotGrid refresh;
- performs no download;
- performs no extraction;
- performs no P4 sync; and
- opens launchable files already recorded in the local manifest (via Cadet).

It supports both attachment-based files and P4 files prepared under **Sync and open**. Manual Open Again intentionally bypasses the daily exactly-once launch record.

## 11. Scheduling, Authentication, and Recovery

Per-user settings include:

- scheduled prep time (default **5:00 AM** local);
- run-on-next-opportunity / catch-up behavior;
- retry count and delay;
- ShotGrid query configuration (shipped `layout_3` default);
- staging root and retention N days;
- P4 executable, server, user, client, and category policies;
- dependency roots (empty by default);
- archive rules and `7z.exe` path;
- file recognition / include-exclude patterns;
- Cadet launch command templates;
- launch concurrency (default uncapped); and
- summary preferences.

Secrets (ShotGrid script key) are stored in Windows Credential Manager. Existing P4 tickets/configuration are reused rather than storing a P4 password where possible. The worker and foreground application run as the same Windows user.

The worker must not rely on mapped drive letters; local or UNC paths are required for unattended access.

Before work begins, the worker preflights:

- ShotGrid connectivity and authentication;
- P4 connectivity, ticket validity, and client availability;
- configured storage paths;
- available disk space; and
- 7-Zip extractor availability.

Transient failures receive bounded retries. After retries are exhausted, the next summary states:

- what completed;
- what failed or was skipped;
- why;
- what the user must do, such as connect VPN, renew a P4 ticket, or enter Cadet; and
- which retry or Open Again action is available.

The application does not promise unattended prep while the workstation is powered off or asleep. It runs at the next Task Scheduler opportunity and reports whether prep completed before the user began work.

## 12. State and Idempotency

A local SQLite database stores:

- scheduled and manual prep runs;
- ShotGrid cards, comments, and attachment identities;
- CL categories, numbers, depot revisions, and local mappings;
- route-level step states;
- extracted and detected files;
- launch eligibility and launch history;
- summary acknowledgment;
- errors and retry history; and
- configuration schema version.

Operations are idempotent. Successful route steps are not repeated unless the source identity changes or local verification shows that prepared content is missing or invalid.

Route states include:

- not prepared;
- queued;
- downloading;
- extracting;
- syncing;
- ready to launch;
- synced only;
- launched;
- skipped;
- partial; and
- failed.

Card-level state is derived from route states and must not hide partial failure.

## 13. Error Handling and Notifications

One failed asset or route does not stop independent work.

Errors must:

- identify the failed step and source;
- include actionable remediation;
- avoid exposing credentials;
- preserve successful sibling routes; and
- support targeted retry where retry is meaningful.

MVP reports through the **dashboard summary only** (auto-open when unacked). No Windows toast, email, or Slack notifications in MVP. Additional channels may be added later.

## 14. Packaging and Prerequisites

The application is delivered through a Windows installer that packages the Python runtime and libraries. Users are not required to install Python, Node.js, or developer tooling. Prefer a per-user layout that works without elevation for daily use; prep identity remains the interactive Windows user.

Operational prerequisites are:

- supported Windows workstation (including VM / Parsec);
- ShotGrid script-key access (shared department key);
- network/VPN access;
- P4 command-line access and the artist's everyday client when CL delivery is used;
- Cadet with `apex_r5dev` available for interactive launches;
- 7-Zip available or path configured;
- installed DCC applications reachable via Cadet; and
- permissions to register per-user scheduled and login/unlock tasks.

## 15. Component Boundaries

The implementation separates:

- ShotGrid query adapter (`layout_3` default);
- ShotGrid delivery resolver (attachments + comments);
- deterministic comment/CL parser;
- attachment downloader;
- safe archive extractor (7-Zip);
- P4 adapter and safety planner;
- file classifier;
- prep orchestrator;
- manifest/state repository;
- scheduler integration;
- foreground launch coordinator (Cadet);
- dashboard UI; and
- settings/credential services.

Each component exposes a narrow interface and can be tested without running the other external systems.

## 16. Testing

Unit tests cover:

- `layout_3` worklist handling and empty-result skip behavior;
- latest relevant comment selection;
- mixed attachment + CL routes on one card;
- labeled and unknown CL parsing;
- Windows path sanitization;
- archive traversal and expansion limits (rar/zip);
- file classification and custom rules;
- per-category P4 policies and shipped defaults;
- exact-CL and dependency-head command planning;
- overlapping CL detection and unsafe-file skip (no force);
- idempotent route execution;
- route/card state derivation;
- exactly-once launch leases, Cadet-not-ready non-success, and Open Again bypass; and
- summary acknowledgment / no re-popup behavior.

Adapter integration tests cover:

- ShotGrid query parity with page 12787 `layout_3` and attachment download;
- P4 preview, mapping, exact-CL sync, dependency sync, and conflicts;
- Windows Credential Manager;
- Task Scheduler registration and catch-up;
- 7-Zip extraction; and
- Cadet launch command invocation.

A controlled Windows end-to-end test covers a mixed submission containing:

- an attachment archive (rar or zip);
- multiple labeled CLs;
- at least one **Sync only** category;
- at least one **Sync and open** category;
- first-interactive launch followed by manual Open Again; and
- summary auto-open + acknowledge.

## 17. Version-One Non-Goals

Version one does not:

- write prep status back to ShotGrid;
- parse Slack as the daily worklist;
- auto-start or auto-enter Cadet / `apex_r5dev`;
- infer dependencies from DCC scene contents;
- use AI to interpret delivery comments;
- dynamically reproduce arbitrary ShotGrid UI layouts;
- force unsafe P4 workspace changes;
- provide a dashboard Re-run operation;
- guarantee work while a workstation is off or asleep;
- ship Windows toast / email / Slack notifications; or
- centrally manage team configuration.

## 18. Future Extensions

Potential later work includes:

- Slack "3D submission" worklist integration;
- Cadet auto-start / auto-enter `apex_r5dev`;
- launch concurrency defaults tuned from field use;
- IT-managed defaults with per-user overrides;
- additional notification channels;
- centrally managed updates;
- DCC-aware dependency discovery;
- richer CL-label templates;
- isolated per-asset Perforce workspaces;
- ShotGrid write-back; and
- additional review-file formats and launchers.
