"""M5: display rows shared by the CLI and the dashboard."""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from helpers import decimal_places
from souqsort.display import (
    DisplayRow,
    DisplaySummary,
    GridRow,
    display_rows,
    display_summary,
    grid_rows,
    search_products,
)
from souqsort.models import Catalogue, GccConfig
from souqsort.pipeline import (
    CatalogueSummary,
    LocalisationError,
    LocalisedProduct,
    localise_catalogue,
    summarise_catalogue,
)

HEADPHONES = "ELEC-HP-001"
CHARGER = "ELEC-CHG-002"
BAG = "FASH-BAG-014"
SCARF = "FASH-SCF-015"
KETTLEBELL = "SPRT-KTB-020"
KETTLE = "HOME-KTL-030"
LIP_BALM = "BEAU-LIP-040"
SERUM = "BEAU-SRM-041"
LICENCE = "DIGI-LIC-050"
TEA = "GROC-TEA-060"
VANILLA = "GROC-VAN-061"
GUMMY_BEARS = "GROC-GUM-062"

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


# --- grid rows: display rows whose price and margin are numbers ---------------------------


def test_grid_rows_show_what_the_display_rows_show(localised: list[LocalisedProduct]) -> None:
    rows = grid_rows(localised)
    text_rows = display_rows(localised)

    assert len(rows) == 12
    for row, text in zip(rows, text_rows, strict=True):
        assert isinstance(row, GridRow)
        assert (row.sku, row.name_en, row.delivery_date) == (
            text.sku,
            text.name_en,
            text.delivery_date,
        )
        # str() of a Decimal keeps its digits, so this is the same text the CLI prints.
        assert str(row.shelf_price) == text.shelf_price
        assert str(row.margin_percent) == text.margin_percent

    # Flags are the one difference: the CLI prints their codes, the grid their labels.
    assert {row.flags for row in rows} == {"", "No Arabic name"}


def test_worked_example_grid_rows(localised: list[LocalisedProduct]) -> None:
    rows = {row.sku: row for row in grid_rows(localised)}

    assert rows[HEADPHONES] == GridRow(
        sku="ELEC-HP-001",
        name_en="Wireless Noise-Cancelling Headphones",
        shelf_price=Decimal("686.95"),
        margin_percent=Decimal("58.7"),
        delivery_date="2026-10-25",
        flags="",
    )
    assert rows[BAG] == GridRow(
        sku="FASH-BAG-014",
        name_en="Leather Crossbody Bag",
        shelf_price=Decimal("594.95"),
        margin_percent=Decimal("64.6"),
        delivery_date="2026-10-25",
        flags="No Arabic name",
    )


def test_grid_price_and_margin_are_decimals_never_floats_or_text(
    localised: list[LocalisedProduct],
) -> None:
    for row in grid_rows(localised):
        assert type(row.shelf_price) is Decimal
        assert type(row.margin_percent) is Decimal
        assert decimal_places(row.shelf_price) == 2  # the currency's minor units
        assert decimal_places(row.margin_percent) == 1


def test_grid_prices_sort_by_value_where_text_would_not(
    localised: list[LocalisedProduct],
) -> None:
    by_value = [row.sku for row in sorted(grid_rows(localised), key=lambda row: row.shelf_price)]
    as_text = [row.sku for row in sorted(display_rows(localised), key=lambda row: row.shelf_price)]

    assert by_value == [
        LIP_BALM,  # 16.95
        GUMMY_BEARS,  # 22.95
        TEA,  # 34.95
        VANILLA,  # 61.95
        SERUM,  # 111.95
        CHARGER,  # 184.95
        KETTLE,  # 237.95
        SCARF,  # 293.95
        LICENCE,  # 340.95
        KETTLEBELL,  # 593.95
        BAG,  # 594.95
        HEADPHONES,  # 686.95
    ]
    assert as_text[:2] == [SERUM, LIP_BALM]  # as text, "111.95" comes before "16.95"


def test_grid_margins_sort_by_value(headphones: LocalisedProduct) -> None:
    margins = ["0.7", "-0.0312", "0.058", "-0.25", "1.0"]
    rows = grid_rows([_with_margin(headphones, margin) for margin in margins])

    in_order = sorted(row.margin_percent for row in rows)

    # As text these would run "-25.0", "-3.1", "100.0", "5.8", "70.0".
    assert [str(margin) for margin in in_order] == ["-25.0", "-3.1", "5.8", "70.0", "100.0"]


