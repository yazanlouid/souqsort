"""M5: the `price` command-line interface (SPEC §10); M11: the `report` command (§9.6)."""

import ast
import csv
import io
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import souqsort
from helpers import FOR_SALE_COUNTS, REPORT_ORDERED_AT
from souqsort.cli import _csv_cell, main
from souqsort.loaders import load_sample_orders
from souqsort.models import Catalogue, GccConfig
from souqsort.pipeline import localise_and_summarise
from souqsort.pricing.money import format_money
from souqsort.report import build_report, render_report

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = Path(souqsort.__file__).resolve().parent
CATALOGUE_PATH = REPO_ROOT / "data" / "raw" / "global_products.json"
CONFIG_PATH = REPO_ROOT / "data" / "raw" / "gcc_config.json"
ORDERS_PATH = REPO_ROOT / "data" / "raw" / "sample_orders.json"
ZERO_VAT_CONFIG_PATH = Path(__file__).resolve().parent / "fixtures" / "zero_vat_config.json"

HEADPHONES = "ELEC-HP-001"
BAG = "FASH-BAG-014"
ESPRESSO = "HOME-ESP-031"
KETTLEBELL = "SPRT-KTB-020"
TEA = "GROC-TEA-060"


def _price(
    market: str = "KSA", catalogue: Path = CATALOGUE_PATH, config: Path = CONFIG_PATH
) -> tuple[str, ...]:
    """Arguments for `price` with explicit data files, so tests do not depend on the cwd."""
    return ("price", "--market", market, "--catalogue", str(catalogue), "--config", str(config))


PRICE_KSA = _price()
THU_EVENING = ("--ordered-at", "2026-10-15T20:59Z")  # Thu 23:59 in Riyadh: after the cutoff

KSA_FOR_SALE = FOR_SALE_COUNTS["KSA"]  # the table and the CSV leave out what KSA does not sell
VANILLA = "GROC-VAN-061"
GUMMY_BEARS = "GROC-GUM-062"

TABLE_HEADER = ["SKU", "Name", "Shelf price (SAR)", "Margin %", "Duty", "Delivery", "Flags"]
CSV_HEADER = [
    "sku",
    "name_en",
    "currency",
    "shelf_price",
    "margin_percent",
    "duty_percent",
    "duty_waived",
    "delivery_date",
    "flags",
]

# Table columns, by position.
SKU, NAME, PRICE, MARGIN, DUTY, DELIVERY, FLAGS = range(7)


# --- helpers and fixtures -----------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    code: int
    out: str
    err: str


def _clock_must_not_be_read() -> datetime:
    raise AssertionError("the clock was read, but this run should not need it")


def _cells(line: str) -> list[str]:
    """Split a table line into cells; columns are at least two spaces apart."""
    return re.split(r"\s{2,}", line.strip())


def _table_lines(out: str) -> tuple[str, str, list[str]]:
    """The header line, the rule under it and the data lines of the printed table."""
    lines = out.splitlines()
    rule_at = next(i for i, line in enumerate(lines) if line.startswith("---"))
    rows: list[str] = []
    for line in lines[rule_at + 1 :]:
        if not line.strip():
            break
        rows.append(line)
    return lines[rule_at - 1], lines[rule_at], rows


def _table(out: str) -> tuple[list[str], dict[str, list[str]]]:
    """The header cells, and the data rows keyed by SKU in printed order."""
    header, _, rows = _table_lines(out)
    return _cells(header), {cells[SKU]: cells for cells in map(_cells, rows)}


