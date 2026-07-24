# Project — AI Assistant Instructions

This file is the entry point for AI assistants (Claude Code, Claude Chat, etc.) working in this repository. It provides orientation and points to the detailed guides that live alongside the code.

## Repository Overview

This is a **Python package template** for creating Python 3.11+ packages with modern tooling (`uv`, `ruff`, `ty`, `pytest`). It also supports frontend development with React + TypeScript + Vite and Electron.

## Template State

Check whether this repo has been initialized:

- No @pyproject.toml → still a template. Guide the user to run `bin/setup/setup-project.ps1 -Name "project-name"`.
  They may need to run `bin/setup/get-uv.ps1` first.
- @pyproject.toml exists → initialized project. Treat as a normal Python package.

## Style Guides & Skills

Domain-specific coding standards live in dedicated files — not here. Consult them when working in the relevant domain:

### Skills (`.agents/skills/`)

- **`.agents/skills/bumpversion/SKILL.md`** — Version bump and changelog workflow
- **`.agents/skills/grill-me/SKILL.md`** — Interview the user to stress-test a plan or design
- **`.agents/skills/project-setup/SKILL.md`** — Initialize this template into a real project
- **`.agents/skills/topic-documentation/SKILL.md`** — Interview-driven writeups for a topic at Executive, Manager, and Engineering density levels (saved to `docs/topics/`)

### GitHub Copilot

- **`.github/copilot-instructions.md`** — Copilot entry point (references the skills above)
- **`.github/agents/code-manager.agent.md`** — Code enforcement agent

## Quick Reference

### Validation Commands

```bash
# Python
uv run ruff check .
uv run ruff format --check .
uv run ty check .
uv run pytest

# React/TypeScript
npm run type-check
npm run lint
npm run test
```

### Build

```powershell
.\bin\build.ps1
```

### Key Files

- **`version.toml`** — single source of truth for version
- **`VERSION`** — auto-generated, do not edit
- **`ruff.toml`** / **`ty.toml`** / **`uv.toml`** — tooling configuration

## Template Maintenance

When improving this template:

- Keep examples generic (no domain-specific names)
- Maintain cross-platform compatibility (PowerShell + Bash)
- Update `.agents/skills/` and `.github/copilot-instructions.md` when changing standards
- Test the initialization flow on a clean clone
