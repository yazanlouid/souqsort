"""Price an order of several items in one market (SPEC §7.10).

Shelf prices never depend on what else is in the order: what an order changes is added at
checkout, as the customs fee and the duty that de minimis no longer waives.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, Inexact, localcontext
from typing import Literal

from souqsort.compliance import ExcludedProduct, screen_products
from souqsort.logistics.calendar import DeliveryEstimate, estimate_delivery
from souqsort.models import (
    Catalogue,
    GccConfig,
    MarketConfig,
    OrderLine,
    Product,
    SampleOrder,
    SampleOrders,
    ShippingModel,
    require_shipping,
)
from souqsort.pipeline import (
    LocalisationError,
    find_market,
    localisation_error,
    localise_catalogue,
    require_duty_adjustment,
)
from souqsort.pricing.customs import (
    duty_rate,
    parcel_fee_due,
    sends_parcel,
    travels,
    within_threshold,
)
from souqsort.pricing.landed_cost import PriceQuote
from souqsort.pricing.money import round_minor

CheckoutKind = Literal["customs_fee", "duty"]

# Digits for an order's products and sums, so that they never round: a line's cif has at most
# the default context's 28 digits and its quantity two, and every figure is far below 10**26.
# Inexact is trapped, so a figure that does not fit raises rather than rounding.
_EXACT_PRECISION = 100


@dataclass(frozen=True)
class CheckoutLine:
    """An amount the order adds at checkout, rounded once to the currency's minor units."""

    kind: CheckoutKind
    amount: Decimal


@dataclass(frozen=True)
class QuotedLine:
    """A line the market sells. ``quote`` is exactly ``price_product``'s, and ``line_total``
    is ``quantity * quote.shelf_price``, exact. ``travels`` says whether it goes in a parcel.
    """

    sku: str
    name_en: str
    quantity: int
    quote: PriceQuote
    line_total: Decimal
    travels: bool


@dataclass(frozen=True)
class OrderQuote:
    """An order priced in one market, for one shipping model, duty adjustment and order time.

    ``lines`` are the lines the market sells and ``not_sold`` the rest, with their reasons,
    each in the order's order. ``parcel_value`` is the full-precision CIF of the lines that
    travel, or ``None`` when no parcel is sent. ``within_threshold`` is the de minimis test of
    that value, or ``None`` without a parcel or a rule. ``checkout`` holds the customs fee,
    then the duty.
    """

    market: str
    currency: str
    minor_units: int
    shipping: ShippingModel
    lines: tuple[QuotedLine, ...]
    not_sold: tuple[ExcludedProduct, ...]
    parcel_value: Decimal | None
    within_threshold: bool | None
    checkout: tuple[CheckoutLine, ...]
    delivery: DeliveryEstimate

    @property
    def items_total(self) -> Decimal:
        """The sum of the line totals, exact."""
        return sum((line.line_total for line in self.lines), Decimal(0))

    @property
    def total(self) -> Decimal:
        """The line totals plus the checkout lines, exact."""
        return self.items_total + sum((line.amount for line in self.checkout), Decimal(0))

    def checkout_amount(self, kind: CheckoutKind) -> Decimal | None:
        """What the order adds at checkout as ``kind``, or ``None`` when it adds no such line.

        An order has at most one checkout line of each kind.
        """
        return next((line.amount for line in self.checkout if line.kind == kind), None)


def _require_lines(lines: Sequence[OrderLine]) -> None:
    if not lines:
        raise ValueError("an order needs at least one line")
    counts = Counter(line.sku for line in lines)
    duplicates = sorted(sku for sku, n in counts.items() if n > 1)
    if duplicates:
        raise ValueError(f"duplicate sku: {', '.join(duplicates)}")


@dataclass(frozen=True)
class _ParcelFigures:
    value: Decimal | None
    within_threshold: bool | None
    duty: Decimal | None  # with its VAT, before rounding; None when none is added


def _parcel_figures(
    quoted: Sequence[QuotedLine],
    products: dict[str, Product],
    market: MarketConfig,
    duty_adjustment: Decimal,
    sent: bool,
) -> _ParcelFigures:
    """The parcel's value, its de minimis test and the duty it adds, all exact.

    Each line's ``cif`` is the stored value that decided its waiver; only the products and
    sums over the lines run with ``_EXACT_PRECISION``. Rounded under the default context, a
    sum's last digit would depend on the order of the lines.
    """
    if not sent:
        return _ParcelFigures(value=None, within_threshold=None, duty=None)
    rule = market.customs.de_minimis
    waived = [line for line in quoted if line.quote.duty_waived]
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        context.traps[Inexact] = True
        value = sum((line.quantity * line.quote.cif for line in quoted if line.travels), Decimal(0))
        passes = None if rule is None else within_threshold(value, rule)
        duty = None
        if passes is False and waived:
            lost = sum(
                (
                    line.quantity
                    * line.quote.cif
                    * duty_rate(products[line.sku], market, duty_adjustment)
                    for line in waived
                ),
                Decimal(0),
            )
            duty = lost * (1 + market.tax.vat_rate)
    return _ParcelFigures(value=value, within_threshold=passes, duty=duty)


