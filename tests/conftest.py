from pathlib import Path

import pytest
import questionary

from .helpers import FakeQuestion


@pytest.fixture(autouse=True)
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Keep saved answers out of the real home directory.
    path = tmp_path / "state"
    monkeypatch.setenv("AGENT_SCAFFOLD_STATE_DIR", str(path))
    return path


@pytest.fixture
def press_enter_everywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace questionary prompts with ones that accept their default, like pressing Enter."""
    monkeypatch.setattr(questionary, "text", lambda _m, default="", **_kw: FakeQuestion(default))
    monkeypatch.setattr(questionary, "confirm", lambda _m, default=True, **_kw: FakeQuestion(default))
    monkeypatch.setattr(questionary, "select", lambda _m, choices, default=None, **_kw: FakeQuestion(default))
    monkeypatch.setattr(
        questionary, "checkbox", lambda _m, choices, **_kw: FakeQuestion([c.value for c in choices if c.checked])
    )
