"""M11 to M13: the report's text (SPEC §9.3 and §9.4): formatting, sentences, the template."""

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, get_args

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from helpers import (
    FOR_SALE_COUNTS,
    GUMMY_BEARS,
    REPORT_ORDERED_AT,
    VANILLA,
    only_products,
    without_products,
)
from souqsort.compliance import ExcludedProduct
from souqsort.logistics.calendar import DeliveryEstimate
from souqsort.models import (
    AttributeName,
    Catalogue,
    DeMinimisApplies,
    DeMinimisRule,
    GccConfig,
    ShippingModel,
)
from souqsort.pipeline import LocalisationError, localise_and_summarise
from souqsort.pricing.landed_cost import PriceQuote
from souqsort.pricing.money import charm_up, round_minor
from souqsort.report import build_report, render_report
from souqsort.report.figures import (
    TARIFF_RISES_POINTS,
    ExpansionReport,
    MarketOverview,
    PriceBuildUp,
    ProductComparison,
    SampleProduct,
    ShippingComparison,
    TariffExposure,
)
from souqsort.report.text import (
    build_up_column,
    build_up_sentences,
    clock_text,
    count_text,
    date_text,
    de_minimis_sentence,
    join_clauses,
    join_list,
    local_time_text,
    markets_sentences,
    money_text,
    not_sold_sentence,
    one_line,
    percent_text,
    report_context,
    shipping_market_sentences,
    shipping_sentence,
    signed_percent_text,
    table_cell,
    tariff_sentence,
)

# SPEC Appendix A, exactly: the parts of the sample report that M11 builds.
HEADER = """\
# GCC expansion report

An order placed on Thu 2026-10-15 at 09:00 UTC, priced in every market in the config with both shipping models. Built from market config 2026-10-01, FX rates as of 2026-10-01 and catalogue 2026-10-01.

> All market data is illustrative. Do not use it to quote real prices or delivery dates.

"""  # noqa: E501

MARKETS_SECTION = """\
## Markets side by side

On average, shelf prices sit 24.7% above the catalogue price in UAE, 33.1% in KWT and 41.2% in KSA. For this order, delivery is on Thu 2026-10-22 in KSA, Wed 2026-10-21 in UAE and Thu 2026-10-22 in KWT.

| Market | Currency | VAT | For sale | Not sold | Above catalogue price | Average margin | Ordered (local time) | Cut-off | Delivered |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| KSA (Saudi Arabia) | SAR | 15.0% | 11 | 2 | +41.2% | 64.6% | Thu 2026-10-15 12:00 | 14:00 | Thu 2026-10-22 |
| UAE (United Arab Emirates) | AED | 5.0% | 12 | 1 | +24.7% | 64.9% | Thu 2026-10-15 13:00 | 15:00 | Wed 2026-10-21 |
| KWT (Kuwait) | KWD | 0.0% | 11 | 2 | +33.1% | 66.6% | Thu 2026-10-15 12:00 | 13:00 | Thu 2026-10-22 |

"""  # noqa: E501

SHIPPING_SECTION = """\
## Consolidated or parcel

Direct parcels are cheaper than consolidated imports for 6 of 11 products in KSA, 5 of 12 in UAE and 0 of 11 in KWT.

### KSA (Saudi Arabia)

No duty on a parcel whose CIF is below 1,000.00 SAR. Parcels are cheaper for 6 of 11 products, dearer for 4 and unchanged for 1. Duty is waived on 10 of them.

| SKU | Product | Consolidated (SAR) | Direct parcel (SAR) | Change | Parcel duty |
|---|---|---:|---:|---:|---|
| ELEC-HP-001 | Wireless Noise-Cancelling Headphones | 686.95 | 660.95 | -3.8% | waived |
| ELEC-CHG-002 | 65W USB-C Charger | 184.95 | 179.95 | -2.7% | waived |
| FASH-BAG-014 | Leather Crossbody Bag | 594.95 | 546.95 | -8.1% | waived |
| FASH-SCF-015 | Silk Scarf | 293.95 | 264.95 | -9.9% | waived |
| SPRT-KTB-020 | Cast Iron Kettlebell 16 kg | 593.95 | 875.95 | +47.5% | waived |
| HOME-KTL-030 | Electric Kettle 1.7 L | 237.95 | 249.95 | +5.0% | waived |
| HOME-ESP-031 | Bean-to-Cup Espresso Machine | 4,144.95 | 4,344.95 | +4.8% | 5.0% |
| BEAU-LIP-040 | Lip Balm | 16.95 | 15.95 | -5.9% | waived |
| BEAU-SRM-041 | Vitamin C Serum 30 ml | 111.95 | 108.95 | -2.7% | waived |
| DIGI-LIC-050 | Photo Editor Pro Licence (digital download) | 340.95 | 340.95 | 0.0% | waived |
| GROC-TEA-060 | English Breakfast Tea, 80 bags | 34.95 | 37.95 | +8.6% | waived |

### UAE (United Arab Emirates)

No duty on a parcel whose CIF is at or below 1,000.00 AED, except products containing alcohol. Parcels are cheaper for 5 of 12 products, dearer for 5 and unchanged for 2. Duty is waived on 10 of them.

| SKU | Product | Consolidated (AED) | Direct parcel (AED) | Change | Parcel duty |
|---|---|---:|---:|---:|---|
| ELEC-HP-001 | Wireless Noise-Cancelling Headphones | 612.99 | 589.99 | -3.8% | waived |
| ELEC-CHG-002 | 65W USB-C Charger | 164.99 | 159.99 | -3.0% | waived |
| FASH-BAG-014 | Leather Crossbody Bag | 496.99 | 485.99 | -2.2% | waived |
| FASH-SCF-015 | Silk Scarf | 246.99 | 236.99 | -4.0% | waived |
| SPRT-KTB-020 | Cast Iron Kettlebell 16 kg | 498.99 | 721.99 | +44.7% | waived |
| HOME-KTL-030 | Electric Kettle 1.7 L | 209.99 | 218.99 | +4.3% | waived |
| HOME-ESP-031 | Bean-to-Cup Espresso Machine | 3,685.99 | 3,844.99 | +4.3% | 5.0% |
| BEAU-LIP-040 | Lip Balm | 14.99 | 14.99 | 0.0% | waived |
| BEAU-SRM-041 | Vitamin C Serum 30 ml | 99.99 | 96.99 | -3.0% | waived |
| DIGI-LIC-050 | Photo Editor Pro Licence (digital download) | 304.99 | 304.99 | 0.0% | waived |
| GROC-TEA-060 | English Breakfast Tea, 80 bags | 29.99 | 32.99 | +10.0% | waived |
| GROC-VAN-061 | Pure Vanilla Extract | 55.99 | 57.99 | +3.6% | 5.0% |

### KWT (Kuwait)

No de minimis rule, so every parcel pays duty. Parcels are cheaper for 0 of 11 products, dearer for 6 and unchanged for 5.

| SKU | Product | Consolidated (KWD) | Direct parcel (KWD) | Change | Parcel duty |
|---|---|---:|---:|---:|---|
| ELEC-HP-001 | Wireless Noise-Cancelling Headphones | 48.950 | 49.950 | +2.0% | 5.0% |
| ELEC-CHG-002 | 65W USB-C Charger | 13.950 | 13.950 | 0.0% | 5.0% |
| FASH-BAG-014 | Leather Crossbody Bag | 39.950 | 41.950 | +5.0% | 5.0% |
| FASH-SCF-015 | Silk Scarf | 19.950 | 19.950 | 0.0% | 5.0% |
| SPRT-KTB-020 | Cast Iron Kettlebell 16 kg | 44.950 | 70.950 | +57.8% | 5.0% |
| HOME-KTL-030 | Electric Kettle 1.7 L | 17.950 | 19.950 | +11.1% | 5.0% |
| HOME-ESP-031 | Bean-to-Cup Espresso Machine | 296.950 | 312.950 | +5.4% | 5.0% |
| BEAU-LIP-040 | Lip Balm | 1.950 | 1.950 | 0.0% | 5.0% |
| BEAU-SRM-041 | Vitamin C Serum 30 ml | 7.950 | 8.950 | +12.6% | 5.0% |
| DIGI-LIC-050 | Photo Editor Pro Licence (digital download) | 24.950 | 24.950 | 0.0% | 0.0% |
| GROC-TEA-060 | English Breakfast Tea, 80 bags | 2.950 | 2.950 | 0.0% | 5.0% |

"""  # noqa: E501

