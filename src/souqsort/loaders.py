"""Load and validate the catalogue, market config and sample orders JSON files."""

from pathlib import Path

from pydantic import BaseModel, ValidationError

from souqsort.models import Catalogue, GccConfig, SampleOrders


class DataFileError(ValueError):
    """A data file is not valid JSON or does not match its model."""


def _load[M: BaseModel](model: type[M], path: Path) -> M:
    # Validate the raw JSON bytes: numbers reach the Decimal validators as numbers (and are
    # rejected), and the file's UTF-8 is decoded by Pydantic, not the Windows locale.
    raw = path.read_bytes()
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        raise DataFileError(f"{path}: invalid data file\n{exc}") from exc


def load_catalogue(path: Path) -> Catalogue:
    return _load(Catalogue, path)


def load_gcc_config(path: Path) -> GccConfig:
    return _load(GccConfig, path)


def load_sample_orders(path: Path) -> SampleOrders:
    return _load(SampleOrders, path)
