"""Turn answers into project files. Pure: no file system access, so the CLI and the web API share it."""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined

from .models import AGENTS, MCP_SERVERS, ROLES, STACKS, Answers, Workspace

SETTINGS_SCHEMA = "https://json.schemastore.org/claude-code-settings.json"
GITIGNORE_LINES = ("CLAUDE.local.md", ".claude/settings.local.json")
AGENTS_IMPORT = "@AGENTS.md"
MANIFEST = "agent-scaffold.workspace.json"
_PRINCIPLES_HEADING = "## How to work"

# A managed block is a marked section of a Markdown file that agent-scaffold owns and may rewrite.
# Everything outside the markers belongs to the user.
_BLOCK = re.compile(r"<!-- agent-scaffold:(?P<name>[\w-]+) -->\n.*?\n<!-- /agent-scaffold:(?P=name) -->", re.DOTALL)


@dataclass(frozen=True)
class GeneratedFile:
    path: str
    content: str
    # Append missing lines to an existing file instead of replacing it (used for .gitignore).
    merge_lines: bool = False


@dataclass(frozen=True)
class SystemContext:
    """What a service in a workspace needs to know about the system it belongs to."""

    name: str
    goal: str
    root_dir: str  # relative path from the service to the workspace root, e.g. "../.."
    service_path: str  # the service's folder, as recorded in the workspace manifest

    @property
    def root(self) -> str:
        return f"{self.root_dir}/AGENTS.md"


_env = Environment(  # noqa: S701 - templates render Markdown and Python, never HTML, so autoescape must stay off
    loader=PackageLoader("agent_scaffold", "templates"),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)
_env.globals["roles"] = ROLES
_env.globals["stacks"] = STACKS
_env.globals["manifest"] = MANIFEST
_env.filters["cell"] = lambda text: str(text).replace("|", "\\|")


def _render(template: str, a: Answers, **extra: Any) -> str:
    return _env.get_template(template).render(a=a, **extra)


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2) + "\n"


def merge_lines(existing: str, new: str) -> str:
    present = set(existing.splitlines())
    missing = [line for line in new.splitlines() if line not in present]
    if not missing:
        return existing
    sep = "" if not existing or existing.endswith("\n") else "\n"
    return existing + sep + "\n".join(missing) + "\n"


def blocks(text: str) -> dict[str, str]:
    """The managed blocks in a file, by name, including their markers."""
    return {m["name"]: m[0] for m in _BLOCK.finditer(text)}


def replace_block(text: str, name: str, block: str) -> str | None:
    """Swap one managed block for a new version, or None if the file doesn't have that block."""
    current = blocks(text).get(name)
    return None if current is None else text.replace(current, block, 1)


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


def _shared_files(a: Answers) -> list[GeneratedFile]:
    """Files every project and every workspace root gets: guardrails, chosen agents, MCP and the safety hook."""
    env_vars = [v for key in a.mcp_servers for v in MCP_SERVERS[key].env]
    files = [
        GeneratedFile("CLAUDE.local.md", _render("CLAUDE.local.md.j2", a, env_vars=env_vars)),
        # Humane design guardrails are always on; see README.
        GeneratedFile(".claude/rules/humane-design.md", _render("rules/humane-design.md.j2", a)),
        GeneratedFile(
            ".claude/agents/humane-design-reviewer.md",
            _render("agents/humane-design-reviewer.md.j2", a),
        ),
    ]
    if a.mcp_servers:
        files.append(GeneratedFile(".mcp.json", _json(mcp_config(a))))
    for key in a.agents:
        files.append(GeneratedFile(f".claude/agents/{key}.md", _render(f"agents/{key}.md.j2", a, label=AGENTS[key])))
    if a.block_dangerous:
        files.append(GeneratedFile(".claude/hooks/block_dangerous.py", _render("hooks/block_dangerous.py.j2", a)))
    return files


