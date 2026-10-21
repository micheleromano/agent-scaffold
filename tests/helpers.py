import json
from typing import Any

from agent_scaffold.generate import generate
from agent_scaffold.models import Answers

FULL: dict[str, Any] = {
    "name": "acme-app",
    "description": "Ordering portal for Acme customers.",
    "stacks": ["typescript", "python"],
    "frameworks": "Next.js, FastAPI",
    "test_cmd": "npm test",
    "lint_cmd": "npm run lint",
    "format_cmd": "npx prettier --write",
    "has_api": True,
    "mcp_servers": ["github", "sentry"],
    "agents": ["code-reviewer", "security-auditor"],
    "block_dangerous": True,
    "format_on_edit": True,
}

MINIMAL: dict[str, Any] = {
    "name": "tiny",
    "description": "",
    "extensions": ["ex"],
    "block_dangerous": False,
}


def make_answers(**overrides: Any) -> Answers:
    return Answers(**{**FULL, **overrides})


def files_by_path(answers: Answers) -> dict[str, str]:
    return {f.path: f.content for f in generate(answers)}


def frontmatter(text: str) -> dict[str, str]:
    """Top-level `key: value` pairs between the opening `---` markers."""
    assert text.startswith("---\n")
    block = text.split("---\n")[1]
    return dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(" "))


def frontmatter_list(text: str, key: str) -> list[str]:
    """The quoted items of a YAML list such as `paths:`."""
    block = text.split("---\n")[1].split(f"{key}:\n", 1)[1]
    return [json.loads(line.strip()[2:]) for line in block.splitlines() if line.startswith("  - ")]
