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

from souqsort.display import SHIPPING_LABELS, WAIVED, excluded_grid_rows
from souqsort.models import AttributeName, DeMinimisApplies, ShippingModel
from souqsort.pipeline import LocalisationError
from souqsort.pricing.landed_cost import PriceQuote
from souqsort.pricing.money import round_minor
from souqsort.report.figures import (
    HEADLINE_TARIFF_RISE_POINTS,
    TARIFF_RISES_POINTS,
    ExpansionReport,
    MarketOverview,
    PriceBuildUp,
    ProductComparison,
    SampleProduct,
    ShippingComparison,
    TariffExposure,
)

type ContextValue = str | Sequence[ContextValue] | Mapping[str, ContextValue]

_TEMPLATE = "expansion_report.md.j2"
_NO_VALUE = "-"
_PERCENT = Decimal(100)
_NOTHING_FOR_SALE = "No market has products for sale."

# The tariff sentence's two figures per market, in its order: "9.0% for consolidated imports
# and 0.9% for direct parcels".
_SENTENCE_MODELS: tuple[ShippingModel, ShippingModel] = ("consolidated", "parcel")

# How a de minimis rule reads: "a parcel whose CIF is below 1,000.00 SAR".
_APPLIES: dict[DeMinimisApplies, str] = {"below": "below", "at_or_below": "at or below"}

# What a product excluded from de minimis contains: "except products containing alcohol".
_CONTAINING: dict[AttributeName, str] = {
    "contains_alcohol": "alcohol",
    "contains_pork": "pork",
    "contains_lithium_battery": "a lithium battery",
}

# The build-up's steps above the shelf price, in the order build_up_column gives them.
_BUILD_UP_STEPS = (
    "Catalogue price, converted",
    "Freight",
    "Duty",
    "VAT",
    "Rounding and price ending",
)

# English day names by date.weekday(). strftime's %a follows the locale, and the report must
# be the same bytes on every machine.
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# A line ending as Markdown reads one.
_LINE_BREAK = re.compile(r"\r\n|\r|\n")


# --- formatting (§9.3.1) ------------------------------------------------------------------


def _rounded(figure: str, amount: Decimal, places: int, scale: Decimal = Decimal(1)) -> Decimal:
    """``amount * scale``, rounded half up to ``places`` decimals for display.

    Every number the report shows is rounded here. A figure too large for decimal arithmetic
    raises ``LocalisationError`` naming ``figure`` (``"KSA: average margin"``), as the CLI and
    the dashboard do, so the report command fails with a message rather than a traceback.
    """
    try:
        return round_minor(amount * scale, places)
    except ArithmeticError as exc:
        raise LocalisationError(f"{figure} is too large to display") from exc


def money_text(amount: Decimal, minor_units: int, *, figure: str) -> str:
    """The currency's minor units, rounded half up, with commas between thousands.

    ``figure`` names the amount in the error if it is too large to display.
    """
    return f"{_rounded(figure, amount, minor_units):,f}"


def percent_text(fraction: Decimal, *, figure: str) -> str:
    """A rate or margin: one decimal, rounded half up, no sign (``0.15`` -> ``15.0%``).

    ``figure`` names the fraction in the error if it is too large to display.
    """
    return f"{_rounded(figure, fraction, 1, _PERCENT):f}%"


def signed_percent_text(fraction: Decimal, *, figure: str) -> str:
    """A change: as ``percent_text``, with ``+`` when it is positive after rounding.

    ``round_minor`` never returns a signed zero, so nothing shows as ``-0.0%`` or ``+0.0%``.
    """
    rounded = _rounded(figure, fraction, 1, _PERCENT)
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


def join_list(items: Sequence[str], *, word: str = "and") -> str:
    """``a``, ``a and b``, ``a, b and c``; ``word`` can be ``"or"``.

    Raises ``ValueError`` if there is nothing to join.
    """
    if not items:
        raise ValueError("nothing to join")
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} {word} {items[-1]}"


def join_clauses(items: Sequence[str]) -> str:
    """Clauses that already contain "and": ``a``, ``a; and b``, ``a; b; and c``.

    Raises ``ValueError`` if there is nothing to join.
    """
    if not items:
        raise ValueError("nothing to join")
    if len(items) == 1:
        return items[0]
    return f"{'; '.join(items[:-1])}; and {items[-1]}"


