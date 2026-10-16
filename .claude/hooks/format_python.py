"""Claude Code PostToolUse hook: format a Python file right after Claude writes or edits it.

Claude Code passes the hook event as JSON on stdin. Only ``.py`` files inside the project are
formatted, with the project's own ruff. The hook never blocks an edit: if ruff cannot format
the file (usually a syntax error halfway through a change), it exits with code 2 so that Claude
sees ruff's message, and the edit stands.

It formats only. ``ruff check --fix`` would delete an import that Claude adds in one edit and
uses in the next.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    tool_input = event.get("tool_input") if isinstance(event, dict) else None
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(file_path, str) or not file_path.endswith(".py"):
        return 0

    path = Path(file_path).resolve()
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path.cwd())).resolve()
    if not path.is_relative_to(project) or not path.is_file():
        return 0

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        print(f"ruff format could not format {path.name}: {message}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
