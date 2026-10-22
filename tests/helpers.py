import json
from typing import Any

from agent_scaffold.generate import generate
from agent_scaffold.models import Answers, Service, Workspace

FULL: dict[str, Any] = {
    "name": "acme-app",
    "description": "Ordering portal for Acme customers.",
    "stacks": ["typescript", "python"],
    "frameworks": "Next.js, FastAPI",
    "test_cmd": "npm test",
    "lint_cmd": "npm run lint",
    "format_cmd": "npx prettier --write",
    "role": "backend",
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


class FakeQuestion:
    def __init__(self, reply: Any) -> None:
        self.reply = reply

    def ask(self) -> Any:
        return self.reply


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


def make_workspace(**overrides: Any) -> Workspace:
    data: dict[str, Any] = {
        "name": "acme",
        "goal": "Help students build lasting study habits.",
        "layout": "repos",
        "communication": "The backend calls the llm service over HTTP.",
        "services": [
            Service(
                "backend",
                Answers(
                    name="backend", description="Public API", role="backend", stacks=["typescript"], test_cmd="npm test"
                ),
            ),
            Service("services/llm", Answers(name="llm", description="", role="llm", stack_undecided=True)),
        ],
        "agents": ["code-reviewer"],
    }
    return Workspace(**{**data, **overrides})
