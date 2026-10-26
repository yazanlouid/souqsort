"""Business days and delivery-date estimates."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from souqsort.models import MarketConfig, ShippingModel, Weekday, require_shipping

# Config day names as ``date.weekday()`` numbers.
_WEEKDAY_NUMBER: dict[Weekday, int] = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
    "SAT": 5,
    "SUN": 6,
}
_ALL_WEEKDAYS = frozenset(range(7))


@dataclass(frozen=True)
class DeliveryEstimate:
    """When an order is dispatched and delivered, on the destination market's calendar.

    ``ordered_at_local`` is the order time in the market's timezone.
    """

    ordered_at_local: datetime
    dispatch_date: date
    delivery_date: date


def _require_date(name: str, value: date) -> None:
    """Reject a datetime: it never equals a date, so it would match no holiday."""
    if isinstance(value, datetime):
        raise TypeError(f"{name} must be a date, not a datetime; pass its .date(), got {value!r}")


def is_business_day(d: date, weekend: frozenset[int], holidays: frozenset[date]) -> bool:
    """True if ``d`` is neither a weekend day nor a holiday.

    ``weekend`` holds ``date.weekday()`` numbers: Monday is 0 and Sunday is 6.

    Raises ``TypeError`` if ``d`` is a datetime.
    """
    _require_date("d", d)
    return d.weekday() not in weekend and d not in holidays


def add_business_days(
    start: date, n: int, weekend: frozenset[int], holidays: frozenset[date]
) -> date:
    """The ``n``-th business day after ``start``; ``start`` itself is never counted.

    ``n = 0`` returns ``start`` unchanged, even when it is not a business day. Two calls
    chain: adding ``a`` days and then ``b`` days equals adding ``a + b`` on one calendar.

    Raises ``ValueError`` if ``n`` is negative, if ``weekend`` has a number outside 0-6 or
    covers all seven days, which would leave no business day to find, or if the result would
    be after ``date.max``. Raises ``TypeError`` if ``start`` is a datetime.
    """
    _require_date("start", start)
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    if not weekend <= _ALL_WEEKDAYS:
        raise ValueError(f"weekend days must be 0 (Monday) to 6 (Sunday), got {sorted(weekend)}")
    if weekend == _ALL_WEEKDAYS:
        raise ValueError("weekend covers all seven days, leaving no business day")
    if n == 0:
        return start

    # Each business day takes at least one calendar day, so this is known before searching.
    days_left = (date.max - start).days
    too_far = f"business day {n} after {start} is beyond the last supported date, {date.max}"
    if n > days_left:
        raise ValueError(too_far)

    # The search is bounded so it can never run forever. Any seven days in a row include a
    # day outside the weekend, and at most len(holidays) of those days are holidays, so the
    # n-th business day is at most 7 * (n + len(holidays)) days away.
    search_days = 7 * (n + len(holidays))
    found = 0
    for offset in range(1, min(search_days, days_left) + 1):
        day = start + timedelta(days=offset)
        if is_business_day(day, weekend, holidays):
            found += 1
            if found == n:
                return day
    if search_days > days_left:
        raise ValueError(too_far)
    raise AssertionError(f"no {n}-th business day within the search bound after {start}")


def in_market_time(ordered_at: datetime, market: MarketConfig) -> datetime:
    """An order time given without an offset is on the market's own clock.

    A naive ``ordered_at``, as a command-line option or a date and time picker gives it, gets
    the market's timezone. One that already has an offset is returned as it is.
    """
    if ordered_at.utcoffset() is None:
        return ordered_at.replace(tzinfo=ZoneInfo(market.calendar.timezone))
    return ordered_at


def to_market_time(moment: datetime, market: MarketConfig) -> datetime:
    """The same instant on the market's clock.

    Raises ``ValueError`` if ``moment`` is naive: unlike an order time typed by a person, an
    instant has to say which one it is.
    """
    if moment.utcoffset() is None:
        raise ValueError("moment must be timezone-aware, got a naive datetime")
    return moment.astimezone(ZoneInfo(market.calendar.timezone))


def estimate_delivery(
    ordered_at: datetime, market: MarketConfig, shipping: ShippingModel = "consolidated"
) -> DeliveryEstimate:
    """Estimate the dispatch and delivery dates of an order, on the market's calendar.

    The order is dispatched on its local date if that is a business day and the order came
    before the cutoff, otherwise on the next business day. An order exactly at the cutoff
    misses it. Delivery is linehaul plus last-mile business days after dispatch. Both shipping
    models share the dispatch rule and the last mile; a direct parcel takes the parcel
    linehaul.

    Raises ``ValueError`` if ``shipping`` is not a shipping model or ``ordered_at`` is naive.
    """
    require_shipping(shipping)
    if ordered_at.utcoffset() is None:
        raise ValueError("ordered_at must be timezone-aware, got a naive datetime")

    calendar = market.calendar
    logistics = market.logistics
    weekend = frozenset(_WEEKDAY_NUMBER[day] for day in calendar.weekend)
    holidays = frozenset(holiday.date for holiday in calendar.holidays)

    zone = ZoneInfo(calendar.timezone)
    local = ordered_at.astimezone(zone)
    local_date = local.date()

    # The cutoff is an instant, compared in UTC. Comparing clock times would let an order in
    # an hour repeated by a clock change get in before a cutoff that an earlier order missed.
    # A cutoff in a repeated hour is its first occurrence; one in a skipped hour falls an
    # hour later on the clock.
    cutoff = datetime.combine(local_date, calendar.order_cutoff_local, tzinfo=zone)
    before_cutoff = ordered_at.astimezone(UTC) < cutoff.astimezone(UTC)

    if before_cutoff and is_business_day(local_date, weekend, holidays):
        dispatch_date = local_date
    else:
        dispatch_date = add_business_days(local_date, 1, weekend, holidays)

    linehaul = (
        logistics.parcel_linehaul_business_days
        if shipping == "parcel"
        else logistics.linehaul_business_days
    )
    transit_days = linehaul + logistics.last_mile_business_days
    delivery_date = add_business_days(dispatch_date, transit_days, weekend, holidays)

    return DeliveryEstimate(
        ordered_at_local=local,
        dispatch_date=dispatch_date,
        delivery_date=delivery_date,
    )
