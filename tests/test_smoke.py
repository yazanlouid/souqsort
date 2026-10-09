"""Smoke test: the package is installed and importable."""

import souqsort


def test_import_souqsort() -> None:
    assert souqsort.__name__ == "souqsort"
