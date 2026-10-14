"""Helpers shared by the test modules."""

from decimal import Decimal

SAMPLE_PRODUCT_COUNT = 13  # products in data/raw/global_products.json


def decimal_places(value: Decimal) -> int:
    """Decimal places the value carries; ``Decimal("9.9") == Decimal("9.90")`` hides them."""
    exponent = value.as_tuple().exponent
    assert isinstance(exponent, int)
    return -exponent
