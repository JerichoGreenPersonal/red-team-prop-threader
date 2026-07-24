# VCS Safety

Always require explicit user confirmation before executing any of the following version control commands. These commands must never be auto-executed regardless of auto-execution level settings:

- `git push` (any variant, including `--force`)
- `git commit` (any variant)
- `gh pr merge` (any variant)

Present the exact command to the user and wait for approval before proceeding.
