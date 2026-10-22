import json
import sys
from pathlib import Path
from typing import Any, ClassVar

import cohere
import pytest
import questionary

from agent_scaffold import draft, questions
from agent_scaffold.detect import Detected
from agent_scaffold.draft import SCHEMA, from_detected, parse, system_prompt, user_prompt
from agent_scaffold.models import ROLES, STACKS

from .helpers import FakeQuestion

REPO = Detected(
    name="strava-art",
    description="Art from your runs",
    stacks=["typescript"],
    dependencies=["react", "react-router", "prettier"],
    install_cmd="pnpm install",
    test_cmd="pnpm run test",
    format_cmd="pnpm exec prettier --write",
    sources=["package.json"],
)


def reply(**overrides: Any) -> str:
    data: dict[str, Any] = {
        "role": "frontend",
        "languages_known": True,
        "stacks": ["typescript"],
        "stack_reason": "",
        "extensions": [],
        "frameworks": ["React Router", "HeroUI"],
        "conventions": ["Load data with react-router loaders, not useEffect", "  "],
        "architecture": "A single-page app that reads activities from Strava.",
        "install_cmd": "npm install",
        "dev_cmd": "npm run dev",
        "test_cmd": "npm test",
        "lint_cmd": "npm run lint",
        "format_cmd": "",
    }
    return json.dumps({**data, **overrides})


# --- prompts and schema -------------------------------------------------------------------


def test_schema_offers_only_the_catalogs_and_requires_every_field() -> None:
    props = SCHEMA["properties"]
    assert props["role"]["enum"] == list(ROLES)
    assert props["stacks"]["items"]["enum"] == list(STACKS)
    assert set(SCHEMA["required"]) == set(props)


def test_system_prompt_lists_roles_and_stacks_and_forbids_versions() -> None:
    prompt = system_prompt()
    assert "a web app: typescript" in prompt
    assert "\\" not in prompt  # line continuations, not literal backslashes
    assert "- llm: LLM / AI service. Calls language models" in prompt
    assert "- other: Other (library, CLI, tool, ...)\n" in prompt
    assert "python (Python)" in prompt
    assert "Never include version numbers" in prompt


def test_user_prompt_for_a_new_project() -> None:
    prompt = user_prompt("  A habit tracker.  ", Detected())
    assert prompt == "Project description:\nA habit tracker.\n\nThere is no existing code: this is a new project."


def test_user_prompt_sends_only_names_and_commands_from_the_repo() -> None:
    prompt = user_prompt("Art from runs", REPO)
    assert "Existing repository (package.json):" in prompt
    assert "- Dependencies: react, react-router, prettier" in prompt
    assert "- Install command: pnpm install" in prompt
    assert "- Format command: pnpm exec prettier --write" in prompt
    assert "Dev command" not in prompt  # blank facts are left out


# --- starting answers ---------------------------------------------------------------------


def test_nothing_to_start_from() -> None:
    assert from_detected("x", "", Detected()) is None


def test_a_description_alone_starts_an_undecided_project() -> None:
    answers = from_detected("x", "A habit tracker", Detected())
    assert answers is not None
    assert (answers.description, answers.stack_undecided, answers.test_cmd) == ("A habit tracker", True, "")


def test_starting_answers_from_the_repository() -> None:
    answers = from_detected("folder", "", REPO)
    assert answers is not None
    assert (answers.name, answers.description, answers.stacks) == ("folder", "Art from your runs", ["typescript"])
    assert answers.frameworks == "react-router, react"
    assert (answers.install_cmd, answers.format_cmd, answers.format_on_edit) == (
        "pnpm install",
        "pnpm exec prettier --write",
        True,
    )


def test_parse_a_draft_for_a_new_project() -> None:
    answers = parse(reply(), "habits", "A habit tracker", Detected())
    assert (answers.name, answers.description, answers.role) == ("habits", "A habit tracker", "frontend")
    assert answers.frameworks == "React Router, HeroUI"
    assert answers.convention_list == ["Load data with react-router loaders, not useEffect"]
    assert answers.architecture.startswith("A single-page app")
    assert (answers.test_cmd, answers.format_cmd, answers.format_on_edit) == ("npm test", "", False)


def test_the_repository_wins_over_the_draft() -> None:
    answers = parse(reply(stacks=["python"]), "strava-art", "Art", REPO)
    assert answers.stacks == ["typescript", "python"]
    assert (answers.install_cmd, answers.test_cmd) == ("pnpm install", "pnpm run test")
    assert answers.lint_cmd == "npm run lint"  # the repo has none, so the draft's suggestion stays
    assert answers.format_on_edit


