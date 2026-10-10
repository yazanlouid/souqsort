"""Minor-unit rounding, charm endings and money formatting.

Every amount is a ``Decimal``; a float, int or string is rejected rather than converted.
"""

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal


def _require_decimal(name: str, value: object) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal, not {type(value).__name__} {value!r}")


def _quantum(minor_units: int) -> Decimal:
    if minor_units < 0:
        raise ValueError(f"minor_units must be >= 0, got {minor_units}")
    return Decimal(1).scaleb(-minor_units)


def round_minor(amount: Decimal, minor_units: int) -> Decimal:
    """Round to exactly ``minor_units`` decimals with ``ROUND_HALF_UP``.

    Negative amounts round away from zero. A zero result is never signed.
    """
    _require_decimal("amount", amount)
    if not amount.is_finite():
        raise ValueError(f"amount must be finite, got {amount}")
    rounded = amount.quantize(_quantum(minor_units), rounding=ROUND_HALF_UP)
    return rounded.copy_abs() if rounded.is_zero() else rounded


def charm_up(amount: Decimal, charm_ending: Decimal | None, minor_units: int) -> Decimal:
    """Move an already-rounded price up to the next price ending in ``charm_ending``.

    A price that already has the ending is kept, so charm pricing never lowers a price.
    ``charm_ending=None`` means no charm pricing. The result has exactly ``minor_units``
    decimals.
    """
    rounded = round_minor(amount, minor_units)
    if amount < 0:
        raise ValueError(f"cannot charm a negative amount, got {amount}")
    if amount != rounded:
        raise ValueError(
            f"amount {amount} must be rounded to {minor_units} minor units before charm pricing"
        )
    if charm_ending is None:
        return rounded

    _require_decimal("charm_ending", charm_ending)
    if not charm_ending.is_finite() or not 0 <= charm_ending < 1:
        raise ValueError(f"charm_ending must be at least 0 and less than 1, got {charm_ending}")
    quantum = _quantum(minor_units)
    if charm_ending != charm_ending.quantize(quantum):
        raise ValueError(
            f"charm_ending {charm_ending} has more decimals than minor_units ({minor_units})"
        )

    charmed = rounded.to_integral_value(rounding=ROUND_FLOOR) + charm_ending
    if charmed < rounded:
        charmed += 1
    return charmed.quantize(quantum)


def format_money(amount: Decimal, minor_units: int) -> str:
    """Format with exactly ``minor_units`` decimals, rounding half up for display."""
    return f"{round_minor(amount, minor_units):f}"
