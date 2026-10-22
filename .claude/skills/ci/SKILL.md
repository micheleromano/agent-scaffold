---
name: ci
description: "Set up CI for agent-scaffold: a GitHub Actions workflow that runs its checks on every push and pull request, plus a status badge"
disable-model-invocation: true
---

Set up continuous integration so the checks run on every push and pull request, and add a status badge to the README.

1. Look in `.github/workflows/`. If a workflow already runs these checks, show it and ask whether to update it instead of adding another.
2. Take the commands from `AGENTS.md`: install `uv sync`, lint `uv run ruff check .`, test `uv run pytest`. If the test or lint command is missing, ask the user how CI should verify the code.
3. Write `.github/workflows/ci.yml`:
   - `name: ci`; run on pushes to the default branch and on pull requests.
   - `permissions: contents: read`.
   - One job on `ubuntu-latest`: check out the code, set up the toolchain with its official setup action (with dependency caching where it offers it), then install, lint and test. Use the language version the project declares (e.g. `.python-version`, `engines` in `package.json`, `go.mod`).
   - Look up the latest release of every action you use (`gh api repos/<owner>/<action>/releases/latest --jq .tag_name`) and reference its major version tag (e.g. `@v7`) if the action publishes one (`gh api repos/<owner>/<action>/git/ref/tags/v7`); otherwise use the full release tag. Don't use versions you remember, and don't write them anywhere else.
   - Never put secret values in the workflow. If a check needs one, reference `${{ secrets.NAME }}` and tell the user to add it under Settings → Secrets and variables → Actions.
4. Add a badge under the title of `README.md` (create the README if there isn't one):
   `[![ci](https://github.com/<owner>/<repo>/actions/workflows/ci.yml/badge.svg)](https://github.com/<owner>/<repo>/actions/workflows/ci.yml)`
   Get `<owner>/<repo>` from `gh repo view --json nameWithOwner` or `git remote -v`. If there's no GitHub remote yet, skip the badge and say it can be added once the repository is on GitHub.
5. If `actionlint` is installed, run it on the workflow. Show the user the workflow and the badge, and **wait for their go-ahead** before committing. After it's pushed, run `gh run watch` and report whether the checks pass.