def quote_order(
    lines: Sequence[OrderLine],
    catalogue: Catalogue,
    config: GccConfig,
    market_code: str,
    ordered_at: datetime,
    duty_adjustment: Decimal = Decimal("0"),
    shipping: ShippingModel = "consolidated",
) -> OrderQuote:
    """Price an order in a market, following SPEC §7.10.1.

    A line whose product the market does not allow is never priced: it is reported in
    ``not_sold``. Every other line is priced as ``price_product`` prices its product. A
    direct parcel holds the lines that travel; de minimis tests their CIF once for the whole
    order, and when it fails, the duty the waived lines' shelf prices left out is added at
    checkout with the VAT on it. A parcel pays the market's customs fee.

    Checks ``duty_adjustment`` and ``shipping`` first, as ``localise_catalogue`` does. Then
    raises ``ValueError`` for no lines or a SKU listed twice. Then ``LocalisationError`` for an
    unknown market, for a SKU that is not in the catalogue, as ``localise_catalogue`` raises it
    (a naive ``ordered_at``, or a line that cannot be priced), or naming the market when the
    delivery date or the order's own figures cannot be worked out.
    """
    require_duty_adjustment(duty_adjustment)
    require_shipping(shipping)
    _require_lines(lines)
    market = find_market(config, market_code)

    products = {product.sku: product for product in catalogue.products}
    for line in lines:
        if line.sku not in products:
            raise LocalisationError(f"{line.sku}: not in the catalogue")
    quantities = {line.sku: line.quantity for line in lines}

    screen = screen_products([products[line.sku] for line in lines], market)
    localised = localise_catalogue(
        screen.sellable, config, market.code, ordered_at, duty_adjustment, shipping
    )

    quoted = tuple(
        QuotedLine(
            sku=item.sku,
            name_en=item.name_en,
            quantity=quantities[item.sku],
            quote=item.quote,
            line_total=quantities[item.sku] * item.quote.shelf_price,
            travels=travels(products[item.sku]),
        )
        for item in localised
    )

    anything_travels = any(line.travels for line in quoted)
    sent = sends_parcel(shipping, anything_travels)
    minor_units = market.currency.minor_units
    try:
        delivery = estimate_delivery(ordered_at, market, shipping)
        parcel = _parcel_figures(quoted, products, market, duty_adjustment, sent)
        checkout: list[CheckoutLine] = []
        fee = parcel_fee_due(market, shipping, anything_travels)
        if fee is not None:
            checkout.append(CheckoutLine("customs_fee", round_minor(fee, minor_units)))
        if parcel.duty is not None:
            checkout.append(CheckoutLine("duty", round_minor(parcel.duty, minor_units)))
    except (ValueError, ArithmeticError) as exc:
        raise localisation_error(market.code, exc) from exc

    return OrderQuote(
        market=market.code,
        currency=market.currency.code,
        minor_units=minor_units,
        shipping=shipping,
        lines=quoted,
        not_sold=screen.excluded,
        parcel_value=parcel.value,
        within_threshold=parcel.within_threshold,
        checkout=tuple(checkout),
        delivery=delivery,
    )


@dataclass(frozen=True)
class OrderQuotes:
    """The same order priced as a consolidated import and as a direct parcel."""

    consolidated: OrderQuote
    parcel: OrderQuote


def quote_order_both_ways(
    lines: Sequence[OrderLine],
    catalogue: Catalogue,
    config: GccConfig,
    market_code: str,
    ordered_at: datetime,
    duty_adjustment: Decimal = Decimal("0"),
) -> OrderQuotes:
    """Price an order in both shipping models, each named, so no caller depends on the order
    of ``SHIPPING_MODELS``. Raises as ``quote_order`` does.
    """
    return OrderQuotes(
        consolidated=quote_order(
            lines, catalogue, config, market_code, ordered_at, duty_adjustment, "consolidated"
        ),
        parcel=quote_order(
            lines, catalogue, config, market_code, ordered_at, duty_adjustment, "parcel"
        ),
    )


def find_sample_order(sample_orders: SampleOrders, order_id: str) -> SampleOrder:
    """A sample order, looked up by its exact id.

    Raises ``LocalisationError`` listing the sample orders' ids, in file order, if no order
    has that id.
    """
    for order in sample_orders.orders:
        if order.id == order_id:
            return order
    known = ", ".join(order.id for order in sample_orders.orders) or "none"
    raise LocalisationError(f"{order_id}: unknown order; sample orders: {known}")
