import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from agent_scaffold import cli
from agent_scaffold.cli import app
from agent_scaffold.generate import (
    MANIFEST,
    GeneratedFile,
    adopt_claude_md,
    blocks,
    generate,
    generate_workspace,
    refresh_blocks,
    replace_block,
)
from agent_scaffold.models import Answers, Service, Workspace, load_answers
from agent_scaffold.writer import plan

from .helpers import frontmatter, make_answers, make_workspace

runner = CliRunner()


def by_path(files: list[GeneratedFile]) -> dict[str, GeneratedFile]:
    return {f.path: f for f in files}


def write_all(root: Path, files: list[GeneratedFile]) -> None:
    for f in files:
        target = root / f.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content)


def reader(root: Path) -> Any:
    return lambda p: (root / p).read_text() if (root / p).is_file() else None


def assert_up_to_date(root: Path, ws: Workspace) -> None:
    """Running the generator again would change nothing on disk."""
    changes = {f.path: a for f, a in plan(generate_workspace(ws), root) if a != "unchanged"}
    assert changes == {}


# --- models -------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/abs", "~/x", "../up", "a/../b", "", "/", "./x"])
def test_service_folders_must_stay_inside_the_workspace(path: str) -> None:
    with pytest.raises(ValueError, match="relative path inside the workspace"):
        Service(path, make_answers())


