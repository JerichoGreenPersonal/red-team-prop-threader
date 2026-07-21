# red-team-prop-threader

Internal Slack app that creates and indexes prop-request threads from API-exportable ShotGrid pages.

**Author:** Jericho A. Green ([jgreen2@ea.com](mailto:jgreen2@ea.com))

## Overview

### Long Description

RED Team Prop Threader:
• Imports up to 30 assets from an API-exportable ShotGrid page via `/create-prop-threads`
• Validates Asset Name and Entity ID columns, deduplicates Entity IDs, and preserves export order
• Collects group-level and asset-level context in a paginated Slack modal (Animator, Additional People, supporting links)
• Lets users exclude individual assets before submission (at least one must remain included)
• Presents a confirmation summary of channel, group title, included count, and conflict warnings
• Creates one Slack root message per selected asset after explicit confirmation
• Indexes threads in the channel canvas under `INDEX OF PROP REQUESTS`
• Supports latest-only post-completion edits without sending new notifications

The result is a consistent, discoverable set of prop-request threads that stakeholders can follow without manually copying assets from ShotGrid or rebuilding channel indexes by hand.

Human-in-the-Loop Control (does not post prop threads autonomously — by design)
All prop-request threads are assembled as a private draft and require confirmation before any public messages are created. The bot does not autonomously publish asset roots or canvas updates from a slash-command invocation alone. This ensures oversight, editorial control, and alignment with team communication standards. After confirmation, processing cannot be cancelled mid-batch; failures are reported privately with a Retry Failed path.

Canvas Indexing
When a channel canvas is missing or mistitled, the app asks for confirmation before creating or renaming it to `INDEX OF PROP REQUESTS`. Canvas edits are narrow and additive: the bot maintains group headings and asset links for threads it creates, without overwriting unrelated canvas content.

Latest-Only Editing
Any current channel member (invoking from the EA workspace) may edit group or asset details on the current `Latest` messages only. Historical roots remain snapshots. Edits update the latest roots and canvas summary without re-notifying mentioned users.

`red-team-prop-threader` is a Python 3.11 web service with three entry points:

- **`prop-threader-web`** — Flask/Waitress HTTP server handling Slack events and slash commands
- **`prop-threader-worker`** — background worker that executes durable prop-thread batches
- **`prop-threader-retention`** — scheduled job that redacts aged job payloads and expires drafts

## Development Setup

### Prerequisites

- Python 3.11 (managed by `uv`)
- PostgreSQL (or SQLite for local dev via `DATABASE_URL`)
- A Slack app configured from `slack-app-manifest.yaml`

### Install Dependencies

```powershell
# All runtime + dev deps (creates .venv automatically)
.\uv.exe sync --all-groups
```

### Environment

Copy `.env.example` to `.env` and fill in values:

```powershell
Copy-Item .env.example .env
```

### Local run

```powershell
.\bin\run-local.ps1          # web + worker (+ optional tunnel)
.\bin\run-local.ps1 -Test    # run pytest/ruff/ty first
```

### Administrator docs

- [Slack app setup (IT / manifest)](docs/admin/slack-app-setup.md)
- [Development-channel pilot procedure](docs/admin/pilot-test.md)
- [ROI assessment / reason for the app](docs/admin/roi.md)
- Manifest: [`slack-app-manifest.yaml`](slack-app-manifest.yaml) — replace `prop-threader-dev.example.invalid` before import

## Development Commands

### Python Validation

```bash
# Lint
uv run ruff check .

# Format check
uv run ruff format --check .

# Type check
uv run ty check

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=src --cov-report=html
```

### Build

```powershell
.\bin\build.ps1
```

## Project Structure

```text
red-team-prop-threader/
├── bin/
│   ├── build.ps1
│   ├── run-local.ps1
│   ├── run-local.bat
│   └── setup/
├── docs/admin/
│   ├── slack-app-setup.md
│   └── pilot-test.md
├── src/red_team_prop_threader/
│   ├── __init__.py
│   ├── web.py              # Flask/Waitress entry point
│   ├── worker.py           # Durable batch worker entry point
│   └── retention.py        # Retention job entry point
├── tests/
├── .agents/                # AI skill workflows
├── pyproject.toml
├── ruff.toml
├── ty.toml
├── version.toml
├── VERSION
└── slack-app-manifest.yaml
```

## Key Files

- **`version.toml`** — single source of truth for version
- **`VERSION`** — auto-generated, do not edit
- **`ruff.toml`** / **`ty.toml`** / **`uv.toml`** — tooling configuration
- **`slack-app-manifest.yaml`** — Slack app manifest for IT provisioning
- **`docs/admin/slack-app-setup.md`** — manifest import and scope justification
- **`docs/admin/pilot-test.md`** — development-channel pilot checklist
