"""The expansion report's figures: everything ``Decimal``, nothing formatted (SPEC §9.2)."""

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from souqsort.compliance import ExcludedProduct
from souqsort.logistics.calendar import DeliveryEstimate, estimate_delivery
from souqsort.models import Catalogue, GccConfig, MarketConfig, Product
from souqsort.pipeline import localise_and_summarise


@dataclass(frozen=True)
class MarketOverview:
    """One market for the order, with consolidated imports and today's duty rates.

    Both averages are unweighted means over the products for sale, kept as full-precision
    fractions, and are ``None`` when the market sells nothing. ``average_above_catalogue_pct``
    is the mean of ``shelf_price / goods - 1``. The delivery estimate needs no product, so a
    market that sells nothing still has one.
    """

    code: str
    name: str
    currency: str
    vat_rate: Decimal
    for_sale: int
    not_sold: tuple[ExcludedProduct, ...]
    average_margin_pct: Decimal | None
    average_above_catalogue_pct: Decimal | None
    cutoff: time
    delivery: DeliveryEstimate


@dataclass(frozen=True)
class ExpansionReport:
    """Every market in the config for one order, in config order.

    It names the data it was built from, not the SouqSort version, so a release leaves it
    unchanged.
    """

    ordered_at: datetime
    config_version: str
    fx_as_of: date
    catalogue_version: str
    product_count: int
    markets: tuple[MarketOverview, ...]


def _overview(
    products: list[Product], config: GccConfig, market: MarketConfig, ordered_at: datetime
) -> MarketOverview:
    localised = localise_and_summarise(
        products, config, market.code, ordered_at, Decimal("0"), "consolidated"
    )
    quotes = [item.quote for item in localised.items]
    above = (
        sum((quote.shelf_price / quote.goods - 1 for quote in quotes), Decimal(0)) / len(quotes)
        if quotes
        else None
    )
    return MarketOverview(
        code=market.code,
        name=market.name,
        currency=market.currency.code,
        vat_rate=market.tax.vat_rate,
        for_sale=len(localised.items),
        not_sold=localised.excluded,
        average_margin_pct=localised.summary.average_margin_pct,
        average_above_catalogue_pct=above,
        cutoff=market.calendar.order_cutoff_local,
        # localise_and_summarise has already made this estimate for the same order and
        # market, so it cannot fail here.
        delivery=estimate_delivery(ordered_at, market),
    )


def build_report(catalogue: Catalogue, config: GccConfig, ordered_at: datetime) -> ExpansionReport:
    """The report's figures for an order placed at ``ordered_at``.

    Every market comes from ``localise_and_summarise``, so the report agrees with the CLI and
    the dashboard, and a product a market does not allow is never priced.

    Raises ``ValueError`` if ``ordered_at`` is naive, before anything is priced, and
    ``LocalisationError`` as ``localise_and_summarise`` raises it.
    """
    if ordered_at.utcoffset() is None:
        raise ValueError("ordered_at must be timezone-aware, got a naive datetime")
    return ExpansionReport(
        ordered_at=ordered_at,
        config_version=config.config_version,
        fx_as_of=config.fx.as_of,
        catalogue_version=catalogue.catalogue_version,
        product_count=len(catalogue.products),
        markets=tuple(
            _overview(catalogue.products, config, market, ordered_at)
            for market in config.markets.values()
        ),
    )
