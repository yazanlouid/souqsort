"""The expansion report's figures: everything ``Decimal``, nothing formatted (SPEC §9.2)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, Inexact, localcontext

from souqsort.compliance import ExcludedProduct
from souqsort.logistics.calendar import DeliveryEstimate, estimate_delivery
from souqsort.models import (
    Catalogue,
    DeMinimisRule,
    GccConfig,
    MarketConfig,
    Product,
    ShippingModel,
)
from souqsort.pipeline import (
    LocalisedCatalogue,
    duty_adjustment_from_points,
    localise_and_summarise,
)
from souqsort.pricing.customs import SHIPPING_MODELS, parcel_fee_due, travels
from souqsort.pricing.landed_cost import PriceQuote

# The tariff rises the report stress-tests, in whole percentage points (§9.2.3).
TARIFF_RISES_POINTS: tuple[int, ...] = (5, 10, 20)
# The rise the tariff sentence quotes; it must be one of TARIFF_RISES_POINTS.
HEADLINE_TARIFF_RISE_POINTS = 10


def _require_headline_rise(headline: int, rises: tuple[int, ...]) -> None:
    """Raise ``ValueError`` naming both constants unless ``headline`` is one of ``rises``."""
    if headline not in rises:
        raise ValueError(
            f"HEADLINE_TARIFF_RISE_POINTS ({headline}) must be one of TARIFF_RISES_POINTS {rises}"
        )


# Checked on import, so a mismatch fails at once rather than on every render.
_require_headline_rise(HEADLINE_TARIFF_RISE_POINTS, TARIFF_RISES_POINTS)

# A product is a pricing risk when rounding and the price ending add more than this share
# to its consolidated price (§9.2.5). Exactly the alert is not a risk.
PRICE_ENDING_ALERT = Decimal("0.10")


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
class ProductComparison:
    """One product for sale as a one-item order: a consolidated import and a direct parcel.

    The consolidated order costs ``consolidated_price``. The parcel order costs
    ``parcel_price``, the parcel shelf price, plus ``parcel_fee``, the customs fee it pays at
    checkout (``None`` when the market has none or the product does not travel).
    ``change_pct`` is the full-precision ``parcel_order / consolidated_price - 1``.
    ``parcel_duty_rate`` and ``parcel_duty_waived`` are the parcel quote's.
    """

    sku: str
    name_en: str
    consolidated_price: Decimal
    parcel_price: Decimal
    parcel_fee: Decimal | None
    change_pct: Decimal
    parcel_duty_rate: Decimal
    parcel_duty_waived: bool

    @property
    def parcel_order(self) -> Decimal:
        """What the one-item parcel order costs at checkout, exactly."""
        return self.parcel_price + (self.parcel_fee or 0)


@dataclass(frozen=True)
class ShippingComparison:
    """One market's products for sale in both shipping models, in catalogue order.

    A product is cheaper, dearer or unchanged as a parcel by comparing the two one-item
    orders themselves, never the rounded change. ``parcel_fee`` is the fee the market charges
    a parcel in which something travels, and ``parcel_delivery`` is when its parcels arrive;
    a market that sells nothing still has both.
    """

    code: str
    name: str
    currency: str
    minor_units: int
    de_minimis: DeMinimisRule | None
    parcel_fee: Decimal | None
    parcel_delivery: DeliveryEstimate
    products: tuple[ProductComparison, ...]

    @property
    def cheaper(self) -> int:
        return sum(1 for p in self.products if p.parcel_order < p.consolidated_price)

    @property
    def dearer(self) -> int:
        return sum(1 for p in self.products if p.parcel_order > p.consolidated_price)

    @property
    def unchanged(self) -> int:
        return sum(1 for p in self.products if p.parcel_order == p.consolidated_price)

    @property
    def waived(self) -> int:
        """How many parcel quotes de minimis waived the duty of."""
        return sum(1 for p in self.products if p.parcel_duty_waived)


@dataclass(frozen=True)
class TariffExposure:
    """How much a market's prices rise in one shipping model for each tariff rise.

    ``average_change_pct`` has one full-precision fraction per ``TARIFF_RISES_POINTS``: the
    mean change in shelf price against the same products in the same model at today's rates.
    Each is ``None`` when the market sells nothing.
    """

    code: str
    shipping: ShippingModel
    average_change_pct: tuple[Decimal | None, ...]


@dataclass(frozen=True)
class SampleProduct:
    """The first product in catalogue order that every market sells (§9.2.4)."""

    sku: str
    name_en: str


@dataclass(frozen=True)
class PriceBuildUp:
    """The sample product's two quotes in one market, at today's duty rates.

    The quotes keep full precision; the report rounds their components for display only.
    ``parcel_fee`` is what the one-item parcel order adds at checkout, or ``None``.
    """

    code: str
    currency: str
    minor_units: int
    consolidated: PriceQuote
    parcel: PriceQuote
    parcel_fee: Decimal | None

    @property
    def parcel_order(self) -> Decimal:
        """What the one-item parcel order costs at checkout, exactly."""
        return self.parcel.shelf_price + (self.parcel_fee or 0)


@dataclass(frozen=True)
class PricingRisk:
    """A product whose price ending adds more than ``PRICE_ENDING_ALERT`` to its price.

    From its consolidated quote at today's duty rates: ``gross`` is the full-precision price
    before rounding and the price ending, and ``added_pct`` is the full-precision
    ``shelf_price / gross - 1``.
    """

    code: str
    sku: str
    name_en: str
    minor_units: int
    gross: Decimal
    shelf_price: Decimal
    added_pct: Decimal


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
    shipping: tuple[ShippingComparison, ...]
    tariffs: tuple[TariffExposure, ...]  # by market, then shipping model
    sample_product: SampleProduct | None  # None when no product is sold in every market
    build_ups: tuple[PriceBuildUp, ...]  # config order; empty without a sample product
    pricing_risks: tuple[PricingRisk, ...]  # by market, then catalogue order


@dataclass(frozen=True)
class _MarketViews:
    """One market at today's duty rates, localised once in each shipping model."""

    market: MarketConfig
    consolidated: LocalisedCatalogue
    parcel: LocalisedCatalogue


