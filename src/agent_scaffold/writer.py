"""Write generated files into a project directory without clobbering existing work."""

from __future__ import annotations

from pathlib import Path

from .generate import GeneratedFile, merge_lines


def plan(
    files: list[GeneratedFile], root: Path, force: bool = False, overwrite: frozenset[str] = frozenset()
) -> list[tuple[GeneratedFile, str]]:
    """Decide what happens to each file: create, overwrite, merge, skip or unchanged.

    Existing files are skipped unless `force` is set or their path is in `overwrite`.
    """
    actions = []
    for f in files:
        target = root / f.path
        if not target.exists():
            action = "create"
        elif f.merge_lines:
            existing = target.read_text()
            action = "unchanged" if merge_lines(existing, f.content) == existing else "merge"
        elif target.read_text() == f.content:
            action = "unchanged"
        else:
            action = "overwrite" if force or f.path in overwrite else "skip"
        actions.append((f, action))
    return actions


def write(actions: list[tuple[GeneratedFile, str]], root: Path) -> None:
    for f, action in actions:
        target = root / f.path
        if action in ("create", "overwrite"):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.content)
        elif action == "merge":
            target.write_text(merge_lines(target.read_text(), f.content))