def test_unknown_values_from_the_model_are_dropped() -> None:
    answers = parse(
        reply(role="wizard", stacks=["cobol", "go"], extensions=["ex", "../x", 3], frameworks="not a list"),
        "x",
        "",
        Detected(),
    )
    assert (answers.role, answers.stacks, answers.extensions, answers.frameworks) == ("other", ["go"], ["ex"], "")


def test_undecided_languages_drop_the_commands() -> None:
    answers = parse(reply(languages_known=False, stacks=["go"], extensions=["ex"]), "x", "an idea", Detected())
    assert answers.stack_undecided
    assert (answers.stacks, answers.extensions, answers.test_cmd, answers.format_on_edit) == ([], [], "", False)


def test_an_existing_repo_is_never_undecided() -> None:
    assert parse(reply(languages_known=False), "x", "", REPO).stacks == ["typescript"]


@pytest.mark.parametrize("text", ["not json", "[1]"])
def test_a_reply_that_isnt_an_object_is_rejected(text: str) -> None:
    with pytest.raises(ValueError, match=r"Expecting value|isn't a JSON object"):
        parse(text, "x", "", Detected())


# --- the Cohere client --------------------------------------------------------------------


class FakeClient:
    calls: ClassVar[list[dict[str, Any]]] = []
    content: ClassVar[list[Any]] = []

    def __init__(self, api_key: str, timeout: float) -> None:
        assert (api_key, timeout) == ("key", 60)

    def chat(self, **kwargs: Any) -> Any:
        FakeClient.calls.append(kwargs)
        return type("Response", (), {"message": type("Message", (), {"content": FakeClient.content})()})()


@pytest.fixture
def fake_cohere(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    FakeClient.calls = []
    FakeClient.content = [
        cohere.ThinkingAssistantMessageResponseContentItem(thinking="hmm"),
        cohere.TextAssistantMessageResponseContentItem(text='{"role": "llm"}'),
    ]
    monkeypatch.setattr(cohere, "ClientV2", FakeClient)
    return FakeClient


def test_cohere_drafter_sends_the_schema_and_returns_the_text(fake_cohere: type[FakeClient]) -> None:
    ask = draft.cohere_drafter("key", "some-model")
    assert ask("system", "user") == '{"role": "llm"}'
    (call,) = fake_cohere.calls
    assert call["model"] == "some-model"
    assert [m.content for m in call["messages"]] == ["system", "user"]
    assert call["response_format"].json_schema == SCHEMA


def test_cohere_drafter_without_text_fails(fake_cohere: type[FakeClient]) -> None:
    fake_cohere.content = []
    with pytest.raises(ValueError, match="no text"):
        draft.cohere_drafter("key")("s", "u")


def test_cohere_drafter_needs_the_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "cohere", None)
    with pytest.raises(ImportError):
        draft.cohere_drafter("key")


# --- in the interview ---------------------------------------------------------------------


@pytest.fixture
def describe(monkeypatch: pytest.MonkeyPatch, press_enter_everywhere: None) -> list[str]:
    """Press Enter everywhere, but answer the description prompt; returns the prompts shown."""
    shown: list[str] = []

    def text(message: str, default: str = "", **_kw: Any) -> FakeQuestion:
        shown.append(message)
        return FakeQuestion("An art generator for runners." if message.startswith("Describe") else default)

    monkeypatch.setattr(questionary, "text", text)
    return shown


