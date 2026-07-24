# Daily Review Prep Assistant

Windows desktop assistant for preparing daily review routes: syncing Perforce changelists, downloading ShotGrid attachments, and tracking route state through launch.

Built on Python 3.12+ with PySide6, `shotgun-api3`, and `keyring`. Run tests with `uv run pytest`.

## Packaging (PyInstaller)

Build self-contained Windows executables (no user-installed Python required at runtime):

```powershell
# From repo root (uses uv packaging group → pyinstaller)
.\packaging\build.ps1
```

Outputs:

| Binary | Mode | Path |
|--------|------|------|
| `review-prep-worker.exe` | console | `packaging/dist/review-prep-worker.exe` |
| `review-prep.exe` | windowed (PySide6) | `packaging/dist/review-prep.exe` |

### Install (per-user)

```powershell
.\packaging\install.ps1
```

This will:

1. Copy both EXEs to `%LOCALAPPDATA%\ReviewPrep\app\`
2. Create a **Start Menu** shortcut: `Review Prep` → `review-prep.exe`
3. Register Task Scheduler jobs (unless `-SkipSchedule`):
   - `ReviewPrep\DailyPrep` — daily worker at 05:00 local (override with `-ScheduleHour` / `-ScheduleMinute`); `StartWhenAvailable` catch-up
   - `ReviewPrep\OpenDashboard` — on-logon helper to open the dashboard

First launch of `review-prep.exe` runs the empty-settings setup wizard when `settings.json` is missing under `%LOCALAPPDATA%\ReviewPrep\`.

Smoke-check the worker after build:

```powershell
.\packaging\dist\review-prep-worker.exe --help
```

---

This repository started from a Python package template. The sections below document template tooling (`uv`, `ruff`, `ty`, pytest) still used during development.

## Features

### Automated Setup

- **One-command initialization** with `bin/setup/setup-project.ps1`
    - Check `Option A` down below for skill based setup.
- **Auto-detects project name** from folder or accepts `-Name` parameter
- **Vendored `uv` binary** for consistent dependency management
- **Dynamic versioning** from `version.toml` (single source of truth)

### Code Quality Standards

- **Python 3.11+** with modern type hints and strict typing
- **pytest** for testing with 90%+ coverage targets
- **ruff** for fast linting and formatting (160 char line length)
- **ty** for comprehensive type checking
- **Custom logging module** pattern (`_logging.py`)

### Multi-Language Support

- **Python**: Backend packages with strict standards
- **React + TypeScript + Vite**: Modern frontend with Vitest + React Testing Library
- **Electron**: Desktop apps with security-first architecture

### Code Organization

- **No monolithic files**: Submodules when 2+ supporting modules needed
- **No monolithic functions**: Max 100 lines, refactor into helpers
- **Feature-based organization**: Clean module structure
- **Comprehensive style guides**: Python, React/TypeScript, Electron

### AI Assistant Integration

- **Shared skills** (`.agents/skills/`) — canonical workflows for version bumping, design reviews, etc.
- **GitHub Copilot** (`.github/copilot-instructions.md`)
- **Windsurf** (`.windsurf/rules/`, `.windsurf/workflows/`)
- **Claude** (`.claude/skills/`, `CLAUDE.md`)
- **Codex** (`.codex/`, `AGENTS.md`)

## Getting Started

### Option A — AI-assisted setup (Claude Code, Cursor, Windsurf, Codex)

If you're using an AI coding assistant, the `/project-setup` skill handles initialization interactively. The skill interviews you about the project, runs the setup scripts, patches configuration, and updates the documentation files — so you don't have to memorize flags or hand-edit `pyproject.toml`.

1. Clone the template and open it in your editor.
2. Run the skill in the AI chat panel:
    - **Claude Code:** type `/project-setup` (mapped via `.claude/commands/project-setup.md`).
    - **Cursor:** type `/project-setup` or say "run the project-setup skill" — Cursor reads `AGENTS.md` and follows the skill at `.agents/skills/project-setup/SKILL.md`.
    - **Windsurf:** type `/project-setup` (mapped via `.windsurf/workflows/project-setup.md`).
    - **Codex CLI:** ask Codex to "run project setup" — it reads `.codex/AGENTS.md` and follows the skill.
3. Answer the interview questions. The skill asks about:
    - What you're building (1-2 sentence description)
    - Project name (defaults to folder name)
    - Languages (Python, TypeScript/JavaScript, HTML, or other)
    - Project kind (library, CLI tool, web service, frontend, desktop, notebook, or mixed)
    - Python version and CLI command name (if applicable)
    - Frontend stack (React + Vite, Electron + React, plain HTML, or other)
    - License, author info, and git remote URL (optional)
4. Review the setup summary and approve. The skill runs `bin/setup/setup-project.ps1` and `bin/setup/get-npm.ps1` as needed, patches `pyproject.toml` with your license/author/repo info, and updates `CLAUDE.md`, `AGENTS.md`, `.codex/AGENTS.md`, `.github/copilot-instructions.md`, and this README with project-specific content.

The canonical skill lives at `.agents/skills/project-setup/SKILL.md` — one source of truth across every assistant.

### Option B — Manual setup

### 1. Clone the template

```bash
git clone <this-repo-url> my-project
cd my-project
```

### 2. Vendor `uv`

Download and install the `uv` binary to the repository root:

```powershell
# Windows
.\bin\setup\get-uv.ps1
```

### 3. Initialize the project

Run `setup-project` to scaffold the package, add dev dependencies, create a virtual environment, and set up the workspace file:

```powershell
# Windows
.\bin\setup\setup-project.ps1 -Name my-project

