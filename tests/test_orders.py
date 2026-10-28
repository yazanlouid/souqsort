"""M16: orders of several items in one market (SPEC §7.10, worked examples I to P)."""

from dataclasses import FrozenInstanceError
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext
from itertools import permutations
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from helpers import (
    FOR_SALE_COUNTS,
    GUMMY_BEARS,
    NO_ATTRIBUTES,
    REPORT_ORDERED_AT,
    VANILLA,
    decimal_places,
)
from souqsort import orders as order_engine
from souqsort.logistics.calendar import estimate_delivery
from souqsort.models import (
    SHIPPING_MODELS,
    Catalogue,
    GccConfig,
    OrderLine,
    ParcelFee,
    Product,
    ProductName,
    SampleOrders,
    ShippingModel,
)
from souqsort.orders import (
    CheckoutKind,
    CheckoutLine,
    OrderQuote,
    OrderQuotes,
    find_sample_order,
    quote_order,
    quote_order_both_ways,
)
from souqsort.pipeline import LocalisationError, duty_adjustment_from_points
from souqsort.pricing.customs import sends_parcel
from souqsort.pricing.landed_cost import price_product
from souqsort.report import build_report

HEADPHONES = "ELEC-HP-001"
CHARGER = "ELEC-CHG-002"
BAG = "FASH-BAG-014"
ESPRESSO = "HOME-ESP-031"
SCARF = "FASH-SCF-015"
LIP_BALM = "BEAU-LIP-040"
SERUM = "BEAU-SRM-041"
LICENCE = "DIGI-LIC-050"
TEA = "GROC-TEA-060"

BELOW = "TEST-BELOW"
AT_OR_BELOW = "TEST-AT-OR-BELOW"

PLUS_3_PP = Decimal("0.03")


def _lines(*items: tuple[str, int]) -> list[OrderLine]:
    return [OrderLine(sku=sku, quantity=quantity) for sku, quantity in items]


def _quote(
    catalogue: Catalogue,
    config: GccConfig,
    market: str,
    shipping: ShippingModel,
    *items: tuple[str, int],
    duty_adjustment: Decimal = Decimal("0"),
) -> OrderQuote:
    return quote_order(
        _lines(*items), catalogue, config, market, REPORT_ORDERED_AT, duty_adjustment, shipping
    )


def _checkout(*items: tuple[CheckoutKind, str]) -> tuple[CheckoutLine, ...]:
    return tuple(CheckoutLine(kind, Decimal(amount)) for kind, amount in items)


def _cut(value: Decimal | None, places: int) -> Decimal:
    """Cut to ``places`` decimals, as the spec prints a long value followed by "..."."""
    assert value is not None
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)


def _line_totals(quote: OrderQuote) -> list[Decimal]:
    return [line.line_total for line in quote.lines]


# --- worked example I: headphones and a bag in KSA (SPEC §7.10.2) ---------------------------


def test_example_i_the_order_fails_the_test(catalogue: Catalogue, config: GccConfig) -> None:
    order = _quote(catalogue, config, "KSA", "parcel", (HEADPHONES, 1), (BAG, 1))

    assert _line_totals(order) == [Decimal("660.95"), Decimal("546.95")]
    assert all(line.quote.duty_waived for line in order.lines)
    assert order.items_total == Decimal("1207.90")
    assert _cut(order.parcel_value, 8) == Decimal("1049.26157718")
    assert order.within_threshold is False
    assert order.checkout == _checkout(("customs_fee", "15.00"), ("duty", "98.57"))
    assert order.total == Decimal("1321.47")


def test_example_i_consolidated_adds_nothing(catalogue: Catalogue, config: GccConfig) -> None:
    order = _quote(catalogue, config, "KSA", "consolidated", (HEADPHONES, 1), (BAG, 1))

    assert _line_totals(order) == [Decimal("686.95"), Decimal("594.95")]
    assert order.checkout == ()
    assert order.total == Decimal("1281.90")


