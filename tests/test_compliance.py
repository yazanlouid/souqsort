"""M9: screening products against each market's compliance rules (SPEC §7.6, §9.1)."""

import dataclasses

import pytest

from helpers import FOR_SALE_COUNTS, NO_ATTRIBUTES
from souqsort.compliance import ComplianceScreen, ExcludedProduct, screen_products
from souqsort.models import AttributeName, Catalogue, GccConfig, MarketConfig, Product

HEADPHONES = "ELEC-HP-001"
VANILLA = "GROC-VAN-061"
GUMMY_BEARS = "GROC-GUM-062"
ZERO_VAT_MARKET = "TEST-KWD"


def _skus(products: tuple[Product, ...]) -> list[str]:
    return [product.sku for product in products]


def _banning(market: MarketConfig, *banned: AttributeName) -> MarketConfig:
    compliance = market.compliance.model_copy(update={"banned_attributes": banned})
    return market.model_copy(update={"compliance": compliance})


@pytest.mark.parametrize(
    ("market", "expected"),
    [
        ("KSA", [(VANILLA, ("contains_alcohol",)), (GUMMY_BEARS, ("contains_pork",))]),
        ("UAE", [(GUMMY_BEARS, ("contains_pork",))]),
        ("KWT", [(VANILLA, ("contains_alcohol",)), (GUMMY_BEARS, ("contains_pork",))]),
    ],
)
def test_each_market_excludes_what_it_bans(
    catalogue: Catalogue,
    config: GccConfig,
    market: str,
    expected: list[tuple[str, tuple[str, ...]]],
) -> None:
    screen = screen_products(catalogue.products, config.markets[market])

    assert [(item.sku, item.reasons) for item in screen.excluded] == expected
    assert len(screen.sellable) == FOR_SALE_COUNTS[market]


@pytest.mark.parametrize("market", ["KSA", "UAE", "KWT"])
def test_both_lists_keep_catalogue_order_and_lose_nothing(
    catalogue: Catalogue, config: GccConfig, market: str
) -> None:
    screen = screen_products(catalogue.products, config.markets[market])

    catalogue_order = [product.sku for product in catalogue.products]
    sellable = _skus(screen.sellable)
    excluded = [item.sku for item in screen.excluded]
    assert sellable == [sku for sku in catalogue_order if sku in sellable]
    assert excluded == [sku for sku in catalogue_order if sku in excluded]
    assert sorted(sellable + excluded) == sorted(catalogue_order)  # never silently dropped


def test_sellable_products_are_the_catalogue_products_unchanged(
    catalogue: Catalogue, config: GccConfig
) -> None:
    screen = screen_products(catalogue.products, config.markets["KSA"])
    by_sku = {product.sku: product for product in catalogue.products}
    assert all(product == by_sku[product.sku] for product in screen.sellable)


def test_excluded_product_carries_its_sku_name_and_reasons(
    catalogue: Catalogue, config: GccConfig
) -> None:
    screen = screen_products(catalogue.products, config.markets["UAE"])
    assert screen.excluded == (
        ExcludedProduct(
            sku=GUMMY_BEARS, name_en="Gummy Bears (pork gelatine)", reasons=("contains_pork",)
        ),
    )


def test_a_true_attribute_the_market_does_not_ban_is_sold(
    catalogue: Catalogue, config: GccConfig
) -> None:
    headphones = next(p for p in catalogue.products if p.sku == HEADPHONES)
    assert headphones.attributes.contains_lithium_battery

    screen = screen_products([headphones], config.markets["KSA"])
    assert _skus(screen.sellable) == [HEADPHONES]
    assert screen.excluded == ()


def test_reasons_follow_the_order_the_market_lists_them(
    catalogue: Catalogue, config: GccConfig
) -> None:
    both = NO_ATTRIBUTES.model_copy(update={"contains_alcohol": True, "contains_pork": True})
    product = catalogue.products[0].model_copy(update={"attributes": both})

    pork_first = _banning(config.markets["KSA"], "contains_pork", "contains_alcohol")
    alcohol_first = _banning(config.markets["KSA"], "contains_alcohol", "contains_pork")

    assert screen_products([product], pork_first).excluded[0].reasons == (
        "contains_pork",
        "contains_alcohol",
    )
    assert screen_products([product], alcohol_first).excluded[0].reasons == (
        "contains_alcohol",
        "contains_pork",
    )


def test_a_market_that_bans_nothing_excludes_nothing(
    catalogue: Catalogue, zero_vat_config: GccConfig
) -> None:
    market = zero_vat_config.markets[ZERO_VAT_MARKET]
    assert market.compliance.banned_attributes == ()

    screen = screen_products(catalogue.products, market)
    assert screen.sellable == tuple(catalogue.products)
    assert screen.excluded == ()


def test_empty_catalogue_gives_two_empty_lists(config: GccConfig) -> None:
    assert screen_products([], config.markets["KSA"]) == ComplianceScreen(sellable=(), excluded=())


def test_results_are_frozen_and_hold_tuples(catalogue: Catalogue, config: GccConfig) -> None:
    screen = screen_products(catalogue.products, config.markets["KSA"])

    assert isinstance(screen.sellable, tuple)
    assert isinstance(screen.excluded, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        screen.excluded = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        screen.excluded[0].reasons = ()  # type: ignore[misc]
