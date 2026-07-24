---
name: project-setup
description: Use when initializing this template into a real project. Triggers on /project-setup, "set up the project", "initialize this template", or when pyproject.toml is missing and the user wants to start building.
---

# Project Setup

Interactive wizard that interviews the user about the project, runs the appropriate setup scripts, patches configuration files, and updates all documentation to reflect the new project identity.

This template's setup script is Python-centric (uv + ruff + ty + pytest). For non-Python projects (frontend-only, Java, Go, Rust, etc.), the skill skips the Python scaffolding and gives the user manual setup guidance.

**Guard:** If `pyproject.toml` already exists, tell the user the project is already initialized and stop. Do not re-run.

## Workflow

### 1. Interview the user

Ask questions **one at a time**. Provide a default where noted - accept it if the user doesn't care. After every 2-3 answers, briefly echo back what you've captured so far to keep the user oriented.

Capture answers into a mental scratchpad. You will summarize them in step 2 before executing anything.

#### 1a. What are you building?

Free-text. Get a 1-2 sentence description. This drives the documentation updates and how you tailor later questions.

Probe if the answer is too vague:
- "is it a library, a CLI, a web service, a desktop app, a static site?"
- "who is it for - developers, end users, internal tooling?"
- "what problem does it solve?"

Save as `description`.

#### 1b. Project name

What should we call it? Default: parent folder name. Constraints:
- No spaces.
- Lowercase, kebab-case or snake_case.
- Will be the Python package name (if Python is selected), so it must be a valid Python identifier when underscores replace dashes.

Save as `name`.

#### 1c. Languages

Which languages will this project use? Multi-select. Read the list, let the user pick one or more:

1. **Python** - backend, CLIs, scripts, data, ML
2. **TypeScript / JavaScript** - frontend, Node services
3. **HTML / CSS only** - static site, landing page
4. **Other** - Java, Go, Rust, C#, etc. (the template will skip its built-in scaffolding; user handles their own toolchain)

Save as `languages` (list).

#### 1d. Project kind

What kind of project? Pick the closest match - this informs the documentation tone and whether to wire up a CLI entry point:

1. Library / package (importable code, no entry point)
2. CLI tool (command-line entry point)
3. Web service / API (FastAPI, Flask, Express, etc.)
4. Web frontend (SPA, static site)
5. Desktop app (Electron, Tauri, etc.)
6. Notebook / data analysis
7. Mixed / full-stack

Save as `kind`.

#### 1e. Python details (only if Python in `languages`)

- **Python version?** Default: `3.11`. Accept major.minor or major.minor.patch (e.g. `3.11`, `3.12.4`, `3.13`).
- **CLI command name?** Only if `kind` is "CLI tool". Default: `name`. This becomes the `[project.scripts]` entry in `pyproject.toml`.

Save as `python_version`, `cli_command` (optional).

#### 1f. Frontend details (only if TypeScript/JavaScript or HTML in `languages`)

- **Frontend stack?**
  1. React + TypeScript + Vite
  2. Electron + React + TypeScript
  3. Plain HTML / JS / CSS
  4. Other (the user will scaffold it manually)
- **Is Node.js installed?** (yes / no / unsure)

Save as `frontend_stack`, `has_node`.

#### 1g. License

What license? Default: `MIT`. Common alternatives: `Apache-2.0`, `BSD-3-Clause`, `GPL-3.0`, `MPL-2.0`, `proprietary` (for closed-source / internal projects).

Save as `license`.

#### 1h. Author info (optional)

- **Author / maintainer name?** (optional - press enter to skip)
- **Author email?** (optional - press enter to skip)

These will be written into `pyproject.toml` if Python is selected. Skip silently if either is blank.

Save as `author_name`, `author_email`.

#### 1i. Repository URL (optional)

- **Git remote URL?** (optional - press enter to skip)

If provided, it will be added to `pyproject.toml` under `[project.urls]`.

Save as `repo_url`.

### 2. Confirm before executing

Present a summary table and the action list. Do **not** run any commands until the user explicitly approves.