def test_example_i_at_plus_three_points(catalogue: Catalogue, config: GccConfig) -> None:
    order = _quote(
        catalogue, config, "KSA", "parcel", (HEADPHONES, 1), (BAG, 1), duty_adjustment=PLUS_3_PP
    )

    # Both lines are waived, so their shelf prices stay put (§7.4).
    assert _line_totals(order) == [Decimal("660.95"), Decimal("546.95")]
    assert order.checkout == _checkout(("customs_fee", "15.00"), ("duty", "134.77"))
    assert order.total == Decimal("1357.67")


# --- J: the same order in the UAE -----------------------------------------------------------


def test_example_j_the_uae(catalogue: Catalogue, config: GccConfig) -> None:
    order = _quote(catalogue, config, "UAE", "parcel", (HEADPHONES, 1), (BAG, 1))

    assert _line_totals(order) == [Decimal("589.99"), Decimal("485.99")]
    assert order.items_total == Decimal("1075.98")
    assert _cut(order.parcel_value, 8) == Decimal("1023.35346291")
    assert order.within_threshold is False
    assert order.checkout == _checkout(("duty", "53.73"))
    assert order.total == Decimal("1129.71")

    consolidated = _quote(catalogue, config, "UAE", "consolidated", (HEADPHONES, 1), (BAG, 1))
    assert consolidated.total == Decimal("1109.98")


# --- K: two lip balms in KSA ----------------------------------------------------------------


def test_example_k_two_lip_balms(catalogue: Catalogue, config: GccConfig) -> None:
    order = _quote(catalogue, config, "KSA", "parcel", (LIP_BALM, 2))

    assert _line_totals(order) == [Decimal("31.90")]
    assert order.parcel_value == Decimal("27.525")
    assert order.within_threshold is True
    assert order.checkout == _checkout(("customs_fee", "15.00"))
    assert order.total == Decimal("46.90")

    consolidated = _quote(catalogue, config, "KSA", "consolidated", (LIP_BALM, 2))
    assert consolidated.total == Decimal("33.90")


# --- L: the cliff ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("chargers", "items", "value", "within", "checkout", "total", "consolidated"),
    [
        (6, "1079.70", "936.225", True, [("customs_fee", "15.00")], "1094.70", "1109.70"),
        (
            7,
            "1259.65",
            "1092.2625",
            False,
            [("customs_fee", "15.00"), ("duty", "62.81")],
            "1337.46",
            "1294.65",
        ),
    ],
)
def test_example_l_the_cliff(
    catalogue: Catalogue,
    config: GccConfig,
    chargers: int,
    items: str,
    value: str,
    within: bool,
    checkout: list[tuple[CheckoutKind, str]],
    total: str,
    consolidated: str,
) -> None:
    order = _quote(catalogue, config, "KSA", "parcel", (CHARGER, chargers))

    assert order.items_total == Decimal(items)
    assert order.parcel_value == Decimal(value)
    assert order.within_threshold is within
    assert order.checkout == _checkout(*checkout)
    assert order.total == Decimal(total)
    assert _quote(catalogue, config, "KSA", "consolidated", (CHARGER, chargers)).total == Decimal(
        consolidated
    )


def test_example_l_the_seventh_charger(catalogue: Catalogue, config: GccConfig) -> None:
    def added(shipping: ShippingModel) -> Decimal:
        six = _quote(catalogue, config, "KSA", shipping, (CHARGER, 6))
        seven = _quote(catalogue, config, "KSA", shipping, (CHARGER, 7))
        return seven.total - six.total

    assert added("parcel") == Decimal("242.76")
    assert added("consolidated") == Decimal("184.95")


# --- M: an excluded product in a duty-free parcel -------------------------------------------


def test_example_m_in_the_uae(catalogue: Catalogue, config: GccConfig) -> None:
    order = _quote(catalogue, config, "UAE", "parcel", (VANILLA, 1), (HEADPHONES, 1))

    vanilla, headphones = order.lines
    assert (vanilla.line_total, vanilla.quote.duty_waived) == (Decimal("57.99"), False)
    assert vanilla.quote.duty_rate == Decimal("0.05")  # already in its shelf price
    assert (headphones.line_total, headphones.quote.duty_waived) == (Decimal("589.99"), True)
    assert order.parcel_value == Decimal("613.23405")
    assert order.within_threshold is True
    assert order.checkout == ()
    assert order.total == Decimal("647.98")

    consolidated = _quote(catalogue, config, "UAE", "consolidated", (VANILLA, 1), (HEADPHONES, 1))
    assert consolidated.total == Decimal("668.98")


