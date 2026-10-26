"""M1: Pydantic models and JSON loaders for the catalogue and the GCC market config."""

from collections.abc import Callable
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from helpers import NO_ATTRIBUTES, SAMPLE_PRODUCT_COUNT
from souqsort.loaders import DataFileError, load_catalogue, load_gcc_config
from souqsort.models import (
    SHIPPING_MODELS,
    AttributeName,
    GccConfig,
    Product,
    ProductAttributes,
    ProductName,
    ShippingModel,
    require_shipping,
)

WriteJson = Callable[[Any], Path]
Raw = dict[str, Any]

HEADPHONES = "ELEC-HP-001"
BAG = "FASH-BAG-014"
LICENCE = "DIGI-LIC-050"

# Worked example A, exactly as written in SPEC §6.1.
EXAMPLE_A: Raw = {
    "sku": "ELEC-HP-001",
    "name": {"en": "Wireless Noise-Cancelling Headphones", "ar": "سماعات لاسلكية عازلة للضوضاء"},
    "category": "electronics",
    "hs_code": "851830",
    "base_price": "149.99",
    "currency": "USD",
    "unit_cost": "62.00",
    "weight_kg": "0.35",
    "attributes": {
        "contains_alcohol": False,
        "contains_pork": False,
        "contains_lithium_battery": True,
    },
}


# --- helpers ------------------------------------------------------------------------------


def _product(raw: Raw, sku: str = HEADPHONES) -> Raw:
    return next(p for p in raw["products"] if p["sku"] == sku)


def _ksa(raw: Raw) -> Raw:
    market: Raw = raw["markets"]["KSA"]
    return market


def _set(obj: Raw, keys: tuple[str, ...], value: Any) -> None:
    for key in keys[:-1]:
        obj = obj[key]
    obj[keys[-1]] = value


def _assert_message_has(exc: DataFileError, fragments: tuple[str, ...]) -> None:
    message = str(exc)
    for fragment in fragments:
        assert fragment in message, f"{fragment!r} not in error message:\n{message}"


def _reject_catalogue(write_json: WriteJson, raw: Raw, *fragments: str) -> None:
    path = write_json(raw)
    with pytest.raises(DataFileError) as excinfo:
        load_catalogue(path)
    _assert_message_has(excinfo.value, fragments)


def _reject_config(write_json: WriteJson, raw: Raw, *fragments: str) -> None:
    path = write_json(raw)
    with pytest.raises(DataFileError) as excinfo:
        load_gcc_config(path)
    _assert_message_has(excinfo.value, fragments)


def _load_config(write_json: WriteJson, raw: Raw) -> GccConfig:
    return load_gcc_config(write_json(raw))


# --- the sample data files load -----------------------------------------------------------


def test_sample_catalogue_loads(catalogue_path: Path) -> None:
    catalogue = load_catalogue(catalogue_path)

    assert catalogue.catalogue_version == "2026-10-01"
    assert len(catalogue.products) == SAMPLE_PRODUCT_COUNT
    for product in catalogue.products:
        assert isinstance(product.base_price, Decimal)
        assert isinstance(product.unit_cost, Decimal)
        assert isinstance(product.weight_kg, Decimal)

    headphones = next(p for p in catalogue.products if p.sku == HEADPHONES)
    assert headphones.base_price == Decimal("149.99")
    assert headphones.unit_cost == Decimal("62.00")
    assert headphones.weight_kg == Decimal("0.35")
    assert headphones.attributes.contains_lithium_battery is True


def test_sample_config_loads(config_path: Path) -> None:
    config = load_gcc_config(config_path)

    assert config.config_version == "2026-11-01"
    assert config.fx.as_of == date(2026, 10, 1)
    assert config.fx.per_usd["SAR"] == Decimal("3.7500")
    assert config.fx.per_usd["GBP"] == Decimal("0.7450")
    assert config.fx.per_usd["AED"] == Decimal("3.6725")
    assert config.fx.per_usd["KWD"] == Decimal("0.3070")
    assert list(config.markets) == ["KSA", "UAE", "KWT"]  # three markets, in file order

    ksa = config.markets["KSA"]
    assert ksa.code == "KSA"
    assert ksa.name == "Saudi Arabia"
    assert ksa.currency.code == "SAR"
    assert ksa.currency.minor_units == 2
    assert ksa.currency.charm_ending == Decimal("0.95")
    assert ksa.tax.vat_rate == Decimal("0.15")
    assert ksa.customs.default_duty_rate == Decimal("0.05")
    assert ksa.customs.category_overrides["fashion"] == Decimal("0.12")
    assert ksa.calendar.timezone == "Asia/Riyadh"
    assert list(ksa.calendar.weekend) == ["FRI", "SAT"]
    assert ksa.calendar.order_cutoff_local == time(14, 0)
    assert [(h.date, h.name, h.provisional) for h in ksa.calendar.holidays] == [
        (date(2027, 2, 22), "Founding Day", False),
        (date(2027, 3, 9), "Eid al-Fitr", True),
        (date(2027, 3, 10), "Eid al-Fitr", True),
        (date(2027, 3, 11), "Eid al-Fitr", True),
    ]
    assert ksa.logistics.freight_per_kg_usd == Decimal("4.50")
    assert ksa.logistics.linehaul_business_days == 3
    assert ksa.logistics.last_mile_business_days == 2


