"""Command line: interview the user, then write the agent setup for a project or a workspace of services."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import questionary
import typer

from . import apply, questions, ui
from .generate import MANIFEST, generate, generate_workspace
from .models import Answers, Workspace, load_answers

app = typer.Typer(help="Set up the agent files for a project, or for a system of services.", no_args_is_help=True)


def saved_answers_path(root: Path) -> Path:
    """Where the latest answers for `root` are kept, outside the project so nothing lands there before you confirm."""
    state = os.environ.get("AGENT_SCAFFOLD_STATE_DIR") or Path.home() / ".local" / "state" / "agent-scaffold"
    key = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    return Path(state) / "answers" / f"{key}.json"


def _load_answers(path: Path) -> Answers | Workspace:
    return load_answers(json.loads(path.read_text()))


def _load_workspace(root: Path) -> Workspace:
    manifest = root / MANIFEST
    if not manifest.is_file():
        typer.secho(
            f"No {MANIFEST} in {root}. Run this in a workspace made with `agent-scaffold init`.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)
    try:
        return Workspace.from_dict(json.loads(manifest.read_text()))
    except (ValueError, TypeError, KeyError) as e:
        typer.secho(f"Invalid {MANIFEST}: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e


# --- commands -----------------------------------------------------------------------------


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
    """Interview you about a project or a system of services, preview the files, and write them once you confirm."""
    root = directory.resolve()
    if root.exists() and not root.is_dir():
        raise typer.BadParameter(f"{root} is a file, not a directory", param_hint="DIRECTORY")

    typer.secho("Nothing is written until you confirm at the end.\n", bold=True)
    saved = saved_answers_path(root)
    try:
        if answers_file:
            answers = _load_answers(answers_file)
        else:
            # Your latest answers for this folder, or the manifest of a workspace that's already here.
            source = saved if saved.exists() else root / MANIFEST if (root / MANIFEST).is_file() else None
            previous = _load_answers(source) if source else None
            choice = "restart"
            if previous:
                typer.echo(f"Saved answers for {root}:\n")
                ui.show(previous)
                typer.echo()
                choice = ui.ask(
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
                else questions.new_answers(root.name, previous if choice == "edit" else None)
            )
    except (ValueError, TypeError, KeyError) as e:
        typer.secho(f"Invalid answers: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e

    if not answers_file:
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps(answers.to_dict(), indent=2) + "\n")
    if save_answers:
        save_answers.write_text(json.dumps(answers.to_dict(), indent=2) + "\n")

    files = generate_workspace(answers) if isinstance(answers, Workspace) else generate(answers)
    if not apply.apply(files, root, yes=yes, force=force):
        if not answers_file:
            typer.echo("Your answers are saved: run the same command again to use or edit them.")
        return
    if isinstance(answers, Workspace):
        apply.next_steps(answers, root)
    typer.secho(f"\nDone. Start Claude Code in {root} to use the new setup.", fg=typer.colors.GREEN)


@app.command("add-service")
def add_service(
    folder: Annotated[str, typer.Argument(help="The service's folder, relative to the workspace.")] = "",
    workspace: Annotated[Path, typer.Option(help="The workspace directory.")] = Path(),
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Write without asking for confirmation.")] = False,
) -> None:
    """Add a service to a workspace (or edit one) with the standard structure for its role."""
    root = workspace.resolve()
    ws = _load_workspace(root)
    typer.secho("Nothing is written until you confirm at the end.\n", bold=True)
    existing = next((s for s in ws.services if s.path == folder.strip("/")), None)
    if existing:
        typer.echo(f"{existing.path}/ is already a service; its answers are pre-filled.\n")
    try:
        service = questions.service_interview(existing, folder)
        others = [s for s in ws.services if s.path not in (service.path, existing.path if existing else "")]
        updated = replace(ws, services=[*others, service])
    except ValueError as e:
        typer.secho(f"Invalid service: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e
    if apply.apply(generate_workspace(updated), root, yes=yes, force=False):
        apply.next_steps(updated, root)
        typer.secho(f"\nDone. {service.path}/ is part of {ws.name}.", fg=typer.colors.GREEN)
