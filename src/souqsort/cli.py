"""Command-line interface.

``main`` is the only place in ``src/`` that reads the clock: ``--ordered-at`` defaults to the
current time, taken from an injectable ``now`` callable. The engine is always handed the time.
"""

import argparse
import csv
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from souqsort.display import DisplayRow, display_rows
from souqsort.loaders import DataFileError, load_catalogue, load_gcc_config
from souqsort.models import MarketConfig
from souqsort.pipeline import LocalisationError, find_market, localise_catalogue

MAX_DUTY_ADJUST_POINTS = 20
DEFAULT_CATALOGUE = Path("data/raw/global_products.json")
DEFAULT_CONFIG = Path("data/raw/gcc_config.json")

# CSV column names, each with the cell it takes from a row.
_CSV_COLUMNS: tuple[tuple[str, Callable[[DisplayRow], str]], ...] = (
    ("sku", lambda row: row.sku),
    ("name_en", lambda row: row.name_en),
    ("currency", lambda row: row.currency),
    ("shelf_price", lambda row: row.shelf_price),
    ("margin_percent", lambda row: row.margin_percent),
    ("delivery_date", lambda row: row.delivery_date),
    ("flags", lambda row: ";".join(row.flags)),
)


# A date, then T or a space, then a time with at least hours and minutes, then an optional
# offset. datetime.fromisoformat() alone is too loose: it takes a bare date as midnight, and
# any character as the separator, so "2026-10-15+03:00" would be read as 03:00.
_DATE_AND_TIME = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})?", re.ASCII
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


# --- argument parsing ---------------------------------------------------------------------


def _percentage_points(text: str) -> int:
    """Whole percentage points from 0 to 20; converted to a fraction where it is used."""
    if not (text.isascii() and text.isdigit() and int(text) <= MAX_DUTY_ADJUST_POINTS):
        raise argparse.ArgumentTypeError(
            f"must be a whole number of percentage points from 0 to {MAX_DUTY_ADJUST_POINTS}, "
            f"got {text!r}"
        )
    return int(text)


def _iso_datetime(text: str) -> datetime:
    problem = argparse.ArgumentTypeError(
        f"must be a date and time such as 2026-10-15T20:59Z or 2026-10-15T23:59+03:00, got {text!r}"
    )
    if not _DATE_AND_TIME.fullmatch(text):
        raise problem
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise problem from None


def _build_parser() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    """The top-level parser and the ``price`` parser, which reports that command's errors."""
    parser = argparse.ArgumentParser(
        prog="python -m souqsort",
        description="SouqSort: GCC localisation and pricing engine.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    price = commands.add_parser(
        "price",
        help="price the catalogue for a market",
        description="Print shelf prices, margins and delivery dates for one market.",
    )
    price.add_argument(
        "--market", required=True, metavar="CODE", help="market code from the config, e.g. KSA"
    )
    price.add_argument(
        "--duty-adjust",
        type=_percentage_points,
        default=0,
        metavar="POINTS",
        help=(
            "percentage points added to every duty rate, a whole number from 0 to "
            f"{MAX_DUTY_ADJUST_POINTS} (default: 0)"
        ),
    )
    price.add_argument(
        "--ordered-at",
        type=_iso_datetime,
        metavar="ISO",
        help=(
            "order date and time, e.g. 2026-10-15T20:59Z or 2026-10-15T23:59+03:00; without an "
            "offset it is read as local time in the market's timezone (default: now)"
        ),
    )
    price.add_argument(
        "--csv",
        dest="csv_path",
        type=Path,
        metavar="PATH",
        help="also write the rows to a CSV file, creating its folder if needed",
    )
    price.add_argument(
        "--catalogue",
        type=Path,
        default=DEFAULT_CATALOGUE,
        metavar="PATH",
        help=f"catalogue JSON file (default: {DEFAULT_CATALOGUE.as_posix()})",
    )
    price.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        metavar="PATH",
        help=f"market config JSON file (default: {DEFAULT_CONFIG.as_posix()})",
    )
    return parser, price


def _same_file(path: Path, other: Path) -> bool:
    try:
        return path.samefile(other)
    except OSError:  # one of them does not exist, so they cannot be the same file
        return False


def _in_market_time(ordered_at: datetime, market: MarketConfig) -> datetime:
    """An order time given without an offset is on the market's own clock."""
    if ordered_at.utcoffset() is None:
        return ordered_at.replace(tzinfo=ZoneInfo(market.calendar.timezone))
    return ordered_at


# --- output -------------------------------------------------------------------------------


