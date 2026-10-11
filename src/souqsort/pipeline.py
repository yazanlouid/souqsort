"""Localise a catalogue for a market: prices, delivery estimates and flags."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, DecimalException

from souqsort.logistics.calendar import DeliveryEstimate, estimate_delivery
from souqsort.models import FxTable, GccConfig, MarketConfig, Product
from souqsort.pricing.landed_cost import PriceQuote, price_product
from souqsort.pricing.money import require_decimal

MISSING_ARABIC_NAME = "missing_arabic_name"


class LocalisationError(ValueError):
    """A catalogue could not be localised for a market.

    The message starts with the SKU of the product that failed, or with the market code when
    the failure is not tied to one product. The original error, if any, is ``__cause__``.
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
