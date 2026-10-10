"""M4: business days and delivery estimates (SPEC §8)."""

from dataclasses import FrozenInstanceError, dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from souqsort.logistics.calendar import (
    DeliveryEstimate,
    add_business_days,
    estimate_delivery,
    is_business_day,
)
from souqsort.models import GccConfig, Holiday, MarketConfig

WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")  # position = date.weekday()
EVERY_DAY = frozenset(range(7))
KSA_WEEKEND = frozenset({4, 5})  # FRI, SAT
UK_WEEKEND = frozenset({5, 6})  # SAT, SUN
NO_HOLIDAYS: frozenset[date] = frozenset()

MON_19 = date(2026, 10, 19)


# --- helpers and fixtures -----------------------------------------------------------------


def _utc(text: str) -> datetime:
    """An aware UTC datetime from text such as ``"2026-10-11 07:00"``."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def _holiday(day: date, provisional: bool = False) -> Holiday:
    return Holiday(date=day, name="Test holiday", provisional=provisional)


def _with_calendar(market: MarketConfig, **changes: Any) -> MarketConfig:
    """A copy of the market with calendar fields replaced; the original is untouched."""
    return market.model_copy(update={"calendar": market.calendar.model_copy(update=changes)})


def _with_business_days(market: MarketConfig, linehaul: int, last_mile: int) -> MarketConfig:
    """A copy of the market with different transit times; the original is untouched."""
    logistics = market.logistics.model_copy(
        update={"linehaul_business_days": linehaul, "last_mile_business_days": last_mile}
    )
    return market.model_copy(update={"logistics": logistics})


def _is_working(day: date, weekend: frozenset[int], holidays: frozenset[date]) -> bool:
    """The business-day rule, restated here so the tests do not lean on the engine's own."""
    return day.weekday() not in weekend and day not in holidays


def _business_days_in(
    after: date, upto: date, weekend: frozenset[int], holidays: frozenset[date]
) -> int:
    """Business days in ``(after, upto]``, counted one day at a time."""
    days = (upto - after).days
    return sum(
        _is_working(after + timedelta(days=i), weekend, holidays) for i in range(1, days + 1)
    )


@pytest.fixture
def ksa(config: GccConfig) -> MarketConfig:
    return config.markets["KSA"]


# --- is_business_day ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 10, 15), True),  # Thu
        (date(2026, 10, 16), False),  # Fri
        (date(2026, 10, 17), False),  # Sat
        (date(2026, 10, 18), True),  # Sun
    ],
)
def test_weekend_days_are_not_business_days(day: date, expected: bool) -> None:
    assert is_business_day(day, KSA_WEEKEND, NO_HOLIDAYS) is expected


def test_holiday_is_not_a_business_day() -> None:
    assert is_business_day(MON_19, KSA_WEEKEND, NO_HOLIDAYS) is True
    assert is_business_day(MON_19, KSA_WEEKEND, frozenset({MON_19})) is False


def test_without_weekend_or_holidays_every_day_is_a_business_day() -> None:
    week = [date(2026, 10, 12) + timedelta(days=i) for i in range(7)]
    assert all(is_business_day(day, frozenset(), NO_HOLIDAYS) for day in week)


# --- add_business_days --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "n", "expected"),
    [
        (date(2026, 10, 11), 1, date(2026, 10, 12)),  # Sun -> Mon
        (date(2026, 10, 11), 5, date(2026, 10, 18)),  # Sun -> Sun, across Fri-Sat
        (date(2026, 10, 15), 1, date(2026, 10, 18)),  # Thu -> Sun
        (date(2026, 10, 16), 1, date(2026, 10, 18)),  # Fri (weekend) -> Sun
        (date(2026, 10, 17), 1, date(2026, 10, 18)),  # Sat (weekend) -> Sun
        (date(2026, 12, 31), 1, date(2027, 1, 3)),  # Thu -> Sun, across the year end
    ],
)
def test_add_business_days_skips_the_weekend(start: date, n: int, expected: date) -> None:
    assert add_business_days(start, n, KSA_WEEKEND, NO_HOLIDAYS) == expected


