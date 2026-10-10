"""Currency conversion."""

from decimal import Decimal

from souqsort.models import FxTable
from souqsort.pricing.money import require_decimal


def _per_usd(currency: str, fx: FxTable) -> Decimal:
    try:
        return fx.per_usd[currency]
    except KeyError:
        raise ValueError(f"no FX rate for currency {currency!r} in fx.per_usd") from None


def convert(amount: Decimal, from_currency: str, to_currency: str, fx: FxTable) -> Decimal:
    """Convert through USD: ``amount * per_usd[to] / per_usd[from]``.

    Multiplying first keeps a result exact whenever it has a finite decimal expansion; only
    the division can round, to the decimal context's precision. Nothing is rounded to minor
    units here. Converting a currency to itself returns the amount unchanged.
    """
    require_decimal("amount", amount)
    if not amount.is_finite():
        raise ValueError(f"amount must be finite, got {amount}")
    from_rate = _per_usd(from_currency, fx)
    to_rate = _per_usd(to_currency, fx)
    if from_currency == to_currency:
        return amount
    return amount * to_rate / from_rate