```
project setup summary

  description:   <description>
  name:          <name>
  languages:     <comma-separated languages>
  kind:          <kind>
  python:        <python_version>           (omit row if not selected)
  cli command:   <cli_command>              (omit row if not a CLI)
  frontend:      <frontend_stack>           (omit row if not selected)
  license:       <license>
  author:        <author_name> <author_email>   (omit row if blank)
  repo:          <repo_url>                 (omit row if blank)

actions:
  1. <if Python selected>
     run bin/setup/setup-project.ps1 -Name "<name>" -Python "<python_version>"
       scaffolds pyproject.toml, src/<name>/, dev deps (ruff, ty, pytest), .venv
  2. <if Python selected and any of license/author/repo/cli provided>
     patch pyproject.toml with license, authors, urls, scripts
  3. <if frontend selected>
     run bin/setup/get-npm.ps1                (verifies Node, installs client/ deps if package.json exists)
     suggest frontend scaffolding command for chosen stack
  4. <if "Other" language selected>
     skip Python scaffolding; print manual setup notes for the chosen language
  5. update CLAUDE.md, AGENTS.md, .codex/AGENTS.md, .github/copilot-instructions.md,
     and README.md to replace template language with project-specific content

proceed? (yes / no)
```

If the user says no or asks for amendments, loop back to the relevant question.

### 3. Execute setup

On approval, run steps in order. Stop and report at the first failure - do not continue past an error.

#### 3a. Python setup (only if Python in `languages`)

```powershell
.\bin\setup\setup-project.ps1 -Name "<name>" -Python "<python_version>"
```

The script handles:
- `uv init --name <name> --package --python <python_version>`
- Patches `pyproject.toml` for dynamic versioning (setuptools + `VERSION` file).
- Patches `ruff.toml` (`namespace-packages`, `target-version`).
- Patches `ty.toml` (`python-version`).
- Adds dev dependencies (`ruff`, `ty`, `pytest`).
- Creates `.venv`.
- Renames `template-py-package.code-workspace` to `<folder-name>.code-workspace`.

#### 3b. Patch pyproject.toml (only if Python ran successfully)

After 3a, read `pyproject.toml` and append/modify the `[project]` table to include any of these the user provided:

- `license = "<license>"` (skip if `MIT` since uv may set it by default)
- `authors = [{ name = "<author_name>", email = "<author_email>" }]` (skip if either is blank)
- `[project.urls]` table with `Repository = "<repo_url>"` (skip if blank)
- `[project.scripts]` table with `<cli_command> = "<name>:main"` (only if `kind` is "CLI tool")

Be conservative - use a single Edit per field, and verify the file is still valid TOML after each change.

#### 3c. Frontend setup (only if TypeScript/JavaScript or HTML in `languages`)

```powershell
.\bin\setup\get-npm.ps1
```

The script verifies Node.js / npm and, if `client/package.json` exists, runs `npm install`. It does **not** scaffold a Vite or Electron project.

After it runs, tell the user how to scaffold their chosen stack:

| Stack                          | Suggested scaffolding command                                       |
|--------------------------------|---------------------------------------------------------------------|
| React + TypeScript + Vite      | `npm create vite@latest client -- --template react-ts`              |
| Electron + React + TypeScript  | `npm create @quick-start/electron@latest client -- --template react-ts` |
| Plain HTML / JS / CSS          | create `client/index.html` and supporting files manually            |
| Other                          | user-driven                                                         |

If `has_node` was "no" or "unsure", the `get-npm.ps1` script will provide installation guidance - surface that to the user.

#### 3d. Non-Python primary language (only if Python is NOT in `languages`)

Skip `setup-project.ps1` entirely. Tell the user:

- The template's build script (`bin/build.ps1`) assumes Python - they should remove or replace it.
- They need to add their own build configuration (`package.json`, `build.gradle`, `Cargo.toml`, `go.mod`, etc.) at the project root.
- The `.agents/`, `.claude/`, `.codex/`, `.windsurf/`, and `.github/` directories work for any language and can be kept as-is.
- The Python-specific style guide (`.agents/codestyles/python-style.md`) can be removed or kept for reference.

#### 3e. Update documentation

For each of these files, replace the template language with project-specific content. Use Edit (not Write) to preserve unmodified sections:

- `CLAUDE.md` - replace "Repository Overview" paragraph with `description`. Replace the "Template State" section with a single line stating the project is initialized.
- `AGENTS.md` - same edits as CLAUDE.md.
- `.codex/AGENTS.md` - same edits.
- `.github/copilot-instructions.md` - replace the opening overview line with `description`. Delete the "Template State" section entirely.
- `README.md` - replace the opening paragraph and "Features" section header with `description` and project-appropriate content. Remove the "Getting Started" section's "Option A - AI-assisted setup" subsection (the user is past that point). Keep the development commands, project structure, and module organization sections.

When updating each file:
1. Read the current content.
2. Make minimal targeted edits - preserve all sections that still apply (style guides, validation commands, module organization).
3. Do **not** delete the references to `.agents/skills/` - those remain useful post-initialization.