def test_grid_price_has_the_currency_minor_units(
    catalogue: Catalogue, zero_vat_config: GccConfig
) -> None:
    items = localise_catalogue(catalogue.products, zero_vat_config, ZERO_VAT_MARKET, THU_EVENING)

    rows = {row.sku: row for row in grid_rows(items)}

    assert str(rows[HEADPHONES].shelf_price) == "48.950"  # three decimals, trailing zero kept
    assert all(decimal_places(row.shelf_price) == 3 for row in rows.values())


def test_grid_margin_that_rounds_to_zero_is_not_negative(headphones: LocalisedProduct) -> None:
    (row,) = grid_rows([_with_margin(headphones, "-0.0004")])

    assert str(row.margin_percent) == "0.0"
    assert not row.margin_percent.is_signed()


def test_grid_rows_of_an_empty_list() -> None:
    assert grid_rows([]) == []


def test_grid_margin_too_large_to_display_names_the_sku(headphones: LocalisedProduct) -> None:
    with pytest.raises(LocalisationError, match=f"^{HEADPHONES}: "):
        grid_rows([_with_margin(headphones, "-1E+27")])


# --- grid flags: labels a person can read -------------------------------------------------


def test_grid_shows_a_missing_arabic_name_as_a_label(localised: list[LocalisedProduct]) -> None:
    flags = {row.sku: row.flags for row in grid_rows(localised)}

    assert flags[BAG] == flags[TEA] == "No Arabic name"
    assert all(flag == "" for sku, flag in flags.items() if sku not in {BAG, TEA})


def test_display_rows_keep_the_flag_codes(localised: list[LocalisedProduct]) -> None:
    # The CLI table and the CSV are read by scripts as well as people: their codes stay.
    rows = {row.sku: row for row in display_rows(localised)}
    assert rows[BAG].flags == ("missing_arabic_name",)


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ((), ""),
        (("missing_arabic_name",), "No Arabic name"),
        (("banned_attribute",), "banned_attribute"),  # no label yet: the code, not a blank
        (("missing_arabic_name", "banned_attribute"), "No Arabic name, banned_attribute"),
    ],
    ids=["none", "labelled", "unlabelled", "several"],
)
def test_grid_flag_labels(
    headphones: LocalisedProduct, flags: tuple[str, ...], expected: str
) -> None:
    (row,) = grid_rows([replace(headphones, flags=flags)])
    assert row.flags == expected


# --- search: SKU or English name ----------------------------------------------------------


def _skus(items: list[LocalisedProduct]) -> list[str]:
    return [item.sku for item in items]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("ELEC-", [HEADPHONES, CHARGER]),  # part of a SKU
        ("FASH-BAG-014", [BAG]),  # a whole SKU
        ("crossbody", [BAG]),  # part of a name
        ("elec", [HEADPHONES, CHARGER, KETTLE]),  # two SKUs, and "Electric Kettle 1.7 L"
        ("bag", [BAG, TEA]),  # a SKU and its name, and "English Breakfast Tea, 80 bags"
        ("noise-cancelling headphones", [HEADPHONES]),  # several words, as one phrase
    ],
)
def test_search_matches_part_of_a_sku_or_an_english_name(
    localised: list[LocalisedProduct], query: str, expected: list[str]
) -> None:
    assert _skus(search_products(localised, query)) == expected


@pytest.mark.parametrize("query", ["KETTLE", "kettle", "KeTtLe"])
def test_search_ignores_case(localised: list[LocalisedProduct], query: str) -> None:
    assert _skus(search_products(localised, query)) == [KETTLEBELL, KETTLE]


def test_search_ignores_spaces_around_the_query(localised: list[LocalisedProduct]) -> None:
    assert _skus(search_products(localised, "  silk \t")) == [SCARF]


@pytest.mark.parametrize("query", ["", " ", "\t\n"], ids=["empty", "space", "whitespace"])
def test_blank_search_keeps_every_product(localised: list[LocalisedProduct], query: str) -> None:
    assert search_products(localised, query) == localised


def test_search_with_no_match_gives_no_products(localised: list[LocalisedProduct]) -> None:
    assert search_products(localised, "no such product") == []


@pytest.mark.parametrize(
    "query",
    ["electronics", "missing_arabic", "No Arabic", "686.95", "2026-10-25", "SAR", "سماعات"],
    ids=["category", "flag", "flag-label", "price", "delivery-date", "currency", "arabic-name"],
)
def test_search_looks_only_at_the_sku_and_the_english_name(
    localised: list[LocalisedProduct], query: str
) -> None:
    assert search_products(localised, query) == []


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("1.7", [KETTLE]),  # "Electric Kettle 1.7 L"
        (".*", []),  # as a pattern this would match every product
        ("(", [LICENCE, GUMMY_BEARS]),  # "(digital download)" and "(pork gelatine)"
        ("[", []),
    ],
)
def test_search_text_is_literal_not_a_pattern(
    localised: list[LocalisedProduct], query: str, expected: list[str]
) -> None:
    assert _skus(search_products(localised, query)) == expected


