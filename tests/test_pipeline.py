"""M5: localise_catalogue() over the sample data (SPEC §9 and §10)."""

import decimal
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest

from helpers import decimal_places
from souqsort.logistics.calendar import DeliveryEstimate, estimate_delivery
from souqsort.models import Catalogue, GccConfig, MarketConfig, Product, ProductName
from souqsort.pipeline import (
    MISSING_ARABIC_NAME,
    LocalisationError,
    LocalisedProduct,
    find_market,
    localise_catalogue,
)
from souqsort.pricing.landed_cost import PriceQuote, price_product

HEADPHONES = "ELEC-HP-001"
BAG = "FASH-BAG-014"
KETTLEBELL = "SPRT-KTB-020"
LICENCE = "DIGI-LIC-050"
TEA = "GROC-TEA-060"

ZERO_VAT_MARKET = "TEST-KWD"

THU_EVENING = datetime(2026, 10, 15, 20, 59, tzinfo=UTC)  # Thu 23:59 in Riyadh: after the cutoff
SUN_MORNING = datetime(2026, 10, 11, 7, 0, tzinfo=UTC)  # Sun 10:00 in Riyadh: before the cutoff

# Shelf prices in SAR with no duty adjustment, in catalogue order. Each gross is worked by hand
# from SPEC §7.1: cif * (1 + duty rate) * 1.15, rounded half up, then charmed up to .95.
KSA_SHELF_PRICES = {
    "ELEC-HP-001": "686.95",  # gross 686.305265625 (SPEC §7.2)
    "ELEC-CHG-002": "184.95",  # cif 153.00, gross 184.7475 -> 184.75
    "FASH-BAG-014": "594.95",  # gross 594.39471141... (SPEC §7.3)
    "FASH-SCF-015": "293.95",  # cif 228.19756711..., 12% duty, gross 293.91846644...
    "SPRT-KTB-020": "593.95",  # gross 593.184375
    "HOME-KTL-030": "237.95",  # cif 196.37416107..., gross 237.12179949...
    "BEAU-LIP-040": "16.95",  # gross 16.2106875
    "BEAU-SRM-041": "111.95",  # cif 92.025, gross 111.1201875
    "DIGI-LIC-050": "340.95",  # gross 340.6875 (0% duty, no freight)
    "GROC-TEA-060": "34.95",  # cif 28.12814597..., gross 33.96473626... -> 33.96, past 33.95
    "GROC-VAN-061": "61.95",  # cif 51.24375, gross 61.876828125 -> 61.88
    "GROC-GUM-062": "22.95",  # cif 18.42533557..., gross 22.24859270... -> 22.25
}


# --- helpers and fixtures -----------------------------------------------------------------