@pytest.fixture
def drafts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Turn drafting on with a fake Cohere that records each request and replies with `reply()`."""
    sent: list[tuple[str, str]] = []

    def drafter(api_key: str, model: str) -> draft.Drafter:
        assert (api_key, model) == ("key", draft.DEFAULT_MODEL)

        def ask(system: str, user: str) -> str:
            sent.append((system, user))
            return reply()

        return ask

    monkeypatch.setenv("CO_API_KEY", "key")
    monkeypatch.setattr(draft, "cohere_drafter", drafter)
    return sent


def write_package_json(root: Path) -> None:
    root.mkdir(exist_ok=True)
    (root / "package.json").write_text(json.dumps({"name": "x", "scripts": {"test": "vitest"}}))
    (root / "node_modules").mkdir()  # folders are ignored


@pytest.mark.usefixtures("press_enter_everywhere")
def test_without_a_key_the_interview_starts_from_the_repository(tmp_path: Path) -> None:
    write_package_json(tmp_path)
    answers = questions.interview("strava", root=tmp_path)
    assert (answers.name, answers.stacks, answers.test_cmd) == ("strava", ["typescript"], "npm run test")


def test_without_a_key_or_a_repository_nothing_changes(tmp_path: Path) -> None:
    assert questions.starting_answers("new", tmp_path / "missing") is None
    assert questions.starting_answers("new", None) is None


def test_the_draft_prefills_the_interview(
    tmp_path: Path, describe: list[str], drafts: list[tuple[str, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    write_package_json(tmp_path)
    answers = questions.interview("strava", root=tmp_path)
    assert "Cohere drafts your answers from it and package.json" in describe[0]
    ((system, user),) = drafts
    assert system == draft.system_prompt()
    assert "An art generator for runners." in user
    assert "- Test command: npm run test" in user
    assert (answers.description, answers.role) == ("An art generator for runners.", "frontend")
    assert answers.test_cmd == "npm run test"  # the repository's command beats the draft's
    assert answers.convention_list == ["Load data with react-router loaders, not useEffect"]
    assert answers.agents == list(ROLES["frontend"].agents)  # shared choices still start from the role
    out = capsys.readouterr().out
    assert "Cohere suggests:\n\n  Project       strava\n" in out
    assert "  Role          Frontend (web or mobile UI)\n" in out
    assert "Subagents" not in out  # shared choices aren't part of the draft
    assert "Why these languages" not in out  # they came from the repository
    assert "Each question below starts with these answers" in out


@pytest.mark.usefixtures("describe")
def test_a_suggested_stack_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CO_API_KEY", "key")
    why = "A web app with a rich UI fits TypeScript and React."
    monkeypatch.setattr(draft, "cohere_drafter", lambda _k, _m: lambda _s, _u: reply(stack_reason=why))
    answers = questions.interview("new", root=tmp_path)
    out = capsys.readouterr().out
    assert answers.stacks == ["typescript"]
    assert f"Why these languages: {why}" in out
    assert 'answer No to "Do you know which languages it will use?"' in out


@pytest.mark.parametrize(
    ("overrides", "detected", "expected"),
    [
        ({"stack_reason": " Fits a web UI. "}, Detected(), "Fits a web UI."),
        ({"stack_reason": "Fits a web UI."}, REPO, ""),  # the repository's languages, not a suggestion
        ({"stack_reason": "Why", "languages_known": False, "stacks": []}, Detected(), ""),
        ({"stack_reason": 3}, Detected(), ""),
    ],
)
def test_stack_reason(overrides: dict[str, Any], detected: Detected, expected: str) -> None:
    text = reply(**overrides)
    assert draft.stack_reason(text, parse(text, "x", "", detected), detected) == expected


@pytest.mark.usefixtures("press_enter_everywhere", "drafts")
def test_skipping_the_description_falls_back_to_the_repository(tmp_path: Path, drafts: list[tuple[str, str]]) -> None:
    write_package_json(tmp_path)
    answers = questions.interview("strava", root=tmp_path)
    assert drafts == []
    assert answers.test_cmd == "npm run test"


@pytest.mark.usefixtures("describe")
def test_a_failed_draft_keeps_the_description(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(_key: str, _model: str) -> draft.Drafter:
        def ask(_system: str, _user: str) -> str:
            raise RuntimeError("401 invalid api token")

        return ask

    monkeypatch.setenv("CO_API_KEY", "key")
    monkeypatch.setattr(draft, "cohere_drafter", broken)
    answers = questions.interview("idea", root=tmp_path)
    assert "Couldn't get a draft (401 invalid api token)" in capsys.readouterr().out
    assert answers.description == "An art generator for runners."
    assert answers.stack_undecided  # nothing to go on but an idea


def test_a_key_without_the_package_says_how_to_install_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CO_API_KEY", "key")
    monkeypatch.setitem(sys.modules, "cohere", None)
    assert questions.starting_answers("x", tmp_path) is None
    assert "uv tool install 'agent-scaffold[cohere]'" in capsys.readouterr().out


@pytest.mark.usefixtures("describe")
def test_model_can_be_chosen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    models: list[str] = []

    def drafter(_key: str, model: str) -> draft.Drafter:
        models.append(model)
        return lambda _s, _u: reply()

    monkeypatch.setenv("CO_API_KEY", "key")
    monkeypatch.setenv("AGENT_SCAFFOLD_COHERE_MODEL", "command-a-03-2025")
    monkeypatch.setattr(draft, "cohere_drafter", drafter)
    questions.interview("x", root=tmp_path)
    assert models == ["command-a-03-2025"]


@pytest.mark.usefixtures("describe", "drafts")
def test_a_new_service_is_drafted_from_its_own_folder(tmp_path: Path) -> None:
    write_package_json(tmp_path / "web")
    service = questions.service_interview(folder="web", root=tmp_path)
    assert (service.path, service.answers.name, service.answers.test_cmd) == ("web", "web", "npm run test")


@pytest.mark.usefixtures("describe", "drafts")
def test_editing_saved_answers_never_drafts(tmp_path: Path, drafts: list[tuple[str, str]]) -> None:
    previous = parse(reply(), "x", "saved", Detected())
    assert questions.interview("x", previous, tmp_path).description == "saved"
    assert drafts == []