def test_name_ar_null_accepted(catalogue_path: Path) -> None:
    bag = next(p for p in load_catalogue(catalogue_path).products if p.sku == BAG)
    assert bag.name.ar is None
    assert bag.name.en == "Leather Crossbody Bag"


# --- the sample data covers SPEC §6.1 -----------------------------------------------------


def test_catalogue_contains_worked_example_a_exactly(raw_catalogue: Raw) -> None:
    assert _product(raw_catalogue, HEADPHONES) == EXAMPLE_A


def test_catalogue_contains_worked_example_b(raw_catalogue: Raw) -> None:
    bag = _product(raw_catalogue, BAG)
    assert bag["name"] == {"en": "Leather Crossbody Bag", "ar": None}
    assert bag["category"] == "fashion"
    assert bag["currency"] == "GBP"
    assert bag["base_price"] == "89.00"
    assert bag["unit_cost"] == "31.50"
    assert bag["weight_kg"] == "0.80"


def test_catalogue_covers_spec_cases(catalogue_path: Path, config_path: Path) -> None:
    products = load_catalogue(catalogue_path).products
    overrides = load_gcc_config(config_path).markets["KSA"].customs.category_overrides

    assert any(p.weight_kg >= 10 for p in products), "heavy item"
    assert any(p.currency == "USD" and p.base_price < 10 for p in products), "cheap item"
    assert sum(p.name.ar is None for p in products) >= 2
    assert any(p.attributes.contains_alcohol for p in products)
    assert any(p.attributes.contains_pork for p in products)

    categories = {p.category for p in products}
    assert len(categories) >= 4
    assert categories & overrides.keys(), "a category with a duty override"
    assert categories - overrides.keys(), "a category on the default duty"


def test_digital_licence_is_weightless_with_zero_duty(
    catalogue_path: Path, config_path: Path
) -> None:
    licence = next(p for p in load_catalogue(catalogue_path).products if p.sku == LICENCE)
    overrides = load_gcc_config(config_path).markets["KSA"].customs.category_overrides

    assert licence.name.en == "Photo Editor Pro Licence (digital download)"
    assert licence.currency == "USD"
    assert licence.category == "digital"
    assert licence.weight_kg == Decimal("0")
    assert overrides["digital"] == Decimal("0.00")


# --- decimal-string validator: JSON numbers are rejected ----------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_price", 149.99),
        ("unit_cost", 62.0),
        ("weight_kg", 0.35),
        ("base_price", 149),
        ("base_price", True),
    ],
)
def test_json_number_in_product_decimal_field_rejected(
    write_json: WriteJson, raw_catalogue: Raw, field: str, value: Any
) -> None:
    _product(raw_catalogue)[field] = value
    _reject_catalogue(write_json, raw_catalogue, field, "decimal string")


@pytest.mark.parametrize(
    ("keys", "value"),
    [
        (("tax", "vat_rate"), 0.15),
        (("customs", "default_duty_rate"), 0.05),
        (("customs", "de_minimis", "threshold"), 1000),
        (("logistics", "freight_per_kg_usd"), 4.5),
        (("logistics", "parcel_freight_per_kg_usd"), 9.0),
    ],
)
def test_json_number_in_market_rate_rejected(
    write_json: WriteJson, raw_config: Raw, keys: tuple[str, ...], value: Any
) -> None:
    _set(_ksa(raw_config), keys, value)
    _reject_config(write_json, raw_config, keys[-1], "decimal string")


def test_json_number_in_fx_rate_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    raw_config["fx"]["per_usd"]["SAR"] = 3.75
    _reject_config(write_json, raw_config, "per_usd", "decimal string")


def test_python_float_rejected_for_money() -> None:
    with pytest.raises(ValidationError, match="decimal string"):
        Product(
            sku="TEST-001",
            name=ProductName(en="Test", ar=None),
            category="test",
            hs_code="851830",
            base_price=1.5,  # type: ignore[arg-type]
            currency="USD",
            unit_cost=Decimal("1.00"),
            weight_kg=Decimal("0"),
            attributes=NO_ATTRIBUTES,
        )


