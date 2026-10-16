"""M5: localise_catalogue() over the sample data (SPEC §9 and §10)."""

import decimal
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest

from helpers import FOR_SALE_COUNTS, SAMPLE_PRODUCT_COUNT, decimal_places
from souqsort.compliance import screen_products
from souqsort.logistics.calendar import DeliveryEstimate, estimate_delivery
from souqsort.models import Catalogue, GccConfig, MarketConfig, Product, ProductName
from souqsort.pipeline import (
    MAX_DUTY_ADJUST_POINTS,
    MISSING_ARABIC_NAME,
    CatalogueSummary,
    LocalisationError,
    LocalisedCatalogue,
    LocalisedProduct,
    duty_adjustment_from_points,
    find_market,
    localise_and_summarise,
    localise_catalogue,
    summarise_catalogue,
)
from souqsort.pricing.landed_cost import PriceQuote, price_product

HEADPHONES = "ELEC-HP-001"
BAG = "FASH-BAG-014"
KETTLEBELL = "SPRT-KTB-020"
LIP_BALM = "BEAU-LIP-040"
LICENCE = "DIGI-LIC-050"
TEA = "GROC-TEA-060"
VANILLA = "GROC-VAN-061"
GUMMY_BEARS = "GROC-GUM-062"

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
    "HOME-ESP-031": "4144.95",  # cif 3432.15352348..., gross 4144.32537961... -> 4144.33
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
def for_sale(catalogue: Catalogue) -> list[Product]:
    """The sample products KSA sells: all but the vanilla extract and the gummy bears."""
    return [p for p in catalogue.products if p.sku not in (VANILLA, GUMMY_BEARS)]


@pytest.fixture
def localised(catalogue: Catalogue, config: GccConfig) -> list[LocalisedProduct]:
    """The whole sample catalogue for KSA, ordered on Thursday evening."""
    return localise_catalogue(catalogue.products, config, "KSA", THU_EVENING)


@pytest.fixture
def plus_three_points(catalogue: Catalogue, config: GccConfig) -> list[LocalisedProduct]:
    """The same catalogue and order time with 3 percentage points added to every duty rate."""
    return localise_catalogue(catalogue.products, config, "KSA", THU_EVENING, Decimal("0.03"))


# --- integration over the sample data -----------------------------------------------------


def test_every_product_is_localised_in_catalogue_order(
    catalogue: Catalogue, localised: list[LocalisedProduct]
) -> None:
    assert len(localised) == SAMPLE_PRODUCT_COUNT
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
    assert len(items) == SAMPLE_PRODUCT_COUNT


def test_find_market_returns_the_configured_market(config: GccConfig) -> None:
    assert find_market(config, "KSA") is config.markets["KSA"]


def test_unknown_market_rejected(catalogue: Catalogue, config: GccConfig) -> None:
    with pytest.raises(LocalisationError) as excinfo:
        localise_catalogue(catalogue.products, config, "ZZZ", THU_EVENING)

    message = str(excinfo.value)
    assert message.startswith("ZZZ: ")
    assert "KSA" in message  # the message lists the markets that are configured


def test_find_market_and_the_pipeline_report_an_unknown_market_the_same_way(
    catalogue: Catalogue, config: GccConfig
) -> None:
    with pytest.raises(LocalisationError) as from_lookup:
        find_market(config, "ZZZ")
    with pytest.raises(LocalisationError) as from_pipeline:
        localise_catalogue(catalogue.products, config, "ZZZ", THU_EVENING)

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


# --- duty adjustment in whole percentage points (SPEC §7.4) -------------------------------


def test_the_duty_adjustment_goes_up_to_twenty_points() -> None:
    assert MAX_DUTY_ADJUST_POINTS == 20


@pytest.mark.parametrize(("points", "fraction"), [(0, "0"), (1, "0.01"), (3, "0.03"), (20, "0.2")])
def test_whole_points_become_a_decimal_fraction(points: int, fraction: str) -> None:
    result = duty_adjustment_from_points(points)

    assert isinstance(result, Decimal)
    assert result == Decimal(fraction)


