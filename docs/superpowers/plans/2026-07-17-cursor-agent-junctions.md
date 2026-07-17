# Cursor Agent Junctions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Cursor consume the canonical agents, rules, and skills in `.agents` through local Windows directory junctions.

**Architecture:** `.agents` remains the tracked source of truth. Three ignored `.cursor` directory junctions expose that content locally, while `.cursor/workflows` remains a normal tracked directory. The conflicting Git workflow rule is reconciled before the duplicate tracked Cursor rules are removed.

**Tech Stack:** Git, Markdown, PowerShell 7, Windows directory junctions.

## Global Constraints

- Preserve every unrelated modified and untracked file.
- Keep `.agents` as the canonical source for agents, rules, and skills.
- Keep `.cursor/workflows` tracked and unchanged.
- Create `.cursor/agents`, `.cursor/rules`, and `.cursor/skills` as local Windows directory junctions.
- Ignore all three junction paths in Git.
- Do not add a junction setup or recreation script.
- Keep the main-based Git workflow and the richer VCS safety rule.
- Obtain explicit approval before each `git commit`; obtain separate approval before any push or merge.

---

## Planned File Structure

- Modify: `.agents/rules/git-workflow.md` — canonical main-based branch and PR workflow.
- Modify: `.gitignore` — ignores the three local Cursor projection paths.
- Delete: `.cursor/rules/git-workflow.md` — obsolete tracked duplicate.
- Delete: `.cursor/rules/vcs-safety.md` — obsolete tracked duplicate.
- Local only: `.cursor/agents` — junction to `.agents/agents`.
- Local only: `.cursor/rules` — junction to `.agents/rules`.
- Local only: `.cursor/skills` — junction to `.agents/skills`.
- Preserve: `.cursor/workflows` — tracked Cursor workflows.

### Task 1: Reconcile Canonical Rules and Ignore Local Projections

**Files:**
- Modify: `.agents/rules/git-workflow.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: the main-based workflow body currently in `.cursor/rules/git-workflow.md`.
- Produces: one main-based canonical Git workflow and ignore rules required before junction creation.

- [ ] **Step 1: Verify the source rules and junction targets**

Run:

```powershell
$required = @(
    '.cursor\rules\git-workflow.md',
    '.agents\agents',
    '.agents\rules',
    '.agents\skills'
)
foreach ($path in $required) {
    if (-not (Test-Path $path)) {
        throw "Required path is missing: $path"
    }
}
```

Expected: command exits successfully with no output.

- [ ] **Step 2: Replace the conflicting canonical workflow body**

Run:

```powershell
$body = Get-Content '.cursor\rules\git-workflow.md' -Raw
$frontmatter = @'
---
description: Git branching model and workflow rules
alwaysApply: true
---

'@
Set-Content '.agents\rules\git-workflow.md' ($frontmatter + $body) -NoNewline
```

Expected: `.agents/rules/git-workflow.md` retains its canonical frontmatter and now describes direct, PR-based branches into `main`, with no `develop` branch.

- [ ] **Step 3: Add the local junction paths to `.gitignore`**

Append this exact block after the existing local-tool entries:

```gitignore
# Local Cursor projections of canonical agent configuration
.cursor/agents/
.cursor/rules/
.cursor/skills/
```

- [ ] **Step 4: Verify rule reconciliation and ignore coverage**

Run:

```powershell
$difference = Compare-Object `
    (Get-Content '.cursor\rules\git-workflow.md') `
    (Get-Content '.agents\rules\git-workflow.md' | Select-Object -Skip 5)
