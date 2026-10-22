import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import questionary
import typer
from typer.testing import CliRunner

from agent_scaffold import cli
from agent_scaffold.cli import app
from agent_scaffold.models import Answers

from .helpers import MINIMAL, make_answers

runner = CliRunner()


@pytest.fixture(autouse=True)
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Keep saved answers out of the real home directory.
    path = tmp_path / "state"
    monkeypatch.setenv("AGENT_SCAFFOLD_STATE_DIR", str(path))
    return path


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


class FakeQuestion:
    def __init__(self, reply: Any) -> None:
        self.reply = reply

    def ask(self) -> Any:
        return self.reply


def replies(*values: Any) -> Callable[[Any], Any]:
    """A stand-in for cli._ask that answers each question in turn and fails if asked too many."""
    queue: Iterator[Any] = iter(values)

    def ask(_question: Any) -> Any:
        return next(queue)

    return ask


def save(root: Path, answers: Answers) -> Path:
    path = cli.saved_answers_path(root.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(answers.to_dict()))
    return path


# --- confirm before writing ---------------------------------------------------------------


def test_says_nothing_is_written_until_confirmed(project: Path, answers_file: Path) -> None:
    result = runner.invoke(app, ["init", str(project), "--answers", str(answers_file), "--yes"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("Nothing is written until you confirm at the end.")


def test_declining_writes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answers_file: Path) -> None:
    project = tmp_path / "new"
    monkeypatch.setattr(cli, "_ask", replies(False))  # "Write these files?"
    result = runner.invoke(app, ["init", str(project), "--answers", str(answers_file)])
    assert result.exit_code == 0, result.output
    assert "+ AGENTS.md" in result.output
    assert "(new directory)" in result.output
    assert "Nothing written." in result.output
    assert not project.exists()


def test_confirming_writes_the_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answers_file: Path) -> None:
    project = tmp_path / "new" / "project"
    monkeypatch.setattr(cli, "_ask", replies(True))
    result = runner.invoke(app, ["init", str(project), "--answers", str(answers_file)])
    assert result.exit_code == 0, result.output
    assert (project / "AGENTS.md").exists()
    assert "Done." in result.output


def test_nothing_to_write_skips_the_confirmation(project: Path, answers_file: Path) -> None:
    runner.invoke(app, ["init", str(project), "--answers", str(answers_file), "--yes"])
    result = runner.invoke(app, ["init", str(project), "--answers", str(answers_file)])  # would block on a prompt
    assert result.exit_code == 0, result.output
    assert "Nothing to write" in result.output


# --- saved answers ------------------------------------------------------------------------


