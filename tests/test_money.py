"""M2: minor-unit rounding, charm endings and money formatting (SPEC §7.5)."""

import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from souqsort.pricing.money import charm_up, format_money, round_minor

AmountCall = Callable[[Any, int], object]

# Each money function as f(amount, minor_units), for the checks they all share.
ALL_FUNCTIONS = [
    pytest.param(round_minor, id="round_minor"),
    pytest.param(format_money, id="format_money"),
    pytest.param(lambda amount, mu: charm_up(amount, Decimal("0.95"), mu), id="charm_up"),
]


# --- helpers ------------------------------------------------------------------------------


def _decimals(value: Decimal) -> int:
    """Decimal places the value carries; ``Decimal("9.9") == Decimal("9.90")`` hides them."""
    exponent = value.as_tuple().exponent
    assert isinstance(exponent, int)
    return -exponent


# --- round_minor: ROUND_HALF_UP to the currency's minor units -----------------------------


@pytest.mark.parametrize(
    ("value", "minor_units", "expected"),
    [
        ("12.3455", 3, "12.346"),
        ("0.0005", 3, "0.001"),  # banker's rounding would give 0.000
        ("10.005", 2, "10.01"),
        ("0.125", 2, "0.13"),  # banker's rounding would give 0.12
        ("2.5", 0, "3"),  # banker's rounding would give 2
        ("686.305265625", 2, "686.31"),  # worked example A, gross
        ("594.39471141", 2, "594.39"),  # worked example B, gross
        ("12.34", 3, "12.340"),
        ("1E+3", 2, "1000.00"),
        ("-10.005", 2, "-10.01"),  # negatives round away from zero
    ],
)
def test_round_minor(value: str, minor_units: int, expected: str) -> None:
    assert str(round_minor(Decimal(value), minor_units)) == expected


@pytest.mark.parametrize("value", ["0", "-0", "-0.000", "-0.00000", "-0.0001", "0.0004"])
def test_round_minor_zero_is_unsigned(value: str) -> None:
    rounded = round_minor(Decimal(value), 3)
    assert str(rounded) == "0.000"
    assert not rounded.is_signed()


# --- format_money: exact number of decimals -----------------------------------------------


@pytest.mark.parametrize(
    ("value", "minor_units", "expected"),
    [
        ("12.34", 3, "12.340"),
        ("12.3455", 3, "12.346"),
        ("686.95", 2, "686.95"),
        ("9", 2, "9.00"),
        ("5", 0, "5"),
        ("1E+3", 2, "1000.00"),  # no exponent notation
        ("1234567.5", 2, "1234567.50"),  # no thousands separators
        ("-10.005", 2, "-10.01"),
    ],
)
def test_format_money(value: str, minor_units: int, expected: str) -> None:
    assert format_money(Decimal(value), minor_units) == expected


@pytest.mark.parametrize("value", ["0", "-0", "-0.000", "-0.00000", "-0.0001", "0.0004"])
def test_format_money_never_shows_negative_zero(value: str) -> None:
    assert format_money(Decimal(value), 3) == "0.000"
    assert format_money(Decimal(value), 2) == "0.00"


def test_zero_vat_amount_is_exactly_zero_and_formats_unsigned() -> None:
    # 0% VAT: (cif + duty) * 0. The fixture market and PriceQuote.vat are covered in M3.
    vat = Decimal("596.7871875") * Decimal("0")
    assert vat == 0
    assert format_money(vat, 3) == "0.000"
    assert format_money(vat, 2) == "0.00"


# --- charm_up: move up to the next price with the charm ending ----------------------------


@pytest.mark.parametrize(
    ("amount", "ending", "minor_units", "expected"),
    [
        ("686.31", "0.95", 2, "686.95"),
        ("686.95", "0.95", 2, "686.95"),  # already charmed: unchanged
        ("686.96", "0.95", 2, "687.95"),
        ("9.00", "0.95", 2, "9.95"),
        ("4.200", "0.950", 3, "4.950"),
        ("4.200", "0.95", 3, "4.950"),  # ending with fewer decimals than minor_units
        ("4.951", "0.95", 3, "5.950"),
        ("9", "0.95", 2, "9.95"),  # amount with fewer decimals than minor_units
        ("0.00", "0.95", 2, "0.95"),
        ("-0.00", "0.95", 2, "0.95"),
        ("9.00", "0.00", 2, "9.00"),
        ("9.01", "0.00", 2, "10.00"),
        ("7", "0", 0, "7"),
    ],
)
def test_charm_up(amount: str, ending: str, minor_units: int, expected: str) -> None:
    assert str(charm_up(Decimal(amount), Decimal(ending), minor_units)) == expected


def test_charm_ending_coarser_than_minor_units_keeps_exact_decimals() -> None:
    charmed = charm_up(Decimal("4.200"), Decimal("0.95"), 3)
    assert charmed == Decimal("4.950")
    assert _decimals(charmed) == 3
    assert str(charmed) == "4.950"


@pytest.mark.parametrize(
    ("amount", "minor_units", "expected"),
    [("686.31", 2, "686.31"), ("9", 2, "9.00"), ("4.200", 3, "4.200"), ("-0.00", 2, "0.00")],
)
def test_charm_ending_none_means_no_charm(amount: str, minor_units: int, expected: str) -> None:
    assert str(charm_up(Decimal(amount), None, minor_units)) == expected