if ($difference) {
    $difference | Format-Table
    throw 'Canonical workflow body does not match the approved main-based rule.'
}
if (Select-String -Path '.agents\rules\git-workflow.md' -Pattern '\bdevelop\b') {
    throw 'Canonical workflow still references develop.'
}
git check-ignore -v --no-index .cursor/agents/ .cursor/rules/ .cursor/skills/
```

Expected: no comparison error and three `.gitignore` matches, one for each `.cursor` path.

- [ ] **Step 5: Review and commit the canonical configuration**

Run:

```powershell
git diff --check
git diff -- .agents/rules/git-workflow.md .gitignore
git status --short
```

Expected: no whitespace errors; the working tree diff contains only the intended canonical workflow and ignore additions for this task. After presenting the exact command and receiving approval:

```powershell
git add .agents/rules/git-workflow.md .gitignore
git commit -m "chore: canonicalize Cursor agent configuration"
```

### Task 2: Replace Tracked Duplicates with Local Junctions

**Files:**
- Delete: `.cursor/rules/git-workflow.md`
- Delete: `.cursor/rules/vcs-safety.md`
- Create locally: `.cursor/agents`
- Create locally: `.cursor/rules`
- Create locally: `.cursor/skills`
- Preserve: `.cursor/workflows`

**Interfaces:**
- Consumes: canonical `.agents` directories and Task 1 ignore rules.
- Produces: three local Cursor discovery paths backed directly by canonical content.

- [ ] **Step 1: Record workflow state and check destination safety**

Run:

```powershell
$workflowStatusBefore = git status --short -- .cursor/workflows
if ($workflowStatusBefore) {
    throw ".cursor/workflows is unexpectedly modified:`n$workflowStatusBefore"
}
foreach ($path in @('.cursor\agents', '.cursor\skills')) {
    if (Test-Path $path) {
        throw "Junction destination already exists: $path"
    }
}
$rulesItem = Get-Item '.cursor\rules'
if ($rulesItem.LinkType) {
    throw '.cursor\rules is already a link; expected the tracked duplicate directory.'
}
```

Expected: command exits successfully with no output.

- [ ] **Step 2: Remove the tracked duplicate rules**

Run:

```powershell
git rm '.cursor\rules\git-workflow.md' '.cursor\rules\vcs-safety.md'
if (Test-Path '.cursor\rules') {
    Remove-Item '.cursor\rules'
}
```

Expected: `.cursor/rules` no longer exists; Git stages deletion of its two tracked files. Removing
the files from the index before junction creation prevents Git from treating the projected canonical
files as modifications to the former tracked duplicates.

- [ ] **Step 3: Create the local directory junctions**

Run:

```powershell
$junctions = @{
    '.cursor\agents' = (Resolve-Path '.agents\agents').Path
    '.cursor\rules'  = (Resolve-Path '.agents\rules').Path
    '.cursor\skills' = (Resolve-Path '.agents\skills').Path
}
foreach ($entry in $junctions.GetEnumerator()) {
    if (Test-Path $entry.Key) {
        throw "Refusing to overwrite existing path: $($entry.Key)"
    }
    New-Item -ItemType Junction -Path $entry.Key -Target $entry.Value | Out-Null
}
```

Expected: all three commands succeed without modifying canonical `.agents` content.

- [ ] **Step 4: Verify junction targets, projected files, and workflow preservation**

Run:

```powershell
$expected = @{
    '.cursor\agents' = (Resolve-Path '.agents\agents').Path
    '.cursor\rules'  = (Resolve-Path '.agents\rules').Path
    '.cursor\skills' = (Resolve-Path '.agents\skills').Path
}
foreach ($entry in $expected.GetEnumerator()) {
    $item = Get-Item $entry.Key
    if ($item.LinkType -ne 'Junction') {
        throw "$($entry.Key) is not a directory junction."
    }
    if ($item.Target[0] -ne $entry.Value) {
        throw "$($entry.Key) targets '$($item.Target[0])', expected '$($entry.Value)'."
    }
}
if (-not (Test-Path '.cursor\rules\git-workflow.md')) {
    throw 'Canonical Git workflow is not visible through the Cursor junction.'
}
if (-not (Test-Path '.cursor\rules\vcs-safety.md')) {
    throw 'Canonical VCS safety rule is not visible through the Cursor junction.'
}
if (git status --short -- .cursor/workflows) {
    throw '.cursor/workflows changed during junction creation.'
}
git check-ignore -v --no-index .cursor/agents/ .cursor/rules/ .cursor/skills/
git status --short
```

Expected: all junction assertions pass, representative canonical rules are visible through `.cursor/rules`, workflows remain clean, all three junctions are ignored, and Git reports only the two tracked `.cursor/rules` deletions from this task alongside pre-existing user changes.

- [ ] **Step 5: Review and commit removal of tracked duplicates**

Run:

```powershell
git diff --check --cached
git diff --cached -- .cursor/rules/git-workflow.md .cursor/rules/vcs-safety.md
git status --short
```

Expected: no whitespace errors and only the two obsolete tracked rule files are staged for this task. After presenting the exact command and receiving approval:

```powershell
git commit -m "chore: project agent config into Cursor"
```

- [ ] **Step 6: Perform final repository verification**

Run:

```powershell
git diff --check
git status --short
Get-ChildItem '.cursor' -Force | Select-Object Name,Attributes,LinkType,Target
```

Expected: `.cursor/agents`, `.cursor/rules`, and `.cursor/skills` show `LinkType` `Junction`; `.cursor/workflows` remains a normal directory; no new whitespace errors exist; unrelated pre-existing user changes remain untouched.