def test_add_business_days_skips_holidays() -> None:
    # Sun 18 + 5 with Mon 19 off: Tue 20, Wed 21, Thu 22, Sun 25, Mon 26.
    sunday = date(2026, 10, 18)
    assert add_business_days(sunday, 5, KSA_WEEKEND, frozenset({MON_19})) == date(2026, 10, 26)


@pytest.mark.parametrize(
    "start",
    [date(2026, 10, 15), date(2026, 10, 16), MON_19],
    ids=["business-day", "weekend-day", "holiday"],
)
def test_adding_zero_business_days_returns_the_start(start: date) -> None:
    # Adding nothing is the identity, even from a day that is not a business day.
    assert add_business_days(start, 0, KSA_WEEKEND, frozenset({MON_19})) == start


def test_two_legs_chain_with_different_calendars() -> None:
    # SPEC §8: the later two-leg version is two chained calls. From Thu 15, two days on a
    # Sat-Sun calendar reach Mon 19; two more on the Fri-Sat calendar reach Wed 21.
    handover = add_business_days(date(2026, 10, 15), 2, UK_WEEKEND, NO_HOLIDAYS)
    assert handover == MON_19
    assert add_business_days(handover, 2, KSA_WEEKEND, NO_HOLIDAYS) == date(2026, 10, 21)


# --- add_business_days always terminates --------------------------------------------------


@pytest.mark.parametrize("n", [0, 1, 5])
def test_weekend_covering_all_seven_days_rejected(n: int) -> None:
    # No day can ever be a business day: this must raise, not search forever.
    with pytest.raises(ValueError, match="weekend"):
        add_business_days(date(2026, 10, 11), n, EVERY_DAY, NO_HOLIDAYS)


@pytest.mark.parametrize("weekend", [{7}, {-1}, {4, 5, 9}])
def test_weekday_outside_monday_to_sunday_rejected(weekend: set[int]) -> None:
    with pytest.raises(ValueError, match="weekend"):
        add_business_days(date(2026, 10, 11), 1, frozenset(weekend), NO_HOLIDAYS)


@pytest.mark.parametrize("n", [-1, -5])
def test_negative_business_days_rejected(n: int) -> None:
    with pytest.raises(ValueError, match="n must be"):
        add_business_days(date(2026, 10, 11), n, KSA_WEEKEND, NO_HOLIDAYS)


@pytest.mark.parametrize(("n", "days_later"), [(1, 406), (3, 420)])
def test_long_run_of_holidays_with_a_six_day_weekend(n: int, days_later: int) -> None:
    # Only Sundays are worked, and the 400 days after the start are all holidays. Day 400 is
    # a Monday, so the first business day is the Sunday after it: day 406.
    start = date(2026, 10, 11)  # Sun
    only_sunday_worked = frozenset({0, 1, 2, 3, 4, 5})
    holidays = frozenset(start + timedelta(days=i) for i in range(1, 401))

    result = add_business_days(start, n, only_sunday_worked, holidays)

    assert result == start + timedelta(days=days_later)


# --- add_business_days: dates out of range, and datetimes ---------------------------------


def test_business_day_beyond_the_last_date_rejected_at_once() -> None:
    # Four million business days from 2026 is past the year 9999: a clear error before any
    # searching, not an OverflowError after millions of steps.
    with pytest.raises(ValueError, match="beyond"):
        add_business_days(date(2026, 10, 18), 4_000_000, KSA_WEEKEND, NO_HOLIDAYS)


def test_search_running_past_the_last_date_rejected() -> None:
    # Six days are left after Sat 9999-12-25, but the last of them is a Friday: only five
    # are business days.
    with pytest.raises(ValueError, match="beyond"):
        add_business_days(date(9999, 12, 25), 6, KSA_WEEKEND, NO_HOLIDAYS)


