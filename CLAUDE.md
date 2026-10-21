# agent-scaffold

Interview-driven CLI (and soon a web app) that generates a project's Claude Code setup: CLAUDE.md, settings, MCP, rules, skills, subagents and hooks.

## Stack

- Python
- Frameworks and libraries: Typer, questionary, Jinja2, pytest; uv for packaging

## Commands

- Install: `uv sync`
- Run locally: `uv run agent-scaffold`
- Test: `uv run pytest`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format`

## Architecture

models.py holds the Answers dataclass and the catalogs (stacks, MCP servers, agents). generate.py is a pure function Answers -> list[GeneratedFile] that renders Jinja2 templates in templates/. writer.py plans and applies changes to disk (create / merge / skip / overwrite). cli.py runs the questionary interview and the Typer command. The planned FastAPI service and Next.js wizard reuse generate.py unchanged.

A task is done when `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run pytest` all pass. Coverage is 100%; keep it there.

## Conventions

- **This tool is stack-agnostic.** It runs on any project, so generated output must never assume a language, package manager or command. Every command comes from `Answers`; empty answers leave their line or section out rather than rendering a placeholder.
- **`models.py` and `generate.py` stay pure:** no file system, network or environment access, and only pure-Python dependencies. They will run inside a Cloudflare Python Worker (Pyodide). All disk I/O belongs in `writer.py` and `cli.py`.
- **Generated formats follow the Claude Code docs** at code.claude.com/docs. Check the relevant page before changing a format, and link it in the commit message. Custom commands are skills (`.claude/skills/<name>/SKILL.md`); hooks are configured in `settings.json`.
- **Build JSON with `json.dumps`, never in a template.** In YAML frontmatter, render user text through `| tojson` so colons and quotes can't break it.
- **Never destroy user work:** existing files are skipped unless `--force`; `.gitignore` is merged line by line.
- **Generated hook scripts use only the Python standard library.** They run in the user's project, which may have no Python environment.
- **To add a stack, MCP server or agent:** add the catalog entry in `models.py`, a template if needed, and a test. The parametrized tests pick up new catalog entries automatically.

Detailed rules live in `.claude/rules/` and load when Claude works on matching files.