def _dp(value: Decimal, places: int) -> Decimal:
    """Round for comparison with the spec tables, which show a fixed number of decimals."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _by_sku(items: list[LocalisedProduct]) -> dict[str, LocalisedProduct]:
    return {item.sku: item for item in items}


def _with_market(config: GccConfig, market: MarketConfig) -> GccConfig:
    """A copy of the config with one market replaced; the original is untouched."""
    return config.model_copy(update={"markets": {**config.markets, market.code: market}})


def _without_charm(market: MarketConfig) -> MarketConfig:
    """A copy of the market with charm pricing switched off; the original is untouched."""
    currency = market.currency.model_copy(update={"charm_ending": None})
    return market.model_copy(update={"currency": currency})


@pytest.fixture
def products(catalogue: Catalogue) -> dict[str, Product]:
    return {p.sku: p for p in catalogue.products}


@pytest.fixture
def localised(catalogue: Catalogue, config: GccConfig) -> list[LocalisedProduct]:
    """The whole sample catalogue for KSA, ordered on Thursday evening."""
    return localise_catalogue(catalogue.products, config, "KSA", THU_EVENING)


# --- integration over the sample data -----------------------------------------------------


def test_every_product_is_localised_in_catalogue_order(
    catalogue: Catalogue, localised: list[LocalisedProduct]
) -> None:
    assert len(localised) == 12
    assert [item.sku for item in localised] == [p.sku for p in catalogue.products]
    assert [item.sku for item in localised] == list(KSA_SHELF_PRICES)


def test_shelf_prices_for_the_sample_catalogue(localised: list[LocalisedProduct]) -> None:
    shelf_prices = {item.sku: str(item.quote.shelf_price) for item in localised}
    assert shelf_prices == KSA_SHELF_PRICES


def test_quotes_are_for_the_requested_market(localised: list[LocalisedProduct]) -> None:
    for item in localised:
        assert isinstance(item.quote, PriceQuote)
        assert item.quote.sku == item.sku
        assert item.quote.market == "KSA"
        assert item.quote.currency == "SAR"
        assert decimal_places(item.quote.shelf_price) == 2


def test_worked_example_margins(localised: list[LocalisedProduct]) -> None:
    items = _by_sku(localised)
    assert _dp(items[HEADPHONES].quote.margin_pct, 3) == Decimal("0.587")
    assert _dp(items[BAG].quote.margin_pct, 3) == Decimal("0.646")


def test_delivery_dates_for_a_thursday_evening_order(localised: list[LocalisedProduct]) -> None:
    # SPEC §8.1 row 4: Thu 23:59 in Riyadh misses the cutoff and Fri-Sat is the weekend.
    for item in localised:
        assert isinstance(item.delivery, DeliveryEstimate)
        assert item.delivery.dispatch_date == date(2026, 10, 18)
        assert item.delivery.delivery_date == date(2026, 10, 25)
        assert item.delivery.ordered_at_local.isoformat() == "2026-10-15T23:59:00+03:00"


def test_product_details_are_carried_through(
    catalogue: Catalogue, localised: list[LocalisedProduct]
) -> None:
    for product, item in zip(catalogue.products, localised, strict=True):
        assert item.name_en == product.name.en
        assert item.name_ar == product.name.ar
        assert item.category == product.category

    headphones = _by_sku(localised)[HEADPHONES]
    assert headphones.name_en == "Wireless Noise-Cancelling Headphones"
    assert headphones.name_ar  # the Arabic name is present, not dropped
    assert headphones.category == "electronics"


# --- composition: the pipeline adds nothing to the engine's own results -------------------


def test_each_result_matches_the_engine_functions(
    catalogue: Catalogue, config: GccConfig, localised: list[LocalisedProduct]
) -> None:
    ksa = config.markets["KSA"]
    expected_delivery = estimate_delivery(THU_EVENING, ksa)

    for product, item in zip(catalogue.products, localised, strict=True):
        assert item.quote == price_product(product, ksa, config.fx)
        assert item.delivery == expected_delivery


# --- flags --------------------------------------------------------------------------------


def test_missing_arabic_name_is_flagged(localised: list[LocalisedProduct]) -> None:
    flagged = {item.sku: item.flags for item in localised if item.flags}
    assert flagged == {BAG: (MISSING_ARABIC_NAME,), TEA: (MISSING_ARABIC_NAME,)}
    assert MISSING_ARABIC_NAME == "missing_arabic_name"


def test_products_with_an_arabic_name_have_no_flags(localised: list[LocalisedProduct]) -> None:
    items = _by_sku(localised)
    assert items[BAG].name_ar is None
    assert items[HEADPHONES].flags == ()
    for item in localised:
        assert isinstance(item.flags, tuple)


@pytest.mark.parametrize("arabic", ["", "   ", "\t\n"], ids=["empty", "spaces", "whitespace"])
def test_blank_arabic_name_is_flagged(
    products: dict[str, Product], config: GccConfig, arabic: str
) -> None:
    name = ProductName(en="Wireless Noise-Cancelling Headphones", ar=arabic)
    blank = products[HEADPHONES].model_copy(update={"name": name})

    (item,) = localise_catalogue([blank], config, "KSA", THU_EVENING)

    assert item.flags == (MISSING_ARABIC_NAME,)
    assert item.name_ar == arabic  # the name is reported as given, not rewritten


# --- duty adjustment and order time are passed through ------------------------------------


def test_duty_adjustment_is_passed_to_pricing(catalogue: Catalogue, config: GccConfig) -> None:
    items = _by_sku(
        localise_catalogue(catalogue.products, config, "KSA", THU_EVENING, Decimal("0.03"))
    )

    assert str(items[HEADPHONES].quote.shelf_price) == "705.95"  # 5% + 3 points
    assert str(items[LICENCE].quote.shelf_price) == "350.95"  # 0% override + 3 points


def test_duty_adjustment_defaults_to_zero(
    catalogue: Catalogue, config: GccConfig, localised: list[LocalisedProduct]
) -> None:
    explicit = localise_catalogue(catalogue.products, config, "KSA", THU_EVENING, Decimal("0"))
    assert explicit == localised


def test_duty_adjustment_does_not_change_delivery(
    catalogue: Catalogue, config: GccConfig, localised: list[LocalisedProduct]
) -> None:
    adjusted = localise_catalogue(catalogue.products, config, "KSA", THU_EVENING, Decimal("0.20"))
    assert [item.delivery for item in adjusted] == [item.delivery for item in localised]


def test_order_time_is_passed_to_the_delivery_estimate(
    catalogue: Catalogue, config: GccConfig, localised: list[LocalisedProduct]
) -> None:
    # SPEC §8.1 row 1: Sun 10:00 in Riyadh is dispatched the same day.
    sunday = localise_catalogue(catalogue.products, config, "KSA", SUN_MORNING)

    for item in sunday:
        assert item.delivery.dispatch_date == date(2026, 10, 11)
        assert item.delivery.delivery_date == date(2026, 10, 18)
    assert [item.quote for item in sunday] == [item.quote for item in localised]


# --- markets are data ---------------------------------------------------------------------


def test_another_market_is_priced_from_its_own_config(
    catalogue: Catalogue, zero_vat_config: GccConfig
) -> None:
    items = _by_sku(
        localise_catalogue(catalogue.products, zero_vat_config, ZERO_VAT_MARKET, THU_EVENING)
    )

    headphones = items[HEADPHONES]
    assert headphones.quote.market == ZERO_VAT_MARKET
    assert headphones.quote.currency == "KWD"
    assert str(headphones.quote.shelf_price) == "48.950"
    assert headphones.quote.vat == 0
    assert headphones.delivery.ordered_at_local.isoformat() == "2026-10-15T23:59:00+03:00"
    assert len(items) == 12


def test_find_market_returns_the_configured_market(config: GccConfig) -> None:
    assert find_market(config, "KSA") is config.markets["KSA"]


def test_unknown_market_rejected(catalogue: Catalogue, config: GccConfig) -> None:
    with pytest.raises(LocalisationError) as excinfo:
        localise_catalogue(catalogue.products, config, "UAE", THU_EVENING)

    message = str(excinfo.value)
    assert message.startswith("UAE: ")
    assert "KSA" in message  # the message lists the markets that are configured


def test_find_market_and_the_pipeline_report_an_unknown_market_the_same_way(
    catalogue: Catalogue, config: GccConfig
) -> None:
    with pytest.raises(LocalisationError) as from_lookup:
        find_market(config, "UAE")
    with pytest.raises(LocalisationError) as from_pipeline:
        localise_catalogue(catalogue.products, config, "UAE", THU_EVENING)

    assert str(from_lookup.value) == str(from_pipeline.value)


def test_market_code_is_matched_exactly(catalogue: Catalogue, config: GccConfig) -> None:
    with pytest.raises(LocalisationError, match=r"^ksa: "):
        localise_catalogue(catalogue.products, config, "ksa", THU_EVENING)


# --- order time must be timezone-aware ----------------------------------------------------


def test_naive_order_time_rejected(catalogue: Catalogue, config: GccConfig) -> None:
    naive = THU_EVENING.replace(tzinfo=None)

    with pytest.raises(LocalisationError, match="timezone-aware") as excinfo:
        localise_catalogue(catalogue.products, config, "KSA", naive)

    assert str(excinfo.value).startswith("KSA: ")  # not tied to a product: names the market
    assert type(excinfo.value.__cause__) is ValueError


def test_naive_order_time_rejected_even_with_no_products(config: GccConfig) -> None:
    naive = THU_EVENING.replace(tzinfo=None)
    with pytest.raises(LocalisationError, match="timezone-aware"):
        localise_catalogue([], config, "KSA", naive)


def test_order_time_beyond_the_calendar_names_the_market(
    catalogue: Catalogue, config: GccConfig
) -> None:
    # 23:00 UTC on the last supported day is already the next year in Riyadh.
    end_of_time = datetime(9999, 12, 31, 23, 0, tzinfo=UTC)

    with pytest.raises(LocalisationError) as excinfo:
        localise_catalogue(catalogue.products, config, "KSA", end_of_time)

    assert str(excinfo.value).startswith("KSA: ")
    cause = excinfo.value.__cause__
    assert isinstance(cause, ValueError | ArithmeticError)
    assert not isinstance(cause, LocalisationError)


# --- edge cases ---------------------------------------------------------------------------


def test_empty_catalogue_gives_an_empty_list(config: GccConfig) -> None:
    assert localise_catalogue([], config, "KSA", THU_EVENING) == []


def test_single_product(products: dict[str, Product], config: GccConfig) -> None:
    (item,) = localise_catalogue([products[BAG]], config, "KSA", THU_EVENING)

    assert item.sku == BAG
    assert str(item.quote.shelf_price) == "594.95"


def test_product_that_cannot_be_priced_fails_the_run_naming_the_sku(
    products: dict[str, Product], config: GccConfig
) -> None:
    # Without charm pricing, 32 kg of freight grosses to 652.05 SAR and rounding swallows goods
    # of 0.00075 SAR (see test_landed_cost): no goods revenue, so price_product() rejects it.
    heavy_and_cheap = products[KETTLEBELL].model_copy(
        update={"base_price": Decimal("0.0002"), "weight_kg": Decimal("32.00")}
    )
    no_charm = _with_market(config, _without_charm(config.markets["KSA"]))

    with pytest.raises(LocalisationError) as excinfo:
        localise_catalogue(
            [products[HEADPHONES], heavy_and_cheap, products[BAG]], no_charm, "KSA", THU_EVENING
        )

    message = str(excinfo.value)
    assert message.startswith(f"{KETTLEBELL}: ")
    assert message.count(KETTLEBELL) == 1  # price_product() already names it: not repeated
    assert "no goods revenue" in message
    assert type(excinfo.value.__cause__) is ValueError


def test_missing_fx_rate_names_the_product_it_stopped_on(
    catalogue: Catalogue, config: GccConfig
) -> None:
    # A config needs rates only for USD and its market currencies, so GBP can be missing.
    rates = {code: rate for code, rate in config.fx.per_usd.items() if code != "GBP"}
    no_gbp = config.model_copy(update={"fx": config.fx.model_copy(update={"per_usd": rates})})

    with pytest.raises(LocalisationError, match="GBP") as excinfo:
        localise_catalogue(catalogue.products, no_gbp, "KSA", THU_EVENING)

    assert str(excinfo.value).startswith(f"{BAG}: ")  # the first GBP product in the catalogue
    assert type(excinfo.value.__cause__) is ValueError


def test_amount_too_large_for_decimal_arithmetic_names_the_sku(
    products: dict[str, Product], config: GccConfig
) -> None:
    # A gross of about 4.5E+30 SAR needs 33 digits at two decimals; the context holds 28.
    enormous = products[HEADPHONES].model_copy(update={"base_price": Decimal("1E+30")})

    with pytest.raises(LocalisationError) as excinfo:
        localise_catalogue([products[BAG], enormous], config, "KSA", THU_EVENING)

    assert str(excinfo.value).startswith(f"{HEADPHONES}: ")
    assert isinstance(excinfo.value.__cause__, decimal.InvalidOperation)


@pytest.mark.parametrize("adjustment", [0.03, 3, "0.03"], ids=["float", "int", "str"])
def test_programming_errors_are_not_wrapped(
    catalogue: Catalogue, config: GccConfig, adjustment: Any
) -> None:
    with pytest.raises(TypeError, match="Decimal"):
        localise_catalogue(catalogue.products, config, "KSA", THU_EVENING, adjustment)


@pytest.mark.parametrize("adjustment", ["-0.01", "-1", "NaN", "Infinity", "-Infinity"])
def test_bad_duty_adjustment_is_a_plain_value_error_not_tied_to_a_product(
    catalogue: Catalogue, config: GccConfig, adjustment: str
) -> None:
    with pytest.raises(ValueError, match="duty_adjustment") as excinfo:
        localise_catalogue(catalogue.products, config, "KSA", THU_EVENING, Decimal(adjustment))

    assert type(excinfo.value) is ValueError  # the caller's mistake, not a LocalisationError
    assert HEADPHONES not in str(excinfo.value)  # and not blamed on the first product


@pytest.mark.parametrize(
    ("adjustment", "error"),
    [(Decimal("-0.01"), ValueError), (Decimal("NaN"), ValueError), (0.03, TypeError)],
    ids=["negative", "NaN", "float"],
)
def test_duty_adjustment_is_checked_before_any_product_is_priced(
    config: GccConfig, adjustment: Any, error: type[Exception]
) -> None:
    with pytest.raises(error, match="duty_adjustment"):
        localise_catalogue([], config, "KSA", THU_EVENING, adjustment)


def test_localisation_error_is_a_value_error() -> None:
    assert issubclass(LocalisationError, ValueError)


def test_config_is_not_modified(catalogue: Catalogue, config: GccConfig) -> None:
    before = config.model_dump()

    localise_catalogue(catalogue.products, config, "KSA", THU_EVENING, Decimal("0.20"))

    assert config.model_dump() == before


# --- result objects -----------------------------------------------------------------------


def test_localised_product_is_frozen(localised: list[LocalisedProduct]) -> None:
    item = localised[0]
    assert isinstance(item, LocalisedProduct)
    with pytest.raises(FrozenInstanceError):
        item.sku = "OTHER"  # type: ignore[misc]
