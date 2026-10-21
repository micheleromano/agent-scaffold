"""PreToolUse hook: block shell commands that are hard to undo. Exit code 2 blocks the call."""

import json
import re
import sys

BLOCKED = [
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|~|\$HOME)(\s|$)", "recursive delete of / or home"),
    (r"\bgit\s+push\b.*(--force\b|-f\b)", "force push"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard discards uncommitted work"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "git clean deletes untracked files"),
    (r"\b(curl|wget)\b[^|]*\|\s*(sh|bash|zsh)\b", "piping a download into a shell"),
    (r"\bdrop\s+(table|database)\b", "dropping a table or database"),
]

command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
for pattern, reason in BLOCKED:
    if re.search(pattern, command, re.IGNORECASE):
        print(f"Blocked by project hook: {reason}. Ask the user to run it themselves.", file=sys.stderr)
        sys.exit(2)
sys.exit(0)
