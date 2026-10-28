"""Customs: the duty rate a product pays, when de minimis waives it, and the parcel fee."""

from dataclasses import dataclass
from decimal import Decimal
from typing import assert_never

from souqsort.models import (
    DeMinimisRule,
    MarketConfig,
    Product,
    ProductAttributes,
    ShippingModel,
    require_shipping,
)


@dataclass(frozen=True)
class DutyAssessment:
    """The duty rate applied to CIF, and whether de minimis waived the duty.

    ``rate`` is 0 when ``waived``. A product whose category is already duty-free is not
    ``waived`` unless de minimis applied to it.
    """

    rate: Decimal
    waived: bool


def travels(product: Product) -> bool:
    """Whether the product goes in a parcel: it weighs more than 0 kg.

    A product that weighs nothing, such as a download, never travels, so de minimis never
    applies to it.
    """
    return product.weight_kg > 0


def within_threshold(value: Decimal, rule: DeMinimisRule) -> bool:
    """Whether a full-precision value passes the rule's own test, ``below`` or ``at_or_below``.

    It tests the value only: the rule's excluded attributes are about products, and
    ``de_minimis_applies`` checks them.
    """
    # A match, not a dict: mypy fails here if DeMinimisApplies gains a value with no case.
    match rule.applies:
        case "below":
            return value < rule.threshold
        case "at_or_below":
            return value <= rule.threshold
        case unknown:
            assert_never(unknown)


def de_minimis_applies(
    cif: Decimal, rule: DeMinimisRule | None, attributes: ProductAttributes
) -> bool:
    """Whether a one-item parcel with this full-precision CIF is under the rule's threshold.

    Never when there is no rule, or when one of the product's true attributes is excluded.
    """
    if rule is None:
        return False
    if any(attributes.has(name) for name in rule.excluded_attributes):
        return False
    return within_threshold(cif, rule)


def duty_rate(product: Product, market: MarketConfig, duty_adjustment: Decimal) -> Decimal:
    """The rate a product pays when de minimis does not waive its duty.

    Its category's rate, or the market default, plus ``duty_adjustment``.
    """
    customs = market.customs
    category_rate = customs.category_overrides.get(product.category, customs.default_duty_rate)
    return category_rate + duty_adjustment


def sends_parcel(shipping: ShippingModel, anything_travels: bool) -> bool:
    """Whether an order is sent as a parcel: a direct parcel in which something travels.

    A consolidated import sends none, and neither does a direct parcel order in which nothing
    travels. Raises ``ValueError`` for an unknown ``shipping``.
    """
    require_shipping(shipping)
    # A match, not a comparison: mypy fails here if ShippingModel gains a value with no case.
    match shipping:
        case "consolidated":
            return False
        case "parcel":
            return anything_travels
        case unknown:
            assert_never(unknown)


def parcel_fee_due(
    market: MarketConfig, shipping: ShippingModel, anything_travels: bool
) -> Decimal | None:
    """The customs fee an order pays at checkout, as the config writes it, or ``None``.

    Only an order that ``sends_parcel`` pays it. A market without a fee charges none. No VAT
    is charged on it. Raises ``ValueError`` for an unknown ``shipping``.
    """
    fee = market.customs.parcel_fee
    if fee is None or not sends_parcel(shipping, anything_travels):
        return None
    return fee.amount


def assess_duty(
    product: Product,
    market: MarketConfig,
    cif: Decimal,
    duty_adjustment: Decimal,
    shipping: ShippingModel,
) -> DutyAssessment:
    """The duty rate for a product's CIF in the market currency.

    A consolidated import always pays its category rate plus ``duty_adjustment``. A direct
    parcel pays nothing when the product travels and de minimis applies, whatever the
    adjustment; otherwise the same. Raises ``ValueError`` for an unknown ``shipping``.
    """
    require_shipping(shipping)
    customs = market.customs
    match shipping:
        case "consolidated":
            waived = False
        case "parcel":
            waived = travels(product) and de_minimis_applies(
                cif, customs.de_minimis, product.attributes
            )
        case unknown:
            assert_never(unknown)
    if waived:
        return DutyAssessment(rate=Decimal(0), waived=True)
    return DutyAssessment(rate=duty_rate(product, market, duty_adjustment), waived=False)
