"""M3: currency conversion and landed-cost pricing (SPEC §7)."""

from dataclasses import FrozenInstanceError
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest
from hypothesis import given, reject
from hypothesis import strategies as st

from helpers import NO_ATTRIBUTES, decimal_places
from souqsort.models import Catalogue, FxTable, GccConfig, MarketConfig, Product, ProductName
from souqsort.pricing.fx import convert
from souqsort.pricing.landed_cost import PriceQuote, PriceStep, price_product
from souqsort.pricing.money import format_money

HEADPHONES = "ELEC-HP-001"
BAG = "FASH-BAG-014"
KETTLEBELL = "SPRT-KTB-020"
LIP_BALM = "BEAU-LIP-040"
LICENCE = "DIGI-LIC-050"

ZERO_VAT_MARKET = "TEST-KWD"


# --- helpers and fixtures -----------------------------------------------------------------


def _dp(value: Decimal, places: int) -> Decimal:
    """Round for comparison with the spec tables, which show a fixed number of decimals."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _duty_rate(quote: PriceQuote) -> Decimal:
    """The duty rate a quote was priced with: duty / cif, to 10 decimals."""
    return _dp(quote.duty / (quote.goods + quote.freight), 10)


def _without_charm(market: MarketConfig) -> MarketConfig:
    """A copy of the market with charm pricing switched off; the original is untouched."""
    currency = market.currency.model_copy(update={"charm_ending": None})
    return market.model_copy(update={"currency": currency})


def _quote_or_none(
    product: Product, market: MarketConfig, fx: FxTable, duty_adjustment: Decimal
) -> PriceQuote | None:
    """The quote, or None if the product is rejected because it earns no goods revenue."""
    try:
        return price_product(product, market, fx, duty_adjustment)
    except ValueError as exc:
        if product.sku not in str(exc):
            raise
        return None


@pytest.fixture
def ksa(config: GccConfig) -> MarketConfig:
    return config.markets["KSA"]


@pytest.fixture
def fx(config: GccConfig) -> FxTable:
    return config.fx


@pytest.fixture
def kwd(zero_vat_config: GccConfig) -> MarketConfig:
    return zero_vat_config.markets[ZERO_VAT_MARKET]


@pytest.fixture
def products(catalogue: Catalogue) -> dict[str, Product]:
    return {p.sku: p for p in catalogue.products}


# --- convert ------------------------------------------------------------------------------


def test_convert_usd_to_market_currency(fx: FxTable) -> None:
    assert convert(Decimal("149.99"), "USD", "SAR", fx) == Decimal("562.4625")


def test_convert_gbp_to_market_currency_goes_through_usd(fx: FxTable) -> None:
    # 89.00 / 0.7450 * 3.75 = 447.98657718... (SPEC §7.3)
    assert _dp(convert(Decimal("89.00"), "GBP", "SAR", fx), 8) == Decimal("447.98657718")


def test_convert_back_to_usd(fx: FxTable) -> None:
    assert convert(Decimal("3.75"), "SAR", "USD", fx) == 1


def test_convert_keeps_full_precision(fx: FxTable) -> None:
    # 1.575 USD of freight is 5.90625 SAR: five decimals, not rounded to minor units.
    assert convert(Decimal("1.575"), "USD", "SAR", fx) == Decimal("5.90625")


@pytest.mark.parametrize("currency", ["USD", "GBP", "SAR", "KWD"])
def test_convert_same_currency_is_exact(fx: FxTable, currency: str) -> None:
    assert convert(Decimal("89.00"), currency, currency, fx) == Decimal("89.00")


def test_convert_multiplies_before_dividing(fx: FxTable) -> None:
    # 0.01 * 1.49 / 0.7450 is exactly 0.02. Dividing first gives 0.02000000000000000000000000001,
    # an error that could tip a half-up rounding at the shelf price.
    fx_with_test_rate = fx.model_copy(update={"per_usd": {**fx.per_usd, "TST": Decimal("1.49")}})
    assert convert(Decimal("0.01"), "GBP", "TST", fx_with_test_rate) == Decimal("0.02")


@pytest.mark.parametrize("to_currency", ["SAR", "USD"], ids=["other-currency", "same-currency"])
@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_convert_non_finite_amount_rejected(fx: FxTable, amount: str, to_currency: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        convert(Decimal(amount), "USD", to_currency, fx)


@pytest.mark.parametrize(
    ("from_currency", "to_currency"), [("XYZ", "SAR"), ("USD", "XYZ"), ("XYZ", "XYZ")]
)
def test_convert_unknown_currency_rejected(
    fx: FxTable, from_currency: str, to_currency: str
) -> None:
    with pytest.raises(ValueError, match="XYZ"):
        convert(Decimal("1.00"), from_currency, to_currency, fx)


@pytest.mark.parametrize("amount", [149.99, 149, "149.99"], ids=["float", "int", "str"])
def test_convert_non_decimal_amount_rejected(fx: FxTable, amount: Any) -> None:
    with pytest.raises(TypeError, match="Decimal"):
        convert(amount, "USD", "SAR", fx)


# --- worked examples (SPEC §7.2 and §7.3) -------------------------------------------------


def test_worked_example_a_headphones_in_ksa(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    quote = price_product(products[HEADPHONES], ksa, fx)

    assert isinstance(quote, PriceQuote)
    assert quote.sku == HEADPHONES
    assert quote.market == "KSA"
    assert quote.currency == "SAR"
    assert quote.goods == Decimal("562.4625")
    assert quote.freight == Decimal("5.90625")
    assert quote.duty == Decimal("28.4184375")
    assert quote.vat == Decimal("89.518078125")
    assert quote.gross == Decimal("686.305265625")
    assert str(quote.shelf_price) == "686.95"
    assert _dp(quote.margin_pct, 3) == Decimal("0.587")
    assert quote.steps == ()


def test_worked_example_b_bag_in_ksa(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    quote = price_product(products[BAG], ksa, fx)

    assert quote.sku == BAG
    assert quote.currency == "SAR"
    assert _dp(quote.goods, 8) == Decimal("447.98657718")
    assert quote.freight == Decimal("13.50")
    assert _dp(quote.duty, 8) == Decimal("55.37838926")
    assert _dp(quote.vat, 8) == Decimal("77.52974497")
    assert _dp(quote.gross, 8) == Decimal("594.39471141")
    assert str(quote.shelf_price) == "594.95"
    assert _dp(quote.margin_pct, 3) == Decimal("0.646")


@pytest.mark.parametrize(
    ("sku", "expected"),
    [
        (HEADPHONES, "686.95"),  # gross 686.305265625
        (BAG, "594.95"),  # gross 594.39471141...
        (KETTLEBELL, "593.95"),  # gross 593.184375
        (LIP_BALM, "16.95"),  # gross 16.2106875: the charm ending adds 0.74
        (LICENCE, "340.95"),  # gross 340.6875
    ],
)
def test_shelf_price_in_ksa(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable, sku: str, expected: str
) -> None:
    assert str(price_product(products[sku], ksa, fx).shelf_price) == expected


# --- components keep full precision; only the shelf price is rounded ----------------------


def test_only_the_shelf_price_is_rounded(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    quote = price_product(products[HEADPHONES], ksa, fx)

    assert quote.gross == quote.goods + quote.freight + quote.duty + quote.vat
    assert decimal_places(quote.shelf_price) == 2
    for component in (quote.goods, quote.freight, quote.duty, quote.vat, quote.gross):
        assert component != _dp(component, 2)


# --- margin (SPEC §7.1 step 9) ------------------------------------------------------------


def test_margin_follows_the_spec_formula(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    quote = price_product(products[HEADPHONES], ksa, fx)

    # shelf / (1 + vat) - freight - duty, against a unit cost of 62.00 USD = 232.50 SAR.
    goods_revenue = Decimal("686.95") / Decimal("1.15") - Decimal("5.90625") - Decimal("28.4184375")
    expected = (goods_revenue - Decimal("232.50")) / goods_revenue
    assert _dp(quote.margin_pct, 12) == _dp(expected, 12)


def test_margin_is_negative_when_cost_exceeds_revenue(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    loss_maker = products[HEADPHONES].model_copy(update={"unit_cost": Decimal("500.00")})
    assert price_product(loss_maker, ksa, fx).margin_pct < 0


# --- no goods revenue: rejected, naming the SKU -------------------------------------------


@pytest.mark.parametrize("charm_ending", [None, Decimal("0.000")], ids=["no-charm", "charm-0.000"])
def test_shelf_price_rounding_to_zero_rejected(
    products: dict[str, Product],
    kwd: MarketConfig,
    zero_vat_config: GccConfig,
    charm_ending: Decimal | None,
) -> None:
    # 0.001 USD is 0.000307 KWD, which rounds to a shelf price of 0.000: goods revenue is
    # zero and the margin would divide by it.
    almost_free = products[LICENCE].model_copy(update={"base_price": Decimal("0.001")})
    currency = kwd.currency.model_copy(update={"charm_ending": charm_ending})
    market = kwd.model_copy(update={"currency": currency})

    with pytest.raises(ValueError, match=LICENCE):
        price_product(almost_free, market, zero_vat_config.fx)


def test_shelf_price_below_freight_and_duty_rejected(
    products: dict[str, Product], kwd: MarketConfig, zero_vat_config: GccConfig
) -> None:
    # Gross 0.00046740 KWD rounds to 0.000, less than freight plus duty. Goods revenue is
    # negative, and a negative cost gap over it would read as a margin of about 800%.
    tiny = products[HEADPHONES].model_copy(
        update={
            "base_price": Decimal("0.0001"),
            "weight_kg": Decimal("0.0003"),
            "unit_cost": Decimal("0.01"),
        }
    )

    with pytest.raises(ValueError, match=HEADPHONES):
        price_product(tiny, _without_charm(kwd), zero_vat_config.fx)


def test_rounding_down_past_the_goods_value_rejected(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    # The shelf price need not be zero. 32 kg of freight alone grosses to exactly 652.05 SAR;
    # goods of 0.00075 SAR lift the gross to 652.050905625, which rounds back down to 652.05.
    # The rounding swallows the goods and their duty, leaving goods revenue of -0.0000375.
    heavy_and_cheap = products[KETTLEBELL].model_copy(
        update={"base_price": Decimal("0.0002"), "weight_kg": Decimal("32.00")}
    )

    with pytest.raises(ValueError, match=KETTLEBELL):
        price_product(heavy_and_cheap, _without_charm(ksa), fx)


# --- duty: category override vs default ---------------------------------------------------


@pytest.mark.parametrize(
    ("sku", "expected_rate"),
    [
        (HEADPHONES, "0.05"),  # electronics: no override, default rate
        (KETTLEBELL, "0.05"),  # sports: no override, default rate
        (BAG, "0.12"),  # fashion override
        (LICENCE, "0.00"),  # digital override
    ],
)
def test_duty_rate_by_category(
    products: dict[str, Product],
    ksa: MarketConfig,
    fx: FxTable,
    sku: str,
    expected_rate: str,
) -> None:
    assert _duty_rate(price_product(products[sku], ksa, fx)) == Decimal(expected_rate)


def test_unlisted_category_uses_default_duty(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    toy = products[BAG].model_copy(update={"category": "toys"})
    assert _duty_rate(price_product(toy, ksa, fx)) == Decimal("0.05")


def test_zero_duty_override_gives_exactly_zero_duty(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    assert price_product(products[LICENCE], ksa, fx).duty == 0


# --- duty adjustment (SPEC §7.4) ----------------------------------------------------------


def test_duty_adjustment_adds_percentage_points(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    quote = price_product(products[HEADPHONES], ksa, fx, Decimal("0.03"))

    assert quote.duty == Decimal("45.4695")  # 568.36875 * 0.08
    assert quote.vat == Decimal("92.0757375")
    assert quote.gross == Decimal("705.9139875")
    assert str(quote.shelf_price) == "705.95"


def test_duty_adjustment_applies_to_overridden_categories(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    assert _duty_rate(price_product(products[BAG], ksa, fx, Decimal("0.03"))) == Decimal("0.15")

    licence = price_product(products[LICENCE], ksa, fx, Decimal("0.03"))
    assert licence.duty == Decimal("8.8875")  # 296.25 * (0.00 + 0.03)
    assert str(licence.shelf_price) == "350.95"


def test_duty_adjustment_defaults_to_zero(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    product = products[HEADPHONES]
    assert price_product(product, ksa, fx) == price_product(product, ksa, fx, Decimal("0"))


def test_duty_adjustment_does_not_modify_the_config(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    before = ksa.model_dump()

    price_product(products[HEADPHONES], ksa, fx, Decimal("0.20"))

    assert ksa.model_dump() == before
    assert str(price_product(products[HEADPHONES], ksa, fx).shelf_price) == "686.95"


@pytest.mark.parametrize("adjustment", ["-0.01", "-0.0001", "-1", "NaN", "Infinity"])
def test_negative_or_non_finite_duty_adjustment_rejected(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable, adjustment: str
) -> None:
    with pytest.raises(ValueError, match="duty_adjustment"):
        price_product(products[HEADPHONES], ksa, fx, Decimal(adjustment))


@pytest.mark.parametrize("adjustment", [0.03, 3, "0.03", None], ids=["float", "int", "str", "None"])
def test_non_decimal_duty_adjustment_rejected(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable, adjustment: Any
) -> None:
    with pytest.raises(TypeError, match="Decimal"):
        price_product(products[HEADPHONES], ksa, fx, adjustment)


# --- freight ------------------------------------------------------------------------------


def test_zero_weight_gives_zero_freight(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    quote = price_product(products[LICENCE], ksa, fx)

    assert quote.freight == 0
    assert quote.goods == Decimal("296.25")
    assert quote.gross == Decimal("340.6875")  # goods + 15% VAT only
    assert str(quote.shelf_price) == "340.95"


def test_freight_scales_with_weight(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    quote = price_product(products[KETTLEBELL], ksa, fx)

    assert quote.freight == Decimal("270")  # 16 kg * 4.50 USD * 3.75
    assert quote.freight > quote.goods


# --- 0% VAT fixture market: KWD, 3 minor units --------------------------------------------


def test_zero_vat_market_prices_to_three_decimals(
    products: dict[str, Product], kwd: MarketConfig, zero_vat_config: GccConfig
) -> None:
    quote = price_product(products[HEADPHONES], kwd, zero_vat_config.fx)

    assert quote.market == ZERO_VAT_MARKET
    assert quote.currency == "KWD"
    assert quote.goods == Decimal("46.04693")  # 149.99 * 0.3070
    assert quote.freight == Decimal("0.483525")
    assert quote.duty == Decimal("2.32652275")
    assert quote.gross == Decimal("48.85697775")  # rounds to 48.857
    assert str(quote.shelf_price) == "48.950"
    assert decimal_places(quote.shelf_price) == 3
    assert _dp(quote.margin_pct, 3) == Decimal("0.587")


def test_zero_vat_is_exactly_zero_and_never_formats_negative(
    products: dict[str, Product], kwd: MarketConfig, zero_vat_config: GccConfig
) -> None:
    quote = price_product(products[HEADPHONES], kwd, zero_vat_config.fx)

    assert quote.vat == 0
    assert not quote.vat.is_signed()
    assert format_money(quote.vat, 3) == "0.000"
    assert quote.gross == quote.goods + quote.freight + quote.duty


def test_zero_vat_market_without_charm_rounds_half_up_to_three_decimals(
    products: dict[str, Product], kwd: MarketConfig, zero_vat_config: GccConfig
) -> None:
    quote = price_product(products[HEADPHONES], _without_charm(kwd), zero_vat_config.fx)

    assert str(quote.shelf_price) == "48.857"


def test_zero_vat_market_prices_a_gbp_product(
    products: dict[str, Product], kwd: MarketConfig, zero_vat_config: GccConfig
) -> None:
    quote = price_product(products[BAG], kwd, zero_vat_config.fx)

    assert _dp(quote.goods, 8) == Decimal("36.67516779")  # 89.00 / 0.7450 * 0.3070
    assert quote.freight == Decimal("1.1052")
    assert _duty_rate(quote) == Decimal("0.05")  # no fashion override in this market
    assert quote.vat == 0
    assert _dp(quote.gross, 8) == Decimal("39.66938617")
    assert str(quote.shelf_price) == "39.950"


def test_zero_vat_and_zero_duty_leaves_only_goods(
    products: dict[str, Product], kwd: MarketConfig, zero_vat_config: GccConfig
) -> None:
    quote = price_product(products[LICENCE], kwd, zero_vat_config.fx)

    assert quote.freight == 0
    assert quote.duty == 0
    assert quote.vat == 0
    assert quote.gross == quote.goods == Decimal("24.253")  # 79.00 * 0.3070
    assert str(quote.shelf_price) == "24.950"


# --- result objects -----------------------------------------------------------------------


def test_price_quote_is_frozen(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    quote = price_product(products[HEADPHONES], ksa, fx)
    with pytest.raises(FrozenInstanceError):
        quote.shelf_price = Decimal("1.00")  # type: ignore[misc]


def test_price_step_type_exists_for_later_milestones() -> None:
    step = PriceStep(
        name="duty",
        basis=Decimal("568.36875"),
        rate=Decimal("0.05"),
        amount=Decimal("28.4184375"),
        source="KSA.customs.default_duty_rate",
    )
    assert step.rate == Decimal("0.05")
    with pytest.raises(FrozenInstanceError):
        step.name = "vat"  # type: ignore[misc]


# --- missing FX rate ----------------------------------------------------------------------


def test_product_currency_without_fx_rate_rejected(
    products: dict[str, Product], ksa: MarketConfig, fx: FxTable
) -> None:
    rates = {code: rate for code, rate in fx.per_usd.items() if code != "GBP"}
    fx_without_gbp = fx.model_copy(update={"per_usd": rates})

    with pytest.raises(ValueError, match="GBP"):
        price_product(products[BAG], ksa, fx_without_gbp)


# --- Hypothesis properties ----------------------------------------------------------------

# Ordinary prices, plus prices below one minor unit, where a shelf price can round to zero.
PRICES = st.one_of(
    st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000"), places=2),
    st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("0.01"), places=4),
)

GENERATED_PRODUCTS = st.builds(
    Product,
    sku=st.just("HYPO-001"),
    name=st.just(ProductName(en="Generated product", ar=None)),
    category=st.sampled_from(["electronics", "fashion", "digital", "unlisted"]),
    hs_code=st.just("851830"),
    base_price=PRICES,
    currency=st.sampled_from(["USD", "GBP"]),
    unit_cost=PRICES,
    weight_kg=st.decimals(min_value=0, max_value=1000, places=3),
    attributes=st.just(NO_ATTRIBUTES),
)

# 0 to 100 percentage points, in steps of one basis point.
ADJUSTMENTS = st.integers(min_value=0, max_value=10_000).map(lambda bp: Decimal(bp).scaleb(-4))


def _generated_market(
    config: GccConfig, zero_vat_config: GccConfig, use_zero_vat_market: bool, with_charm: bool
) -> tuple[MarketConfig, FxTable]:
    """One of four markets: KSA or the 0% VAT KWD market, each with or without charm pricing."""
    source, code = (zero_vat_config, ZERO_VAT_MARKET) if use_zero_vat_market else (config, "KSA")
    market = source.markets[code]
    return (market if with_charm else _without_charm(market)), source.fx


@given(
    product=GENERATED_PRODUCTS,
    adjustments=st.tuples(ADJUSTMENTS, ADJUSTMENTS),
    use_zero_vat_market=st.booleans(),
    with_charm=st.booleans(),
)
def test_higher_duty_adjustment_never_lowers_shelf_price(
    config: GccConfig,
    zero_vat_config: GccConfig,
    product: Product,
    adjustments: tuple[Decimal, Decimal],
    use_zero_vat_market: bool,
    with_charm: bool,
) -> None:
    market, fx = _generated_market(config, zero_vat_config, use_zero_vat_market, with_charm)
    lower, higher = sorted(adjustments)

    low = _quote_or_none(product, market, fx, lower)
    high = _quote_or_none(product, market, fx, higher)
    if low is None or high is None:
        reject()  # no goods revenue at one of the two rates: nothing to compare

    assert high.shelf_price >= low.shelf_price
    assert decimal_places(low.shelf_price) == market.currency.minor_units
    assert decimal_places(high.shelf_price) == market.currency.minor_units


@given(
    product=GENERATED_PRODUCTS,
    duty_adjustment=ADJUSTMENTS,
    use_zero_vat_market=st.booleans(),
    with_charm=st.booleans(),
)
def test_every_quote_has_a_positive_shelf_price_and_a_margin_below_one(
    config: GccConfig,
    zero_vat_config: GccConfig,
    product: Product,
    duty_adjustment: Decimal,
    use_zero_vat_market: bool,
    with_charm: bool,
) -> None:
    market, fx = _generated_market(config, zero_vat_config, use_zero_vat_market, with_charm)

    # Either a ValueError naming the SKU (checked in _quote_or_none) or a sound quote; never
    # a DivisionByZero, and never a margin above 100% from dividing by negative revenue.
    quote = _quote_or_none(product, market, fx, duty_adjustment)
    if quote is None:
        return

    assert quote.shelf_price > 0
    assert decimal_places(quote.shelf_price) == market.currency.minor_units
    assert quote.margin_pct < 1