def test_last_supported_date_is_reachable() -> None:
    day_before = date.max - timedelta(days=1)
    assert add_business_days(day_before, 1, frozenset(), NO_HOLIDAYS) == date.max
    assert add_business_days(date.max, 0, KSA_WEEKEND, NO_HOLIDAYS) == date.max


def test_datetime_rejected_as_a_day() -> None:
    # A datetime never equals a date, so it would slip past every holiday unnoticed.
    moment = datetime.combine(MON_19, time(10), tzinfo=UTC)
    with pytest.raises(TypeError, match="datetime"):
        is_business_day(moment, KSA_WEEKEND, frozenset({MON_19}))


@pytest.mark.parametrize("n", [0, 5])
def test_datetime_rejected_as_a_start(n: int) -> None:
    with pytest.raises(TypeError, match="datetime"):
        add_business_days(_utc("2026-10-18 10:00"), n, KSA_WEEKEND, frozenset({MON_19}))


# --- estimate_delivery: worked examples (SPEC §8.1) ---------------------------------------


@pytest.mark.parametrize(
    ("ordered_at", "holidays", "local", "dispatch", "delivery"),
    [
        ("2026-10-11 07:00", (), "2026-10-11T10:00:00+03:00", "2026-10-11", "2026-10-18"),
        ("2026-10-11 11:00", (), "2026-10-11T14:00:00+03:00", "2026-10-12", "2026-10-19"),
        ("2026-10-15 10:30", (), "2026-10-15T13:30:00+03:00", "2026-10-15", "2026-10-22"),
        ("2026-10-15 20:59", (), "2026-10-15T23:59:00+03:00", "2026-10-18", "2026-10-25"),
        ("2026-10-15 22:30", (), "2026-10-16T01:30:00+03:00", "2026-10-18", "2026-10-25"),
        ("2026-10-15 20:59", (MON_19,), "2026-10-15T23:59:00+03:00", "2026-10-18", "2026-10-26"),
    ],
    ids=[
        "sun-10:00",
        "sun-14:00-exactly-at-cutoff",
        "thu-13:30",
        "thu-23:59",
        "fri-01:30-local-weekend",
        "thu-23:59-with-holiday-mon-19",
    ],
)
def test_worked_examples(
    ksa: MarketConfig,
    ordered_at: str,
    holidays: tuple[date, ...],
    local: str,
    dispatch: str,
    delivery: str,
) -> None:
    market = _with_calendar(ksa, holidays=tuple(_holiday(day) for day in holidays))

    estimate = estimate_delivery(_utc(ordered_at), market)

    assert isinstance(estimate, DeliveryEstimate)
    assert estimate.ordered_at_local.isoformat() == local
    assert estimate.dispatch_date == date.fromisoformat(dispatch)
    assert estimate.delivery_date == date.fromisoformat(delivery)


# --- estimate_delivery: order time and timezone -------------------------------------------


@pytest.mark.parametrize(
    ("ordered_at", "dispatch"),
    [
        ("2026-10-11 10:59:00", "2026-10-11"),  # 13:59 in Riyadh
        ("2026-10-11 10:59:59.999999", "2026-10-11"),
        ("2026-10-11 11:00:00", "2026-10-12"),  # exactly the cutoff misses it
        ("2026-10-11 11:00:00.000001", "2026-10-12"),
    ],
)
def test_cutoff_boundary(ksa: MarketConfig, ordered_at: str, dispatch: str) -> None:
    assert estimate_delivery(_utc(ordered_at), ksa).dispatch_date == date.fromisoformat(dispatch)


def test_ordered_at_local_is_the_same_instant_in_the_market_timezone(ksa: MarketConfig) -> None:
    ordered_at = _utc("2026-10-15 22:30")

    local = estimate_delivery(ordered_at, ksa).ordered_at_local

    assert local == ordered_at
    assert local.utcoffset() == timedelta(hours=3)
    assert local.date() == date(2026, 10, 16)  # already Friday in Riyadh


