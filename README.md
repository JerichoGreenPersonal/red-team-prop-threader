# red-team-prop-threader

Internal Slack app that creates and indexes prop-request threads from API-exportable ShotGrid pages.

## Overview

`red-team-prop-threader` is a Python 3.11 web service with three entry points:

- **`prop-threader-web`** — Flask/Waitress HTTP server handling Slack events and slash commands
- **`prop-threader-worker`** — background worker that polls ShotGrid for new prop requests and creates Slack threads
- **`prop-threader-retention`** — scheduled job that enforces thread retention policy

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
│   └── setup/
├── src/red_team_prop_threader/
│   ├── __init__.py
│   ├── web.py              # Flask/Waitress entry point
│   ├── worker.py           # Polling worker entry point
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
