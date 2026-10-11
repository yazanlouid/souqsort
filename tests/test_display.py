"""M5: display rows shared by the CLI and the dashboard."""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from souqsort.display import DisplayRow, display_rows
from souqsort.models import Catalogue, GccConfig
from souqsort.pipeline import LocalisationError, LocalisedProduct, localise_catalogue

HEADPHONES = "ELEC-HP-001"
BAG = "FASH-BAG-014"

ZERO_VAT_MARKET = "TEST-KWD"

THU_EVENING = datetime(2026, 10, 15, 20, 59, tzinfo=UTC)  # Thu 23:59 in Riyadh: after the cutoff


# --- helpers and fixtures -----------------------------------------------------------------


def _with_margin(item: LocalisedProduct, margin_pct: str) -> LocalisedProduct:
    """A copy of the item whose quote has a different margin; the original is untouched."""
    return replace(item, quote=replace(item.quote, margin_pct=Decimal(margin_pct)))


@pytest.fixture
def localised(catalogue: Catalogue, config: GccConfig) -> list[LocalisedProduct]:
    """The whole sample catalogue for KSA, ordered on Thursday evening."""
    return localise_catalogue(catalogue.products, config, "KSA", THU_EVENING)


@pytest.fixture
def headphones(localised: list[LocalisedProduct]) -> LocalisedProduct:
    return next(item for item in localised if item.sku == HEADPHONES)


# --- rows over the sample data ------------------------------------------------------------


def test_one_row_per_product_in_the_same_order(localised: list[LocalisedProduct]) -> None:
    rows = display_rows(localised)

    assert len(rows) == 12
    assert [row.sku for row in rows] == [item.sku for item in localised]


def test_worked_example_rows(localised: list[LocalisedProduct]) -> None:
    rows = {row.sku: row for row in display_rows(localised)}

    assert rows[HEADPHONES] == DisplayRow(
        sku="ELEC-HP-001",
        name_en="Wireless Noise-Cancelling Headphones",
        currency="SAR",
        shelf_price="686.95",
        margin_percent="58.7",
        delivery_date="2026-10-25",
        flags=(),
    )
    assert rows[BAG] == DisplayRow(
        sku="FASH-BAG-014",
        name_en="Leather Crossbody Bag",
        currency="SAR",
        shelf_price="594.95",
        margin_percent="64.6",
        delivery_date="2026-10-25",
        flags=("missing_arabic_name",),
    )


def test_every_value_is_text_except_the_flags(localised: list[LocalisedProduct]) -> None:
    for row in display_rows(localised):
        for field in fields(row):
            value = getattr(row, field.name)
            assert isinstance(value, tuple if field.name == "flags" else str), field.name


def test_empty_list_gives_no_rows() -> None:
    assert display_rows([]) == []


# --- shelf price --------------------------------------------------------------------------


def test_shelf_price_has_the_currency_minor_units(
    catalogue: Catalogue, zero_vat_config: GccConfig
) -> None:
    items = localise_catalogue(catalogue.products, zero_vat_config, ZERO_VAT_MARKET, THU_EVENING)

    rows = {row.sku: row for row in display_rows(items)}

    assert rows[HEADPHONES].currency == "KWD"
    assert rows[HEADPHONES].shelf_price == "48.950"  # three decimals, trailing zero kept


# --- margin: a percentage with one decimal, rounded half up -------------------------------


@pytest.mark.parametrize(
    ("margin_pct", "expected"),
    [
        ("0.5865", "58.7"),  # 58.65: half up; banker's rounding would give 58.6
        ("0.58649", "58.6"),
        ("0.7", "70.0"),  # the decimal is always shown
        ("0", "0.0"),
        ("-0.0312", "-3.1"),  # a loss-making product
        ("-0.0004", "0.0"),  # rounds to zero: never shown as -0.0
        ("-12.5", "-1250.0"),
    ],
)
def test_margin_percent(headphones: LocalisedProduct, margin_pct: str, expected: str) -> None:
    (row,) = display_rows([_with_margin(headphones, margin_pct)])
    assert row.margin_percent == expected


def test_margin_too_large_to_display_names_the_sku(headphones: LocalisedProduct) -> None:
    # -1E+29 percent needs 31 digits at one decimal; the decimal context holds 28.
    absurd = _with_margin(headphones, "-1E+27")

    with pytest.raises(LocalisationError) as excinfo:
        display_rows([absurd])

    assert str(excinfo.value).startswith(f"{HEADPHONES}: ")
    assert isinstance(excinfo.value.__cause__, ArithmeticError)


# --- result objects -----------------------------------------------------------------------


def test_display_row_is_frozen(localised: list[LocalisedProduct]) -> None:
    row = display_rows(localised)[0]
    with pytest.raises(FrozenInstanceError):
        row.shelf_price = "1.00"  # type: ignore[misc]
