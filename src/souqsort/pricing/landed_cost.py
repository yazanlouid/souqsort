"""Landed-cost pricing of a product for a market."""

from dataclasses import dataclass
from decimal import Decimal

from souqsort.models import FxTable, MarketConfig, Product
from souqsort.pricing.fx import convert
from souqsort.pricing.money import charm_up, require_decimal, round_minor


@dataclass(frozen=True)
class PriceStep:
    """One line of a calculation trace (filled in by a later milestone)."""

    name: str
    basis: Decimal
    rate: Decimal | None
    amount: Decimal
    source: str


@dataclass(frozen=True)
class PriceQuote:
    """A product's price in a market, in the market currency.

    ``shelf_price`` is the only rounded value and is authoritative. The components keep full
    precision and are rounded for display only, so their displayed sum can differ from it.
    ``margin_pct`` is a fraction (``0.587`` = 58.7%).
    """

    sku: str
    market: str
    currency: str
    goods: Decimal
    freight: Decimal
    duty: Decimal
    vat: Decimal
    gross: Decimal
    shelf_price: Decimal
    margin_pct: Decimal
    steps: tuple[PriceStep, ...] = ()


def price_product(
    product: Product,
    market: MarketConfig,
    fx: FxTable,
    duty_adjustment: Decimal = Decimal("0"),
) -> PriceQuote:
    """Price a product for a market, passing every cost through to the customer.

    ``duty_adjustment`` is a fraction added to the product's duty rate, whatever its category
    (``Decimal("0.03")`` = +3 percentage points). The config itself is never modified.

    Raises ``ValueError`` naming the SKU if the shelf price leaves no goods revenue.
    """
    require_decimal("duty_adjustment", duty_adjustment)
    if not duty_adjustment.is_finite() or duty_adjustment < 0:
        raise ValueError(f"duty_adjustment must be a finite fraction >= 0, got {duty_adjustment}")

    currency = market.currency
    customs = market.customs
    vat_rate = market.tax.vat_rate

    goods = convert(product.base_price, product.currency, currency.code, fx)
    freight_usd = market.logistics.freight_per_kg_usd * product.weight_kg
    freight = convert(freight_usd, "USD", currency.code, fx)
    cif = goods + freight

    category_rate = customs.category_overrides.get(product.category, customs.default_duty_rate)
    duty = cif * (category_rate + duty_adjustment)
    vat = (cif + duty) * vat_rate
    gross = cif + duty + vat

    rounded = round_minor(gross, currency.minor_units)
    shelf_price = charm_up(rounded, currency.charm_ending, currency.minor_units)

    cost_local = convert(product.unit_cost, product.currency, currency.code, fx)
    goods_revenue = shelf_price / (1 + vat_rate) - freight - duty
    if goods_revenue <= 0:
        # Only reachable when rounding to minor units swallows the goods value.
        raise ValueError(
            f"{product.sku}: shelf price {shelf_price} {currency.code} leaves no goods revenue "
            f"after VAT, freight and duty ({goods_revenue}), so it has no margin"
        )
    margin_pct = (goods_revenue - cost_local) / goods_revenue

    return PriceQuote(
        sku=product.sku,
        market=market.code,
        currency=currency.code,
        goods=goods,
        freight=freight,
        duty=duty,
        vat=vat,
        gross=gross,
        shelf_price=shelf_price,
        margin_pct=margin_pct,
    )
