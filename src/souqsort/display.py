"""Display-ready rows for a localised catalogue, shared by the CLI and the dashboard.

Formatting only: every value comes from the engine's result objects.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from souqsort.pipeline import LocalisationError, LocalisedProduct
from souqsort.pricing.money import format_money


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


def _margin_percent(item: LocalisedProduct) -> str:
    try:
        return format_money(item.quote.margin_pct * 100, 1)
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
