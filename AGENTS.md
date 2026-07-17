# Project — Agent Instructions

This file is the entry point for GitHub Copilot agents and other AI assistants working in this repository.

## Repository Overview

`red-team-prop-threader` is an internal Slack app that creates and indexes prop-request threads from API-exportable ShotGrid pages. It is a Python 3.11 web service with separate web, worker, and retention entry points.

## Style Guides & Instructions

Domain-specific coding standards live in dedicated files — not here. Consult them when working in the relevant domain:

### GitHub Copilot

- **`.github/copilot-instructions.md`** — Copilot entry point (references the skills above)
- **`.github/agents/code-manager.agent.md`** — Code enforcement agent

### Skills (`.agents/skills/`)

- **`.agents/skills/bumpversion/SKILL.md`** — Version bump and changelog workflow
- **`.agents/skills/grill-me/SKILL.md`** — Interview the user to stress-test a plan or design
- **`.agents/skills/topic-documentation/SKILL.md`** — Interview-driven writeups for a topic at Executive, Manager, and Engineering density levels (saved to `docs/topics/`)

## Quick Reference

### Validation Commands

```bash
# Python
uv run ruff check .
uv run ruff format --check .
uv run ty check .
uv run pytest
```

### Build

```powershell
.\bin\build.ps1
```

### Key Files

- **`version.toml`** — single source of truth for version
- **`VERSION`** — auto-generated, do not edit
- **`ruff.toml`** / **`ty.toml`** / **`uv.toml`** — tooling configuration
- **`slack-app-manifest.yaml`** — Slack app manifest for IT provisioning
