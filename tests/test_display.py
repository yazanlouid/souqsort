"""M5: display rows shared by the CLI and the dashboard."""

from dataclasses import FrozenInstanceError, astuple, fields, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, get_args

import pytest

from helpers import REPORT_ORDERED_AT, SAMPLE_PRODUCT_COUNT, decimal_places
from souqsort.compliance import ExcludedProduct
from souqsort.display import (
    ATTRIBUTE_LABELS,
    CHECKOUT_LABELS,
    SHIPPING_LABELS,
    DisplayRow,
    DisplaySummary,
    ExcludedGridRow,
    GridRow,
    display_rows,
    display_summary,
    duty_text,
    excluded_grid_rows,
    grid_rows,
    order_rows,
    parcel_fee_note,
    parcel_note,
    search_products,
)
from souqsort.models import (
    SHIPPING_MODELS,
    AttributeName,
    Catalogue,
    GccConfig,
    OrderLine,
    ParcelFee,
    ShippingModel,
)
from souqsort.orders import CheckoutKind, OrderQuote, quote_order
from souqsort.pipeline import (
    CatalogueSummary,
    LocalisationError,
    LocalisedProduct,
    duty_adjustment_from_points,
    localise_catalogue,
    summarise_catalogue,
)

HEADPHONES = "ELEC-HP-001"
CHARGER = "ELEC-CHG-002"
BAG = "FASH-BAG-014"
SCARF = "FASH-SCF-015"
KETTLEBELL = "SPRT-KTB-020"
KETTLE = "HOME-KTL-030"
ESPRESSO = "HOME-ESP-031"
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

    assert len(rows) == SAMPLE_PRODUCT_COUNT
    assert [row.sku for row in rows] == [item.sku for item in localised]


def test_worked_example_rows(localised: list[LocalisedProduct]) -> None:
    rows = {row.sku: row for row in display_rows(localised)}

    assert rows[HEADPHONES] == DisplayRow(
        sku="ELEC-HP-001",
        name_en="Wireless Noise-Cancelling Headphones",
        currency="SAR",
        shelf_price="686.95",
        margin_percent="58.7",
        duty_percent="5.0",
        duty_waived=False,
        delivery_date="2026-10-25",
        flags=(),
    )
    assert rows[BAG] == DisplayRow(
        sku="FASH-BAG-014",
        name_en="Leather Crossbody Bag",
        currency="SAR",
        shelf_price="594.95",
        margin_percent="64.6",
        duty_percent="12.0",
        duty_waived=False,
        delivery_date="2026-10-25",
        flags=("missing_arabic_name",),
    )


def test_every_value_is_text_except_the_flags_and_duty_waived(
    localised: list[LocalisedProduct],
) -> None:
    kinds = {"flags": tuple, "duty_waived": bool}
    for row in display_rows(localised):
        for field in fields(row):
            value = getattr(row, field.name)
            assert isinstance(value, kinds.get(field.name, str)), field.name


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


# --- the parcel fee note (SPEC §10.5, M15) ------------------------------------------------

KSA_FEE_NOTE = "Each parcel order also pays a customs fee of 15.00 SAR at checkout."


def test_parcel_fee_note_names_ksa_s_fee_for_a_direct_parcel(config: GccConfig) -> None:
    assert parcel_fee_note(config.markets["KSA"], "parcel") == KSA_FEE_NOTE


def test_no_parcel_fee_note_for_a_consolidated_import(config: GccConfig) -> None:
    assert parcel_fee_note(config.markets["KSA"], "consolidated") is None


@pytest.mark.parametrize("shipping", ["consolidated", "parcel"])
@pytest.mark.parametrize("code", ["UAE", "KWT"])
def test_no_parcel_fee_note_without_a_fee(
    config: GccConfig, code: str, shipping: ShippingModel
) -> None:
    assert parcel_fee_note(config.markets[code], shipping) is None


@pytest.mark.parametrize("shipping", ["bulk", "Parcel", "", None])
def test_parcel_fee_note_rejects_an_unknown_shipping_model(
    config: GccConfig, shipping: Any
) -> None:
    with pytest.raises(ValueError, match="one of consolidated, parcel"):
        parcel_fee_note(config.markets["KSA"], shipping)


@pytest.mark.parametrize(("amount", "shown"), [("15", "15.000"), ("1234.5", "1234.500")])
def test_parcel_fee_note_shows_the_currency_s_minor_units(
    config: GccConfig, amount: str, shown: str
) -> None:
    kwt = config.markets["KWT"]
    fee = ParcelFee(amount=Decimal(amount), source="test fee")
    market = kwt.model_copy(update={"customs": kwt.customs.model_copy(update={"parcel_fee": fee})})

    assert parcel_fee_note(market, "parcel") == (
        f"Each parcel order also pays a customs fee of {shown} KWD at checkout."
    )


