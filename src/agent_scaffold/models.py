"""The answers a project interview produces, and the catalogs the questions offer."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class Stack:
    label: str
    globs: tuple[str, ...]
    test_globs: tuple[str, ...]
    test: str
    lint: str
    format: str


STACKS: dict[str, Stack] = {
    "typescript": Stack(
        "TypeScript / JavaScript",
        ("**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx"),
        ("**/*.test.*", "**/*.spec.*", "**/__tests__/**"),
        test="npm test",
        lint="npm run lint",
        format="npx prettier --write",
    ),
    "python": Stack(
        "Python",
        ("**/*.py",),
        ("tests/**/*.py", "**/test_*.py"),
        test="pytest",
        lint="ruff check .",
        format="ruff format",
    ),
    "go": Stack("Go", ("**/*.go",), ("**/*_test.go",), test="go test ./...", lint="go vet ./...", format="gofmt -w"),
    "rust": Stack("Rust", ("**/*.rs",), ("tests/**/*.rs",), test="cargo test", lint="cargo clippy", format="rustfmt"),
    "jvm": Stack(
        "Java / Kotlin",
        ("**/*.java", "**/*.kt"),
        ("**/src/test/**",),
        test="./gradlew test",
        lint="./gradlew check",
        format="",
    ),
    "csharp": Stack(
        "C#",
        ("**/*.cs",),
        ("**/*Tests/**", "**/*.Tests/**"),
        test="dotnet test",
        lint="dotnet format --verify-no-changes",
        format="",
    ),
    "ruby": Stack(
        "Ruby",
        ("**/*.rb",),
        ("spec/**/*.rb", "test/**/*.rb"),
        test="bundle exec rspec",
        lint="bundle exec rubocop",
        format="bundle exec rubocop -a",
    ),
    "php": Stack(
        "PHP",
        ("**/*.php",),
        ("tests/**/*.php",),
        test="vendor/bin/phpunit",
        lint="vendor/bin/phpstan analyse",
        format="",
    ),
    "swift": Stack(
        "Swift",
        ("**/*.swift",),
        ("**/*Tests/**",),
        test="swift test",
        lint="swiftlint",
        format="swift-format -i",
    ),
}


@dataclass(frozen=True)
class McpServer:
    label: str
    config: dict[str, Any]
    env: tuple[str, ...] = ()


# Remote URLs come from the Claude Code MCP docs (code.claude.com/docs/en/mcp).
MCP_SERVERS: dict[str, McpServer] = {
    "github": McpServer(
        "GitHub",
        {
            "type": "http",
            "url": "https://api.githubcopilot.com/mcp/",
            "headers": {"Authorization": "Bearer ${GITHUB_PAT}"},
        },
        env=("GITHUB_PAT",),
    ),
    "sentry": McpServer("Sentry", {"type": "http", "url": "https://mcp.sentry.dev/mcp"}),
    "notion": McpServer("Notion", {"type": "http", "url": "https://mcp.notion.com/mcp"}),
    "slack": McpServer("Slack", {"type": "http", "url": "https://mcp.slack.com/mcp"}),
    "playwright": McpServer(
        "Playwright (browser testing)",
        {"command": "npx", "args": ["-y", "@playwright/mcp@latest"]},
    ),
}


@dataclass(frozen=True)
class Role:
    label: str
    focus: str
    default_stack: str | None
    agents: tuple[str, ...]


# What a project or service is for. Each role (except "other") adds a rule file of conventions for that purpose.
ROLES: dict[str, Role] = {
    "backend": Role(
        "Backend / API",
        "Serves data and business logic to clients or other services through an API.",
        "typescript",
        ("code-reviewer", "security-auditor"),
    ),
    "frontend": Role(
        "Frontend (web or mobile UI)", "The interface people use directly.", "typescript", ("code-reviewer",)
    ),
    "fullstack": Role(
        "Full-stack app", "UI and server in one codebase.", "typescript", ("code-reviewer", "security-auditor")
    ),
    "data": Role(
        "Data pipeline",
        "Ingests, transforms and stores data for the rest of the system.",
        "python",
        ("code-reviewer",),
    ),
    "llm": Role(
        "LLM / AI service",
        "Calls language models: prompts, retrieval, evaluation and model configuration.",
        "python",
        ("code-reviewer", "security-auditor"),
    ),
    "worker": Role(
        "Background worker", "Runs scheduled or queued jobs outside the request path.", None, ("code-reviewer",)
    ),
    "other": Role("Other (library, CLI, tool, ...)", "", None, ("code-reviewer",)),
}

AGENTS: dict[str, str] = {
    "code-reviewer": "Code reviewer",
    "security-auditor": "Security auditor",
    "test-writer": "Test writer",
}


@dataclass
class Answers:
    name: str
    description: str
    # True when the languages aren't known yet; the /choose-stack skill finishes the setup later.
    stack_undecided: bool = False
    stacks: list[str] = field(default_factory=list)
    # File extensions for languages without a preset, e.g. ["ex", "exs"] for Elixir.
    extensions: list[str] = field(default_factory=list)
    frameworks: str = ""
    architecture: str = ""
    conventions: str = ""
    install_cmd: str = ""
    dev_cmd: str = ""
    test_cmd: str = ""
    lint_cmd: str = ""
    format_cmd: str = ""
    role: str = "other"
    mcp_servers: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    block_dangerous: bool = True
    format_on_edit: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name is required")
        self.extensions = [e.strip().lstrip(".").lower() for e in self.extensions if e.strip().lstrip(".")]
        if self.stack_undecided:
            if self.stacks or self.extensions:
                raise ValueError("stack_undecided can't be combined with stacks or extensions")
            if self.format_on_edit:
                raise ValueError("format_on_edit needs a decided stack")
        elif not self.stacks and not self.extensions:
            raise ValueError("pick at least one stack or file extension, or set stack_undecided")
        if self.role not in ROLES:
            raise ValueError(f"unknown role: {self.role}")
        for key, catalog, kind in (
            (self.stacks, STACKS, "stack"),
            (self.mcp_servers, MCP_SERVERS, "MCP server"),
            (self.agents, AGENTS, "agent"),
        ):
            unknown = [k for k in key if k not in catalog]
            if unknown:
                raise ValueError(f"unknown {kind}: {', '.join(unknown)}")
        if self.format_on_edit and not self.format_cmd:
            raise ValueError("format_on_edit needs a format_cmd")

    @property
    def globs(self) -> list[str]:
        return [g for s in self.stacks for g in STACKS[s].globs] + [f"**/*.{e}" for e in self.extensions]

    @property
    def test_globs(self) -> list[str]:
        custom = [f"**/*{word}*.{e}" for e in self.extensions for word in ("test", "spec")]
        return [g for s in self.stacks for g in STACKS[s].test_globs] + custom

    @property
    def convention_list(self) -> list[str]:
        """The project's own rules, one per item: the answer is split on ";" and newlines."""
        return [rule.strip() for rule in re.split(r"[;\n]", self.conventions) if rule.strip()]

    @property
    def languages(self) -> list[str]:
        return [STACKS[s].label for s in self.stacks] + [f"*.{e} files" for e in self.extensions]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Answers:
        data = dict(data)
        # Answers saved before roles existed had a has_api flag; an API project is a backend.
        if "has_api" in data:
            has_api = data.pop("has_api")
            data.setdefault("role", "backend" if has_api else "other")
        known = set(cls.__dataclass_fields__)
        extra = set(data) - known
        if extra:
            raise ValueError(f"unknown fields: {', '.join(sorted(extra))}")
        return cls(**data)