def test_order_time_in_another_timezone_gives_the_same_estimate(ksa: MarketConfig) -> None:
    # 02:29 on Fri 16 in India is 20:59 UTC on Thu 15: still Thursday 23:59 in Riyadh.
    india = timezone(timedelta(hours=5, minutes=30))
    ordered_at = datetime(2026, 10, 16, 2, 29, tzinfo=india)

    estimate = estimate_delivery(ordered_at, ksa)

    assert estimate == estimate_delivery(_utc("2026-10-15 20:59"), ksa)
    assert estimate.ordered_at_local.isoformat() == "2026-10-15T23:59:00+03:00"
    assert estimate.dispatch_date == date(2026, 10, 18)


def test_naive_datetime_rejected(ksa: MarketConfig) -> None:
    naive = _utc("2026-10-11 07:00").replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        estimate_delivery(naive, ksa)


# --- estimate_delivery: holidays ----------------------------------------------------------


@pytest.mark.parametrize("provisional", [False, True], ids=["confirmed", "provisional"])
def test_provisional_holidays_count_as_holidays(ksa: MarketConfig, provisional: bool) -> None:
    market = _with_calendar(ksa, holidays=(_holiday(MON_19, provisional),))

    estimate = estimate_delivery(_utc("2026-10-15 20:59"), market)

    assert estimate.delivery_date == date(2026, 10, 26)


def test_order_on_a_holiday_dispatches_the_next_business_day(ksa: MarketConfig) -> None:
    # Sun 11 at 10:00 is before the cutoff, but the day is a holiday.
    market = _with_calendar(ksa, holidays=(_holiday(date(2026, 10, 11)),))

    estimate = estimate_delivery(_utc("2026-10-11 07:00"), market)

    assert estimate.dispatch_date == date(2026, 10, 12)
    assert estimate.delivery_date == MON_19


def test_holiday_right_after_the_weekend_pushes_dispatch(ksa: MarketConfig) -> None:
    # Thu 23:59 misses the cutoff; Fri and Sat are the weekend and Sun 18 is a holiday.
    market = _with_calendar(ksa, holidays=(_holiday(date(2026, 10, 18)),))

    estimate = estimate_delivery(_utc("2026-10-15 20:59"), market)

    assert estimate.dispatch_date == MON_19
    assert estimate.delivery_date == date(2026, 10, 26)


def test_holiday_from_the_sample_config_delays_delivery(ksa: MarketConfig) -> None:
    # Founding Day, Mon 2027-02-22, is in gcc_config.json. Ordered Sun 21 at 10:00:
    # Tue 23, Wed 24, Thu 25, Sun 28, Mon 1 March.
    estimate = estimate_delivery(_utc("2027-02-21 07:00"), ksa)

    assert estimate.dispatch_date == date(2027, 2, 21)
    assert estimate.delivery_date == date(2027, 3, 1)


# --- estimate_delivery: everything comes from the market config ---------------------------


@pytest.mark.parametrize(
    ("linehaul", "last_mile", "delivery"),
    [
        (0, 0, "2026-10-15"),  # same day as dispatch
        (1, 0, "2026-10-18"),
        (0, 1, "2026-10-18"),
        (2, 4, "2026-10-25"),
    ],
)
def test_transit_days_are_linehaul_plus_last_mile(
    ksa: MarketConfig, linehaul: int, last_mile: int, delivery: str
) -> None:
    market = _with_business_days(ksa, linehaul, last_mile)

    estimate = estimate_delivery(_utc("2026-10-15 10:30"), market)

    assert estimate.dispatch_date == date(2026, 10, 15)
    assert estimate.delivery_date == date.fromisoformat(delivery)


def test_weekend_and_timezone_come_from_the_config(ksa: MarketConfig) -> None:
    # The same order on a Sat-Sun calendar in Dubai (UTC+4): 00:59 on Fri 16, a business day.
    market = _with_calendar(ksa, timezone="Asia/Dubai", weekend=("SAT", "SUN"))

    estimate = estimate_delivery(_utc("2026-10-15 20:59"), market)

    assert estimate.ordered_at_local.isoformat() == "2026-10-16T00:59:00+04:00"
    assert estimate.dispatch_date == date(2026, 10, 16)
    assert estimate.delivery_date == date(2026, 10, 23)


