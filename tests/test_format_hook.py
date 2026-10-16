"""The Claude Code format hook (.claude/hooks/format_python.py), run as Claude Code runs it."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".claude" / "hooks" / "format_python.py"
MESSY = "x=1\n"


def _run_hook(stdin: str, project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)},
        capture_output=True,
        text=True,
        check=False,
    )


def _event(path: Path) -> str:
    return json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(path)}})


@pytest.fixture
def project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    return project


def test_formats_a_messy_python_file_in_the_project(project: Path) -> None:
    messy = project / "messy.py"
    messy.write_text(MESSY, encoding="utf-8")

    result = _run_hook(_event(messy), project)

    assert result.returncode == 0, result.stderr
    assert messy.read_text(encoding="utf-8") == "x = 1\n"


def test_leaves_a_markdown_file_alone(project: Path) -> None:
    notes = project / "notes.md"
    notes.write_text(MESSY, encoding="utf-8")

    result = _run_hook(_event(notes), project)

    assert result.returncode == 0, result.stderr
    assert notes.read_text(encoding="utf-8") == MESSY


def test_leaves_a_python_file_outside_the_project_alone(project: Path) -> None:
    outside = project.parent / "outside.py"
    outside.write_text(MESSY, encoding="utf-8")

    result = _run_hook(_event(outside), project)

    assert result.returncode == 0, result.stderr
    assert outside.read_text(encoding="utf-8") == MESSY


def test_exits_2_with_ruffs_message_on_a_syntax_error(project: Path) -> None:
    broken = project / "broken.py"
    broken.write_text("def f(:\n", encoding="utf-8")

    result = _run_hook(_event(broken), project)

    assert result.returncode == 2
    prefix = "ruff format could not format broken.py: "
    assert result.stderr.startswith(prefix)
    ruff_message = result.stderr.removeprefix(prefix).strip()
    assert "parse" in ruff_message.lower()
    assert broken.read_text(encoding="utf-8") == "def f(:\n"


@pytest.mark.parametrize("stdin", ["", "not json"])
def test_ignores_input_that_is_not_json(project: Path, stdin: str) -> None:
    result = _run_hook(stdin, project)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
