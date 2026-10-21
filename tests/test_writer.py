from pathlib import Path

from agent_scaffold.generate import GeneratedFile, generate
from agent_scaffold.writer import plan, write

from .helpers import make_answers


def actions_by_path(files: list[GeneratedFile], root: Path, *, force: bool = False) -> dict[str, str]:
    return {f.path: action for f, action in plan(files, root, force=force)}


def test_creates_everything_in_an_empty_directory(tmp_path: Path) -> None:
    files = generate(make_answers())
    write(plan(files, tmp_path), tmp_path)
    for f in files:
        assert (tmp_path / f.path).read_text() == f.content


def test_skips_existing_files_unless_forced(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("hand-written\n")
    files = generate(make_answers())

    assert actions_by_path(files, tmp_path)["CLAUDE.md"] == "skip"
    write(plan(files, tmp_path), tmp_path)
    assert (tmp_path / "CLAUDE.md").read_text() == "hand-written\n"

    assert actions_by_path(files, tmp_path, force=True)["CLAUDE.md"] == "overwrite"
    write(plan(files, tmp_path, force=True), tmp_path)
    assert (tmp_path / "CLAUDE.md").read_text().startswith("# acme-app")


def test_merges_gitignore_lines(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("node_modules\nCLAUDE.local.md")  # no trailing newline
    files = generate(make_answers())
    assert actions_by_path(files, tmp_path)[".gitignore"] == "merge"
    write(plan(files, tmp_path), tmp_path)
    assert (tmp_path / ".gitignore").read_text() == "node_modules\nCLAUDE.local.md\n.claude/settings.local.json\n"


def test_second_run_changes_nothing(tmp_path: Path) -> None:
    files = generate(make_answers())
    write(plan(files, tmp_path), tmp_path)
    assert set(actions_by_path(files, tmp_path).values()) == {"unchanged"}
