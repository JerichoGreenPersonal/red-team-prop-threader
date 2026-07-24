# Copilot Instructions

This repository is a **Python package template** for creating Python 3.11+ packages with modern tooling (`uv`, `ruff`, `ty`, `pytest`). It also supports frontend development with React + TypeScript + Vite and Electron.

## Template State

- **No `pyproject.toml`** → still a template. Guide the user to run `bin/setup/setup-project.ps1 -Name "project-name"`.
- **`pyproject.toml` exists** → initialized project. Treat as a normal Python package.

## Style Guides & Skills

Domain-specific coding standards live in dedicated skill files. Consult them when working in the relevant domain:

- **`.agents/skills/bumpversion/SKILL.md`** — Version bump and changelog workflow
- **`.agents/skills/grill-me/SKILL.md`** — Interview the user to stress-test a plan or design
- **`.agents/skills/project-setup/SKILL.md`** — Initialize this template into a real project
- **`.agents/skills/topic-documentation/SKILL.md`** — Interview-driven writeups for a topic at Executive, Manager, and Engineering density levels (saved to `docs/topics/`)

## Copilot Behavior

- Assume the user is an experienced engineer
- Code must be deterministic, explicit, testable, lint-clean, and safe
- No emojis, hype tone, or conversational filler
- No suggestion of packages not already in `pyproject.toml` dependencies
- No TODOs without username annotations (`# TODO (username): message`)

## Validation Commands

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

## Build

```powershell
.\bin\build.ps1
```