def test_example_m_in_ksa(catalogue: Catalogue, config: GccConfig) -> None:
    order = _quote(catalogue, config, "KSA", "parcel", (VANILLA, 1), (HEADPHONES, 1))

    assert [(p.sku, p.reasons) for p in order.not_sold] == [(VANILLA, ("contains_alcohol",))]
    assert [line.sku for line in order.lines] == [HEADPHONES]
    assert order.parcel_value == Decimal("574.275")
    assert order.checkout == _checkout(("customs_fee", "15.00"))
    assert order.total == Decimal("675.95")


# --- N: a download --------------------------------------------------------------------------


def test_example_n_the_licence_alone_sends_no_parcel(
    catalogue: Catalogue, config: GccConfig
) -> None:
    order = _quote(catalogue, config, "KSA", "parcel", (LICENCE, 1))

    assert [line.travels for line in order.lines] == [False]
    assert order.parcel_value is None
    assert order.within_threshold is None
    assert order.checkout == ()
    assert order.total == Decimal("340.95")


def test_example_n_the_licence_stays_out_of_the_parcel(
    catalogue: Catalogue, config: GccConfig
) -> None:
    order = _quote(catalogue, config, "KSA", "parcel", (LIP_BALM, 2), (LICENCE, 1))

    assert [line.travels for line in order.lines] == [True, False]
    assert order.items_total == Decimal("372.85")
    assert order.parcel_value == Decimal("27.525")
    assert order.checkout == _checkout(("customs_fee", "15.00"))
    assert order.total == Decimal("387.85")


# --- O: the threshold itself (test fixture) -------------------------------------------------


def _usd_product(sku: str, base_price: str) -> Product:
    """1 kg, and freight is 0 in the boundary markets, so its CIF there is 4 x its price."""
    return Product(
        sku=sku,
        name=ProductName(en=f"Boundary test product {sku}", ar=None),
        category="test",
        hs_code="851830",
        base_price=Decimal(base_price),
        currency="USD",
        unit_cost=Decimal("1.00"),
        weight_kg=Decimal("1"),
        attributes=NO_ATTRIBUTES,
    )


def _boundary_catalogue(*prices: str) -> Catalogue:
    products = [_usd_product(f"TEST-O-{n}", price) for n, price in enumerate(prices, start=1)]
    return Catalogue(catalogue_version="test", products=products)


@pytest.mark.parametrize(
    ("market", "prices", "within", "checkout", "total"),
    [
        (BELOW, ("125.00", "125.00"), False, [("duty", "50.00")], "1050.00"),
        (AT_OR_BELOW, ("125.00", "125.00"), True, [], "1000.00"),
        (BELOW, ("125.00", "125.01"), False, [("duty", "50.00")], "1050.04"),
        (AT_OR_BELOW, ("125.00", "125.01"), False, [("duty", "50.00")], "1050.04"),
    ],
)
def test_example_o_the_threshold_itself(
    de_minimis_boundary_config: GccConfig,
    market: str,
    prices: tuple[str, ...],
    within: bool,
    checkout: list[tuple[CheckoutKind, str]],
    total: str,
) -> None:
    catalogue = _boundary_catalogue(*prices)
    items = [(p.sku, 1) for p in catalogue.products]
    order = _quote(catalogue, de_minimis_boundary_config, market, "parcel", *items)

    assert all(line.quote.duty_waived for line in order.lines)  # each alone is under it
    expected_value = sum((Decimal(price) * 4 for price in prices), Decimal(0))
    assert order.parcel_value == expected_value
    assert order.within_threshold is within
    assert order.checkout == _checkout(*checkout)
    assert order.total == Decimal(total)


# --- P: Kuwait ------------------------------------------------------------------------------


