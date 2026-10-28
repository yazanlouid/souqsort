"""M10: de minimis, duty assessment and direct-parcel pricing (SPEC §7.7 and §7.8 E-H)."""

from dataclasses import FrozenInstanceError, replace
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any, get_args

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from helpers import NO_ATTRIBUTES
from souqsort.models import (
    AttributeName,
    Catalogue,
    DeMinimisRule,
    FxTable,
    GccConfig,
    MarketConfig,
    Product,
    ProductAttributes,
    ProductName,
)
from souqsort.pricing.customs import (
    DutyAssessment,
    assess_duty,
    de_minimis_applies,
    duty_rate,
    parcel_fee_due,
    sends_parcel,
    travels,
    within_threshold,
)
from souqsort.pricing.landed_cost import price_product

HEADPHONES = "ELEC-HP-001"
BAG = "FASH-BAG-014"
ESPRESSO = "HOME-ESP-031"
VANILLA = "GROC-VAN-061"
LICENCE = "DIGI-LIC-050"

BELOW = "TEST-BELOW"
AT_OR_BELOW = "TEST-AT-OR-BELOW"

ALCOHOL = ProductAttributes(
    contains_alcohol=True, contains_pork=False, contains_lithium_battery=False
)
LITHIUM = ProductAttributes(
    contains_alcohol=False, contains_pork=False, contains_lithium_battery=True
)


def _dp(value: Decimal, places: int) -> Decimal:
    """Round for comparison with the spec tables, which show a fixed number of decimals."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _cut(value: Decimal, places: int) -> Decimal:
    """Cut to ``places`` decimals, as the spec prints a long value followed by "..."."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)


def _rule(applies: str, *excluded: AttributeName) -> DeMinimisRule:
    return DeMinimisRule(
        threshold=Decimal("1000.00"),
        applies=applies,  # type: ignore[arg-type]
        excluded_attributes=excluded,
        source="test rule",
    )


def _usd_product(
    base_price: str,
    attributes: ProductAttributes = NO_ATTRIBUTES,
    weight_kg: str = "1",
) -> Product:
    """A USD product. Freight is 0 in the boundary markets, so its CIF there is 4 x its price.

    It weighs 1 kg by default, so it travels in a parcel (SPEC §7.8 H, from M15).
    """
    return Product(
        sku="TEST-H",
        name=ProductName(en="Boundary test product", ar=None),
        category="test",
        hs_code="851830",
        base_price=Decimal(base_price),
        currency="USD",
        unit_cost=Decimal("1.00"),
        weight_kg=Decimal(weight_kg),
        attributes=attributes,
    )


@pytest.fixture
def products(catalogue: Catalogue) -> dict[str, Product]:
    return {p.sku: p for p in catalogue.products}


@pytest.fixture
def ksa(config: GccConfig) -> MarketConfig:
    return config.markets["KSA"]


@pytest.fixture
def uae(config: GccConfig) -> MarketConfig:
    return config.markets["UAE"]


@pytest.fixture
def fx(config: GccConfig) -> FxTable:
    return config.fx


# --- de_minimis_applies (SPEC §7.7.2) ------------------------------------------------------

# SPEC §7.8 H: CIF against a 1,000.00 threshold, for "below" and "at_or_below".
THRESHOLD_CELLS = [
    ("999.96", True, True),
    ("1000.00", False, True),
    ("1000.04", False, False),
]


@pytest.mark.parametrize(("cif", "below", "at_or_below"), THRESHOLD_CELLS)
def test_threshold_cells(cif: str, below: bool, at_or_below: bool) -> None:
    assert de_minimis_applies(Decimal(cif), _rule("below"), NO_ATTRIBUTES) is below
    assert de_minimis_applies(Decimal(cif), _rule("at_or_below"), NO_ATTRIBUTES) is at_or_below


def test_cif_is_compared_at_full_precision() -> None:
    # 999.995 would round to 1000.00, but de minimis looks at the unrounded CIF.
    assert de_minimis_applies(Decimal("999.995"), _rule("below"), NO_ATTRIBUTES) is True
    assert de_minimis_applies(Decimal("1000.0001"), _rule("at_or_below"), NO_ATTRIBUTES) is False


def test_no_rule_never_applies() -> None:
    assert de_minimis_applies(Decimal("1"), None, NO_ATTRIBUTES) is False