# --- orders (SPEC §10.5, M17) -------------------------------------------------------------


def _both(
    config: GccConfig, catalogue: Catalogue, code: str, *items: tuple[str, int], points: int = 0
) -> tuple[OrderQuote, OrderQuote]:
    """An order priced in a market as a consolidated import and as a direct parcel."""
    lines = [OrderLine(sku=sku, quantity=quantity) for sku, quantity in items]
    consolidated, parcel = (
        quote_order(
            lines,
            catalogue,
            config,
            code,
            REPORT_ORDERED_AT,
            duty_adjustment_from_points(points),
            shipping,
        )
        for shipping in SHIPPING_MODELS
    )
    return consolidated, parcel


def _rows(consolidated: OrderQuote, parcel: OrderQuote) -> list[tuple[str, ...]]:
    return [astuple(row) for row in order_rows(consolidated, parcel)]


def test_order_rows_of_headphones_and_a_bag_in_ksa(config: GccConfig, catalogue: Catalogue) -> None:
    quotes = _both(config, catalogue, "KSA", (HEADPHONES, 1), (BAG, 1))

    assert _rows(*quotes) == [
        (HEADPHONES, "Wireless Noise-Cancelling Headphones", "1", "686.95", "660.95"),
        (BAG, "Leather Crossbody Bag", "1", "594.95", "546.95"),
        ("Items", "", "", "1281.90", "1207.90"),
        ("Customs fee", "", "", "-", "15.00"),
        ("Duty and VAT", "", "", "-", "98.57"),
        ("Total", "", "", "1281.90", "1321.47"),
        ("Delivery", "", "", "2026-10-22", "2026-10-21"),
    ]


def test_order_rows_at_three_points(config: GccConfig, catalogue: Catalogue) -> None:
    quotes = _both(config, catalogue, "KSA", (HEADPHONES, 1), (BAG, 1), points=3)
    rows = {row[0]: row[3:] for row in _rows(*quotes)}

    assert rows["Duty and VAT"] == ("-", "134.77")
    assert rows["Total"] == ("1316.90", "1357.67")  # consolidated prices carry the duty


def test_order_rows_in_the_uae_have_no_fee_row(config: GccConfig, catalogue: Catalogue) -> None:
    rows = _rows(*_both(config, catalogue, "UAE", (HEADPHONES, 1), (BAG, 1)))

    assert [row[0] for row in rows] == [
        HEADPHONES,
        BAG,
        "Items",
        "Duty and VAT",
        "Total",
        "Delivery",
    ]
    assert rows[3][3:] == ("-", "53.73")
    assert rows[4][3:] == ("1109.98", "1129.71")


def test_order_rows_in_kuwait_have_no_checkout_rows_and_three_decimals(
    config: GccConfig, catalogue: Catalogue
) -> None:
    rows = _rows(*_both(config, catalogue, "KWT", (SCARF, 1), (SERUM, 1)))

    assert [row[0] for row in rows] == [SCARF, SERUM, "Items", "Total", "Delivery"]
    assert rows[3][3:] == ("27.900", "28.900")


def test_order_rows_of_two_lip_balms_in_ksa(config: GccConfig, catalogue: Catalogue) -> None:
    rows = _rows(*_both(config, catalogue, "KSA", (LIP_BALM, 2)))

    assert rows[0] == (LIP_BALM, "Lip Balm", "2", "33.90", "31.90")
    assert [row[0] for row in rows] == [LIP_BALM, "Items", "Customs fee", "Total", "Delivery"]
    assert rows[3][3:] == ("33.90", "46.90")


def test_order_rows_leave_out_what_the_market_does_not_sell(
    config: GccConfig, catalogue: Catalogue
) -> None:
    rows = _rows(*_both(config, catalogue, "KSA", (VANILLA, 1), (TEA, 3)))

    assert [row[0] for row in rows][:2] == [TEA, "Items"]
    assert VANILLA not in [row[0] for row in rows]


def test_order_rows_reject_quotes_of_different_orders(
    config: GccConfig, catalogue: Catalogue
) -> None:
    ksa, _ = _both(config, catalogue, "KSA", (LIP_BALM, 2))
    _, uae = _both(config, catalogue, "UAE", (LIP_BALM, 2))
    _, other = _both(config, catalogue, "KSA", (SERUM, 1))

    with pytest.raises(ValueError, match="not the same order"):
        order_rows(ksa, uae)
    with pytest.raises(ValueError, match="not the same order"):
        order_rows(ksa, other)