def _write_json(path: Path, obj: Any) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def _read_csv(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


@pytest.fixture
def run(capsys: pytest.CaptureFixture[str]) -> Callable[..., Result]:
    """Run the CLI in-process. The clock is off limits unless a test passes its own ``now``."""

    def run(*argv: str, now: Callable[[], datetime] = _clock_must_not_be_read) -> Result:
        try:
            code = main(list(argv), now=now)
        except SystemExit as exc:  # argparse reports usage errors and --help by exiting
            if not isinstance(exc.code, int):
                raise
            code = exc.code
        captured = capsys.readouterr()
        return Result(code, captured.out, captured.err)

    return run


# --- the table ----------------------------------------------------------------------------


def test_price_exits_zero_and_prints_the_expected_columns(run: Callable[..., Result]) -> None:
    result = run(*PRICE_KSA, *THU_EVENING)

    assert result.code == 0
    assert result.err == ""
    header, rows = _table(result.out)
    assert header == TABLE_HEADER
    assert len(rows) == KSA_FOR_SALE
    assert all(len(cells) == 7 for cells in rows.values())


def test_rows_are_in_catalogue_order(run: Callable[..., Result], catalogue: Catalogue) -> None:
    _, rows = _table(run(*PRICE_KSA, *THU_EVENING).out)
    not_sold = (VANILLA, GUMMY_BEARS)
    assert list(rows) == [p.sku for p in catalogue.products if p.sku not in not_sold]


def test_worked_example_rows(run: Callable[..., Result]) -> None:
    _, rows = _table(run(*PRICE_KSA, *THU_EVENING).out)

    assert rows[HEADPHONES] == [
        "ELEC-HP-001",
        "Wireless Noise-Cancelling Headphones",
        "686.95",
        "58.7%",
        "5.0%",
        "2026-10-25",
        "-",
    ]
    assert rows[BAG] == [
        "FASH-BAG-014",
        "Leather Crossbody Bag",
        "594.95",
        "64.6%",
        "12.0%",
        "2026-10-25",
        "missing_arabic_name",
    ]


def test_table_shows_the_same_result_as_the_pipeline(
    run: Callable[..., Result], catalogue: Catalogue, config: GccConfig
) -> None:
    ordered_at = datetime(2026, 10, 15, 20, 59, tzinfo=UTC)
    expected = localise_and_summarise(catalogue.products, config, "KSA", ordered_at).items

    _, rows = _table(run(*PRICE_KSA, *THU_EVENING).out)

    for item in expected:
        cells = rows[item.sku]
        assert cells[NAME] == item.name_en
        assert cells[PRICE] == format_money(item.quote.shelf_price, 2)
        assert cells[DUTY] == f"{format_money(item.quote.duty_rate * 100, 1)}%"
        assert cells[DELIVERY] == item.delivery.delivery_date.isoformat()
        assert cells[FLAGS] == (",".join(item.flags) or "-")


def test_margin_is_a_percentage_with_one_decimal(run: Callable[..., Result]) -> None:
    _, rows = _table(run(*PRICE_KSA, *THU_EVENING).out)
    for cells in rows.values():
        assert re.fullmatch(r"-?\d+\.\d%", cells[MARGIN]), cells


def test_flags_column(run: Callable[..., Result]) -> None:
    _, rows = _table(run(*PRICE_KSA, *THU_EVENING).out)
    flagged = {sku for sku, cells in rows.items() if cells[FLAGS] != "-"}
    assert flagged == {BAG, TEA}


def test_summary_line_names_the_market_order_time_and_adjustment(
    run: Callable[..., Result],
) -> None:
    summary = run(*PRICE_KSA, *THU_EVENING).out.splitlines()[0]

    assert "KSA (Saudi Arabia)" in summary
    assert "2026-10-15 23:59 Asia/Riyadh" in summary  # shown in market local time
    assert "+0 pp" in summary
    assert summary.endswith("   Shipping: consolidated")


def test_numeric_columns_are_right_aligned_and_lines_have_no_trailing_space(
    run: Callable[..., Result],
) -> None:
    header, rule, rows = _table_lines(run(*PRICE_KSA, *THU_EVENING).out)

    price = re.compile(r"\d+\.\d{2}(?=\s+-?\d+\.\d%)")
    price_ends = [match.end() for line in rows for match in price.finditer(line)]
    margin_ends = [line.index("%") for line in rows]
    assert len(price_ends) == len(margin_ends) == KSA_FOR_SALE
    assert len(set(price_ends)) == 1
    assert len(set(margin_ends)) == 1
    for line in (header, rule, *rows):
        assert line == line.rstrip()
        assert len(line) <= len(rule)


def test_output_is_ascii(run: Callable[..., Result]) -> None:
    # Arabic names are not printed, so the output is safe on a Windows console code page.
    assert run(*PRICE_KSA, *THU_EVENING).out.isascii()


# --- not sold (SPEC §7.6, §9.2; M9) --------------------------------------------------------


def _not_sold(out: str) -> tuple[list[str], list[str]]:
    """The lines before the "Not sold in" title, and the section from the title to a blank line."""
    lines = out.splitlines()
    title_at = next(i for i, line in enumerate(lines) if line.startswith("Not sold in "))
    section: list[str] = []
    for line in lines[title_at:]:
        if not line.strip():
            break
        section.append(line)
    return lines[:title_at], section


def test_products_ksa_does_not_sell_are_listed_after_the_table(
    run: Callable[..., Result],
) -> None:
    result = run(*PRICE_KSA, *THU_EVENING)

    assert result.code == 0
    before, section = _not_sold(result.out)
    assert before[-1] == ""  # a blank line after the table
    title, header, rule, *rows = section
    assert title == "Not sold in KSA (2):"
    assert _cells(header) == ["SKU", "Name", "Reasons"]
    assert set(rule.replace("  ", "")) == {"-"}
    assert [_cells(row) for row in rows] == [
        [VANILLA, "Pure Vanilla Extract", "contains_alcohol"],
        [GUMMY_BEARS, "Gummy Bears (pork gelatine)", "contains_pork"],
    ]
    for line in (header, rule, *rows):
        assert line == line.rstrip()


def test_products_not_sold_are_not_in_the_table(run: Callable[..., Result]) -> None:
    _, rows = _table(run(*PRICE_KSA, *THU_EVENING).out)
    assert VANILLA not in rows
    assert GUMMY_BEARS not in rows


def test_several_reasons_are_joined_with_commas(
    run: Callable[..., Result], raw_catalogue: dict[str, Any], tmp_path: Path
) -> None:
    gummy_bears = next(p for p in raw_catalogue["products"] if p["sku"] == GUMMY_BEARS)
    gummy_bears["attributes"]["contains_alcohol"] = True
    catalogue = _write_json(tmp_path / "catalogue.json", raw_catalogue)

    result = run(*_price(catalogue=catalogue), *THU_EVENING)

    _, (title, _header, _rule, *rows) = _not_sold(result.out)
    assert title == "Not sold in KSA (2):"
    assert _cells(rows[1]) == [
        GUMMY_BEARS,
        "Gummy Bears (pork gelatine)",
        "contains_alcohol,contains_pork",  # in the order KSA lists them
    ]


def test_uae_lists_one_product_as_not_sold(run: Callable[..., Result]) -> None:
    result = run(*_price(market="UAE"), *THU_EVENING)

    _, (title, _header, _rule, *rows) = _not_sold(result.out)
    assert title == "Not sold in UAE (1):"
    assert [_cells(row)[0] for row in rows] == [GUMMY_BEARS]
    assert len(_table(result.out)[1]) == FOR_SALE_COUNTS["UAE"]


def test_a_market_that_bans_nothing_prints_no_not_sold_section(
    run: Callable[..., Result],
) -> None:
    result = run(*_price(market="TEST-KWD", config=ZERO_VAT_CONFIG_PATH), *THU_EVENING)

    assert result.code == 0
    assert "Not sold" not in result.out
    assert result.out.splitlines()[-1].strip() != ""


def test_csv_holds_only_the_products_for_sale(run: Callable[..., Result], tmp_path: Path) -> None:
    out_path = tmp_path / "ksa.csv"

    result = run(*PRICE_KSA, *THU_EVENING, "--csv", str(out_path))

    _, *rows = _read_csv(out_path)
    assert len(rows) == KSA_FOR_SALE
    assert {row[0] for row in rows}.isdisjoint({VANILLA, GUMMY_BEARS})
    assert "Wrote 11 rows" in result.out


# --- --duty-adjust (SPEC §7.4) ------------------------------------------------------------


@pytest.mark.parametrize(
    ("points", "expected"),
    [("0", "686.95"), ("3", "705.95"), ("20", "817.95")],  # duty 5%, 8% and 25% on 568.36875
)
def test_duty_adjust_takes_whole_percentage_points(
    run: Callable[..., Result], points: str, expected: str
) -> None:
    result = run(*PRICE_KSA, *THU_EVENING, "--duty-adjust", points)

    assert result.code == 0
    _, rows = _table(result.out)
    assert rows[HEADPHONES][PRICE] == expected
    assert f"+{points} pp" in result.out.splitlines()[0]


def test_duty_adjust_defaults_to_zero(run: Callable[..., Result]) -> None:
    default = run(*PRICE_KSA, *THU_EVENING)
    explicit = run(*PRICE_KSA, *THU_EVENING, "--duty-adjust", "0")
    assert default.out == explicit.out


@pytest.mark.parametrize("value", ["-1", "21", "100", "2.5", "0.03", "abc", ""])
def test_duty_adjust_outside_whole_points_0_to_20_is_a_usage_error(
    run: Callable[..., Result], value: str
) -> None:
    result = run(*PRICE_KSA, *THU_EVENING, "--duty-adjust", value)

    assert result.code == 2
    assert "--duty-adjust" in result.err
    assert result.out == ""


# --- --shipping (SPEC §7.7 and §9.2, M10) ------------------------------------------------


def test_shipping_parcel_prices_direct_parcels(run: Callable[..., Result]) -> None:
    result = run(*PRICE_KSA, *THU_EVENING, "--shipping", "parcel")

    assert result.code == 0
    assert result.out.splitlines()[0].endswith("   Shipping: parcel")
    _, rows = _table(result.out)
    assert rows[HEADPHONES][PRICE] == "660.95"  # SPEC §7.8 E
    assert rows[HEADPHONES][DUTY] == "waived"
    assert rows[ESPRESSO][PRICE] == "4344.95"  # SPEC §7.8 G: above the threshold
    assert rows[ESPRESSO][DUTY] == "5.0%"


@pytest.mark.parametrize(
    ("shipping", "delivery"), [("parcel", "2026-10-21"), ("consolidated", "2026-10-22")]
)
def test_delivery_column_follows_the_shipping_model(
    run: Callable[..., Result], shipping: str, delivery: str
) -> None:
    # Thu 12:00 in Riyadh, before the cutoff (SPEC §8.3).
    result = run(*PRICE_KSA, "--ordered-at", "2026-10-15T12:00", "--shipping", shipping)

    _, rows = _table(result.out)
    assert {cells[DELIVERY] for cells in rows.values()} == {delivery}


KSA_FEE_NOTE = "Each parcel order also pays a customs fee of 15.00 SAR at checkout."


def test_a_ksa_parcel_run_names_the_fee_before_what_is_not_sold(
    run: Callable[..., Result],
) -> None:
    result = run(*PRICE_KSA, *THU_EVENING, "--shipping", "parcel")

    assert result.code == 0
    _, _, rows = _table_lines(result.out)
    assert f"{rows[-1]}\n\n{KSA_FEE_NOTE}\n\nNot sold in KSA (2):\n" in result.out


@pytest.mark.parametrize(
    ("market", "shipping"),
    [
        ("KSA", "consolidated"),
        ("UAE", "parcel"),
        ("UAE", "consolidated"),
        ("KWT", "parcel"),
        ("KWT", "consolidated"),
    ],
)
def test_no_fee_line_elsewhere(run: Callable[..., Result], market: str, shipping: str) -> None:
    result = run(*_price(market), *THU_EVENING, "--shipping", shipping)

    assert result.code == 0
    assert "customs fee" not in result.out


def test_shipping_help_names_the_fee_and_the_transit_time(run: Callable[..., Result]) -> None:
    result = run("price", "--help")

    assert (
        "shipping model: consolidated (one commercial import, no de minimis) or parcel "
        "(each order cleared on its own, with its own freight rate, transit time and customs "
        "fee; duty-free under the market's de minimis threshold) (default: consolidated)"
    ) in " ".join(result.out.split())


def test_shipping_defaults_to_consolidated(run: Callable[..., Result]) -> None:
    default = run(*PRICE_KSA, *THU_EVENING)
    explicit = run(*PRICE_KSA, *THU_EVENING, "--shipping", "consolidated")

    assert default.out == explicit.out
    _, rows = _table(default.out)
    assert "waived" not in {cells[DUTY] for cells in rows.values()}


def test_duty_column_includes_the_duty_adjustment(run: Callable[..., Result]) -> None:
    _, rows = _table(run(*PRICE_KSA, *THU_EVENING, "--duty-adjust", "3").out)

    assert rows[BAG][DUTY] == "15.0%"  # fashion 12% + 3 pp
    assert rows[HEADPHONES][DUTY] == "8.0%"


def test_shipping_parcel_with_the_duty_adjustment(run: Callable[..., Result]) -> None:
    result = run(*PRICE_KSA, *THU_EVENING, "--shipping", "parcel", "--duty-adjust", "3")

    _, rows = _table(result.out)
    assert rows[HEADPHONES][PRICE] == "660.95"  # waived: the adjustment changes nothing
    assert rows[ESPRESSO][PRICE] == "4468.95"


def test_csv_records_the_duty_and_whether_it_was_waived(
    run: Callable[..., Result], tmp_path: Path
) -> None:
    out_path = tmp_path / "ksa-parcel.csv"

    result = run(*PRICE_KSA, *THU_EVENING, "--shipping", "parcel", "--csv", str(out_path))

    assert result.code == 0
    header, *rows = _read_csv(out_path)
    assert header == CSV_HEADER
    by_sku = {row[0]: dict(zip(header, row, strict=True)) for row in rows}
    assert (by_sku[HEADPHONES]["duty_percent"], by_sku[HEADPHONES]["duty_waived"]) == (
        "0.0",
        "true",
    )
    assert (by_sku[ESPRESSO]["duty_percent"], by_sku[ESPRESSO]["duty_waived"]) == ("5.0", "false")
    assert by_sku[HEADPHONES]["shelf_price"] == "660.95"


def test_kuwait_never_waives_duty_by_parcel(run: Callable[..., Result]) -> None:
    result = run(*_price("KWT"), *THU_EVENING, "--shipping", "parcel")

    _, rows = _table(result.out)
    assert rows[HEADPHONES][PRICE] == "49.950"  # SPEC §7.9.2
    assert {cells[DUTY] for cells in rows.values()} <= {"5.0%", "0.0%"}


@pytest.mark.parametrize("value", ["bulk", "Parcel", "PARCEL", ""])
def test_unknown_shipping_model_is_a_usage_error(run: Callable[..., Result], value: str) -> None:
    result = run(*PRICE_KSA, *THU_EVENING, "--shipping", value)

    assert result.code == 2
    assert "--shipping" in result.err
    assert result.out == ""


# --- --ordered-at -------------------------------------------------------------------------


def test_ordered_at_with_an_offset_is_the_same_instant_as_utc(run: Callable[..., Result]) -> None:
    utc = run(*PRICE_KSA, "--ordered-at", "2026-10-15T20:59Z")
    riyadh = run(*PRICE_KSA, "--ordered-at", "2026-10-15T23:59+03:00")

    assert utc.code == riyadh.code == 0
    assert utc.out == riyadh.out


@pytest.mark.parametrize(
    ("ordered_at", "local", "delivery"),
    [
        ("2026-10-11T07:00Z", "2026-10-11 10:00", "2026-10-18"),  # SPEC §8.1 row 1
        ("2026-10-11T11:00Z", "2026-10-11 14:00", "2026-10-19"),  # row 2: exactly at the cutoff
        ("2026-10-15T20:59Z", "2026-10-15 23:59", "2026-10-25"),  # row 4
        ("2026-10-15T22:30Z", "2026-10-16 01:30", "2026-10-25"),  # row 5: Friday in Riyadh
    ],
)
def test_ordered_at_drives_the_delivery_date(
    run: Callable[..., Result], ordered_at: str, local: str, delivery: str
) -> None:
    result = run(*PRICE_KSA, "--ordered-at", ordered_at)

    _, rows = _table(result.out)
    assert {cells[DELIVERY] for cells in rows.values()} == {delivery}
    assert f"{local} Asia/Riyadh" in result.out.splitlines()[0]


def test_ordered_at_without_an_offset_is_market_local_time(run: Callable[..., Result]) -> None:
    # 13:59 on the Riyadh clock is before the 14:00 cutoff; 13:59Z is 16:59 there, after it.
    local = run(*PRICE_KSA, "--ordered-at", "2026-10-15T13:59")
    utc = run(*PRICE_KSA, "--ordered-at", "2026-10-15T13:59Z")

    assert local.code == utc.code == 0
    assert "2026-10-15 13:59 Asia/Riyadh" in local.out.splitlines()[0]
    assert "2026-10-15 16:59 Asia/Riyadh" in utc.out.splitlines()[0]
    assert {cells[DELIVERY] for cells in _table(local.out)[1].values()} == {"2026-10-22"}
    assert {cells[DELIVERY] for cells in _table(utc.out)[1].values()} == {"2026-10-25"}


@pytest.mark.parametrize(
    ("ordered_at", "delivery"),
    [
        # London is UTC+1 on this date. Read as UTC, 13:30 would be 14:30 there and miss the
        # cutoff; read as Riyadh time, 15:00 would be 13:00 there and make it.
        ("2026-10-15T13:30", "2026-10-22"),
        ("2026-10-15T15:00", "2026-10-25"),
    ],
)
def test_ordered_at_without_an_offset_uses_the_timezone_from_the_config(
    run: Callable[..., Result],
    raw_config: dict[str, Any],
    tmp_path: Path,
    ordered_at: str,
    delivery: str,
) -> None:
    raw_config["markets"]["KSA"]["calendar"]["timezone"] = "Europe/London"
    london = _write_json(tmp_path / "config.json", raw_config)

    result = run(*_price(config=london), "--ordered-at", ordered_at)

    assert result.code == 0
    assert "Europe/London" in result.out.splitlines()[0]
    assert {cells[DELIVERY] for cells in _table(result.out)[1].values()} == {delivery}


@pytest.mark.parametrize("value", ["yesterday", "2026-13-45T00:00Z", "20:59", ""])
def test_unparseable_ordered_at_is_a_usage_error(run: Callable[..., Result], value: str) -> None:
    result = run(*PRICE_KSA, "--ordered-at", value)

    assert result.code == 2
    assert "--ordered-at" in result.err
    assert result.out == ""


@pytest.mark.parametrize(
    "value", ["2026-10-15", "20261015", "2026-W42-4"], ids=["date", "basic-date", "week-date"]
)
def test_ordered_at_without_a_time_is_a_usage_error(run: Callable[..., Result], value: str) -> None:
    # Read as midnight it would always beat the cutoff, whenever the order was really placed.
    result = run(*PRICE_KSA, "--ordered-at", value)

    assert result.code == 2
    assert "--ordered-at" in result.err
    assert "time" in result.err
    assert result.out == ""


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-15+03:00",  # a date and an offset: the offset must not be read as 03:00
        "2026-10-15-03:00",
        "2026-10-15x20:59",  # only T or a space may separate the date and the time
        "2026-10-15T20",  # an hour with no minutes
        "20261015T2059Z",  # basic format: accepted by the parser, but not by this CLI
    ],
)
def test_ordered_at_must_be_a_date_then_a_time(run: Callable[..., Result], value: str) -> None:
    result = run(*PRICE_KSA, "--ordered-at", value)

    assert result.code == 2
    assert "--ordered-at" in result.err
    assert result.out == ""


