"""Display-ready rows for a localised catalogue, shared by the CLI and the dashboard.

Formatting, and choosing which rows to show: every value comes from the engine's result
objects.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from souqsort.pipeline import (
    MISSING_ARABIC_NAME,
    CatalogueSummary,
    LocalisationError,
    LocalisedProduct,
)
from souqsort.pricing.money import format_money

_NO_VALUE = "-"

# What a grid shows for each flag. A flag with no label here is shown as its code.
_FLAG_LABELS = {MISSING_ARABIC_NAME: "No Arabic name"}


@dataclass(frozen=True)
class DisplayRow:
    """One localised product as text.

    ``shelf_price`` has exactly the currency's minor units, as the engine rounded it.
    ``margin_percent`` is a percentage with one decimal and no ``%`` sign (``"58.7"``).
    ``delivery_date`` is an ISO date.
    """

    sku: str
    name_en: str
    currency: str
    shelf_price: str
    margin_percent: str
    delivery_date: str
    flags: tuple[str, ...]


@dataclass(frozen=True)
class GridRow:
    """One localised product for a sortable grid.

    The same values as a ``DisplayRow``, but ``shelf_price`` and ``margin_percent`` are
    numbers, so a grid sorts them by value: as text, ``"111.95"`` comes before ``"16.95"``.
    Each keeps the decimals of its text. ``flags`` is one string of labels for a person to
    read (``"No Arabic name"``), empty when there are none; a ``DisplayRow`` keeps the codes.
    """

    sku: str
    name_en: str
    shelf_price: Decimal
    margin_percent: Decimal
    delivery_date: str
    flags: str


@dataclass(frozen=True)
class DisplaySummary:
    """A catalogue's headline figures as text.

    The averages are percentages with one decimal (``"67.7%"``), or ``"-"`` when there is
    nothing to average. ``average_price_change`` has a ``+`` sign when prices went up.
    """

    average_margin: str
    flagged_products: str
    average_price_change: str


def _percent(fraction: Decimal) -> str:
    """A fraction as a percentage with one decimal, rounded half up (``0.5865`` -> ``58.7``)."""
    return format_money(fraction * 100, 1)


def _margin_percent(item: LocalisedProduct) -> str:
    try:
        return _percent(item.quote.margin_pct)
    except ArithmeticError as exc:
        raise LocalisationError(f"{item.sku}: margin is too large to display") from exc


def display_rows(items: Sequence[LocalisedProduct]) -> list[DisplayRow]:
    """One row per localised product, in the same order.

    Raises ``LocalisationError`` naming the SKU if a margin is too large to display.
    """
    return [
        DisplayRow(
            sku=item.sku,
            name_en=item.name_en,
            currency=item.quote.currency,
            shelf_price=f"{item.quote.shelf_price:f}",
            margin_percent=_margin_percent(item),
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
            delivery_date=row.delivery_date,
            flags=", ".join(_FLAG_LABELS.get(flag, flag) for flag in row.flags),
        )
        for row in display_rows(items)
    ]


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