def test_answers_are_saved_even_when_declined(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    monkeypatch.setattr(cli, "interview", lambda _name, _previous=None: make_answers())
    monkeypatch.setattr(cli, "_ask", replies(False))
    result = runner.invoke(app, ["init", str(project)])
    assert result.exit_code == 0, result.output
    assert "Your answers are saved" in result.output
    assert cli._load_answers(cli.saved_answers_path(project.resolve())) == make_answers()


def test_use_saved_answers_as_they_are(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    save(project, make_answers())

    def no_interview(_name: str, _previous: Answers | None = None) -> Answers:
        raise AssertionError("'Use them as they are' should skip the interview")

    monkeypatch.setattr(cli, "interview", no_interview)
    monkeypatch.setattr(cli, "_ask", replies("use", True))
    result = runner.invoke(app, ["init", str(project)])

    assert result.exit_code == 0, result.output
    assert re.search(r"Project\s+acme-app", result.output)
    assert (project / "AGENTS.md").read_text().startswith("# acme-app")


@pytest.mark.parametrize(("choice", "prefilled"), [("edit", True), ("restart", False)])
def test_edit_prefills_the_interview_and_start_over_does_not(
    monkeypatch: pytest.MonkeyPatch, project: Path, choice: str, *, prefilled: bool
) -> None:
    saved = save(project, make_answers(name="old"))
    seen: list[Answers | None] = []

    def fake_interview(_name: str, previous: Answers | None = None) -> Answers:
        seen.append(previous)
        return make_answers(name="new")

    monkeypatch.setattr(cli, "interview", fake_interview)
    monkeypatch.setattr(cli, "_ask", replies(choice, False))
    result = runner.invoke(app, ["init", str(project)])

    assert result.exit_code == 0, result.output
    assert (seen[0] is not None) is prefilled
    assert cli._load_answers(saved).name == "new"


def test_saved_answers_are_kept_after_writing(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    saved = save(project, make_answers())
    monkeypatch.setattr(cli, "_ask", replies("use", True))
    runner.invoke(app, ["init", str(project)])
    assert saved.exists()


def test_answers_file_runs_save_nothing(project: Path, answers_file: Path, state_dir: Path) -> None:
    runner.invoke(app, ["init", str(project), "--answers", str(answers_file), "--yes"])
    assert not state_dir.exists()


def test_saved_answers_are_kept_per_directory(tmp_path: Path) -> None:
    assert cli.saved_answers_path(tmp_path / "a") != cli.saved_answers_path(tmp_path / "b")


def test_save_answers_option_writes_a_copy(monkeypatch: pytest.MonkeyPatch, project: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "interview", lambda _name, _previous=None: make_answers())
    copy = tmp_path / "copy.json"
    runner.invoke(app, ["init", str(project), "--save-answers", str(copy), "--yes"])
    assert cli._load_answers(copy) == make_answers()


# --- pre-filled interview -----------------------------------------------------------------


@pytest.fixture
def press_enter_everywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace questionary prompts with ones that accept their default, like pressing Enter."""
    monkeypatch.setattr(questionary, "text", lambda _m, default="", **_kw: FakeQuestion(default))
    monkeypatch.setattr(questionary, "confirm", lambda _m, default=True, **_kw: FakeQuestion(default))
    monkeypatch.setattr(
        questionary, "checkbox", lambda _m, choices, **_kw: FakeQuestion([c.value for c in choices if c.checked])
    )


@pytest.mark.usefixtures("press_enter_everywhere")
@pytest.mark.parametrize(
    "previous",
    [
        make_answers(architecture="Next.js calls FastAPI.", install_cmd="npm ci", lint_cmd=""),
        Answers.from_dict({**MINIMAL, "extensions": ["ex", "exs"], "test_cmd": "mix test"}),
        Answers.from_dict({"name": "idea", "description": "An idea.", "stack_undecided": True, "agents": []}),
    ],
)
def test_pressing_enter_through_a_prefilled_interview_keeps_every_answer(previous: Answers) -> None:
    assert cli.interview("folder-name", previous) == previous


@pytest.mark.usefixtures("press_enter_everywhere")
def test_fresh_interview_defaults_come_from_the_first_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    # No languages are ticked by default, so pick Python and accept everything else.
    monkeypatch.setattr(
        questionary,
        "checkbox",
        lambda message, choices, **_kw: FakeQuestion(
            ["python"] if message.startswith("Languages") else [c.value for c in choices if c.checked]
        ),
    )
    answers = cli.interview("folder-name")
    assert answers.name == "folder-name"
    assert answers.test_cmd == "pytest"
    assert answers.format_on_edit is True
    assert answers.agents == ["code-reviewer"]


@pytest.mark.usefixtures("press_enter_everywhere")
def test_switching_from_undecided_to_a_language_suggests_its_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    previous = Answers.from_dict({"name": "idea", "description": "", "stack_undecided": True})
    monkeypatch.setattr(
        questionary,
        "confirm",
        lambda m, default=True, **_kw: FakeQuestion(True if m.startswith("Do you know") else default),
    )
    monkeypatch.setattr(
        questionary,
        "checkbox",
        lambda message, choices, **_kw: FakeQuestion(
            ["go"] if message.startswith("Languages") else [c.value for c in choices if c.checked]
        ),
    )
    answers = cli.interview("idea", previous)
    assert answers.stacks == ["go"]
    assert answers.test_cmd == "go test ./..."


# --- scripted interviews ------------------------------------------------------------------


def test_interview_builds_answers(monkeypatch: pytest.MonkeyPatch, project: Path, tmp_path: Path) -> None:
    ask = replies(
        "shop",  # name
        "A shop.",  # description
        True,  # languages known
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
    )
    monkeypatch.setattr(cli, "_ask", ask)
    result = runner.invoke(app, ["init", str(project), "--yes"])

    assert result.exit_code == 0, result.output
    data = json.loads(cli.saved_answers_path(project.resolve()).read_text())
    assert data["extensions"] == ["ex", "exs"]
    assert data["format_on_edit"] is True
    assert (project / ".claude/hooks/format_on_edit.py").exists()
    with pytest.raises(StopIteration):
        ask(None)  # every scripted reply was used


def test_interview_with_an_undecided_stack_skips_stack_questions(
    monkeypatch: pytest.MonkeyPatch, project: Path
) -> None:
    ask = replies("habit", "A habit tracker for students.", False, "", "", True, [], [], True)
    monkeypatch.setattr(cli, "_ask", ask)
    result = runner.invoke(app, ["init", str(project), "--yes"])

    assert result.exit_code == 0, result.output
    data = json.loads(cli.saved_answers_path(project.resolve()).read_text())
    assert data["stack_undecided"] is True
    assert data["test_cmd"] == ""
    assert (project / ".claude/skills/choose-stack/SKILL.md").exists()
    with pytest.raises(StopIteration):
        ask(None)


# --- files and errors ---------------------------------------------------------------------


def test_reports_skipped_files_and_a_missing_import(project: Path, answers_file: Path) -> None:
    (project / "CLAUDE.md").write_text("mine\n")
    result = runner.invoke(app, ["init", str(project), "--answers", str(answers_file), "--yes"])
    assert result.exit_code == 0, result.output
    assert "CLAUDE.md  (skip)" in result.output
    assert "--force" in result.output
    assert "doesn't import AGENTS.md" in result.output


def test_no_import_warning_when_claude_md_imports_agents_md(project: Path, answers_file: Path) -> None:
    (project / "CLAUDE.md").write_text("@AGENTS.md\n\nmine\n")
    result = runner.invoke(app, ["init", str(project), "--answers", str(answers_file), "--yes"])
    assert result.exit_code == 0, result.output
    assert "doesn't import AGENTS.md" not in result.output


def test_invalid_answers_file_exits_with_error(project: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"name": "x", "description": "", "stacks": ["cobol"]}))
    result = runner.invoke(app, ["init", str(project), "--answers", str(bad)])
    assert result.exit_code == 1
    assert "unknown stack: cobol" in result.output


def test_a_file_path_is_rejected(tmp_path: Path, answers_file: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("")
    result = runner.invoke(app, ["init", str(target), "--answers", str(answers_file)])
    assert result.exit_code != 0
    assert "is a file, not a directory" in result.output


# --- summary and prompts ------------------------------------------------------------------


def test_summary_lists_answers_and_leaves_out_blanks() -> None:
    rows = dict(cli.summarize(make_answers()))
    assert rows["Languages"] == "TypeScript / JavaScript, Python"
    assert rows["Commands"] == "test `npm test` · lint `npm run lint` · format `npx prettier --write`"
    assert rows["MCP servers"] == "GitHub, Sentry"
    assert rows["Hooks"] == "block destructive commands, format on edit"
    assert "Architecture" not in rows


def test_summary_of_an_undecided_stack() -> None:
    rows = dict(cli.summarize(Answers.from_dict({"name": "idea", "description": "", "stack_undecided": True})))
    assert rows["Languages"] == "not decided yet (/choose-stack)"
    assert "Commands" not in rows
    assert rows["Subagents"] == "none"


def test_ask_returns_the_reply() -> None:
    assert cli._ask(FakeQuestion("yes")) == "yes"  # type: ignore[arg-type]  # duck-typed stand-in for questionary.Question


def test_ctrl_c_aborts() -> None:
    # questionary returns None when the user presses Ctrl-C.
    with pytest.raises(typer.Abort):
        cli._ask(FakeQuestion(None))  # type: ignore[arg-type]  # duck-typed stand-in for questionary.Question
