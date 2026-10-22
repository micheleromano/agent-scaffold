# agent-scaffold

[![ci](https://github.com/micheleromano/agent-scaffold/actions/workflows/ci.yml/badge.svg)](https://github.com/micheleromano/agent-scaffold/actions/workflows/ci.yml)

Answer a few questions about a project and get a working Claude Code setup: instructions, permissions, path-scoped rules, a review skill, subagents and safety hooks.

```
uv run agent-scaffold init path/to/project
```

## What it writes

| File | Purpose |
| --- | --- |
| `AGENTS.md` | Project overview, stack, commands, architecture, conventions and working principles, in the open [AGENTS.md](https://agents.md) format other coding agents read too |
| `CLAUDE.md` | Imports `AGENTS.md` (`@AGENTS.md`), then adds what's specific to Claude Code |
| `CLAUDE.local.md` | Your machine-specific notes; gitignored |
| `.claude/settings.json` | Allows your test/lint/dev commands, denies reading `.env`, wires up hooks |
| `.claude/rules/*.md` | Code-style and testing rules scoped with `paths:` to the files they cover, plus conventions for the project's role (see below) |
| `.claude/skills/*/SKILL.md` | `/plan` before building, `/review` the current diff, `/ship` (checks, review, then commit and PR once you confirm), `/ci` (a GitHub Actions workflow and status badge, using the action versions current when it runs), and `/choose-stack` when the stack isn't decided |
| `.claude/rules/humane-design.md` | Always: the Center for Humane Technology's principles as concrete guardrails (see below) |
| `.claude/agents/humane-design-reviewer.md` | Always: reviews a diff against all seven principles |
| `.claude/agents/*.md` | Optional code reviewer, security auditor and test writer subagents |
| `.claude/hooks/*.py` | Always: block destructive shell commands. With a formatter: format each file after Claude edits it |
| `.gitignore` | Adds `CLAUDE.local.md` and `.claude/settings.local.json` (merged, never replaced) |

Formats follow the current [Claude Code docs](https://code.claude.com/docs). Custom commands now live in skills, and hooks are configured in `settings.json`, so there is no separate `commands/` directory.

## One file for every agent

The project context lives in `AGENTS.md`, so Codex, Cursor and other agents that read the format get the same instructions as Claude. `CLAUDE.md` starts with `@AGENTS.md`, which Claude Code needs: it skips a standalone `AGENTS.md` whenever a `CLAUDE.md` or `CLAUDE.local.md` exists ([docs](https://code.claude.com/docs/en/memory)). If your project already has a `CLAUDE.md`, the CLI offers to move it into `AGENTS.md` and add the import for you.

## How agents work

`AGENTS.md` includes six working principles. The first four are adapted from [Andrej Karpathy's notes on LLM coding mistakes](https://x.com/karpathy/status/2015883857489522876), as collected in [andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills); the fifth comes from the humane design principles below, and the sixth keeps dependencies current:

1. **Think before coding:** state assumptions, surface ambiguity, ask when unclear.
2. **Keep it simple:** the least code that solves the problem.
3. **Make surgical changes:** every changed line traces back to the request.
4. **Work toward a verifiable goal:** turn tasks into checks and loop until they pass.
5. **Keep people in control:** ask before irreversible or outward-facing actions; report what was and wasn't verified.
6. **Use current, compatible dependencies:** look up the latest stable versions when adding or upgrading packages, check they work together, and keep versions only in the package file and lockfile.

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
- **New services follow the blueprint.** `agent-scaffold add-service <folder>` asks for the role and stack, adds the service to the manifest, writes its setup, and refreshes the root services table and `/review` skill. The root `AGENTS.md` tells every agent to add services this way, never by hand.

Sections that depend on the list of services (the services table, the `/review` service list, each service's "Part of" section) are wrapped in `<!-- agent-scaffold:name -->` markers. `init` and `add-service` refresh what's between them; everything else in the file is yours.

## Any stack

Presets cover TypeScript/JavaScript, Python, Go, Rust, Java/Kotlin, C#, Ruby, PHP and Swift. The interview never asks for commands: they come from the repository's `package.json` or `pyproject.toml` when there is one, then from a Cohere draft, then from the first language's standard tooling (e.g. `pytest`, `ruff check .`, `ruff format` for Python). Wherever there's a formatter, a hook formats each file after Claude edits it. To change a command later, edit `AGENTS.md`.

Stack not decided, or a language that isn't listed? Leave every language unticked. `AGENTS.md` records the stack as not decided, and a `/choose-stack` skill asks Claude to explore the idea with you (or takes the language you already know), propose 2 or 3 stacks with trade-offs, and, once you pick, fill in the stack, commands, rule paths and permissions.

**MCP servers** aren't part of the interview: connect one when the work needs it (`claude mcp add --scope project ...`), and the generated `CLAUDE.md` tells Claude to ask you first. An answers file can still list them under `mcp_servers`. **The hook that blocks destructive shell commands** (deleting `/` or your home folder, force pushes, `git reset --hard`, `git clean -f`, piping a download into a shell, and dropping a table or database) is always installed.

The generated hooks are standard-library Python scripts, so the machine running Claude Code needs `python3` on its PATH (preinstalled on macOS and most Linux distributions).

## Existing code and Cohere drafts

The interview doesn't start from a blank page when there's something to go on.

- **Existing repositories:** run it in a folder with a `package.json` or `pyproject.toml` and the questions start with what those files say: the language, package manager (npm, pnpm, yarn, bun, uv, Poetry or pip), install/dev/test/lint/format commands, and well-known frameworks among the dependencies. `go.mod`, `Cargo.toml`, `build.gradle`, `pom.xml`, `Gemfile`, `composer.json` and `Package.swift` mark their stacks too.
- **Cohere drafts (optional):** with a [Cohere API key](https://dashboard.cohere.com/api-keys) in `CO_API_KEY` and the extra installed (`uv tool install 'agent-scaffold[cohere]'`), the interview first asks you to describe the project in a few sentences. Cohere's `command-a-plus-05-2026` model drafts the role, languages, frameworks, architecture, project-specific conventions and commands, using [structured outputs](https://docs.cohere.com/docs/structured-outputs) so the role and languages can only be ones the tool knows. It shows the draft first, so you can see what it suggested, then each question starts with it; Enter keeps an answer, or you type over it. For a new project whose kind makes a stack an easy pick (a web app, an LLM service), it suggests languages and says why; untick every language to weigh options with `/choose-stack` instead. A description too vague to go on leaves the stack undecided.
  - Only your description and the names of dependencies and commands are sent, never file contents. The repository's own commands win over the model's suggestions.
  - Set `AGENT_SCAFFOLD_COHERE_MODEL` to use another Command model. If the request fails, the interview carries on without the draft.

Editing saved answers never redrafts: your previous answers are the starting point.

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
  detect.py     # facts from package.json, pyproject.toml and marker files (pure)
  draft.py      # starting answers: from the repository, or a Cohere draft (pure, except the API call)
  writer.py     # plan + write: create / merge / skip / overwrite
  ui.py         # asking questions, showing answers and diffs
  questions.py  # the project, service and workspace interviews
  apply.py      # refresh, settle existing files, preview, confirm, write
  cli.py        # Typer commands
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
- Cohere drafts in the web wizard, and for a whole workspace's list of services
