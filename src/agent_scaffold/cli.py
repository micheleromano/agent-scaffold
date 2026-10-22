"""Command line: interview the user, then write the agent setup for a project or a workspace of services."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import posixpath
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any

import questionary
import typer

from .generate import (
    AGENTS_IMPORT,
    MANIFEST,
    GeneratedFile,
    adopt_claude_md,
    can_adopt_claude_md,
    generate,
    generate_workspace,
    refresh_blocks,
)
from .models import AGENTS, LAYOUTS, MCP_SERVERS, ROLES, STACKS, Answers, Service, Stack, Workspace, load_answers
from .writer import plan, write

app = typer.Typer(help="Set up the agent files for a project, or for a system of services.", no_args_is_help=True)

ACTION_STYLE = {
    "create": ("+", typer.colors.GREEN),
    "overwrite": ("~", typer.colors.YELLOW),
    "refresh": ("~", typer.colors.YELLOW),
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


def _load_answers(path: Path) -> Answers | Workspace:
    return load_answers(json.loads(path.read_text()))


def _reader(root: Path) -> Any:
    return lambda path: (root / path).read_text() if (root / path).is_file() else None


# --- summaries ----------------------------------------------------------------------------


def _commands(a: Answers) -> str:
    pairs = (("install", a.install_cmd), ("run", a.dev_cmd), ("test", a.test_cmd), ("lint", a.lint_cmd))
    return " · ".join(f"{label} `{cmd}`" for label, cmd in (*pairs, ("format", a.format_cmd)) if cmd)


def _languages(a: Answers) -> str:
    return "not decided yet (/choose-stack)" if a.stack_undecided else ", ".join(a.languages)


def _shared_rows(x: Answers | Workspace) -> list[tuple[str, str]]:
    hooks = ["block destructive commands"] if x.block_dangerous else []
    if isinstance(x, Answers) and x.format_on_edit:
        hooks.append("format on edit")
    return [
        ("MCP servers", ", ".join(MCP_SERVERS[k].label for k in x.mcp_servers) or "none"),
        ("Subagents", ", ".join(x.agents) or "none"),
        ("Hooks", ", ".join(hooks) or "none"),
    ]


def summarize(x: Answers | Workspace) -> list[tuple[str, str]]:
    """The answers as label/value rows, leaving out anything blank."""
    if isinstance(x, Workspace):
        rows = [
            ("Workspace", x.name),
            ("Goal", x.goal),
            ("Layout", LAYOUTS[x.layout]),
            ("Services", "" if x.services else "none yet"),
            *((f"{s.path}/", f"{ROLES[s.answers.role].label} · {_languages(s.answers)}") for s in x.services),
            ("Services talk", x.communication),
            ("Contracts", x.contracts),
            *_shared_rows(x),
        ]
    else:
        rows = [
            ("Project", x.name),
            ("Description", x.description),
            ("Role", ROLES[x.role].label),
            ("Languages", _languages(x)),
            ("Frameworks", x.frameworks),
            ("Architecture", x.architecture),
            ("Conventions", x.conventions),
            ("Commands", _commands(x)),
            *_shared_rows(x),
        ]
    return [(label, value) for label, value in rows if value]


def _show(x: Answers | Workspace) -> None:
    rows = summarize(x)
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        typer.echo(f"  {label.ljust(width)}  {value}")


# --- interviews ---------------------------------------------------------------------------


def _choices(catalog: dict[str, Any], label: Any, checked: tuple[str, ...] = ()) -> list[questionary.Choice]:
    return [questionary.Choice(label(v), value=k, checked=k in checked) for k, v in catalog.items()]


def _default_stacks(previous: Answers | None, role: str) -> tuple[str, ...]:
    """Pre-ticked languages: the previous answer, or the role's usual stack for a fresh interview."""
    if previous:
        return tuple(previous.stacks)
    default = ROLES[role].default_stack
    return (default,) if default else ()


