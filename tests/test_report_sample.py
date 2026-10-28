"""M13: docs/GCC_EXPANSION_REPORT.md is the report for the sample data, byte for byte (§9.5)."""

from pathlib import Path

from helpers import REPORT_ORDERED_AT
from souqsort.models import Catalogue, GccConfig, SampleOrders
from souqsort.report import build_report, render_report

SAMPLE_REPORT = Path(__file__).resolve().parents[1] / "docs" / "GCC_EXPANSION_REPORT.md"
REGENERATE = (
    "uv run python -m souqsort report --ordered-at 2026-10-15T09:00Z "
    "--out docs/GCC_EXPANSION_REPORT.md"
)


def test_the_sample_report_is_current(
    catalogue: Catalogue, config: GccConfig, sample_orders: SampleOrders
) -> None:
    expected = render_report(
        build_report(catalogue, config, sample_orders, REPORT_ORDERED_AT)
    ).encode("utf-8")

    assert SAMPLE_REPORT.is_file(), f"{SAMPLE_REPORT} is missing; write it with: {REGENERATE}"
    assert SAMPLE_REPORT.read_bytes() == expected, (
        f"{SAMPLE_REPORT.name} is out of date; regenerate it with: {REGENERATE}"
    )
