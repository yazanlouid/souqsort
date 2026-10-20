"""M11 and M12: the expansion report's figures (SPEC §9.2), all Decimal."""

from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from helpers import (
    FOR_SALE_COUNTS,
    GUMMY_BEARS,
    REPORT_ORDERED_AT,
    SAMPLE_PRODUCT_COUNT,
    VANILLA,
    only_products,
)
from souqsort.models import Catalogue, GccConfig, ShippingModel
from souqsort.pipeline import (
    MAX_DUTY_ADJUST_POINTS,
    LocalisationError,
    duty_adjustment_from_points,
    localise_and_summarise,
)
from souqsort.pricing.customs import SHIPPING_MODELS
from souqsort.pricing.money import round_minor
from souqsort.report import build_report, figures
from souqsort.report.figures import (
    HEADLINE_TARIFF_RISE_POINTS,
    TARIFF_RISES_POINTS,
    ExpansionReport,
    MarketOverview,
    ProductComparison,
    ShippingComparison,
)


def _percent(fraction: Decimal | None) -> Decimal | None:
    """A fraction as a percentage with one decimal, as the report shows it."""
    return None if fraction is None else round_minor(fraction * 100, 1)


@pytest.fixture(scope="module")
def report(catalogue: Catalogue, config: GccConfig) -> ExpansionReport:
    return build_report(catalogue, config, REPORT_ORDERED_AT)


def _market(report: ExpansionReport, code: str) -> MarketOverview:
    return next(market for market in report.markets if market.code == code)


# --- markets side by side (§9.2.1) --------------------------------------------------------


def test_markets_are_in_config_order(report: ExpansionReport, config: GccConfig) -> None:
    assert [market.code for market in report.markets] == list(config.markets)


def test_each_market_has_its_name_currency_and_vat_rate(report: ExpansionReport) -> None:
    assert [(m.code, m.name, m.currency, m.vat_rate) for m in report.markets] == [
        ("KSA", "Saudi Arabia", "SAR", Decimal("0.15")),
        ("UAE", "United Arab Emirates", "AED", Decimal("0.05")),
        ("KWT", "Kuwait", "KWD", Decimal("0")),
    ]


def test_products_for_sale_and_not_sold(report: ExpansionReport) -> None:
    assert {m.code: m.for_sale for m in report.markets} == FOR_SALE_COUNTS
    assert {m.code: len(m.not_sold) for m in report.markets} == {"KSA": 2, "UAE": 1, "KWT": 2}
    for market in report.markets:
        assert market.for_sale + len(market.not_sold) == SAMPLE_PRODUCT_COUNT


@pytest.mark.parametrize(
    ("code", "margin", "above"),
    [("KSA", "64.6", "41.2"), ("UAE", "64.9", "24.7"), ("KWT", "66.6", "33.1")],
)
def test_averages_of_the_markets_table(
    report: ExpansionReport, code: str, margin: str, above: str
) -> None:
    market = _market(report, code)

    assert _percent(market.average_margin_pct) == Decimal(margin)
    assert _percent(market.average_above_catalogue_pct) == Decimal(above)


@pytest.mark.parametrize(
    ("code", "local", "cutoff", "delivered"),
    [
        ("KSA", time(12, 0), time(14, 0), date(2026, 10, 22)),
        ("UAE", time(13, 0), time(15, 0), date(2026, 10, 21)),
        ("KWT", time(12, 0), time(13, 0), date(2026, 10, 22)),
    ],
)
def test_order_time_cutoff_and_delivery(
    report: ExpansionReport, code: str, local: time, cutoff: time, delivered: date
) -> None:
    market = _market(report, code)
    ordered_at_local = market.delivery.ordered_at_local

    assert (ordered_at_local.date(), ordered_at_local.time()) == (date(2026, 10, 15), local)
    assert market.cutoff == cutoff
    assert market.delivery.delivery_date == delivered


def test_figures_come_from_localise_and_summarise(
    report: ExpansionReport, catalogue: Catalogue, config: GccConfig
) -> None:
    for market in report.markets:
        localised = localise_and_summarise(
            catalogue.products, config, market.code, REPORT_ORDERED_AT
        )
        quotes = [item.quote for item in localised.items]
        above = sum((q.shelf_price / q.goods - 1 for q in quotes), Decimal(0)) / len(quotes)

        assert market.for_sale == len(localised.items)
        assert market.not_sold == localised.excluded
        assert market.average_margin_pct == localised.summary.average_margin_pct
        assert market.average_above_catalogue_pct == above
        assert market.delivery == localised.items[0].delivery


def test_averages_keep_full_precision(report: ExpansionReport) -> None:
    for market in report.markets:
        assert isinstance(market.average_margin_pct, Decimal)
        assert isinstance(market.average_above_catalogue_pct, Decimal)
        assert market.average_above_catalogue_pct != _percent(market.average_above_catalogue_pct)