TARIFF_SECTION = """\
## Tariff exposure

A 10 pp tariff rise lifts average prices by 9.0% for consolidated imports and 0.9% for direct parcels in KSA; 9.3% and 1.5% in UAE; and 7.6% and 9.4% in KWT.

| Market | Shipping model | +5 pp | +10 pp | +20 pp |
|---|---|---:|---:|---:|
| KSA | Consolidated import | +4.6% | +9.0% | +18.6% |
| KSA | Direct parcel | +0.4% | +0.9% | +1.7% |
| UAE | Consolidated import | +4.9% | +9.3% | +19.2% |
| UAE | Direct parcel | +0.8% | +1.5% | +3.2% |
| KWT | Consolidated import | +3.8% | +7.6% | +16.0% |
| KWT | Direct parcel | +6.3% | +9.4% | +17.7% |

"""  # noqa: E501

NOT_SOLD_SECTION = """\
## Not sold

Out of 13 products, KSA cannot sell 2, UAE 1 and KWT 2.

| Market | SKU | Product | Reasons |
|---|---|---|---|
| KSA | GROC-VAN-061 | Pure Vanilla Extract | Contains alcohol |
| KSA | GROC-GUM-062 | Gummy Bears (pork gelatine) | Contains pork |
| UAE | GROC-GUM-062 | Gummy Bears (pork gelatine) | Contains pork |
| KWT | GROC-VAN-061 | Pure Vanilla Extract | Contains alcohol |
| KWT | GROC-GUM-062 | Gummy Bears (pork gelatine) | Contains pork |

"""

METHOD_SECTION = """\
## How these figures are made

- Each product is priced as a one-item order, and every cost is passed on to the customer.
- Prices use today's duty rates. A tariff rise adds percentage points to every duty rate.
- Above catalogue price compares the shelf price with the catalogue price converted at the config's FX rates, so it includes freight, duty, VAT and the price ending.
- Averages are unweighted means over the products a market sells.
- Price components are rounded for display, and the rounding line makes each column add up to the shelf price, which is exact.
- Markets side by side and pricing risks use consolidated imports, the default shipping model.
- Delivery dates are the same for both shipping models.
"""  # noqa: E501

PRICE_SENTENCE = (
    "On average, shelf prices sit 24.7% above the catalogue price in UAE, 33.1% in KWT "
    "and 41.2% in KSA."
)
DELIVERY_SENTENCE = (
    "For this order, delivery is on Thu 2026-10-22 in KSA, Wed 2026-10-21 in UAE "
    "and Thu 2026-10-22 in KWT."
)
NOT_SOLD_SENTENCE = "Out of 13 products, KSA cannot sell 2, UAE 1 and KWT 2."


@pytest.fixture(scope="module")
def report(catalogue: Catalogue, config: GccConfig) -> ExpansionReport:
    return build_report(catalogue, config, REPORT_ORDERED_AT)


@pytest.fixture(scope="module")
def rendered(report: ExpansionReport) -> str:
    return render_report(report)


def _section(text: str, heading: str) -> str:
    """From ``## heading`` up to the next ``## `` heading, or to the end."""
    start = text.index(f"## {heading}\n")
    end = text.find("\n## ", start)
    return text[start:] if end == -1 else text[start : end + 1]


def _overview(
    code: str,
    *,
    above: str | None = "0.25",
    delivered: date = date(2026, 10, 22),
    not_sold: int = 0,
) -> MarketOverview:
    """A hand-built market for sentence tests; ``above=None`` sells nothing."""
    excluded = tuple(
        ExcludedProduct(f"SKU-{n}", f"Product {n}", ("contains_pork",)) for n in range(not_sold)
    )
    return MarketOverview(
        code=code,
        name=f"{code} name",
        currency="XXX",
        vat_rate=Decimal("0.05"),
        for_sale=0 if above is None else 1,
        not_sold=excluded,
        average_margin_pct=None if above is None else Decimal("0.5"),
        average_above_catalogue_pct=None if above is None else Decimal(above),
        cutoff=time(14, 0),
        delivery=DeliveryEstimate(
            ordered_at_local=datetime(2026, 10, 15, 12, 0, tzinfo=UTC),
            dispatch_date=date(2026, 10, 15),
            delivery_date=delivered,
        ),
    )