def price_ending_added(quote: PriceQuote) -> Decimal:
    """The share rounding and the price ending add to a price: ``shelf_price / gross - 1``.

    Full precision, for display: the quotient is rounded to the context's precision, so
    whether a price is a risk is decided by ``_adds_more_than_the_alert`` instead. Catalogue
    prices are above zero, so ``gross`` never is zero.
    """
    return quote.shelf_price / quote.gross - 1


def _adds_more_than_the_alert(quote: PriceQuote) -> bool:
    """Whether ``shelf_price > gross * (1 + PRICE_ENDING_ALERT)``, decided exactly.

    A product of two coefficients has at most as many digits as both together, so with that
    precision the multiplication never rounds; ``Inexact`` is trapped to prove it, and so
    that an alert whose factor cannot be formed exactly raises rather than being rounded.
    Dividing instead would round a repeating quotient, which can land on the alert itself.
    """
    with localcontext() as context:
        context.traps[Inexact] = True
        factor = 1 + PRICE_ENDING_ALERT
        context.prec = len(quote.gross.as_tuple().digits) + len(factor.as_tuple().digits)
        return quote.shelf_price > quote.gross * factor


def _overview(
    market: MarketConfig, localised: LocalisedCatalogue, ordered_at: datetime
) -> MarketOverview:
    """``localised`` is the market with consolidated imports at today's duty rates."""
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


def _shipping(
    market: MarketConfig,
    consolidated: LocalisedCatalogue,
    parcel: LocalisedCatalogue,
    products: Mapping[str, Product],
    ordered_at: datetime,
) -> ShippingComparison:
    """Both views are of the same products at today's duty rates, one per shipping model.

    Each product is compared as a one-item order (§7.10.1 rule 10), so a parcel pays the fee
    when the product travels. ``products`` finds a product by its SKU.
    """
    comparisons: list[ProductComparison] = []
    for by_import, by_parcel in zip(consolidated.items, parcel.items, strict=True):
        # strict=True checks the lengths only; the pairs must also be the same product.
        if by_import.sku != by_parcel.sku:
            raise ValueError(f"parcel view has {by_parcel.sku} where {by_import.sku} is expected")
        import_price, parcel_quote = by_import.quote.shelf_price, by_parcel.quote
        fee = parcel_fee_due(market, "parcel", travels(products[by_import.sku]))
        parcel_order = parcel_quote.shelf_price + (fee or 0)
        comparisons.append(
            ProductComparison(
                sku=by_import.sku,
                name_en=by_import.name_en,
                consolidated_price=import_price,
                parcel_price=parcel_quote.shelf_price,
                parcel_fee=fee,
                change_pct=parcel_order / import_price - 1,
                parcel_duty_rate=parcel_quote.duty_rate,
                parcel_duty_waived=parcel_quote.duty_waived,
            )
        )
    return ShippingComparison(
        code=market.code,
        name=market.name,
        currency=market.currency.code,
        minor_units=market.currency.minor_units,
        de_minimis=market.customs.de_minimis,
        parcel_fee=parcel_fee_due(market, "parcel", anything_travels=True),
        # localise_and_summarise has already made a parcel estimate for the same order and
        # market, so it cannot fail here.
        parcel_delivery=estimate_delivery(ordered_at, market, "parcel"),
        products=tuple(comparisons),
    )


