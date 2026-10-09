"""Shared pytest fixtures for the SouqSort test suite."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"


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


@pytest.fixture
def write_json(tmp_path: Path) -> Callable[[Any], Path]:
    """Write an object as JSON into a temp file and return its path."""

    def write(obj: Any) -> Path:
        path = tmp_path / "data.json"
        path.write_text(json.dumps(obj), encoding="utf-8")
        return path

    return write
