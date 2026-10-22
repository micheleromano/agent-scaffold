"""Writing a generated setup to disk: refresh managed blocks, settle existing files, preview, confirm, write."""

from __future__ import annotations

import posixpath
from dataclasses import replace
from pathlib import Path
from typing import Any

import questionary
import typer

from . import ui
from .generate import (
    AGENTS_IMPORT,
    MANIFEST,
    GeneratedFile,
    adopt_claude_md,
    can_adopt_claude_md,
    refresh_blocks,
)
from .models import Workspace
from .writer import plan, write

ACTION_STYLE = {
    "create": ("+", typer.colors.GREEN),
    "overwrite": ("~", typer.colors.YELLOW),
    "refresh": ("~", typer.colors.YELLOW),
    "merge": ("~", typer.colors.YELLOW),
    "keeping yours": ("=", None),
    "unchanged": ("=", None),
}


def _files(n: int) -> str:
    return f"{n} file" if n == 1 else f"{n} files"


def reader(root: Path) -> Any:
    return lambda path: (root / path).read_text() if (root / path).is_file() else None


def resolve_conflicts(
    files: list[GeneratedFile], root: Path, skip: frozenset[str] = frozenset()
) -> tuple[list[GeneratedFile], frozenset[str]]:
    """Ask what to do with each generated file that already exists with different content.

    Returns the files (an AGENTS.md changes if the user moves their CLAUDE.md into it) and the paths to overwrite.
    """
    overwrite: set[str] = set()
    for f in [f for f, action in plan(files, root) if action == "skip" and f.path not in skip]:
        existing = (root / f.path).read_text()
        directory = posixpath.dirname(f.path)
        choices = [questionary.Choice("Keep mine", value="keep")]
        agents_md = root / directory / "AGENTS.md"
        if posixpath.basename(f.path) == "CLAUDE.md" and can_adopt_claude_md(existing, agents_md.exists()):
            choices.append(questionary.Choice("Move mine into AGENTS.md and import it (recommended)", value="adopt"))
        choices += [
            questionary.Choice("Replace it with the generated version", value="replace"),
            questionary.Choice("Show the difference", value="diff"),
        ]
        typer.echo(f"\n{f.path} already exists.")
        while (choice := ui.ask(questionary.select("What do you want to do with it?", choices=choices))) == "diff":
            ui.show_diff(existing, f.content, f.path)
        if choice == "adopt":
            files = adopt_claude_md(files, existing, directory)
            overwrite.add(f.path)
            typer.echo("  Your CLAUDE.md becomes AGENTS.md; the new CLAUDE.md imports it.")
        elif choice == "replace":
            overwrite.add(f.path)
    return files, frozenset(overwrite)


def apply(files: list[GeneratedFile], root: Path, *, yes: bool, force: bool) -> bool:
    """Preview, ask about existing files, confirm, then write. Returns whether anything was written.

    Out-of-date managed blocks (sections agent-scaffold owns inside a file) are refreshed without asking about the
    file, and the workspace manifest is always rewritten: both still wait for the final confirmation.
    """
    refresh = refresh_blocks(files, reader(root))
    files = [replace(f, content=refresh[f.path]) if f.path in refresh else f for f in files]
    auto = frozenset(refresh) | frozenset(f.path for f in files if f.path == MANIFEST)
    overwrite = auto
    if not force and not yes:
        files, chosen = resolve_conflicts(files, root, skip=auto)
        overwrite |= chosen
    actions = plan(files, root, force=force, overwrite=overwrite)

    typer.echo(f"\nFiles for {root}:\n")
    if not root.exists():
        typer.secho(f"  + {root}/  (new directory)", fg=typer.colors.GREEN)
    for f, action in actions:
        label = "refresh" if f.path in refresh else "keeping yours" if action == "skip" else action
        mark, color = ACTION_STYLE[label]
        typer.secho(f"  {mark} {f.path}" + (f"  ({label})" if label != "create" else ""), fg=color)
    typer.echo()

    if all(action in ("skip", "unchanged") for _, action in actions):
        typer.echo("Nothing to write: every file is up to date or you chose to keep it.")
        return False
    if not yes and not ui.ask(questionary.confirm("Write these files?", default=True)):
        typer.echo("Nothing written.")
        return False

    root.mkdir(parents=True, exist_ok=True)
    write(actions, root)
    if refresh:
        typer.echo(
            f"\nUpdated the agent-scaffold sections of {_files(len(refresh))}; your text around them is unchanged."
        )
    kept = sum(action == "skip" for _, action in actions)
    if kept and yes:
        typer.echo(
            f"\nKept {_files(kept)} that already existed with different content. "
            "Run without --yes to compare each with the generated version and choose."
        )
    elif kept:
        typer.echo(f"\nKept your version of {_files(kept)}.")
    for f in files:
        claude_md = root / f.path
        if f.path.endswith("CLAUDE.md") and AGENTS_IMPORT not in claude_md.read_text().splitlines():
            typer.secho(
                f"\n{f.path} doesn't import AGENTS.md, so Claude Code won't read it. "
                f"Add `{AGENTS_IMPORT}` as its first line.",
                fg=typer.colors.YELLOW,
            )
    return True


def next_steps(ws: Workspace, root: Path) -> None:
    repos = [""] + [s.path for s in ws.services] if ws.layout == "repos" else [""]
    uninitialized = [p for p in repos if not (root / p / ".git").exists()]
    if uninitialized:
        typer.echo("\nNext: make each of these a git repository (`git init`):")
        for p in uninitialized:
            typer.echo(f"  {root / p}")
    typer.echo(f"\nStart Claude Code in {root} for work across services, or in a service folder for focused work.")