def test_points_price_the_same_as_the_fraction(
    catalogue: Catalogue, config: GccConfig, plus_three_points: list[LocalisedProduct]
) -> None:
    from_points = localise_catalogue(
        catalogue.products, config, "KSA", THU_EVENING, duty_adjustment_from_points(3)
    )
    assert from_points == plus_three_points


@pytest.mark.parametrize("points", [-1, 21, 100])
def test_points_outside_0_to_20_rejected(points: int) -> None:
    with pytest.raises(ValueError, match="0 to 20"):
        duty_adjustment_from_points(points)


@pytest.mark.parametrize(
    "points", [2.5, 3.0, "3", Decimal("3"), True, None], ids=lambda v: type(v).__name__ + str(v)
)
def test_points_that_are_not_a_whole_number_rejected(points: Any) -> None:
    # A float could only come from a front end that let fractions of a point through.
    with pytest.raises(TypeError, match="whole number"):
        duty_adjustment_from_points(points)


# --- summary: the dashboard's headline figures --------------------------------------------


def test_summary_counts_products_and_flagged_products(localised: list[LocalisedProduct]) -> None:
    summary = summarise_catalogue(localised, localised)

    assert isinstance(summary, CatalogueSummary)
    assert summary.product_count == SAMPLE_PRODUCT_COUNT
    assert summary.flagged_count == 2  # the bag and the tea have no Arabic name


def test_average_margin_is_the_unweighted_mean(localised: list[LocalisedProduct]) -> None:
    summary = summarise_catalogue(localised, localised)

    assert summary.average_margin_pct == (
        sum(item.quote.margin_pct for item in localised) / SAMPLE_PRODUCT_COUNT
    )
    assert summary.average_margin_pct is not None
    assert _dp(summary.average_margin_pct, 3) == Decimal("0.656")


def test_average_margin_of_the_worked_examples(localised: list[LocalisedProduct]) -> None:
    items = _by_sku(localised)
    pair = [items[HEADPHONES], items[BAG]]

    summary = summarise_catalogue(pair, pair)

    # (0.58705... + 0.64644...) / 2, from SPEC §7.2 and §7.3.
    assert summary.average_margin_pct is not None
    assert _dp(summary.average_margin_pct, 3) == Decimal("0.617")


def test_price_change_against_itself_is_exactly_zero(localised: list[LocalisedProduct]) -> None:
    assert summarise_catalogue(localised, localised).average_price_change_pct == 0


def test_price_change_is_the_mean_of_each_products_change(
    localised: list[LocalisedProduct], plus_three_points: list[LocalisedProduct]
) -> None:
    # Headphones 686.95 -> 705.95 is +2.7658...%; the licence 340.95 -> 350.95 is +2.9330...%.
    skus = (HEADPHONES, LICENCE)
    before = [_by_sku(localised)[sku] for sku in skus]
    after = [_by_sku(plus_three_points)[sku] for sku in skus]

    summary = summarise_catalogue(after, before)

    assert summary.average_price_change_pct is not None
    assert _dp(summary.average_price_change_pct, 6) == Decimal("0.028494")


def test_price_change_is_not_weighted_by_price(
    localised: list[LocalisedProduct], plus_three_points: list[LocalisedProduct]
) -> None:
    # The lip balm stays at 16.95, so the mean is half the headphones' +2.766%. Weighted by
    # price (19.00 on a basket of 703.90) it would be +2.70%.
    skus = (HEADPHONES, LIP_BALM)
    before = [_by_sku(localised)[sku] for sku in skus]
    after = [_by_sku(plus_three_points)[sku] for sku in skus]
    assert after[1].quote.shelf_price == before[1].quote.shelf_price

    summary = summarise_catalogue(after, before)

    assert summary.average_price_change_pct is not None
    assert _dp(summary.average_price_change_pct, 4) == Decimal("0.0138")


