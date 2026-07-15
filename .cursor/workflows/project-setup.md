---
description: Initialize this template into a real project — interviews the user, runs setup scripts, patches config, and updates documentation
---

Follow the project-setup skill at `.agents/skills/project-setup/SKILL.md` exactly.

## Steps

1. Read `.agents/skills/project-setup/SKILL.md` in full to load the skill instructions.

2. Check if `pyproject.toml` exists. If it does, tell the user the project is already initialized and stop.

3. Interview the user **one question at a time**, gathering:
   - **description** — what are they building (1-2 sentences)
   - **name** — project name (default: folder name, no spaces)
   - **languages** — Python, TypeScript/JS, HTML, Other (multi-select)
   - **kind** — library, CLI tool, web service, web frontend, desktop, notebook, mixed
   - **python_version** — only if Python selected (default: 3.11)
   - **cli_command** — only if kind is CLI tool (default: name)
   - **frontend_stack** — only if TS/JS or HTML selected (React+Vite, Electron, plain HTML, other)
   - **has_node** — only if frontend selected
   - **license** — default MIT
   - **author_name**, **author_email** — optional
   - **repo_url** — optional

4. Present the setup summary and wait for explicit user approval.

5. On approval, execute in order (stop at the first failure):
   a. **If Python selected:** run
      ```powershell
      .\bin\setup\setup-project.ps1 -Name "<name>" -Python "<python_version>"
      ```
   b. **If Python selected and license/author/repo/cli provided:** patch `pyproject.toml` to add `license`, `authors`, `[project.urls]`, `[project.scripts]`.
   c. **If frontend selected:** run
      ```powershell
      .\bin\setup\get-npm.ps1
      ```
      then tell the user the scaffolding command for their stack (e.g. `npm create vite@latest client -- --template react-ts`).
   d. **If "Other" language only:** skip Python scaffolding entirely. Warn that `bin/build.ps1` assumes Python and should be removed or rewritten.
   e. Update `CLAUDE.md`, `AGENTS.md`, `.codex/AGENTS.md`, `.github/copilot-instructions.md`, and `README.md` to replace template language with the project description and remove the "Template State" sections.

6. Verify each output and report a checklist to the user. Suggest tailored next steps based on their selections.
