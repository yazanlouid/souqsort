"""M11 to M13: the expansion report's figures (SPEC §9.2), all Decimal."""

from datetime import UTC, date, datetime, time
from decimal import Decimal, Inexact, localcontext

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
from souqsort.logistics.calendar import DeliveryEstimate, estimate_delivery
from souqsort.models import SHIPPING_MODELS, Catalogue, GccConfig, ShippingModel
from souqsort.pipeline import (
    MAX_DUTY_ADJUST_POINTS,
    LocalisationError,
    duty_adjustment_from_points,
    localise_and_summarise,
)
from souqsort.pricing.landed_cost import PriceQuote
from souqsort.pricing.money import round_minor
from souqsort.report import build_report, figures
from souqsort.report.figures import (
    HEADLINE_TARIFF_RISE_POINTS,
    PRICE_ENDING_ALERT,
    TARIFF_RISES_POINTS,
    ExpansionReport,
    MarketOverview,
    ProductComparison,
    SampleProduct,
    ShippingComparison,
    price_ending_added,
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
    assert report.config_version == "2026-11-01"
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


LICENCE = "DIGI-LIC-050"


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
        ("DIGI-LIC-050", "340.95", "340.95", False),  # never travels
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
        ("DIGI-LIC-050", "304.99", "304.99", False),
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
    [("KSA", (3, 7, 1, 9)), ("UAE", (5, 5, 2, 9)), ("KWT", (0, 6, 5, 0))],
)
def test_counts_of_the_parcel_table(
    report: ExpansionReport, code: str, counts: tuple[int, int, int, int]
) -> None:
    market = _shipping(report, code)

    assert (market.cheaper, market.dearer, market.unchanged, market.waived) == counts


def test_change_is_the_full_precision_ratio_of_one_item_orders(report: ExpansionReport) -> None:
    for market in report.shipping:
        for product in market.products:
            assert product.change_pct == product.parcel_order / product.consolidated_price - 1


# SPEC §9.2.2: the market's fee and when its parcels arrive, for the order of §9.5.
PARCEL_TERMS: dict[str, tuple[Decimal | None, date]] = {
    "KSA": (Decimal("15.00"), date(2026, 10, 21)),
    "UAE": (None, date(2026, 10, 20)),
    "KWT": (None, date(2026, 10, 21)),
}


@pytest.mark.parametrize("code", list(PARCEL_TERMS))
def test_each_market_s_fee_and_parcel_delivery(
    report: ExpansionReport, config: GccConfig, code: str
) -> None:
    market = _shipping(report, code)
    fee, delivered = PARCEL_TERMS[code]

    assert market.parcel_fee == fee
    assert market.parcel_delivery == estimate_delivery(
        REPORT_ORDERED_AT, config.markets[code], "parcel"
    )
    assert market.parcel_delivery.delivery_date == delivered


@pytest.mark.parametrize("code", list(PRICE_LISTS))
def test_a_parcel_order_is_the_shelf_price_plus_the_fee_when_it_travels(
    report: ExpansionReport, code: str
) -> None:
    fee = PARCEL_TERMS[code][0]
    for product in _shipping(report, code).products:
        expected = None if product.sku == LICENCE else fee
        assert product.parcel_fee == expected, product.sku
        assert product.parcel_order == product.parcel_price + (expected or 0)


def test_ksa_parcel_orders_cost_the_price_list_plus_15(report: ExpansionReport) -> None:
    orders = {p.sku: p.parcel_order for p in _shipping(report, "KSA").products}

    assert orders["ELEC-HP-001"] == Decimal("675.95")
    assert orders["ELEC-CHG-002"] == Decimal("194.95")  # dearer than 184.95 consolidated
    assert orders["BEAU-LIP-040"] == Decimal("30.95")
    assert orders[LICENCE] == Decimal("340.95")  # it never travels, so no fee


