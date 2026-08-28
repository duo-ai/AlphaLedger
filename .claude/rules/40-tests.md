---
paths:
  - "tests/**/*.py"
---

# Test rules

- Prefer deterministic unit and contract tests. Networked Alpaca calls belong
  only in separately marked paper integration tests.
- A test name states the invariant and failure condition, not the function name.
- Freeze time and broker responses. Avoid sleeps, wall-clock dependence, and
  tests whose outcome depends on the current market session.
- Test the no-trade and fail-closed paths with the same rigor as filled orders.
- Each regression test must fail against the defect it protects against.
- Paper integration tests are opt-in, capped, and require an explicit
  acknowledgement; they must never be part of the default test suite.
- Never use production-like secrets or record unredacted HTTP fixtures.