@pytest.mark.parametrize(
    ("value", "local"),
    [
        ("2026-10-15 20:59Z", "2026-10-15 23:59"),  # a space instead of T
        ("2026-10-15T20:59:30Z", "2026-10-15 23:59"),  # seconds
        ("2026-10-15T23:59:30.250+03:00", "2026-10-15 23:59"),  # fraction and offset
        ("2026-10-15T15:59-05:00", "2026-10-15 23:59"),  # a negative offset
        ("2026-10-15T23:59:30", "2026-10-15 23:59"),  # seconds, market local time
    ],
)
def test_ordered_at_accepted_forms(run: Callable[..., Result], value: str, local: str) -> None:
    result = run(*PRICE_KSA, "--ordered-at", value)

    assert result.code == 0
    assert f"{local} Asia/Riyadh" in result.out.splitlines()[0]


def test_ordered_at_midnight_is_accepted_when_written_out(run: Callable[..., Result]) -> None:
    result = run(*PRICE_KSA, "--ordered-at", "2026-10-15T00:00")

    assert result.code == 0
    assert "2026-10-15 00:00 Asia/Riyadh" in result.out.splitlines()[0]


# --- the clock: read only for the default, and only through `now` -------------------------


def test_ordered_at_defaults_to_now(run: Callable[..., Result]) -> None:
    calls: list[datetime] = []

    def sunday_morning() -> datetime:
        calls.append(datetime(2026, 10, 11, 7, 0, tzinfo=UTC))  # Sun 10:00 in Riyadh
        return calls[-1]

    result = run(*PRICE_KSA, now=sunday_morning)

    assert result.code == 0
    assert len(calls) == 1
    assert "2026-10-11 10:00 Asia/Riyadh" in result.out.splitlines()[0]
    assert {cells[DELIVERY] for cells in _table(result.out)[1].values()} == {"2026-10-18"}


def test_clock_is_not_read_when_ordered_at_is_given(run: Callable[..., Result]) -> None:
    result = run(*PRICE_KSA, *THU_EVENING, now=_clock_must_not_be_read)
    assert result.code == 0