# --- formatting (§9.3.1) ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "minor_units", "expected"),
    [
        ("4144.95", 2, "4,144.95"),
        ("312.95", 3, "312.950"),
        ("1234567.891", 3, "1,234,567.891"),
        ("999.995", 2, "1,000.00"),  # half up, then grouped
        ("16.95", 2, "16.95"),
        ("0", 2, "0.00"),
    ],
)
def test_money_has_minor_units_and_thousands_separators(
    amount: str, minor_units: int, expected: str
) -> None:
    assert money_text(Decimal(amount), minor_units, figure="price") == expected


@pytest.mark.parametrize(
    ("fraction", "expected"),
    [
        ("0.4124", "+41.2%"),
        ("0.41249", "+41.2%"),
        ("0.41250", "+41.3%"),  # half up
        ("-0.038", "-3.8%"),
        ("0", "0.0%"),
        ("-0.00049", "0.0%"),  # never -0.0%
        ("0.00049", "0.0%"),  # never +0.0%
        ("0.0005", "+0.1%"),
    ],
)
def test_signed_percent(fraction: str, expected: str) -> None:
    assert signed_percent_text(Decimal(fraction), figure="change") == expected


@pytest.mark.parametrize(
    ("fraction", "expected"),
    [("0.15", "15.0%"), ("0.05", "5.0%"), ("0", "0.0%"), ("0.6455", "64.6%"), ("-0.0004", "0.0%")],
)
def test_rates_and_margins_have_no_sign(fraction: str, expected: str) -> None:
    assert percent_text(Decimal(fraction), figure="rate") == expected


@pytest.mark.parametrize(
    "show",
    [
        lambda value: money_text(value, 2, figure="KSA: average margin"),
        lambda value: percent_text(value, figure="KSA: average margin"),
        lambda value: signed_percent_text(value, figure="KSA: average margin"),
    ],
    ids=["money", "percent", "signed-percent"],
)
@pytest.mark.parametrize("value", ["1E+27", "-1E+27", "1E+999999"], ids=["big", "negative", "huge"])
def test_a_figure_too_large_to_display_is_named(show: Callable[[Decimal], str], value: str) -> None:
    with pytest.raises(LocalisationError, match=r"^KSA: average margin is too large to display$"):
        show(Decimal(value))


def test_dates_and_times() -> None:
    riyadh = timezone(timedelta(hours=3))

    assert date_text(date(2026, 10, 22)) == "Thu 2026-10-22"
    assert date_text(date(2026, 10, 21)) == "Wed 2026-10-21"
    assert local_time_text(datetime(2026, 10, 15, 12, 0, tzinfo=riyadh)) == "Thu 2026-10-15 12:00"
    assert clock_text(time(14, 0)) == "14:00"


def test_every_weekday_has_its_english_name() -> None:
    monday = date(2026, 10, 12)
    names = [date_text(monday + timedelta(days=n))[:3] for n in range(7)]

    assert names == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        (["KSA"], "KSA"),
        (["KSA", "UAE"], "KSA and UAE"),
        (["KSA", "UAE", "KWT"], "KSA, UAE and KWT"),
    ],
)
def test_lists_join_with_commas_and_a_final_and(items: list[str], expected: str) -> None:
    assert join_list(items) == expected


def test_an_empty_list_cannot_be_joined() -> None:
    with pytest.raises(ValueError, match="nothing to join"):
        join_list([])


@pytest.mark.parametrize(
    ("count", "expected"), [(0, "0 products"), (1, "1 product"), (2, "2 products")]
)
def test_counts(count: int, expected: str) -> None:
    assert count_text(count, "product") == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Lip Balm", "Lip Balm"),
        ("Tea | Coffee", "Tea \\| Coffee"),
        ("Two\nlines", "Two lines"),
        ("Two\r\nlines", "Two lines"),
        ("Two\rlines", "Two lines"),
        ("a|b\nc", "a\\|b c"),
    ],
)
def test_table_cells_escape_pipes_and_line_breaks(text: str, expected: str) -> None:
    assert table_cell(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-01", "2026-10-01"),
        ("2026-10-01\nrev2", "2026-10-01 rev2"),
        ("a\r\nb\rc", "a b c"),
        ("a|b", "a|b"),  # only a table cell escapes |
    ],
)
def test_one_line_turns_line_breaks_into_spaces(text: str, expected: str) -> None:
    assert one_line(text) == expected


# --- sentences (§9.3.2 items 1 and 6) -----------------------------------------------------


def test_markets_sentences_for_the_sample_data(report: ExpansionReport) -> None:
    assert markets_sentences(report.markets) == [PRICE_SENTENCE, DELIVERY_SENTENCE]


def test_price_sentence_lists_the_lowest_first() -> None:
    markets = [
        _overview("A", above="0.3"),
        _overview("B", above="0.1"),
        _overview("C", above="0.2"),
    ]

    price, _ = markets_sentences(markets)

    assert price == (
        "On average, shelf prices sit 10.0% above the catalogue price in B, 20.0% in C "
        "and 30.0% in A."
    )


def test_price_sentence_compares_full_precision_averages() -> None:
    # Both show 24.7%: the order follows the averages themselves, not config order.
    markets = [_overview("A", above="0.2471"), _overview("B", above="0.2469")]

    price, _ = markets_sentences(markets)

    assert (
        price == "On average, shelf prices sit 24.7% above the catalogue price in B and 24.7% in A."
    )


def test_price_sentence_keeps_config_order_for_exact_ties() -> None:
    markets = [_overview("A", above="0.25"), _overview("B", above="0.25")]

    price, _ = markets_sentences(markets)

    assert (
        price == "On average, shelf prices sit 25.0% above the catalogue price in A and 25.0% in B."
    )


def test_price_sentence_leaves_out_a_market_that_sells_nothing() -> None:
    markets = [_overview("A", above=None), _overview("B", above="0.2")]

    price, delivery = markets_sentences(markets)

    assert price == "On average, shelf prices sit 20.0% above the catalogue price in B."
    assert delivery == "For this order, delivery is on Thu 2026-10-22 in A and Thu 2026-10-22 in B."


