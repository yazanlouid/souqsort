"""M7: guard rails for two non-negotiables, floats and market codes (SPEC §3 rules 1 and 4)."""

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
APP_DIR = REPO_ROOT / "app"

Found = list[tuple[int, str]]  # (line number, what was found)


def _python_files(*roots: Path) -> list[Path]:
    """Every ``*.py`` under the roots. An empty root fails, so no guard passes on a wrong path."""
    paths: list[Path] = []
    for root in roots:
        found = sorted(root.rglob("*.py"))
        assert found, f"no Python files under {root}"
        paths += found
    return paths


def _violations(paths: list[Path], find: Callable[[str], Found]) -> list[str]:
    return [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{line}: {text}"
        for path in paths
        for line, text in find(path.read_text("utf-8"))
    ]


# --- floats -------------------------------------------------------------------------------


def _float_uses(source: str) -> Found:
    """Float literals and uses of the name ``float``, called or not.

    The class argument of ``isinstance(...)`` is exempt: rejecting a float needs its name.
    """
    tree = ast.parse(source)
    exempt = {
        id(inner)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
        and len(node.args) == 2
        for inner in ast.walk(node.args[1])
    }
    uses: Found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            uses.append((node.lineno, ast.get_source_segment(source, node) or repr(node.value)))
        elif isinstance(node, ast.Name) and node.id == "float" and id(node) not in exempt:
            uses.append((node.lineno, "float"))
    return sorted(uses)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("rate = 0.15", ["0.15"]),
        ("big = 1e3", ["1e3"]),
        ('rate = float("0.15")', ["float"]),
        ("class Tax(BaseModel):\n    vat_rate: float", ["float"]),
        ("def scale(amount: float): ...", ["float"]),
        ("def rate() -> float: ...", ["float"]),
        ("rates: list[float] = []", ["float"]),
        ("rate: float | None = None", ["float"]),
        # How models.py declares field types: an assignment, not an annotation.
        ("Rate = Annotated[float, Field(gt=0)]", ["float"]),
        ("isinstance(value, bool | int | float)", []),  # the guard in models.py
        ("isinstance(value, (int, float))", []),
        ("isinstance(float(value), int)", ["float"]),  # only the class argument is exempt
        ('rate = Decimal("0.15")', []),
        ("count = 15", []),
        ('"""Half is 0.5."""', []),
    ],
    ids=[
        "literal",
        "exponent",
        "call",
        "model-field",
        "argument",
        "return",
        "nested",
        "optional",
        "alias",
        "isinstance-union",
        "isinstance-tuple",
        "isinstance-value",
        "decimal",
        "int",
        "docstring",
    ],
)
def test_float_guard_recognises_floats(source: str, expected: list[str]) -> None:
    assert [text for _, text in _float_uses(source)] == expected


def test_src_has_no_floats() -> None:
    assert _violations(_python_files(SRC_DIR), _float_uses) == []


# --- market codes -------------------------------------------------------------------------


def _market_code_literals(source: str, codes: frozenset[str]) -> Found:
    """String literals that are exactly a market code."""
    return sorted(
        (node.lineno, node.value)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in codes
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('if market == "KSA": ...', ["KSA"]),
        ('match market:\n    case "UAE":\n        pass', ["UAE"]),
        ('market = config.markets["KSA"]', ["KSA"]),
        ('help_text = "market code from the config, e.g. KSA"', []),  # mentions, not equals
        ('market = "ksa"', []),
        ('currency = "SAR"', []),
    ],
    ids=["comparison", "match-case", "lookup", "mention", "lowercase", "currency"],
)
def test_market_code_guard_recognises_codes(source: str, expected: list[str]) -> None:
    found = _market_code_literals(source, frozenset({"KSA", "UAE"}))

    assert [text for _, text in found] == expected


def test_src_and_app_have_no_market_code_literals(raw_config: dict[str, Any]) -> None:
    codes = frozenset(raw_config["markets"])
    assert codes, "no markets in the config"

    def find(source: str) -> Found:
        return _market_code_literals(source, codes)

    assert _violations(_python_files(SRC_DIR, APP_DIR), find) == []