def test_example_p_kuwait_has_no_rule_and_no_fee(catalogue: Catalogue, config: GccConfig) -> None:
    order = _quote(catalogue, config, "KWT", "parcel", (SCARF, 1), (SERUM, 1))

    assert _line_totals(order) == [Decimal("19.950"), Decimal("8.950")]
    assert _cut(order.parcel_value, 8) == Decimal("26.58702416")  # reported, decides nothing
    assert order.within_threshold is None
    assert order.checkout == ()
    assert order.total == Decimal("28.900")

    consolidated = _quote(catalogue, config, "KWT", "consolidated", (SCARF, 1), (SERUM, 1))
    assert consolidated.total == Decimal("27.900")


# --- lines, consolidated imports and delivery -----------------------------------------------


@pytest.mark.parametrize("market", ["KSA", "UAE", "KWT"])
@pytest.mark.parametrize("shipping", SHIPPING_MODELS)
def test_each_line_is_price_product_s_quote_times_its_quantity(
    catalogue: Catalogue, config: GccConfig, market: str, shipping: ShippingModel
) -> None:
    order = _quote(
        catalogue, config, market, shipping, (HEADPHONES, 3), (BAG, 2), duty_adjustment=PLUS_3_PP
    )
    products = {p.sku: p for p in catalogue.products}

    for line in order.lines:
        product = products[line.sku]
        expected = price_product(product, config.markets[market], config.fx, PLUS_3_PP, shipping)
        assert line.quote == expected
        assert line.line_total == line.quantity * expected.shelf_price
        assert line.name_en == product.name.en
    assert [(line.sku, line.quantity) for line in order.lines] == [(HEADPHONES, 3), (BAG, 2)]


@pytest.mark.parametrize("market", ["KSA", "UAE", "KWT"])
def test_a_consolidated_import_adds_nothing(
    catalogue: Catalogue, config: GccConfig, market: str
) -> None:
    # Enough headphones to cross every threshold: consolidated imports still add nothing.
    order = _quote(catalogue, config, market, "consolidated", (HEADPHONES, 9), (LIP_BALM, 2))

    assert order.checkout == ()
    assert order.parcel_value is None
    assert order.within_threshold is None
    assert order.total == order.items_total == sum(_line_totals(order), Decimal(0))


@pytest.mark.parametrize("market", ["KSA", "UAE", "KWT"])
@pytest.mark.parametrize("shipping", SHIPPING_MODELS)
def test_delivery_is_estimate_delivery_for_the_model(
    catalogue: Catalogue, config: GccConfig, market: str, shipping: ShippingModel
) -> None:
    order = _quote(catalogue, config, market, shipping, (HEADPHONES, 1))

    assert order.delivery == estimate_delivery(REPORT_ORDERED_AT, config.markets[market], shipping)
    assert (order.market, order.shipping) == (market, shipping)
    assert order.currency == config.markets[market].currency.code
    assert order.minor_units == config.markets[market].currency.minor_units


def test_lines_not_sold_keep_the_order_s_order(catalogue: Catalogue, config: GccConfig) -> None:
    order = _quote(catalogue, config, "KSA", "parcel", (GUMMY_BEARS, 1), (TEA, 3), (VANILLA, 2))

    assert [p.sku for p in order.not_sold] == [GUMMY_BEARS, VANILLA]
    assert [line.sku for line in order.lines] == [TEA]


def test_an_order_the_market_sells_nothing_of(catalogue: Catalogue, config: GccConfig) -> None:
    order = _quote(catalogue, config, "KSA", "parcel", (GUMMY_BEARS, 2))

    assert order.lines == ()
    assert [p.sku for p in order.not_sold] == [GUMMY_BEARS]
    assert order.parcel_value is None
    assert order.within_threshold is None
    assert order.checkout == ()
    assert order.total == 0
    assert order.delivery == estimate_delivery(REPORT_ORDERED_AT, config.markets["KSA"], "parcel")


