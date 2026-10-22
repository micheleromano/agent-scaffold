@AGENTS.md

## Claude Code

`AGENTS.md` above is shared with every coding agent. This section adds what's specific to Claude Code.

- **Rules** in `.claude/rules/` load when you work on matching files; `humane-design.md` always loads.
- **Skills:** `/plan` before building anything non-trivial, `/review` to check the current changes, `/ship` to test, commit and open a PR, `/ci` to run the checks on GitHub on every push.
- **Subagents** in `.claude/agents/`: `humane-design-reviewer` for anything people see or use, `code-reviewer`, `test-writer`.
- **Hooks** in `.claude/hooks/` block destructive shell commands and format each file after you edit it. If a hook blocks something, tell the user rather than working around it.
