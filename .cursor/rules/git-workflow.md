# Git Workflow

Merges to `main` trigger production deploys. Branch hygiene is not optional.

## Branching Model

```
main (production)
  ^
  +-- feature/<name>
  +-- bugfix/<name>
  +-- hotfix/<name>
  +-- chore/<name>
```

- `main` -- production. CI builds and deploys on every merge.
- Working branches use a purpose prefix: `feature/`, `bugfix/`, `hotfix/`, `chore/`.

## Hard Rules

1. **Never push or merge directly to `main`.** All work goes through a PR, except genuine hotfixes (PR'd, with user approval).
2. **Always PR feature branches into `main`.** Path is always `feature/* -> main`.
3. **Branch off `main` for all new work.** Use the appropriate purpose prefix.
4. **Always use Pull Requests.** PRs give build checks, history, and rollback points. No direct commits to `main`.
5. **Merging requires explicit user approval.** The agent can open PRs and push to feature branches freely, but merging a PR needs user confirmation.

## Merge Strategy

**feature/bugfix/chore/\* -> main: squash and merge.**
Each PR becomes one atomic commit on main. Clean per-feature history,
easy to revert a whole change with a single `git revert`.

To revert a merged PR on main:

```bash
git revert <squash-commit-hash>
```

## Branch Naming

Short, kebab-case, descriptive. Examples:

- `feature/slack-scraper`
- `bugfix/taxonomy-sync-drift`
- `chore/upgrade-uv`
- `hotfix/indexer-crash-on-empty-chunk`

## Standard Workflow

New work:

```bash
git checkout main && git pull origin main
git checkout -b feature/<short-name>
# work, commit as you go
git push -u origin feature/<short-name>
# open PR targeting main
```

Keeping a feature branch fresh:

```bash
git checkout feature/<name>
git merge main
```

Prefer `merge` over `rebase` on shared branches. Rebase is fine on solo branches.

## What Goes Where

- **Unfinished work** stays on its feature branch. Do not merge half-done features into `main`.
- **Experimental work** stays on its branch or goes behind a feature flag.
- **Multiple features in flight** each get their own branch, each PR to `main` independently.

## Release Cycle

Each feature ships independently via a PR directly to `main`. CI runs on merge and triggers production deploys.

Before merging any PR to `main`, confirm: CI is green and the user has reviewed the change.

## When Unsure

Ask the user before:

- Force-pushing anything
- Merging any PR to `main`
- Deleting branches
- Touching CI config files

## Quick Reference

| Situation       | Action                                                |
| --------------- | ----------------------------------------------------- |
| New feature     | Branch off `main`, PR to `main`                       |
| Bug fix         | `bugfix/*` off `main`, PR to `main`                   |
| Urgent prod bug | `hotfix/*` off `main`, PR to `main` -- ask user first |
| Branch behind   | `git merge main` into the feature branch              |