def test_a_market_that_sells_nothing_still_has_its_fee(
    catalogue: Catalogue, config: GccConfig
) -> None:
    report = build_report(only_products(catalogue, VANILLA, GUMMY_BEARS), config, REPORT_ORDERED_AT)
    ksa = _shipping(report, "KSA")

    assert ksa.products == ()
    assert ksa.parcel_fee == Decimal("15.00")
    assert ksa.parcel_delivery.delivery_date == date(2026, 10, 21)


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


def test_counts_compare_one_item_orders_not_the_rounded_change() -> None:
    # +0.04% rounds to 0.0%, but the parcel order is still dearer.
    comparison = ShippingComparison(
        code="A",
        name="A name",
        currency="XXX",
        minor_units=2,
        de_minimis=None,
        parcel_fee=Decimal("10.00"),
        parcel_delivery=DeliveryEstimate(
            ordered_at_local=REPORT_ORDERED_AT,
            dispatch_date=date(2026, 10, 15),
            delivery_date=date(2026, 10, 21),
        ),
        products=(
            ProductComparison(
                "SKU-1",
                "One",
                Decimal("2500.00"),
                Decimal("2491.00"),
                Decimal("10.00"),
                Decimal("0.05"),
                False,
            ),
        ),
    )

    # The shelf price is cheaper, but the one-item order, with the fee, is dearer.
    assert (comparison.cheaper, comparison.dearer, comparison.unchanged) == (0, 1, 0)
    assert comparison.products[0].change_pct == Decimal("0.0004")  # 2501 / 2500 - 1


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

    products = {product.sku: product for product in catalogue.products}

    with pytest.raises(ValueError, match="parcel view has ELEC-CHG-002 where ELEC-HP-001"):
        figures._shipping(market, consolidated, parcel, products, REPORT_ORDERED_AT)


# --- tariff exposure (§9.2.3) -------------------------------------------------------------

