"""Starting answers for the interview, from an existing repository and, optionally, a Cohere-drafted reading of the
project's description. The person still sees and confirms every answer.

Everything but `cohere_drafter` is pure, so the web API can reuse it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .detect import Detected
from .models import ROLES, STACKS, Answers

DEFAULT_MODEL = "command-a-plus-05-2026"

# Takes the system and user messages, returns the model's JSON reply.
Drafter = Callable[[str, str], str]

_TEXT_FIELDS = ("stack_reason", "architecture", "install_cmd", "dev_cmd", "test_cmd", "lint_cmd", "format_cmd")
_COMMANDS = ("install_cmd", "dev_cmd", "test_cmd", "lint_cmd", "format_cmd")

# Cohere's structured outputs keep the reply to this shape; enums keep role and stacks to the tool's catalogs.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "role": {"type": "string", "enum": list(ROLES)},
        "languages_known": {"type": "boolean"},
        "stacks": {"type": "array", "items": {"type": "string", "enum": list(STACKS)}},
        "extensions": {"type": "array", "items": {"type": "string"}},
        "frameworks": {"type": "array", "items": {"type": "string"}},
        "conventions": {"type": "array", "items": {"type": "string"}},
        **{name: {"type": "string"} for name in _TEXT_FIELDS},
    },
    "required": [
        "role",
        "languages_known",
        "stacks",
        "extensions",
        "frameworks",
        "conventions",
        *_TEXT_FIELDS,
    ],
}

_SYSTEM = """You draft the answers to a setup interview for a software project. The answers configure the files \
that AI coding agents read (AGENTS.md, CLAUDE.md). The person reviews every answer before anything is written, so \
leave a field empty rather than invent facts about the project.

Fields:
- role: what the project is for. One of:
{roles}
- languages_known: true when the description or repository names the languages, or when the kind of project \
makes one stack a common, sensible choice (e.g. a web app: typescript; a data pipeline or an LLM service: python). \
False only when the description is too vague to suggest any.
- stacks: the languages, from these keys: {stacks}. Empty when languages_known is false.
- stack_reason: when you suggest languages that the description and repository don't state, one short sentence \
on why they fit this project. Otherwise empty.
- extensions: file extensions (without a dot) only for languages not covered by stacks, e.g. ["ex", "exs"].
- frameworks: main frameworks and libraries, names only. For an existing repository, use its own. For a new \
project with languages, suggest the usual main ones for that stack and kind of project. Never include version \
numbers.
- architecture: one or two sentences on how the project is structured, only from what is stated or evident.
- conventions: at most five project-specific rules an AI coding agent would not guess, taken from the description \
or the dependencies, e.g. "Load data with react-router loaders and actions, not useEffect". No generic advice such \
as "write tests" or "keep code clean". Empty when none are evident.
- install_cmd, dev_cmd, test_cmd, lint_cmd: shell commands run inside the project: install its dependencies \
(e.g. "npm install"), run it locally, run its tests, lint it. Never a command that creates or scaffolds a project. \
When the repository lists a command, use it exactly. Otherwise suggest the usual command for the chosen stack's \
standard tooling, or leave it empty.
- format_cmd: formats one file; its path is appended (e.g. "npx prettier --write"). Empty if unsure.

Never state facts the description and repository don't support. Never include version numbers anywhere."""


def system_prompt() -> str:
    roles = "\n".join(
        f"  - {key}: {role.label}" + (f". {role.focus}" if role.focus else "") for key, role in ROLES.items()
    )
    stacks = ", ".join(f"{key} ({stack.label})" for key, stack in STACKS.items())
    return _SYSTEM.format(roles=roles, stacks=stacks)


def user_prompt(description: str, detected: Detected) -> str:
    """The description and the repository's facts: names and commands only, never file contents."""
    lines = [f"Project description:\n{description.strip()}", ""]
    if not detected:
        lines.append("There is no existing code: this is a new project.")
        return "\n".join(lines)
    lines.append(f"Existing repository ({', '.join(detected.sources)}):")
    facts = (
        ("Package name", detected.name),
        ("Package description", detected.description),
        ("Languages", ", ".join(detected.stacks)),
        ("Dependencies", ", ".join(detected.dependencies)),
        *((name.removesuffix("_cmd").capitalize() + " command", getattr(detected, name)) for name in _COMMANDS),
    )
    lines += [f"- {label}: {value}" for label, value in facts if value]
    return "\n".join(lines)


