"""M11: the expansion report's figures (SPEC §9.2.1 and §9.2.6), all Decimal."""

from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

from helpers import (
    FOR_SALE_COUNTS,
    GUMMY_BEARS,
    REPORT_ORDERED_AT,
    SAMPLE_PRODUCT_COUNT,
    VANILLA,
    only_products,
)
from souqsort.models import Catalogue, GccConfig
from souqsort.pipeline import LocalisationError, localise_and_summarise
from souqsort.pricing.money import round_minor
from souqsort.report import build_report
from souqsort.report.figures import ExpansionReport, MarketOverview


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