# SPEC §9.2.3: the average price change at +5, +10 and +20 pp, rounded for display.
TARIFF_CELLS: dict[tuple[str, ShippingModel], tuple[str, str, str]] = {
    ("KSA", "consolidated"): ("4.6", "9.0", "18.6"),
    ("KSA", "parcel"): ("0.9", "1.8", "3.5"),
    ("UAE", "consolidated"): ("4.9", "9.3", "19.2"),
    ("UAE", "parcel"): ("1.2", "2.4", "4.8"),
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


def test_the_headline_rise_must_be_one_of_the_rises() -> None:
    figures._require_headline_rise(10, (5, 10, 20))
    with pytest.raises(
        ValueError,
        match=r"^HEADLINE_TARIFF_RISE_POINTS \(15\) must be one of "
        r"TARIFF_RISES_POINTS \(5, 10, 20\)$",
    ):
        figures._require_headline_rise(15, (5, 10, 20))


def test_figures_do_not_depend_on_the_order_shipping_models_are_declared(
    catalogue: Catalogue,
    config: GccConfig,
    report: ExpansionReport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(figures, "SHIPPING_MODELS", ("parcel", "consolidated"))
    reordered = build_report(catalogue, config, REPORT_ORDERED_AT)

    assert reordered.markets == report.markets
    assert reordered.shipping == report.shipping
    assert sorted(reordered.tariffs, key=str) == sorted(report.tariffs, key=str)


# --- how a price is built (§9.2.4) --------------------------------------------------------

HEADPHONES = "ELEC-HP-001"
KETTLE = "HOME-KTL-030"

# Appendix A's build-up, as (freight, duty, VAT, shelf price) per shipping model, and goods.
BUILD_UPS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "KSA": ("562.46", ("5.91", "28.42", "89.52", "686.95"), ("11.81", "0.00", "86.14", "660.95")),
    "UAE": ("550.84", ("5.14", "27.80", "29.19", "612.99"), ("10.28", "0.00", "28.06", "589.99")),
    "KWT": (
        "46.047",
        ("0.537", "2.329", "0.000", "48.950"),
        ("1.075", "2.356", "0.000", "49.950"),
    ),
}


def test_the_sample_product_is_the_first_every_market_sells(report: ExpansionReport) -> None:
    assert report.sample_product == SampleProduct(
        sku=HEADPHONES, name_en="Wireless Noise-Cancelling Headphones"
    )


def test_the_sample_product_skips_products_a_market_does_not_sell(
    catalogue: Catalogue, config: GccConfig
) -> None:
    by_sku = {product.sku: product for product in catalogue.products}
    products = [by_sku[VANILLA], by_sku[GUMMY_BEARS], by_sku[KETTLE], by_sku[HEADPHONES]]
    report = build_report(
        catalogue.model_copy(update={"products": products}), config, REPORT_ORDERED_AT
    )

    assert report.sample_product is not None
    assert report.sample_product.sku == KETTLE
    assert [build_up.consolidated.sku for build_up in report.build_ups] == [KETTLE] * 3


def test_build_ups_are_in_config_order_with_their_currency(
    report: ExpansionReport, config: GccConfig
) -> None:
    assert [(b.code, b.currency, b.minor_units) for b in report.build_ups] == [
        (market.code, market.currency.code, market.currency.minor_units)
        for market in config.markets.values()
    ]


@pytest.mark.parametrize("code", list(BUILD_UPS))
def test_the_six_columns_of_the_build_up(report: ExpansionReport, code: str) -> None:
    build_up = next(b for b in report.build_ups if b.code == code)
    goods, consolidated, parcel = BUILD_UPS[code]

    for quote, expected in ((build_up.consolidated, consolidated), (build_up.parcel, parcel)):
        shown = tuple(
            round_minor(amount, build_up.minor_units)
            for amount in (quote.freight, quote.duty, quote.vat, quote.shelf_price)
        )
        assert round_minor(quote.goods, build_up.minor_units) == Decimal(goods)
        assert shown == tuple(Decimal(amount) for amount in expected)
    assert build_up.consolidated.shipping == "consolidated"
    assert build_up.parcel.shipping == "parcel"


def test_only_ksa_s_build_up_pays_a_fee(report: ExpansionReport) -> None:
    assert [(b.code, b.parcel_fee) for b in report.build_ups] == [
        ("KSA", Decimal("15.00")),
        ("UAE", None),
        ("KWT", None),
    ]
    assert [b.parcel_order for b in report.build_ups] == [
        Decimal("675.95"),
        Decimal("589.99"),
        Decimal("49.950"),
    ]


def test_a_sample_product_that_does_not_travel_pays_no_fee(
    catalogue: Catalogue, config: GccConfig
) -> None:
    report = build_report(only_products(catalogue, LICENCE), config, REPORT_ORDERED_AT)

    assert [(b.consolidated.sku, b.parcel_fee) for b in report.build_ups] == [(LICENCE, None)] * 3
    assert [b.parcel_order for b in report.build_ups] == [
        b.parcel.shelf_price for b in report.build_ups
    ]


def test_duty_is_waived_on_the_sample_parcels_in_ksa_and_uae(report: ExpansionReport) -> None:
    assert {
        (b.code, b.consolidated.duty_waived, b.parcel.duty_waived) for b in report.build_ups
    } == {
        ("KSA", False, True),
        ("UAE", False, True),
        ("KWT", False, False),
    }


def test_build_ups_come_from_localise_and_summarise(
    report: ExpansionReport, catalogue: Catalogue, config: GccConfig
) -> None:
    for build_up in report.build_ups:
        for model, quote in (("consolidated", build_up.consolidated), ("parcel", build_up.parcel)):
            localised = localise_and_summarise(
                catalogue.products, config, build_up.code, REPORT_ORDERED_AT, Decimal("0"), model
            )
            assert quote == next(i.quote for i in localised.items if i.sku == HEADPHONES)


@pytest.mark.parametrize(
    "skus",
    [(VANILLA,), (VANILLA, GUMMY_BEARS), (GUMMY_BEARS,), ()],
    ids=["only-uae-sells-it", "a-market-sells-nothing", "none-sells-anything", "empty"],
)
def test_no_product_sold_everywhere_gives_no_build_up(
    catalogue: Catalogue, config: GccConfig, skus: tuple[str, ...]
) -> None:
    report = build_report(only_products(catalogue, *skus), config, REPORT_ORDERED_AT)

    assert report.sample_product is None
    assert report.build_ups == ()


def test_build_ups_are_the_same_whatever_order_shipping_models_are_declared(
    catalogue: Catalogue,
    config: GccConfig,
    report: ExpansionReport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(figures, "SHIPPING_MODELS", ("parcel", "consolidated"))
    reordered = build_report(catalogue, config, REPORT_ORDERED_AT)

    assert reordered.sample_product == report.sample_product
    assert reordered.build_ups == report.build_ups


# --- pricing risks (§9.2.5) ---------------------------------------------------------------

LIP_BALM = "BEAU-LIP-040"
TEA = "GROC-TEA-060"


def _quote(gross: str, shelf_price: str) -> PriceQuote:
    """A hand-built consolidated quote; only the gross and the shelf price matter here."""
    return PriceQuote(
        sku="SKU-1",
        market="A",
        currency="XXX",
        goods=Decimal(gross),
        freight=Decimal(0),
        cif=Decimal(gross),
        duty=Decimal(0),
        vat=Decimal(0),
        gross=Decimal(gross),
        shelf_price=Decimal(shelf_price),
        margin_pct=Decimal("0.5"),
        shipping="consolidated",
        duty_rate=Decimal("0.05"),
        duty_waived=False,
    )


def test_the_alert_is_ten_percent() -> None:
    assert Decimal("0.10") == PRICE_ENDING_ALERT


@pytest.mark.parametrize(
    ("shelf_price", "added", "risk"),
    [("1.00", "0", False), ("1.10", "0.10", False), ("1.11", "0.11", True)],
    ids=["nothing-added", "exactly-the-alert", "above-the-alert"],
)
def test_price_ending_added(shelf_price: str, added: str, risk: bool) -> None:
    quote = _quote("1.00", shelf_price)

    assert price_ending_added(quote) == Decimal(added)
    assert figures._adds_more_than_the_alert(quote) is risk


# 0.999...9 with 28 nines: shelf / gross rounds to exactly 1.1 at 28 digits, although the
# share added is 0.10000000000000000000000000011, above the alert.
JUST_BELOW_ONE = "0." + "9" * 28
LONG_GROSS = "1.234567890123456789012345678901234567890"  # 40 digits
LONG_AT_ALERT = "1.35802467913580246791358024679135802467900"  # LONG_GROSS * 1.10, exactly


@pytest.mark.parametrize(
    ("gross", "shelf_price", "risk"),
    [
        (JUST_BELOW_ONE, "1.10", True),
        ("1." + "0" * 27 + "1", "1.10", False),
        (LONG_GROSS, LONG_AT_ALERT, False),
        (LONG_GROSS, LONG_AT_ALERT + "1", True),
        ("3", "3.30", False),
        ("3", "3.300000000000000000000000000000001", True),
    ],
    ids=[
        "just-below-one",
        "just-above-one",
        "long-exactly-the-alert",
        "long-just-above",
        "exactly",
        "far-digit-above",
    ],
)
def test_the_alert_is_compared_exactly(gross: str, shelf_price: str, risk: bool) -> None:
    assert figures._adds_more_than_the_alert(_quote(gross, shelf_price)) is risk


def test_the_division_alone_would_miss_the_boundary() -> None:
    quote = _quote(JUST_BELOW_ONE, "1.10")

    assert price_ending_added(quote) == PRICE_ENDING_ALERT  # rounded onto the boundary
    assert figures._adds_more_than_the_alert(quote)


def test_the_comparison_ignores_the_caller_s_precision() -> None:
    with localcontext() as ctx:
        ctx.prec = 3
        assert figures._adds_more_than_the_alert(_quote(JUST_BELOW_ONE, "1.10"))
        assert not figures._adds_more_than_the_alert(_quote(LONG_GROSS, LONG_AT_ALERT))


def test_an_alert_that_cannot_be_added_to_one_exactly_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(figures, "PRICE_ENDING_ALERT", Decimal("0." + "3" * 30))

    with pytest.raises(Inexact):
        figures._adds_more_than_the_alert(_quote("1.00", "1.50"))


def test_price_ending_added_keeps_full_precision() -> None:
    assert price_ending_added(_quote("3", "4")) == Decimal(4) / Decimal(3) - 1


def test_the_two_pricing_risks_of_the_sample_data(report: ExpansionReport) -> None:
    shown = [
        (
            risk.code,
            risk.sku,
            risk.name_en,
            risk.minor_units,
            round_minor(risk.gross, risk.minor_units),
            risk.shelf_price,
            _percent(risk.added_pct),
        )
        for risk in report.pricing_risks
    ]

    assert shown == [
        ("KWT", LIP_BALM, "Lip Balm", 3, Decimal("1.157"), Decimal("1.950"), Decimal("68.5")),
        (
            "KWT",
            TEA,
            "English Breakfast Tea, 80 bags",
            3,
            Decimal("2.458"),
            Decimal("2.950"),
            Decimal("20.0"),
        ),
    ]


def test_pricing_risks_come_from_consolidated_quotes(
    report: ExpansionReport, catalogue: Catalogue, config: GccConfig
) -> None:
    expected = []
    for code in config.markets:
        localised = localise_and_summarise(
            catalogue.products, config, code, REPORT_ORDERED_AT, Decimal("0"), "consolidated"
        )
        for item in localised.items:
            if figures._adds_more_than_the_alert(item.quote):
                quote = item.quote
                added = price_ending_added(quote)
                expected.append((code, item.sku, quote.gross, quote.shelf_price, added))

    assert [(r.code, r.sku, r.gross, r.shelf_price, r.added_pct) for r in report.pricing_risks] == (
        expected
    )


def test_pricing_risks_are_in_market_then_catalogue_order(
    catalogue: Catalogue, config: GccConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(figures, "PRICE_ENDING_ALERT", Decimal("0.04"))
    risks = build_report(catalogue, config, REPORT_ORDERED_AT).pricing_risks
    markets = list(config.markets)
    skus = [product.sku for product in catalogue.products]

    assert [r.code for r in risks] == sorted((r.code for r in risks), key=markets.index)
    for code in markets:
        in_market = [r.sku for r in risks if r.code == code]
        assert in_market == sorted(in_market, key=skus.index)
    assert {(r.code, r.sku) for r in risks} == {
        ("KSA", LIP_BALM),
        ("KWT", "ELEC-CHG-002"),
        ("KWT", "HOME-KTL-030"),
        ("KWT", LIP_BALM),
        ("KWT", TEA),
    }


def test_no_risks_without_a_price_ending_that_adds_more_than_the_alert(
    catalogue: Catalogue, config: GccConfig
) -> None:
    report = build_report(only_products(catalogue, HEADPHONES), config, REPORT_ORDERED_AT)

    assert report.pricing_risks == ()


def test_a_build_up_names_a_view_missing_the_sample_product(
    catalogue: Catalogue, config: GccConfig
) -> None:
    ksa = config.markets["KSA"]
    views = figures._MarketViews(
        market=ksa,
        consolidated=localise_and_summarise(
            catalogue.products, config, ksa.code, REPORT_ORDERED_AT, Decimal("0"), "consolidated"
        ),
        parcel=localise_and_summarise(
            [p for p in catalogue.products if p.sku != HEADPHONES],
            config,
            ksa.code,
            REPORT_ORDERED_AT,
            Decimal("0"),
            "parcel",
        ),
    )

    with pytest.raises(ValueError, match=r"^KSA: the parcel view has no ELEC-HP-001$"):
        figures._build_up(views, next(p for p in catalogue.products if p.sku == HEADPHONES))
