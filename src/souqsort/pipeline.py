"""Localise a catalogue for a market: prices, delivery estimates and flags."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, DecimalException

from souqsort.logistics.calendar import DeliveryEstimate, estimate_delivery
from souqsort.models import FxTable, GccConfig, MarketConfig, Product
from souqsort.pricing.landed_cost import PriceQuote, price_product
from souqsort.pricing.money import require_decimal

MISSING_ARABIC_NAME = "missing_arabic_name"
MAX_DUTY_ADJUST_POINTS = 20


class LocalisationError(ValueError):
    """A catalogue could not be localised for a market.

    The message starts with the SKU of the product that failed, or with the market code when
    the failure is not tied to one product; a figure for the whole catalogue that cannot be
    displayed is named instead. The original error, if any, is ``__cause__``.
    """


@dataclass(frozen=True)
class LocalisedProduct:
    """A product ready for one market: its price, delivery estimate and flags.

    ``name_ar`` is reported as it is in the catalogue; a missing one is marked in ``flags``.
    """

    sku: str
    name_en: str
    name_ar: str | None
    category: str
    quote: PriceQuote
    delivery: DeliveryEstimate
    flags: tuple[str, ...]


def _about(subject: str, exc: Exception) -> LocalisationError:
    """The error to raise in place of ``exc``, with a message starting with ``subject``."""
    if isinstance(exc, DecimalException):
        # str() of a decimal signal is only a list of signal classes.
        message = f"a value is out of range for decimal arithmetic ({type(exc).__name__})"
    else:
        message = str(exc)
    if not message.startswith(f"{subject}:"):
        message = f"{subject}: {message}"
    return LocalisationError(message)


def find_market(config: GccConfig, market_code: str) -> MarketConfig:
    """The config of a market, looked up by its exact code.

    Raises ``LocalisationError`` listing the configured markets if the code is not one of them.
    """
    try:
        return config.markets[market_code]
    except KeyError:
        configured = ", ".join(sorted(config.markets))
        raise LocalisationError(
            f"{market_code}: unknown market; configured markets: {configured}"
        ) from None


def duty_adjustment_from_points(points: int) -> Decimal:
    """Whole percentage points, as the CLI and the dashboard take them, as a fraction.

    ``3`` becomes ``Decimal("0.03")``. Raises ``TypeError`` if ``points`` is not an ``int``
    and ``ValueError`` if it is outside 0 to ``MAX_DUTY_ADJUST_POINTS``.
    """
    if isinstance(points, bool) or not isinstance(points, int):
        raise TypeError(
            "points must be a whole number of percentage points, "
            f"not {type(points).__name__} {points!r}"
        )
    if not 0 <= points <= MAX_DUTY_ADJUST_POINTS:
        raise ValueError(f"points must be from 0 to {MAX_DUTY_ADJUST_POINTS}, got {points}")
    return Decimal(points) / 100


def _require_duty_adjustment(duty_adjustment: Decimal) -> None:
    """Apply ``price_product``'s rule once, before any product is priced.

    A bad value is the caller's mistake, so it must not be reported against the first SKU.
    """
    require_decimal("duty_adjustment", duty_adjustment)
    if not duty_adjustment.is_finite() or duty_adjustment < 0:
        raise ValueError(f"duty_adjustment must be a finite fraction >= 0, got {duty_adjustment}")


def _flags(product: Product) -> tuple[str, ...]:
    arabic = product.name.ar
    if arabic is None or not arabic.strip():
        return (MISSING_ARABIC_NAME,)
    return ()


def _quote(
    product: Product, market: MarketConfig, fx: FxTable, duty_adjustment: Decimal
) -> PriceQuote:
    try:
        return price_product(product, market, fx, duty_adjustment)
    except (ValueError, ArithmeticError) as exc:
        raise _about(product.sku, exc) from exc


def localise_catalogue(
    products: list[Product],
    config: GccConfig,
    market_code: str,
    ordered_at: datetime,
    duty_adjustment: Decimal = Decimal("0"),
) -> list[LocalisedProduct]:
    """Price every product for a market and estimate its delivery, in catalogue order.

    ``ordered_at`` must be timezone-aware. ``duty_adjustment`` is a fraction added to every
    duty rate (``Decimal("0.03")`` = +3 percentage points).

    Raises ``LocalisationError``, with no partial result, if the market is not in the config,
    if the delivery date cannot be estimated (a naive or out-of-range ``ordered_at``), or if a
    product cannot be priced. Other exceptions are bugs and are not wrapped.

    Raises a plain ``TypeError`` or ``ValueError``, before anything else is looked at, if
    ``duty_adjustment`` is not a finite ``Decimal`` >= 0.
    """
    _require_duty_adjustment(duty_adjustment)
    market = find_market(config, market_code)

    # The estimate depends only on the order time and the market, so every product shares it.
    try:
        delivery = estimate_delivery(ordered_at, market)
    except (ValueError, ArithmeticError) as exc:
        raise _about(market.code, exc) from exc

    return [
        LocalisedProduct(
            sku=product.sku,
            name_en=product.name.en,
            name_ar=product.name.ar,
            category=product.category,
            quote=_quote(product, market, config.fx, duty_adjustment),
            delivery=delivery,
            flags=_flags(product),
        )
        for product in products
    ]


@dataclass(frozen=True)
class CatalogueSummary:
    """Headline figures for a localised catalogue.

    Both averages are unweighted means over the products, kept as full-precision fractions
    (``0.677`` = 67.7%), and are ``None`` when there are no products.
    ``average_price_change_pct`` is the mean change in shelf price against a baseline.
    """

    product_count: int
    flagged_count: int
    average_margin_pct: Decimal | None
    average_price_change_pct: Decimal | None


def summarise_catalogue(
    items: Sequence[LocalisedProduct], baseline: Sequence[LocalisedProduct]
) -> CatalogueSummary:
    """Summarise ``items`` and compare their shelf prices with ``baseline``.

    ``baseline`` is the same catalogue localised with no duty adjustment. Counts and the
    average margin describe ``items``. The price change of a product is
    ``(shelf_price - baseline shelf_price) / baseline shelf_price``.

    Raises ``ValueError`` if ``baseline`` does not hold the same SKUs in the same order, or if
    one of its shelf prices is zero, which leaves no change to measure against.
    """
    if len(items) != len(baseline):
        raise ValueError(
            f"baseline has {len(baseline)} products but there are {len(items)} to compare"
        )
    for item, base in zip(items, baseline, strict=True):
        if item.sku != base.sku:
            raise ValueError(f"baseline has {base.sku} where {item.sku} is expected")
        if base.quote.shelf_price == 0:
            raise ValueError(f"baseline shelf price of {base.sku} is zero")

    count = len(items)
    flagged_count = sum(1 for item in items if item.flags)
    if count == 0:
        return CatalogueSummary(0, flagged_count, None, None)

    margins = sum((item.quote.margin_pct for item in items), Decimal(0))
    changes = sum(
        (
            (item.quote.shelf_price - base.quote.shelf_price) / base.quote.shelf_price
            for item, base in zip(items, baseline, strict=True)
        ),
        Decimal(0),
    )
    return CatalogueSummary(
        product_count=count,
        flagged_count=flagged_count,
        average_margin_pct=margins / count,
        average_price_change_pct=changes / count,
    )


@dataclass(frozen=True)
class LocalisedCatalogue:
    """A catalogue localised for a market, with its headline figures.

    ``summary`` compares ``items`` with the same catalogue at no duty adjustment.
    """

    items: tuple[LocalisedProduct, ...]
    summary: CatalogueSummary


def localise_and_summarise(
    products: list[Product],
    config: GccConfig,
    market_code: str,
    ordered_at: datetime,
    duty_adjustment: Decimal = Decimal("0"),
) -> LocalisedCatalogue:
    """Localise a catalogue as ``localise_catalogue`` does, and summarise the result.

    The price change in the summary is measured against a baseline built here: the same
    products, config, market and order time with no duty adjustment. Callers do not build or
    pair the baseline themselves.

    Raises what ``localise_catalogue`` raises.
    """
    items = localise_catalogue(products, config, market_code, ordered_at, duty_adjustment)
    baseline = localise_catalogue(products, config, market_code, ordered_at)
    return LocalisedCatalogue(
        items=tuple(items),
        summary=summarise_catalogue(items, baseline),
    )