def _clock_reads(source: str) -> list[str]:
    """References to the clock in Python source, called or not, and imports of ``time``."""
    reads: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in {"now", "today", "utcnow"}:
            reads.append(ast.unparse(node))
        elif isinstance(node, ast.Import):
            reads += [f"import {a.name}" for a in node.names if a.name.split(".")[0] == "time"]
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            reads.append("from time import")
    return reads


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("stamp = datetime.now()", ["datetime.now"]),
        ("day = date.today()", ["date.today"]),
        ("stamp = dt.datetime.utcnow()", ["dt.datetime.utcnow"]),
        # Not called here, so a search for "now(" would miss it.
        ("make = dict(default_factory=datetime.now)", ["datetime.now"]),
        ("import time", ["import time"]),
        ("from time import time_ns", ["from time import"]),
        ("cutoff = dt.time(14, 0)", []),  # a time of day, not the clock
        ("stamp = now()", []),  # an injected callable
    ],
    ids=[
        "now",
        "today",
        "utcnow",
        "uncalled",
        "time-module",
        "from-time",
        "time-of-day",
        "injected",
    ],
)
def test_clock_guard_recognises_clock_reads(source: str, expected: list[str]) -> None:
    assert _clock_reads(source) == expected


def test_only_the_cli_reads_the_clock() -> None:
    reads = {
        path.relative_to(SRC_DIR).as_posix(): _clock_reads(path.read_text("utf-8"))
        for path in SRC_DIR.rglob("*.py")
    }

    assert {name: found for name, found in reads.items() if found} == {"cli.py": ["datetime.now"]}


def test_src_does_not_import_pandas() -> None:
    pandas_import = re.compile(r"^\s*(?:import|from)\s+pandas\b", re.MULTILINE)
    offenders = [
        path.relative_to(SRC_DIR).as_posix()
        for path in SRC_DIR.rglob("*.py")
        if pandas_import.search(path.read_text("utf-8"))
    ]

    assert offenders == []


# --- --csv --------------------------------------------------------------------------------


def test_csv_has_the_table_columns_plus_currency(
    run: Callable[..., Result], tmp_path: Path
) -> None:
    out_path = tmp_path / "ksa.csv"

    result = run(*PRICE_KSA, *THU_EVENING, "--csv", str(out_path))

    assert result.code == 0
    header, *rows = _read_csv(out_path)
    assert header == CSV_HEADER
    assert len(rows) == KSA_FOR_SALE
    assert rows[0] == [
        "ELEC-HP-001",
        "Wireless Noise-Cancelling Headphones",
        "SAR",
        "686.95",
        "58.7",
        "5.0",
        "false",
        "2026-10-25",
        "",
    ]
    assert rows[2] == [
        "FASH-BAG-014",
        "Leather Crossbody Bag",
        "SAR",
        "594.95",
        "64.6",
        "12.0",
        "false",
        "2026-10-25",
        "missing_arabic_name",
    ]


def test_csv_matches_the_printed_table(run: Callable[..., Result], tmp_path: Path) -> None:
    out_path = tmp_path / "ksa.csv"

    result = run(*PRICE_KSA, *THU_EVENING, "--duty-adjust", "3", "--csv", str(out_path))

    _, table_rows = _table(result.out)  # the table is still printed
    _, *csv_rows = _read_csv(out_path)
    assert [row[0] for row in csv_rows] == list(table_rows)
    for sku, name, currency, price, margin, duty, waived, delivery, flags in csv_rows:
        cells = table_rows[sku]
        assert currency == "SAR"
        assert [name, price, f"{margin}%", f"{duty}%", delivery] == cells[NAME:FLAGS]
        assert waived == "false"
        assert flags == ("" if cells[FLAGS] == "-" else cells[FLAGS])


def test_csv_creates_missing_parent_folders(run: Callable[..., Result], tmp_path: Path) -> None:
    out_path = tmp_path / "outputs" / "2026-10" / "ksa.csv"
    assert not out_path.parent.parent.exists()

    result = run(*PRICE_KSA, *THU_EVENING, "--csv", str(out_path))

    assert result.code == 0
    assert result.err == ""
    assert len(_read_csv(out_path)) == KSA_FOR_SALE + 1  # header + products


def test_csv_reports_where_it_was_written(run: Callable[..., Result], tmp_path: Path) -> None:
    out_path = tmp_path / "ksa.csv"

    result = run(*PRICE_KSA, *THU_EVENING, "--csv", str(out_path))

    assert f"{KSA_FOR_SALE} rows" in result.out
    assert out_path.name in result.out


def test_csv_overwrites_an_existing_file(run: Callable[..., Result], tmp_path: Path) -> None:
    out_path = tmp_path / "ksa.csv"

    run(*PRICE_KSA, *THU_EVENING, "--csv", str(out_path))
    run(*PRICE_KSA, *THU_EVENING, "--duty-adjust", "3", "--csv", str(out_path))

    rows = _read_csv(out_path)
    assert len(rows) == KSA_FOR_SALE + 1  # header + products
    assert rows[1][3] == "705.95"


def test_csv_has_no_blank_lines_between_rows(run: Callable[..., Result], tmp_path: Path) -> None:
    # Without newline="" the csv module's \r\n becomes \r\r\n on Windows.
    out_path = tmp_path / "ksa.csv"

    run(*PRICE_KSA, *THU_EVENING, "--csv", str(out_path))

    raw = out_path.read_bytes()
    assert b"\r\r\n" not in raw
    assert len(raw.splitlines()) == KSA_FOR_SALE + 1  # header + products


def test_csv_path_that_cannot_be_written_exits_one(
    run: Callable[..., Result], tmp_path: Path
) -> None:
    result = run(*PRICE_KSA, *THU_EVENING, "--csv", str(tmp_path))  # a folder, not a file

    assert result.code == 1
    assert tmp_path.name in result.err
    assert "Traceback" not in result.err


def test_no_csv_is_written_unless_asked(
    run: Callable[..., Result], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = run(*PRICE_KSA, *THU_EVENING)

    assert result.code == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("option", ["--catalogue", "--config"])
def test_csv_refuses_to_overwrite_an_input_file(
    run: Callable[..., Result], tmp_path: Path, option: str
) -> None:
    catalogue = Path(shutil.copyfile(CATALOGUE_PATH, tmp_path / "catalogue.json"))
    config = Path(shutil.copyfile(CONFIG_PATH, tmp_path / "config.json"))
    target = catalogue if option == "--catalogue" else config
    original = target.read_bytes()

    result = run(*_price(catalogue=catalogue, config=config), *THU_EVENING, "--csv", str(target))

    assert result.code == 2
    assert "--csv" in result.err
    assert option in result.err
    assert target.read_bytes() == original
    assert result.out == ""


def test_csv_refuses_an_input_file_spelled_differently(
    run: Callable[..., Result], tmp_path: Path
) -> None:
    catalogue = Path(shutil.copyfile(CATALOGUE_PATH, tmp_path / "catalogue.json"))
    (tmp_path / "sub").mkdir()
    same_file = tmp_path / "sub" / ".." / "catalogue.json"
    original = catalogue.read_bytes()

    result = run(*_price(catalogue=catalogue), *THU_EVENING, "--csv", str(same_file))

    assert result.code == 2
    assert catalogue.read_bytes() == original


# --- --csv: spreadsheet formulas (issue #2) -----------------------------------------------


def test_csv_prefixes_a_formula_name_with_a_quote(
    run: Callable[..., Result], raw_catalogue: dict[str, Any], tmp_path: Path
) -> None:
    name = '=HYPERLINK("http://example.com","x")'
    raw_catalogue["products"][0]["name"]["en"] = name
    catalogue = _write_json(tmp_path / "catalogue.json", raw_catalogue)
    csv_path = tmp_path / "ksa.csv"

    result = run(*_price(catalogue=catalogue), *THU_EVENING, "--csv", str(csv_path))

    assert result.code == 0
    assert _read_csv(csv_path)[1][1] == f"'{name}"
    _, rows = _table(result.out)
    assert rows[HEADPHONES][NAME] == name  # the table is unchanged


@pytest.mark.parametrize("name", ["+1", "-1+2", "@SUM(A1)", "\tTabbed name"])
def test_csv_prefixes_names_that_start_like_a_formula(
    run: Callable[..., Result], raw_catalogue: dict[str, Any], tmp_path: Path, name: str
) -> None:
    raw_catalogue["products"][0]["name"]["en"] = name
    catalogue = _write_json(tmp_path / "catalogue.json", raw_catalogue)
    csv_path = tmp_path / "ksa.csv"

    result = run(*_price(catalogue=catalogue), *THU_EVENING, "--csv", str(csv_path))

    assert result.code == 0
    assert _read_csv(csv_path)[1][1] == f"'{name}"


def test_csv_keeps_a_negative_margin_as_a_number(
    run: Callable[..., Result], raw_catalogue: dict[str, Any], tmp_path: Path
) -> None:
    raw_catalogue["products"][0]["unit_cost"] = "1000.00"  # far above what the price brings in
    catalogue = _write_json(tmp_path / "catalogue.json", raw_catalogue)
    csv_path = tmp_path / "ksa.csv"

    result = run(*_price(catalogue=catalogue), *THU_EVENING, "--csv", str(csv_path))

    assert result.code == 0
    margin = _read_csv(csv_path)[1][4]
    assert margin.startswith("-")
    _, rows = _table(result.out)
    assert rows[HEADPHONES][MARGIN] == f"{margin}%"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("=1+1", "'=1+1"),
        ("+1", "'+1"),
        ("-1+2", "'-1+2"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tx", "'\tx"),
        ("\rx", "'\rx"),
        # Start like a number, but are not a plain decimal.
        ("-12.", "'-12."),
        ("-.5", "'-.5"),
        ("-1e5", "'-1e5"),
        ("--1", "'--1"),
        ("-12.3\n", "'-12.3\n"),
        ("-١٢", "'-١٢"),  # Arabic-Indic digits
        # Left as they are.
        ("-12.3", "-12.3"),
        ("686.95", "686.95"),
        ("0", "0"),
        ("Leather Crossbody Bag", "Leather Crossbody Bag"),
        ("", ""),
        ("missing_arabic_name", "missing_arabic_name"),
    ],
)
def test_csv_cell_escapes_only_what_a_spreadsheet_would_run(text: str, expected: str) -> None:
    assert _csv_cell(text) == expected


