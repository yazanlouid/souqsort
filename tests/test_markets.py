"""M8: every market's price list and delivery dates (SPEC §7.9.1 and §8.2).

Each market adds its own column to ``PRICE_LISTS`` and its own cells to ``DELIVERY_CELLS``;
the tests below run over every market listed, and fail if a configured market has none.
"""

from datetime import UTC, date, datetime

import pytest

from helpers import SAMPLE_PRODUCT_COUNT
from souqsort.logistics.calendar import estimate_delivery
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


# SPEC §8.2: the same six moments in every market.
ORDER_TIMES = (
    datetime(2026, 10, 15, 9, 30, tzinfo=UTC),  # the UAE's shorter last mile
    datetime(2026, 10, 15, 10, 30, tzinfo=UTC),  # Kuwait's earlier cutoff
    datetime(2026, 10, 16, 7, 0, tzinfo=UTC),  # the UAE works on Fridays
    datetime(2026, 12, 1, 8, 0, tzinfo=UTC),  # UAE National Day, 2-3 Dec
    datetime(2027, 2, 24, 7, 0, tzinfo=UTC),  # Kuwait's National and Liberation Days
    datetime(2027, 3, 8, 7, 0, tzinfo=UTC),  # Eid al-Fitr (provisional)
)

# Each cell: (dispatch, delivery), one per order time above.
DELIVERY_CELLS: dict[str, tuple[tuple[date, date], ...]] = {
    "KSA": (
        (date(2026, 10, 15), date(2026, 10, 22)),  # Thu 12:30
        (date(2026, 10, 15), date(2026, 10, 22)),  # Thu 13:30, SPEC §8.1 row 3
        (date(2026, 10, 18), date(2026, 10, 25)),  # Fri 10:00, weekend
        (date(2026, 12, 1), date(2026, 12, 8)),
        (date(2027, 2, 24), date(2027, 3, 3)),
        (date(2027, 3, 8), date(2027, 3, 18)),  # Eid, Tue 9 to Thu 11
    ),
}

DELIVERY_PARAMS = [
    pytest.param(market, ordered_at, dispatch, delivery, id=f"{market}-{ordered_at:%Y-%m-%dT%H:%M}")
    for market, cells in DELIVERY_CELLS.items()
    for ordered_at, (dispatch, delivery) in zip(ORDER_TIMES, cells, strict=True)
]


def test_every_market_has_delivery_cells(config: GccConfig) -> None:
    assert set(DELIVERY_CELLS) == set(config.markets)


@pytest.mark.parametrize(("market", "ordered_at", "dispatch", "delivery"), DELIVERY_PARAMS)
def test_delivery_cells(
    config: GccConfig, market: str, ordered_at: datetime, dispatch: date, delivery: date
) -> None:
    estimate = estimate_delivery(ordered_at, config.markets[market])

    assert (estimate.dispatch_date, estimate.delivery_date) == (dispatch, delivery)
