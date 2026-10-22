"""The interviews: questions about one project, one service, or a system of services."""

from __future__ import annotations

import posixpath
from typing import Any

import questionary
import typer

from . import ui
from .models import AGENTS, LAYOUTS, MCP_SERVERS, ROLES, STACKS, Answers, Service, Stack, Workspace

# The "Other (not listed)" language choice, which then asks for file extensions.
OTHER_LANGUAGE = "other"


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
    name = ui.ask(questionary.text(f"{noun.capitalize()} name:", default=p.name if p else default_name))
    description = ui.ask(
        questionary.text("What does it do, and who is it for? (a sentence or two):", default=p.description if p else "")
    )
    role = ui.ask(
        questionary.select(
            f"What kind of {noun} is it?",
            choices=[questionary.Choice(r.label, value=k) for k, r in ROLES.items()],
            default=p.role if p else "other",
        )
    )
    stack_undecided = not ui.ask(
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
        picked = ui.ask(
            questionary.checkbox(
                "Languages:",
                choices=[
                    *_choices(STACKS, lambda s: s.label, checked=_default_stacks(p, role)),
                    questionary.Choice("Other (not listed)", value=OTHER_LANGUAGE, checked=bool(p and p.extensions)),
                ],
                validate=lambda v: bool(v) or "Pick at least one",
            )
        )
        stacks = [k for k in picked if k != OTHER_LANGUAGE]
        if OTHER_LANGUAGE in picked:
            # Rules and the format hook are scoped by file extension, so an unlisted language needs its own.
            extensions_text = ui.ask(
                questionary.text(
                    "Which file extensions does it use? (e.g. ex, exs for Elixir; html, css for a static site):",
                    default=", ".join(p.extensions) if p else "",
                    validate=lambda v: bool(v.strip()) or "Enter at least one extension",
                )
            )
        primary = STACKS[stacks[0]] if stacks else None
        frameworks = ui.ask(
            questionary.text("Main frameworks and libraries, names only (optional):", default=p.frameworks if p else "")
        )
    architecture = ui.ask(
        questionary.text("Architecture in a sentence or two (optional):", default=p.architecture if p else "")
    )
    conventions = ui.ask(
        questionary.text(
            'Rules an AI agent might not guess for this project, separated by ";" (optional).\n'
            "  E.g. Use react-router loaders instead of useEffect for data fetching; never edit generated files\n",
            default=p.conventions if p else "",
        )
    )
    if not stack_undecided:
        # Keep earlier commands exactly (even blank ones); otherwise suggest the first language's preset.
        kept = p if p and not p.stack_undecided else None
        install_cmd = ui.ask(questionary.text("Install command (optional):", default=kept.install_cmd if kept else ""))
        dev_cmd = ui.ask(questionary.text("Run-locally command (optional):", default=kept.dev_cmd if kept else ""))
        test_cmd = ui.ask(
            questionary.text("Test command:", default=kept.test_cmd if kept else primary.test if primary else "")
        )
        lint_cmd = ui.ask(
            questionary.text("Lint command:", default=kept.lint_cmd if kept else primary.lint if primary else "")
        )
        format_cmd = ui.ask(
            questionary.text(
                "Format command (gets the file path appended):",
                default=kept.format_cmd if kept else primary.format if primary else "",
            )
        )
        format_on_edit = bool(format_cmd) and ui.ask(
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
    mcp_servers = ui.ask(
        questionary.checkbox(
            "MCP servers to connect:",
            choices=_choices(MCP_SERVERS, lambda m: m.label, checked=tuple(p.mcp_servers) if p else ()),
        )
    )
    agents = ui.ask(
        questionary.checkbox(
            "Subagents:", choices=_choices(AGENTS, str, checked=tuple(p.agents) if p else default_agents)
        )
    )
    block_dangerous = ui.ask(
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
    path = ui.ask(
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
    name = ui.ask(questionary.text("Workspace (system) name:", default=p.name if p else default_name))
    goal = ui.ask(
        questionary.text("What is the goal every service works toward? (a sentence):", default=p.goal if p else "")
    )
    layout = ui.ask(
        questionary.select(
            "How are the services stored?",
            choices=[questionary.Choice(label, value=k) for k, label in LAYOUTS.items()],
            default=p.layout if p else "repos",
        )
    )
    services: list[Service] = []
    question = (
        "Add a service now? (No: set up just the workspace; add services later with `agent-scaffold add-service`)"
    )
    # Fresh: Enter sets up just the workspace, so service and stack questions only come when asked for.
    # Editing: Enter walks through exactly the services there were.
    while ui.ask(questionary.confirm(question, default=len(services) < len(p.services) if p else False)):
        before = p.services[len(services)] if p and len(services) < len(p.services) else None
        typer.echo(f"\nService {len(services) + 1}")
        services.append(service_interview(before))
        question = "Add another service?"
    communication = ui.ask(
        questionary.text("How do the services talk to each other? (optional):", default=p.communication if p else "")
    )
    contracts = ui.ask(
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
        kind = ui.ask(
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