def test_service_folder_is_normalized() -> None:
    service = Service("services/llm/", make_answers())
    assert service.path == "services/llm"
    assert service.depth == 2


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"layout": "galaxy"}, "unknown layout"),
        ({"name": " "}, "name is required"),
        ({"agents": ["intern"]}, "unknown agent"),
        (
            {"services": [Service("api", make_answers()), Service("api/", make_answers())]},
            "duplicate service folders: api",
        ),
        (
            {"services": [Service("api", make_answers()), Service("api/v2", make_answers())]},
            "can't be inside other services: api/v2",
        ),
    ],
)
def test_rejects_invalid_workspaces(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        make_workspace(**overrides)


def test_manifest_round_trips_and_keeps_shared_choices_out_of_services() -> None:
    ws = make_workspace(mcp_servers=["github"])
    data = ws.to_dict()
    assert "agents" not in data["services"][0]["answers"]
    assert load_answers(json.loads(json.dumps(data))) == Workspace.from_dict(data)
    assert Workspace.from_dict(data).to_dict() == data


def test_load_answers_tells_projects_and_workspaces_apart() -> None:
    assert isinstance(load_answers(make_answers().to_dict()), Answers)
    assert isinstance(load_answers(make_workspace().to_dict()), Workspace)
    with pytest.raises(ValueError, match="unknown fields: colour"):
        Workspace.from_dict({**make_workspace().to_dict(), "colour": "blue"})


def test_shared_choices_apply_to_every_service() -> None:
    ws = make_workspace(agents=["test-writer"], block_dangerous=False)
    answers = ws.service_answers(ws.services[0])
    assert answers.agents == ["test-writer"]
    assert answers.block_dangerous is False
    assert answers.test_cmd == "npm test"


# --- generation ---------------------------------------------------------------------------


def test_root_has_the_system_files_and_each_service_its_own_scaffold() -> None:
    files = by_path(generate_workspace(make_workspace()))
    for path in (
        MANIFEST,
        "AGENTS.md",
        "CLAUDE.md",
        ".claude/settings.json",
        ".claude/rules/humane-design.md",
        ".claude/skills/new-service/SKILL.md",
        "backend/AGENTS.md",
        "backend/.claude/rules/backend.md",
        "backend/.claude/skills/ship/SKILL.md",
        "services/llm/.claude/rules/llm.md",
        "services/llm/.claude/skills/choose-stack/SKILL.md",
    ):
        assert path in files, path
    assert ".claude/skills/ship/SKILL.md" not in files  # shipping happens per service


def test_manifest_file_is_the_workspace_answers() -> None:
    ws = make_workspace()
    assert json.loads(by_path(generate_workspace(ws))[MANIFEST].content) == ws.to_dict()


@pytest.mark.parametrize(("layout", "ignored"), [("repos", True), ("monorepo", False)])
def test_separate_repos_are_ignored_by_the_workspace_repo(layout: str, *, ignored: bool) -> None:
    gitignore = by_path(generate_workspace(make_workspace(layout=layout)))[".gitignore"]
    assert gitignore.merge_lines
    assert ("/backend/" in gitignore.content.splitlines()) is ignored
    assert ("/services/llm/" in gitignore.content.splitlines()) is ignored


def test_root_agents_md_has_goal_services_and_rules() -> None:
    agents = by_path(generate_workspace(make_workspace()))["AGENTS.md"].content
    assert "## Goal\n\nHelp students build lasting study habits." in agents
    assert "| backend | `backend/` | Backend / API | TypeScript / JavaScript | `npm test` |" in agents
    assert "| llm | `services/llm/` | LLM / AI service | not decided yet | none yet |" in agents
    assert "`agent-scaffold add-service <folder>`" in agents
    assert set(blocks(agents)) == {"services", "workspace-rules", "principles"}


def test_table_cells_escape_pipes() -> None:
    ws = make_workspace(
        services=[Service("api", Answers(name="a|b", description="", stacks=["go"], test_cmd="go test | tee"))]
    )
    agents = by_path(generate_workspace(ws))["AGENTS.md"].content
    assert "| a\\|b |" in agents
    assert "`go test \\| tee`" in agents


@pytest.mark.parametrize(("path", "root"), [("backend", "../AGENTS.md"), ("services/llm", "../../AGENTS.md")])
def test_each_service_knows_its_system_and_goal(path: str, root: str) -> None:
    agents = by_path(generate_workspace(make_workspace()))[f"{path}/AGENTS.md"].content
    system = blocks(agents)["system"]
    assert "Part of **acme**. Goal: Help students build lasting study habits." in system
    assert f"`{root}`" in system


def test_principles_are_identical_everywhere() -> None:
    files = by_path(generate_workspace(make_workspace()))
    single = blocks(by_path(generate(make_answers()))["AGENTS.md"].content)["principles"]
    for path in ("AGENTS.md", "backend/AGENTS.md", "services/llm/AGENTS.md"):
        assert blocks(files[path].content)["principles"] == single


@pytest.mark.parametrize("skill", ["plan", "review", "new-service"])
def test_root_skills_are_user_invoked(skill: str) -> None:
    content = by_path(generate_workspace(make_workspace()))[f".claude/skills/{skill}/SKILL.md"].content
    meta = frontmatter(content)
    assert meta["name"] == skill
    assert meta["disable-model-invocation"] == "true"


@pytest.mark.parametrize(
    ("layout", "command"),
    [("repos", "git -C services/llm diff HEAD"), ("monorepo", "git diff HEAD -- services/llm")],
)
def test_review_skill_diffs_each_service_for_its_layout(layout: str, command: str) -> None:
    review = by_path(generate_workspace(make_workspace(layout=layout)))[".claude/skills/review/SKILL.md"].content
    assert command in review


# --- managed blocks -----------------------------------------------------------------------


def test_replace_block_leaves_everything_else_untouched() -> None:
    text = "intro\n<!-- agent-scaffold:x -->\nold\n<!-- /agent-scaffold:x -->\noutro\n"
    new = "<!-- agent-scaffold:x -->\nnew\n<!-- /agent-scaffold:x -->"
    assert replace_block(text, "x", new) == "intro\n" + new + "\noutro\n"
    assert replace_block("no markers\n", "x", new) is None


@pytest.fixture
def workspace_on_disk(tmp_path: Path) -> tuple[Path, list[GeneratedFile]]:
    files = generate_workspace(make_workspace())
    write_all(tmp_path, files)
    return tmp_path, files


def test_nothing_to_refresh_on_a_fresh_workspace(workspace_on_disk: tuple[Path, list[GeneratedFile]]) -> None:
    root, files = workspace_on_disk
    assert refresh_blocks(files, reader(root)) == {}


def test_refresh_updates_every_stale_block_and_keeps_the_rest(
    workspace_on_disk: tuple[Path, list[GeneratedFile]],
) -> None:
    root, files = workspace_on_disk
    agents = root / "AGENTS.md"
    agents.write_text(
        agents.read_text().replace("| llm |", "| x |").replace("## How to work", "## How we work") + "\nMy notes.\n"
    )
    refreshed = refresh_blocks(files, reader(root))
    assert list(refreshed) == ["AGENTS.md"]
    assert refreshed["AGENTS.md"] == by_path(files)["AGENTS.md"].content + "\nMy notes.\n"


def test_files_without_markers_are_not_refreshed(workspace_on_disk: tuple[Path, list[GeneratedFile]]) -> None:
    root, files = workspace_on_disk
    (root / "backend/AGENTS.md").write_text("# backend\n\nRewritten by hand.\n")
    (root / ".gitignore").write_text("node_modules\n")  # merged, never refreshed
    assert refresh_blocks(files, reader(root)) == {}


# --- existing CLAUDE.md -------------------------------------------------------------------


def test_adopting_a_service_claude_md_keeps_the_system_block() -> None:
    files = generate_workspace(make_workspace())
    mine = "# backend\n\nOur API rules.\n"
    agents = by_path(adopt_claude_md(files, mine, "backend"))["backend/AGENTS.md"].content
    assert agents.startswith("# backend\n\n<!-- agent-scaffold:system -->")
    assert "\n\nOur API rules.\n\n<!-- agent-scaffold:principles -->" in agents


# --- commands -----------------------------------------------------------------------------


def replies(*values: Any) -> Any:
    queue = iter(values)
    return lambda _question: next(queue)


@pytest.mark.usefixtures("press_enter_everywhere")
def test_pressing_enter_through_a_prefilled_workspace_interview_keeps_it() -> None:
    previous = Workspace.from_dict(make_workspace(mcp_servers=["github"]).to_dict())
    assert cli.workspace_interview("folder", previous).to_dict() == previous.to_dict()


def test_init_a_workspace_from_the_interview(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "acme"
    monkeypatch.setattr(
        cli,
        "_ask",
        replies(
            "workspace",  # what are you setting up
            "acme",  # name
            "Help students study.",  # goal
            "repos",  # layout
            True,  # add a service now
            "backend",  # service folder
            "backend",  # service name
            "",  # description
            "backend",  # role
            True,  # languages known
            ["typescript"],  # languages
            "",  # frameworks
            "",  # architecture
            "",  # conventions
            "",  # install
            "",  # dev
            "npm test",  # test
            "",  # lint
            "",  # format
            True,  # add another service
            "llm",  # service folder
            "llm",  # service name
            "",  # description
            "llm",  # role
            False,  # languages known
            "",  # architecture
            "",  # conventions
            False,  # add another service
            "",  # how they talk
            "",  # contracts
            [],  # MCP servers
            ["code-reviewer"],  # agents
            True,  # block dangerous
            True,  # write these files
        ),
    )
    result = runner.invoke(app, ["init", str(root)])

    assert result.exit_code == 0, result.output
    assert (root / "llm/.claude/rules/llm.md").exists()
    assert Workspace.from_dict(json.loads((root / MANIFEST).read_text())).name == "acme"
    assert "make each of these a git repository" in result.output
    assert_up_to_date(root, cli._load_workspace(root))


def test_init_offers_an_existing_workspace_manifest(
    monkeypatch: pytest.MonkeyPatch, workspace_on_disk: tuple[Path, list[GeneratedFile]]
) -> None:
    root, _ = workspace_on_disk
    monkeypatch.setattr(cli, "_ask", replies("use"))
    result = runner.invoke(app, ["init", str(root)])
    assert result.exit_code == 0, result.output
    assert "Saved answers for" in result.output
    assert "Workspace" in result.output
    assert "Nothing to write" in result.output


def test_add_service_updates_the_manifest_and_the_services_table(
    monkeypatch: pytest.MonkeyPatch, workspace_on_disk: tuple[Path, list[GeneratedFile]]
) -> None:
    root, _ = workspace_on_disk
    agents = root / "AGENTS.md"
    agents.write_text(agents.read_text() + "\nMy own notes.\n")
    monkeypatch.setattr(
        cli,
        "_ask",
        replies("data", "data", "", "data", True, ["python"], "", "", "", "", "", "pytest", "", "", True),
    )
    result = runner.invoke(app, ["add-service", "data", "--workspace", str(root)])

    assert result.exit_code == 0, result.output
    assert "AGENTS.md  (refresh)" in result.output
    assert ".claude/skills/review/SKILL.md  (refresh)" in result.output
    assert "git -C data diff HEAD" in (root / ".claude/skills/review/SKILL.md").read_text()
    assert (root / "data/.claude/rules/data.md").exists()
    assert "| data | `data/` | Data pipeline | Python | `pytest` |" in agents.read_text()
    assert agents.read_text().endswith("\nMy own notes.\n")
    assert "/data/" in (root / ".gitignore").read_text().splitlines()
    assert [s.path for s in cli._load_workspace(root).services] == ["backend", "services/llm", "data"]


def test_add_service_edits_an_existing_service(
    monkeypatch: pytest.MonkeyPatch, workspace_on_disk: tuple[Path, list[GeneratedFile]], press_enter_everywhere: None
) -> None:
    root, _ = workspace_on_disk
    result = runner.invoke(app, ["add-service", "backend", "--workspace", str(root), "--yes"])
    assert result.exit_code == 0, result.output
    assert "already a service" in result.output
    assert [s.path for s in cli._load_workspace(root).services] == ["services/llm", "backend"]


def test_add_service_rejects_a_bad_folder(
    monkeypatch: pytest.MonkeyPatch, workspace_on_disk: tuple[Path, list[GeneratedFile]]
) -> None:
    root, _ = workspace_on_disk
    monkeypatch.setattr(cli, "service_interview", lambda *_a: Service("backend/api", make_answers()))
    result = runner.invoke(app, ["add-service", "backend/api", "--workspace", str(root)])
    assert result.exit_code == 1
    assert "can't be inside other services" in result.output


def test_summary_lists_each_service() -> None:
    rows = dict(cli.summarize(make_workspace()))
    assert rows["Workspace"] == "acme"
    assert rows["backend/"] == "Backend / API · TypeScript / JavaScript"
    assert rows["services/llm/"] == "LLM / AI service · not decided yet (/choose-stack)"
    assert rows["Subagents"] == "code-reviewer"


def test_editing_saved_workspace_answers_reopens_the_workspace_interview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "acme"
    saved = cli.saved_answers_path(root.resolve())
    saved.parent.mkdir(parents=True)
    saved.write_text(json.dumps(make_workspace().to_dict()))
    seen: list[Workspace | None] = []

    def fake(_name: str, previous: Workspace | None = None) -> Workspace:
        seen.append(previous)
        return make_workspace(goal="A new goal.")

    monkeypatch.setattr(cli, "workspace_interview", fake)
    monkeypatch.setattr(cli, "_ask", replies("edit", False))
    result = runner.invoke(app, ["init", str(root)])

    assert result.exit_code == 0, result.output
    assert seen[0] is not None
    assert seen[0].name == "acme"
    assert Workspace.from_dict(json.loads(saved.read_text())).goal == "A new goal."


# --- starting without services ------------------------------------------------------------


def test_a_workspace_can_start_with_no_services(tmp_path: Path) -> None:
    ws = make_workspace(services=[])
    files = by_path(generate_workspace(ws))
    assert not any("/" in path and not path.startswith(".claude/") for path in files)
    agents = files["AGENTS.md"].content
    assert "No services yet. Add the first with `agent-scaffold add-service <folder>`." in agents
    assert "| Service |" not in agents
    assert "No services yet." in files[".claude/skills/review/SKILL.md"].content
    assert dict(cli.summarize(ws))["Services"] == "none yet"
    write_all(tmp_path, list(files.values()))
    assert_up_to_date(tmp_path, ws)


def test_interview_can_skip_services(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "_ask",
        replies("acme", "", "monorepo", False, "", "", [], ["code-reviewer"], True),
    )
    ws = cli.workspace_interview("acme")
    assert ws.services == []
    assert ws.agents == ["code-reviewer"]


@pytest.mark.usefixtures("press_enter_everywhere")
def test_enter_through_an_empty_workspace_keeps_it_empty() -> None:
    previous = make_workspace(services=[])
    assert cli.workspace_interview("acme", previous).to_dict() == previous.to_dict()


def test_first_service_added_later_fills_in_the_table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    write_all(tmp_path, generate_workspace(make_workspace(services=[])))
    monkeypatch.setattr(cli, "_ask", replies("llm", "llm", "", "llm", False, "", "", True))
    result = runner.invoke(app, ["add-service", "llm", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    agents = (tmp_path / "AGENTS.md").read_text()
    assert "No services yet" not in agents
    assert "| llm | `llm/` | LLM / AI service | not decided yet | none yet |" in agents
    assert (tmp_path / "llm/.claude/rules/llm.md").exists()
    assert_up_to_date(tmp_path, cli._load_workspace(tmp_path))


def test_add_service_needs_a_workspace(tmp_path: Path) -> None:
    result = runner.invoke(app, ["add-service", "x", "--workspace", str(tmp_path)])
    assert result.exit_code == 1
    assert f"No {MANIFEST}" in result.output


def test_add_service_reports_an_invalid_manifest(tmp_path: Path) -> None:
    (tmp_path / MANIFEST).write_text('{"name": "x"}')
    result = runner.invoke(app, ["add-service", "x", "--workspace", str(tmp_path)])
    assert result.exit_code == 1
    assert f"Invalid {MANIFEST}" in result.output


# --- choosing a service's stack later -----------------------------------------------------


def test_choose_stack_in_a_workspace_updates_the_blueprint_too() -> None:
    files = by_path(generate_workspace(make_workspace()))
    skill = files["services/llm/.claude/skills/choose-stack/SKILL.md"].content
    assert f"`../../{MANIFEST}`" in skill
    assert 'whose `path` is `"services/llm"`' in skill
    assert f"`agent-scaffold init ../.. --answers ../../{MANIFEST} --yes`" in skill
    assert "`python`" in skill  # the valid stack keys are listed
    single = by_path(generate(make_answers(stack_undecided=True, stacks=[], format_on_edit=False)))
    assert MANIFEST not in single[".claude/skills/choose-stack/SKILL.md"].content


def test_the_command_choose_stack_runs_refreshes_the_table_and_keeps_edits(
    workspace_on_disk: tuple[Path, list[GeneratedFile]],
) -> None:
    root, _ = workspace_on_disk
    # What Claude does at the end of /choose-stack: edit the service's files, then its blueprint entry.
    style = root / "services/llm/.claude/rules/code-style.md"
    style.write_text('---\npaths:\n  - "**/*.py"\n---\n\n# Code style\n\n- Edited by /choose-stack.\n')
    manifest = root / MANIFEST
    data = json.loads(manifest.read_text())
    llm = next(s for s in data["services"] if s["path"] == "services/llm")
    llm["answers"].update(stack_undecided=False, stacks=["python"], test_cmd="pytest")
    manifest.write_text(json.dumps(data, indent=2))

    result = runner.invoke(app, ["init", str(root / "services/llm/../.."), "--answers", str(manifest), "--yes"])

    assert result.exit_code == 0, result.output
    assert "| llm | `services/llm/` | LLM / AI service | Python | `pytest` |" in (root / "AGENTS.md").read_text()
    assert style.read_text().endswith("- Edited by /choose-stack.\n")


def test_monorepo_service_ci_lives_at_the_repository_root() -> None:
    files = by_path(generate_workspace(make_workspace(layout="monorepo")))
    ci = files["services/llm/.claude/skills/ci/SKILL.md"].content
    assert "`../../.github/workflows/ci-services-llm.yml`" in ci
    assert "`services/llm/**`" in ci
    assert "working-directory: services/llm" in ci


def test_service_in_its_own_repo_has_a_plain_ci_workflow() -> None:
    ci = by_path(generate_workspace(make_workspace(layout="repos")))["backend/.claude/skills/ci/SKILL.md"].content
    assert "`.github/workflows/ci.yml`" in ci
    assert "working-directory" not in ci


@pytest.mark.usefixtures("press_enter_everywhere")
def test_enter_through_a_new_workspace_asks_no_service_or_stack_questions() -> None:
    ws = cli.workspace_interview("acme")
    assert ws.services == []