# --- not sold (§9.2.6) --------------------------------------------------------------------


def test_not_sold_lists_and_reasons(report: ExpansionReport) -> None:
    assert {m.code: [(item.sku, item.reasons) for item in m.not_sold] for m in report.markets} == {
        "KSA": [(VANILLA, ("contains_alcohol",)), (GUMMY_BEARS, ("contains_pork",))],
        "UAE": [(GUMMY_BEARS, ("contains_pork",))],
        "KWT": [(VANILLA, ("contains_alcohol",)), (GUMMY_BEARS, ("contains_pork",))],
    }


# --- provenance and edge cases ------------------------------------------------------------


def test_report_names_its_data_and_order(report: ExpansionReport) -> None:
    assert report.ordered_at == REPORT_ORDERED_AT
    assert report.config_version == "2026-10-01"
    assert report.fx_as_of == date(2026, 10, 1)
    assert report.catalogue_version == "2026-10-01"
    assert report.product_count == SAMPLE_PRODUCT_COUNT


def test_a_market_that_sells_nothing_has_no_averages_but_a_delivery_date(
    catalogue: Catalogue, config: GccConfig
) -> None:
    report = build_report(only_products(catalogue, VANILLA, GUMMY_BEARS), config, REPORT_ORDERED_AT)
    ksa = _market(report, "KSA")

    assert ksa.for_sale == 0
    assert ksa.average_margin_pct is None
    assert ksa.average_above_catalogue_pct is None
    assert ksa.delivery.delivery_date == date(2026, 10, 22)
    assert _market(report, "UAE").for_sale == 1


def test_an_empty_catalogue_gives_every_market_with_nothing_for_sale(
    catalogue: Catalogue, config: GccConfig
) -> None:
    report = build_report(only_products(catalogue), config, REPORT_ORDERED_AT)

    assert report.product_count == 0
    assert [(m.for_sale, m.not_sold) for m in report.markets] == [(0, ())] * len(config.markets)


def test_a_naive_order_time_is_rejected(catalogue: Catalogue, config: GccConfig) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_report(catalogue, config, REPORT_ORDERED_AT.replace(tzinfo=None))


def test_an_order_time_beyond_the_calendar_raises_localisation_error(
    catalogue: Catalogue, config: GccConfig
) -> None:
    with pytest.raises(LocalisationError, match=r"^KSA:"):
        build_report(catalogue, config, datetime(9999, 12, 31, 23, 0, tzinfo=UTC))


# --- consolidated or parcel (§9.2.2) ------------------------------------------------------

# SPEC §7.9.1 and §7.9.2 for the products each market sells, in catalogue order:
# (SKU, consolidated, direct parcel, duty waived on the parcel).
PRICE_LISTS: dict[str, list[tuple[str, str, str, bool]]] = {
    "KSA": [
        ("ELEC-HP-001", "686.95", "660.95", True),
        ("ELEC-CHG-002", "184.95", "179.95", True),
        ("FASH-BAG-014", "594.95", "546.95", True),
        ("FASH-SCF-015", "293.95", "264.95", True),
        ("SPRT-KTB-020", "593.95", "875.95", True),
        ("HOME-KTL-030", "237.95", "249.95", True),
        ("HOME-ESP-031", "4144.95", "4344.95", False),
        ("BEAU-LIP-040", "16.95", "15.95", True),
        ("BEAU-SRM-041", "111.95", "108.95", True),
        ("DIGI-LIC-050", "340.95", "340.95", True),
        ("GROC-TEA-060", "34.95", "37.95", True),
    ],
    "UAE": [
        ("ELEC-HP-001", "612.99", "589.99", True),
        ("ELEC-CHG-002", "164.99", "159.99", True),
        ("FASH-BAG-014", "496.99", "485.99", True),
        ("FASH-SCF-015", "246.99", "236.99", True),
        ("SPRT-KTB-020", "498.99", "721.99", True),
        ("HOME-KTL-030", "209.99", "218.99", True),
        ("HOME-ESP-031", "3685.99", "3844.99", False),
        ("BEAU-LIP-040", "14.99", "14.99", True),
        ("BEAU-SRM-041", "99.99", "96.99", True),
        ("DIGI-LIC-050", "304.99", "304.99", True),
        ("GROC-TEA-060", "29.99", "32.99", True),
        (VANILLA, "55.99", "57.99", False),
    ],
    "KWT": [
        ("ELEC-HP-001", "48.950", "49.950", False),
        ("ELEC-CHG-002", "13.950", "13.950", False),
        ("FASH-BAG-014", "39.950", "41.950", False),
        ("FASH-SCF-015", "19.950", "19.950", False),
        ("SPRT-KTB-020", "44.950", "70.950", False),
        ("HOME-KTL-030", "17.950", "19.950", False),
        ("HOME-ESP-031", "296.950", "312.950", False),
        ("BEAU-LIP-040", "1.950", "1.950", False),
        ("BEAU-SRM-041", "7.950", "8.950", False),
        ("DIGI-LIC-050", "24.950", "24.950", False),
        ("GROC-TEA-060", "2.950", "2.950", False),
    ],
}


