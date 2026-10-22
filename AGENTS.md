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
- **To add a stack, role, MCP server or agent:** add the catalog entry in `models.py`, a template if needed (`templates/roles/<role>.md.j2` for a role), and a test. The parametrized tests pick up new catalog entries automatically.
- **Managed blocks:** text between `<!-- agent-scaffold:name -->` markers is owned by the tool and refreshed by `init` and `add-service`; never put user content inside them, and never touch text outside them. Use a block only when generated text depends on the workspace's list of services.

## How to work

Adapted from Andrej Karpathy's notes on common LLM coding mistakes (https://x.com/karpathy/status/2015883857489522876, via github.com/multica-ai/andrej-karpathy-skills) and the Center for Humane Technology's principles (https://www.humanetech.com/humane-product-design). These favor care over speed; for trivial tasks, use judgment.

1. **Think before coding.** Say what you're assuming. If a request can be read more than one way, lay out the readings instead of picking one quietly. If something is unclear, stop and ask. If there's a simpler approach, propose it.
2. **Keep it simple.** Write the least code that solves the problem: no features, options or abstractions nobody asked for, and no handling for cases that can't happen. If a senior engineer would call it overbuilt, cut it down.
3. **Make surgical changes.** Every changed line should trace back to the request. Match the existing style, leave unrelated code alone, and mention problems you notice instead of fixing them unasked. Do clean up anything your own change made unused.
4. **Work toward a verifiable goal.** Turn the task into a check you can run, such as a failing test that should pass. For multi-step work, write a short plan with a check for each step, and keep going until the checks pass.
5. **Keep people in control.** Ask before anything irreversible or outward-facing: deleting data, migrations, deploys, publishing, sending messages. Explain trade-offs in plain words and recommend one option. Report what you verified and what you didn't; never claim a check passed that you didn't run.