def test_python_decimal_accepted_for_money() -> None:
    product = Product(
        sku="TEST-001",
        name=ProductName(en="Test", ar=None),
        category="test",
        hs_code="851830",
        base_price=Decimal("1.50"),
        currency="USD",
        unit_cost=Decimal("1.00"),
        weight_kg=Decimal("0"),
        attributes=NO_ATTRIBUTES,
    )
    assert product.base_price == Decimal("1.50")


# --- decimal parsing ----------------------------------------------------------------------


@pytest.mark.parametrize("value", ["abc", "", "NaN", "Infinity", "-Infinity"])
def test_non_finite_or_unparseable_decimal_rejected(
    write_json: WriteJson, raw_catalogue: Raw, value: str
) -> None:
    _product(raw_catalogue)["base_price"] = value
    _reject_catalogue(write_json, raw_catalogue, "base_price")


# --- PositiveDecimal / NonNegativeDecimal -------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [("base_price", "0"), ("base_price", "-1"), ("unit_cost", "0"), ("unit_cost", "-0.01")],
)
def test_non_positive_product_money_rejected(
    write_json: WriteJson, raw_catalogue: Raw, field: str, value: str
) -> None:
    _product(raw_catalogue)[field] = value
    _reject_catalogue(write_json, raw_catalogue, field)


def test_negative_weight_rejected(write_json: WriteJson, raw_catalogue: Raw) -> None:
    _product(raw_catalogue)["weight_kg"] = "-0.1"
    _reject_catalogue(write_json, raw_catalogue, "weight_kg")


def test_non_positive_fx_rate_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    raw_config["fx"]["per_usd"]["SAR"] = "0"
    _reject_config(write_json, raw_config, "per_usd")


@pytest.mark.parametrize(
    "keys",
    [
        ("tax", "vat_rate"),
        ("customs", "default_duty_rate"),
        ("customs", "category_overrides", "fashion"),
        ("customs", "de_minimis", "threshold"),
        ("logistics", "freight_per_kg_usd"),
        ("logistics", "parcel_freight_per_kg_usd"),
        ("currency", "charm_ending"),
    ],
)
def test_negative_market_value_rejected(
    write_json: WriteJson, raw_config: Raw, keys: tuple[str, ...]
) -> None:
    _set(_ksa(raw_config), keys, "-0.05")
    _reject_config(write_json, raw_config, keys[-1])