def _project_questions(default_name: str, p: Answers | None, noun: str = "project") -> dict[str, Any]:
    """Everything about one codebase: what it is, its stack and its commands. With `p`, answers start pre-filled."""
    name = _ask(questionary.text(f"{noun.capitalize()} name:", default=p.name if p else default_name))
    description = _ask(
        questionary.text("What does it do, and who is it for? (a sentence or two):", default=p.description if p else "")
    )
    role = _ask(
        questionary.select(
            f"What kind of {noun} is it?",
            choices=[questionary.Choice(r.label, value=k) for k, r in ROLES.items()],
            default=p.role if p else "other",
        )
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
    format_on_edit = False
    if not stack_undecided:
        stacks = _ask(
            questionary.checkbox(
                "Languages with presets:",
                choices=_choices(STACKS, lambda s: s.label, checked=_default_stacks(p, role)),
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
        format_on_edit = bool(format_cmd) and _ask(
            questionary.confirm(
                "Add a hook that formats files after Claude edits them?", default=p.format_on_edit if p else True
            )
        )
    return {
        "name": name,
        "description": description,
        "role": role,
        "stack_undecided": stack_undecided,
        "stacks": stacks,
        "extensions": extensions_text.split(","),
        "frameworks": frameworks,
        "architecture": architecture,
        "conventions": conventions,
        "install_cmd": install_cmd,
        "dev_cmd": dev_cmd,
        "test_cmd": test_cmd,
        "lint_cmd": lint_cmd,
        "format_cmd": format_cmd,
        "format_on_edit": format_on_edit,
    }


def _shared_questions(p: Answers | Workspace | None, default_agents: tuple[str, ...]) -> dict[str, Any]:
    mcp_servers = _ask(
        questionary.checkbox(
            "MCP servers to connect:",
            choices=_choices(MCP_SERVERS, lambda m: m.label, checked=tuple(p.mcp_servers) if p else ()),
        )
    )
    agents = _ask(
        questionary.checkbox(
            "Subagents:", choices=_choices(AGENTS, str, checked=tuple(p.agents) if p else default_agents)
        )
    )
    block_dangerous = _ask(
        questionary.confirm(
            "Add a hook that blocks destructive shell commands?", default=p.block_dangerous if p else True
        )
    )
    return {"mcp_servers": mcp_servers, "agents": agents, "block_dangerous": block_dangerous}


def interview(default_name: str, previous: Answers | None = None) -> Answers:
    """Ask about one project. With `previous`, every question starts at its old answer so Enter keeps it."""
    project = _project_questions(default_name, previous)
    return Answers(**project, **_shared_questions(previous, ROLES[project["role"]].agents))


def service_interview(previous: Service | None = None, folder: str = "") -> Service:
    """Ask about one service of a workspace: its folder, then the same questions as a project minus the shared ones."""
    path = _ask(
        questionary.text(
            "Service folder, relative to the workspace (e.g. backend):",
            default=previous.path if previous else folder,
            validate=lambda v: bool(v.strip()) or "Enter a folder name",
        )
    )
    project = _project_questions(posixpath.basename(path.strip("/")), previous.answers if previous else None, "service")
    return Service(path, Answers(**project))


def workspace_interview(default_name: str, previous: Workspace | None = None) -> Workspace:
    """Ask about a system of services: its goal and layout, each service, then the choices they all share."""
    p = previous
    name = _ask(questionary.text("Workspace (system) name:", default=p.name if p else default_name))
    goal = _ask(
        questionary.text("What is the goal every service works toward? (a sentence):", default=p.goal if p else "")
    )
    layout = _ask(
        questionary.select(
            "How are the services stored?",
            choices=[questionary.Choice(label, value=k) for k, label in LAYOUTS.items()],
            default=p.layout if p else "repos",
        )
    )
    services: list[Service] = []
    question = "Add a service now? (No: add them later with `agent-scaffold add-service`)"
    # Fresh: suggest adding one. Editing: Enter walks through exactly the services there were.
    while _ask(questionary.confirm(question, default=len(services) < len(p.services) if p else not services)):
        before = p.services[len(services)] if p and len(services) < len(p.services) else None
        typer.echo(f"\nService {len(services) + 1}")
        services.append(service_interview(before))
        question = "Add another service?"
    communication = _ask(
        questionary.text("How do the services talk to each other? (optional):", default=p.communication if p else "")
    )
    contracts = _ask(
        questionary.text(
            "Where do API schemas, events and shared types live? (optional):", default=p.contracts if p else ""
        )
    )
    default_agents = tuple(dict.fromkeys(a for s in services for a in ROLES[s.answers.role].agents)) or (
        "code-reviewer",
    )
    return Workspace(
        name=name,
        goal=goal,
        layout=layout,
        services=services,
        communication=communication,
        contracts=contracts,
        **_shared_questions(p, default_agents),
    )


def new_answers(default_name: str, previous: Answers | Workspace | None = None) -> Answers | Workspace:
    """Interview for a project or a workspace. Editing keeps the previous kind; starting fresh asks which."""
    if isinstance(previous, Workspace):
        return workspace_interview(default_name, previous)
    if previous is None:
        kind = _ask(
            questionary.select(
                "What are you setting up?",
                choices=[
                    questionary.Choice("One project", value="project"),
                    questionary.Choice("A system of several services (backend, data, LLM, ...)", value="workspace"),
                ],
            )
        )
        if kind == "workspace":
            return workspace_interview(default_name)
    return interview(default_name, previous)


# --- writing ------------------------------------------------------------------------------


def _show_diff(existing: str, generated: str, path: str) -> None:
    diff = difflib.unified_diff(
        existing.splitlines(), generated.splitlines(), f"{path} (yours)", f"{path} (generated)", lineterm=""
    )
    for line in diff:
        color = typer.colors.GREEN if line.startswith("+") else typer.colors.RED if line.startswith("-") else None
        typer.secho(f"    {line}", fg=color)


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
        while (choice := _ask(questionary.select("What do you want to do with it?", choices=choices))) == "diff":
            _show_diff(existing, f.content, f.path)
        if choice == "adopt":
            files = adopt_claude_md(files, existing, directory)
            overwrite.add(f.path)
            typer.echo("  Your CLAUDE.md becomes AGENTS.md; the new CLAUDE.md imports it.")
        elif choice == "replace":
            overwrite.add(f.path)
    return files, frozenset(overwrite)


def _apply(files: list[GeneratedFile], root: Path, *, yes: bool, force: bool) -> bool:
    """Preview, ask about existing files, confirm, then write. Returns whether anything was written.

    Out-of-date managed blocks (sections agent-scaffold owns inside a file) are refreshed without asking about the
    file, and the workspace manifest is always rewritten: both still wait for the final confirmation.
    """
    refresh = refresh_blocks(files, _reader(root))
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
        label = "refresh" if f.path in refresh else action
        mark, color = ACTION_STYLE[label]
        typer.secho(f"  {mark} {f.path}" + (f"  ({label})" if label != "create" else ""), fg=color)
    typer.echo()

    if all(action in ("skip", "unchanged") for _, action in actions):
        typer.echo("Nothing to write: every file is up to date or you chose to keep it.")
        return False
    if not yes and not _ask(questionary.confirm("Write these files?", default=True)):
        typer.echo("Nothing written.")
        return False

    root.mkdir(parents=True, exist_ok=True)
    write(actions, root)
    if any(action == "skip" for _, action in actions):
        typer.echo("\nSkipped files already exist; rerun with --force to overwrite them.")
    for f in files:
        claude_md = root / f.path
        if f.path.endswith("CLAUDE.md") and AGENTS_IMPORT not in claude_md.read_text().splitlines():
            typer.secho(
                f"\n{f.path} doesn't import AGENTS.md, so Claude Code won't read it. "
                f"Add `{AGENTS_IMPORT}` as its first line.",
                fg=typer.colors.YELLOW,
            )
    return True


def _next_steps(ws: Workspace, root: Path) -> None:
    repos = [""] + [s.path for s in ws.services] if ws.layout == "repos" else [""]
    uninitialized = [p for p in repos if not (root / p / ".git").exists()]
    if uninitialized:
        typer.echo("\nNext: make each of these a git repository (`git init`):")
        for p in uninitialized:
            typer.echo(f"  {root / p}")
    typer.echo(f"\nStart Claude Code in {root} for work across services, or in a service folder for focused work.")


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
                else new_answers(root.name, previous if choice == "edit" else None)
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
    if not _apply(files, root, yes=yes, force=force):
        if not answers_file:
            typer.echo("Your answers are saved: run the same command again to use or edit them.")
        return
    if isinstance(answers, Workspace):
        _next_steps(answers, root)
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
        service = service_interview(existing, folder)
        others = [s for s in ws.services if s.path not in (service.path, existing.path if existing else "")]
        updated = replace(ws, services=[*others, service])
    except ValueError as e:
        typer.secho(f"Invalid service: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e
    if _apply(generate_workspace(updated), root, yes=yes, force=False):
        _next_steps(updated, root)
        typer.secho(f"\nDone. {service.path}/ is part of {ws.name}.", fg=typer.colors.GREEN)
