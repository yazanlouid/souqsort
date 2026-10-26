"""Guard rails for the non-negotiables.

M7: no floats and no market codes in the code (SPEC §3 rules 1 and 4). M11: the report's
templates only place text (§3 rule 8, §9.4.1). M15: the delivery calendar does not depend on
pricing.
"""

import ast
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, nodes

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
APP_DIR = REPO_ROOT / "app"
TEMPLATES_DIR = SRC_DIR / "souqsort" / "report" / "templates"

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


# --- layering -----------------------------------------------------------------------------

LOGISTICS_DIR = SRC_DIR / "souqsort" / "logistics"


def _imports_of(source: str, package: str) -> Found:
    """Every import of ``package`` or one of its modules."""
    found: Found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            names = [node.module]
        else:
            continue
        found += [
            (node.lineno, name)
            for name in names
            if name == package or name.startswith(f"{package}.")
        ]
    return found


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from souqsort.pricing.customs import travels", ["souqsort.pricing.customs"]),
        ("import souqsort.pricing", ["souqsort.pricing"]),
        ("from souqsort.pricing import money", ["souqsort.pricing"]),
        ("from souqsort.models import ShippingModel", []),
        ("from souqsort.pricingx import thing", []),
    ],
)
def test_import_guard_recognises_imports(source: str, expected: list[str]) -> None:
    assert [name for _, name in _imports_of(source, "souqsort.pricing")] == expected


def test_logistics_does_not_import_pricing() -> None:
    def find(source: str) -> Found:
        return _imports_of(source, "souqsort.pricing")

    assert _violations(_python_files(LOGISTICS_DIR), find) == []


# --- report templates ---------------------------------------------------------------------

# Filters that would turn a value into a number or format one inside the template (§9.4.1).
_NUMBER_FILTERS = frozenset({"float", "int", "round", "sum", "abs", "format"})
_ARITHMETIC = (
    nodes.Add,
    nodes.Sub,
    nodes.Mul,
    nodes.Div,
    nodes.FloorDiv,
    nodes.Mod,
    nodes.Pow,
    nodes.Neg,
    nodes.Pos,
)


def _template_problems(source: str, codes: frozenset[str]) -> Found:
    """Number filters, arithmetic, ``.format`` calls and market or currency codes as words."""
    found: Found = []
    tree = Environment().parse(source)
    for node in tree.find_all((nodes.Filter, nodes.Getattr, *_ARITHMETIC)):
        if isinstance(node, nodes.Filter):
            if node.name in _NUMBER_FILTERS:
                found.append((node.lineno, f"filter {node.name}"))
        elif isinstance(node, nodes.Getattr):
            if node.attr == "format":
                found.append((node.lineno, ".format"))
        else:
            found.append((node.lineno, f"arithmetic {type(node).__name__}"))
    if codes:
        word = re.compile(r"\b(" + "|".join(map(re.escape, sorted(codes))) + r")\b")
        for number, line in enumerate(source.splitlines(), start=1):
            found += [(number, match) for match in word.findall(line)]
    return sorted(found)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("{{ price | round(2) }}", ["filter round"]),
        ("{{ price|float }}", ["filter float"]),
        ("{{ count | int }}", ["filter int"]),
        ("{{ prices | sum }}", ["filter sum"]),
        ("{{ change | abs }}", ["filter abs"]),
        ('{{ "%.2f" | format(price) }}', ["filter format"]),
        ("{% filter round %}{{ price }}{% endfilter %}", ["filter round"]),
        ("{{ a + b }}", ["arithmetic Add"]),
        ("{{ a - b }}", ["arithmetic Sub"]),
        ("{{ a * 100 }}", ["arithmetic Mul"]),
        ("{{ a / b }}", ["arithmetic Div"]),
        ('{{ "%.2f" % price }}', ["arithmetic Mod"]),
        ("{{ -change }}", ["arithmetic Neg"]),
        ('{{ "{:.2f}".format(price) }}', [".format"]),
        ("## KSA (Saudi Arabia)", ["KSA"]),
        ("| Consolidated (SAR) |", ["SAR"]),
        ("{% if market == 'UAE' %}x{% endif %}", ["UAE"]),
        ("KSAX and ksa", []),  # whole words, exact case
        ("{{ row.market }} | {{ rows | join(', ') }} ~ {{ a ~ b }}", []),
        ("{% if rows and not other %}{{ row.market }}{% endif %}", []),
    ],
    ids=[
        "round",
        "float",
        "int",
        "sum",
        "abs",
        "format-filter",
        "filter-block",
        "add",
        "sub",
        "mul",
        "div",
        "percent-format",
        "neg",
        "format-method",
        "market-code",
        "currency-code",
        "market-in-test",
        "not-a-word",
        "plain-text",
        "logic",
    ],
)
def test_template_guard_recognises_problems(source: str, expected: list[str]) -> None:
    found = _template_problems(source, frozenset({"KSA", "UAE", "SAR"}))

    assert [text for _, text in found] == expected


def test_report_templates_only_place_text(raw_config: dict[str, Any]) -> None:
    codes = frozenset(raw_config["markets"]) | frozenset(raw_config["fx"]["per_usd"])
    codes |= {market["currency"]["code"] for market in raw_config["markets"].values()}
    templates = sorted(TEMPLATES_DIR.rglob("*.j2"))
    assert templates, f"no templates under {TEMPLATES_DIR}"

    def find(source: str) -> Found:
        return _template_problems(source, codes)

    assert _violations(templates, find) == []