def test_checkout_lines_have_the_currency_s_minor_units(
    catalogue: Catalogue, config: GccConfig
) -> None:
    # A fee written without decimals is still charged in minor units.
    ksa = config.markets["KSA"]
    fee = ParcelFee(amount=Decimal("15"), source="test fee")
    customs = ksa.customs.model_copy(update={"parcel_fee": fee})
    markets = {**config.markets, "KSA": ksa.model_copy(update={"customs": customs})}
    edited = config.model_copy(update={"markets": markets})

    order = _quote(catalogue, edited, "KSA", "parcel", (HEADPHONES, 1), (BAG, 1))

    assert order.checkout == _checkout(("customs_fee", "15.00"), ("duty", "98.57"))
    assert [decimal_places(line.amount) for line in order.checkout] == [2, 2]


def test_results_are_frozen(catalogue: Catalogue, config: GccConfig) -> None:
    order = _quote(catalogue, config, "KSA", "parcel", (HEADPHONES, 1), (BAG, 1))
    with pytest.raises(FrozenInstanceError):
        order.total = Decimal(0)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        order.lines[0].quantity = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        order.checkout[0].amount = Decimal(0)  # type: ignore[misc]


def test_every_amount_is_a_decimal(catalogue: Catalogue, config: GccConfig) -> None:
    order = _quote(catalogue, config, "KSA", "parcel", (HEADPHONES, 1), (BAG, 1))
    amounts = [
        order.items_total,
        order.total,
        order.parcel_value,
        *(line.line_total for line in order.lines),
        *(line.amount for line in order.checkout),
    ]
    assert all(type(amount) is Decimal for amount in amounts)


def test_the_parcel_value_is_exact_whatever_the_line_order(
    catalogue: Catalogue, config: GccConfig
) -> None:
    # Summed under the default 28 digits, two orders of these lines differed in the last digit.
    orders = [
        _quote(catalogue, config, "KSA", "parcel", *((sku, 7) for sku in skus))
        for skus in permutations((BAG, SCARF, ESPRESSO))
    ]
    with localcontext() as context:  # the products and their sum, with no rounding at all
        context.prec = 100
        context.traps[Inexact] = True
        expected = sum((7 * line.quote.cif for line in orders[0].lines), Decimal(0))

    assert {order.parcel_value for order in orders} == {expected}
    assert {order.checkout for order in orders} == {orders[0].checkout}
    assert [line.kind for line in orders[0].checkout] == ["customs_fee", "duty"]


def test_a_zero_rate_parcel_over_the_threshold_still_gets_a_duty_line(
    catalogue: Catalogue, config: GccConfig
) -> None:
    # The order really owes duty at 0%: the line says so, and shows a rise in the rate.
    ksa = config.markets["KSA"]
    overrides = {**ksa.customs.category_overrides, "electronics": Decimal("0.00")}
    customs = ksa.customs.model_copy(update={"category_overrides": overrides})
    markets = {**config.markets, "KSA": ksa.model_copy(update={"customs": customs})}
    edited = config.model_copy(update={"markets": markets})

    at_0 = _quote(catalogue, edited, "KSA", "parcel", (HEADPHONES, 2))
    at_5 = _quote(
        catalogue, edited, "KSA", "parcel", (HEADPHONES, 2), duty_adjustment=Decimal("0.05")
    )

    assert at_0.parcel_value == Decimal("1148.55")
    assert at_0.within_threshold is False
    assert at_0.checkout == _checkout(("customs_fee", "15.00"), ("duty", "0.00"))
    # 1,148.55 x 5% x 1.15 = 66.041625
    assert at_5.checkout == _checkout(("customs_fee", "15.00"), ("duty", "66.04"))


# --- errors ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("duty_adjustment", "error"),
    [(Decimal("-0.01"), ValueError), (Decimal("NaN"), ValueError), (0.03, TypeError)],
)
def test_a_bad_duty_adjustment_fails_first(
    catalogue: Catalogue, config: GccConfig, duty_adjustment: Any, error: type[Exception]
) -> None:
    with pytest.raises(error, match="duty_adjustment") as excinfo:
        quote_order([], catalogue, config, "XYZ", REPORT_ORDERED_AT, duty_adjustment)
    assert not isinstance(excinfo.value, LocalisationError)


