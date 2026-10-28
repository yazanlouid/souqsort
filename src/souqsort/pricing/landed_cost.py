"""Landed-cost pricing of a product for a market."""

from dataclasses import dataclass
from decimal import Decimal
from typing import assert_never

from souqsort.models import FxTable, MarketConfig, Product, ShippingModel, require_shipping
from souqsort.pricing.customs import assess_duty
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
    ``cif`` is ``goods + freight`` exactly as duty and de minimis assessed it.
    ``margin_pct`` is a fraction (``0.587`` = 58.7%). ``duty_rate`` is the rate applied to
    CIF, 0 when ``duty_waived`` (de minimis applied).
    """

    sku: str
    market: str
    currency: str
    goods: Decimal
    freight: Decimal
    cif: Decimal
    duty: Decimal
    vat: Decimal
    gross: Decimal
    shelf_price: Decimal
    margin_pct: Decimal
    shipping: ShippingModel
    duty_rate: Decimal
    duty_waived: bool
    steps: tuple[PriceStep, ...] = ()


def price_product(
    product: Product,
    market: MarketConfig,
    fx: FxTable,
    duty_adjustment: Decimal = Decimal("0"),
    shipping: ShippingModel = "consolidated",
) -> PriceQuote:
    """Price a product for a market, passing every cost through to the customer.

    ``duty_adjustment`` is a fraction added to the product's duty rate, whatever its category
    (``Decimal("0.03")`` = +3 percentage points). The config itself is never modified.

    ``shipping`` is ``"consolidated"`` (freight at ``freight_per_kg_usd``, never de minimis) or
    ``"parcel"``: a one-item parcel, with freight at ``parcel_freight_per_kg_usd`` and no duty
    when the market's de minimis rule applies to its CIF.

    Raises ``ValueError`` for an unknown ``shipping``, and naming the SKU if the shelf price
    leaves no goods revenue.
    """
    require_decimal("duty_adjustment", duty_adjustment)
    if not duty_adjustment.is_finite() or duty_adjustment < 0:
        raise ValueError(f"duty_adjustment must be a finite fraction >= 0, got {duty_adjustment}")
    require_shipping(shipping)

    currency = market.currency
    logistics = market.logistics
    vat_rate = market.tax.vat_rate

    goods = convert(product.base_price, product.currency, currency.code, fx)
    # A match, not an if: mypy fails here if ShippingModel gains a value with no case.
    match shipping:
        case "consolidated":
            freight_per_kg = logistics.freight_per_kg_usd
        case "parcel":
            freight_per_kg = logistics.parcel_freight_per_kg_usd
        case unknown:
            assert_never(unknown)
    freight = convert(freight_per_kg * product.weight_kg, "USD", currency.code, fx)
    cif = goods + freight

    assessment = assess_duty(product, market, cif, duty_adjustment, shipping)
    duty = cif * assessment.rate
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
        cif=cif,
        duty=duty,
        vat=vat,
        gross=gross,
        shelf_price=shelf_price,
        margin_pct=margin_pct,
        shipping=shipping,
        duty_rate=assessment.rate,
        duty_waived=assessment.waived,
    )
