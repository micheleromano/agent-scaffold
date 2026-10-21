import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from agent_scaffold import cli
from agent_scaffold.cli import app

from .helpers import make_answers

runner = CliRunner()


@pytest.fixture
def answers_file(tmp_path: Path) -> Path:
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(make_answers().to_dict()))
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    path = tmp_path / "project"
    path.mkdir()
    return path


def test_dry_run_writes_nothing(project: Path, answers_file: Path) -> None:
    result = runner.invoke(app, ["init", str(project), "--answers", str(answers_file), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "+ CLAUDE.md" in result.output
    assert "Dry run" in result.output
    assert list(project.iterdir()) == []


def test_writes_files_and_reports_skips(project: Path, answers_file: Path) -> None:
    (project / "CLAUDE.md").write_text("mine\n")
    result = runner.invoke(app, ["init", str(project), "--answers", str(answers_file)])
    assert result.exit_code == 0, result.output
    assert "CLAUDE.md  (skip)" in result.output
    assert "--force" in result.output
    assert (project / ".claude/settings.json").exists()


def test_invalid_answers_file_exits_with_error(project: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"name": "x", "description": "", "stacks": ["cobol"]}))
    result = runner.invoke(app, ["init", str(project), "--answers", str(bad)])
    assert result.exit_code == 1
    assert "unknown stack: cobol" in result.output


def test_missing_directory_is_rejected(tmp_path: Path, answers_file: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path / "nope"), "--answers", str(answers_file)])
    assert result.exit_code != 0
    assert "is not a directory" in result.output


def scripted(replies: list[Any]) -> Iterator[Any]:
    yield from replies


def test_interview_builds_answers_and_saves_them(
    monkeypatch: pytest.MonkeyPatch, project: Path, tmp_path: Path
) -> None:
    replies = scripted(
        [
            "shop",  # name
            "A shop.",  # description
            [],  # preset languages
            "ex, exs",  # other extensions
            "Phoenix",  # frameworks
            "",  # architecture
            "",  # conventions
            "mix deps.get",  # install
            "mix phx.server",  # dev
            "mix test",  # test
            "mix credo",  # lint
            "mix format",  # format
            False,  # has API
            ["github"],  # MCP servers
            ["code-reviewer"],  # agents
            True,  # block dangerous
            True,  # format on edit
        ]
    )
    monkeypatch.setattr(cli, "_ask", lambda _question: next(replies))
    saved = tmp_path / "saved.json"

    result = runner.invoke(app, ["init", str(project), "--save-answers", str(saved)])

    assert result.exit_code == 0, result.output
    data = json.loads(saved.read_text())
    assert data["extensions"] == ["ex", "exs"]
    assert data["test_cmd"] == "mix test"
    assert data["format_on_edit"] is True
    assert (project / ".claude/rules/humane-design.md").exists()
    assert (project / ".claude/hooks/format_on_edit.py").exists()
    assert next(replies, None) is None, "interview asked fewer questions than scripted"


class FakeQuestion:
    def __init__(self, reply: Any) -> None:
        self.reply = reply

    def ask(self) -> Any:
        return self.reply


def test_ask_returns_the_reply() -> None:
    assert cli._ask(FakeQuestion("yes")) == "yes"  # type: ignore[arg-type]


def test_ctrl_c_aborts() -> None:
    # questionary returns None when the user presses Ctrl-C.
    with pytest.raises(typer.Abort):
        cli._ask(FakeQuestion(None))  # type: ignore[arg-type]  # duck-typed stand-in for questionary.Question