def test_zero_rates_accepted(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["tax"]["vat_rate"] = "0"
    _ksa(raw_config)["customs"]["default_duty_rate"] = "0.00"
    ksa = _load_config(write_json, raw_config).markets["KSA"]
    assert ksa.tax.vat_rate == 0
    assert ksa.customs.default_duty_rate == 0


# --- base model config: extra="forbid", frozen=True ---------------------------------------


def test_unknown_product_key_rejected(write_json: WriteJson, raw_catalogue: Raw) -> None:
    _product(raw_catalogue)["colour"] = "black"
    _reject_catalogue(write_json, raw_catalogue, "colour")


def test_unknown_market_key_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["tax"]["vat_ratee"] = "0.15"
    _reject_config(write_json, raw_config, "vat_ratee")


def test_models_are_frozen(catalogue_path: Path) -> None:
    product = load_catalogue(catalogue_path).products[0]
    with pytest.raises(ValidationError):
        product.sku = "CHANGED"  # type: ignore[misc]


# --- ProductName --------------------------------------------------------------------------


def test_empty_english_name_rejected(write_json: WriteJson, raw_catalogue: Raw) -> None:
    _product(raw_catalogue)["name"]["en"] = ""
    _reject_catalogue(write_json, raw_catalogue, "name.en")


def test_missing_arabic_name_key_rejected(write_json: WriteJson, raw_catalogue: Raw) -> None:
    del _product(raw_catalogue)["name"]["ar"]
    _reject_catalogue(write_json, raw_catalogue, "name.ar")


# --- Product fields -----------------------------------------------------------------------


@pytest.mark.parametrize("value", ["8518", "85183X", "85183012345"])
def test_malformed_hs_code_rejected(write_json: WriteJson, raw_catalogue: Raw, value: str) -> None:
    _product(raw_catalogue)["hs_code"] = value
    _reject_catalogue(write_json, raw_catalogue, "hs_code")


@pytest.mark.parametrize("value", ["EUR", "SAR", "usd"])
def test_unknown_product_currency_rejected(
    write_json: WriteJson, raw_catalogue: Raw, value: str
) -> None:
    _product(raw_catalogue)["currency"] = value
    _reject_catalogue(write_json, raw_catalogue, "currency")


@pytest.mark.parametrize("value", ["true", 1])
def test_non_boolean_attribute_rejected(
    write_json: WriteJson, raw_catalogue: Raw, value: Any
) -> None:
    _product(raw_catalogue)["attributes"]["contains_alcohol"] = value
    _reject_catalogue(write_json, raw_catalogue, "contains_alcohol")


# --- ProductAttributes: a fixed schema (SPEC §6.1, M9) -----------------------------------


def test_missing_attribute_rejected(write_json: WriteJson, raw_catalogue: Raw) -> None:
    del _product(raw_catalogue)["attributes"]["contains_pork"]
    _reject_catalogue(write_json, raw_catalogue, "contains_pork", "Field required")


def test_unknown_attribute_rejected(write_json: WriteJson, raw_catalogue: Raw) -> None:
    _product(raw_catalogue)["attributes"]["contains_nuts"] = False
    _reject_catalogue(write_json, raw_catalogue, "contains_nuts", "Extra inputs")


def test_attribute_names_are_exactly_the_attribute_fields() -> None:
    assert get_args(AttributeName) == tuple(ProductAttributes.model_fields)


@pytest.mark.parametrize("name", get_args(AttributeName))
def test_has_reads_the_named_attribute(name: AttributeName) -> None:
    only_this = NO_ATTRIBUTES.model_copy(update={name: True})
    assert only_this.has(name) is True
    assert NO_ATTRIBUTES.has(name) is False
    assert [other for other in get_args(AttributeName) if only_this.has(other)] == [name]


# --- CategoryName: lowercase, so an override never misses (issue #1) ---------------------


@pytest.mark.parametrize(
    "category", ["Fashion", "FASHION", "fashion wear", "fashion-wear", "1fashion", "_fashion", ""]
)
def test_category_that_is_not_lowercase_snake_case_rejected(
    write_json: WriteJson, raw_catalogue: Raw, category: str
) -> None:
    _product(raw_catalogue, BAG)["category"] = category
    _reject_catalogue(write_json, raw_catalogue, "category", "should match pattern")


@pytest.mark.parametrize("category", ["fashion", "home_audio", "a1"])
def test_lowercase_category_accepted(
    write_json: WriteJson, raw_catalogue: Raw, category: str
) -> None:
    _product(raw_catalogue, BAG)["category"] = category
    bag = next(p for p in load_catalogue(write_json(raw_catalogue)).products if p.sku == BAG)
    assert bag.category == category


def test_sample_markets_ban_the_attributes_in_the_spec(config_path: Path) -> None:
    markets = load_gcc_config(config_path).markets
    assert {code: market.compliance.banned_attributes for code, market in markets.items()} == {
        "KSA": ("contains_alcohol", "contains_pork"),
        "UAE": ("contains_pork",),
        "KWT": ("contains_alcohol", "contains_pork"),
    }
    assert all(market.compliance.source for market in markets.values())


# --- ComplianceConfig (SPEC §6.2, M9) -----------------------------------------------------


def test_market_without_compliance_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    del _ksa(raw_config)["compliance"]
    _reject_config(write_json, raw_config, "compliance", "Field required")


def test_unknown_banned_attribute_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["compliance"]["banned_attributes"] = ["contains_pork", "contains_porc"]
    _reject_config(write_json, raw_config, "banned_attributes", "contains_porc")


def test_duplicate_banned_attribute_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    banned = ["contains_pork", "contains_alcohol", "contains_pork"]
    _ksa(raw_config)["compliance"]["banned_attributes"] = banned
    _reject_config(write_json, raw_config, "duplicate banned attribute", "contains_pork")


def test_empty_compliance_source_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["compliance"]["source"] = ""
    _reject_config(write_json, raw_config, "compliance.source")


def test_nothing_banned_accepted(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["compliance"]["banned_attributes"] = []
    assert _load_config(write_json, raw_config).markets["KSA"].compliance.banned_attributes == ()


# --- DeMinimisRule and parcel freight (SPEC §6.2, M10) ------------------------------------


def test_sample_markets_have_the_de_minimis_rules_in_the_spec(config_path: Path) -> None:
    markets = load_gcc_config(config_path).markets
    rules = {code: market.customs.de_minimis for code, market in markets.items()}

    ksa, uae = rules["KSA"], rules["UAE"]
    assert ksa is not None
    assert (ksa.threshold, ksa.applies, ksa.excluded_attributes) == (
        Decimal("1000.00"),
        "below",
        (),
    )
    assert ksa.source.startswith("illustrative, modelled on ZATCA")
    assert uae is not None
    assert (uae.threshold, uae.applies, uae.excluded_attributes) == (
        Decimal("1000.00"),
        "at_or_below",
        ("contains_alcohol",),
    )
    assert uae.source.startswith("illustrative, modelled on Dubai Customs")
    assert rules["KWT"] is None  # Kuwait has no de minimis


def test_sample_markets_have_the_parcel_freight_in_the_spec(config_path: Path) -> None:
    markets = load_gcc_config(config_path).markets
    assert {
        code: market.logistics.parcel_freight_per_kg_usd for code, market in markets.items()
    } == {
        "KSA": Decimal("9.00"),
        "UAE": Decimal("8.00"),
        "KWT": Decimal("10.00"),
    }


def test_market_without_de_minimis_key_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    del _ksa(raw_config)["customs"]["de_minimis"]
    _reject_config(write_json, raw_config, "de_minimis", "Field required")


def test_null_de_minimis_accepted(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["customs"]["de_minimis"] = None
    assert _load_config(write_json, raw_config).markets["KSA"].customs.de_minimis is None


def test_zero_de_minimis_threshold_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["customs"]["de_minimis"]["threshold"] = "0"
    _reject_config(write_json, raw_config, "threshold", "greater than 0")


@pytest.mark.parametrize("applies", ["under", "BELOW", "at_or_above", ""])
def test_unknown_de_minimis_applies_rejected(
    write_json: WriteJson, raw_config: Raw, applies: str
) -> None:
    _ksa(raw_config)["customs"]["de_minimis"]["applies"] = applies
    _reject_config(write_json, raw_config, "applies", "'below' or 'at_or_below'")


def test_unknown_excluded_attribute_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["customs"]["de_minimis"]["excluded_attributes"] = ["contains_alcohl"]
    _reject_config(write_json, raw_config, "excluded_attributes", "contains_alcohl")


def test_duplicate_excluded_attribute_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    excluded = ["contains_alcohol", "contains_alcohol"]
    _ksa(raw_config)["customs"]["de_minimis"]["excluded_attributes"] = excluded
    _reject_config(write_json, raw_config, "duplicate excluded attribute", "contains_alcohol")


def test_empty_de_minimis_source_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["customs"]["de_minimis"]["source"] = ""
    _reject_config(write_json, raw_config, "de_minimis.source")


def test_unknown_de_minimis_key_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["customs"]["de_minimis"]["currency"] = "SAR"
    _reject_config(write_json, raw_config, "de_minimis.currency")


def test_de_minimis_threshold_finer_than_minor_units_rejected(
    write_json: WriteJson, raw_config: Raw
) -> None:
    # Shown as 1,000.00 SAR, a 999.995 threshold would make the report's rule sentence wrong.
    _ksa(raw_config)["customs"]["de_minimis"]["threshold"] = "999.995"
    _reject_config(write_json, raw_config, "KSA:", "threshold 999.995", "minor_units (2)")


@pytest.mark.parametrize("threshold", ["1000.00", "1000", "1000.000", "1E+30"])
def test_de_minimis_threshold_in_whole_minor_units_accepted(
    write_json: WriteJson, raw_config: Raw, threshold: str
) -> None:
    # Trailing zeros add no precision, as for charm_ending; a huge threshold still loads.
    _ksa(raw_config)["customs"]["de_minimis"]["threshold"] = threshold
    rule = _load_config(write_json, raw_config).markets["KSA"].customs.de_minimis
    assert rule is not None
    assert rule.threshold == Decimal(threshold)


def test_de_minimis_threshold_with_three_minor_units_accepted(
    write_json: WriteJson, raw_config: Raw
) -> None:
    rule = {**_ksa(raw_config)["customs"]["de_minimis"], "threshold": "300.125"}
    raw_config["markets"]["KWT"]["customs"]["de_minimis"] = rule
    loaded = _load_config(write_json, raw_config).markets["KWT"].customs.de_minimis
    assert loaded is not None
    assert loaded.threshold == Decimal("300.125")


def test_excluded_attributes_may_be_empty(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["customs"]["de_minimis"]["excluded_attributes"] = []
    rule = _load_config(write_json, raw_config).markets["KSA"].customs.de_minimis
    assert rule is not None
    assert rule.excluded_attributes == ()


def test_market_without_parcel_freight_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    del _ksa(raw_config)["logistics"]["parcel_freight_per_kg_usd"]
    _reject_config(write_json, raw_config, "parcel_freight_per_kg_usd", "Field required")


def test_zero_parcel_freight_accepted(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["logistics"]["parcel_freight_per_kg_usd"] = "0"
    ksa = _load_config(write_json, raw_config).markets["KSA"]
    assert ksa.logistics.parcel_freight_per_kg_usd == 0


def test_sample_markets_have_the_parcel_fees_and_linehauls_in_the_spec(config_path: Path) -> None:
    markets = load_gcc_config(config_path).markets
    ksa_fee = markets["KSA"].customs.parcel_fee
    assert ksa_fee is not None
    assert str(ksa_fee.amount) == "15.00"  # exactly, as written
    assert ksa_fee.source.startswith("illustrative, modelled on ZATCA: SAR 15 to declare")
    assert markets["UAE"].customs.parcel_fee is None
    assert markets["KWT"].customs.parcel_fee is None
    assert {code: m.logistics.parcel_linehaul_business_days for code, m in markets.items()} == {
        "KSA": 2,
        "UAE": 2,
        "KWT": 2,
    }


def test_market_without_parcel_fee_key_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    del _ksa(raw_config)["customs"]["parcel_fee"]
    _reject_config(write_json, raw_config, "parcel_fee", "Field required")


def test_null_parcel_fee_accepted(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["customs"]["parcel_fee"] = None
    assert _load_config(write_json, raw_config).markets["KSA"].customs.parcel_fee is None


@pytest.mark.parametrize(
    ("amount", "fragments"),
    [
        ("0", ("amount", "greater than 0")),
        ("-15.00", ("amount", "greater than 0")),
        (15, ("amount", "decimal string")),
        (15.0, ("amount", "decimal string")),
        ("15.001", ("KSA:", "parcel fee 15.001", "minor_units (2)")),
    ],
)
def test_bad_parcel_fee_amount_rejected(
    write_json: WriteJson, raw_config: Raw, amount: Any, fragments: tuple[str, ...]
) -> None:
    _ksa(raw_config)["customs"]["parcel_fee"]["amount"] = amount
    _reject_config(write_json, raw_config, *fragments)


@pytest.mark.parametrize("amount", ["15", "15.00", "15.000"])
def test_parcel_fee_in_whole_minor_units_accepted(
    write_json: WriteJson, raw_config: Raw, amount: str
) -> None:
    _ksa(raw_config)["customs"]["parcel_fee"]["amount"] = amount
    fee = _load_config(write_json, raw_config).markets["KSA"].customs.parcel_fee
    assert fee is not None
    assert fee.amount == Decimal("15")


def test_parcel_fee_with_three_minor_units_accepted(write_json: WriteJson, raw_config: Raw) -> None:
    fee = {**_ksa(raw_config)["customs"]["parcel_fee"], "amount": "1.125"}
    raw_config["markets"]["KWT"]["customs"]["parcel_fee"] = fee
    loaded = _load_config(write_json, raw_config).markets["KWT"].customs.parcel_fee
    assert loaded is not None
    assert loaded.amount == Decimal("1.125")


def test_empty_parcel_fee_source_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["customs"]["parcel_fee"]["source"] = ""
    _reject_config(write_json, raw_config, "parcel_fee.source")


def test_unknown_parcel_fee_key_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["customs"]["parcel_fee"]["vat"] = "0"
    _reject_config(write_json, raw_config, "parcel_fee.vat")


def test_market_without_parcel_linehaul_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    del _ksa(raw_config)["logistics"]["parcel_linehaul_business_days"]
    _reject_config(write_json, raw_config, "parcel_linehaul_business_days", "Field required")


def test_de_minimis_boundary_fixture_loads(de_minimis_boundary_config: GccConfig) -> None:
    markets = de_minimis_boundary_config.markets
    assert list(markets) == ["TEST-BELOW", "TEST-AT-OR-BELOW"]
    assert de_minimis_boundary_config.fx.per_usd["XTS"] == Decimal("4.0000")
    for code, applies in (("TEST-BELOW", "below"), ("TEST-AT-OR-BELOW", "at_or_below")):
        market = markets[code]
        rule = market.customs.de_minimis
        assert rule is not None
        assert (rule.threshold, rule.applies, rule.excluded_attributes) == (
            Decimal("1000.00"),
            applies,
            (),
        )
        assert (market.currency.code, market.currency.minor_units) == ("XTS", 2)
        assert market.currency.charm_ending is None
        assert market.tax.vat_rate == 0
        assert market.customs.default_duty_rate == Decimal("0.05")
        assert market.compliance.banned_attributes == ()
        assert market.logistics.freight_per_kg_usd == 0
        assert market.logistics.parcel_freight_per_kg_usd == 0
        assert market.customs.parcel_fee is None
        assert market.logistics.parcel_linehaul_business_days == 2


def test_zero_vat_fixture_has_no_de_minimis(zero_vat_config: GccConfig) -> None:
    market = zero_vat_config.markets["TEST-KWD"]
    assert market.customs.de_minimis is None
    assert market.logistics.parcel_freight_per_kg_usd == Decimal("9.00")
    assert market.customs.parcel_fee is None
    assert market.logistics.parcel_linehaul_business_days == 2


@pytest.mark.parametrize("key", ["Fashion", "FASHION", "fashion wear"])
def test_category_override_key_that_is_not_lowercase_rejected(
    write_json: WriteJson, raw_config: Raw, key: str
) -> None:
    overrides = _ksa(raw_config)["customs"]["category_overrides"]
    overrides[key] = overrides.pop("fashion")
    _reject_config(write_json, raw_config, "category_overrides", key, "should match pattern")


# --- Catalogue: unique SKUs ---------------------------------------------------------------


def test_duplicate_sku_rejected(write_json: WriteJson, raw_catalogue: Raw) -> None:
    raw_catalogue["products"][1]["sku"] = raw_catalogue["products"][0]["sku"]
    duplicate = raw_catalogue["products"][0]["sku"]
    _reject_catalogue(write_json, raw_catalogue, "duplicate", duplicate)


# --- FxTable ------------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["sar", "SARX", "S1R"])
def test_malformed_fx_currency_code_rejected(
    write_json: WriteJson, raw_config: Raw, code: str
) -> None:
    raw_config["fx"]["per_usd"][code] = "3.75"
    _reject_config(write_json, raw_config, "per_usd", code)


def test_fx_without_usd_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    del raw_config["fx"]["per_usd"]["USD"]
    _reject_config(write_json, raw_config, "fx", "USD")


def test_fx_with_usd_not_one_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    raw_config["fx"]["per_usd"]["USD"] = "1.01"
    _reject_config(write_json, raw_config, "fx", "USD")


def test_fx_usd_with_trailing_zeros_accepted(write_json: WriteJson, raw_config: Raw) -> None:
    raw_config["fx"]["per_usd"]["USD"] = "1.0000"
    assert _load_config(write_json, raw_config).fx.per_usd["USD"] == 1


# --- CurrencyConfig -----------------------------------------------------------------------


@pytest.mark.parametrize("value", [-1, "2", 2.0])
def test_bad_minor_units_rejected(write_json: WriteJson, raw_config: Raw, value: Any) -> None:
    _ksa(raw_config)["currency"]["minor_units"] = value
    _reject_config(write_json, raw_config, "minor_units")


@pytest.mark.parametrize("value", ["1", "1.00", "1.5"])
def test_charm_ending_of_one_or_more_rejected(
    write_json: WriteJson, raw_config: Raw, value: str
) -> None:
    _ksa(raw_config)["currency"]["charm_ending"] = value
    _reject_config(write_json, raw_config, "charm_ending")


def test_charm_ending_finer_than_minor_units_rejected(
    write_json: WriteJson, raw_config: Raw
) -> None:
    _ksa(raw_config)["currency"]["charm_ending"] = "0.955"
    _reject_config(write_json, raw_config, "charm_ending", "minor_units")


def test_charm_ending_null_accepted(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["currency"]["charm_ending"] = None
    assert _load_config(write_json, raw_config).markets["KSA"].currency.charm_ending is None


def test_charm_ending_with_three_minor_units_accepted(
    write_json: WriteJson, raw_config: Raw
) -> None:
    _ksa(raw_config)["currency"]["minor_units"] = 3
    _ksa(raw_config)["currency"]["charm_ending"] = "0.950"
    currency = _load_config(write_json, raw_config).markets["KSA"].currency
    assert currency.minor_units == 3
    assert currency.charm_ending == Decimal("0.950")


# --- CalendarConfig -----------------------------------------------------------------------


@pytest.mark.parametrize("value", ["Asia/Ryadh", "", "Asia", "../etc/passwd"])
def test_invalid_timezone_rejected(write_json: WriteJson, raw_config: Raw, value: str) -> None:
    _ksa(raw_config)["calendar"]["timezone"] = value
    _reject_config(write_json, raw_config, "timezone")


@pytest.mark.parametrize("weekend", [["FRIDAY", "SAT"], ["fri", "sat"], ["FRI", "FRI"]])
def test_bad_weekend_rejected(write_json: WriteJson, raw_config: Raw, weekend: list[str]) -> None:
    _ksa(raw_config)["calendar"]["weekend"] = weekend
    _reject_config(write_json, raw_config, "weekend")


def test_weekend_covering_every_day_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    # No day could ever be a business day, so no order could ever be dispatched.
    _ksa(raw_config)["calendar"]["weekend"] = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    _reject_config(write_json, raw_config, "weekend", "no business day")


@pytest.mark.parametrize(
    "weekend", [[], ["MON", "TUE", "WED", "THU", "FRI", "SAT"]], ids=["no-weekend", "six-days"]
)
def test_weekend_leaving_a_business_day_accepted(
    write_json: WriteJson, raw_config: Raw, weekend: list[str]
) -> None:
    _ksa(raw_config)["calendar"]["weekend"] = weekend
    calendar = _load_config(write_json, raw_config).markets["KSA"].calendar
    assert list(calendar.weekend) == weekend


@pytest.mark.parametrize("value", ["2pm", "24:00", "14:0", "14:00:00", "9:00", "14:60", 1400])
def test_malformed_cutoff_rejected(write_json: WriteJson, raw_config: Raw, value: Any) -> None:
    _ksa(raw_config)["calendar"]["order_cutoff_local"] = value
    _reject_config(write_json, raw_config, "order_cutoff_local")


@pytest.mark.parametrize(("value", "expected"), [("00:00", time(0, 0)), ("23:59", time(23, 59))])
def test_cutoff_boundaries_accepted(
    write_json: WriteJson, raw_config: Raw, value: str, expected: time
) -> None:
    _ksa(raw_config)["calendar"]["order_cutoff_local"] = value
    calendar = _load_config(write_json, raw_config).markets["KSA"].calendar
    assert calendar.order_cutoff_local == expected


# --- LogisticsConfig ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["linehaul_business_days", "parcel_linehaul_business_days", "last_mile_business_days"],
)
@pytest.mark.parametrize("value", [-1, "3", 3.0])
def test_bad_business_day_count_rejected(
    write_json: WriteJson, raw_config: Raw, field: str, value: Any
) -> None:
    _ksa(raw_config)["logistics"][field] = value
    _reject_config(write_json, raw_config, field)


# --- ShippingModel ------------------------------------------------------------------------


def test_shipping_models_are_the_literal_s_values() -> None:
    assert SHIPPING_MODELS == get_args(ShippingModel) == ("consolidated", "parcel")


@pytest.mark.parametrize("shipping", ["bulk", "Parcel", "", None])
def test_require_shipping_rejects_anything_else(shipping: Any) -> None:
    with pytest.raises(ValueError, match="one of consolidated, parcel"):
        require_shipping(shipping)


@pytest.mark.parametrize("shipping", ["consolidated", "parcel"])
def test_require_shipping_accepts_the_two_models(shipping: Any) -> None:
    require_shipping(shipping)


# --- GccConfig: market code from the dict key ---------------------------------------------


def test_market_code_injected_from_key(config_path: Path) -> None:
    config = load_gcc_config(config_path)
    for code, market in config.markets.items():
        assert market.code == code


def test_explicit_matching_market_code_accepted(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["code"] = "KSA"
    assert _load_config(write_json, raw_config).markets["KSA"].code == "KSA"


def test_conflicting_market_code_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["code"] = "UAE"
    _reject_config(write_json, raw_config, "code", "UAE")


def test_code_injection_does_not_mutate_input(raw_config: Raw) -> None:
    GccConfig.model_validate(raw_config)
    assert "code" not in _ksa(raw_config)


# --- GccConfig: market currency must be in the FX table -----------------------------------


def test_unknown_market_currency_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["currency"]["code"] = "XYZ"
    _reject_config(write_json, raw_config, "XYZ", "per_usd")


# --- GccConfig: at least one market -------------------------------------------------------


def test_config_with_no_markets_rejected(write_json: WriteJson, raw_config: Raw) -> None:
    # A config with nothing to price is a broken file, not something each front end handles.
    raw_config["markets"] = {}
    _reject_config(write_json, raw_config, "markets", "at least one market")


def test_config_with_no_markets_rejected_without_a_file(raw_config: Raw) -> None:
    raw_config["markets"] = {}
    with pytest.raises(ValidationError, match="at least one market"):
        GccConfig.model_validate(raw_config)


# --- loaders: DataFileError ---------------------------------------------------------------


def test_malformed_json_raises_data_file_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(DataFileError) as excinfo:
        load_catalogue(path)

    assert str(path) in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, ValidationError)


def test_validation_error_names_the_file(write_json: WriteJson, raw_config: Raw) -> None:
    _ksa(raw_config)["tax"]["vat_rate"] = 0.15
    path = write_json(raw_config)

    with pytest.raises(DataFileError) as excinfo:
        load_gcc_config(path)

    assert str(path) in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, ValidationError)


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_catalogue(tmp_path / "nope.json")
