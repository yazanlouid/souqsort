"""The expansion report's text: formatting, sentences and the template context (SPEC §9.3).

Every number is formatted here, from ``Decimal``; the template receives strings only and
places them (§9.4.1).
"""

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from functools import cache

from jinja2 import Environment, PackageLoader, StrictUndefined

from souqsort.display import ATTRIBUTE_LABELS
from souqsort.pricing.money import round_minor
from souqsort.report.figures import ExpansionReport, MarketOverview

type ContextValue = str | Sequence[ContextValue] | Mapping[str, ContextValue]

_TEMPLATE = "expansion_report.md.j2"
_NO_VALUE = "-"

# English day names by date.weekday(). strftime's %a follows the locale, and the report must
# be the same bytes on every machine.
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# A line ending as Markdown reads one.
_LINE_BREAK = re.compile(r"\r\n|\r|\n")


# --- formatting (§9.3.1) ------------------------------------------------------------------


def money_text(amount: Decimal, minor_units: int) -> str:
    """The currency's minor units, rounded half up, with commas between thousands."""
    return f"{round_minor(amount, minor_units):,f}"


def percent_text(fraction: Decimal) -> str:
    """A rate or margin: one decimal, rounded half up, no sign (``0.15`` -> ``15.0%``)."""
    return f"{round_minor(fraction * 100, 1):f}%"


def signed_percent_text(fraction: Decimal) -> str:
    """A change: as ``percent_text``, with ``+`` when it is positive after rounding.

    ``round_minor`` never returns a signed zero, so nothing shows as ``-0.0%`` or ``+0.0%``.
    """
    rounded = round_minor(fraction * 100, 1)
    sign = "+" if rounded > 0 else ""
    return f"{sign}{rounded:f}%"


def date_text(day: date) -> str:
    """``Thu 2026-10-22``."""
    return f"{_WEEKDAYS[day.weekday()]} {day.isoformat()}"


def clock_text(moment: time) -> str:
    """``14:00``."""
    return f"{moment:%H:%M}"


def local_time_text(moment: datetime) -> str:
    """``Thu 2026-10-15 12:00``, on the clock ``moment`` already carries."""
    return f"{date_text(moment.date())} {clock_text(moment.time())}"


def join_list(items: Sequence[str]) -> str:
    """``a``, ``a and b``, ``a, b and c``. Raises ``ValueError`` if there is nothing to join."""
    if not items:
        raise ValueError("nothing to join")
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def count_text(count: int, noun: str) -> str:
    """``1 product``, otherwise ``N products``."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def table_cell(text: str) -> str:
    """Text from the data, safe in a Markdown table cell: ``|`` escaped, line breaks as spaces."""
    return _LINE_BREAK.sub(" ", text.replace("|", "\\|"))


# --- sentences (§9.3.2) -------------------------------------------------------------------


def markets_sentences(markets: Sequence[MarketOverview]) -> list[str]:
    """The two sentences of "Markets side by side": prices, then delivery.

    The price sentence lists the markets that sell something, lowest average first, comparing
    the full-precision averages; exact ties keep config order. The delivery sentence lists
    every market, in config order.
    """
    priced = sorted(
        (
            (market.average_above_catalogue_pct, market.code)
            for market in markets
            if market.average_above_catalogue_pct is not None
        ),
        key=lambda pair: pair[0],
    )
    if priced:
        phrases = [
            f"{percent_text(above)} in {code}"
            if position
            else f"{percent_text(above)} above the catalogue price in {code}"
            for position, (above, code) in enumerate(priced)
        ]
        prices = f"On average, shelf prices sit {join_list(phrases)}."
    else:
        prices = "No market has products for sale."

    deliveries = [f"{date_text(m.delivery.delivery_date)} in {m.code}" for m in markets]
    return [prices, f"For this order, delivery is on {join_list(deliveries)}."]


def not_sold_sentence(product_count: int, markets: Sequence[MarketOverview]) -> str:
    """The sentence of "Not sold": every market, in config order."""
    if all(not market.not_sold for market in markets):
        return "Every market can sell every product."
    phrases = [
        f"{market.code} {len(market.not_sold)}"
        if position
        else f"{market.code} cannot sell {len(market.not_sold)}"
        for position, market in enumerate(markets)
    ]
    return f"Out of {count_text(product_count, 'product')}, {join_list(phrases)}."


# --- the template -------------------------------------------------------------------------


def _market_row(market: MarketOverview) -> dict[str, str]:
    above = market.average_above_catalogue_pct
    margin = market.average_margin_pct
    return {
        "market": table_cell(f"{market.code} ({market.name})"),
        "currency": table_cell(market.currency),
        "vat": percent_text(market.vat_rate),
        "for_sale": str(market.for_sale),
        "not_sold": str(len(market.not_sold)),
        "above_catalogue": _NO_VALUE if above is None else signed_percent_text(above),
        "average_margin": _NO_VALUE if margin is None else percent_text(margin),
        "ordered": local_time_text(market.delivery.ordered_at_local),
        "cutoff": clock_text(market.cutoff),
        "delivered": date_text(market.delivery.delivery_date),
    }


def _not_sold_rows(markets: Sequence[MarketOverview]) -> list[dict[str, str]]:
    return [
        {
            "market": table_cell(market.code),
            "sku": table_cell(item.sku),
            "product": table_cell(item.name_en),
            "reasons": table_cell(", ".join(ATTRIBUTE_LABELS[reason] for reason in item.reasons)),
        }
        for market in markets
        for item in market.not_sold
    ]


def report_context(report: ExpansionReport) -> Mapping[str, ContextValue]:
    """Everything the template places, as strings, lists and dicts of strings.

    No key is a dict method name (``items``, ``values``…): the template's ``row.key`` syntax
    would find the method first.
    """
    ordered_at = report.ordered_at.astimezone(UTC)
    markets = markets_sentences(report.markets)
    not_sold = not_sold_sentence(report.product_count, report.markets)
    return {
        "order": {"date": date_text(ordered_at.date()), "time": clock_text(ordered_at.time())},
        "data": {
            "config_version": report.config_version,
            "fx_as_of": report.fx_as_of.isoformat(),
            "catalogue_version": report.catalogue_version,
        },
        "summary": [*markets, not_sold],
        "markets": {
            "sentences": " ".join(markets),
            "rows": [_market_row(market) for market in report.markets],
        },
        "not_sold": {"sentence": not_sold, "rows": _not_sold_rows(report.markets)},
    }


@cache
def _environment() -> Environment:
    return Environment(
        loader=PackageLoader("souqsort.report", "templates"),
        undefined=StrictUndefined,
        autoescape=False,  # Markdown, not HTML: table cells are escaped by table_cell
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render_report(report: ExpansionReport) -> str:
    """The report as Markdown (§9.4): ``\\n`` line endings, ending with a single newline."""
    return _environment().get_template(_TEMPLATE).render(report_context(report))
