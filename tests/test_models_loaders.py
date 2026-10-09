"""M1: Pydantic models and JSON loaders for the catalogue and the GCC market config."""

from collections.abc import Callable
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from souqsort.loaders import DataFileError, load_catalogue, load_gcc_config
from souqsort.models import GccConfig, Product, ProductName

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
    assert len(catalogue.products) == 12
    for product in catalogue.products:
        assert isinstance(product.base_price, Decimal)
        assert isinstance(product.unit_cost, Decimal)
        assert isinstance(product.weight_kg, Decimal)

    headphones = next(p for p in catalogue.products if p.sku == HEADPHONES)
    assert headphones.base_price == Decimal("149.99")
    assert headphones.unit_cost == Decimal("62.00")
    assert headphones.weight_kg == Decimal("0.35")
    assert headphones.attributes["contains_lithium_battery"] is True


def test_sample_config_loads(config_path: Path) -> None:
    config = load_gcc_config(config_path)

    assert config.config_version == "2026-10-01"
    assert config.fx.as_of == date(2026, 10, 1)
    assert config.fx.per_usd["SAR"] == Decimal("3.7500")
    assert config.fx.per_usd["GBP"] == Decimal("0.7450")

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
        (date(2027, 2, 22), "Founding Day", False)
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
    assert any(p.attributes.get("contains_alcohol") for p in products)
    assert any(p.attributes.get("contains_pork") for p in products)

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
        (("logistics", "freight_per_kg_usd"), 4.5),
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
            attributes={},
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
        attributes={},
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
        ("logistics", "freight_per_kg_usd"),
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


@pytest.mark.parametrize("field", ["linehaul_business_days", "last_mile_business_days"])
@pytest.mark.parametrize("value", [-1, "3", 3.0])
def test_bad_business_day_count_rejected(
    write_json: WriteJson, raw_config: Raw, field: str, value: Any
) -> None:
    _ksa(raw_config)["logistics"][field] = value
    _reject_config(write_json, raw_config, field)


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