@dataclass(frozen=True)
class _TableColumn:
    header: str
    cell: Callable[[DisplayRow], str]
    right_aligned: bool = False


def _summary_line(market: MarketConfig, ordered_at_local: datetime, duty_points: int) -> str:
    return (
        f"Market: {market.code} ({market.name})   "
        f"Ordered at: {ordered_at_local:%Y-%m-%d %H:%M} {market.calendar.timezone}   "
        f"Duty adjustment: +{duty_points} pp"
    )


def _table_lines(rows: Sequence[DisplayRow], currency_code: str) -> list[str]:
    columns = (
        _TableColumn("SKU", lambda row: row.sku),
        _TableColumn("Name", lambda row: row.name_en),
        _TableColumn(f"Shelf price ({currency_code})", lambda row: row.shelf_price, True),
        _TableColumn("Margin %", lambda row: f"{row.margin_percent}%", True),
        _TableColumn("Delivery", lambda row: row.delivery_date),
        _TableColumn("Flags", lambda row: ",".join(row.flags) or "-"),
    )
    body = [[column.cell(row) for column in columns] for row in rows]
    widths = [
        max([len(column.header), *(len(cells[position]) for cells in body)])
        for position, column in enumerate(columns)
    ]

    def line(cells: Sequence[str]) -> str:
        aligned = (
            cell.rjust(width) if column.right_aligned else cell.ljust(width)
            for cell, width, column in zip(cells, widths, columns, strict=True)
        )
        return "  ".join(aligned).rstrip()

    return [
        line([column.header for column in columns]),
        line(["-" * width for width in widths]),
        *(line(cells) for cells in body),
    ]


def _write_csv(path: Path, rows: Sequence[DisplayRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" leaves line endings to the csv module; otherwise Windows writes \r\r\n.
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([name for name, _ in _CSV_COLUMNS])
        writer.writerows([cell(row) for _, cell in _CSV_COLUMNS] for row in rows)


def _print(text: str = "") -> None:
    """Print to stdout, with ``?`` for any character its encoding cannot represent.

    Piped or redirected output on Windows is in the ANSI code page, where a name outside it
    would otherwise stop the run with a ``UnicodeEncodeError``.
    """
    encoding = sys.stdout.encoding or "utf-8"
    print(text.encode(encoding, errors="replace").decode(encoding))


def _fail(message: str) -> int:
    print(f"souqsort: error: {message}", file=sys.stderr)
    return 1


# --- entry point --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None, *, now: Callable[[], datetime] = _utc_now) -> int:
    """Run the CLI and return its exit code.

    ``now`` supplies the order time when ``--ordered-at`` is not given, and is not called
    otherwise. Usage errors, including an unknown market, exit with code 2 through argparse.
    A data file that cannot be read, a catalogue that cannot be localised or a CSV that cannot
    be written returns 1 with a message. Any other exception is a bug and is left to raise.
    """
    parser, price_parser = _build_parser()
    args = parser.parse_args(argv)
    duty_points: int = args.duty_adjust
    csv_path: Path | None = args.csv_path

    if csv_path is not None:
        for option, source in (("--catalogue", args.catalogue), ("--config", args.config)):
            if _same_file(csv_path, source):
                price_parser.error(
                    f"argument --csv: {csv_path} is the {option} file and would be overwritten"
                )

    try:
        config = load_gcc_config(args.config)
        catalogue = load_catalogue(args.catalogue)
    except DataFileError as exc:
        return _fail(str(exc))
    except OSError as exc:
        return _fail(f"cannot read data file: {exc}")

    try:
        market = find_market(config, args.market)
    except LocalisationError as exc:
        price_parser.error(f"argument --market: {exc}")

    ordered_at = now() if args.ordered_at is None else _in_market_time(args.ordered_at, market)

    try:
        items = localise_catalogue(
            catalogue.products,
            config,
            market.code,
            ordered_at,
            Decimal(duty_points) / 100,  # whole points to a fraction, at the boundary
        )
        rows = display_rows(items)
    except LocalisationError as exc:
        return _fail(str(exc))

    # The delivery estimate has already made this conversion, so it cannot be out of range.
    ordered_at_local = ordered_at.astimezone(ZoneInfo(market.calendar.timezone))

    _print(_summary_line(market, ordered_at_local, duty_points))
    _print()
    _print("\n".join(_table_lines(rows, market.currency.code)))

    if csv_path is not None:
        try:
            _write_csv(csv_path, rows)
        except OSError as exc:
            return _fail(f"cannot write {csv_path}: {exc.strerror or exc}")
        _print()
        _print(f"Wrote {len(rows)} rows to {csv_path}")

    return 0
