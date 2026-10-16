"""The Claude Code format hook (.claude/hooks/format_python.py), run as Claude Code runs it."""

import json
import locale
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".claude" / "hooks" / "format_python.py"
MESSY = "x=1\n"


def _run_hook(stdin: str | bytes, project: Path) -> subprocess.CompletedProcess[str]:
    """Run the hook with the event as UTF-8 bytes on stdin, as Claude Code sends it.

    Text mode would encode the input in the locale's code page (cp1252 on Windows), which is
    not what the hook receives. Its output is decoded the way the hook writes it.
    """
    raw = stdin.encode("utf-8") if isinstance(stdin, str) else stdin
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)},
        capture_output=True,
        check=False,
    )
    encoding = locale.getencoding()
    return subprocess.CompletedProcess(
        result.args,
        result.returncode,
        result.stdout.decode(encoding, errors="replace"),
        result.stderr.decode(encoding, errors="replace"),
    )


def _event(path: Path) -> str:
    # ensure_ascii=False: Claude Code sends non-ASCII characters as they are, not as \u escapes.
    event = {"tool_name": "Write", "tool_input": {"file_path": str(path)}}
    return json.dumps(event, ensure_ascii=False)


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


def test_formats_a_file_with_a_non_latin_name(project: Path) -> None:
    # The event arrives as UTF-8. Read in the Windows code page, the name would be garbled,
    # the file not found and left unformatted, with no error.
    souq = project / "سوق.py"
    souq.write_text(MESSY, encoding="utf-8")

    result = _run_hook(_event(souq), project)

    assert result.returncode == 0, result.stderr
    assert souq.read_text(encoding="utf-8") == "x = 1\n"


@pytest.mark.parametrize(
    "stdin", ["", "not json", b'{"tool_input": "\xff"}'], ids=["empty", "text", "not-utf-8"]
)
def test_ignores_input_that_is_not_json(project: Path, stdin: str | bytes) -> None:
    result = _run_hook(stdin, project)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