def test_checkout_labels_cover_every_checkout_kind() -> None:
    assert set(CHECKOUT_LABELS) == set(get_args(CheckoutKind))
    assert list(CHECKOUT_LABELS.values()) == ["Customs fee", "Duty and VAT"]


def test_order_row_is_frozen(config: GccConfig, catalogue: Catalogue) -> None:
    row = order_rows(*_both(config, catalogue, "KSA", (LIP_BALM, 2)))[0]
    with pytest.raises(FrozenInstanceError):
        row.label = "x"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("code", "items", "note"),
    [
        (
            "KSA",
            ((HEADPHONES, 1), (BAG, 1)),
            "Direct parcel: the order's CIF, 1049.26 SAR, is not below 1000.00 SAR, so the whole "
            "order pays duty; the duty its shelf prices left out is added at checkout.",
        ),
        (
            "KSA",
            ((ESPRESSO, 1),),
            "Direct parcel: the order's CIF, 3597.53 SAR, is not below 1000.00 SAR, so the whole "
            "order pays duty; its shelf prices already include it.",
        ),
        (
            "KSA",
            ((LIP_BALM, 2), (LICENCE, 1)),
            "Direct parcel: the order's CIF, 27.53 SAR, is below 1000.00 SAR, so de minimis "
            "applies.",
        ),
        (
            "UAE",
            ((HEADPHONES, 1), (BAG, 1)),
            "Direct parcel: the order's CIF, 1023.35 AED, is not at or below 1000.00 AED, so the "
            "whole order pays duty; the duty its shelf prices left out is added at checkout.",
        ),
        (
            "UAE",
            ((LIP_BALM, 2),),
            "Direct parcel: the order's CIF, 26.81 AED, is at or below 1000.00 AED, so de minimis "
            "applies.",
        ),
        (
            "KWT",
            ((LIP_BALM, 2),),
            "Direct parcel: KWT has no de minimis rule, so every line pays duty.",
        ),
        (
            "KSA",
            ((LICENCE, 1),),
            "Direct parcel: nothing in the order travels, so no parcel is sent.",
        ),
    ],
)
def test_parcel_note(
    config: GccConfig,
    catalogue: Catalogue,
    code: str,
    items: tuple[tuple[str, int], ...],
    note: str,
) -> None:
    _, parcel = _both(config, catalogue, code, *items)
    assert parcel_note(config.markets[code], parcel) == note


def test_parcel_note_shows_the_threshold_in_minor_units(
    config: GccConfig, catalogue: Catalogue
) -> None:
    ksa = config.markets["KSA"]
    rule = ksa.customs.de_minimis
    assert rule is not None
    customs = ksa.customs.model_copy(
        update={"de_minimis": rule.model_copy(update={"threshold": Decimal("1000")})}
    )
    market = ksa.model_copy(update={"customs": customs})
    _, parcel = _both(config, catalogue, "KSA", (LIP_BALM, 2))

    assert "is below 1000.00 SAR" in parcel_note(market, parcel)


# --- duty (SPEC §7.1 and §9.1, M10) -------------------------------------------------------


@pytest.mark.parametrize(
    ("sku", "points", "shipping", "percent", "waived", "cell"),
    [
        (HEADPHONES, "0", "consolidated", "5.0", False, "5.0%"),
        (BAG, "0.03", "consolidated", "15.0", False, "15.0%"),  # fashion 12% + 3 pp
        (LICENCE, "0", "consolidated", "0.0", False, "0.0%"),  # duty-free, but not waived
        (HEADPHONES, "0", "parcel", "0.0", True, "waived"),  # SPEC §7.8 E
        (HEADPHONES, "0.20", "parcel", "0.0", True, "waived"),  # whatever the adjustment
        (BAG, "0.03", "parcel", "0.0", True, "waived"),
        (ESPRESSO, "0.03", "parcel", "8.0", False, "8.0%"),  # above the threshold
        (LICENCE, "0", "parcel", "0.0", False, "0.0%"),  # SPEC §7.9.2: never travels
        (LICENCE, "0.03", "parcel", "3.0", False, "3.0%"),  # so the adjustment applies
    ],
)
def test_duty_cells(
    catalogue: Catalogue,
    config: GccConfig,
    sku: str,
    points: str,
    shipping: ShippingModel,
    percent: str,
    waived: bool,
    cell: str,
) -> None:
    items = localise_catalogue(
        catalogue.products, config, "KSA", THU_EVENING, Decimal(points), shipping
    )
    item = next(item for item in items if item.sku == sku)

    (row,) = display_rows([item])
    (grid_row,) = grid_rows([item])

    assert (row.duty_percent, row.duty_waived) == (percent, waived)
    assert duty_text(row) == cell
    assert grid_row.duty == cell


