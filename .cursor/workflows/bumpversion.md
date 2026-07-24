---
description: Bump the project version and generate a CHANGELOG entry from recent git history
---

Follow the bumpversion skill at `.agents/skills/bumpversion/SKILL.md` exactly.

## Steps

1. Read `.agents/skills/bumpversion/SKILL.md` in full to load the skill instructions.

2. If the user has not specified a bump type (patch / minor / major), ask them now.

3. Read `version.toml` to get the current version.

4. Run the following git command to gather commits since the last version bump:
   ```
   git log --oneline --format="%h %s" $(git log -1 --format=%H -- version.toml)..HEAD
   ```

5. Draft the changelog entry following the skill style rules (lowercase, no hype, area references, past tense). Compute the new version by incrementing the chosen segment and resetting lower segments to 0.

6. Present the new version number and the drafted changelog entry to the user. Wait for explicit approval or amendments before writing anything.

7. On approval:
   a. Update `version.toml` with the new `major`, `minor`, `patch` integers.
   b. Prepend the new entry to `CHANGELOG.md` (after any header line).
// turbo
   c. Run `python scripts/version.py` to regenerate the `VERSION` file.

8. Read back `version.toml`, the top of `CHANGELOG.md`, and `VERSION` to confirm all three are consistent.