def _localise(
    products: list[Product], config: GccConfig, market: MarketConfig, ordered_at: datetime
) -> _MarketViews:
    """One market, each shipping model localised once at today's duty rates.

    The models are named, not taken from ``SHIPPING_MODELS``, so the markets table always
    shows consolidated imports whatever order the models are declared in.
    """
    return _MarketViews(
        market=market,
        consolidated=localise_and_summarise(
            products, config, market.code, ordered_at, Decimal("0"), "consolidated"
        ),
        parcel=localise_and_summarise(
            products, config, market.code, ordered_at, Decimal("0"), "parcel"
        ),
    )


def _sample_product(products: list[Product], views: list[_MarketViews]) -> SampleProduct | None:
    """The first product in catalogue order that every market sells, if there is one.

    Compliance does not depend on the shipping model, so the consolidated views decide.
    """
    selling = [{item.sku for item in view.consolidated.items} for view in views]
    for product in products:
        if all(product.sku in skus for skus in selling):
            return SampleProduct(sku=product.sku, name_en=product.name.en)
    return None


def _build_up(view: _MarketViews, product: Product) -> PriceBuildUp:
    """The product's two quotes in one market, taken from the views already localised.

    Raises ``ValueError`` naming the market, the shipping model and the SKU if a view does not
    sell it.
    """
    sku = product.sku
    by_model: tuple[tuple[ShippingModel, LocalisedCatalogue], ...] = (
        ("consolidated", view.consolidated),
        ("parcel", view.parcel),
    )
    quotes: dict[ShippingModel, PriceQuote] = {}
    for model, localised in by_model:
        quote = next((item.quote for item in localised.items if item.sku == sku), None)
        if quote is None:
            raise ValueError(f"{view.market.code}: the {model} view has no {sku}")
        quotes[model] = quote
    consolidated, parcel = quotes["consolidated"], quotes["parcel"]
    return PriceBuildUp(
        code=view.market.code,
        currency=view.market.currency.code,
        minor_units=view.market.currency.minor_units,
        consolidated=consolidated,
        parcel=parcel,
        parcel_fee=parcel_fee_due(view.market, "parcel", travels(product)),
    )


def _tariffs(
    products: list[Product], config: GccConfig, market: MarketConfig, ordered_at: datetime
) -> list[TariffExposure]:
    """One market's exposure in each shipping model, from ``localise_and_summarise``.

    Its average price change already compares each product with its price at 0 pp in the
    same shipping model.
    """
    return [
        TariffExposure(
            code=market.code,
            shipping=model,
            average_change_pct=tuple(
                localise_and_summarise(
                    products,
                    config,
                    market.code,
                    ordered_at,
                    duty_adjustment_from_points(rise),
                    model,
                ).summary.average_price_change_pct
                for rise in TARIFF_RISES_POINTS
            ),
        )
        for model in SHIPPING_MODELS
    ]


def _pricing_risks(view: _MarketViews) -> list[PricingRisk]:
    """One market's pricing risks, from its consolidated view, in catalogue order."""
    risks = []
    for item in view.consolidated.items:
        if _adds_more_than_the_alert(item.quote):
            risks.append(
                PricingRisk(
                    code=view.market.code,
                    sku=item.sku,
                    name_en=item.name_en,
                    minor_units=view.market.currency.minor_units,
                    gross=item.quote.gross,
                    shelf_price=item.quote.shelf_price,
                    added_pct=price_ending_added(item.quote),
                )
            )
    return risks


def build_report(catalogue: Catalogue, config: GccConfig, ordered_at: datetime) -> ExpansionReport:
    """The report's figures for an order placed at ``ordered_at``.

    Every market comes from ``localise_and_summarise``, so the report agrees with the CLI and
    the dashboard, and a product a market does not allow is never priced.

    Raises ``ValueError`` if ``ordered_at`` is naive, before anything is priced, and
    ``LocalisationError`` as ``localise_and_summarise`` raises it.
    """
    if ordered_at.utcoffset() is None:
        raise ValueError("ordered_at must be timezone-aware, got a naive datetime")
    views = [
        _localise(catalogue.products, config, market, ordered_at)
        for market in config.markets.values()
    ]
    by_sku = {product.sku: product for product in catalogue.products}
    sample = _sample_product(catalogue.products, views)
    return ExpansionReport(
        ordered_at=ordered_at,
        config_version=config.config_version,
        fx_as_of=config.fx.as_of,
        catalogue_version=catalogue.catalogue_version,
        product_count=len(catalogue.products),
        markets=tuple(_overview(view.market, view.consolidated, ordered_at) for view in views),
        shipping=tuple(
            _shipping(view.market, view.consolidated, view.parcel, by_sku, ordered_at)
            for view in views
        ),
        tariffs=tuple(
            exposure
            for market in config.markets.values()
            for exposure in _tariffs(catalogue.products, config, market, ordered_at)
        ),
        sample_product=sample,
        build_ups=(
            () if sample is None else tuple(_build_up(view, by_sku[sample.sku]) for view in views)
        ),
        pricing_risks=tuple(risk for view in views for risk in _pricing_risks(view)),
    )
