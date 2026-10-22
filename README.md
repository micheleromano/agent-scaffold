# agent-scaffold

Answer a few questions about a project and get a working Claude Code setup: instructions, permissions, MCP connections, path-scoped rules, a review skill, subagents and safety hooks.

```
uv run agent-scaffold init path/to/project
```

## What it writes

| File | Purpose |
| --- | --- |
| `AGENTS.md` | Project overview, stack, commands, architecture, conventions and working principles, in the open [AGENTS.md](https://agents.md) format other coding agents read too |
| `CLAUDE.md` | Imports `AGENTS.md` (`@AGENTS.md`), then adds what's specific to Claude Code |
| `CLAUDE.local.md` | Your machine-specific notes; gitignored |
| `.mcp.json` | Shared MCP servers (GitHub, Sentry, Notion, Slack, Playwright) |
| `.claude/settings.json` | Allows your test/lint/dev commands, denies reading `.env`, wires up hooks |
| `.claude/rules/*.md` | Code-style and testing rules scoped with `paths:` to the files they cover, plus conventions for the project's role (see below) |
| `.claude/skills/*/SKILL.md` | `/plan` before building, `/review` the current diff, `/ship` (checks, review, then commit and PR once you confirm), and `/choose-stack` when the stack isn't decided |
| `.claude/rules/humane-design.md` | Always: the Center for Humane Technology's principles as concrete guardrails (see below) |
| `.claude/agents/humane-design-reviewer.md` | Always: reviews a diff against all seven principles |
| `.claude/agents/*.md` | Optional code reviewer, security auditor and test writer subagents |
| `.claude/hooks/*.py` | Block destructive shell commands; format files after every edit |
| `.gitignore` | Adds `CLAUDE.local.md` and `.claude/settings.local.json` (merged, never replaced) |

Formats follow the current [Claude Code docs](https://code.claude.com/docs). Custom commands now live in skills, and hooks are configured in `settings.json`, so there is no separate `commands/` directory.

## One file for every agent

The project context lives in `AGENTS.md`, so Codex, Cursor and other agents that read the format get the same instructions as Claude. `CLAUDE.md` starts with `@AGENTS.md`, which Claude Code needs: it skips a standalone `AGENTS.md` whenever a `CLAUDE.md` or `CLAUDE.local.md` exists ([docs](https://code.claude.com/docs/en/memory)). If your project already has a `CLAUDE.md`, the CLI offers to move it into `AGENTS.md` and add the import for you.

## How agents work

`AGENTS.md` includes five working principles. The first four are adapted from [Andrej Karpathy's notes on LLM coding mistakes](https://x.com/karpathy/status/2015883857489522876), as collected in [andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills); the fifth comes from the humane design principles below:

1. **Think before coding:** state assumptions, surface ambiguity, ask when unclear.
2. **Keep it simple:** the least code that solves the problem.
3. **Make surgical changes:** every changed line traces back to the request.
4. **Work toward a verifiable goal:** turn tasks into checks and loop until they pass.
5. **Keep people in control:** ask before irreversible or outward-facing actions; report what was and wasn't verified.

## Humane design guardrails

Every project gets guardrails adapted from the Center for Humane Technology's [Principles of Humane Technology](https://www.humanetech.com/humane-product-design). The seven principles are values, so the rule turns each one into something Claude can act on:

- **What gets built:** flag dark patterns (infinite scroll, streaks, false urgency, hard opt-outs) before adding them; pair engagement analytics with a user-outcome metric; minimal data with easy export and deletion; WCAG 2.2 AA; label AI-generated and ranked content.
- **How agents work with you:** covered by principle 5 above, in `AGENTS.md`, so it applies to every agent.

Claude names a conflict and suggests an alternative instead of refusing; you decide. The `humane-design-reviewer` subagent checks a diff against all seven principles.

They are always on, not an interview question: in projects with nothing user-facing, the rule costs only a few hundred tokens of context. To opt out, delete the files; that should be a deliberate choice.

## Roles

The interview asks what kind of project it is, and each role adds a rule of conventions for that purpose and pre-selects a sensible stack and subagents:

| Role | Conventions |
| --- | --- |
| Backend / API | input validation, one error shape, authorization on every endpoint, versioned responses, append-only migrations |
| Frontend | WCAG 2.2 AA, loading, empty and error states, no secrets in client code, reuse the design system |
| Full-stack | both of the above |
| Data pipeline | idempotent jobs, migrations, contract validation with quarantine, dry-run backfills, PII handling, lineage |
| LLM / AI service | prompts as files, pinned models, evals before every prompt or model change, model output as untrusted input, prompt-injection separation, cost and latency tracking, AI labeling |
| Background worker | safe retries, backoff and dead-letter queues, timeouts, traceable logs |
| Other | none |

## Systems with several services

Answer "A system of several services" to the first question and agent-scaffold sets up a **workspace**: a backend, a data pipeline, an LLM service and so on, either as one monorepo or as separate repositories side by side.

```
acme/
  agent-scaffold.workspace.json   the blueprint: goal, layout, services, shared choices (commit it)
  AGENTS.md                       the goal, a services table, how they talk, contracts, rules for every service
  CLAUDE.md, .claude/             cross-service /plan and /review, /new-service
  backend/  data/  llm/           each a complete setup for its role, starting with "Part of acme. Goal: ..."
```

- **One goal, everywhere.** The root `AGENTS.md` states it, and every service's `AGENTS.md` repeats it in a system section, so a service cloned on its own still knows what it's for. Claude Code also loads the root `CLAUDE.md` in any service session, because it reads `CLAUDE.md` from every parent folder.
- **Each service is set up for its purpose** through its role, and stands alone: settings and skills aren't inherited across repositories, so each service gets its own `.claude/`.
- **Separate repositories:** the workspace is a small repository whose `.gitignore` excludes the service folders.
- **Services can come later.** Start with just the goal and no services; the services table says so until the first one is added.
- **New services follow the blueprint.** `agent-scaffold add-service <folder>` asks for the role, stack and commands, adds the service to the manifest, writes its setup, and refreshes the root services table and `/review` skill. The root `AGENTS.md` tells every agent to add services this way, never by hand.

Sections that depend on the list of services (the services table, the `/review` service list, each service's "Part of" section) are wrapped in `<!-- agent-scaffold:name -->` markers. `init` and `add-service` refresh what's between them; everything else in the file is yours.

## Any stack

Presets fill in default test, lint and format commands for TypeScript/JavaScript, Python, Go, Rust, Java/Kotlin, C#, Ruby, PHP and Swift. For any other language, tick "Other (not listed)" and enter its file extensions (e.g. `ex, exs` for Elixir, `html, css` for a static site); rules and hooks are then scoped to those files. Every command can be edited or left blank, and blank answers are left out of the output.

Don't know the stack yet? Answer "no" to "Do you know which languages it will use?" and the interview skips the language and command questions. `AGENTS.md` records the stack as not decided, and a `/choose-stack` skill asks Claude to explore the idea with you, propose 2 or 3 stacks with trade-offs, and, once you pick, fill in the stack, commands, rule paths and permissions.

The generated hooks are standard-library Python scripts, so the machine running Claude Code needs `python3` on its PATH (preinstalled on macOS and most Linux distributions).

## Options

- **Nothing is written until you confirm.** Every run ends with the list of files it would create, merge or skip, then asks "Write these files?" Say no to just preview.
- **Your answers are saved** per project folder in `~/.local/state/agent-scaffold/`, never in the project itself. The next run for that folder shows them and asks whether to use them as they are, edit them (every question starts with your previous answer, so Enter keeps it), or start over.
- **Existing files are never overwritten without asking.** For each generated file that already exists with different contents, you choose: keep yours, replace it, or see the diff first. For an existing `CLAUDE.md` there's a fourth option: move it into `AGENTS.md` (followed by the working principles) and replace `CLAUDE.md` with one that imports it, so your instructions reach every agent. `--yes` keeps every existing file; `--force` replaces them all.
- `--save-answers answers.json` also saves a copy you can share; `--answers answers.json` replays it without the interview. Add `--yes` to write without the confirmation prompt, for scripts.

## Design

`generate.py` turns `Answers` (one project) or a `Workspace` (several services) into a list of files, and `refresh_blocks` updates the marked sections of existing files through a reader function. Neither touches the file system, so the CLI and the planned web API share them.

```
src/agent_scaffold/
  models.py     # Answers + catalogs (stacks, MCP servers, agents)
  generate.py   # Answers -> files (pure)
  writer.py     # plan + write: create / merge / skip / overwrite
  cli.py        # interview (questionary) + Typer command
  templates/    # Jinja2 templates
```

## Development

```
uv sync
uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest
```

ruff lints and formats, mypy runs in strict mode, and pytest reports coverage (100%). The tests render every stack preset and check each file's structure. They also run the generated hook scripts against real commands, and drive the interview with scripted answers.

This repo's own `AGENTS.md`, `CLAUDE.md` and `.claude/` were generated by `agent-scaffold` from `agent-scaffold.json`, then edited by hand.

## Roadmap

- FastAPI service on Cloudflare Python Workers, returning a preview and a .zip
- Next.js wizard on Cloudflare
- D1 database for saved presets and usage stats
- Optional Cohere-drafted `AGENTS.md` from your answers