def test_price_sentence_when_no_market_sells_anything() -> None:
    markets = [_overview("A", above=None), _overview("B", above=None)]

    price, delivery = markets_sentences(markets)

    assert price == "No market has products for sale."
    assert delivery == "For this order, delivery is on Thu 2026-10-22 in A and Thu 2026-10-22 in B."


def test_delivery_sentence_lists_every_market_in_config_order() -> None:
    markets = [
        _overview("A", delivered=date(2026, 10, 22)),
        _overview("B", delivered=date(2026, 10, 21)),
    ]

    _, delivery = markets_sentences(markets)

    assert delivery == "For this order, delivery is on Thu 2026-10-22 in A and Wed 2026-10-21 in B."


def test_not_sold_sentence_for_the_sample_data(report: ExpansionReport) -> None:
    assert not_sold_sentence(report.product_count, report.markets) == NOT_SOLD_SENTENCE


def test_not_sold_sentence_includes_a_market_that_sells_everything() -> None:
    markets = [_overview("A", not_sold=2), _overview("B"), _overview("C", not_sold=1)]

    assert not_sold_sentence(5, markets) == "Out of 5 products, A cannot sell 2, B 0 and C 1."


def test_not_sold_sentence_counts_one_product() -> None:
    assert (
        not_sold_sentence(1, [_overview("A", not_sold=1)]) == "Out of 1 product, A cannot sell 1."
    )


def test_not_sold_sentence_when_nothing_is_excluded() -> None:
    markets = [_overview("A"), _overview("B")]

    assert not_sold_sentence(13, markets) == "Every market can sell every product."


# --- the template context (§9.4.1) --------------------------------------------------------


def _non_strings(value: object, path: str = "context") -> list[str]:
    """Where the context holds anything but strings, lists and dicts with string keys."""
    if isinstance(value, str):
        return []
    if isinstance(value, list):
        return [bad for n, item in enumerate(value) for bad in _non_strings(item, f"{path}[{n}]")]
    if isinstance(value, dict):
        found = [f"{path}: key {key!r}" for key in value if not isinstance(key, str)]
        return found + [
            bad for k, item in value.items() for bad in _non_strings(item, f"{path}.{k}")
        ]
    return [f"{path}: {type(value).__name__} {value!r}"]


def test_context_walk_finds_what_is_not_a_string() -> None:
    sample = {"ok": ["a", {"b": "c"}], "n": Decimal("1.5"), "t": ("x",), 3: "y"}

    assert _non_strings(sample) == [
        "context: key 3",
        "context.n: Decimal Decimal('1.5')",
        "context.t: tuple ('x',)",
    ]


@pytest.mark.parametrize(
    "skus",
    [None, (VANILLA, GUMMY_BEARS), (GUMMY_BEARS,), ()],
    ids=["sample", "a-market-sells-nothing", "none-sells-anything", "empty"],
)
def test_context_holds_only_strings(
    catalogue: Catalogue, config: GccConfig, skus: Sequence[str] | None
) -> None:
    products = catalogue if skus is None else only_products(catalogue, *skus)
    context = report_context(build_report(products, config, REPORT_ORDERED_AT))

    assert _non_strings(context) == []


# --- the rendered report (§9.4) -----------------------------------------------------------


def test_header_is_appendix_a(rendered: str) -> None:
    assert rendered.startswith(HEADER)


def test_summary_lists_the_sentences_built_so_far(rendered: str) -> None:
    assert _section(rendered, "Summary") == (
        f"## Summary\n\n- {PRICE_SENTENCE}\n- {DELIVERY_SENTENCE}\n- {SHIPPING_SENTENCE}\n"
        f"- {TARIFF_SENTENCE}\n- {' '.join(BUILD_UP_SENTENCES)}\n"
        f"- {NOT_SOLD_SENTENCE}\n\n"
    )


def test_markets_side_by_side_is_appendix_a(rendered: str) -> None:
    assert _section(rendered, "Markets side by side") == MARKETS_SECTION


def test_not_sold_is_appendix_a(rendered: str) -> None:
    assert _section(rendered, "Not sold") == NOT_SOLD_SECTION


def test_method_notes_are_appendix_a(rendered: str) -> None:
    assert rendered.endswith(METHOD_SECTION)


def test_sections_are_in_order(rendered: str) -> None:
    headings = [line for line in rendered.splitlines() if line.startswith("#")]

    assert headings == [
        "# GCC expansion report",
        "## Summary",
        "## Markets side by side",
        "## Consolidated or parcel",
        "### KSA (Saudi Arabia)",
        "### UAE (United Arab Emirates)",
        "### KWT (Kuwait)",
        "## Tariff exposure",
        "## How a price is built",
        "### KSA (SAR)",
        "### UAE (AED)",
        "### KWT (KWD)",
        "## Not sold",
        "## How these figures are made",
    ]


@pytest.mark.parametrize(
    "skus",
    [None, (VANILLA, GUMMY_BEARS), (GUMMY_BEARS,), ()],
    ids=["sample", "a-market-sells-nothing", "none-sells-anything", "empty"],
)
def test_layout_rules(catalogue: Catalogue, config: GccConfig, skus: Sequence[str] | None) -> None:
    products = catalogue if skus is None else only_products(catalogue, *skus)
    text = render_report(build_report(products, config, REPORT_ORDERED_AT))

    assert "\r" not in text
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert "\n\n\n" not in text
    assert [line for line in text.splitlines() if line != line.rstrip()] == []


def test_a_market_that_sells_nothing_shows_dashes(catalogue: Catalogue, config: GccConfig) -> None:
    report = build_report(only_products(catalogue, VANILLA, GUMMY_BEARS), config, REPORT_ORDERED_AT)
    section = _section(render_report(report), "Markets side by side")

    assert (
        "| KSA (Saudi Arabia) | SAR | 15.0% | 0 | 2 | - | - | Thu 2026-10-15 12:00 | 14:00 "
        "| Thu 2026-10-22 |"
    ) in section
    assert "above the catalogue price in UAE." in section