### 4. Verify

After all steps complete, verify each output and report a checklist to the user:

- [ ] `pyproject.toml` exists and contains the correct `name` (if Python)
- [ ] `pyproject.toml` `requires-python` matches `python_version` (if Python)
- [ ] `ruff.toml` `target-version` matches `python_version` (if Python)
- [ ] `ty.toml` `python-version` matches `python_version` (if Python)
- [ ] `.venv` directory exists (if Python)
- [ ] `license`, `authors`, `[project.urls]`, `[project.scripts]` are present in pyproject.toml (if requested)
- [ ] Node.js / npm verified or guidance printed (if frontend)
- [ ] Documentation files updated (`CLAUDE.md`, `AGENTS.md`, `.codex/AGENTS.md`, `.github/copilot-instructions.md`, `README.md`)
- [ ] Workspace file renamed to `<folder>.code-workspace` (if Python)

### 5. Next steps

Tell the user exactly what to do next. Tailor the message to their selections:

**Python-only project:**
- edit `src/<name>/__init__.py` to start your package
- run `uv run pytest` to verify the toolchain
- run `.\bin\build.ps1` to build a wheel
- commit the initialization: `git add -A && git commit -m "init: scaffold <name>"`

**Python + frontend:**
- everything above, plus
- scaffold the frontend with the command from the table in step 3c
- run the frontend's dev server to verify

**Frontend / static site only:**
- scaffold the frontend with the command from the table in step 3c
- remove `bin/build.ps1` or rewrite it for your stack
- commit the initialization

**Other language only:**
- add your build configuration at the project root
- remove or rewrite `bin/build.ps1`
- the `.agents/` skills (`bumpversion`, `grill-me`) still work for any project - they only touch `version.toml`, `CHANGELOG.md`, and conversation context

## Example Session

```
user: /project-setup

A: what are you building? give me a 1-2 sentence description.

user: a CLI for managing cloud infrastructure deployments across AWS and GCP

A: what should we call it? (default: <folder-name>)

user: cloudctl

A: which languages will it use? options:
  1. python
  2. typescript / javascript
  3. html / css only
  4. other (manual setup)
you can pick multiple.

user: python only

A: what kind of project? library, CLI tool, web service, frontend,
desktop, notebook, or mixed?

user: cli tool

A: python version? (default: 3.11)

user: 3.12

A: cli command name? (default: cloudctl)

user: cloudctl

A: license? (default: MIT - Apache-2.0, BSD-3-Clause, GPL-3.0,
MPL-2.0, proprietary are common alternatives)

user: MIT

A: author name? (optional - press enter to skip)

user: Jane Doe

A: author email?

user: jane@example.com

A: git remote URL? (optional)

user: https://github.com/janedoe/cloudctl

A:
  project setup summary

    description: a CLI for managing cloud infrastructure deployments across AWS and GCP
    name:        cloudctl
    languages:   python
    kind:        CLI tool
    python:      3.12
    cli command: cloudctl
    license:     MIT
    author:      Jane Doe <jane@example.com>
    repo:        https://github.com/janedoe/cloudctl

  actions:
    1. run bin/setup/setup-project.ps1 -Name "cloudctl" -Python "3.12"
    2. patch pyproject.toml with authors, urls, scripts
    3. update CLAUDE.md, AGENTS.md, .codex/AGENTS.md, .github/copilot-instructions.md, README.md

  proceed? (yes / no)

user: yes

A: [executes setup, patches pyproject.toml, updates docs, verifies, reports checklist, suggests next steps]
```

## Edge Cases

- **Non-Python primary language:** skip `setup-project.ps1` entirely. Warn the user that `bin/build.ps1` assumes Python and should be removed or rewritten.
- **No frontend chosen but `client/` already exists:** ask whether to keep, archive, or delete it before proceeding.
- **`uv.exe` missing:** `setup-project.ps1` auto-runs `bin/setup/get-uv.ps1` to vendor it. If that fails, stop and report the error.
- **Git not in a clean state:** `setup-project.ps1` creates an `init-project` branch. If there are uncommitted changes, warn the user before running so they can stash or commit first.
- **Project name conflicts with a Python keyword or stdlib name:** warn the user (e.g. `json`, `os`, `class`, `import` would all be problems). Suggest a prefix or suffix.
- **Setup script fails partway through:** read the error, surface it to the user, and do not attempt to "fix" partial state. Tell them whether to clean up manually or to retry after fixing the underlying cause.
