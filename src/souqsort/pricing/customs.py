"""Customs duty: the rate a product pays, and when de minimis waives it."""

from dataclasses import dataclass
from decimal import Decimal
from typing import assert_never, get_args

from souqsort.models import DeMinimisRule, MarketConfig, Product, ProductAttributes, ShippingModel

SHIPPING_MODELS: tuple[ShippingModel, ...] = get_args(ShippingModel)


@dataclass(frozen=True)
class DutyAssessment:
    """The duty rate applied to CIF, and whether de minimis waived the duty.

    ``rate`` is 0 when ``waived``. A product whose category is already duty-free is not
    ``waived`` unless de minimis applied to it.
    """

    rate: Decimal
    waived: bool


def require_shipping(shipping: object) -> None:
    """Raise ``ValueError`` unless ``shipping`` is one of ``ShippingModel``'s values."""
    if shipping not in SHIPPING_MODELS:
        allowed = ", ".join(SHIPPING_MODELS)
        raise ValueError(f"shipping must be one of {allowed}, got {shipping!r}")


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


def assess_duty(
    product: Product,
    market: MarketConfig,
    cif: Decimal,
    duty_adjustment: Decimal,
    shipping: ShippingModel,
) -> DutyAssessment:
    """The duty rate for a product's CIF in the market currency.

    A consolidated import always pays its category rate plus ``duty_adjustment``. A direct
    parcel pays nothing when de minimis applies, whatever the adjustment; otherwise the same.
    Raises ``ValueError`` for an unknown ``shipping``.
    """
    require_shipping(shipping)
    customs = market.customs
    if shipping == "parcel" and de_minimis_applies(cif, customs.de_minimis, product.attributes):
        return DutyAssessment(rate=Decimal(0), waived=True)
    category_rate = customs.category_overrides.get(product.category, customs.default_duty_rate)
    return DutyAssessment(rate=category_rate + duty_adjustment, waived=False)