def test_no_market_selling_anything(catalogue: Catalogue, config: GccConfig) -> None:
    report = build_report(only_products(catalogue, GUMMY_BEARS), config, REPORT_ORDERED_AT)
    text = render_report(report)

    assert _section(text, "Markets side by side").startswith(
        f"## Markets side by side\n\nNo market has products for sale. {DELIVERY_SENTENCE}\n\n"
    )
    assert "- No market has products for sale.\n" in _section(text, "Summary")


def test_nothing_excluded_anywhere_has_no_not_sold_table(
    catalogue: Catalogue, config: GccConfig
) -> None:
    report = build_report(
        without_products(catalogue, VANILLA, GUMMY_BEARS), config, REPORT_ORDERED_AT
    )

    assert _section(render_report(report), "Not sold") == (
        "## Not sold\n\nEvery market can sell every product.\n\n"
    )


def test_cells_from_the_data_are_escaped(catalogue: Catalogue, config: GccConfig) -> None:
    gummy = next(p for p in catalogue.products if p.sku == GUMMY_BEARS)
    odd = gummy.model_copy(
        update={"name": gummy.name.model_copy(update={"en": "Gummy | Bears\nXL"})}
    )
    report = build_report(
        catalogue.model_copy(update={"products": [odd]}), config, REPORT_ORDERED_AT
    )

    assert "| KSA | GROC-GUM-062 | Gummy \\| Bears XL | Contains pork |\n" in render_report(report)


def test_the_report_is_the_same_for_the_same_instant(
    catalogue: Catalogue, config: GccConfig, rendered: str
) -> None:
    same_instant = REPORT_ORDERED_AT.astimezone(timezone(timedelta(hours=3)))

    assert render_report(build_report(catalogue, config, same_instant)) == rendered


# --- data that would break the text ------------------------------------------------------


def test_a_figure_too_large_to_display_fails_naming_the_market_and_figure(
    raw_catalogue: dict[str, Any], config: GccConfig
) -> None:
    # Tiny catalogue prices put shelf prices about 1E+26 times above them: the average is
    # computed in full, but has too many digits to round to one decimal for display.
    for product in raw_catalogue["products"]:
        product["base_price"] = product["unit_cost"] = "1E-26"
    report = build_report(Catalogue.model_validate(raw_catalogue), config, REPORT_ORDERED_AT)

    with pytest.raises(
        LocalisationError, match=r"^[A-Z]+: average above catalogue price is too large to display$"
    ):
        render_report(report)


def test_line_breaks_in_the_data_versions_stay_on_one_line(
    catalogue: Catalogue, config: GccConfig
) -> None:
    report = build_report(
        catalogue.model_copy(update={"catalogue_version": "2026-10-01\r\nb"}),
        config.model_copy(update={"config_version": "2026-10-01\nrev2"}),
        REPORT_ORDERED_AT,
    )
    text = render_report(report)

    assert (
        "Built from market config 2026-10-01 rev2, FX rates as of 2026-10-01 "
        "and catalogue 2026-10-01 b.\n"
    ) in text
    assert "\n\n\n" not in text


def test_line_breaks_in_a_market_code_stay_on_one_line() -> None:
    markets = [_overview("A\nB", above="0.1", not_sold=1), _overview("C", above="0.2")]

    assert markets_sentences(markets) == [
        "On average, shelf prices sit 10.0% above the catalogue price in A B and 20.0% in C.",
        "For this order, delivery is on Thu 2026-10-22 in A B and Thu 2026-10-22 in C.",
    ]
    assert not_sold_sentence(2, markets) == "Out of 2 products, A B cannot sell 1 and C 0."


# --- consolidated or parcel (§9.3.2 item 2) -----------------------------------------------

SHIPPING_SENTENCE = (
    "Direct parcels are cheaper than consolidated imports for 6 of 11 products in KSA, "
    "5 of 12 in UAE and 0 of 11 in KWT."
)


def _rule(
    applies: DeMinimisApplies = "below", *excluded: AttributeName, threshold: str = "1000.00"
) -> DeMinimisRule:
    return DeMinimisRule(
        threshold=Decimal(threshold),
        applies=applies,
        excluded_attributes=excluded,
        source="test rule",
    )


def _comparison(
    code: str,
    rule: DeMinimisRule | None = None,
    prices: Sequence[tuple[str, str, bool]] = (),
) -> ShippingComparison:
    """A hand-built market for sentence tests: (consolidated, parcel, waived) per product."""
    products = tuple(
        ProductComparison(
            sku=f"SKU-{n}",
            name_en=f"Product {n}",
            consolidated_price=Decimal(consolidated),
            parcel_price=Decimal(parcel),
            change_pct=Decimal(parcel) / Decimal(consolidated) - 1,
            parcel_duty_rate=Decimal(0) if waived else Decimal("0.05"),
            parcel_duty_waived=waived,
        )
        for n, (consolidated, parcel, waived) in enumerate(prices)
    )
    return ShippingComparison(
        code=code,
        name=f"{code} name",
        currency="XXX",
        minor_units=2,
        de_minimis=rule,
        products=products,
    )


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        (_rule("below"), "No duty on a parcel whose CIF is below 1,000.00 XXX."),
        (
            _rule("at_or_below", "contains_alcohol"),
            "No duty on a parcel whose CIF is at or below 1,000.00 XXX, "
            "except products containing alcohol.",
        ),
        (
            _rule("below", "contains_alcohol", "contains_pork"),
            "No duty on a parcel whose CIF is below 1,000.00 XXX, "
            "except products containing alcohol or pork.",
        ),
        (
            _rule("below", *get_args(AttributeName)),
            "No duty on a parcel whose CIF is below 1,000.00 XXX, "
            "except products containing alcohol, pork or a lithium battery.",
        ),
        (_rule("below", threshold="250.5"), "No duty on a parcel whose CIF is below 250.50 XXX."),
        (None, "No de minimis rule, so every parcel pays duty."),
    ],
    ids=["below", "at-or-below-except", "two-exclusions", "every-attribute", "minor-units", "none"],
)
def test_de_minimis_rule_sentences(rule: DeMinimisRule | None, expected: str) -> None:
    assert de_minimis_sentence(_comparison("A", rule)) == expected