def count_text(count: int, noun: str) -> str:
    """``1 product``, otherwise ``N products``."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def one_line(text: str) -> str:
    """Text from the data, kept on one line: each line break becomes a space.

    Every data string the report places, in a sentence or a table, goes through this, so a
    line break in the data can never split a paragraph, a bullet or a row.
    """
    return _LINE_BREAK.sub(" ", text)


def table_cell(text: str) -> str:
    """Text from the data, safe in a Markdown table cell: ``|`` escaped, line breaks as spaces."""
    return one_line(text.replace("|", "\\|"))


def _above_catalogue(market: MarketOverview) -> str:
    return f"{market.code}: average above catalogue price"


# --- sentences (§9.3.2) -------------------------------------------------------------------


def markets_sentences(markets: Sequence[MarketOverview]) -> list[str]:
    """The two sentences of "Markets side by side": prices, then delivery.

    The price sentence lists the markets that sell something, lowest average first, comparing
    the full-precision averages; exact ties keep config order. The delivery sentence lists
    every market, in config order.
    """
    priced = sorted(
        (
            (market.average_above_catalogue_pct, market)
            for market in markets
            if market.average_above_catalogue_pct is not None
        ),
        key=lambda pair: pair[0],
    )
    if priced:
        shown = [
            (percent_text(above, figure=_above_catalogue(market)), one_line(market.code))
            for above, market in priced
        ]
        phrases = [
            f"{percent} in {code}" if position else f"{percent} above the catalogue price in {code}"
            for position, (percent, code) in enumerate(shown)
        ]
        prices = f"On average, shelf prices sit {join_list(phrases)}."
    else:
        prices = _NOTHING_FOR_SALE

    deliveries = [f"{date_text(m.delivery.delivery_date)} in {one_line(m.code)}" for m in markets]
    return [prices, f"For this order, delivery is on {join_list(deliveries)}."]


def de_minimis_sentence(comparison: ShippingComparison) -> str:
    """The rule a market's parcel subsection opens with.

    The threshold is shown in the market currency's minor units; excluded attributes join
    with "or".
    """
    rule = comparison.de_minimis
    if rule is None:
        return "No de minimis rule, so every parcel pays duty."
    threshold = money_text(
        rule.threshold, comparison.minor_units, figure=f"{comparison.code}: de minimis threshold"
    )
    sentence = (
        f"No duty on a parcel whose CIF is {_APPLIES[rule.applies]} {threshold} "
        f"{one_line(comparison.currency)}"
    )
    if rule.excluded_attributes:
        containing = [_CONTAINING[name] for name in rule.excluded_attributes]
        sentence += f", except products containing {join_list(containing, word='or')}"
    return f"{sentence}."


def shipping_market_sentences(comparison: ShippingComparison) -> str:
    """A market's parcel subsection: its rule, then its counts, or that nothing is for sale.

    The waived count is given only when the market has a de minimis rule.
    """
    sentences = [de_minimis_sentence(comparison)]
    if not comparison.products:
        sentences.append("No products are for sale.")
        return " ".join(sentences)
    sentences.append(
        f"Parcels are cheaper for {comparison.cheaper} of "
        f"{count_text(len(comparison.products), 'product')}, dearer for {comparison.dearer} "
        f"and unchanged for {comparison.unchanged}."
    )
    if comparison.de_minimis is not None:
        sentences.append(f"Duty is waived on {comparison.waived} of them.")
    return " ".join(sentences)


def shipping_sentence(comparisons: Sequence[ShippingComparison]) -> str:
    """The sentence of "Consolidated or parcel": markets that sell something, config order."""
    selling = [comparison for comparison in comparisons if comparison.products]
    if not selling:
        return _NOTHING_FOR_SALE
    phrases = [
        f"{c.cheaper} of {len(c.products)} in {one_line(c.code)}"
        if position
        else f"{c.cheaper} of {count_text(len(c.products), 'product')} in {one_line(c.code)}"
        for position, c in enumerate(selling)
    ]
    return f"Direct parcels are cheaper than consolidated imports for {join_list(phrases)}."


def tariff_sentence(tariffs: Sequence[TariffExposure]) -> str:
    """The sentence of "Tariff exposure", at ``HEADLINE_TARIFF_RISE_POINTS``.

    Markets in config order, both shipping models each; a market that sells nothing has no
    averages and is left out. Raises ``LocalisationError`` naming the market and model if a
    market has figures for one shipping model but not the other.
    """
    headline = TARIFF_RISES_POINTS.index(HEADLINE_TARIFF_RISE_POINTS)
    by_market: dict[str, dict[ShippingModel, Decimal]] = {}
    for exposure in tariffs:
        change = exposure.average_change_pct[headline]
        if change is not None:
            by_market.setdefault(exposure.code, {})[exposure.shipping] = change
    if not by_market:
        return _NOTHING_FOR_SALE

    clauses = []
    for position, (code, changes) in enumerate(by_market.items()):
        for model in _SENTENCE_MODELS:
            if model not in changes:
                raise LocalisationError(f"{code}: no {model} figure for the tariff sentence")
        consolidated, parcel = (
            percent_text(
                changes[model],
                figure=f"{code}: {HEADLINE_TARIFF_RISE_POINTS} pp {model} price change",
            )
            for model in _SENTENCE_MODELS
        )
        clauses.append(
            f"{consolidated} and {parcel} in {one_line(code)}"
            if position
            else f"{consolidated} for consolidated imports and {parcel} for direct parcels "
            f"in {one_line(code)}"
        )
    return (
        f"A {HEADLINE_TARIFF_RISE_POINTS} pp tariff rise lifts average prices by "
        f"{join_clauses(clauses)}."
    )


def build_up_sentences(
    sample: SampleProduct | None, build_ups: Sequence[PriceBuildUp]
) -> list[str]:
    """The sentences of "How a price is built": the sample product, then its parcel change.

    The change is ``parcel / consolidated - 1`` of the shelf prices, every market in config
    order (each sells the sample product).
    """
    if sample is None:
        return ["No product is sold in every market, so there is no price to break down."]
    changes = [
        (
            signed_percent_text(
                b.parcel.shelf_price / b.consolidated.shelf_price - 1,
                figure=f"{b.code}: {sample.sku} parcel change",
            ),
            one_line(b.code),
        )
        for b in build_ups
    ]
    phrases = [f"{change} in {code}" for change, code in changes]
    return [
        f"{one_line(sample.name_en)} ({one_line(sample.sku)}) is the first product every "
        "market sells.",
        "Shipped as a direct parcel instead of a consolidated import, its price changes by "
        f"{join_list(phrases)}.",
    ]


def not_sold_sentence(product_count: int, markets: Sequence[MarketOverview]) -> str:
    """The sentence of "Not sold": every market, in config order."""
    if all(not market.not_sold for market in markets):
        return "Every market can sell every product."
    phrases = [
        f"{one_line(market.code)} {len(market.not_sold)}"
        if position
        else f"{one_line(market.code)} cannot sell {len(market.not_sold)}"
        for position, market in enumerate(markets)
    ]
    return f"Out of {count_text(product_count, 'product')}, {join_list(phrases)}."


# --- the template -------------------------------------------------------------------------


def _market_row(market: MarketOverview) -> dict[str, str]:
    above = market.average_above_catalogue_pct
    margin = market.average_margin_pct
    code = market.code
    return {
        "market": table_cell(f"{code} ({market.name})"),
        "currency": table_cell(market.currency),
        "vat": percent_text(market.vat_rate, figure=f"{code}: VAT rate"),
        "for_sale": str(market.for_sale),
        "not_sold": str(len(market.not_sold)),
        "above_catalogue": (
            _NO_VALUE
            if above is None
            else signed_percent_text(above, figure=_above_catalogue(market))
        ),
        "average_margin": (
            _NO_VALUE if margin is None else percent_text(margin, figure=f"{code}: average margin")
        ),
        "ordered": local_time_text(market.delivery.ordered_at_local),
        "cutoff": clock_text(market.cutoff),
        "delivered": date_text(market.delivery.delivery_date),
    }


def _parcel_row(comparison: ShippingComparison, product: ProductComparison) -> dict[str, str]:
    figure = f"{comparison.code}: {product.sku}"
    minor_units = comparison.minor_units
    return {
        "sku": table_cell(product.sku),
        "product": table_cell(product.name_en),
        "consolidated": money_text(
            product.consolidated_price, minor_units, figure=f"{figure} consolidated price"
        ),
        "parcel": money_text(product.parcel_price, minor_units, figure=f"{figure} parcel price"),
        "change": signed_percent_text(product.change_pct, figure=f"{figure} parcel change"),
        "duty": (
            WAIVED
            if product.parcel_duty_waived
            else percent_text(product.parcel_duty_rate, figure=f"{figure} parcel duty rate")
        ),
    }


def _shipping_market(comparison: ShippingComparison) -> dict[str, ContextValue]:
    return {
        "heading": one_line(f"{comparison.code} ({comparison.name})"),
        "sentences": shipping_market_sentences(comparison),
        "currency": table_cell(comparison.currency),
        "rows": [_parcel_row(comparison, product) for product in comparison.products],
    }


def _tariff_row(exposure: TariffExposure) -> dict[str, ContextValue]:
    figure = f"{exposure.code}: {exposure.shipping} price change"
    return {
        "market": table_cell(exposure.code),
        "shipping": SHIPPING_LABELS[exposure.shipping],
        "changes": [
            _NO_VALUE
            if change is None
            else signed_percent_text(change, figure=f"{figure} at +{rise} pp")
            for rise, change in zip(TARIFF_RISES_POINTS, exposure.average_change_pct, strict=True)
        ],
    }


def build_up_column(quote: PriceQuote, minor_units: int, *, figure: str) -> list[str]:
    """One column of a build-up: goods, freight, duty, VAT, rounding, then the shelf price.

    Each component is rounded for display, and the rounding line is the shelf price minus
    their sum, so the column adds up exactly to the shelf price. It can be a minor unit or two
    below zero when the rounded gross already has the price ending. ``figure`` names the
    quote in the error if an amount is too large to display.
    """
    components = [
        _rounded(f"{figure} {name}", amount, minor_units)
        for name, amount in (
            ("goods", quote.goods),
            ("freight", quote.freight),
            ("duty", quote.duty),
            ("VAT", quote.vat),
        )
    ]
    shelf = _rounded(f"{figure} shelf price", quote.shelf_price, minor_units)
    rounding = _rounded(f"{figure} rounding", shelf - sum(components, Decimal(0)), minor_units)
    goods, freight, duty, vat = (f"{amount:,f}" for amount in components)
    if quote.duty_waived:
        duty = f"{duty} ({WAIVED})"
    return [goods, freight, duty, vat, f"{rounding:,f}", f"{shelf:,f}"]


def _build_up_market(build_up: PriceBuildUp) -> dict[str, ContextValue]:
    figure = f"{build_up.code}: {build_up.consolidated.sku}"
    consolidated = build_up_column(
        build_up.consolidated, build_up.minor_units, figure=f"{figure} consolidated"
    )
    parcel = build_up_column(build_up.parcel, build_up.minor_units, figure=f"{figure} parcel")
    *import_steps, import_shelf = consolidated
    *parcel_steps, parcel_shelf = parcel
    return {
        "heading": one_line(f"{build_up.code} ({build_up.currency})"),
        "rows": [
            {"step": step, "consolidated": by_import, "parcel": by_parcel}
            for step, by_import, by_parcel in zip(
                _BUILD_UP_STEPS, import_steps, parcel_steps, strict=True
            )
        ],
        "shelf": {"consolidated": import_shelf, "parcel": parcel_shelf},
    }


def _not_sold_rows(markets: Sequence[MarketOverview]) -> list[dict[str, str]]:
    return [
        {
            "market": table_cell(market.code),
            "sku": table_cell(row.sku),
            "product": table_cell(row.name_en),
            "reasons": table_cell(row.reasons),
        }
        for market in markets
        for row in excluded_grid_rows(market.not_sold)  # the dashboard's labels
    ]


def report_context(report: ExpansionReport) -> Mapping[str, ContextValue]:
    """Everything the template places, as strings, lists and dicts of strings.

    No key is a dict method name (``items``, ``values``…): the template's ``row.key`` syntax
    would find the method first.

    Raises ``LocalisationError`` naming the figure if one is too large to display.
    """
    ordered_at = report.ordered_at.astimezone(UTC)
    markets = markets_sentences(report.markets)
    shipping = shipping_sentence(report.shipping)
    tariffs = tariff_sentence(report.tariffs)
    build_up = build_up_sentences(report.sample_product, report.build_ups)
    not_sold = not_sold_sentence(report.product_count, report.markets)
    return {
        "order": {"date": date_text(ordered_at.date()), "time": clock_text(ordered_at.time())},
        "data": {
            "config_version": one_line(report.config_version),
            "fx_as_of": report.fx_as_of.isoformat(),
            "catalogue_version": one_line(report.catalogue_version),
        },
        "summary": [*markets, shipping, tariffs, " ".join(build_up), not_sold],
        "markets": {
            "sentences": " ".join(markets),
            "rows": [_market_row(market) for market in report.markets],
        },
        "shipping": {
            "sentence": shipping,
            "markets": [_shipping_market(comparison) for comparison in report.shipping],
        },
        "tariffs": {
            "sentence": tariffs,
            "rises": [f"+{rise} pp" for rise in TARIFF_RISES_POINTS],
            "rows": [_tariff_row(exposure) for exposure in report.tariffs],
        },
        "build_up": {
            "sentences": " ".join(build_up),
            "markets": [_build_up_market(build_up) for build_up in report.build_ups],
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
    """The report as Markdown (§9.4): ``\\n`` line endings, ending with a single newline.

    Raises ``LocalisationError`` as ``report_context`` does.
    """
    return _environment().get_template(_TEMPLATE).render(report_context(report))
