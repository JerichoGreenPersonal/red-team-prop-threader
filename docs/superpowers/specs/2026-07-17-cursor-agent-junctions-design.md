# Cursor Agent Junctions Design

## Goal

Expose the repository's canonical agent configuration to Cursor without maintaining duplicate
copies. `.agents` remains the source of truth for agents, rules, and skills, while Cursor discovers
the same content under `.cursor`.

## Design

Create three local Windows directory junctions:

- `.cursor/agents` → `.agents/agents`
- `.cursor/rules` → `.agents/rules`
- `.cursor/skills` → `.agents/skills`

Keep `.cursor/workflows` as a normal tracked directory. Add all three junction paths to
`.gitignore`, because the junctions are workstation-local filesystem objects. Do not add a setup or
recreation script; a fresh clone requires manual junction creation.

Before creating `.cursor/rules`, reconcile `.agents/rules/git-workflow.md` with the repository's
existing main-based workflow. Preserve the richer `.agents/rules/vcs-safety.md`, including its
session-scoped auto-commit grant and prohibition on AI attribution.

The existing tracked duplicate files under `.cursor/rules` will be removed from version control.
The directory must then be removed locally before the junction can be created at the same path.

## Alternatives Considered

### Copy canonical content into `.cursor`

This requires synchronization and allows the copies to drift. The current conflicting Git workflow
rules demonstrate that risk, so this approach is rejected.

### Use symbolic links

Symbolic links provide similar behavior but can require Windows Developer Mode or elevated
permissions. Directory junctions work locally without those requirements and are preferred.

### Use directory junctions

Junctions provide one canonical copy, work well for local directories on Windows, and are
transparent to Cursor. This is the selected approach.

## Safety and Failure Handling

- Preserve all unrelated modified and untracked files.
- Verify each canonical `.agents` target exists before creating its junction.
- Stop if any target `.cursor` path still exists after the tracked duplicate cleanup; never overwrite
  an unexpected file or directory.
- If junction creation fails, leave the canonical `.agents` content untouched and report the failed
  path.
- Do not commit, push, or merge without the approval required by the VCS safety rule.

## Verification

After creation:

1. Confirm `.cursor/agents`, `.cursor/rules`, and `.cursor/skills` are directory junctions pointing
   to the intended `.agents` directories.
2. Confirm representative files are visible through both canonical and Cursor paths.
3. Confirm `.cursor/workflows` is unchanged.
4. Confirm Git ignores all three junction paths and records deletion of only the former duplicate
   `.cursor/rules` files.
5. Confirm the reconciled Git workflow rule is main-based and the richer VCS safety rule remains
   intact.

## Scope

This change only establishes local Cursor discovery paths and reconciles duplicate rules. It does
not initialize the Python project, implement RED Team Prop Threader, create the product worktree, or
add cross-platform junction automation.