def from_detected(name: str, description: str, detected: Detected) -> Answers | None:
    """Starting answers from the repository alone, or None when there's nothing to start from."""
    if not detected and not description:
        return None
    return _answers(
        name,
        description or detected.description,
        role="other",
        stacks=detected.stacks,
        extensions=[],
        frameworks=detected.frameworks,
        architecture="",
        conventions=[],
        commands={key: getattr(detected, key) for key in _COMMANDS},
    )


def parse(reply: str, name: str, description: str, detected: Detected) -> Answers:
    """Turn the model's JSON into starting answers. The repository's own stacks and commands win over the model's."""
    data = json.loads(reply)
    if not isinstance(data, dict):
        raise ValueError("the draft isn't a JSON object")

    def text(key: str) -> str:
        value = data.get(key)
        return value.strip() if isinstance(value, str) else ""

    def items(key: str) -> list[str]:
        value = data.get(key)
        return [v.strip() for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []

    known = data.get("languages_known") is not False
    stacks = [*detected.stacks, *(s for s in items("stacks") if s in STACKS and s not in detected.stacks)]
    return _answers(
        name,
        description,
        role=text("role") if text("role") in ROLES else "other",
        stacks=stacks if known or detected.stacks else [],
        extensions=[e for e in items("extensions") if e.isalnum()] if known else [],
        frameworks=items("frameworks"),
        architecture=text("architecture"),
        conventions=items("conventions"),
        commands={key: getattr(detected, key) or text(key) for key in _COMMANDS},
    )


def stack_reason(reply: str, answers: Answers, detected: Detected) -> str:
    """Why the model suggested the languages, when they're its suggestion rather than the person's or the repo's."""
    data = json.loads(reply)
    reason = data.get("stack_reason") if isinstance(data, dict) else None
    suggested = not answers.stack_undecided and not detected.stacks
    return reason.strip() if suggested and isinstance(reason, str) else ""


def _answers(
    name: str,
    description: str,
    *,
    role: str,
    stacks: list[str],
    extensions: list[str],
    frameworks: list[str],
    architecture: str,
    conventions: list[str],
    commands: dict[str, str],
) -> Answers:
    undecided = not stacks and not extensions
    if undecided:
        commands = dict.fromkeys(commands, "")
    return Answers(
        name=name,
        description=description,
        role=role,
        stack_undecided=undecided,
        stacks=stacks,
        extensions=extensions,
        frameworks=", ".join(frameworks),
        architecture=architecture,
        conventions="; ".join(conventions),
        install_cmd=commands["install_cmd"],
        dev_cmd=commands["dev_cmd"],
        test_cmd=commands["test_cmd"],
        lint_cmd=commands["lint_cmd"],
        format_cmd=commands["format_cmd"],
        format_on_edit=bool(commands["format_cmd"]),
    )


def cohere_drafter(api_key: str, model: str = DEFAULT_MODEL) -> Drafter:
    """A drafter backed by Cohere's chat API. Raises ImportError when the optional `cohere` package isn't installed."""
    import cohere  # optional dependency, imported only when drafting

    client = cohere.ClientV2(api_key=api_key, timeout=60)

    def ask(system: str, user: str) -> str:
        response = client.chat(
            model=model,
            messages=[cohere.SystemChatMessageV2(content=system), cohere.UserChatMessageV2(content=user)],
            response_format=cohere.JsonObjectResponseFormatV2(json_schema=SCHEMA),
            temperature=0.2,
        )
        # Reasoning models may put "thinking" items before the answer.
        texts = [
            c.text
            for c in response.message.content or []
            if isinstance(c, cohere.TextAssistantMessageResponseContentItem)
        ]
        if not texts:
            raise ValueError("Cohere returned no text")
        return texts[-1]

    return ask
