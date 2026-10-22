---
name: ship
description: "Ship the current changes in agent-scaffold: run checks, review, then commit, push and open a PR after the user confirms"
disable-model-invocation: true
---

Ship the current changes. Stop and report at the first failure.

1. Run `git status` and `git diff HEAD`. If there are no changes, say so and stop. If you're on the default branch, propose a branch name and ask before creating it.
2. Lint: `uv run ruff check .`
3. Test: `uv run pytest`
4. Review the diff for bugs and leftover debug code. If the change affects anything people see or use, run the `humane-design-reviewer` subagent, and run the `code-reviewer` subagent on larger changes.
5. Draft a commit message: a short summary line, then why the change was made.
6. Show the user the checks you ran, the review findings and the message. **Wait for their go-ahead** before you commit, push or open a PR.
7. Commit, push, and open a pull request (`gh pr create` if the GitHub CLI is installed). Reply with the PR link.