def test_market_sentences_with_a_rule() -> None:
    comparison = _comparison(
        "A", _rule(), [("10.00", "9.00", True), ("10.00", "12.00", True), ("10.00", "10.00", False)]
    )

    assert shipping_market_sentences(comparison) == (
        "No duty on a parcel whose CIF is below 1,000.00 XXX. Parcels are cheaper for 1 of "
        "3 products, dearer for 1 and unchanged for 1. Duty is waived on 2 of them."
    )


def test_market_sentences_without_a_rule_say_nothing_about_waivers() -> None:
    comparison = _comparison("A", None, [("10.00", "11.00", False)])

    assert shipping_market_sentences(comparison) == (
        "No de minimis rule, so every parcel pays duty. Parcels are cheaper for 0 of 1 product, "
        "dearer for 1 and unchanged for 0."
    )


def test_market_sentences_with_a_rule_that_waived_nothing() -> None:
    comparison = _comparison("A", _rule(), [("10.00", "11.00", False)])

    assert shipping_market_sentences(comparison).endswith(" Duty is waived on 0 of them.")


@pytest.mark.parametrize(
    ("rule", "opening"),
    [
        (_rule(), "No duty on a parcel whose CIF is below 1,000.00 XXX."),
        (None, "No de minimis rule, so every parcel pays duty."),
    ],
    ids=["rule", "no-rule"],
)
def test_a_market_that_sells_nothing_gives_its_rule_and_no_products(
    rule: DeMinimisRule | None, opening: str
) -> None:
    assert shipping_market_sentences(_comparison("A", rule)) == (
        f"{opening} No products are for sale."
    )


def test_shipping_sentence_for_the_sample_data(report: ExpansionReport) -> None:
    assert shipping_sentence(report.shipping) == SHIPPING_SENTENCE


def test_shipping_sentence_leaves_out_a_market_that_sells_nothing() -> None:
    comparisons = [
        _comparison("A"),
        _comparison("B", None, [("10.00", "9.00", False)]),
        _comparison("C", None, [("10.00", "9.00", False), ("10.00", "11.00", False)]),
    ]

    assert shipping_sentence(comparisons) == (
        "Direct parcels are cheaper than consolidated imports for 1 of 1 product in B "
        "and 1 of 2 in C."
    )


def test_shipping_sentence_when_no_market_sells_anything() -> None:
    assert shipping_sentence([_comparison("A"), _comparison("B")]) == (
        "No market has products for sale."
    )


def test_lists_can_join_with_or() -> None:
    assert join_list(["alcohol"], word="or") == "alcohol"
    assert join_list(["alcohol", "pork"], word="or") == "alcohol or pork"
    assert join_list(["a", "b", "c"], word="or") == "a, b or c"


def test_consolidated_or_parcel_is_appendix_a(rendered: str) -> None:
    assert _section(rendered, "Consolidated or parcel") == SHIPPING_SECTION


def test_a_market_that_sells_nothing_has_no_parcel_table(
    catalogue: Catalogue, config: GccConfig
) -> None:
    report = build_report(only_products(catalogue, VANILLA, GUMMY_BEARS), config, REPORT_ORDERED_AT)
    section = _section(render_report(report), "Consolidated or parcel")

    assert section.startswith(
        "## Consolidated or parcel\n\n"
        "Direct parcels are cheaper than consolidated imports for 0 of 1 product in UAE.\n\n"
        "### KSA (Saudi Arabia)\n\n"
        "No duty on a parcel whose CIF is below 1,000.00 SAR. No products are for sale.\n\n"
        "### UAE (United Arab Emirates)\n\n"
    )
    assert "| GROC-VAN-061 | Pure Vanilla Extract | 55.99 | 57.99 | +3.6% | 5.0% |\n" in section
    assert section.endswith(
        "### KWT (Kuwait)\n\n"
        "No de minimis rule, so every parcel pays duty. No products are for sale.\n\n"
    )


def test_parcel_rows_escape_cells_from_the_data(catalogue: Catalogue, config: GccConfig) -> None:
    lip = next(p for p in catalogue.products if p.sku == "BEAU-LIP-040")
    odd = lip.model_copy(update={"name": lip.name.model_copy(update={"en": "Lip | Balm\nXL"})})
    report = build_report(
        catalogue.model_copy(update={"products": [odd]}), config, REPORT_ORDERED_AT
    )
    row = "| BEAU-LIP-040 | Lip \\| Balm XL | 16.95 | 15.95 | -5.9% | waived |\n"

    assert row in render_report(report)


# --- tariff exposure (§9.3.2 item 3) ------------------------------------------------------

TARIFF_SENTENCE = (
    "A 10 pp tariff rise lifts average prices by 9.0% for consolidated imports and 0.9% for "
    "direct parcels in KSA; 9.3% and 1.5% in UAE; and 7.6% and 9.4% in KWT."
)


def _exposures(code: str, consolidated: str | None, parcel: str | None) -> list[TariffExposure]:
    """A hand-built market's two rows, one figure for every rise; ``None`` sells nothing."""

    def changes(figure: str | None) -> tuple[Decimal | None, ...]:
        return tuple(None if figure is None else Decimal(figure) for _ in TARIFF_RISES_POINTS)

    return [
        TariffExposure(code, "consolidated", changes(consolidated)),
        TariffExposure(code, "parcel", changes(parcel)),
    ]


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        (["a"], "a"),
        (["a and b", "c and d"], "a and b; and c and d"),
        (["a and b", "c and d", "e and f"], "a and b; c and d; and e and f"),
    ],
)
def test_clauses_join_with_semicolons_and_a_final_and(items: list[str], expected: str) -> None:
    assert join_clauses(items) == expected


def test_no_clauses_cannot_be_joined() -> None:
    with pytest.raises(ValueError, match="nothing to join"):
        join_clauses([])


def test_tariff_sentence_for_the_sample_data(report: ExpansionReport) -> None:
    assert tariff_sentence(report.tariffs) == TARIFF_SENTENCE


def test_tariff_sentence_for_one_market() -> None:
    assert tariff_sentence(_exposures("A", "0.09", "0.009")) == (
        "A 10 pp tariff rise lifts average prices by 9.0% for consolidated imports and 0.9% for "
        "direct parcels in A."
    )