# --- markets and data files ---------------------------------------------------------------


def test_another_market_from_another_config(run: Callable[..., Result]) -> None:
    result = run(*_price(market="TEST-KWD", config=ZERO_VAT_CONFIG_PATH), *THU_EVENING)

    assert result.code == 0
    header, rows = _table(result.out)
    assert header[PRICE] == "Shelf price (KWD)"
    assert rows[HEADPHONES][PRICE] == "48.950"
    assert all(re.fullmatch(r"\d+\.\d{3}", cells[PRICE]) for cells in rows.values())
    assert "Asia/Kuwait" in result.out.splitlines()[0]


@pytest.mark.parametrize(
    ("market", "currency", "headphones", "price_pattern", "timezone"),
    [
        ("UAE", "AED", "612.99", r"\d+\.\d{2}", "Asia/Dubai"),
        ("KWT", "KWD", "48.950", r"\d+\.\d{3}", "Asia/Kuwait"),
    ],
)
def test_every_configured_market_prints_in_its_own_currency(
    run: Callable[..., Result],
    market: str,
    currency: str,
    headphones: str,
    price_pattern: str,
    timezone: str,
) -> None:
    result = run(*_price(market=market), *THU_EVENING)

    assert result.code == 0
    header, rows = _table(result.out)
    assert header[PRICE] == f"Shelf price ({currency})"
    assert rows[HEADPHONES][PRICE] == headphones  # SPEC §7.8, worked examples C and D
    assert all(re.fullmatch(price_pattern, cells[PRICE]) for cells in rows.values())
    assert timezone in result.out.splitlines()[0]


def test_unknown_market_is_a_usage_error_listing_the_configured_markets(
    run: Callable[..., Result], config: GccConfig
) -> None:
    result = run(*_price(market="ZZZ"), *THU_EVENING)

    assert result.code == 2
    assert "ZZZ" in result.err
    assert f"configured markets: {', '.join(sorted(config.markets))}" in result.err
    assert "usage: python -m souqsort price" in result.err  # the price command's own usage
    assert "--market" in result.err
    assert result.out == ""


@pytest.mark.parametrize(
    "argv",
    [(), ("price",), ("price", *THU_EVENING), ("refund", "--market", "KSA")],
    ids=["no-command", "no-market", "no-market-with-time", "unknown-command"],
)
def test_missing_command_or_market_is_a_usage_error(
    run: Callable[..., Result], argv: tuple[str, ...]
) -> None:
    assert run(*argv).code == 2


def test_data_files_default_to_data_raw_under_the_current_folder(
    run: Callable[..., Result], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO_ROOT)

    result = run("price", "--market", "KSA", *THU_EVENING)

    assert result.code == 0
    assert len(_table(result.out)[1]) == KSA_FOR_SALE


def test_missing_data_file_exits_one_naming_the_file(
    run: Callable[..., Result], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # no data/raw here

    result = run("price", "--market", "KSA", *THU_EVENING)

    assert result.code == 1
    assert "gcc_config.json" in result.err or "global_products.json" in result.err
    assert "Traceback" not in result.err
    assert result.out == ""


def test_missing_catalogue_file_exits_one(run: Callable[..., Result], tmp_path: Path) -> None:
    missing = tmp_path / "no_such_catalogue.json"

    result = run(*_price(catalogue=missing), *THU_EVENING)

    assert result.code == 1
    assert "no_such_catalogue.json" in result.err
    assert result.out == ""


def test_invalid_catalogue_exits_one_with_the_validation_message(
    run: Callable[..., Result], raw_catalogue: dict[str, Any], tmp_path: Path
) -> None:
    raw_catalogue["products"][0]["base_price"] = 149.99  # a JSON number, not a string
    bad = _write_json(tmp_path / "float_price.json", raw_catalogue)

    result = run(*_price(catalogue=bad), *THU_EVENING)

    assert result.code == 1
    assert "float_price.json" in result.err
    assert "base_price" in result.err
    assert "Traceback" not in result.err
    assert result.out == ""


def test_config_that_is_not_json_exits_one(run: Callable[..., Result], tmp_path: Path) -> None:
    bad = tmp_path / "broken_config.json"
    bad.write_text("{ not json", encoding="utf-8")

    result = run(*_price(config=bad), *THU_EVENING)

    assert result.code == 1
    assert "broken_config.json" in result.err
    assert result.out == ""


def test_config_with_no_markets_exits_one_as_a_bad_data_file(
    run: Callable[..., Result], raw_config: dict[str, Any], tmp_path: Path
) -> None:
    # Not a usage error about --market: no market code could be right for this file.
    raw_config["markets"] = {}
    config = _write_json(tmp_path / "no_markets.json", raw_config)

    result = run(*_price(config=config), *THU_EVENING)

    assert result.code == 1
    assert "no_markets.json" in result.err
    assert "at least one market" in result.err
    assert "Traceback" not in result.err
    assert result.out == ""


def test_product_that_cannot_be_priced_exits_one_naming_the_sku(
    run: Callable[..., Result],
    raw_catalogue: dict[str, Any],
    raw_config: dict[str, Any],
    tmp_path: Path,
) -> None:
    # Same case as test_pipeline: no charm pricing, and rounding swallows the goods value.
    raw_config["markets"]["KSA"]["currency"]["charm_ending"] = None
    kettlebell = next(p for p in raw_catalogue["products"] if p["sku"] == KETTLEBELL)
    kettlebell.update(base_price="0.0002", weight_kg="32.00")
    catalogue = _write_json(tmp_path / "catalogue.json", raw_catalogue)
    config = _write_json(tmp_path / "config.json", raw_config)

    result = run(*_price(catalogue=catalogue, config=config), *THU_EVENING)

    assert result.code == 1
    assert KETTLEBELL in result.err
    assert "Traceback" not in result.err
    assert result.out == ""


def test_product_without_an_fx_rate_exits_one_naming_the_sku(
    run: Callable[..., Result], raw_config: dict[str, Any], tmp_path: Path
) -> None:
    del raw_config["fx"]["per_usd"]["GBP"]  # still a valid config: no market uses GBP
    config = _write_json(tmp_path / "config.json", raw_config)

    result = run(*_price(config=config), *THU_EVENING)

    assert result.code == 1
    assert BAG in result.err  # the first GBP product
    assert "GBP" in result.err
    assert "Traceback" not in result.err
    assert result.out == ""


def test_amount_too_large_to_price_exits_one_naming_the_sku(
    run: Callable[..., Result], raw_catalogue: dict[str, Any], tmp_path: Path
) -> None:
    raw_catalogue["products"][0]["base_price"] = "1E+30"  # valid, but beyond 28 digits in SAR
    catalogue = _write_json(tmp_path / "catalogue.json", raw_catalogue)

    result = run(*_price(catalogue=catalogue), *THU_EVENING)

    assert result.code == 1
    assert HEADPHONES in result.err
    assert "Traceback" not in result.err
    assert result.out == ""


def test_order_time_beyond_the_calendar_exits_one_naming_the_market(
    run: Callable[..., Result],
) -> None:
    result = run(*PRICE_KSA, "--ordered-at", "9999-12-31T23:00Z")

    assert result.code == 1
    assert "KSA" in result.err
    assert "Traceback" not in result.err
    assert result.out == ""


@pytest.mark.parametrize(
    "bug",
    [ValueError("boom"), ArithmeticError("boom"), RuntimeError("boom")],
    ids=["ValueError", "ArithmeticError", "RuntimeError"],
)
def test_unexpected_errors_are_not_turned_into_an_exit_code(
    run: Callable[..., Result], monkeypatch: pytest.MonkeyPatch, bug: Exception
) -> None:
    # Only LocalisationError, DataFileError and OSError are reported as messages. Anything
    # else is a bug, and a bug should show its traceback.
    def broken(*args: Any, **kwargs: Any) -> None:
        raise bug

    monkeypatch.setattr("souqsort.cli.localise_and_summarise", broken)

    with pytest.raises(type(bug), match="boom"):
        run(*PRICE_KSA, *THU_EVENING)


# --- output encoding ----------------------------------------------------------------------


def test_names_the_output_encoding_cannot_represent_are_replaced_not_fatal(
    raw_catalogue: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Piped or redirected output on Windows is in the ANSI code page, which has no U+02BF or
    # U+0101. The table must still print, and the CSV, which is UTF-8, keeps the real name.
    name = "Oud ʿAttar Halāl"
    raw_catalogue["products"][0]["name"]["en"] = name
    catalogue = _write_json(tmp_path / "catalogue.json", raw_catalogue)
    csv_path = tmp_path / "ksa.csv"
    piped = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(piped, encoding="cp1252"))

    code = main([*_price(catalogue=catalogue), *THU_EVENING, "--csv", str(csv_path)])

    sys.stdout.flush()
    printed = piped.getvalue().decode("cp1252")
    assert code == 0
    _, rows = _table(printed)
    assert len(rows) == KSA_FOR_SALE
    assert rows[HEADPHONES][NAME] == "Oud ?Attar Hal?l"
    assert rows[HEADPHONES][PRICE] == "686.95"
    assert _read_csv(csv_path)[1][1] == name


def test_empty_catalogue_prints_the_header_and_no_rows(
    run: Callable[..., Result], raw_catalogue: dict[str, Any], tmp_path: Path
) -> None:
    raw_catalogue["products"] = []
    catalogue = _write_json(tmp_path / "catalogue.json", raw_catalogue)
    csv_path = tmp_path / "empty.csv"

    result = run(*_price(catalogue=catalogue), *THU_EVENING, "--csv", str(csv_path))

    assert result.code == 0
    header, rows = _table(result.out)
    assert header == TABLE_HEADER
    assert rows == {}
    assert _read_csv(csv_path) == [CSV_HEADER]


# --- help and `python -m souqsort` --------------------------------------------------------


def test_price_help_lists_every_option(run: Callable[..., Result]) -> None:
    result = run("price", "--help")

    assert result.code == 0
    options = (
        "--market",
        "--shipping",
        "--duty-adjust",
        "--ordered-at",
        "--csv",
        "--catalogue",
        "--config",
    )
    for option in options:
        assert option in result.out
    assert "{consolidated,parcel}" in result.out
    assert "(default: consolidated)" in " ".join(result.out.split())  # help may wrap lines


def test_python_dash_m_souqsort_runs_the_cli() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "souqsort", "price", "--market", "KSA", *THU_EVENING],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    header, rows = _table(completed.stdout)
    assert header == TABLE_HEADER
    assert rows[HEADPHONES][PRICE] == "686.95"
    assert len(rows) == KSA_FOR_SALE