def test_duty_rate_too_large_to_display_names_the_sku(headphones: LocalisedProduct) -> None:
    absurd = replace(headphones, quote=replace(headphones.quote, duty_rate=Decimal("1E+27")))

    with pytest.raises(LocalisationError) as excinfo:
        display_rows([absurd])

    assert str(excinfo.value).startswith(f"{HEADPHONES}: duty rate")
    assert isinstance(excinfo.value.__cause__, ArithmeticError)


def test_shipping_labels_cover_every_shipping_model() -> None:
    assert list(SHIPPING_LABELS) == list(get_args(ShippingModel))
    assert SHIPPING_LABELS == {"consolidated": "Consolidated import", "parcel": "Direct parcel"}


# --- grid rows: display rows whose price and margin are numbers ---------------------------


def test_grid_rows_show_what_the_display_rows_show(localised: list[LocalisedProduct]) -> None:
    rows = grid_rows(localised)
    text_rows = display_rows(localised)

    assert len(rows) == SAMPLE_PRODUCT_COUNT
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
        assert row.duty == duty_text(text)  # the same Duty cell as the CLI table

    # Flags are the one difference: the CLI prints their codes, the grid their labels.
    assert {row.flags for row in rows} == {"", "No Arabic name"}


def test_worked_example_grid_rows(localised: list[LocalisedProduct]) -> None:
    rows = {row.sku: row for row in grid_rows(localised)}

    assert rows[HEADPHONES] == GridRow(
        sku="ELEC-HP-001",
        name_en="Wireless Noise-Cancelling Headphones",
        shelf_price=Decimal("686.95"),
        margin_percent=Decimal("58.7"),
        duty="5.0%",
        delivery_date="2026-10-25",
        flags="",
    )
    assert rows[BAG] == GridRow(
        sku="FASH-BAG-014",
        name_en="Leather Crossbody Bag",
        shelf_price=Decimal("594.95"),
        margin_percent=Decimal("64.6"),
        duty="12.0%",
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
        ESPRESSO,  # 4144.95
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


# --- not sold: reasons as labels a person can read (SPEC §7.6, M9) -----------------------


def test_every_attribute_has_a_label() -> None:
    assert set(ATTRIBUTE_LABELS) == set(get_args(AttributeName))
    assert ATTRIBUTE_LABELS == {
        "contains_alcohol": "Contains alcohol",
        "contains_pork": "Contains pork",
        "contains_lithium_battery": "Contains lithium battery",
    }


def test_excluded_grid_rows_show_labels_in_the_same_order() -> None:
    excluded = (
        ExcludedProduct(VANILLA, "Pure Vanilla Extract", ("contains_alcohol",)),
        ExcludedProduct(GUMMY_BEARS, "Gummy Bears (pork gelatine)", ("contains_pork",)),
    )

    assert excluded_grid_rows(excluded) == [
        ExcludedGridRow(VANILLA, "Pure Vanilla Extract", "Contains alcohol"),
        ExcludedGridRow(GUMMY_BEARS, "Gummy Bears (pork gelatine)", "Contains pork"),
    ]


def test_several_reasons_are_joined_in_the_markets_order() -> None:
    both = ExcludedProduct("TEST-001", "Test", ("contains_pork", "contains_alcohol"))
    (row,) = excluded_grid_rows([both])
    assert row.reasons == "Contains pork, Contains alcohol"


def test_no_excluded_products_gives_no_rows() -> None:
    assert excluded_grid_rows([]) == []


def test_excluded_grid_row_is_frozen() -> None:
    (row,) = excluded_grid_rows([ExcludedProduct("TEST-001", "Test", ("contains_pork",))])
    with pytest.raises(FrozenInstanceError):
        row.reasons = ""  # type: ignore[misc]


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
        average_margin="65.6%",
        flagged_products="2",
        average_price_change="0.0%",
    )


def test_summary_of_the_sample_catalogue_at_three_points(
    catalogue: Catalogue, config: GccConfig, localised: list[LocalisedProduct]
) -> None:
    adjusted = localise_catalogue(catalogue.products, config, "KSA", THU_EVENING, Decimal("0.03"))

    assert display_summary(summarise_catalogue(adjusted, localised)) == DisplaySummary(
        average_margin="65.3%",
        flagged_products="2",
        average_price_change="+2.2%",
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
