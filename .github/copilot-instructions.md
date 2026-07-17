# Copilot Instructions

`red-team-prop-threader` is an internal Slack app that creates and indexes prop-request threads from API-exportable ShotGrid pages. It is a Python 3.11 web service (`pyproject.toml` exists — treat as a normal Python package).

## Style Guides & Skills

Domain-specific coding standards live in dedicated skill files. Consult them when working in the relevant domain:

- **`.agents/skills/bumpversion/SKILL.md`** — Version bump and changelog workflow
- **`.agents/skills/grill-me/SKILL.md`** — Interview the user to stress-test a plan or design
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
```

## Build

```powershell
.\bin\build.ps1
```
