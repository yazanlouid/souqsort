"""M8: every market's price list (SPEC §7.9.1).

Each market adds its own column to ``PRICE_LISTS``; the tests below run over every market
listed, and fail if a configured market has no column.
"""

import pytest

from helpers import SAMPLE_PRODUCT_COUNT
from souqsort.models import Catalogue, GccConfig
from souqsort.pricing.landed_cost import price_product

# SPEC §7.9.1: consolidated shelf prices with no duty adjustment, in catalogue order, exactly
# as printed. A † in the spec (not sold from M9 on) does not matter here: price_product prices
# every product it is given.
PRICE_LISTS: dict[str, dict[str, str]] = {
    "KSA": {
        "ELEC-HP-001": "686.95",
        "ELEC-CHG-002": "184.95",
        "FASH-BAG-014": "594.95",
        "FASH-SCF-015": "293.95",
        "SPRT-KTB-020": "593.95",
        "HOME-KTL-030": "237.95",
        "HOME-ESP-031": "4144.95",
        "BEAU-LIP-040": "16.95",
        "BEAU-SRM-041": "111.95",
        "DIGI-LIC-050": "340.95",
        "GROC-TEA-060": "34.95",
        "GROC-VAN-061": "61.95",
        "GROC-GUM-062": "22.95",
    },
}

PRICE_CELLS = [
    pytest.param(market, sku, shelf_price, id=f"{market}-{sku}")
    for market, column in PRICE_LISTS.items()
    for sku, shelf_price in column.items()
]


def test_every_market_has_a_price_list(config: GccConfig) -> None:
    assert set(PRICE_LISTS) == set(config.markets)


@pytest.mark.parametrize("market", list(PRICE_LISTS))
def test_price_list_covers_the_catalogue_in_order(catalogue: Catalogue, market: str) -> None:
    column = PRICE_LISTS[market]

    assert list(column) == [product.sku for product in catalogue.products]
    assert len(column) == SAMPLE_PRODUCT_COUNT


@pytest.mark.parametrize(("market", "sku", "shelf_price"), PRICE_CELLS)
def test_consolidated_price_list(
    catalogue: Catalogue, config: GccConfig, market: str, sku: str, shelf_price: str
) -> None:
    product = next(product for product in catalogue.products if product.sku == sku)

    quote = price_product(product, config.markets[market], config.fx)

    # Compared as text, so the number of decimals (the currency's minor units) counts too.
    assert str(quote.shelf_price) == shelf_price