def test_a_true_excluded_attribute_stops_it_applying() -> None:
    rule = _rule("at_or_below", "contains_alcohol")
    assert de_minimis_applies(Decimal("50"), rule, ALCOHOL) is False


def test_an_excluded_attribute_that_is_false_does_not_matter() -> None:
    rule = _rule("at_or_below", "contains_alcohol")
    assert de_minimis_applies(Decimal("50"), rule, LITHIUM) is True


RULES = st.builds(
    DeMinimisRule,
    threshold=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000"), places=2),
    applies=st.sampled_from(["below", "at_or_below"]),
    excluded_attributes=st.lists(st.sampled_from(get_args(AttributeName)), unique=True).map(tuple),
    source=st.just("generated rule"),
)
ATTRIBUTES = st.builds(
    ProductAttributes,
    contains_alcohol=st.booleans(),
    contains_pork=st.booleans(),
    contains_lithium_battery=st.booleans(),
)
CIFS = st.decimals(min_value=Decimal("0"), max_value=Decimal("200000"), places=6)


@given(rule=RULES, attributes=ATTRIBUTES, cifs=st.tuples(CIFS, CIFS))
@example(
    rule=_rule("below"), attributes=NO_ATTRIBUTES, cifs=(Decimal("999.99"), Decimal("1000.00"))
)
def test_if_it_applies_at_a_cif_it_applies_at_every_lower_cif(
    rule: DeMinimisRule, attributes: ProductAttributes, cifs: tuple[Decimal, Decimal]
) -> None:
    lower, higher = sorted(cifs)
    if de_minimis_applies(higher, rule, attributes):
        assert de_minimis_applies(lower, rule, attributes)


# --- within_threshold (SPEC §7.10.1 rule 5, M16) -------------------------------------------


@pytest.mark.parametrize(("value", "below", "at_or_below"), THRESHOLD_CELLS)
def test_within_threshold_cells(value: str, below: bool, at_or_below: bool) -> None:
    assert within_threshold(Decimal(value), _rule("below")) is below
    assert within_threshold(Decimal(value), _rule("at_or_below")) is at_or_below


def test_within_threshold_compares_at_full_precision() -> None:
    assert within_threshold(Decimal("999.995"), _rule("below")) is True
    assert within_threshold(Decimal("1000.0001"), _rule("at_or_below")) is False


def test_within_threshold_ignores_excluded_attributes() -> None:
    # The exclusions are about a product; the threshold test is about a value.
    assert within_threshold(Decimal("50"), _rule("below", "contains_alcohol")) is True


@given(rule=RULES, value=CIFS, attributes=ATTRIBUTES)
def test_de_minimis_applies_is_the_threshold_test_without_exclusions(
    rule: DeMinimisRule, value: Decimal, attributes: ProductAttributes
) -> None:
    excluded = any(attributes.has(name) for name in rule.excluded_attributes)
    expected = within_threshold(value, rule) and not excluded
    assert de_minimis_applies(value, rule, attributes) is expected


# --- duty_rate (SPEC §7.10.1 rule 5, M16) ----------------------------------------------------


@pytest.mark.parametrize(
    ("sku", "adjustment", "expected"),
    [
        (HEADPHONES, "0", "0.05"),  # no override: the market default
        (HEADPHONES, "0.03", "0.08"),
        (BAG, "0", "0.12"),  # fashion's override
        (BAG, "0.03", "0.15"),
        (LICENCE, "0.03", "0.03"),  # digital is 0, plus the adjustment
    ],
)
def test_duty_rate_is_the_category_rate_plus_the_adjustment(
    products: dict[str, Product], ksa: MarketConfig, sku: str, adjustment: str, expected: str
) -> None:
    assert duty_rate(products[sku], ksa, Decimal(adjustment)) == Decimal(expected)


def test_duty_rate_ignores_de_minimis(products: dict[str, Product], ksa: MarketConfig) -> None:
    # A waived parcel's quote has rate 0; duty_rate is what it would pay without the waiver.
    headphones = products[HEADPHONES]
    cif = Decimal("574.275")
    assert assess_duty(headphones, ksa, cif, Decimal(0), "parcel").rate == 0
    assert duty_rate(headphones, ksa, Decimal(0)) == Decimal("0.05")