# --- report (M11, SPEC §9.6) --------------------------------------------------------------

REPORT_ORDER = ("--ordered-at", "2026-10-15T09:00Z")
NO_OFFSET_MESSAGE = (
    "argument --ordered-at: the report covers every market, so give a UTC offset, "
    "e.g. 2026-10-15T09:00Z"
)


def _report(
    *options: str,
    catalogue: Path = CATALOGUE_PATH,
    config: Path = CONFIG_PATH,
    orders: Path = ORDERS_PATH,
) -> tuple[str, ...]:
    """Arguments for `report` with explicit data files, so tests do not depend on the cwd."""
    return (
        "report",
        "--catalogue",
        str(catalogue),
        "--config",
        str(config),
        "--orders",
        str(orders),
        *options,
    )


def _expected_report(catalogue: Catalogue, config: GccConfig, ordered_at: datetime) -> bytes:
    """The report for the sample orders, as the CLI writes it."""
    sample_orders = load_sample_orders(ORDERS_PATH)
    return render_report(build_report(catalogue, config, sample_orders, ordered_at)).encode("utf-8")


def test_report_is_written_to_outputs_by_default(
    run: Callable[..., Result],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    catalogue: Catalogue,
    config: GccConfig,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = run(*_report(*REPORT_ORDER))

    assert result.code == 0, result.err
    written = tmp_path / "outputs" / "GCC_EXPANSION_REPORT.md"
    assert written.read_bytes() == _expected_report(catalogue, config, REPORT_ORDERED_AT)
    assert result.out == "Wrote the expansion report to outputs/GCC_EXPANSION_REPORT.md\n"


def test_report_out_creates_its_folder_and_prints_the_path_as_given(
    run: Callable[..., Result], tmp_path: Path
) -> None:
    out = tmp_path / "new" / "deeper" / "report.md"

    result = run(*_report(*REPORT_ORDER, "--out", str(out)))

    assert result.code == 0, result.err
    assert out.read_bytes().startswith(b"# GCC expansion report\n")
    assert result.out == f"Wrote the expansion report to {out}\n"


def test_report_has_unix_line_endings_on_every_os(
    run: Callable[..., Result], tmp_path: Path
) -> None:
    out = tmp_path / "report.md"

    run(*_report(*REPORT_ORDER, "--out", str(out)))

    raw = out.read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\n\n")


def test_report_overwrites_an_existing_file(run: Callable[..., Result], tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    out.write_text("old", encoding="utf-8")

    result = run(*_report(*REPORT_ORDER, "--out", str(out)))

    assert result.code == 0
    assert out.read_bytes().startswith(b"# GCC expansion report\n")


def test_report_ordered_at_with_an_offset_is_that_instant(
    run: Callable[..., Result], tmp_path: Path, catalogue: Catalogue, config: GccConfig
) -> None:
    out = tmp_path / "report.md"

    run(*_report("--ordered-at", "2026-10-15T12:00+03:00", "--out", str(out)))

    assert out.read_bytes() == _expected_report(catalogue, config, REPORT_ORDERED_AT)


@pytest.mark.parametrize("value", ["2026-10-15T09:00", "2026-10-15 12:00"])
def test_report_ordered_at_without_an_offset_is_a_usage_error(
    run: Callable[..., Result], tmp_path: Path, value: str
) -> None:
    out = tmp_path / "report.md"

    result = run(*_report("--ordered-at", value, "--out", str(out)))

    assert result.code == 2
    assert NO_OFFSET_MESSAGE in result.err
    assert result.out == ""
    assert not out.exists()


@pytest.mark.parametrize("value", ["2026-10-15", "yesterday", "2026-10-15T25:00Z"])
def test_report_unparseable_ordered_at_is_a_usage_error(
    run: Callable[..., Result], value: str
) -> None:
    result = run(*_report("--ordered-at", value))

    assert result.code == 2
    assert "--ordered-at" in result.err


def test_report_ordered_at_defaults_to_now(
    run: Callable[..., Result], tmp_path: Path, catalogue: Catalogue, config: GccConfig
) -> None:
    out = tmp_path / "report.md"

    result = run(*_report("--out", str(out)), now=lambda: REPORT_ORDERED_AT)

    assert result.code == 0
    assert out.read_bytes() == _expected_report(catalogue, config, REPORT_ORDERED_AT)


def test_report_does_not_read_the_clock_when_ordered_at_is_given(
    run: Callable[..., Result], tmp_path: Path
) -> None:
    result = run(*_report(*REPORT_ORDER, "--out", str(tmp_path / "r.md")))

    assert result.code == 0  # the fixture's clock raises if it is read


@pytest.mark.parametrize("option", ["--catalogue", "--config"])
def test_report_refuses_to_overwrite_an_input_file(
    run: Callable[..., Result], tmp_path: Path, option: str
) -> None:
    catalogue = Path(shutil.copyfile(CATALOGUE_PATH, tmp_path / "catalogue.json"))
    config = Path(shutil.copyfile(CONFIG_PATH, tmp_path / "config.json"))
    target = catalogue if option == "--catalogue" else config
    original = target.read_bytes()

    result = run(*_report(*REPORT_ORDER, "--out", str(target), catalogue=catalogue, config=config))

    assert result.code == 2
    assert "--out" in result.err
    assert option in result.err
    assert target.read_bytes() == original
    assert result.out == ""


def test_report_with_a_missing_data_file_exits_one(
    run: Callable[..., Result], tmp_path: Path
) -> None:
    missing = tmp_path / "no_such_config.json"
    out = tmp_path / "report.md"

    result = run(*_report(*REPORT_ORDER, "--out", str(out), config=missing))

    assert result.code == 1
    assert "no_such_config.json" in result.err
    assert "Traceback" not in result.err
    assert result.out == ""
    assert not out.exists()


def test_report_with_an_invalid_catalogue_exits_one(
    run: Callable[..., Result], raw_catalogue: dict[str, Any], tmp_path: Path
) -> None:
    raw_catalogue["products"][0]["base_price"] = 149.99
    bad = _write_json(tmp_path / "float_price.json", raw_catalogue)

    result = run(*_report(*REPORT_ORDER, "--out", str(tmp_path / "r.md"), catalogue=bad))

    assert result.code == 1
    assert "float_price.json" in result.err
    assert "Traceback" not in result.err


def test_report_order_time_beyond_the_calendar_exits_one(
    run: Callable[..., Result], tmp_path: Path
) -> None:
    out = tmp_path / "report.md"

    result = run(*_report("--ordered-at", "9999-12-31T23:00Z", "--out", str(out)))

    assert result.code == 1
    assert "KSA" in result.err
    assert "Traceback" not in result.err
    assert not out.exists()


def test_report_that_cannot_be_written_exits_one(
    run: Callable[..., Result], tmp_path: Path
) -> None:
    result = run(*_report(*REPORT_ORDER, "--out", str(tmp_path)))  # a folder, not a file

    assert result.code == 1
    assert tmp_path.name in result.err
    assert "Traceback" not in result.err
    assert result.out == ""


def test_report_help_lists_every_option(run: Callable[..., Result]) -> None:
    result = run("report", "--help")

    assert result.code == 0
    for option in ("--ordered-at", "--out", "--catalogue", "--config", "--orders"):
        assert option in result.out
    assert "outputs/GCC_EXPANSION_REPORT.md" in result.out
    assert "data/raw/sample_orders.json" in result.out


def test_report_help_says_it_prices_the_sample_orders(run: Callable[..., Result]) -> None:
    result = run("report", "--help")

    # argparse wraps the description, so compare it with its whitespace collapsed.
    assert result.code == 0
    assert (
        "Write the expansion report: every market in the config and the sample orders for one "
        "order time, side by side, as Markdown."
    ) in " ".join(result.out.split())


# --- the report's sample orders (SPEC §9.6, M18) ------------------------------------------


def test_report_orders_reads_another_file(
    run: Callable[..., Result],
    raw_orders: dict[str, Any],
    tmp_path: Path,
    catalogue: Catalogue,
    config: GccConfig,
) -> None:
    raw_orders["orders_version"] = "2026-12-01"
    raw_orders["orders"] = raw_orders["orders"][2:]  # headphones and a bag
    other = _write_json(tmp_path / "other_orders.json", raw_orders)
    out = tmp_path / "report.md"

    result = run(*_report(*REPORT_ORDER, "--out", str(out), orders=other))

    assert result.code == 0, result.err
    written = out.read_bytes()
    expected = build_report(catalogue, config, load_sample_orders(other), REPORT_ORDERED_AT)
    assert written == render_report(expected).encode("utf-8")
    assert b"catalogue 2026-10-01 and sample orders 2026-12-01.\n" in written
    assert b"| Two lip balms |" not in written


def test_report_refuses_to_overwrite_the_orders_file(
    run: Callable[..., Result], tmp_path: Path
) -> None:
    orders = Path(shutil.copyfile(ORDERS_PATH, tmp_path / "orders.json"))
    original = orders.read_bytes()

    result = run(*_report(*REPORT_ORDER, "--out", str(orders), orders=orders))

    assert result.code == 2
    assert "argument --out:" in result.err
    assert "--orders file" in result.err
    assert orders.read_bytes() == original
    assert result.out == ""


def test_report_with_a_missing_orders_file_exits_one(
    run: Callable[..., Result], tmp_path: Path
) -> None:
    out = tmp_path / "report.md"

    result = run(*_report(*REPORT_ORDER, "--out", str(out), orders=tmp_path / "no_orders.json"))

    assert result.code == 1
    assert "no_orders.json" in result.err
    assert "Traceback" not in result.err
    assert result.out == ""
    assert not out.exists()


def test_report_with_a_sample_order_sku_not_in_the_catalogue_exits_one(
    run: Callable[..., Result], raw_orders: dict[str, Any], tmp_path: Path
) -> None:
    raw_orders["orders"][2]["lines"][0]["sku"] = "ELEC-HP-999"
    orders = _write_json(tmp_path / "unknown_sku.json", raw_orders)
    out = tmp_path / "report.md"

    result = run(*_report(*REPORT_ORDER, "--out", str(out), orders=orders))

    assert result.code == 1
    assert result.err == (
        "souqsort: error: headphones-and-bag: ELEC-HP-999 is not in the catalogue\n"
    )
    assert result.out == ""
    assert not out.exists()


def test_top_level_help_lists_both_commands(run: Callable[..., Result]) -> None:
    result = run("--help")

    assert result.code == 0
    assert "price" in result.out
    assert "report" in result.out


def test_report_figure_too_large_to_display_exits_one(
    run: Callable[..., Result], raw_catalogue: dict[str, Any], tmp_path: Path
) -> None:
    for product in raw_catalogue["products"]:
        product["base_price"] = product["unit_cost"] = "1E-26"
    tiny = _write_json(tmp_path / "tiny_prices.json", raw_catalogue)
    out = tmp_path / "report.md"

    result = run(*_report(*REPORT_ORDER, "--out", str(out), catalogue=tiny))

    assert result.code == 1
    assert "average above catalogue price is too large to display" in result.err
    assert "Traceback" not in result.err
    assert result.out == ""
    assert not out.exists()


# --- the order command (SPEC §10.5, M17) --------------------------------------------------

NOON = ("--ordered-at", "2026-10-15T12:00")  # Thu 12:00 in the market: before the cutoff
LIP_BALM = "BEAU-LIP-040"
LICENCE = "DIGI-LIC-050"

ORDER_KSA_EXAMPLE = """\
Market: KSA (Saudi Arabia)   Ordered at: 2026-10-15 12:00 Asia/Riyadh   Duty adjustment: +0 pp
Order: Headphones and a bag

SKU           Name                                  Qty  Consolidated (SAR)  Direct parcel (SAR)
------------  ------------------------------------  ---  ------------------  -------------------
ELEC-HP-001   Wireless Noise-Cancelling Headphones    1              686.95               660.95
FASH-BAG-014  Leather Crossbody Bag                   1              594.95               546.95
Items                                                               1281.90              1207.90
Customs fee                                                               -                15.00
Duty and VAT                                                              -                98.57
Total                                                               1281.90              1321.47
Delivery                                                         2026-10-22           2026-10-21

Direct parcel: the order's CIF, 1049.26 SAR, is not below 1000.00 SAR, so the whole order pays \
duty; the duty its shelf prices left out is added at checkout.
"""


def _order(
    *args: str,
    market: str = "KSA",
    catalogue: Path = CATALOGUE_PATH,
    config: Path = CONFIG_PATH,
    orders: Path = ORDERS_PATH,
) -> tuple[str, ...]:
    """Arguments for `order` with explicit data files, so tests do not depend on the cwd."""
    return (
        "order",
        "--market",
        market,
        *args,
        "--catalogue",
        str(catalogue),
        "--config",
        str(config),
        "--orders",
        str(orders),
    )


def _order_rows(out: str) -> dict[str, list[str]]:
    """The order table's rows keyed by their first cell. Blank cells are not split out."""
    _, _, rows = _table_lines(out)
    return {cells[0]: cells for cells in map(_cells, rows)}


def _last_line(out: str) -> str:
    return out.rstrip("\n").splitlines()[-1]


def test_order_prints_the_spec_example_exactly(run: Callable[..., Result]) -> None:
    result = run(*_order("--sample", "headphones-and-bag", *NOON))

    assert result.code == 0, result.err
    assert result.out == ORDER_KSA_EXAMPLE
    assert result.err == ""


def test_order_in_the_uae(run: Callable[..., Result]) -> None:
    result = run(*_order("--sample", "headphones-and-bag", *NOON, market="UAE"))

    assert result.code == 0, result.err
    rows = _order_rows(result.out)
    assert "Customs fee" not in rows
    assert rows["Duty and VAT"] == ["Duty and VAT", "-", "53.73"]
    assert rows["Total"] == ["Total", "1109.98", "1129.71"]
    assert "is not at or below 1000.00 AED" in _last_line(result.out)


def test_two_lip_balms_in_kuwait(run: Callable[..., Result]) -> None:
    result = run(*_order("--sample", "two-lip-balms", *NOON, market="KWT"))

    assert result.code == 0, result.err
    assert _last_line(result.out) == (
        "Direct parcel: KWT has no de minimis rule, so every line pays duty."
    )


def test_order_of_lip_balms_and_the_licence(run: Callable[..., Result]) -> None:
    result = run(*_order("--item", f"{LIP_BALM}:2", "--item", LICENCE, *NOON))

    assert result.code == 0, result.err
    rows = _order_rows(result.out)
    assert rows[LIP_BALM][2:] == ["2", "33.90", "31.90"]
    assert rows["Total"][-1] == "387.85"
    assert _last_line(result.out) == (
        "Direct parcel: the order's CIF, 27.53 SAR, is below 1000.00 SAR, so de minimis applies."
    )


def test_order_without_a_sample_prints_no_order_name(run: Callable[..., Result]) -> None:
    result = run(*_order("--item", LIP_BALM, *NOON))

    assert result.code == 0, result.err
    assert "Order:" not in result.out
    assert result.out.splitlines()[1] == ""


def test_order_lists_what_the_market_does_not_sell(run: Callable[..., Result]) -> None:
    result = run(*_order("--item", VANILLA, "--item", f"{TEA}:3", *NOON))

    assert result.code == 0, result.err
    assert VANILLA not in _order_rows(result.out)
    assert _order_rows(result.out)[TEA][2] == "3"
    tail = result.out.split("\nNot sold in KSA (1):\n")[1].splitlines()
    assert _cells(tail[0]) == ["SKU", "Name", "Reasons"]
    assert _cells(tail[2]) == [VANILLA, "Pure Vanilla Extract", "contains_alcohol"]
    assert len(tail) == 3


def test_order_that_passes_names_the_lines_the_rule_excludes(run: Callable[..., Result]) -> None:
    result = run(*_order("--item", VANILLA, "--item", HEADPHONES, *NOON, market="UAE"))

    assert result.code == 0, result.err
    assert _order_rows(result.out)["Total"] == ["Total", "668.98", "647.98"]  # §7.10.2 M
    assert _last_line(result.out) == (
        "Direct parcel: the order's CIF, 613.23 AED, is at or below 1000.00 AED, so de minimis "
        "applies, except to GROC-VAN-061, which it excludes."
    )


def test_order_in_which_nothing_travels(run: Callable[..., Result]) -> None:
    result = run(*_order("--item", LICENCE, *NOON))

    assert result.code == 0, result.err
    assert "Customs fee" not in _order_rows(result.out)
    assert _last_line(result.out) == (
        "Direct parcel: nothing in the order travels, so no parcel is sent."
    )


def test_order_over_the_threshold_with_nothing_waived(run: Callable[..., Result]) -> None:
    result = run(*_order("--item", ESPRESSO, *NOON))

    assert result.code == 0, result.err
    assert "Duty and VAT" not in _order_rows(result.out)
    assert _last_line(result.out) == (
        "Direct parcel: the order's CIF, 3597.53 SAR, is not below 1000.00 SAR, so the whole "
        "order pays duty; its shelf prices already include it."
    )


def test_order_the_market_sells_nothing_of(run: Callable[..., Result]) -> None:
    result = run(*_order("--item", GUMMY_BEARS, *NOON))

    assert result.code == 0, result.err
    lines = result.out.splitlines()
    assert lines[1:4] == ["", "KSA sells nothing in this order.", ""]
    assert lines[4] == "Not sold in KSA (1):"
    assert _cells(lines[7]) == [GUMMY_BEARS, "Gummy Bears (pork gelatine)", "contains_pork"]
    assert len(lines) == 8
    assert "Direct parcel" not in result.out


def test_order_at_three_points(run: Callable[..., Result]) -> None:
    result = run(*_order("--item", HEADPHONES, "--item", BAG, "--duty-adjust", "3", *NOON))

    assert result.code == 0, result.err
    assert "Duty adjustment: +3 pp" in result.out.splitlines()[0]
    rows = _order_rows(result.out)
    assert rows["Duty and VAT"][-1] == "134.77"
    assert rows["Total"][-1] == "1357.67"


def test_order_defaults_the_order_time_to_now(run: Callable[..., Result]) -> None:
    result = run(*_order("--item", LIP_BALM), now=lambda: datetime(2026, 10, 15, 9, 0, tzinfo=UTC))

    assert result.code == 0, result.err
    assert "Ordered at: 2026-10-15 12:00 Asia/Riyadh" in result.out


_BAD_ITEMS = (
    "ELEC-HP-001:0",
    "ELEC-HP-001:100",
    "ELEC-HP-001:x",
    "ELEC-HP-001:",
    ":2",
    "ELEC-HP-001:2:3",
    "ELEC-HP-001:-1",
    "ELEC-HP-001:٢",  # an Arabic-Indic digit two: not ASCII
    "",
    # Whitespace, e.g. from copying and pasting, is a format error, not an unknown SKU.
    "ELEC-HP-001 ",
    " ELEC-HP-001",
    "ELEC-HP-001 :2",
    "ELEC-HP-001: 2",
    "ELEC HP-001",
    "ELEC-HP-001\t",
    "ELEC-HP-001\u00a0",  # a no-break space
)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        *(
            (
                ("--item", item),
                "argument --item: must be a SKU, or a SKU and a quantity from 1 to 99 such as "
                f"ELEC-HP-001:2, got {item!r}",
            )
            for item in _BAD_ITEMS
        ),
        (("--item", "ELEC-HP-999"), "argument --item: ELEC-HP-999 is not in the catalogue"),
        (
            ("--item", "ELEC-HP-001", "--item", "ELEC-HP-001:2"),
            "argument --item: ELEC-HP-001 is listed twice",
        ),
        (
            ("--sample", "lip-balm"),
            "argument --sample: lip-balm: unknown order; sample orders: two-lip-balms, "
            "scarf-and-serum, headphones-and-bag",
        ),
        ((), "one of the arguments --sample --item is required"),
        (
            ("--sample", "two-lip-balms", "--item", LIP_BALM),
            "argument --item: not allowed with argument --sample",
        ),
        (("--item", LIP_BALM, "--duty-adjust", "21"), "argument --duty-adjust: must be"),
    ],
)
def test_order_usage_errors_exit_two(
    run: Callable[..., Result], args: tuple[str, ...], message: str
) -> None:
    result = run(*_order(*args, *NOON))

    assert result.code == 2
    assert f"error: {message}" in result.err
    assert result.out == ""