def _shipping(report: ExpansionReport, code: str) -> ShippingComparison:
    return next(market for market in report.shipping if market.code == code)


def test_shipping_comparisons_are_in_config_order(
    report: ExpansionReport, config: GccConfig
) -> None:
    assert [market.code for market in report.shipping] == list(config.markets)


def test_shipping_comparisons_name_the_market_and_its_rule(
    report: ExpansionReport, config: GccConfig
) -> None:
    for comparison in report.shipping:
        market = config.markets[comparison.code]

        assert comparison.name == market.name
        assert comparison.currency == market.currency.code
        assert comparison.minor_units == market.currency.minor_units
        assert comparison.de_minimis == market.customs.de_minimis


@pytest.mark.parametrize("code", list(PRICE_LISTS))
def test_every_price_is_the_spec_price_list(report: ExpansionReport, code: str) -> None:
    products = _shipping(report, code).products

    assert [
        (p.sku, p.consolidated_price, p.parcel_price, p.parcel_duty_waived) for p in products
    ] == [
        (sku, Decimal(consolidated), Decimal(parcel), waived)
        for sku, consolidated, parcel, waived in PRICE_LISTS[code]
    ]


def test_the_product_rows_number_34(report: ExpansionReport) -> None:
    assert sum(len(market.products) for market in report.shipping) == 34


@pytest.mark.parametrize(
    ("code", "counts"),
    [("KSA", (6, 4, 1, 10)), ("UAE", (5, 5, 2, 10)), ("KWT", (0, 6, 5, 0))],
)
def test_counts_of_the_parcel_table(
    report: ExpansionReport, code: str, counts: tuple[int, int, int, int]
) -> None:
    market = _shipping(report, code)

    assert (market.cheaper, market.dearer, market.unchanged, market.waived) == counts


def test_change_is_the_full_precision_ratio(report: ExpansionReport) -> None:
    for market in report.shipping:
        for product in market.products:
            assert product.change_pct == product.parcel_price / product.consolidated_price - 1


def test_parcel_duty_rate_is_the_parcel_quote_s(report: ExpansionReport) -> None:
    rates = {
        (market.code, p.sku): p.parcel_duty_rate
        for market in report.shipping
        for p in market.products
    }

    assert rates["KSA", "HOME-ESP-031"] == Decimal("0.05")
    assert rates["KSA", "ELEC-HP-001"] == Decimal("0")
    assert rates["UAE", VANILLA] == Decimal("0.05")
    assert rates["KWT", "ELEC-HP-001"] == Decimal("0.05")
    assert rates["KWT", "DIGI-LIC-050"] == Decimal("0")


def test_comparisons_come_from_localise_and_summarise(
    report: ExpansionReport, catalogue: Catalogue, config: GccConfig
) -> None:
    for market in report.shipping:
        consolidated, parcel = (
            localise_and_summarise(
                catalogue.products, config, market.code, REPORT_ORDERED_AT, Decimal(0), model
            )
            for model in ("consolidated", "parcel")
        )

        assert [p.sku for p in market.products] == [item.sku for item in consolidated.items]
        assert [p.consolidated_price for p in market.products] == [
            item.quote.shelf_price for item in consolidated.items
        ]
        assert [
            (p.parcel_price, p.parcel_duty_rate, p.parcel_duty_waived) for p in market.products
        ] == [
            (item.quote.shelf_price, item.quote.duty_rate, item.quote.duty_waived)
            for item in parcel.items
        ]


def test_counts_compare_prices_not_the_rounded_change() -> None:
    # +0.04% rounds to 0.0%, but the parcel is still dearer.
    comparison = ShippingComparison(
        code="A",
        name="A name",
        currency="XXX",
        minor_units=2,
        de_minimis=None,
        products=(
            ProductComparison(
                "SKU-1",
                "One",
                Decimal("2500.00"),
                Decimal("2501.00"),
                Decimal("0.0004"),
                Decimal("0.05"),
                False,
            ),
        ),
    )

    assert (comparison.cheaper, comparison.dearer, comparison.unchanged) == (0, 1, 0)


