---
name: incremental-commits
description: Use when implementing repository changes. Keep completed work in small, verified, task-scoped commits instead of accumulating one large final commit.
---

# Incremental commits

Keep the branch reviewable throughout implementation:

- Inspect `git status` before changing or staging anything. Preserve pre-existing
  user changes and never include them in a commit unless the user explicitly
  asks.
- Commit each independently reviewable milestone once its relevant checks pass;
  do not wait until the entire task is finished to create one oversized commit.
- Keep each commit focused on one behavior, fix, or closely related set of
  files. Include tests and directly related documentation with the change they
  verify or describe.
- Stage explicit task-owned paths rather than using `git add .` or
  `git add -A`. Inspect the staged diff before committing.
- Use a clear imperative commit subject. Do not amend existing commits, rewrite
  history, or push unless the user asks.
- If a milestone cannot be verified, do not present its commit as verified;
  explain the blocker and leave the work in a state that can be reviewed.
