"""Turn Answers into project files. Pure: no file system access, so the CLI and the web API share it."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined

from .models import AGENTS, MCP_SERVERS, Answers

SETTINGS_SCHEMA = "https://json.schemastore.org/claude-code-settings.json"
GITIGNORE_LINES = ("CLAUDE.local.md", ".claude/settings.local.json")


@dataclass(frozen=True)
class GeneratedFile:
    path: str
    content: str
    # Append missing lines to an existing file instead of replacing it (used for .gitignore).
    merge_lines: bool = False


_env = Environment(  # noqa: S701 - templates render Markdown and Python, never HTML, so autoescape must stay off
    loader=PackageLoader("agent_scaffold", "templates"),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def _render(template: str, a: Answers, **extra: Any) -> str:
    return _env.get_template(template).render(a=a, **extra)


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2) + "\n"


def _allow_rules(a: Answers) -> list[str]:
    rules = []
    for cmd in (a.test_cmd, a.lint_cmd, a.dev_cmd):
        if cmd:
            rules += [f"Bash({cmd})", f"Bash({cmd} *)"]
    return rules


def _hook_command(script: str) -> dict[str, str]:
    return {"type": "command", "command": f'python3 "${{CLAUDE_PROJECT_DIR}}/.claude/hooks/{script}"'}


def settings(a: Answers) -> dict[str, Any]:
    data: dict[str, Any] = {
        "$schema": SETTINGS_SCHEMA,
        "permissions": {
            "allow": _allow_rules(a),
            "deny": ["Read(./.env)", "Read(./.env.*)"],
        },
    }
    hooks: dict[str, list[dict[str, Any]]] = {}
    if a.block_dangerous:
        hooks["PreToolUse"] = [{"matcher": "Bash", "hooks": [_hook_command("block_dangerous.py")]}]
    if a.format_on_edit:
        hooks["PostToolUse"] = [{"matcher": "Edit|Write", "hooks": [_hook_command("format_on_edit.py")]}]
    if hooks:
        data["hooks"] = hooks
    return data


def mcp_config(a: Answers) -> dict[str, Any]:
    return {"mcpServers": {key: MCP_SERVERS[key].config for key in a.mcp_servers}}


def generate(a: Answers) -> list[GeneratedFile]:
    env_vars = [v for key in a.mcp_servers for v in MCP_SERVERS[key].env]
    files = [
        GeneratedFile("CLAUDE.md", _render("CLAUDE.md.j2", a)),
        GeneratedFile("CLAUDE.local.md", _render("CLAUDE.local.md.j2", a, env_vars=env_vars)),
        GeneratedFile(".claude/settings.json", _json(settings(a))),
        GeneratedFile(".claude/rules/code-style.md", _render("rules/code-style.md.j2", a)),
        GeneratedFile(".claude/rules/testing.md", _render("rules/testing.md.j2", a)),
        GeneratedFile(".claude/skills/review/SKILL.md", _render("skills/review.md.j2", a)),
        GeneratedFile(".gitignore", "\n".join(GITIGNORE_LINES) + "\n", merge_lines=True),
    ]
    if a.mcp_servers:
        files.append(GeneratedFile(".mcp.json", _json(mcp_config(a))))
    if a.has_api:
        files.append(GeneratedFile(".claude/rules/api-conventions.md", _render("rules/api-conventions.md.j2", a)))
    for key in a.agents:
        files.append(GeneratedFile(f".claude/agents/{key}.md", _render(f"agents/{key}.md.j2", a, label=AGENTS[key])))
    if a.block_dangerous:
        files.append(GeneratedFile(".claude/hooks/block_dangerous.py", _render("hooks/block_dangerous.py.j2", a)))
    if a.format_on_edit:
        extensions = sorted({g.rsplit(".", 1)[-1] for g in a.globs if "." in g})
        files.append(
            GeneratedFile(
                ".claude/hooks/format_on_edit.py",
                _render("hooks/format_on_edit.py.j2", a, extensions=extensions),
            )
        )
    return files
