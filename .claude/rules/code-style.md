---
paths:
  - "**/*.py"
---

# Code style

- Match the style of the surrounding code: naming, comment density, file layout.
- Code must pass `uv run ruff check .` and `uv run mypy` (strict) before a task is done.
- Formatting is owned by `uv run ruff format`; don't hand-format.
- Prefer small, focused functions and descriptive names over comments that restate the code.

## Python

- Target Python 3.12. Use modern syntax: `X | None`, `list[str]`, `match` where it reads better than `if` chains.
- Type every function signature, including tests. Avoid `Any` except at JSON and questionary boundaries; prefer a dataclass over a dict for structured data.
- Keep data immutable where possible (`@dataclass(frozen=True)`, tuples for catalog constants).
- Use `pathlib.Path`, never `os.path`. Read and write text with `Path.read_text()` / `write_text()`.
- Raise specific exceptions with a message that names the bad value (`ValueError(f"unknown stack: {key}")`). Never use a bare `except`, and never swallow an exception silently.
- No `print` in library modules; output goes through `typer.echo` / `typer.secho` in `cli.py`.
- Module docstrings say what the module is for in one line. Comments explain why, not what.
- A `# noqa` or `# type: ignore` always names its code and says why on the same line.
