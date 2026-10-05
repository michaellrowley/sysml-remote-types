---
name: regression-tests
description: Use for bug fixes, behavior changes, refactors, and new features. Add focused regression tests and verify the changed behavior, not just that code compiles.
---

# Regression tests

Treat tests as part of the implementation, not optional cleanup:

- Before changing behavior, identify the existing test runner, relevant tests,
  and the observable behavior that needs to change.
- For a bug, add a regression test that fails for the reported case before the
  fix and passes afterward. For a feature, cover its primary success path and
  important failure or boundary cases.
- Update tests whenever the intended behavior changes. Avoid tests that merely
  mirror implementation details or assert only that a function was called.
- Run the narrowest relevant test selection after each coherent change. Before
  finishing, run the smallest suite that covers all changed behavior and report
  any tests that could not be run.
- Do not weaken, skip, or delete a failing test just to get a green run. Fix the
  underlying issue or explain why the result is blocked.
- For documentation-only changes, do not add artificial tests unless the
  repository has documentation checks.
