"""Command line: interview the user, then write the Claude Code project files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import questionary
import typer

from .generate import generate
from .models import AGENTS, MCP_SERVERS, STACKS, Answers
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


def _choices(catalog: dict[str, Any], label: Any, checked: tuple[str, ...] = ()) -> list[questionary.Choice]:
    return [questionary.Choice(label(v), value=k, checked=k in checked) for k, v in catalog.items()]


def interview(default_name: str) -> Answers:
    name = _ask(questionary.text("Project name:", default=default_name))
    description = _ask(questionary.text("One-line description:"))
    stacks = _ask(questionary.checkbox("Languages with presets:", choices=_choices(STACKS, lambda s: s.label)))
    extensions_text = _ask(
        questionary.text(
            "File extensions for other languages, comma separated (e.g. ex, exs):",
            validate=lambda v: bool(stacks or v.strip()) or "Pick a language above or enter an extension",
        )
    )
    primary = STACKS[stacks[0]] if stacks else None
    frameworks = _ask(questionary.text("Main frameworks and libraries (optional):"))
    architecture = _ask(questionary.text("Architecture in a sentence or two (optional):", multiline=False))
    conventions = _ask(questionary.text("Conventions people get wrong most often (optional):"))
    install_cmd = _ask(questionary.text("Install command (optional):"))
    dev_cmd = _ask(questionary.text("Run-locally command (optional):"))
    test_cmd = _ask(questionary.text("Test command:", default=primary.test if primary else ""))
    lint_cmd = _ask(questionary.text("Lint command:", default=primary.lint if primary else ""))
    format_cmd = _ask(
        questionary.text("Format command (gets the file path appended):", default=primary.format if primary else "")
    )
    has_api = _ask(questionary.confirm("Does the project expose an API?", default=False))
    mcp_servers = _ask(
        questionary.checkbox("MCP servers to connect:", choices=_choices(MCP_SERVERS, lambda m: m.label))
    )
    agents = _ask(questionary.checkbox("Subagents:", choices=_choices(AGENTS, str, checked=("code-reviewer",))))
    block_dangerous = _ask(questionary.confirm("Add a hook that blocks destructive shell commands?", default=True))
    format_on_edit = bool(format_cmd) and _ask(
        questionary.confirm("Add a hook that formats files after Claude edits them?", default=True)
    )
    return Answers(
        name=name,
        description=description,
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
    directory: Annotated[Path, typer.Argument(help="Project directory.")] = Path(),
    answers_file: Annotated[
        Path | None, typer.Option("--answers", help="Skip the interview and read answers from a JSON file.")
    ] = None,
    save_answers: Annotated[Path | None, typer.Option(help="Save your answers to a JSON file for reuse.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would change without writing.")] = False,
    force: Annotated[bool, typer.Option("--force", help="Overwrite files that already exist.")] = False,
) -> None:
    """Interview you about the project and write its Claude Code files."""
    root = directory.resolve()
    if not root.is_dir():
        raise typer.BadParameter(f"{root} is not a directory", param_hint="DIRECTORY")

    try:
        answers = Answers.from_dict(json.loads(answers_file.read_text())) if answers_file else interview(root.name)
    except (ValueError, TypeError) as e:
        typer.secho(f"Invalid answers: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e

    if save_answers:
        save_answers.write_text(json.dumps(answers.to_dict(), indent=2) + "\n")

    actions = plan(generate(answers), root, force=force)
    for f, action in actions:
        mark, color = ACTION_STYLE[action]
        typer.secho(f"  {mark} {f.path}" + (f"  ({action})" if action != "create" else ""), fg=color)

    if dry_run:
        typer.echo("\nDry run: nothing written.")
        return
    write(actions, root)
    if any(action == "skip" for _, action in actions):
        typer.echo("\nSkipped files already exist; rerun with --force to overwrite them.")
    typer.secho(f"\nDone. Start Claude Code in {root} to use the new setup.", fg=typer.colors.GREEN)
