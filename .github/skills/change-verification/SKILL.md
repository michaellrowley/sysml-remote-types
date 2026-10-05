---
name: change-verification
description: Use before declaring repository work complete. Verify the requested outcome, inspect the final diff, and leave unrelated or unverified changes untouched.
---

# Change verification

Close the loop on every task:

- Translate the request into observable acceptance criteria and check each
  criterion against the actual implementation.
- Follow affected call paths and user-facing surfaces so related entry points
  behave consistently; update directly related documentation.
- Run applicable tests, linters, type checks, or builds using the repository's
  existing tools. Prefer targeted checks, then broaden only when needed.
- Inspect the final diff and `git status`. Catch accidental files, unrelated
  edits, generated artifacts, whitespace errors, and changes that were not
  covered by validation.
- Never claim a check passed unless it completed successfully. State remaining
  uncertainty or blockers plainly.
