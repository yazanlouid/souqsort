"""Pydantic models for the catalogue and the GCC market config.

Money, rates and weights are ``Decimal`` and must arrive as JSON strings. A JSON number
is rejected so that no value ever passes through a binary float.
"""

import datetime as dt
import re
from collections import Counter
from decimal import Decimal
from typing import Annotated, Any, Literal, Self, get_args
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

_HHMM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")


def _require_decimal_string(value: object) -> object:
    """Reject JSON numbers and booleans; strings and Decimals go on to Decimal parsing."""
    if isinstance(value, bool | int | float):
        raise ValueError(
            f'must be a decimal string such as "149.99", not {type(value).__name__} {value!r}'
        )
    return value


def _parse_hhmm(value: object) -> dt.time:
    if not isinstance(value, str) or not (match := _HHMM.fullmatch(value)):
        raise ValueError(f'must be a 24-hour "HH:MM" string such as "14:00", got {value!r}')
    return dt.time(int(match[1]), int(match[2]))


DecimalStr = Annotated[Decimal, BeforeValidator(_require_decimal_string)]
PositiveDecimal = Annotated[DecimalStr, Field(gt=0)]
NonNegativeDecimal = Annotated[DecimalStr, Field(ge=0)]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]
NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
HsCode = Annotated[str, StringConstraints(pattern=r"^\d{6,10}$")]
HhMm = Annotated[dt.time, BeforeValidator(_parse_hhmm)]
Weekday = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- catalogue ----------------------------------------------------------------------------


class ProductName(_Model):
    en: NonEmptyStr
    ar: str | None


class Product(_Model):
    sku: NonEmptyStr
    name: ProductName
    category: NonEmptyStr
    hs_code: HsCode
    base_price: PositiveDecimal
    currency: Literal["USD", "GBP"]
    unit_cost: PositiveDecimal
    weight_kg: NonNegativeDecimal
    attributes: dict[str, StrictBool]


class Catalogue(_Model):
    catalogue_version: NonEmptyStr
    products: list[Product]

    @model_validator(mode="after")
    def _unique_skus(self) -> Self:
        counts = Counter(p.sku for p in self.products)
        duplicates = sorted(sku for sku, n in counts.items() if n > 1)
        if duplicates:
            raise ValueError(f"duplicate sku: {', '.join(duplicates)}")
        return self


# --- market config ------------------------------------------------------------------------


class FxTable(_Model):
    """Exchange rates as units of each currency per 1 USD."""

    as_of: dt.date
    source: str
    per_usd: dict[CurrencyCode, PositiveDecimal]

    @model_validator(mode="after")
    def _usd_is_base(self) -> Self:
        if self.per_usd.get("USD") != 1:
            raise ValueError("per_usd must contain USD with a rate of 1 (rates are per 1 USD)")
        return self


class CurrencyConfig(_Model):
    code: CurrencyCode
    minor_units: NonNegativeInt
    charm_ending: NonNegativeDecimal | None

    @model_validator(mode="after")
    def _charm_ending_fits_currency(self) -> Self:
        ending = self.charm_ending
        if ending is None:
            return self
        if ending >= 1:
            raise ValueError(f"charm_ending must be less than 1, got {ending}")
        if ending != ending.quantize(Decimal(1).scaleb(-self.minor_units)):
            raise ValueError(
                f"charm_ending {ending} has more decimals than minor_units ({self.minor_units})"
            )
        return self


class TaxConfig(_Model):
    vat_rate: NonNegativeDecimal
    source: str
    effective_from: dt.date


class CustomsConfig(_Model):
    default_duty_rate: NonNegativeDecimal
    category_overrides: dict[str, NonNegativeDecimal]


class Holiday(_Model):
    date: dt.date
    name: NonEmptyStr
    provisional: StrictBool


class CalendarConfig(_Model):
    timezone: str
    weekend: tuple[Weekday, ...]
    order_cutoff_local: HhMm
    holidays: tuple[Holiday, ...]

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise ValueError(f"unknown IANA timezone {value!r}") from exc
        return value

    @field_validator("weekend")
    @classmethod
    def _no_duplicate_days(cls, value: tuple[Weekday, ...]) -> tuple[Weekday, ...]:
        duplicates = sorted(day for day, n in Counter(value).items() if n > 1)
        if duplicates:
            raise ValueError(f"duplicate weekend day: {', '.join(duplicates)}")
        return value

    @field_validator("weekend")
    @classmethod
    def _leaves_a_business_day(cls, value: tuple[Weekday, ...]) -> tuple[Weekday, ...]:
        if set(value) == set(get_args(Weekday)):
            raise ValueError("weekend covers all seven days, leaving no business day")
        return value


class LogisticsConfig(_Model):
    freight_per_kg_usd: NonNegativeDecimal
    linehaul_business_days: NonNegativeInt
    last_mile_business_days: NonNegativeInt


class MarketConfig(_Model):
    code: NonEmptyStr
    name: NonEmptyStr
    currency: CurrencyConfig
    tax: TaxConfig
    customs: CustomsConfig
    calendar: CalendarConfig
    logistics: LogisticsConfig


class GccConfig(_Model):
    config_version: NonEmptyStr
    fx: FxTable
    markets: dict[str, MarketConfig]

    @model_validator(mode="before")
    @classmethod
    def _codes_from_keys(cls, data: Any) -> Any:
        """Fill each market's ``code`` from its key in ``markets`` (without mutating input)."""
        if not isinstance(data, dict) or not isinstance(data.get("markets"), dict):
            return data
        markets: dict[str, Any] = {}
        for code, market in data["markets"].items():
            if isinstance(market, dict):
                if market.get("code", code) != code:
                    raise ValueError(f"market {code!r} has a conflicting code {market['code']!r}")
                market = {**market, "code": code}
            markets[code] = market
        return {**data, "markets": markets}

    @model_validator(mode="after")
    def _market_currencies_have_fx(self) -> Self:
        for code, market in self.markets.items():
            if market.currency.code not in self.fx.per_usd:
                raise ValueError(
                    f"market {code}: currency {market.currency.code} is not in fx.per_usd"
                )
        return self
