"""Display-ready rows for a localised catalogue, shared by the CLI and the dashboard.

Formatting, and choosing which rows to show: every value comes from the engine's result
objects.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from souqsort.compliance import ExcludedProduct
from souqsort.models import AttributeName, DeMinimisApplies, MarketConfig, ShippingModel
from souqsort.orders import CheckoutKind, OrderQuote
from souqsort.pipeline import (
    MISSING_ARABIC_NAME,
    CatalogueSummary,
    LocalisationError,
    LocalisedProduct,
)
from souqsort.pricing.customs import parcel_fee_due
from souqsort.pricing.money import format_money

_NO_VALUE = "-"

# What the Duty column shows for a product whose duty de minimis waived.
WAIVED = "waived"

# What the dashboard calls each shipping model. The CLI keeps the codes.
SHIPPING_LABELS: dict[ShippingModel, str] = {
    "consolidated": "Consolidated import",
    "parcel": "Direct parcel",
}

# What a grid shows for each flag. A flag with no label here is shown as its code.
_FLAG_LABELS = {MISSING_ARABIC_NAME: "No Arabic name"}

# What the dashboard shows for each reason a product is not sold. The CLI keeps the codes.
ATTRIBUTE_LABELS: dict[AttributeName, str] = {
    "contains_alcohol": "Contains alcohol",
    "contains_pork": "Contains pork",
    "contains_lithium_battery": "Contains lithium battery",
}

# What the order table calls each amount added at checkout, in the order the rows come.
CHECKOUT_LABELS: dict[CheckoutKind, str] = {
    "customs_fee": "Customs fee",
    "duty": "Duty and VAT",
}

# How the parcel note words each de minimis test.
_APPLIES: dict[DeMinimisApplies, str] = {"below": "below", "at_or_below": "at or below"}


@dataclass(frozen=True)
class DisplayRow:
    """One localised product as text.

    ``shelf_price`` has exactly the currency's minor units, as the engine rounded it.
    ``margin_percent`` is a percentage with one decimal and no ``%`` sign (``"58.7"``), and so
    is ``duty_percent``, the duty rate applied (``"5.0"``; ``"0.0"`` when ``duty_waived``).
    ``delivery_date`` is an ISO date.
    """

    sku: str
    name_en: str
    currency: str
    shelf_price: str
    margin_percent: str
    duty_percent: str
    duty_waived: bool
    delivery_date: str
    flags: tuple[str, ...]


@dataclass(frozen=True)
class GridRow:
    """One localised product for a sortable grid.

    The same values as a ``DisplayRow``, but ``shelf_price`` and ``margin_percent`` are
    numbers, so a grid sorts them by value: as text, ``"111.95"`` comes before ``"16.95"``.
    Each keeps the decimals of its text. ``duty`` is the Duty cell (``"5.0%"`` or
    ``"waived"``). ``flags`` is one string of labels for a person to read
    (``"No Arabic name"``), empty when there are none; a ``DisplayRow`` keeps the codes.
    """

    sku: str
    name_en: str
    shelf_price: Decimal
    margin_percent: Decimal
    duty: str
    delivery_date: str
    flags: str


@dataclass(frozen=True)
class ExcludedGridRow:
    """A product the market does not sell, for a grid.

    ``reasons`` is one string of labels for a person to read (``"Contains pork"``), in the
    order the market lists them.
    """

    sku: str
    name_en: str
    reasons: str


@dataclass(frozen=True)
class DisplaySummary:
    """A catalogue's headline figures as text.

    The averages are percentages with one decimal (``"67.7%"``), or ``"-"`` when there is
    nothing to average. ``average_price_change`` has a ``+`` sign when prices went up.
    """

    average_margin: str
    flagged_products: str
    average_price_change: str


@dataclass(frozen=True)
class OrderRow:
    """One row of an order's table, for both shipping models.

    ``label`` is the SKU, or Items, Customs fee, Duty and VAT, Total or Delivery; ``name`` is
    the product's English name and ``quantity`` its quantity, both ``""`` on the other rows.
    ``consolidated`` and ``parcel`` are money in the currency's minor units, an ISO date, or
    ``"-"`` when that model has no such amount.
    """

    label: str
    name: str
    quantity: str
    consolidated: str
    parcel: str


def _percent(fraction: Decimal) -> str:
    """A fraction as a percentage with one decimal, rounded half up (``0.5865`` -> ``58.7``)."""
    return format_money(fraction * 100, 1)


def _margin_percent(item: LocalisedProduct) -> str:
    try:
        return _percent(item.quote.margin_pct)
    except ArithmeticError as exc:
        raise LocalisationError(f"{item.sku}: margin is too large to display") from exc


def _duty_percent(item: LocalisedProduct) -> str:
    try:
        return _percent(item.quote.duty_rate)
    except ArithmeticError as exc:
        raise LocalisationError(f"{item.sku}: duty rate is too large to display") from exc


def duty_text(row: DisplayRow) -> str:
    """The Duty cell of a row: ``"waived"`` if de minimis applied, otherwise ``"5.0%"``."""
    return WAIVED if row.duty_waived else f"{row.duty_percent}%"


def display_rows(items: Sequence[LocalisedProduct]) -> list[DisplayRow]:
    """One row per localised product, in the same order.

    Raises ``LocalisationError`` naming the SKU if a margin or duty rate is too large to
    display.
    """
    return [
        DisplayRow(
            sku=item.sku,
            name_en=item.name_en,
            currency=item.quote.currency,
            shelf_price=f"{item.quote.shelf_price:f}",
            margin_percent=_margin_percent(item),
            duty_percent=_duty_percent(item),
            duty_waived=item.quote.duty_waived,
            delivery_date=item.delivery.delivery_date.isoformat(),
            flags=item.flags,
        )
        for item in items
    ]


def grid_rows(items: Sequence[LocalisedProduct]) -> list[GridRow]:
    """One grid row per localised product, in the same order.

    Built from ``display_rows``, so a grid shows exactly what the CLI prints. Raises
    ``LocalisationError`` as ``display_rows`` does.
    """
    return [
        GridRow(
            sku=row.sku,
            name_en=row.name_en,
            # The text is already rounded; Decimal(text) keeps its digits, trailing zeros too.
            shelf_price=Decimal(row.shelf_price),
            margin_percent=Decimal(row.margin_percent),
            duty=duty_text(row),
            delivery_date=row.delivery_date,
            flags=", ".join(_FLAG_LABELS.get(flag, flag) for flag in row.flags),
        )
        for row in display_rows(items)
    ]


def excluded_grid_rows(excluded: Sequence[ExcludedProduct]) -> list[ExcludedGridRow]:
    """One grid row per product not sold, in the same order, with its reasons as labels."""
    return [
        ExcludedGridRow(
            sku=item.sku,
            name_en=item.name_en,
            reasons=", ".join(ATTRIBUTE_LABELS[reason] for reason in item.reasons),
        )
        for item in excluded
    ]


def parcel_fee_note(market: MarketConfig, shipping: ShippingModel) -> str | None:
    """The sentence that names the market's parcel fee, for the CLI and the dashboard.

    ``None`` unless ``shipping`` is a direct parcel in a market with a fee. The amount has the
    currency's minor units, as prices do. Raises ``ValueError`` for an unknown ``shipping``.
    """
    fee = parcel_fee_due(market, shipping, anything_travels=True)
    if fee is None:
        return None
    amount = format_money(fee, market.currency.minor_units)
    return (
        f"Each parcel order also pays a customs fee of {amount} {market.currency.code} at checkout."
    )


def _checkout_amount(quote: OrderQuote, kind: CheckoutKind) -> str:
    for line in quote.checkout:
        if line.kind == kind:
            return format_money(line.amount, quote.minor_units)
    return _NO_VALUE


def order_rows(consolidated: OrderQuote, parcel: OrderQuote) -> list[OrderRow]:
    """The rows of an order's table: one per line the market sells, then Items, each checkout
    amount that either model adds, Total and Delivery.

    The two quotes are the same order in the same market. Raises ``ValueError`` if they are
    not.
    """
    if consolidated.market != parcel.market or [line.sku for line in consolidated.lines] != [
        line.sku for line in parcel.lines
    ]:
        raise ValueError(
            f"not the same order: {consolidated.market} and {parcel.market}, "
            f"{[line.sku for line in consolidated.lines]} and {[line.sku for line in parcel.lines]}"
        )

    def money(quote: OrderQuote, amount: Decimal) -> str:
        return format_money(amount, quote.minor_units)

    rows = [
        OrderRow(
            label=line.sku,
            name=line.name_en,
            quantity=str(line.quantity),
            consolidated=money(consolidated, line.line_total),
            parcel=money(parcel, parcel_line.line_total),
        )
        for line, parcel_line in zip(consolidated.lines, parcel.lines, strict=True)
    ]
    rows.append(
        OrderRow(
            "Items",
            "",
            "",
            money(consolidated, consolidated.items_total),
            money(parcel, parcel.items_total),
        )
    )
    for kind, label in CHECKOUT_LABELS.items():
        amounts = (_checkout_amount(consolidated, kind), _checkout_amount(parcel, kind))
        if amounts != (_NO_VALUE, _NO_VALUE):
            rows.append(OrderRow(label, "", "", *amounts))
    rows.append(
        OrderRow(
            "Total", "", "", money(consolidated, consolidated.total), money(parcel, parcel.total)
        )
    )
    rows.append(
        OrderRow(
            "Delivery",
            "",
            "",
            consolidated.delivery.delivery_date.isoformat(),
            parcel.delivery.delivery_date.isoformat(),
        )
    )
    return rows


def parcel_note(market: MarketConfig, parcel: OrderQuote) -> str:
    """One sentence on what de minimis made of an order sent as a direct parcel.

    The CIF and the threshold have the currency's minor units, as prices do.
    """
    if parcel.parcel_value is None:
        return "Direct parcel: nothing in the order travels, so no parcel is sent."
    rule = market.customs.de_minimis
    if rule is None:
        return f"Direct parcel: {market.code} has no de minimis rule, so every line pays duty."

    currency = market.currency
    value = format_money(parcel.parcel_value, currency.minor_units)
    threshold = format_money(rule.threshold, currency.minor_units)
    test = _APPLIES[rule.applies]
    cif = f"Direct parcel: the order's CIF, {value} {currency.code}"
    if parcel.within_threshold:
        return f"{cif}, is {test} {threshold} {currency.code}, so de minimis applies."
    if any(line.kind == "duty" for line in parcel.checkout):
        consequence = "the duty its shelf prices left out is added at checkout"
    else:
        consequence = "its shelf prices already include it"
    return (
        f"{cif}, is not {test} {threshold} {currency.code}, so the whole order pays duty; "
        f"{consequence}."
    )


def search_products(items: Sequence[LocalisedProduct], query: str) -> list[LocalisedProduct]:
    """The products whose SKU or English name contains ``query``, in the same order.

    The match ignores case and the spaces around ``query``, and takes it literally, not as a
    pattern. A blank ``query`` keeps every product.
    """
    wanted = query.strip().casefold()
    return [
        item for item in items if wanted in item.sku.casefold() or wanted in item.name_en.casefold()
    ]


def _average_percent(figure: str, fraction: Decimal) -> str:
    try:
        return _percent(fraction)
    except ArithmeticError as exc:
        raise LocalisationError(f"{figure} is too large to display") from exc


def display_summary(summary: CatalogueSummary) -> DisplaySummary:
    """A catalogue summary as the text of its headline figures.

    Raises ``LocalisationError`` naming the figure if an average is too large to display.
    No single product is at fault for an average, so the message names no SKU.
    """
    margin = summary.average_margin_pct
    change = summary.average_price_change_pct

    average_margin = (
        _NO_VALUE if margin is None else f"{_average_percent('average margin', margin)}%"
    )
    if change is None:
        price_change = _NO_VALUE
    else:
        percent = _average_percent("average price change", change)
        sign = "+" if Decimal(percent) > 0 else ""  # signed after rounding, so never "+0.0%"
        price_change = f"{sign}{percent}%"

    return DisplaySummary(
        average_margin=average_margin,
        flagged_products=str(summary.flagged_count),
        average_price_change=price_change,
    )