def test_seven_day_weekend_market_rejected_instead_of_hanging(ksa: MarketConfig) -> None:
    # The loader rejects this config; model_copy skips validation, so the engine must cope.
    market = _with_calendar(ksa, weekend=WEEKDAYS)
    with pytest.raises(ValueError, match="weekend"):
        estimate_delivery(_utc("2026-10-11 07:00"), market)


def test_transit_days_beyond_the_last_date_rejected(ksa: MarketConfig) -> None:
    market = _with_business_days(ksa, 4_000_000, 0)
    with pytest.raises(ValueError, match="beyond"):
        estimate_delivery(_utc("2026-10-11 07:00"), market)


def test_estimate_does_not_modify_the_config(ksa: MarketConfig) -> None:
    before = ksa.model_dump()

    estimate_delivery(_utc("2026-10-15 20:59"), ksa)

    assert ksa.model_dump() == before


def test_delivery_estimate_is_frozen(ksa: MarketConfig) -> None:
    estimate = estimate_delivery(_utc("2026-10-11 07:00"), ksa)
    with pytest.raises(FrozenInstanceError):
        estimate.delivery_date = date(2026, 1, 1)  # type: ignore[misc]


# --- estimate_delivery: the cutoff across a clock change ----------------------------------


@pytest.mark.parametrize(
    ("ordered_at", "local", "dispatch", "delivery"),
    [
        ("2026-10-25 00:20", "2026-10-25T01:20:00+01:00", "2026-10-25", "2026-11-01"),
        ("2026-10-25 00:40", "2026-10-25T01:40:00+01:00", "2026-10-26", "2026-11-02"),
        ("2026-10-25 01:10", "2026-10-25T01:10:00+00:00", "2026-10-26", "2026-11-02"),
        ("2026-10-25 01:40", "2026-10-25T01:40:00+00:00", "2026-10-26", "2026-11-02"),
    ],
    ids=["before-cutoff", "first-01:40", "second-01:10", "second-01:40"],
)
def test_cutoff_in_a_repeated_hour_is_its_first_occurrence(
    ksa: MarketConfig, ordered_at: str, local: str, dispatch: str, delivery: str
) -> None:
    # London's clocks go back from 02:00 to 01:00 on Sun 2026-10-25, so 01:00-02:00 happens
    # twice. With a 01:30 cutoff, an order at the second 01:10 comes after one at the first
    # 01:40, which missed the cutoff: it must not be dispatched earlier.
    market = _with_calendar(ksa, timezone="Europe/London", order_cutoff_local=time(1, 30))

    estimate = estimate_delivery(_utc(ordered_at), market)

    assert estimate.ordered_at_local.isoformat() == local
    assert estimate.dispatch_date == date.fromisoformat(dispatch)
    assert estimate.delivery_date == date.fromisoformat(delivery)


@pytest.mark.parametrize(
    ("ordered_at", "local", "dispatch", "delivery"),
    [
        ("2026-03-29 00:59:59", "2026-03-29T00:59:59+00:00", "2026-03-29", "2026-04-05"),
        ("2026-03-29 01:10", "2026-03-29T02:10:00+01:00", "2026-03-29", "2026-04-05"),
        ("2026-03-29 01:29:59", "2026-03-29T02:29:59+01:00", "2026-03-29", "2026-04-05"),
        ("2026-03-29 01:30", "2026-03-29T02:30:00+01:00", "2026-03-30", "2026-04-06"),
        ("2026-03-29 01:45", "2026-03-29T02:45:00+01:00", "2026-03-30", "2026-04-06"),
    ],
    ids=["00:59-gmt", "02:10-bst", "02:29-bst", "02:30-bst-exactly-at-cutoff", "02:45-bst"],
)
def test_cutoff_in_a_skipped_hour_falls_an_hour_later_on_the_clock(
    ksa: MarketConfig, ordered_at: str, local: str, dispatch: str, delivery: str
) -> None:
    # London's clocks go forward from 01:00 to 02:00 on Sun 2026-03-29, so 01:30 never
    # happens. The cutoff still comes 90 minutes after midnight, which the clock shows as
    # 02:30 BST: an order at 02:10 BST makes it and one at exactly 02:30 BST misses it.
    market = _with_calendar(ksa, timezone="Europe/London", order_cutoff_local=time(1, 30))

    estimate = estimate_delivery(_utc(ordered_at), market)

    assert estimate.ordered_at_local.isoformat() == local
    assert estimate.dispatch_date == date.fromisoformat(dispatch)
    assert estimate.delivery_date == date.fromisoformat(delivery)


