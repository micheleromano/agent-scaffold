import json
from typing import Any

import pytest

from agent_scaffold.detect import Detected, detect


def package_json(**data: Any) -> str:
    return json.dumps(data)


def test_nothing_found_in_an_empty_folder() -> None:
    found = detect(set(), lambda _name: None)
    assert not found
    assert found == Detected()


def test_package_json_gives_name_stack_commands_and_frameworks() -> None:
    found = detect(
        {"package.json", "pnpm-lock.yaml"},
        {
            "package.json": package_json(
                name="strava-art",
                description="Art from your runs",
                scripts={"dev": "vite", "test": "vitest", "lint": "eslint ."},
                dependencies={"react": "^19", "react-router": "^8"},
                devDependencies={"prettier": "^3", "tailwindcss": "^4"},
            )
        }.get,
    )
    assert found.sources == ["package.json"]
    assert (found.name, found.description, found.stacks) == ("strava-art", "Art from your runs", ["typescript"])
    assert found.install_cmd == "pnpm install"
    assert (found.dev_cmd, found.test_cmd, found.lint_cmd) == ("pnpm run dev", "pnpm run test", "pnpm run lint")
    assert found.format_cmd == "pnpm exec prettier --write"
    assert found.frameworks == ["react-router", "react", "tailwindcss"]
    assert "^19" not in " ".join(found.dependencies)  # names only, never versions


@pytest.mark.parametrize(
    ("names", "data", "install", "dev"),
    [
        ({"package.json"}, {"scripts": {"start": "node ."}}, "npm install", "npm run start"),
        ({"package.json", "yarn.lock"}, {}, "yarn install", ""),
        ({"package.json", "bun.lockb"}, {}, "bun install", ""),
        ({"package.json"}, {"packageManager": "pnpm@10.0.0"}, "pnpm install", ""),
    ],
)
def test_node_package_manager(names: set[str], data: dict[str, Any], install: str, dev: str) -> None:
    found = detect(names, {"package.json": json.dumps(data)}.get)
    assert (found.install_cmd, found.dev_cmd, found.test_cmd, found.format_cmd) == (install, dev, "", "")


PYPROJECT = """
[project]
name = "agent-scaffold"
description = "Interview-driven setup"
dependencies = ["typer>=0.27", "jinja2[i18n]>=3.1 ; python_version >= '3.12'"]

[project.optional-dependencies]
cohere = ["cohere>=7.3.0"]

[dependency-groups]
dev = ["pytest>=9", "ruff", {include-group = "lint"}]
"""


def test_pyproject_with_uv() -> None:
    found = detect({"pyproject.toml", "uv.lock"}, {"pyproject.toml": PYPROJECT}.get)
    assert (found.name, found.stacks, found.sources) == ("agent-scaffold", ["python"], ["pyproject.toml"])
    assert found.dependencies == ["typer", "jinja2", "cohere", "pytest", "ruff"]
    assert found.frameworks == ["typer", "cohere"]
    assert (found.install_cmd, found.test_cmd) == ("uv sync", "uv run pytest")
    assert (found.lint_cmd, found.format_cmd) == ("uv run ruff check .", "uv run ruff format")


def test_pyproject_with_poetry_and_tool_sections() -> None:
    text = """
[tool.poetry.dependencies]
python = "^3.12"
django = "^5"

[tool.poetry.group.dev.dependencies]
black = "*"

[tool.pytest.ini_options]
addopts = "-q"
"""
    found = detect({"pyproject.toml", "poetry.lock"}, {"pyproject.toml": text}.get)
    assert found.dependencies == ["django", "black"]
    assert (found.install_cmd, found.test_cmd, found.lint_cmd) == ("poetry install", "poetry run pytest", "")


def test_plain_pip_project() -> None:
    found = detect({"pyproject.toml"}, {"pyproject.toml": '[project]\nname = "x"\n[tool.ruff]\n'}.get)
    assert (found.install_cmd, found.test_cmd, found.lint_cmd) == ("pip install -e .", "", "ruff check .")


def test_package_json_commands_win_over_pyproject() -> None:
    found = detect(
        {"package.json", "pyproject.toml", "uv.lock"},
        {"package.json": package_json(scripts={"test": "vitest"}), "pyproject.toml": PYPROJECT}.get,
    )
    assert found.stacks == ["typescript", "python"]
    assert (found.test_cmd, found.lint_cmd) == ("npm run test", "uv run ruff check .")


@pytest.mark.parametrize(
    ("marker", "stack", "test"), [("go.mod", "go", "go test ./..."), ("Cargo.toml", "rust", "cargo test")]
)
def test_marker_files_use_the_stack_preset(marker: str, stack: str, test: str) -> None:
    found = detect({marker}, lambda _name: None)
    assert (found.stacks, found.test_cmd, found.sources) == ([stack], test, [marker])


@pytest.mark.parametrize("text", ["{not json", "[]", '"text"'])
def test_unreadable_package_json_is_skipped(text: str) -> None:
    assert not detect({"package.json"}, {"package.json": text}.get)


def test_broken_pyproject_is_skipped() -> None:
    assert not detect({"pyproject.toml"}, {"pyproject.toml": "[project"}.get)


def test_dependency_list_is_capped() -> None:
    deps = {f"pkg{i}": "1" for i in range(100)}
    assert len(detect({"package.json"}, {"package.json": package_json(dependencies=deps)}.get).dependencies) == 60