@pytest.mark.parametrize("ending", [Decimal("0.95"), None])
@pytest.mark.parametrize(("amount", "minor_units"), [("686.951", 2), ("0.001", 2), ("9.5", 0)])
def test_charm_rejects_amount_not_rounded_to_minor_units(
    amount: str, minor_units: int, ending: Decimal | None
) -> None:
    with pytest.raises(ValueError, match="rounded"):
        charm_up(Decimal(amount), ending, minor_units)


@pytest.mark.parametrize("ending", [Decimal("0.95"), None])
@pytest.mark.parametrize("amount", ["-0.01", "-1.00", "-686.95"])
def test_charm_rejects_negative_amount(amount: str, ending: Decimal | None) -> None:
    with pytest.raises(ValueError, match="negative"):
        charm_up(Decimal(amount), ending, 2)


@pytest.mark.parametrize("ending", ["1", "1.00", "1.5", "-0.05", "NaN", "Infinity"])
def test_charm_ending_outside_zero_to_one_rejected(ending: str) -> None:
    with pytest.raises(ValueError, match="charm_ending"):
        charm_up(Decimal("686.31"), Decimal(ending), 2)


@pytest.mark.parametrize(("ending", "minor_units"), [("0.955", 2), ("0.9501", 3), ("0.5", 0)])
def test_charm_ending_finer_than_minor_units_rejected(ending: str, minor_units: int) -> None:
    with pytest.raises(ValueError, match="minor_units"):
        charm_up(Decimal("686"), Decimal(ending), minor_units)


# --- a float anywhere in money input is rejected ------------------------------------------


@pytest.mark.parametrize("call", ALL_FUNCTIONS)
@pytest.mark.parametrize(
    "value", [686.31, 686, True, "686.31", None], ids=["float", "int", "bool", "str", "None"]
)
def test_non_decimal_amount_rejected(call: AmountCall, value: Any) -> None:
    with pytest.raises(TypeError, match="Decimal"):
        call(value, 2)


@pytest.mark.parametrize("ending", [0.95, 0, True, "0.95"], ids=["float", "int", "bool", "str"])
def test_non_decimal_charm_ending_rejected(ending: Any) -> None:
    with pytest.raises(TypeError, match="Decimal"):
        charm_up(Decimal("686.31"), ending, 2)


# --- bad arguments ------------------------------------------------------------------------


@pytest.mark.parametrize("call", ALL_FUNCTIONS)
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_amount_rejected(call: AmountCall, value: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        call(Decimal(value), 2)


@pytest.mark.parametrize("call", ALL_FUNCTIONS)
def test_negative_minor_units_rejected(call: AmountCall) -> None:
    with pytest.raises(ValueError, match="minor_units"):
        call(Decimal("686.31"), -1)


# --- Hypothesis properties ----------------------------------------------------------------

MINOR_UNITS = st.integers(min_value=0, max_value=4)

# Any finite amount, positive or negative, with 0 to 10 decimals.
AMOUNTS = st.integers(min_value=0, max_value=10).flatmap(
    lambda places: st.decimals(min_value=-(10**9), max_value=10**9, places=places)
)


@st.composite
def charm_cases(draw: st.DrawFn) -> tuple[Decimal, Decimal, int]:
    """(amount, charm_ending, minor_units) that ``charm_up`` accepts.

    The amount is non-negative and already at minor-unit precision. The ending is in [0, 1)
    and carries anywhere from 0 to ``minor_units`` decimals.
    """
    minor_units = draw(MINOR_UNITS)
    amount = Decimal(draw(st.integers(min_value=0, max_value=10**12))).scaleb(-minor_units)
    ending_places = draw(st.integers(min_value=0, max_value=minor_units))
    ending_digits = draw(st.integers(min_value=0, max_value=10**ending_places - 1))
    ending = Decimal(ending_digits).scaleb(-ending_places)
    return amount, ending, minor_units


@given(amount=AMOUNTS, minor_units=MINOR_UNITS)
def test_rounded_value_has_exactly_minor_units_decimals(amount: Decimal, minor_units: int) -> None:
    rounded = round_minor(amount, minor_units)
    assert _decimals(rounded) == minor_units
    assert abs(rounded - amount) * 2 <= Decimal(1).scaleb(-minor_units)


@given(amount=AMOUNTS, minor_units=MINOR_UNITS)
def test_formatted_value_has_exactly_minor_units_decimals(
    amount: Decimal, minor_units: int
) -> None:
    text = format_money(amount, minor_units)
    pattern = r"-?\d+" + (rf"\.\d{{{minor_units}}}" if minor_units else "")
    assert re.fullmatch(pattern, text), text
    assert Decimal(text) == round_minor(amount, minor_units)
    assert not (text.startswith("-") and Decimal(text) == 0), text


@given(case=charm_cases())
def test_charm_never_lowers_a_price(case: tuple[Decimal, Decimal, int]) -> None:
    amount, ending, minor_units = case
    charmed = charm_up(amount, ending, minor_units)
    assert charmed >= amount
    assert _decimals(charmed) == minor_units


@given(case=charm_cases())
def test_charm_is_idempotent(case: tuple[Decimal, Decimal, int]) -> None:
    amount, ending, minor_units = case
    once = charm_up(amount, ending, minor_units)
    twice = charm_up(once, ending, minor_units)
    assert twice == once
    assert _decimals(twice) == minor_units


@given(case=charm_cases())
def test_charm_lands_on_the_next_price_with_the_ending(
    case: tuple[Decimal, Decimal, int],
) -> None:
    amount, ending, minor_units = case
    charmed = charm_up(amount, ending, minor_units)
    assert charmed % 1 == ending
    assert charmed - amount < 1
    assert _decimals(charmed) == minor_units
