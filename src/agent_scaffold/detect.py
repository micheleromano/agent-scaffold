"""What an existing repository says about itself: its stack, commands and dependencies.

Pure: it reads through the `read` function it's given, so the CLI passes files from disk and the web API can pass
uploaded ones. Only `package.json` and `pyproject.toml` are parsed; other stacks are recognized by a marker file.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable, Collection
from dataclasses import dataclass, field

from .models import STACKS

# A file at the root that means the project uses a stack, for stacks without a parsed manifest.
MARKERS = {
    "go.mod": "go",
    "Cargo.toml": "rust",
    "build.gradle": "jvm",
    "build.gradle.kts": "jvm",
    "pom.xml": "jvm",
    "Gemfile": "ruby",
    "composer.json": "php",
    "Package.swift": "swift",
}

# Dependencies worth naming as the project's frameworks when no model is drafting the answers.
FRAMEWORKS = (
    "next",
    "react-router",
    "@remix-run/react",
    "react",
    "vue",
    "nuxt",
    "svelte",
    "@sveltejs/kit",
    "astro",
    "@angular/core",
    "express",
    "hono",
    "fastify",
    "@nestjs/core",
    "tailwindcss",
    "prisma",
    "drizzle-orm",
    "fastapi",
    "django",
    "flask",
    "sqlalchemy",
    "pydantic",
    "typer",
    "click",
    "pandas",
    "polars",
    "torch",
    "langchain",
    "cohere",
    "anthropic",
    "openai",
)

# Node package managers by lockfile, with the commands to install and to run a package's binary.
_NODE_MANAGERS = {
    "pnpm-lock.yaml": ("pnpm", "pnpm install", "pnpm exec"),
    "yarn.lock": ("yarn", "yarn install", "yarn"),
    "bun.lock": ("bun", "bun install", "bunx"),
    "bun.lockb": ("bun", "bun install", "bunx"),
    "package-lock.json": ("npm", "npm install", "npx"),
}
_DEFAULT_NODE = ("npm", "npm install", "npx")
_MAX_DEPENDENCIES = 60


@dataclass
class Detected:
    name: str = ""
    description: str = ""
    stacks: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    install_cmd: str = ""
    dev_cmd: str = ""
    test_cmd: str = ""
    lint_cmd: str = ""
    format_cmd: str = ""
    sources: list[str] = field(default_factory=list)  # the files these facts came from

    @property
    def frameworks(self) -> list[str]:
        return [name for name in FRAMEWORKS if name in self.dependencies]

    def __bool__(self) -> bool:
        return bool(self.sources)

    def _fill(self, **values: str) -> None:
        """Set each blank field; the first file that knows a value wins."""
        for key, value in values.items():
            if value and not getattr(self, key):
                setattr(self, key, value)


def _requirement_name(requirement: str) -> str:
    """`fastapi[standard]>=0.1 ; python_version>'3'` -> `fastapi`."""
    return re.split(r"[\s\[<>=!~;@(]", requirement.strip(), maxsplit=1)[0].lower()


def _package_json(text: str, names: Collection[str], found: Detected) -> None:
    data = json.loads(text)
    deps = [*data.get("dependencies", {}), *data.get("devDependencies", {})]
    declared = str(data.get("packageManager", "")).split("@")[0]
    manager, install, run_bin = next(
        (m for lock, m in _NODE_MANAGERS.items() if lock in names or m[0] == declared), _DEFAULT_NODE
    )
    scripts = data.get("scripts", {})

    def script(*keys: str) -> str:
        key = next((k for k in keys if k in scripts), "")
        return f"{manager} run {key}" if key else ""

    found.stacks.append("typescript")
    found.dependencies += deps
    found._fill(
        name=str(data.get("name", "")),
        description=str(data.get("description", "")),
        install_cmd=install,
        dev_cmd=script("dev", "start"),
        test_cmd=script("test"),
        lint_cmd=script("lint"),
        format_cmd=f"{run_bin} prettier --write" if "prettier" in deps else "",
    )


def _pyproject(text: str, names: Collection[str], found: Detected) -> None:
    data = tomllib.loads(text)
    project = data.get("project", {})
    tool = data.get("tool", {})
    groups = data.get("dependency-groups", {})
    requirements = [
        *project.get("dependencies", []),
        *(r for extra in project.get("optional-dependencies", {}).values() for r in extra),
        *(r for group in groups.values() for r in group if isinstance(r, str)),
        *tool.get("poetry", {}).get("dependencies", {}),
        *tool.get("poetry", {}).get("group", {}).get("dev", {}).get("dependencies", {}),
    ]
    deps = [name for name in map(_requirement_name, requirements) if name and name != "python"]
    if "uv.lock" in names or "uv" in tool:
        install, run = "uv sync", "uv run "
    elif "poetry.lock" in names or "poetry" in tool:
        install, run = "poetry install", "poetry run "
    else:
        install, run = "pip install -e .", ""
    uses_ruff = "ruff" in deps or "ruff" in tool
    found.stacks.append("python")
    found.dependencies += deps
    found._fill(
        name=str(project.get("name", "")),
        description=str(project.get("description", "")),
        install_cmd=install,
        test_cmd=f"{run}pytest" if "pytest" in deps or "pytest" in tool else "",
        lint_cmd=f"{run}ruff check ." if uses_ruff else "",
        format_cmd=f"{run}ruff format" if uses_ruff else "",
    )


def detect(names: Collection[str], read: Callable[[str], str | None]) -> Detected:
    """Facts about the project whose root holds the files in `names`. Unreadable manifests are skipped."""
    found = Detected()
    for manifest, parse in (("package.json", _package_json), ("pyproject.toml", _pyproject)):
        text = read(manifest) if manifest in names else None
        if text is None:
            continue
        try:
            parse(text, names, found)
        except (ValueError, TypeError, AttributeError):  # malformed JSON/TOML, or a field of an unexpected type
            continue
        found.sources.append(manifest)
    for marker, stack in MARKERS.items():
        if marker in names and stack not in found.stacks:
            preset = STACKS[stack]
            found.stacks.append(stack)
            found._fill(test_cmd=preset.test, lint_cmd=preset.lint, format_cmd=preset.format)
            found.sources.append(marker)
    found.dependencies = list(dict.fromkeys(found.dependencies))[:_MAX_DEPENDENCIES]
    return found