def test_summary_of_the_sample_catalogue_at_three_points(
    localised: list[LocalisedProduct], plus_three_points: list[LocalisedProduct]
) -> None:
    summary = summarise_catalogue(plus_three_points, localised)

    assert summary.product_count == SAMPLE_PRODUCT_COUNT
    assert summary.flagged_count == 2
    assert summary.average_margin_pct is not None
    assert summary.average_price_change_pct is not None
    assert _dp(summary.average_price_change_pct, 4) == Decimal("0.0219")
    # The margin is the adjusted catalogue's own, not the baseline's: 65.3%, down from 65.6%.
    assert summary.average_margin_pct == (
        sum(item.quote.margin_pct for item in plus_three_points) / SAMPLE_PRODUCT_COUNT
    )
    assert _dp(summary.average_margin_pct, 3) == Decimal("0.653")


def test_price_change_never_falls_as_the_duty_adjustment_rises(
    catalogue: Catalogue, config: GccConfig, localised: list[LocalisedProduct]
) -> None:
    changes = []
    for points in range(MAX_DUTY_ADJUST_POINTS + 1):
        adjusted = localise_catalogue(
            catalogue.products, config, "KSA", THU_EVENING, duty_adjustment_from_points(points)
        )
        change = summarise_catalogue(adjusted, localised).average_price_change_pct
        assert change is not None
        changes.append(change)

    assert changes[0] == 0
    assert changes == sorted(changes)
    assert changes[-1] > changes[1] > 0  # it reacts from the first point on


def test_averages_keep_full_precision(
    localised: list[LocalisedProduct], plus_three_points: list[LocalisedProduct]
) -> None:
    summary = summarise_catalogue(plus_three_points, localised)

    assert isinstance(summary.average_margin_pct, Decimal)
    assert isinstance(summary.average_price_change_pct, Decimal)
    assert decimal_places(summary.average_margin_pct) > 10  # rounded only where it is shown
    assert decimal_places(summary.average_price_change_pct) > 10


def test_summary_of_an_empty_catalogue_has_no_averages() -> None:
    assert summarise_catalogue([], []) == CatalogueSummary(
        product_count=0,
        flagged_count=0,
        average_margin_pct=None,
        average_price_change_pct=None,
    )


def test_baseline_for_other_products_rejected(localised: list[LocalisedProduct]) -> None:
    with pytest.raises(ValueError, match="baseline"):
        summarise_catalogue(localised, localised[:-1])
    with pytest.raises(ValueError, match="baseline"):
        summarise_catalogue(localised[:1], localised[1:2])


def test_baseline_in_another_order_rejected(localised: list[LocalisedProduct]) -> None:
    # Paired by position: a reordered baseline would compare each product with another one.
    with pytest.raises(ValueError, match="baseline") as excinfo:
        summarise_catalogue(localised, localised[::-1])

    assert HEADPHONES in str(excinfo.value)  # the first pair that does not match


def test_baseline_with_a_zero_shelf_price_rejected(localised: list[LocalisedProduct]) -> None:
    # price_product() never returns a zero price, but a hand-built baseline could hold one.
    headphones = localised[0]
    free = replace(headphones, quote=replace(headphones.quote, shelf_price=Decimal("0.00")))

    with pytest.raises(ValueError, match="baseline") as excinfo:
        summarise_catalogue([headphones], [free])

    assert type(excinfo.value) is ValueError  # not decimal.DivisionByZero
    assert HEADPHONES in str(excinfo.value)


def test_summary_is_frozen(localised: list[LocalisedProduct]) -> None:
    summary = summarise_catalogue(localised, localised)
    with pytest.raises(FrozenInstanceError):
        summary.flagged_count = 0  # type: ignore[misc]


# --- localise and summarise in one call ---------------------------------------------------


def test_localise_and_summarise_returns_the_items_and_their_summary(
    for_sale: list[Product], config: GccConfig
) -> None:
    adjusted = localise_catalogue(for_sale, config, "KSA", THU_EVENING, Decimal("0.03"))
    baseline = localise_catalogue(for_sale, config, "KSA", THU_EVENING)

    result = localise_and_summarise(for_sale, config, "KSA", THU_EVENING, Decimal("0.03"))

    assert isinstance(result, LocalisedCatalogue)
    assert list(result.items) == adjusted
    # The baseline is the same products, market and order time with no duty adjustment.
    assert result.summary == summarise_catalogue(adjusted, baseline)
    assert result.summary.average_price_change_pct is not None
    assert result.summary.average_price_change_pct > 0