def test_search_returns_the_products_themselves_in_catalogue_order(
    localised: list[LocalisedProduct],
) -> None:
    found = search_products(localised, "groc")

    assert _skus(found) == [TEA, VANILLA, GUMMY_BEARS]
    assert all(any(item is original for original in localised) for item in found)


def test_search_of_an_empty_list() -> None:
    assert search_products([], "bag") == []


# --- summary: the dashboard's headline figures as text ------------------------------------


def _summary(margin: str | None, change: str | None, flagged: int = 2) -> CatalogueSummary:
    return CatalogueSummary(
        product_count=12,
        flagged_count=flagged,
        average_margin_pct=None if margin is None else Decimal(margin),
        average_price_change_pct=None if change is None else Decimal(change),
    )


def test_summary_of_the_sample_catalogue(localised: list[LocalisedProduct]) -> None:
    summary = summarise_catalogue(localised, localised)

    assert display_summary(summary) == DisplaySummary(
        average_margin="67.7%",
        flagged_products="2",
        average_price_change="0.0%",
    )


def test_summary_of_the_sample_catalogue_at_three_points(
    catalogue: Catalogue, config: GccConfig, localised: list[LocalisedProduct]
) -> None:
    adjusted = localise_catalogue(catalogue.products, config, "KSA", THU_EVENING, Decimal("0.03"))

    assert display_summary(summarise_catalogue(adjusted, localised)) == DisplaySummary(
        average_margin="67.4%",
        flagged_products="2",
        average_price_change="+2.1%",
    )


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("0", "0.0%"),
        ("0.0213714", "+2.1%"),
        ("0.0215", "+2.2%"),  # 2.15: half up
        ("0.1851218", "+18.5%"),
        ("0.0004", "0.0%"),  # rounds to zero: no sign
        ("-0.0004", "0.0%"),
        ("-0.0312", "-3.1%"),
    ],
)
def test_price_change_is_a_signed_percentage_with_one_decimal(change: str, expected: str) -> None:
    assert display_summary(_summary("0.6768", change)).average_price_change == expected


@pytest.mark.parametrize(
    ("margin", "expected"),
    [("0.6768330", "67.7%"), ("0.5865", "58.7%"), ("0", "0.0%"), ("-0.0312", "-3.1%")],
)
def test_average_margin_is_a_percentage_with_one_decimal_and_no_plus_sign(
    margin: str, expected: str
) -> None:
    assert display_summary(_summary(margin, "0")).average_margin == expected


def test_summary_without_averages_shows_a_dash() -> None:
    empty = CatalogueSummary(
        product_count=0, flagged_count=0, average_margin_pct=None, average_price_change_pct=None
    )

    assert display_summary(empty) == DisplaySummary(
        average_margin="-", flagged_products="0", average_price_change="-"
    )


@pytest.mark.parametrize(
    ("margin", "change", "figure"),
    [
        ("-1E+27", "0", "average margin"),
        ("0.5", "1E+27", "average price change"),
    ],
    ids=["margin", "price-change"],
)
def test_average_too_large_to_display_is_a_localisation_error(
    margin: str, change: str, figure: str
) -> None:
    # The same limit as a single margin: 1E+29 percent needs 31 digits at one decimal.
    with pytest.raises(LocalisationError, match=f"{figure} is too large to display") as excinfo:
        display_summary(_summary(margin, change))

    assert isinstance(excinfo.value.__cause__, ArithmeticError)


# --- result objects -----------------------------------------------------------------------


def test_display_row_is_frozen(localised: list[LocalisedProduct]) -> None:
    row = display_rows(localised)[0]
    with pytest.raises(FrozenInstanceError):
        row.shelf_price = "1.00"  # type: ignore[misc]


def test_grid_row_and_display_summary_are_frozen(localised: list[LocalisedProduct]) -> None:
    row = grid_rows(localised)[0]
    with pytest.raises(FrozenInstanceError):
        row.shelf_price = Decimal("1.00")  # type: ignore[misc]

    summary = display_summary(summarise_catalogue(localised, localised))
    with pytest.raises(FrozenInstanceError):
        summary.average_margin = "100.0%"  # type: ignore[misc]
