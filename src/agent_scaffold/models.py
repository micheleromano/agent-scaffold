"""The answers a project interview produces, and the catalogs the questions offer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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

AGENTS: dict[str, str] = {
    "code-reviewer": "Code reviewer",
    "security-auditor": "Security auditor",
    "test-writer": "Test writer",
}


@dataclass
class Answers:
    name: str
    description: str
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
    has_api: bool = False
    mcp_servers: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    block_dangerous: bool = True
    format_on_edit: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name is required")
        self.extensions = [e.strip().lstrip(".").lower() for e in self.extensions if e.strip().lstrip(".")]
        if not self.stacks and not self.extensions:
            raise ValueError("pick at least one stack or file extension")
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
    def languages(self) -> list[str]:
        return [STACKS[s].label for s in self.stacks] + [f"*.{e} files" for e in self.extensions]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Answers:
        known = set(cls.__dataclass_fields__)
        extra = set(data) - known
        if extra:
            raise ValueError(f"unknown fields: {', '.join(sorted(extra))}")
        return cls(**data)