def test_order_unknown_market_exits_two_as_price_does(run: Callable[..., Result]) -> None:
    result = run(*_order("--item", LIP_BALM, *NOON, market="QAT"))

    assert result.code == 2
    assert (
        "error: argument --market: QAT: unknown market; configured markets: KSA, KWT, UAE"
        in result.err
    )


def test_order_with_items_never_reads_the_orders_file(
    run: Callable[..., Result], tmp_path: Path
) -> None:
    result = run(*_order("--item", LIP_BALM, *NOON, orders=tmp_path / "missing.json"))

    assert result.code == 0, result.err


@pytest.mark.parametrize("option", ["catalogue", "config", "orders"])
def test_order_data_file_that_cannot_be_read_exits_one(
    run: Callable[..., Result], tmp_path: Path, option: str
) -> None:
    missing = tmp_path / "missing.json"

    result = run(*_order("--sample", "two-lip-balms", *NOON, **{option: missing}))

    assert result.code == 1
    assert "missing.json" in result.err
    assert "Traceback" not in result.err
    assert result.out == ""


def test_order_invalid_orders_file_exits_one(
    run: Callable[..., Result], raw_orders: dict[str, Any], tmp_path: Path
) -> None:
    raw_orders["orders"][0]["lines"][0]["quantity"] = 0
    bad = _write_json(tmp_path / "bad_orders.json", raw_orders)

    result = run(*_order("--sample", "two-lip-balms", *NOON, orders=bad))

    assert result.code == 1
    assert "bad_orders.json" in result.err
    assert "Traceback" not in result.err


def test_sample_order_with_a_sku_missing_from_the_catalogue_exits_one(
    run: Callable[..., Result], raw_catalogue: dict[str, Any], tmp_path: Path
) -> None:
    raw_catalogue["products"] = [p for p in raw_catalogue["products"] if p["sku"] != BAG]
    catalogue = _write_json(tmp_path / "no_bag.json", raw_catalogue)

    result = run(*_order("--sample", "headphones-and-bag", *NOON, catalogue=catalogue))

    assert result.code == 1
    assert f"{BAG}: not in the catalogue" in result.err
    assert "Traceback" not in result.err
    assert result.out == ""


def test_order_help_lists_every_option(run: Callable[..., Result]) -> None:
    result = run("order", "--help")

    assert result.code == 0
    for option in (
        "--market",
        "--sample",
        "--item",
        "--duty-adjust",
        "--ordered-at",
        "--catalogue",
        "--config",
        "--orders",
    ):
        assert option in result.out
    assert "data/raw/sample_orders.json" in result.out


def test_top_level_help_lists_the_order_command(run: Callable[..., Result]) -> None:
    result = run("--help")

    assert result.code == 0
    assert "order" in result.out
