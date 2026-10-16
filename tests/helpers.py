"""Helpers shared by the test modules."""

from decimal import Decimal

from souqsort.models import ProductAttributes

SAMPLE_PRODUCT_COUNT = 13  # products in data/raw/global_products.json

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