def test_a_market_that_sells_nothing_compares_nothing(
    catalogue: Catalogue, config: GccConfig
) -> None:
    report = build_report(only_products(catalogue, VANILLA, GUMMY_BEARS), config, REPORT_ORDERED_AT)
    ksa, uae = _shipping(report, "KSA"), _shipping(report, "UAE")

    assert ksa.products == ()
    assert (ksa.cheaper, ksa.dearer, ksa.unchanged, ksa.waived) == (0, 0, 0, 0)
    assert [(p.sku, p.parcel_duty_waived) for p in uae.products] == [(VANILLA, False)]
    assert (uae.cheaper, uae.dearer, uae.unchanged, uae.waived) == (0, 1, 0, 0)


def test_pairs_of_different_products_are_rejected(catalogue: Catalogue, config: GccConfig) -> None:
    # Same length, different SKUs: zip(strict=True) alone would pair them.
    market = config.markets["KSA"]
    consolidated, parcel = (
        localise_and_summarise(
            only_products(catalogue, sku).products, config, "KSA", REPORT_ORDERED_AT
        )
        for sku in ("ELEC-HP-001", "ELEC-CHG-002")
    )

    with pytest.raises(ValueError, match="parcel view has ELEC-CHG-002 where ELEC-HP-001"):
        figures._shipping(market, consolidated, parcel)


# --- tariff exposure (§9.2.3) -------------------------------------------------------------

# SPEC §9.2.3: the average price change at +5, +10 and +20 pp, rounded for display.
TARIFF_CELLS: dict[tuple[str, ShippingModel], tuple[str, str, str]] = {
    ("KSA", "consolidated"): ("4.6", "9.0", "18.6"),
    ("KSA", "parcel"): ("0.4", "0.9", "1.7"),
    ("UAE", "consolidated"): ("4.9", "9.3", "19.2"),
    ("UAE", "parcel"): ("0.8", "1.5", "3.2"),
    ("KWT", "consolidated"): ("3.8", "7.6", "16.0"),
    ("KWT", "parcel"): ("6.3", "9.4", "17.7"),
}


def test_tariff_rises_are_whole_points_the_pipeline_accepts() -> None:
    assert TARIFF_RISES_POINTS == (5, 10, 20)
    assert HEADLINE_TARIFF_RISE_POINTS in TARIFF_RISES_POINTS
    assert all(0 <= rise <= MAX_DUTY_ADJUST_POINTS for rise in TARIFF_RISES_POINTS)


def test_tariffs_are_by_market_then_shipping_model(
    report: ExpansionReport, config: GccConfig
) -> None:
    assert [(t.code, t.shipping) for t in report.tariffs] == [
        (code, model) for code in config.markets for model in SHIPPING_MODELS
    ]


def test_the_18_cells_of_the_tariff_table(report: ExpansionReport) -> None:
    assert {
        (t.code, t.shipping): tuple(_percent(change) for change in t.average_change_pct)
        for t in report.tariffs
    } == {key: tuple(Decimal(cell) for cell in cells) for key, cells in TARIFF_CELLS.items()}


def test_tariffs_come_from_localise_and_summarise(
    report: ExpansionReport, catalogue: Catalogue, config: GccConfig
) -> None:
    for exposure in report.tariffs:
        assert exposure.average_change_pct == tuple(
            localise_and_summarise(
                catalogue.products,
                config,
                exposure.code,
                REPORT_ORDERED_AT,
                duty_adjustment_from_points(rise),
                exposure.shipping,
            ).summary.average_price_change_pct
            for rise in TARIFF_RISES_POINTS
        )


def test_a_market_that_sells_nothing_has_no_tariff_figures(
    catalogue: Catalogue, config: GccConfig
) -> None:
    report = build_report(only_products(catalogue, VANILLA, GUMMY_BEARS), config, REPORT_ORDERED_AT)
    by_market = {(t.code, t.shipping): t.average_change_pct for t in report.tariffs}

    assert by_market["KSA", "consolidated"] == by_market["KSA", "parcel"] == (None, None, None)
    assert all(change is not None for change in by_market["UAE", "parcel"])


@settings(max_examples=50, deadline=None)  # each example builds a whole report
@given(data=st.data())
def test_a_bigger_tariff_rise_never_lowers_the_average_change(
    catalogue: Catalogue, config: GccConfig, data: st.DataObject
) -> None:
    skus = data.draw(st.sets(st.sampled_from([p.sku for p in catalogue.products])), label="skus")
    report = build_report(only_products(catalogue, *skus), config, REPORT_ORDERED_AT)
    selling = {market.code: market.for_sale > 0 for market in report.markets}

    for exposure in report.tariffs:
        changes = exposure.average_change_pct
        if not selling[exposure.code]:
            assert changes == (None,) * len(TARIFF_RISES_POINTS)
            continue
        figures = [change for change in changes if change is not None]
        assert len(figures) == len(TARIFF_RISES_POINTS)
        assert all(change >= 0 for change in figures)
        assert figures == sorted(figures)
