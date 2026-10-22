"""Talking to the person at the terminal: asking questions and showing answers."""

from __future__ import annotations

import difflib
from typing import Any

import questionary
import typer

from .models import LAYOUTS, MCP_SERVERS, ROLES, Answers, Workspace


def ask(question: questionary.Question) -> Any:
    answer = question.ask()
    if answer is None:  # Ctrl-C
        raise typer.Abort()
    return answer


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
            ("Conventions", "; ".join(x.convention_list)),
            ("Commands", _commands(x)),
            *_shared_rows(x),
        ]
    return [(label, value) for label, value in rows if value]


def show(x: Answers | Workspace) -> None:
    rows = summarize(x)
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        typer.echo(f"  {label.ljust(width)}  {value}")


def show_diff(existing: str, generated: str, path: str) -> None:
    diff = difflib.unified_diff(
        existing.splitlines(), generated.splitlines(), f"{path} (yours)", f"{path} (generated)", lineterm=""
    )
    for line in diff:
        color = typer.colors.GREEN if line.startswith("+") else typer.colors.RED if line.startswith("-") else None
        typer.secho(f"    {line}", fg=color)