# --- Hypothesis properties ----------------------------------------------------------------

TIMEZONES = ["Asia/Riyadh", "Asia/Dubai", "Asia/Kuwait", "Europe/London"]

FIRST_ORDER_TIME = datetime(2020, 1, 1, tzinfo=UTC)
LAST_ORDER_TIME = datetime(2035, 12, 31, 23, 59, 59, tzinfo=UTC)


def _last_sunday(year: int, month: int) -> date:
    """The last Sunday of March or October, which both have 31 days."""
    last = date(year, month, 31)
    return last - timedelta(days=(last.weekday() - 6) % 7)


# Europe/London changes its clocks at 01:00 UTC on the last Sunday of March and of October.
LONDON_CLOCK_CHANGES = [
    datetime.combine(_last_sunday(year, month), time(1), tzinfo=UTC)
    for year in range(2020, 2036)
    for month in (3, 10)
]

# Any second from 2020 to 2035, plus times within three hours of a London clock change.
ORDER_TIMES = st.one_of(
    st.integers(0, (LAST_ORDER_TIME - FIRST_ORDER_TIME) // timedelta(seconds=1)).map(
        lambda seconds: FIRST_ORDER_TIME + timedelta(seconds=seconds)
    ),
    st.builds(
        lambda change, seconds: change + timedelta(seconds=seconds),
        st.sampled_from(LONDON_CLOCK_CHANGES),
        st.integers(-3 * 3600, 3 * 3600),
    ),
)

# A later order: seconds to hours later, or up to two weeks later.
GAPS = st.one_of(st.integers(0, 3 * 3600), st.integers(0, 14 * 86400)).map(
    lambda seconds: timedelta(seconds=seconds)
)

CUTOFFS = st.one_of(
    st.sampled_from([time(0, 0), time(1, 0), time(1, 30), time(2, 0), time(14, 0), time(23, 59)]),
    st.builds(time, st.integers(0, 23), st.integers(0, 59)),
)

DATES = st.dates(min_value=date(2020, 1, 1), max_value=date(2035, 12, 31))
WEEKENDS = st.frozensets(st.integers(0, 6), max_size=6)  # at least one day is always worked
HOLIDAY_OFFSETS = st.frozensets(st.integers(-2, 45), max_size=12)  # days from a start date
COUNTS = st.integers(0, 30)


@dataclass(frozen=True)
class Scenario:
    """A generated calendar: everything ``estimate_delivery`` reads from the market config."""

    timezone: str
    weekend: frozenset[int]
    cutoff: time
    holiday_offsets: frozenset[int]  # days from the order's UTC date
    linehaul: int
    last_mile: int

    def holidays(self, ordered_at: datetime) -> frozenset[date]:
        return frozenset(ordered_at.date() + timedelta(days=n) for n in self.holiday_offsets)

    def market(self, base: MarketConfig, ordered_at: datetime) -> MarketConfig:
        """The base market with this calendar, with holidays placed around the order."""
        holidays = tuple(
            _holiday(day, provisional=day.day % 2 == 0) for day in sorted(self.holidays(ordered_at))
        )
        market = _with_calendar(
            base,
            timezone=self.timezone,
            weekend=tuple(WEEKDAYS[day] for day in sorted(self.weekend)),
            order_cutoff_local=self.cutoff,
            holidays=holidays,
        )
        return _with_business_days(market, self.linehaul, self.last_mile)


