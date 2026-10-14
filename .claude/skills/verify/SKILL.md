---
name: verify
description: Run the same checks as CI (format, lint, types, tests) and report the result. Use before saying a task is done and before committing.
allowed-tools: Bash(uv run *)
---

Run these from the project root, in this order, and show each command's output:

1. `uv run --locked ruff format --check .`
2. `uv run --locked ruff check .`
3. `uv run --locked mypy src`
4. `uv run --locked pytest -q`

`--locked` makes a command fail when `uv.lock` is out of date, as `UV_LOCKED` does in CI.

Run all four even if one fails, so the report is complete. For each failure, say in one or two lines what failed and why. Do not fix anything unless asked.

End with exactly one line: `verify: PASS`, or `verify: FAIL (<the checks that failed>)`.
