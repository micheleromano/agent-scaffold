---
paths:
  - "tests/**/*.py"
  - "**/test_*.py"
---

# Testing

- Run tests with `uv run pytest`; run the relevant tests after every change.
- Every bug fix gets a test that fails without the fix.
- Test behavior through public interfaces, not implementation details.
- Never weaken or delete an assertion to make a test pass; report the failure instead.
