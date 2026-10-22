import pytest

from agent_scaffold.models import AGENTS, ROLES, STACKS, Answers

from .helpers import FULL, MINIMAL, make_answers


def test_round_trips_through_a_dict() -> None:
    answers = make_answers()
    assert Answers.from_dict(answers.to_dict()) == answers


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"name": "  "}, "name is required"),
        ({"stacks": [], "extensions": []}, "at least one stack or file extension"),
        ({"stack_undecided": True}, "can't be combined with stacks"),
        (
            {"stack_undecided": True, "stacks": [], "format_on_edit": True},
            "format_on_edit needs a decided stack",
        ),
        ({"stacks": ["cobol"]}, "unknown stack"),
        ({"mcp_servers": ["fax"]}, "unknown MCP server"),
        ({"agents": ["intern"]}, "unknown agent"),
        ({"role": "astronaut"}, "unknown role"),
        ({"format_cmd": "", "format_on_edit": True}, "format_cmd"),
    ],
)
def test_rejects_invalid_answers(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Answers.from_dict({**FULL, **overrides})


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="unknown fields: colour"):
        Answers.from_dict({**MINIMAL, "colour": "blue"})


def test_normalizes_custom_extensions() -> None:
    answers = Answers.from_dict({**MINIMAL, "extensions": [" .EX", "exs ", "", "."]})
    assert answers.extensions == ["ex", "exs"]
    assert answers.globs == ["**/*.ex", "**/*.exs"]
    assert "**/*test*.exs" in answers.test_globs


def test_presets_and_custom_extensions_combine() -> None:
    answers = make_answers(stacks=["go"], extensions=["templ"])
    assert answers.globs == ["**/*.go", "**/*.templ"]
    assert answers.languages == ["Go", "*.templ files"]


@pytest.mark.parametrize("key", list(STACKS))
def test_every_preset_has_code_and_test_globs(key: str) -> None:
    stack = STACKS[key]
    assert stack.globs
    assert stack.test_globs
    assert stack.test


def test_undecided_stack_needs_no_languages() -> None:
    answers = Answers.from_dict({"name": "idea", "description": "", "stack_undecided": True})
    assert answers.globs == []
    assert answers.test_globs == []
    assert answers.languages == []


@pytest.mark.parametrize(("has_api", "role"), [(True, "backend"), (False, "other")])
def test_old_has_api_answers_become_a_role(*, has_api: bool, role: str) -> None:
    answers = Answers.from_dict({**MINIMAL, "has_api": has_api})
    assert answers.role == role


@pytest.mark.parametrize("key", list(ROLES))
def test_every_role_is_complete(key: str) -> None:
    role = ROLES[key]
    assert role.label
    assert role.default_stack is None or role.default_stack in STACKS
    assert set(role.agents) <= set(AGENTS)


@pytest.mark.parametrize(
    ("conventions", "rules"),
    [
        ("", []),
        ("Use loaders; never edit generated files", ["Use loaders", "never edit generated files"]),
        ("  one ;\n two\n\n; ", ["one", "two"]),
    ],
)
def test_conventions_split_into_rules(conventions: str, rules: list[str]) -> None:
    assert make_answers(conventions=conventions).convention_list == rules