# --- travels (SPEC §7.7.2, M15) ------------------------------------------------------------


def test_only_the_licence_does_not_travel(catalogue: Catalogue) -> None:
    assert [p.sku for p in catalogue.products if not travels(p)] == [LICENCE]


@pytest.mark.parametrize(("weight", "expected"), [("0", False), ("0.000", False), ("0.001", True)])
def test_a_product_travels_when_it_weighs_more_than_nothing(weight: str, expected: bool) -> None:
    assert travels(_usd_product("10.00", weight_kg=weight)) is expected


# --- assess_duty ---------------------------------------------------------------------------


def test_consolidated_never_waives_duty(products: dict[str, Product], ksa: MarketConfig) -> None:
    assessment = assess_duty(products[HEADPHONES], ksa, Decimal("10"), Decimal("0"), "consolidated")
    assert assessment == DutyAssessment(rate=Decimal("0.05"), waived=False)


@pytest.mark.parametrize("adjustment", ["0", "0.03", "0.20"])
def test_a_waived_parcel_pays_no_duty_at_any_adjustment(
    products: dict[str, Product], ksa: MarketConfig, adjustment: str
) -> None:
    assessment = assess_duty(
        products[HEADPHONES], ksa, Decimal("574.275"), Decimal(adjustment), "parcel"
    )
    assert assessment == DutyAssessment(rate=Decimal("0"), waived=True)


def test_a_parcel_above_the_threshold_pays_the_category_rate_plus_the_adjustment(
    products: dict[str, Product], ksa: MarketConfig
) -> None:
    assessment = assess_duty(products[BAG], ksa, Decimal("1000.00"), Decimal("0.03"), "parcel")
    assert assessment == DutyAssessment(rate=Decimal("0.15"), waived=False)  # 12% + 3 pp


def test_a_parcel_in_a_market_without_de_minimis_pays_duty(
    products: dict[str, Product], config: GccConfig
) -> None:
    assessment = assess_duty(
        products[HEADPHONES], config.markets["KWT"], Decimal("1"), Decimal("0"), "parcel"
    )
    assert assessment == DutyAssessment(rate=Decimal("0.05"), waived=False)


def test_duty_assessment_is_frozen() -> None:
    assessment = DutyAssessment(rate=Decimal("0.05"), waived=False)
    with pytest.raises(FrozenInstanceError):
        assessment.waived = True  # type: ignore[misc]


BAD_SHIPPING = ["bulk", "Parcel", "", None]


@pytest.mark.parametrize("shipping", BAD_SHIPPING)
def test_assess_duty_rejects_an_unknown_shipping_model(
    products: dict[str, Product], ksa: MarketConfig, shipping: Any
) -> None:
    with pytest.raises(ValueError, match="shipping"):
        assess_duty(products[HEADPHONES], ksa, Decimal("10"), Decimal("0"), shipping)


@pytest.mark.parametrize("shipping", BAD_SHIPPING)
def test_price_product_rejects_an_unknown_shipping_model(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable, shipping: Any
) -> None:
    with pytest.raises(ValueError, match="shipping"):
        price_product(products[HEADPHONES], ksa, fx, Decimal("0"), shipping)


# --- sends_parcel (SPEC §7.10.1 rule 3) -------------------------------------------------------


@pytest.mark.parametrize(
    ("shipping", "anything_travels", "expected"),
    [
        ("parcel", True, True),
        ("parcel", False, False),  # nothing travels, so no parcel is sent
        ("consolidated", True, False),
        ("consolidated", False, False),
    ],
)
def test_sends_parcel(shipping: Any, anything_travels: bool, expected: bool) -> None:
    assert sends_parcel(shipping, anything_travels) is expected


@pytest.mark.parametrize("shipping", BAD_SHIPPING)
def test_sends_parcel_rejects_an_unknown_shipping_model(shipping: Any) -> None:
    with pytest.raises(ValueError, match="one of consolidated, parcel"):
        sends_parcel(shipping, True)


@pytest.mark.parametrize("code", ["KSA", "UAE", "KWT"])
@pytest.mark.parametrize("shipping", ["consolidated", "parcel"])
@pytest.mark.parametrize("anything_travels", [True, False])
def test_a_fee_is_due_only_when_a_parcel_is_sent(
    config: GccConfig, code: str, shipping: Any, anything_travels: bool
) -> None:
    market = config.markets[code]
    fee = parcel_fee_due(market, shipping, anything_travels)
    expected = market.customs.parcel_fee
    sent = sends_parcel(shipping, anything_travels)
    assert fee == (expected.amount if sent and expected is not None else None)