def test_localise_and_summarise_without_an_adjustment(
    for_sale: list[Product], config: GccConfig
) -> None:
    items = localise_catalogue(for_sale, config, "KSA", THU_EVENING)

    result = localise_and_summarise(for_sale, config, "KSA", THU_EVENING)

    assert list(result.items) == items
    assert result.summary == summarise_catalogue(items, items)
    assert result.summary.average_price_change_pct == 0


def test_localise_and_summarise_builds_the_baseline_for_the_same_market_and_order_time(
    catalogue: Catalogue, zero_vat_config: GccConfig
) -> None:
    arguments = (catalogue.products, zero_vat_config, ZERO_VAT_MARKET, SUN_MORNING)
    adjusted = localise_catalogue(*arguments, Decimal("0.20"))
    baseline = localise_catalogue(*arguments)

    result = localise_and_summarise(*arguments, Decimal("0.20"))

    assert list(result.items) == adjusted
    assert result.summary == summarise_catalogue(adjusted, baseline)
    assert {item.quote.currency for item in result.items} == {"KWD"}
    assert {item.delivery.delivery_date for item in result.items} == {date(2026, 10, 18)}


def test_localise_and_summarise_of_an_empty_catalogue(config: GccConfig) -> None:
    result = localise_and_summarise([], config, "KSA", THU_EVENING, Decimal("0.03"))

    assert result.items == ()
    assert result.excluded == ()
    assert result.summary == CatalogueSummary(0, 0, None, None)


def test_localise_and_summarise_fails_as_localise_catalogue_does(
    catalogue: Catalogue, config: GccConfig
) -> None:
    with pytest.raises(LocalisationError, match=r"^ZZZ: "):
        localise_and_summarise(catalogue.products, config, "ZZZ", THU_EVENING)
    with pytest.raises(LocalisationError, match="timezone-aware"):
        localise_and_summarise(catalogue.products, config, "KSA", THU_EVENING.replace(tzinfo=None))
    with pytest.raises(ValueError, match="duty_adjustment") as excinfo:
        localise_and_summarise(catalogue.products, config, "KSA", THU_EVENING, Decimal("-0.01"))
    assert type(excinfo.value) is ValueError
    a_float: Any = 0.03
    with pytest.raises(TypeError, match="Decimal"):
        localise_and_summarise(catalogue.products, config, "KSA", THU_EVENING, a_float)


def test_localise_and_summarise_names_a_product_that_cannot_be_priced(
    products: dict[str, Product], config: GccConfig
) -> None:
    enormous = products[HEADPHONES].model_copy(update={"base_price": Decimal("1E+30")})

    with pytest.raises(LocalisationError, match=f"^{HEADPHONES}: "):
        localise_and_summarise([products[BAG], enormous], config, "KSA", THU_EVENING)


def test_localised_catalogue_is_frozen_and_its_items_are_a_tuple(
    catalogue: Catalogue, config: GccConfig
) -> None:
    result = localise_and_summarise(catalogue.products, config, "KSA", THU_EVENING)

    assert isinstance(result.items, tuple)
    with pytest.raises(FrozenInstanceError):
        result.items = ()  # type: ignore[misc]


def test_localise_and_summarise_does_not_modify_the_config(
    catalogue: Catalogue, config: GccConfig
) -> None:
    before = config.model_dump()

    localise_and_summarise(catalogue.products, config, "KSA", THU_EVENING, Decimal("0.20"))

    assert config.model_dump() == before


# --- compliance: screened before pricing (SPEC §7.6, M9) ----------------------------------


@pytest.mark.parametrize("market", ["KSA", "UAE", "KWT"])
def test_localise_and_summarise_prices_only_what_the_market_sells(
    catalogue: Catalogue, config: GccConfig, market: str
) -> None:
    screen = screen_products(catalogue.products, config.markets[market])

    result = localise_and_summarise(catalogue.products, config, market, THU_EVENING)

    assert [item.sku for item in result.items] == [p.sku for p in screen.sellable]
    assert result.excluded == screen.excluded
    assert len(result.items) == FOR_SALE_COUNTS[market]
    assert result.summary.product_count == FOR_SALE_COUNTS[market]