def test_tariff_sentence_for_two_markets() -> None:
    exposures = [*_exposures("A", "0.09", "0.009"), *_exposures("B", "0.1", "0.02")]

    assert tariff_sentence(exposures) == (
        "A 10 pp tariff rise lifts average prices by 9.0% for consolidated imports and 0.9% for "
        "direct parcels in A; and 10.0% and 2.0% in B."
    )


def test_tariff_sentence_quotes_the_headline_rise() -> None:
    exposures = [
        TariffExposure("A", "consolidated", (Decimal("0.01"), Decimal("0.02"), Decimal("0.03"))),
        TariffExposure("A", "parcel", (Decimal("0.04"), Decimal("0.05"), Decimal("0.06"))),
    ]

    assert tariff_sentence(exposures) == (
        "A 10 pp tariff rise lifts average prices by 2.0% for consolidated imports and 5.0% for "
        "direct parcels in A."
    )


def test_tariff_sentence_leaves_out_a_market_that_sells_nothing() -> None:
    exposures = [
        *_exposures("A", None, None),
        *_exposures("B", "0.1", "0.02"),
        *_exposures("C", "0.05", "0"),
    ]

    assert tariff_sentence(exposures) == (
        "A 10 pp tariff rise lifts average prices by 10.0% for consolidated imports and 2.0% for "
        "direct parcels in B; and 5.0% and 0.0% in C."
    )


def test_tariff_sentence_when_no_market_sells_anything() -> None:
    exposures = [*_exposures("A", None, None), *_exposures("B", None, None)]

    assert tariff_sentence(exposures) == "No market has products for sale."


def test_tariff_exposure_is_appendix_a(rendered: str) -> None:
    assert _section(rendered, "Tariff exposure") == TARIFF_SECTION


def test_a_market_that_sells_nothing_shows_dashes_for_tariffs(
    catalogue: Catalogue, config: GccConfig
) -> None:
    report = build_report(only_products(catalogue, VANILLA, GUMMY_BEARS), config, REPORT_ORDERED_AT)
    section = _section(render_report(report), "Tariff exposure")

    assert "| KSA | Consolidated import | - | - | - |\n| KSA | Direct parcel | - | - | - |\n" in (
        section
    )
    assert "in UAE.\n" in section


def test_tariff_sentence_names_a_market_missing_a_shipping_model() -> None:
    exposures = [*_exposures("A", "0.09", "0.009"), _exposures("B", "0.1", "0.02")[0]]

    with pytest.raises(LocalisationError, match=r"^B: no parcel figure for the tariff sentence$"):
        tariff_sentence(exposures)


# --- how a price is built (§9.3.2 item 4) -------------------------------------------------

BUILD_UP_SENTENCES = [
    "Wireless Noise-Cancelling Headphones (ELEC-HP-001) is the first product every market sells.",
    "Shipped as a direct parcel instead of a consolidated import, its price changes by -3.8% "
    "in KSA, -3.8% in UAE and +2.0% in KWT.",
]
NO_BUILD_UP_SENTENCE = "No product is sold in every market, so there is no price to break down."

BUILD_UP_SECTION = """\
## How a price is built

Wireless Noise-Cancelling Headphones (ELEC-HP-001) is the first product every market sells. Shipped as a direct parcel instead of a consolidated import, its price changes by -3.8% in KSA, -3.8% in UAE and +2.0% in KWT.

### KSA (SAR)

| Step | Consolidated import | Direct parcel |
|---|---:|---:|
| Catalogue price, converted | 562.46 | 562.46 |
| Freight | 5.91 | 11.81 |
| Duty | 28.42 | 0.00 (waived) |
| VAT | 89.52 | 86.14 |
| Rounding and price ending | 0.64 | 0.54 |
| **Shelf price** | **686.95** | **660.95** |

### UAE (AED)

| Step | Consolidated import | Direct parcel |
|---|---:|---:|
| Catalogue price, converted | 550.84 | 550.84 |
| Freight | 5.14 | 10.28 |
| Duty | 27.80 | 0.00 (waived) |
| VAT | 29.19 | 28.06 |
| Rounding and price ending | 0.02 | 0.81 |
| **Shelf price** | **612.99** | **589.99** |

### KWT (KWD)

| Step | Consolidated import | Direct parcel |
|---|---:|---:|
| Catalogue price, converted | 46.047 | 46.047 |
| Freight | 0.537 | 1.075 |
| Duty | 2.329 | 2.356 |
| VAT | 0.000 | 0.000 |
| Rounding and price ending | 0.037 | 0.472 |
| **Shelf price** | **48.950** | **49.950** |

"""  # noqa: E501


def _quote(
    goods: str,
    freight: str,
    duty: str,
    vat: str,
    shelf_price: str,
    *,
    shipping: ShippingModel = "consolidated",
    waived: bool = False,
) -> PriceQuote:
    """A hand-built quote; only the components, the shelf price and the waiver matter here."""
    parts = [Decimal(goods), Decimal(freight), Decimal(duty), Decimal(vat)]
    return PriceQuote(
        sku="SKU-1",
        market="A",
        currency="XXX",
        goods=parts[0],
        freight=parts[1],
        duty=parts[2],
        vat=parts[3],
        gross=sum(parts, Decimal(0)),
        shelf_price=Decimal(shelf_price),
        margin_pct=Decimal("0.5"),
        shipping=shipping,
        duty_rate=Decimal(0) if waived else Decimal("0.05"),
        duty_waived=waived,
    )


def _build_up(code: str, consolidated: str, parcel: str) -> PriceBuildUp:
    """A hand-built market whose two quotes differ only in their shelf prices."""
    return PriceBuildUp(
        code=code,
        currency="XXX",
        minor_units=2,
        consolidated=_quote("1.00", "0", "0", "0", consolidated),
        parcel=_quote("1.00", "0", "0", "0", parcel, shipping="parcel"),
    )


def _adds_up(column: Sequence[str]) -> bool:
    """The five displayed steps of a build-up column add up to its shelf price."""
    *steps, shelf = (Decimal(text.removesuffix(" (waived)").replace(",", "")) for text in column)
    return sum(steps, Decimal(0)) == shelf


def test_build_up_sentences_for_the_sample_data(report: ExpansionReport) -> None:
    assert build_up_sentences(report.sample_product, report.build_ups) == BUILD_UP_SENTENCES


