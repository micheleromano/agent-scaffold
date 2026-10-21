"""PostToolUse hook: format each file Claude edits or writes."""

import json
import shlex
import subprocess
import sys

FORMAT_CMD = "uv run ruff format"
EXTENSIONS = ["py"]

path = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
# A path starting with "-" would be read as a formatter option, so skip it.
if path and not path.startswith("-") and path.rsplit(".", 1)[-1] in EXTENSIONS:
    # No shell is involved and the command is fixed at setup time; only the path comes from Claude.
    result = subprocess.run([*shlex.split(FORMAT_CMD), path], capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        print(f"Formatter failed on {path}: {result.stderr.strip()}", file=sys.stderr)
sys.exit(0)
