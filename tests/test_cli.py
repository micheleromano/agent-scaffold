import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import questionary
import typer
from typer.testing import CliRunner

from agent_scaffold import cli, questions, ui
from agent_scaffold.cli import app
from agent_scaffold.models import Answers

from .helpers import MINIMAL, FakeQuestion, make_answers

runner = CliRunner()


def plain(output: str) -> str:
    """Typer's error box without colors, borders or line wrapping, which vary with the terminal (e.g. on CI)."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", output)
    return " ".join(text.replace("│", " ").split())


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


def replies(*values: Any) -> Callable[[Any], Any]:
    """A stand-in for ui.ask that answers each question in turn and fails if asked too many."""
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
    monkeypatch.setattr(ui, "ask", replies(False))  # "Write these files?"
    result = runner.invoke(app, ["init", str(project), "--answers", str(answers_file)])
    assert result.exit_code == 0, result.output
    assert "+ AGENTS.md" in result.output
    assert "(new directory)" in result.output
    assert "Nothing written." in result.output
    assert not project.exists()


def test_confirming_writes_the_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answers_file: Path) -> None:
    project = tmp_path / "new" / "project"
    monkeypatch.setattr(ui, "ask", replies(True))
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
    monkeypatch.setattr(questions, "interview", lambda _name, _previous=None: make_answers())
    monkeypatch.setattr(ui, "ask", replies("project", False))
    result = runner.invoke(app, ["init", str(project)])
    assert result.exit_code == 0, result.output
    assert "Your answers are saved" in result.output
    assert cli._load_answers(cli.saved_answers_path(project.resolve())) == make_answers()


def test_use_saved_answers_as_they_are(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    save(project, make_answers())

    def no_interview(_name: str, _previous: Answers | None = None) -> Answers:
        raise AssertionError("'Use them as they are' should skip the interview")

    monkeypatch.setattr(questions, "interview", no_interview)
    monkeypatch.setattr(ui, "ask", replies("use", True))
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

    monkeypatch.setattr(questions, "interview", fake_interview)
    # Starting over asks whether it's a project or a workspace; editing keeps the kind.
    monkeypatch.setattr(ui, "ask", replies(choice, False) if choice == "edit" else replies(choice, "project", False))
    result = runner.invoke(app, ["init", str(project)])

    assert result.exit_code == 0, result.output
    assert (seen[0] is not None) is prefilled
    assert cli._load_answers(saved).name == "new"


def test_saved_answers_are_kept_after_writing(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    saved = save(project, make_answers())
    monkeypatch.setattr(ui, "ask", replies("use", True))
    runner.invoke(app, ["init", str(project)])
    assert saved.exists()


def test_answers_file_runs_save_nothing(project: Path, answers_file: Path, state_dir: Path) -> None:
    runner.invoke(app, ["init", str(project), "--answers", str(answers_file), "--yes"])
    assert not state_dir.exists()


def test_saved_answers_are_kept_per_directory(tmp_path: Path) -> None:
    assert cli.saved_answers_path(tmp_path / "a") != cli.saved_answers_path(tmp_path / "b")


def test_save_answers_option_writes_a_copy(monkeypatch: pytest.MonkeyPatch, project: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(questions, "interview", lambda _name, _previous=None: make_answers())
    monkeypatch.setattr(ui, "ask", replies("project"))
    copy = tmp_path / "copy.json"
    runner.invoke(app, ["init", str(project), "--save-answers", str(copy), "--yes"])
    assert cli._load_answers(copy) == make_answers()


# --- pre-filled interview -----------------------------------------------------------------


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
    assert questions.interview("folder-name", previous) == previous


@pytest.mark.usefixtures("press_enter_everywhere")
def test_fresh_interview_defaults_follow_the_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(questionary, "select", lambda _m, choices, default=None, **_kw: FakeQuestion("llm"))
    answers = questions.interview("bot")
    assert answers.role == "llm"
    assert answers.stacks == ["python"]  # the llm role's usual stack is pre-ticked
    assert answers.agents == ["code-reviewer", "security-auditor"]


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
    answers = questions.interview("folder-name")
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
    answers = questions.interview("idea", previous)
    assert answers.stacks == ["go"]
    assert answers.test_cmd == "go test ./..."


# --- scripted interviews ------------------------------------------------------------------


def test_interview_builds_answers(monkeypatch: pytest.MonkeyPatch, project: Path, tmp_path: Path) -> None:
    ask = replies(
        "project",  # what are you setting up
        "shop",  # name
        "A shop.",  # description
        "other",  # role
        True,  # languages known
        ["other"],  # languages: "Other (not listed)"
        "ex, exs",  # its file extensions
        "Phoenix",  # frameworks
        "",  # architecture
        "",  # conventions
        "mix deps.get",  # install
        "mix phx.server",  # dev
        "mix test",  # test
        "mix credo",  # lint
        "mix format",  # format
        True,  # format on edit
        ["github"],  # MCP servers
        ["code-reviewer"],  # agents
        True,  # block dangerous
    )
    monkeypatch.setattr(ui, "ask", ask)
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
    ask = replies("project", "habit", "A habit tracker for students.", "backend", False, "", "", [], [], True)
    monkeypatch.setattr(ui, "ask", ask)
    result = runner.invoke(app, ["init", str(project), "--yes"])

    assert result.exit_code == 0, result.output
    data = json.loads(cli.saved_answers_path(project.resolve()).read_text())
    assert data["stack_undecided"] is True
    assert data["test_cmd"] == ""
    assert (project / ".claude/skills/choose-stack/SKILL.md").exists()
    with pytest.raises(StopIteration):
        ask(None)


# --- existing files -----------------------------------------------------------------------


@pytest.fixture
def existing_claude_md(project: Path) -> Path:
    path = project / "CLAUDE.md"
    path.write_text("# treesdolisten\n\nA frozen static blog.\n")
    return path


def run_with(monkeypatch: pytest.MonkeyPatch, project: Path, answers_file: Path, *choices: Any) -> str:
    monkeypatch.setattr(ui, "ask", replies(*choices))
    result = runner.invoke(app, ["init", str(project), "--answers", str(answers_file)])
    assert result.exit_code == 0, result.output
    return result.output


def test_keep_my_claude_md(
    monkeypatch: pytest.MonkeyPatch, project: Path, answers_file: Path, existing_claude_md: Path
) -> None:
    output = run_with(monkeypatch, project, answers_file, "keep", True)
    assert "CLAUDE.md already exists." in output
    assert existing_claude_md.read_text() == "# treesdolisten\n\nA frozen static blog.\n"
    assert "Kept your version of 1 file." in output
    assert "doesn't import AGENTS.md" in output


def test_move_my_claude_md_into_agents_md(
    monkeypatch: pytest.MonkeyPatch, project: Path, answers_file: Path, existing_claude_md: Path
) -> None:
    output = run_with(monkeypatch, project, answers_file, "adopt", True)
    agents = (project / "AGENTS.md").read_text()
    assert agents.startswith("# treesdolisten\n\nA frozen static blog.\n")
    assert "## How to work" in agents
    assert existing_claude_md.read_text().startswith("@AGENTS.md\n")
    assert "CLAUDE.md  (overwrite)" in output
    assert "doesn't import AGENTS.md" not in output


def test_replace_my_claude_md(
    monkeypatch: pytest.MonkeyPatch, project: Path, answers_file: Path, existing_claude_md: Path
) -> None:
    run_with(monkeypatch, project, answers_file, "replace", True)
    assert existing_claude_md.read_text().startswith("@AGENTS.md\n")
    assert (project / "AGENTS.md").read_text().startswith("# acme-app")


def test_show_the_difference_then_choose(
    monkeypatch: pytest.MonkeyPatch, project: Path, answers_file: Path, existing_claude_md: Path
) -> None:
    output = run_with(monkeypatch, project, answers_file, "diff", "keep", True)
    assert "CLAUDE.md (yours)" in output
    assert "-# treesdolisten" in output
    assert "+@AGENTS.md" in output
    assert existing_claude_md.read_text().startswith("# treesdolisten")


def test_each_existing_file_gets_its_own_choice(
    monkeypatch: pytest.MonkeyPatch, project: Path, answers_file: Path, existing_claude_md: Path
) -> None:
    settings = project / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text("{}\n")
    output = run_with(monkeypatch, project, answers_file, "keep", "replace", True)  # CLAUDE.md, then settings.json
    assert ".claude/settings.json already exists." in output
    assert existing_claude_md.read_text().startswith("# treesdolisten")
    assert json.loads(settings.read_text())["$schema"]


def test_yes_keeps_existing_files_without_asking(project: Path, answers_file: Path, existing_claude_md: Path) -> None:
    result = runner.invoke(app, ["init", str(project), "--answers", str(answers_file), "--yes"])
    assert result.exit_code == 0, result.output
    assert "already exists" not in result.output
    assert existing_claude_md.read_text().startswith("# treesdolisten")


def test_force_replaces_existing_files_without_asking(
    project: Path, answers_file: Path, existing_claude_md: Path
) -> None:
    result = runner.invoke(app, ["init", str(project), "--answers", str(answers_file), "--force", "--yes"])
    assert result.exit_code == 0, result.output
    assert "already exists" not in result.output
    assert existing_claude_md.read_text().startswith("@AGENTS.md")


# --- files and errors ---------------------------------------------------------------------


def test_reports_skipped_files_and_a_missing_import(project: Path, answers_file: Path) -> None:
    (project / "CLAUDE.md").write_text("mine\n")
    result = runner.invoke(app, ["init", str(project), "--answers", str(answers_file), "--yes"])
    assert result.exit_code == 0, result.output
    assert "CLAUDE.md  (keeping yours)" in result.output
    assert "Kept 1 file that already existed" in result.output
    assert "Run without --yes to compare" in result.output
    assert "--force" not in result.output
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
    assert "is a file, not a directory" in plain(result.output)


# --- summary and prompts ------------------------------------------------------------------


def test_summary_lists_answers_and_leaves_out_blanks() -> None:
    rows = dict(ui.summarize(make_answers()))
    assert rows["Languages"] == "TypeScript / JavaScript, Python"
    assert rows["Commands"] == "test `npm test` · lint `npm run lint` · format `npx prettier --write`"
    assert rows["MCP servers"] == "GitHub, Sentry"
    assert rows["Hooks"] == "block destructive commands, format on edit"
    assert rows["Role"] == "Backend / API"
    assert "Architecture" not in rows


def test_summary_of_an_undecided_stack() -> None:
    rows = dict(ui.summarize(Answers.from_dict({"name": "idea", "description": "", "stack_undecided": True})))
    assert rows["Languages"] == "not decided yet (/choose-stack)"
    assert "Commands" not in rows
    assert rows["Subagents"] == "none"


def test_ask_returns_the_reply() -> None:
    assert ui.ask(FakeQuestion("yes")) == "yes"  # type: ignore[arg-type]  # duck-typed stand-in for questionary.Question


def test_ctrl_c_aborts() -> None:
    # questionary returns None when the user presses Ctrl-C.
    with pytest.raises(typer.Abort):
        ui.ask(FakeQuestion(None))  # type: ignore[arg-type]  # duck-typed stand-in for questionary.Question