# --- parcel_fee_due (SPEC §7.10.1 rule 6, M15) ---------------------------------------------


@pytest.mark.parametrize(
    ("code", "shipping", "anything_travels", "expected"),
    [
        ("KSA", "parcel", True, Decimal("15.00")),
        ("KSA", "consolidated", True, None),
        ("KSA", "parcel", False, None),  # nothing travels, so no parcel is sent
        ("UAE", "parcel", True, None),
        ("KWT", "parcel", True, None),
    ],
)
def test_parcel_fee_due(
    config: GccConfig,
    code: str,
    shipping: Any,
    anything_travels: bool,
    expected: Decimal | None,
) -> None:
    fee = parcel_fee_due(config.markets[code], shipping, anything_travels)

    assert fee == expected
    if fee is not None:
        assert str(fee) == "15.00"  # exactly as the config writes it


@pytest.mark.parametrize("shipping", BAD_SHIPPING)
def test_parcel_fee_due_rejects_an_unknown_shipping_model(ksa: MarketConfig, shipping: Any) -> None:
    with pytest.raises(ValueError, match="one of consolidated, parcel"):
        parcel_fee_due(ksa, shipping, True)


# --- a product that weighs nothing (SPEC §7.7.2 rule 4, M15) --------------------------------


@pytest.mark.parametrize("code", ["KSA", "UAE"])
def test_the_licence_as_a_parcel_is_not_waived(
    products: dict[str, Product], config: GccConfig, code: str
) -> None:
    quote = price_product(products[LICENCE], config.markets[code], config.fx, shipping="parcel")

    assert (quote.duty_rate, quote.duty_waived) == (Decimal("0"), False)


def test_the_licence_as_a_uae_parcel_pays_the_adjustment(
    products: dict[str, Product], uae: MarketConfig, fx: FxTable
) -> None:
    at_zero = price_product(products[LICENCE], uae, fx, shipping="parcel")
    plus_three = price_product(products[LICENCE], uae, fx, Decimal("0.03"), "parcel")

    assert str(at_zero.shelf_price) == "304.99"
    assert (plus_three.duty_rate, plus_three.duty_waived) == (Decimal("0.03"), False)
    assert str(plus_three.shelf_price) == "313.99"


def test_a_weightless_product_under_the_threshold_is_not_waived(
    de_minimis_boundary_config: GccConfig,
) -> None:
    quote = price_product(
        _usd_product("10.00", weight_kg="0"),
        de_minimis_boundary_config.markets[AT_OR_BELOW],
        de_minimis_boundary_config.fx,
        shipping="parcel",
    )

    assert (quote.duty_rate, quote.duty_waived) == (Decimal("0.05"), False)
    assert str(quote.shelf_price) == "42.00"  # 40.00 CIF + 5% duty


@given(
    base_price=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("5000"), places=2),
    points=st.integers(0, 20),
    market_index=st.integers(0, 2),
)
@example(base_price=Decimal("90.85"), points=3, market_index=1)
def test_a_weightless_product_gets_the_same_quote_in_both_models(
    config: GccConfig, base_price: Decimal, points: int, market_index: int
) -> None:
    product = _usd_product(str(base_price), weight_kg="0")
    market = list(config.markets.values())[market_index]
    adjustment = Decimal(points) / 100

    consolidated = price_product(product, market, config.fx, adjustment, "consolidated")
    parcel = price_product(product, market, config.fx, adjustment, "parcel")

    assert replace(parcel, shipping="consolidated") == consolidated


# --- worked examples E, F and G (SPEC §7.8) ------------------------------------------------


