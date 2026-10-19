"""M11: the expansion report's text (SPEC §9.3 and §9.4): formatting, sentences, the template."""

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from helpers import (
    GUMMY_BEARS,
    REPORT_ORDERED_AT,
    VANILLA,
    only_products,
    without_products,
)
from souqsort.compliance import ExcludedProduct
from souqsort.logistics.calendar import DeliveryEstimate
from souqsort.models import Catalogue, GccConfig
from souqsort.pipeline import LocalisationError
from souqsort.report import build_report, render_report
from souqsort.report.figures import ExpansionReport, MarketOverview
from souqsort.report.text import (
    clock_text,
    count_text,
    date_text,
    join_list,
    local_time_text,
    markets_sentences,
    money_text,
    not_sold_sentence,
    one_line,
    percent_text,
    report_context,
    signed_percent_text,
    table_cell,
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
        f"## Summary\n\n- {PRICE_SENTENCE}\n- {DELIVERY_SENTENCE}\n- {NOT_SOLD_SENTENCE}\n\n"
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
