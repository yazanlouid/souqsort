"""Helpers shared by the test modules."""

from datetime import UTC, datetime
from decimal import Decimal

from souqsort.models import Catalogue, OrderLine, ProductAttributes, SampleOrder, SampleOrders

SAMPLE_PRODUCT_COUNT = 13  # products in data/raw/global_products.json

# No sample orders, for a report built from a catalogue that lacks some of their products.
NO_ORDERS = SampleOrders(orders_version="none", orders=())

# Sample products each market sells after compliance screening (SPEC §7.6).
FOR_SALE_COUNTS = {"KSA": 11, "UAE": 12, "KWT": 11}

# Attributes for a product built in a test, when none of them matters.
NO_ATTRIBUTES = ProductAttributes(
    contains_alcohol=False, contains_pork=False, contains_lithium_battery=False
)


def decimal_places(value: Decimal) -> int:
    """Decimal places the value carries; ``Decimal("9.9") == Decimal("9.90")`` hides them."""
    exponent = value.as_tuple().exponent
    assert isinstance(exponent, int)
    return -exponent


# The sample report's order (SPEC §9.5): 12:00 in Riyadh and Kuwait, 13:00 in Dubai.
REPORT_ORDERED_AT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)

VANILLA = "GROC-VAN-061"  # contains alcohol: KSA and KWT do not sell it
GUMMY_BEARS = "GROC-GUM-062"  # contains pork: no market sells it


def only_products(catalogue: Catalogue, *skus: str) -> Catalogue:
    """The catalogue with only the products named, in catalogue order."""
    wanted = set(skus)
    return catalogue.model_copy(
        update={"products": [p for p in catalogue.products if p.sku in wanted]}
    )


def without_products(catalogue: Catalogue, *skus: str) -> Catalogue:
    """The catalogue without the products named."""
    unwanted = set(skus)
    return catalogue.model_copy(
        update={"products": [p for p in catalogue.products if p.sku not in unwanted]}
    )


def add_order(
    sample_orders: SampleOrders, order_id: str, name: str, *lines: tuple[str, int]
) -> SampleOrders:
    """The sample orders with one more order at the end, of ``(sku, quantity)`` lines."""
    extra = SampleOrder(
        id=order_id,
        name=name,
        lines=tuple(OrderLine(sku=sku, quantity=quantity) for sku, quantity in lines),
    )
    return sample_orders.model_copy(update={"orders": (*sample_orders.orders, extra)})