# Or auto-detect project name from folder
.\bin\setup\setup-project.ps1
```

**Flags:**

| Flag                   | Required | Default | Description                                         |
| ---------------------- | -------- | ------- | --------------------------------------------------- |
| `-Name` / `--name`     | No       | folder  | Project name (no spaces, auto-detected from folder) |
| `-Python` / `--python` | No       | `3.11`  | Python version (e.g., `3.11.8`)                     |

**What `setup-project` does:**

1. Runs `uv init <name> --package --python <version>` to scaffold the project
2. Patches `pyproject.toml` for dynamic versioning (`setuptools` + `VERSION` file)
3. Adds dev dependencies: `ruff`, `ty`, `pytest`
4. Creates a virtual environment with `uv venv`
5. Renames the workspace file from `template-py-package.code-workspace` to `<folder-name>.code-workspace`

If `pyproject.toml` already exists, the script exits early — it will not overwrite an existing project.

### 4. Start developing

After initialization, you have a fully configured project:

- **Write code** in `src/<project-name>/`
- **Add tests** in `tests/` using pytest
- **Update version** in `version.toml`
- **Follow style guides** in `.windsurf/rules/` and `.github/instructions/`
- **Run validation** before committing (see commands below)

## Development Commands

### Python Validation

```bash
# Lint
uv run ruff check .

# Format check
uv run ruff format --check .

# Type check
uv run ty check .

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=src --cov-report=html

# Build wheel
.\bin\build.ps1
```

### React/TypeScript (if using)

```bash
npm run type-check    # TypeScript compilation
npm run lint          # ESLint
npm run test          # Vitest
npm run test:coverage # Coverage report
```

### Electron (if using)

```bash
npm run type-check    # TypeScript compilation
npm run test          # Vitest (main + renderer)
npm run test:e2e      # Playwright E2E tests
npm audit             # Security audit
```

## Project Structure

### After Running `setup-project.ps1`

```text
<project>/
├── bin/
│   ├── build.ps1                 # Build wheel
│   └── setup/                    # Setup scripts
│       ├── get-uv.ps1            # Install/vendor uv
│       ├── get-npm.ps1           # Verify Node.js/npm, install client deps
│       └── setup-project.ps1     # Initialize project from template
├── client/                       # Optional frontend (React/TS/Vite/Electron)
├── docs/                         # Documentation
├── src/<project-name>/           # Package source (src-layout)
│   ├── __init__.py               # Public API exports
│   ├── _errors.py                # Exception hierarchy
│   ├── _logging.py               # Custom logging module (required)
│   └── ...                       # Your modules
├── tests/                        # pytest tests
├── .agents/
│   └── skills/                   # Canonical AI skill workflows
│       ├── bumpversion/SKILL.md  # Version bump and changelog
│       └── grill-me/SKILL.md     # Design stress-test interviews
├── .claude/
│   └── skills/                   # Claude skill stubs
├── .codex/                       # Codex agent config
├── .github/
│   └── copilot-instructions.md   # GitHub Copilot config
├── .windsurf/
│   ├── rules/                    # Windsurf editor rules
│   └── workflows/                # Windsurf slash-command workflows
├── pyproject.toml                # Package metadata (dynamic versioning)
├── ruff.toml                     # Ruff configuration
├── ty.toml                       # Type checker configuration
├── version.toml                  # Version source of truth
├── VERSION                       # Generated version file
├── AGENTS.md                     # AI assistant instructions
├── CLAUDE.md                     # Claude-specific guidance
└── <project>.code-workspace      # VS Code workspace
```

### Module Organization

When your code grows, organize into submodules:

```text
src/<project>/
├── __init__.py
├── _errors.py
├── _logging.py
├── cache/                        # Submodule (when 2+ related modules)
│   ├── __init__.py               # Exports public API
│   ├── manager.py
│   ├── storage.py
│   └── _serializers.py           # Internal
└── processing/
    ├── __init__.py
    ├── processor.py
    └── validators.py
```

**Rules:**

- Create submodules when a module needs 2+ supporting modules
- Keep modules < 300 lines
- Keep functions < 100 lines (refactor into helpers)
- Prefix internal modules with `_`
- Max 2 levels deep
