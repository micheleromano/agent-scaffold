"""Command line: interview the user, then write the Claude Code project files."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
from typing import Annotated, Any

import questionary
import typer

from .generate import AGENTS_IMPORT, GeneratedFile, adopt_claude_md, can_adopt_claude_md, generate
from .models import AGENTS, MCP_SERVERS, STACKS, Answers, Stack
from .writer import plan, write

app = typer.Typer(help="Set up Claude Code project files by answering a few questions.", no_args_is_help=True)

ACTION_STYLE = {
    "create": ("+", typer.colors.GREEN),
    "overwrite": ("~", typer.colors.YELLOW),
    "merge": ("~", typer.colors.YELLOW),
    "skip": ("!", typer.colors.RED),
    "unchanged": ("=", None),
}


def _ask(question: questionary.Question) -> Any:
    answer = question.ask()
    if answer is None:  # Ctrl-C
        raise typer.Abort()
    return answer


def saved_answers_path(root: Path) -> Path:
    """Where the latest answers for `root` are kept, outside the project so nothing lands there before you confirm."""
    state = os.environ.get("AGENT_SCAFFOLD_STATE_DIR") or Path.home() / ".local" / "state" / "agent-scaffold"
    key = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    return Path(state) / "answers" / f"{key}.json"


def summarize(a: Answers) -> list[tuple[str, str]]:
    """The answers as label/value rows, leaving out anything blank."""
    commands = [
        f"{label} `{cmd}`"
        for label, cmd in (
            ("install", a.install_cmd),
            ("run", a.dev_cmd),
            ("test", a.test_cmd),
            ("lint", a.lint_cmd),
            ("format", a.format_cmd),
        )
        if cmd
    ]
    hooks = [
        label
        for label, on in (("block destructive commands", a.block_dangerous), ("format on edit", a.format_on_edit))
        if on
    ]
    rows = [
        ("Project", a.name),
        ("Description", a.description),
        ("Languages", "not decided yet (/choose-stack)" if a.stack_undecided else ", ".join(a.languages)),
        ("Frameworks", a.frameworks),
        ("Architecture", a.architecture),
        ("Conventions", a.conventions),
        ("Commands", " · ".join(commands)),
        ("API", "yes" if a.has_api else "no"),
        ("MCP servers", ", ".join(MCP_SERVERS[k].label for k in a.mcp_servers) or "none"),
        ("Subagents", ", ".join(a.agents) or "none"),
        ("Hooks", ", ".join(hooks) or "none"),
    ]
    return [(label, value) for label, value in rows if value]


def _show(a: Answers) -> None:
    rows = summarize(a)
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        typer.echo(f"  {label.ljust(width)}  {value}")


def _load_answers(path: Path) -> Answers:
    return Answers.from_dict(json.loads(path.read_text()))


def _show_diff(existing: str, generated: str, path: str) -> None:
    diff = difflib.unified_diff(
        existing.splitlines(), generated.splitlines(), f"{path} (yours)", f"{path} (generated)", lineterm=""
    )
    for line in diff:
        color = typer.colors.GREEN if line.startswith("+") else typer.colors.RED if line.startswith("-") else None
        typer.secho(f"    {line}", fg=color)


def resolve_conflicts(files: list[GeneratedFile], root: Path) -> tuple[list[GeneratedFile], frozenset[str]]:
    """Ask what to do with each generated file that already exists with different content.

    Returns the files (AGENTS.md changes if the user moves their CLAUDE.md into it) and the paths to overwrite.
    """
    overwrite: set[str] = set()
    for f in [f for f, action in plan(files, root) if action == "skip"]:
        existing = (root / f.path).read_text()
        choices = [questionary.Choice("Keep mine", value="keep")]
        if f.path == "CLAUDE.md" and can_adopt_claude_md(existing, (root / "AGENTS.md").exists()):
            choices.append(questionary.Choice("Move mine into AGENTS.md and import it (recommended)", value="adopt"))
        choices += [
            questionary.Choice("Replace it with the generated version", value="replace"),
            questionary.Choice("Show the difference", value="diff"),
        ]
        typer.echo(f"\n{f.path} already exists.")
        while (choice := _ask(questionary.select("What do you want to do with it?", choices=choices))) == "diff":
            _show_diff(existing, f.content, f.path)
        if choice == "adopt":
            files = adopt_claude_md(files, existing)
            overwrite.add(f.path)
            typer.echo("  Your CLAUDE.md becomes AGENTS.md; the new CLAUDE.md imports it.")
        elif choice == "replace":
            overwrite.add(f.path)
    return files, frozenset(overwrite)


def _choices(catalog: dict[str, Any], label: Any, checked: tuple[str, ...] = ()) -> list[questionary.Choice]:
    return [questionary.Choice(label(v), value=k, checked=k in checked) for k, v in catalog.items()]


def interview(default_name: str, previous: Answers | None = None) -> Answers:
    """Ask the questions. With `previous`, every question starts at its old answer so Enter keeps it."""
    p = previous
    name = _ask(questionary.text("Project name:", default=p.name if p else default_name))
    description = _ask(
        questionary.text("What does it do, and who is it for? (a sentence or two):", default=p.description if p else "")
    )
    stack_undecided = not _ask(
        questionary.confirm(
            "Do you know which languages it will use? (No: Claude helps you choose later with /choose-stack)",
            default=not p.stack_undecided if p else True,
        )
    )
    stacks: list[str] = []
    primary: Stack | None = None
    extensions_text = frameworks = install_cmd = dev_cmd = test_cmd = lint_cmd = format_cmd = ""
    if not stack_undecided:
        stacks = _ask(
            questionary.checkbox(
                "Languages with presets:",
                choices=_choices(STACKS, lambda s: s.label, checked=tuple(p.stacks) if p else ()),
            )
        )
        extensions_text = _ask(
            questionary.text(
                "File extensions for other languages, comma separated (e.g. ex, exs):",
                default=", ".join(p.extensions) if p else "",
                validate=lambda v: bool(stacks or v.strip()) or "Pick a language above or enter an extension",
            )
        )
        primary = STACKS[stacks[0]] if stacks else None
        frameworks = _ask(
            questionary.text("Main frameworks and libraries (optional):", default=p.frameworks if p else "")
        )
    architecture = _ask(
        questionary.text("Architecture in a sentence or two (optional):", default=p.architecture if p else "")
    )
    conventions = _ask(
        questionary.text("Conventions people get wrong most often (optional):", default=p.conventions if p else "")
    )
    if not stack_undecided:
        # Keep earlier commands exactly (even blank ones); otherwise suggest the first language's preset.
        kept = p if p and not p.stack_undecided else None
        install_cmd = _ask(questionary.text("Install command (optional):", default=kept.install_cmd if kept else ""))
        dev_cmd = _ask(questionary.text("Run-locally command (optional):", default=kept.dev_cmd if kept else ""))
        test_cmd = _ask(
            questionary.text("Test command:", default=kept.test_cmd if kept else primary.test if primary else "")
        )
        lint_cmd = _ask(
            questionary.text("Lint command:", default=kept.lint_cmd if kept else primary.lint if primary else "")
        )
        format_cmd = _ask(
            questionary.text(
                "Format command (gets the file path appended):",
                default=kept.format_cmd if kept else primary.format if primary else "",
            )
        )
    has_api = _ask(questionary.confirm("Does the project expose an API?", default=p.has_api if p else False))
    mcp_servers = _ask(
        questionary.checkbox(
            "MCP servers to connect:",
            choices=_choices(MCP_SERVERS, lambda m: m.label, checked=tuple(p.mcp_servers) if p else ()),
        )
    )
    agents = _ask(
        questionary.checkbox(
            "Subagents:", choices=_choices(AGENTS, str, checked=tuple(p.agents) if p else ("code-reviewer",))
        )
    )
    block_dangerous = _ask(
        questionary.confirm(
            "Add a hook that blocks destructive shell commands?", default=p.block_dangerous if p else True
        )
    )
    format_on_edit = bool(format_cmd) and _ask(
        questionary.confirm(
            "Add a hook that formats files after Claude edits them?", default=p.format_on_edit if p else True
        )
    )
    return Answers(
        name=name,
        description=description,
        stack_undecided=stack_undecided,
        stacks=stacks,
        extensions=extensions_text.split(","),
        frameworks=frameworks,
        architecture=architecture,
        conventions=conventions,
        install_cmd=install_cmd,
        dev_cmd=dev_cmd,
        test_cmd=test_cmd,
        lint_cmd=lint_cmd,
        format_cmd=format_cmd,
        has_api=has_api,
        mcp_servers=mcp_servers,
        agents=agents,
        block_dangerous=block_dangerous,
        format_on_edit=format_on_edit,
    )


@app.callback()
def main() -> None:
    pass


@app.command()
def init(
    directory: Annotated[Path, typer.Argument(help="Project directory; created if it doesn't exist.")] = Path(),
    answers_file: Annotated[
        Path | None, typer.Option("--answers", help="Skip the interview and read answers from a JSON file.")
    ] = None,
    save_answers: Annotated[Path | None, typer.Option(help="Also save your answers to this JSON file.")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Write without asking for confirmation.")] = False,
    force: Annotated[bool, typer.Option("--force", help="Overwrite files that already exist.")] = False,
) -> None:
    """Interview you about the project, preview the files, and write them once you confirm."""
    root = directory.resolve()
    if root.exists() and not root.is_dir():
        raise typer.BadParameter(f"{root} is a file, not a directory", param_hint="DIRECTORY")

    typer.secho("Nothing is written until you confirm at the end.\n", bold=True)
    saved = saved_answers_path(root)
    try:
        if answers_file:
            answers = _load_answers(answers_file)
        else:
            previous = _load_answers(saved) if saved.exists() else None
            choice = "restart"
            if previous:
                typer.echo(f"Saved answers for {root}:\n")
                _show(previous)
                typer.echo()
                choice = _ask(
                    questionary.select(
                        "What do you want to do with these answers?",
                        choices=[
                            questionary.Choice("Use them as they are", value="use"),
                            questionary.Choice("Edit them (each question starts with your answer)", value="edit"),
                            questionary.Choice("Start over", value="restart"),
                        ],
                    )
                )
            answers = (
                previous
                if previous and choice == "use"
                else interview(root.name, previous if choice == "edit" else None)
            )
    except (ValueError, TypeError) as e:
        typer.secho(f"Invalid answers: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e

    if not answers_file:
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps(answers.to_dict(), indent=2) + "\n")
    if save_answers:
        save_answers.write_text(json.dumps(answers.to_dict(), indent=2) + "\n")

    files = generate(answers)
    overwrite: frozenset[str] = frozenset()
    if not force and not yes:
        files, overwrite = resolve_conflicts(files, root)
    actions = plan(files, root, force=force, overwrite=overwrite)
    typer.echo(f"\nFiles for {root}:\n")
    if not root.exists():
        typer.secho(f"  + {root}/  (new directory)", fg=typer.colors.GREEN)
    for f, action in actions:
        mark, color = ACTION_STYLE[action]
        typer.secho(f"  {mark} {f.path}" + (f"  ({action})" if action != "create" else ""), fg=color)
    typer.echo()

    if all(action in ("skip", "unchanged") for _, action in actions):
        typer.echo("Nothing to write: every file already exists and you chose to keep them.")
        return
    if not yes and not _ask(questionary.confirm("Write these files?", default=True)):
        typer.echo("Nothing written.")
        if not answers_file:
            typer.echo("Your answers are saved: run the same command again to use or edit them.")
        return

    root.mkdir(parents=True, exist_ok=True)
    write(actions, root)
    if any(action == "skip" for _, action in actions):
        typer.echo("\nSkipped files already exist; rerun with --force to overwrite them.")
    claude_md = root / "CLAUDE.md"
    if claude_md.exists() and AGENTS_IMPORT not in claude_md.read_text().splitlines():
        typer.secho(
            f"\nYour existing CLAUDE.md doesn't import AGENTS.md, so Claude Code won't read it. "
            f"Add `{AGENTS_IMPORT}` as the first line of CLAUDE.md.",
            fg=typer.colors.YELLOW,
        )
    typer.secho(f"\nDone. Start Claude Code in {root} to use the new setup.", fg=typer.colors.GREEN)