def test_build_up_sentences_for_one_market() -> None:
    sample = SampleProduct(sku="SKU-1", name_en="Thing")

    assert build_up_sentences(sample, [_build_up("A", "10.00", "10.00")]) == [
        "Thing (SKU-1) is the first product every market sells.",
        "Shipped as a direct parcel instead of a consolidated import, its price changes by "
        "0.0% in A.",
    ]


def test_build_up_sentences_when_no_product_is_sold_everywhere() -> None:
    assert build_up_sentences(None, []) == [NO_BUILD_UP_SENTENCE]


def test_build_up_sentences_keep_data_on_one_line() -> None:
    sample = SampleProduct(sku="SKU\n1", name_en="Two\r\nlines")
    build_ups = [_build_up("A\nB", "10.00", "11.00"), _build_up("C", "10.00", "9.00")]

    assert build_up_sentences(sample, build_ups) == [
        "Two lines (SKU 1) is the first product every market sells.",
        "Shipped as a direct parcel instead of a consolidated import, its price changes by "
        "+10.0% in A B and -10.0% in C.",
    ]


def test_build_up_columns_for_ksa(report: ExpansionReport) -> None:
    ksa = report.build_ups[0]

    assert build_up_column(ksa.consolidated, ksa.minor_units, figure="KSA") == [
        "562.46",
        "5.91",
        "28.42",
        "89.52",
        "0.64",
        "686.95",
    ]
    # 660.95 - (562.46 + 11.81 + 0.00 + 86.14), although shelf_price - gross is 0.53375.
    assert build_up_column(ksa.parcel, ksa.minor_units, figure="KSA") == [
        "562.46",
        "11.81",
        "0.00 (waived)",
        "86.14",
        "0.54",
        "660.95",
    ]


@pytest.mark.parametrize("waived", [False, True])
def test_duty_shows_waived_exactly_when_it_is(waived: bool) -> None:
    quote = _quote("10.00", "1.00", "0", "1.65", "12.95", shipping="parcel", waived=waived)

    assert build_up_column(quote, 2, figure="A")[2] == ("0.00 (waived)" if waived else "0.00")


def test_the_rounding_line_can_be_below_zero() -> None:
    # Each component rounds up by half a minor unit; the gross, 1.95, already has the ending.
    quote = _quote("1.005", "0.315", "0.315", "0.315", "1.95")

    assert build_up_column(quote, 2, figure="A") == [
        "1.01",
        "0.32",
        "0.32",
        "0.32",
        "-0.02",
        "1.95",
    ]


def test_a_component_too_large_to_display_is_named() -> None:
    quote = _quote("1E+30", "0", "0", "0", "1E+30")

    with pytest.raises(LocalisationError, match=r"^A: ELEC parcel goods is too large to display$"):
        build_up_column(quote, 2, figure="A: ELEC parcel")


def test_every_build_up_column_adds_up_to_the_shelf_price(
    catalogue: Catalogue, config: GccConfig
) -> None:
    columns = 0
    for code, market in config.markets.items():
        for model in get_args(ShippingModel):
            localised = localise_and_summarise(
                catalogue.products, config, code, REPORT_ORDERED_AT, Decimal("0"), model
            )
            for item in localised.items:
                column = build_up_column(item.quote, market.currency.minor_units, figure=code)
                assert _adds_up(column), (code, model, item.sku, column)
                columns += 1

    assert columns == 2 * sum(FOR_SALE_COUNTS.values())


_COMPONENT = st.decimals(min_value=0, max_value=100_000, places=6, allow_nan=False)


@settings(max_examples=200)
@given(
    components=st.tuples(_COMPONENT, _COMPONENT, _COMPONENT, _COMPONENT),
    minor_units=st.integers(min_value=0, max_value=3),
    ending=st.sampled_from(["0", "0.5", "0.95", "0.99", "0.950"]),
    waived=st.booleans(),
)
def test_any_build_up_column_adds_up_to_the_shelf_price(
    components: tuple[Decimal, Decimal, Decimal, Decimal],
    minor_units: int,
    ending: str,
    waived: bool,
) -> None:
    gross = sum(components, Decimal(0))
    charm = Decimal(ending)
    fits = charm == charm.quantize(Decimal(1).scaleb(-minor_units))
    shelf = charm_up(round_minor(gross, minor_units), charm if fits else None, minor_units)
    quote = _quote(*(str(c) for c in components), str(shelf), waived=waived)

    assert _adds_up(build_up_column(quote, minor_units, figure="A"))


def test_how_a_price_is_built_is_appendix_a(rendered: str) -> None:
    assert _section(rendered, "How a price is built") == BUILD_UP_SECTION


@pytest.mark.parametrize(
    "skus",
    [(VANILLA,), (VANILLA, GUMMY_BEARS), ()],
    ids=["only-uae-sells-it", "a-market-sells-nothing", "empty"],
)
def test_no_product_sold_everywhere_has_no_build_up_tables(
    catalogue: Catalogue, config: GccConfig, skus: tuple[str, ...]
) -> None:
    text = render_report(build_report(only_products(catalogue, *skus), config, REPORT_ORDERED_AT))

    assert _section(text, "How a price is built") == (
        f"## How a price is built\n\n{NO_BUILD_UP_SENTENCE}\n\n"
    )
    assert f"- {NO_BUILD_UP_SENTENCE}\n" in _section(text, "Summary")


def test_a_sample_product_name_with_a_line_break_stays_on_one_line(
    catalogue: Catalogue, config: GccConfig
) -> None:
    headphones = next(p for p in catalogue.products if p.sku == "ELEC-HP-001")
    odd = headphones.model_copy(
        update={"name": headphones.name.model_copy(update={"en": "Wireless\nHeadphones"})}
    )
    text = render_report(
        build_report(catalogue.model_copy(update={"products": [odd]}), config, REPORT_ORDERED_AT)
    )
    opening = "Wireless Headphones (ELEC-HP-001) is the first product every market sells. "

    assert _section(text, "How a price is built").startswith(
        f"## How a price is built\n\n{opening}Shipped as"
    )
    assert f"\n- {opening}Shipped as" in _section(text, "Summary")
    assert "\n\n\n" not in text