def test_ksa_reports_two_products_as_not_sold(
    catalogue: Catalogue, config: GccConfig, for_sale: list[Product]
) -> None:
    adjusted = localise_catalogue(for_sale, config, "KSA", THU_EVENING, Decimal("0.03"))
    baseline = localise_catalogue(for_sale, config, "KSA", THU_EVENING)

    result = localise_and_summarise(catalogue.products, config, "KSA", THU_EVENING, Decimal("0.03"))

    assert len(result.items) == 11
    assert [(item.sku, item.reasons) for item in result.excluded] == [
        (VANILLA, ("contains_alcohol",)),
        (GUMMY_BEARS, ("contains_pork",)),
    ]
    # The summary and its baseline cover the same 11 products, and nothing else.
    assert list(result.items) == adjusted
    assert result.summary == summarise_catalogue(adjusted, baseline)
    assert result.summary.flagged_count == 2  # the bag and the tea are both for sale


def test_a_catalogue_of_only_banned_products_gives_no_items(
    products: dict[str, Product], config: GccConfig
) -> None:
    result = localise_and_summarise(
        [products[VANILLA], products[GUMMY_BEARS]], config, "KSA", THU_EVENING
    )

    assert result.items == ()
    assert [item.sku for item in result.excluded] == [VANILLA, GUMMY_BEARS]
    assert result.summary == CatalogueSummary(0, 0, None, None)


def test_arguments_and_market_are_checked_before_screening(
    products: dict[str, Product], config: GccConfig
) -> None:
    banned_only = [products[VANILLA], products[GUMMY_BEARS]]
    a_float: Any = 0.03

    with pytest.raises(ValueError, match="duty_adjustment") as excinfo:
        localise_and_summarise(banned_only, config, "ZZZ", THU_EVENING, Decimal("-0.01"))
    assert type(excinfo.value) is ValueError  # the adjustment first, then the market
    with pytest.raises(TypeError, match="Decimal"):
        localise_and_summarise(banned_only, config, "ZZZ", THU_EVENING, a_float)
    with pytest.raises(LocalisationError, match=r"^ZZZ: unknown market"):
        localise_and_summarise(banned_only, config, "ZZZ", THU_EVENING)


def test_a_banned_product_that_cannot_be_priced_does_not_fail_the_run(
    products: dict[str, Product], config: GccConfig
) -> None:
    # Screened out first, so it is never priced: its absurd price cannot stop the run.
    enormous = products[VANILLA].model_copy(update={"base_price": Decimal("1E+30")})

    result = localise_and_summarise([products[BAG], enormous], config, "KSA", THU_EVENING)

    assert [item.sku for item in result.items] == [BAG]
    assert [item.sku for item in result.excluded] == [VANILLA]


def test_localise_catalogue_still_prices_what_it_is_given(
    catalogue: Catalogue, config: GccConfig
) -> None:
    items = _by_sku(localise_catalogue(catalogue.products, config, "KSA", THU_EVENING))

    assert len(items) == SAMPLE_PRODUCT_COUNT
    assert str(items[VANILLA].quote.shelf_price) == KSA_SHELF_PRICES[VANILLA]
    assert str(items[GUMMY_BEARS].quote.shelf_price) == KSA_SHELF_PRICES[GUMMY_BEARS]


def test_excluded_is_a_tuple(catalogue: Catalogue, config: GccConfig) -> None:
    result = localise_and_summarise(catalogue.products, config, "KSA", THU_EVENING)
    assert isinstance(result.excluded, tuple)
    with pytest.raises(FrozenInstanceError):
        result.excluded = ()  # type: ignore[misc]


# --- result objects -----------------------------------------------------------------------


def test_localised_product_is_frozen(localised: list[LocalisedProduct]) -> None:
    item = localised[0]
    assert isinstance(item, LocalisedProduct)
    with pytest.raises(FrozenInstanceError):
        item.sku = "OTHER"  # type: ignore[misc]