def generate(a: Answers, system: SystemContext | None = None) -> list[GeneratedFile]:
    files = [
        GeneratedFile("AGENTS.md", _render("AGENTS.md.j2", a, system=system)),
        GeneratedFile("CLAUDE.md", _render("CLAUDE.md.j2", a)),
        GeneratedFile(".claude/settings.json", _json(settings(a))),
        GeneratedFile(".claude/rules/code-style.md", _render("rules/code-style.md.j2", a)),
        GeneratedFile(".claude/rules/testing.md", _render("rules/testing.md.j2", a)),
        GeneratedFile(".claude/skills/plan/SKILL.md", _render("skills/plan.md.j2", a)),
        GeneratedFile(".claude/skills/review/SKILL.md", _render("skills/review.md.j2", a)),
        GeneratedFile(".claude/skills/ship/SKILL.md", _render("skills/ship.md.j2", a)),
        GeneratedFile(".gitignore", "\n".join(GITIGNORE_LINES) + "\n", merge_lines=True),
        *_shared_files(a),
    ]
    if a.stack_undecided:
        files.append(
            GeneratedFile(
                ".claude/skills/choose-stack/SKILL.md", _render("skills/choose-stack.md.j2", a, system=system)
            )
        )
    if a.role != "other":
        files.append(GeneratedFile(f".claude/rules/{a.role}.md", _render(f"roles/{a.role}.md.j2", a)))
    if a.format_on_edit:
        extensions = sorted({g.rsplit(".", 1)[-1] for g in a.globs if "." in g})
        files.append(
            GeneratedFile(
                ".claude/hooks/format_on_edit.py",
                _render("hooks/format_on_edit.py.j2", a, extensions=extensions),
            )
        )
    return files


def generate_workspace(ws: Workspace) -> list[GeneratedFile]:
    """The workspace root's files, then each service's full scaffold inside its folder."""
    # The root renders the shared templates as a project with no stack of its own.
    root = Answers(name=ws.name, description=ws.goal, stack_undecided=True, **ws.shared)
    services = [(s, ws.service_answers(s)) for s in ws.services]
    gitignore = list(GITIGNORE_LINES) + ([f"/{s.path}/" for s in ws.services] if ws.layout == "repos" else [])

    def render(template: str) -> str:
        return _render(template, root, ws=ws, services=services)

    files = [
        GeneratedFile(MANIFEST, _json(ws.to_dict())),
        GeneratedFile("AGENTS.md", render("workspace/AGENTS.md.j2")),
        GeneratedFile("CLAUDE.md", render("workspace/CLAUDE.md.j2")),
        GeneratedFile(".claude/settings.json", _json(settings(root))),
        *(
            GeneratedFile(f".claude/skills/{skill}/SKILL.md", render(f"workspace/skills/{skill}.md.j2"))
            for skill in ("plan", "review", "new-service")
        ),
        GeneratedFile(".gitignore", "\n".join(gitignore) + "\n", merge_lines=True),
        *_shared_files(root),
    ]
    for service, answers in services:
        system = SystemContext(ws.name, ws.goal, "/".join([".."] * service.depth), service.path)
        files += [replace(f, path=posixpath.join(service.path, f.path)) for f in generate(answers, system)]
    return files


def refresh_blocks(files: list[GeneratedFile], read: Callable[[str], str | None]) -> dict[str, str]:
    """For each existing file whose managed blocks are out of date, its content with those blocks replaced.

    `read` returns a file's current content, or None if it doesn't exist. Text outside the markers is kept as is,
    and a file missing a block's markers isn't refreshed, so the usual "already exists" choice handles it.
    """
    refreshed = {}
    for f in files:
        current = read(f.path)
        if current is None or f.merge_lines:
            continue
        updated: str | None = current
        for name, block in blocks(f.content).items():
            updated = replace_block(updated, name, block) if updated is not None else None
        if updated is not None and updated != current:
            refreshed[f.path] = updated
    return refreshed


def can_adopt_claude_md(existing_claude_md: str, agents_md_exists: bool) -> bool:
    """An existing CLAUDE.md can move into AGENTS.md if it doesn't already import one and there's none to clash with."""
    return not agents_md_exists and AGENTS_IMPORT not in existing_claude_md.splitlines()


def adopt_claude_md(files: list[GeneratedFile], existing_claude_md: str, directory: str = "") -> list[GeneratedFile]:
    """Make the user's CLAUDE.md the body of the AGENTS.md in `directory`, keeping the generated managed blocks.

    A workspace's system block goes right after the user's title; the working principles go at the end. The
    generated CLAUDE.md then imports AGENTS.md, so the user's instructions reach every agent.
    """
    path = posixpath.join(directory, "AGENTS.md")
    generated = blocks(next(f for f in files if f.path == path).content)
    mine = blocks(existing_claude_md)
    lines = existing_claude_md.rstrip().split("\n")
    title = lines[:1] if lines[0].startswith("# ") else []
    parts = ["\n".join(title)] if title else []
    if "system" in generated and "system" not in mine:
        parts.append(generated["system"])
    parts.append("\n".join(lines[len(title) :]).strip())
    if "principles" in generated and "principles" not in mine and _PRINCIPLES_HEADING not in existing_claude_md:
        parts.append(generated["principles"])
    body = "\n\n".join(p for p in parts if p) + "\n"
    return [GeneratedFile(path, body) if f.path == path else f for f in files]
