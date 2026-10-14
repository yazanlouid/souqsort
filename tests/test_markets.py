"""M8: every market's price list and delivery dates (SPEC §7.9.1 and §8.2).

Each market adds its own column to ``PRICE_LISTS`` and its own cells to ``DELIVERY_CELLS``;
the tests below run over every market listed, and fail if a configured market has none.
"""

from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

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
    "UAE": {
        "ELEC-HP-001": "612.99",
        "ELEC-CHG-002": "164.99",
        "FASH-BAG-014": "496.99",
        "FASH-SCF-015": "246.99",
        "SPRT-KTB-020": "498.99",
        "HOME-KTL-030": "209.99",
        "HOME-ESP-031": "3685.99",
        "BEAU-LIP-040": "14.99",
        "BEAU-SRM-041": "99.99",
        "DIGI-LIC-050": "304.99",
        "GROC-TEA-060": "29.99",
        "GROC-VAN-061": "55.99",
        "GROC-GUM-062": "19.99",
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
    "UAE": (
        (date(2026, 10, 15), date(2026, 10, 21)),  # Thu 13:30, shorter last mile
        (date(2026, 10, 15), date(2026, 10, 21)),  # Thu 14:30, before the 15:00 cutoff
        (date(2026, 10, 16), date(2026, 10, 22)),  # Fri 11:00, a UAE business day
        (date(2026, 12, 1), date(2026, 12, 9)),  # National Day, Wed 2 and Thu 3
        (date(2027, 2, 24), date(2027, 3, 2)),
        (date(2027, 3, 8), date(2027, 3, 17)),  # Eid, Tue 9 to Thu 11
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


# --- UAE (SPEC §6.2 and §7.8) --------------------------------------------------------------


def _dp(value: Decimal, places: int) -> Decimal:
    """Round for comparison with the spec tables, which show a fixed number of decimals."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def test_config_loads_the_uae(config: GccConfig) -> None:
    uae = config.markets["UAE"]

    assert uae.code == "UAE"
    assert uae.name == "United Arab Emirates"
    assert (uae.currency.code, uae.currency.minor_units) == ("AED", 2)
    assert uae.currency.charm_ending == Decimal("0.99")
    assert uae.tax.vat_rate == Decimal("0.05")
    assert uae.tax.effective_from == date(2018, 1, 1)
    assert uae.customs.default_duty_rate == Decimal("0.05")
    assert uae.customs.category_overrides == {"digital": Decimal("0.00")}
    assert uae.calendar.timezone == "Asia/Dubai"
    assert uae.calendar.weekend == ("SAT", "SUN")
    assert uae.calendar.order_cutoff_local == time(15, 0)
    assert [(h.date, h.name, h.provisional) for h in uae.calendar.holidays] == [
        (date(2026, 12, 2), "National Day", False),
        (date(2026, 12, 3), "National Day", False),
        (date(2027, 1, 1), "New Year's Day", False),
        (date(2027, 3, 9), "Eid al-Fitr", True),
        (date(2027, 3, 10), "Eid al-Fitr", True),
        (date(2027, 3, 11), "Eid al-Fitr", True),
    ]
    assert uae.logistics.freight_per_kg_usd == Decimal("4.00")
    assert (uae.logistics.linehaul_business_days, uae.logistics.last_mile_business_days) == (3, 1)
    assert config.fx.per_usd["AED"] == Decimal("3.6725")


def test_worked_example_c_headphones_in_the_uae(catalogue: Catalogue, config: GccConfig) -> None:
    product = next(product for product in catalogue.products if product.sku == "ELEC-HP-001")

    quote = price_product(product, config.markets["UAE"], config.fx)

    assert (quote.market, quote.currency) == ("UAE", "AED")
    assert quote.goods == Decimal("550.838275")
    assert quote.freight == Decimal("5.1415")
    assert quote.goods + quote.freight == Decimal("555.979775")  # cif
    assert quote.duty == Decimal("27.79898875")
    assert quote.vat == Decimal("29.1889381875")
    assert quote.gross == Decimal("612.9677019375")
    assert str(quote.shelf_price) == "612.99"
    assert _dp(quote.margin_pct, 3) == Decimal("0.587")
