---
name: review
description: "Review the current changes in agent-scaffold for bugs, missing tests and convention violations"
disable-model-invocation: true
---

Review the uncommitted changes (`git diff HEAD`) in this project.

1. Read CLAUDE.md and the rules in `.claude/rules/` that match the changed files.
2. Look for correctness bugs first, then missing or weakened tests, then convention violations.
3. Run `uv run pytest` and report any failures.

Report findings as a short list, most severe first, each with file:line and a concrete fix.
