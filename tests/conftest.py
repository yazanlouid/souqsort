"""Shared pytest fixtures for the SouqSort test suite."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from souqsort.loaders import load_catalogue, load_gcc_config
from souqsort.models import Catalogue, GccConfig

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def catalogue_path() -> Path:
    return DATA_DIR / "global_products.json"


@pytest.fixture
def config_path() -> Path:
    return DATA_DIR / "gcc_config.json"


@pytest.fixture
def raw_catalogue(catalogue_path: Path) -> dict[str, Any]:
    """A fresh, mutable copy of the sample catalogue as plain JSON data."""
    data: dict[str, Any] = json.loads(catalogue_path.read_text(encoding="utf-8"))
    return data


@pytest.fixture
def raw_config(config_path: Path) -> dict[str, Any]:
    """A fresh, mutable copy of the sample market config as plain JSON data."""
    data: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    return data


# Loaded once per session so Hypothesis tests can use them (it rejects function-scoped
# fixtures). They are shared, and Pydantic's ``frozen`` is shallow: the dicts inside
# (``per_usd``, ``category_overrides``, ``markets``) can still be mutated.
# Never mutate these or anything reached through them. A test that needs a modified config
# builds a copy with ``model_copy(update=...)``, passing new dicts for any nested dict it
# changes (``model_copy`` is shallow too), or starts from ``raw_config`` / ``raw_catalogue``.


@pytest.fixture(scope="session")
def catalogue() -> Catalogue:
    """The sample catalogue, loaded and validated."""
    return load_catalogue(DATA_DIR / "global_products.json")


@pytest.fixture(scope="session")
def config() -> GccConfig:
    """The sample market config, loaded and validated."""
    return load_gcc_config(DATA_DIR / "gcc_config.json")


@pytest.fixture(scope="session")
def zero_vat_config() -> GccConfig:
    """Test-only config: one KWD market with 3 minor units and 0% VAT."""
    return load_gcc_config(FIXTURES_DIR / "zero_vat_config.json")


@pytest.fixture(scope="session")
def de_minimis_boundary_config() -> GccConfig:
    """Test-only config for SPEC §7.8 H: TEST-BELOW and TEST-AT-OR-BELOW, CIF = 4 x USD price."""
    return load_gcc_config(FIXTURES_DIR / "de_minimis_boundary_config.json")


@pytest.fixture
def write_json(tmp_path: Path) -> Callable[[Any], Path]:
    """Write an object as JSON into a temp file and return its path."""

    def write(obj: Any) -> Path:
        path = tmp_path / "data.json"
        path.write_text(json.dumps(obj), encoding="utf-8")
        return path

    return write
