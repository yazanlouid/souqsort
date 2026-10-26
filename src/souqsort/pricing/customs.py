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
    # A match, not a dict: mypy fails here if DeMinimisApplies gains a value with no case.
    match rule.applies:
        case "below":
            return cif < rule.threshold
        case "at_or_below":
            return cif <= rule.threshold
        case unknown:
            assert_never(unknown)


def parcel_fee_due(
    market: MarketConfig, shipping: ShippingModel, anything_travels: bool
) -> Decimal | None:
    """The customs fee an order pays at checkout, as the config writes it, or ``None``.

    Only a direct parcel pays it, and only when something in the order travels: otherwise no
    parcel is sent. A market without a fee charges none. No VAT is charged on it. Raises
    ``ValueError`` for an unknown ``shipping``.
    """
    require_shipping(shipping)
    match shipping:
        case "consolidated":
            return None
        case "parcel":
            fee = market.customs.parcel_fee
            return fee.amount if anything_travels and fee is not None else None
        case unknown:
            assert_never(unknown)


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
    category_rate = customs.category_overrides.get(product.category, customs.default_duty_rate)
    return DutyAssessment(rate=category_rate + duty_adjustment, waived=False)