def test_a_bad_shipping_model_fails_next(catalogue: Catalogue, config: GccConfig) -> None:
    with pytest.raises(ValueError, match="shipping") as excinfo:
        quote_order([], catalogue, config, "XYZ", REPORT_ORDERED_AT, Decimal(0), "bulk")  # type: ignore[arg-type]
    assert not isinstance(excinfo.value, LocalisationError)


def test_an_order_with_no_lines_rejected(catalogue: Catalogue, config: GccConfig) -> None:
    with pytest.raises(ValueError, match="at least one line") as excinfo:
        quote_order([], catalogue, config, "XYZ", REPORT_ORDERED_AT)
    assert type(excinfo.value) is ValueError


def test_a_sku_listed_twice_rejected(catalogue: Catalogue, config: GccConfig) -> None:
    lines = _lines((HEADPHONES, 1), (BAG, 1), (HEADPHONES, 2))
    with pytest.raises(ValueError, match=f"duplicate sku: {HEADPHONES}") as excinfo:
        quote_order(lines, catalogue, config, "XYZ", REPORT_ORDERED_AT)
    assert type(excinfo.value) is ValueError


def test_an_unknown_market_rejected(catalogue: Catalogue, config: GccConfig) -> None:
    lines = _lines(("ELEC-HP-999", 1))
    with pytest.raises(LocalisationError) as excinfo:
        quote_order(lines, catalogue, config, "XYZ", REPORT_ORDERED_AT)
    assert str(excinfo.value).startswith("XYZ: unknown market")


def test_a_sku_not_in_the_catalogue_rejected(catalogue: Catalogue, config: GccConfig) -> None:
    lines = _lines((HEADPHONES, 1), ("ELEC-HP-999", 1))
    with pytest.raises(LocalisationError) as excinfo:
        quote_order(lines, catalogue, config, "KSA", REPORT_ORDERED_AT)
    assert str(excinfo.value) == "ELEC-HP-999: not in the catalogue"


@pytest.mark.parametrize("items", [[(HEADPHONES, 1)], [(GUMMY_BEARS, 1)]])
def test_a_naive_order_time_rejected(
    catalogue: Catalogue, config: GccConfig, items: list[tuple[str, int]]
) -> None:
    naive = REPORT_ORDERED_AT.replace(tzinfo=None)
    with pytest.raises(LocalisationError, match="timezone-aware") as excinfo:
        quote_order(_lines(*items), catalogue, config, "KSA", naive)
    assert str(excinfo.value).startswith("KSA: ")