SCENARIOS = st.builds(
    Scenario,
    timezone=st.sampled_from(TIMEZONES),
    weekend=WEEKENDS,
    cutoff=CUTOFFS,
    holiday_offsets=HOLIDAY_OFFSETS,
    linehaul=st.integers(0, 10),
    last_mile=st.integers(0, 10),
)

# Always tried: a cutoff inside the hour London repeats on Sun 2026-10-25.
REPEATED_HOUR = Scenario(
    timezone="Europe/London",
    weekend=KSA_WEEKEND,
    cutoff=time(1, 30),
    holiday_offsets=frozenset(),
    linehaul=3,
    last_mile=2,
)


@given(start=DATES, n=COUNTS, weekend=WEEKENDS, offsets=HOLIDAY_OFFSETS)
def test_add_business_days_lands_on_the_nth_business_day(
    start: date, n: int, weekend: frozenset[int], offsets: frozenset[int]
) -> None:
    holidays = frozenset(start + timedelta(days=offset) for offset in offsets)

    result = add_business_days(start, n, weekend, holidays)

    assert _business_days_in(start, result, weekend, holidays) == n
    if n == 0:
        assert result == start
    else:
        assert result > start
        assert _is_working(result, weekend, holidays)
        assert is_business_day(result, weekend, holidays)


@given(start=DATES, first=COUNTS, second=COUNTS, weekend=WEEKENDS, offsets=HOLIDAY_OFFSETS)
def test_chained_calls_equal_one_call(
    start: date, first: int, second: int, weekend: frozenset[int], offsets: frozenset[int]
) -> None:
    holidays = frozenset(start + timedelta(days=offset) for offset in offsets)

    chained = add_business_days(
        add_business_days(start, first, weekend, holidays), second, weekend, holidays
    )

    assert chained == add_business_days(start, first + second, weekend, holidays)


@given(scenario=SCENARIOS, ordered_at=ORDER_TIMES)
@example(scenario=REPEATED_HOUR, ordered_at=datetime(2026, 10, 25, 1, 10, tzinfo=UTC))
def test_dispatch_and_delivery_are_never_on_a_weekend_day_or_holiday(
    config: GccConfig, scenario: Scenario, ordered_at: datetime
) -> None:
    market = scenario.market(config.markets["KSA"], ordered_at)
    weekend, holidays = scenario.weekend, scenario.holidays(ordered_at)

    estimate = estimate_delivery(ordered_at, market)

    local_date = estimate.ordered_at_local.date()
    dispatch, delivery = estimate.dispatch_date, estimate.delivery_date
    # Compared in UTC: across timezones, == is always False for a time in a repeated hour.
    assert estimate.ordered_at_local.astimezone(UTC) == ordered_at
    assert _is_working(dispatch, weekend, holidays)
    assert _is_working(delivery, weekend, holidays)
    # Dispatch is the order's local date or the first business day after it, and delivery
    # is exactly linehaul + last-mile business days after dispatch.
    assert dispatch >= local_date
    moved = int(dispatch != local_date)
    assert _business_days_in(local_date, dispatch, weekend, holidays) == moved
    assert (
        _business_days_in(dispatch, delivery, weekend, holidays)
        == scenario.linehaul + scenario.last_mile
    )


@given(scenario=SCENARIOS, first=ORDER_TIMES, gap=GAPS)
@example(
    scenario=REPEATED_HOUR,
    first=datetime(2026, 10, 25, 0, 40, tzinfo=UTC),
    gap=timedelta(minutes=30),
)
def test_later_order_never_gets_an_earlier_delivery_date(
    config: GccConfig, scenario: Scenario, first: datetime, gap: timedelta
) -> None:
    market = scenario.market(config.markets["KSA"], first)
    second = min(first + gap, LAST_ORDER_TIME)

    earlier = estimate_delivery(first, market)
    later = estimate_delivery(second, market)

    assert later.dispatch_date >= earlier.dispatch_date
    assert later.delivery_date >= earlier.delivery_date