LAYOUTS: dict[str, str] = {
    "monorepo": "One git repository with each service in a subfolder",
    "repos": "Separate git repositories side by side, in a workspace repository that ignores them",
}

# Answers that a workspace sets once for every service.
SHARED_FIELDS = ("mcp_servers", "agents", "block_dangerous")


@dataclass
class Service:
    path: str
    answers: Answers

    def __post_init__(self) -> None:
        parts = self.path.strip("/").split("/")
        if not self.path.strip("/") or self.path.startswith(("/", "~")) or ".." in parts or "." in parts:
            raise ValueError(f"service folder must be a relative path inside the workspace: {self.path!r}")
        self.path = "/".join(parts)

    @property
    def depth(self) -> int:
        return self.path.count("/") + 1


@dataclass
class Workspace:
    """A system of several services sharing one goal. Saved as the workspace manifest."""

    name: str
    goal: str
    layout: str
    services: list[Service]
    communication: str = ""
    contracts: str = ""
    mcp_servers: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    block_dangerous: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name is required")
        if self.layout not in LAYOUTS:
            raise ValueError(f"unknown layout: {self.layout}")
        paths = [s.path for s in self.services]
        duplicates = sorted({p for p in paths if paths.count(p) > 1})
        if duplicates:
            raise ValueError(f"duplicate service folders: {', '.join(duplicates)}")
        nested = [a for a in paths for b in paths if a != b and a.startswith(b + "/")]
        if nested:
            raise ValueError(f"service folders can't be inside other services: {', '.join(sorted(set(nested)))}")
        # Validates the shared choices against the catalogs.
        Answers(name=self.name, description="", stack_undecided=True, **self.shared)

    @property
    def shared(self) -> dict[str, Any]:
        return {f: getattr(self, f) for f in SHARED_FIELDS}

    def service_answers(self, service: Service) -> Answers:
        """A service's own answers with the workspace-wide choices applied."""
        return replace(service.answers, **self.shared)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["services"] = [
            {"path": s.path, "answers": {k: v for k, v in s.answers.to_dict().items() if k not in SHARED_FIELDS}}
            for s in self.services
        ]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Workspace:
        data = dict(data)
        known = set(cls.__dataclass_fields__)
        extra = set(data) - known
        if extra:
            raise ValueError(f"unknown fields: {', '.join(sorted(extra))}")
        services = [Service(s["path"], Answers.from_dict(s["answers"])) for s in data.pop("services", [])]
        return cls(services=services, **data)


def load_answers(data: dict[str, Any]) -> Answers | Workspace:
    """Read saved or hand-written answers: a "services" key means a workspace."""
    return Workspace.from_dict(data) if "services" in data else Answers.from_dict(data)