def test_an_order_sum_that_cannot_be_held_exactly_names_the_market(
    catalogue: Catalogue, config: GccConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(order_engine, "_EXACT_PRECISION", 5)
    with pytest.raises(LocalisationError) as excinfo:
        _quote(catalogue, config, "KSA", "parcel", (HEADPHONES, 1), (BAG, 1))
    assert str(excinfo.value) == "KSA: a value is out of range for decimal arithmetic (Inexact)"
    assert isinstance(excinfo.value.__cause__, Inexact)


def test_a_failing_delivery_estimate_names_the_market(
    catalogue: Catalogue, config: GccConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any) -> None:
        raise ValueError("no business day found")

    monkeypatch.setattr(order_engine, "estimate_delivery", fail)
    with pytest.raises(LocalisationError, match=r"^KSA: no business day found$"):
        _quote(catalogue, config, "KSA", "parcel", (HEADPHONES, 1))


# --- both shipping models, and the sample orders (SPEC §10.5, M17) ------------------------


@pytest.mark.parametrize("points", [0, 3])
def test_quote_order_both_ways_names_each_model(
    catalogue: Catalogue, config: GccConfig, points: int
) -> None:
    lines = _lines((HEADPHONES, 1), (BAG, 1))
    adjustment = duty_adjustment_from_points(points)

    both = quote_order_both_ways(lines, catalogue, config, "KSA", REPORT_ORDERED_AT, adjustment)

    assert both == OrderQuotes(
        consolidated=quote_order(
            lines, catalogue, config, "KSA", REPORT_ORDERED_AT, adjustment, "consolidated"
        ),
        parcel=quote_order(
            lines, catalogue, config, "KSA", REPORT_ORDERED_AT, adjustment, "parcel"
        ),
    )
    assert both.consolidated.shipping == "consolidated"
    assert both.parcel.shipping == "parcel"


def test_quote_order_both_ways_defaults_to_today_s_rates(
    catalogue: Catalogue, config: GccConfig
) -> None:
    both = quote_order_both_ways(
        _lines((HEADPHONES, 1), (BAG, 1)), catalogue, config, "KSA", REPORT_ORDERED_AT
    )

    assert both.consolidated.total == Decimal("1281.90")
    assert both.parcel.total == Decimal("1321.47")  # §7.10.2 example I


def test_quote_order_both_ways_raises_as_quote_order_does(
    catalogue: Catalogue, config: GccConfig
) -> None:
    with pytest.raises(LocalisationError, match=r"^QAT: unknown market"):
        quote_order_both_ways(_lines((HEADPHONES, 1)), catalogue, config, "QAT", REPORT_ORDERED_AT)
    with pytest.raises(ValueError, match="at least one line"):
        quote_order_both_ways([], catalogue, config, "KSA", REPORT_ORDERED_AT)


def test_order_quotes_are_frozen(catalogue: Catalogue, config: GccConfig) -> None:
    both = quote_order_both_ways(_lines((LIP_BALM, 2)), catalogue, config, "KSA", REPORT_ORDERED_AT)
    with pytest.raises(FrozenInstanceError):
        both.parcel = both.consolidated  # type: ignore[misc]


def test_find_sample_order(sample_orders: SampleOrders) -> None:
    order = find_sample_order(sample_orders, "headphones-and-bag")

    assert order.name == "Headphones and a bag"
    assert order is sample_orders.orders[2]


@pytest.mark.parametrize("order_id", ["lip-balm", "Two-lip-balms", "", "two-lip-balms "])
def test_an_unknown_sample_order_lists_the_sample_orders(
    sample_orders: SampleOrders, order_id: str
) -> None:
    with pytest.raises(LocalisationError) as caught:
        find_sample_order(sample_orders, order_id)

    assert str(caught.value) == (
        f"{order_id}: unknown order; sample orders: two-lip-balms, scarf-and-serum, "
        "headphones-and-bag"
    )


def test_an_unknown_sample_order_when_there_are_none() -> None:
    no_orders = SampleOrders(orders_version="none", orders=())

    with pytest.raises(LocalisationError, match=r"^lip-balm: unknown order; sample orders: none$"):
        find_sample_order(no_orders, "lip-balm")


# --- properties (Hypothesis over the sample data) -------------------------------------------

Scenario = tuple[list[OrderLine], str, ShippingModel, Decimal]


def _scenarios(catalogue: Catalogue, config: GccConfig) -> st.SearchStrategy[Scenario]:
    """1 to 4 different products, 1 to 9 of each, any market and model, 0 to 20 pp."""
    skus = [p.sku for p in catalogue.products]
    lines = st.lists(st.sampled_from(skus), min_size=1, max_size=4, unique=True).flatmap(
        lambda chosen: st.lists(
            st.integers(min_value=1, max_value=9), min_size=len(chosen), max_size=len(chosen)
        ).map(lambda quantities: _lines(*zip(chosen, quantities, strict=True)))
    )
    return st.tuples(
        lines,
        st.sampled_from(list(config.markets)),
        st.sampled_from(SHIPPING_MODELS),
        st.integers(min_value=0, max_value=20).map(duty_adjustment_from_points),
    )


def _order(
    catalogue: Catalogue,
    config: GccConfig,
    lines: list[OrderLine],
    market: str,
    shipping: ShippingModel,
    adjustment: Decimal,
) -> OrderQuote:
    return quote_order(lines, catalogue, config, market, REPORT_ORDERED_AT, adjustment, shipping)


@given(data=st.data())
def test_the_total_is_never_below_the_line_totals(
    catalogue: Catalogue, config: GccConfig, data: st.DataObject
) -> None:
    lines, market, shipping, adjustment = data.draw(_scenarios(catalogue, config))
    order = _order(catalogue, config, lines, market, shipping, adjustment)

    assert order.items_total == sum(_line_totals(order), Decimal(0))
    assert order.total >= order.items_total
    if shipping == "consolidated":
        assert order.total == order.items_total


@given(data=st.data())
def test_the_order_of_the_lines_changes_nothing_that_is_charged(
    catalogue: Catalogue, config: GccConfig, data: st.DataObject
) -> None:
    lines, market, shipping, adjustment = data.draw(_scenarios(catalogue, config))
    shuffled = data.draw(st.permutations(lines))
    order = _order(catalogue, config, lines, market, shipping, adjustment)
    other = _order(catalogue, config, shuffled, market, shipping, adjustment)

    assert other.total == order.total
    assert other.checkout == order.checkout
    assert other.parcel_value == order.parcel_value
    assert other.within_threshold is order.within_threshold


@given(data=st.data())
def test_one_more_unit_never_lowers_the_total(
    catalogue: Catalogue, config: GccConfig, data: st.DataObject
) -> None:
    lines, market, shipping, adjustment = data.draw(_scenarios(catalogue, config))
    index = data.draw(st.integers(min_value=0, max_value=len(lines) - 1))
    more = list(lines)
    more[index] = OrderLine(sku=lines[index].sku, quantity=lines[index].quantity + 1)

    before = _order(catalogue, config, lines, market, shipping, adjustment)
    after = _order(catalogue, config, more, market, shipping, adjustment)

    assert after.total >= before.total


@given(data=st.data())
def test_a_one_item_order_adds_at_most_the_fee(
    catalogue: Catalogue, config: GccConfig, data: st.DataObject
) -> None:
    sku = data.draw(st.sampled_from([p.sku for p in catalogue.products]))
    market = data.draw(st.sampled_from(list(config.markets)))
    shipping = data.draw(st.sampled_from(SHIPPING_MODELS))
    adjustment = data.draw(st.integers(min_value=0, max_value=20).map(duty_adjustment_from_points))

    order = _order(catalogue, config, _lines((sku, 1)), market, shipping, adjustment)

    assert [line.kind for line in order.checkout] in ([], ["customs_fee"])
    fee = config.markets[market].customs.parcel_fee
    assert order.total - order.items_total <= (fee.amount if fee is not None else 0)


@given(data=st.data())
def test_a_duty_line_appears_only_when_the_parcel_fails_the_test(
    catalogue: Catalogue, config: GccConfig, data: st.DataObject
) -> None:
    lines, market, shipping, adjustment = data.draw(_scenarios(catalogue, config))
    order = _order(catalogue, config, lines, market, shipping, adjustment)

    if any(line.kind == "duty" for line in order.checkout):
        assert order.within_threshold is False
    # The fee and the parcel value follow the same decision.
    sent = sends_parcel(shipping, any(line.travels for line in order.lines))
    assert (order.parcel_value is not None) is sent
    if any(line.kind == "customs_fee" for line in order.checkout):
        assert sent
    assert [line.kind for line in order.checkout] in (
        [],
        ["customs_fee"],
        ["duty"],
        ["customs_fee", "duty"],
    )


# --- the report agrees (SPEC §9.2.2) --------------------------------------------------------


def test_one_item_orders_match_the_report(catalogue: Catalogue, config: GccConfig) -> None:
    report = build_report(catalogue, config, REPORT_ORDERED_AT)

    counts = {market.code: len(market.products) for market in report.shipping}
    assert counts == FOR_SALE_COUNTS
    for market in report.shipping:
        for product in market.products:
            line = _lines((product.sku, 1))
            consolidated, parcel = (
                quote_order(line, catalogue, config, market.code, REPORT_ORDERED_AT, shipping=model)
                for model in ("consolidated", "parcel")
            )
            where = (market.code, product.sku)
            assert consolidated.total == product.consolidated_price, where
            assert parcel.total == product.parcel_order, where
