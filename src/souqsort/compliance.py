"""Screen products against a market's compliance rules before they are priced."""

from collections.abc import Sequence
from dataclasses import dataclass

from souqsort.models import AttributeName, MarketConfig, Product


@dataclass(frozen=True)
class ExcludedProduct:
    """A product a market does not sell, with the banned attributes it has.

    ``reasons`` are in the order the market lists its banned attributes.
    """

    sku: str
    name_en: str
    reasons: tuple[AttributeName, ...]


@dataclass(frozen=True)
class ComplianceScreen:
    """A catalogue split into what a market sells and what it does not, in catalogue order.

    Every product given to the screen is in exactly one of the two.
    """

    sellable: tuple[Product, ...]
    excluded: tuple[ExcludedProduct, ...]


def screen_products(products: Sequence[Product], market: MarketConfig) -> ComplianceScreen:
    """Split ``products`` by the market's banned attributes.

    A product is not sold if one of its attributes is true and the market bans it.
    """
    banned = market.compliance.banned_attributes
    sellable: list[Product] = []
    excluded: list[ExcludedProduct] = []
    for product in products:
        reasons = tuple(name for name in banned if product.attributes.has(name))
        if reasons:
            excluded.append(ExcludedProduct(product.sku, product.name.en, reasons))
        else:
            sellable.append(product)
    return ComplianceScreen(sellable=tuple(sellable), excluded=tuple(excluded))