def test_worked_example_e_headphones_in_ksa_by_parcel(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    quote = price_product(products[HEADPHONES], ksa, fx, shipping="parcel")

    assert quote.shipping == "parcel"
    assert quote.goods == Decimal("562.4625")
    assert quote.freight == Decimal("11.8125")  # 0.35 kg x 9.00 USD
    assert quote.goods + quote.freight == Decimal("574.275")  # cif, below 1,000.00
    assert quote.cif == Decimal("574.275")
    assert quote.duty == 0
    assert (quote.duty_rate, quote.duty_waived) == (Decimal("0"), True)
    assert quote.vat == Decimal("86.14125")
    assert quote.gross == Decimal("660.41625")
    assert str(quote.shelf_price) == "660.95"
    assert _dp(quote.margin_pct, 3) == Decimal("0.587")


def test_worked_example_f_vanilla_in_the_uae_by_parcel(
    products: dict[str, Product], uae: MarketConfig, fx: FxTable
) -> None:
    quote = price_product(products[VANILLA], uae, fx, shipping="parcel")

    assert quote.shipping == "parcel"
    assert quote.goods == Decimal("47.705775")
    assert quote.freight == Decimal("4.407")
    assert quote.goods + quote.freight == Decimal("52.112775")  # under, but alcohol is excluded
    assert (quote.duty_rate, quote.duty_waived) == (Decimal("0.05"), False)
    assert quote.duty == Decimal("2.60563875")
    assert quote.vat == Decimal("2.7359206875")
    assert quote.gross == Decimal("57.4543344375")
    assert str(quote.shelf_price) == "57.99"
    assert _dp(quote.margin_pct, 3) == Decimal("0.688")
    assert str(price_product(products[VANILLA], uae, fx).shelf_price) == "55.99"  # consolidated


def test_worked_example_g_espresso_machine_in_ksa_by_parcel(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    quote = price_product(products[ESPRESSO], ksa, fx, shipping="parcel")

    assert quote.shipping == "parcel"
    assert _cut(quote.goods, 8) == Decimal("3266.77852348")
    assert quote.freight == Decimal("330.75")  # 9.80 kg x 9.00 USD
    assert _cut(quote.goods + quote.freight, 8) == Decimal("3597.52852348")  # not below 1,000
    assert (quote.duty_rate, quote.duty_waived) == (Decimal("0.05"), False)
    assert _cut(quote.duty, 8) == Decimal("179.87642617")
    assert _cut(quote.vat, 8) == Decimal("566.61074244")
    assert _cut(quote.gross, 8) == Decimal("4344.01569211")
    assert str(quote.shelf_price) == "4344.95"
    assert _dp(quote.margin_pct, 3) == Decimal("0.401")


def test_worked_example_g_against_consolidated_and_plus_three_points(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    consolidated = price_product(products[ESPRESSO], ksa, fx)
    plus_three = price_product(products[ESPRESSO], ksa, fx, Decimal("0.03"), "parcel")

    assert str(consolidated.shelf_price) == "4144.95"
    assert str(plus_three.shelf_price) == "4468.95"
    assert plus_three.duty_rate == Decimal("0.08")


# --- example H: the threshold itself (SPEC §7.8) -------------------------------------------


@pytest.mark.parametrize(
    ("market", "base_price", "shelf_price", "waived"),
    [
        (BELOW, "249.99", "999.96", True),
        (BELOW, "250.00", "1050.00", False),
        (BELOW, "250.01", "1050.04", False),
        (AT_OR_BELOW, "249.99", "999.96", True),
        (AT_OR_BELOW, "250.00", "1000.00", True),
        (AT_OR_BELOW, "250.01", "1050.04", False),
    ],
)
def test_worked_example_h_the_threshold_itself(
    de_minimis_boundary_config: GccConfig,
    market: str,
    base_price: str,
    shelf_price: str,
    waived: bool,
) -> None:
    quote = price_product(
        _usd_product(base_price),
        de_minimis_boundary_config.markets[market],
        de_minimis_boundary_config.fx,
        shipping="parcel",
    )

    assert quote.goods + quote.freight == Decimal(base_price) * 4  # cif, exactly
    assert str(quote.shelf_price) == shelf_price
    assert quote.duty_waived is waived
    assert quote.duty_rate == (Decimal("0") if waived else Decimal("0.05"))


@pytest.mark.parametrize("market", [BELOW, AT_OR_BELOW])
def test_example_h_consolidated_always_pays_duty(
    de_minimis_boundary_config: GccConfig, market: str
) -> None:
    quote = price_product(
        _usd_product("249.99"),
        de_minimis_boundary_config.markets[market],
        de_minimis_boundary_config.fx,
    )

    assert str(quote.shelf_price) == "1049.96"
    assert quote.duty_waived is False
