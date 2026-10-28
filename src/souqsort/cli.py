"""Command-line interface: the ``price``, ``order`` and ``report`` commands.

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
from pathlib import Path

from souqsort.compliance import ExcludedProduct
from souqsort.display import (
    DisplayRow,
    OrderRow,
    display_rows,
    duty_text,
    order_rows,
    parcel_fee_note,
    parcel_note,
)
from souqsort.loaders import DataFileError, load_catalogue, load_gcc_config, load_sample_orders
from souqsort.logistics.calendar import in_market_time, to_market_time
from souqsort.models import (
    SHIPPING_MODELS,
    Catalogue,
    GccConfig,
    MarketConfig,
    OrderLine,
    SampleOrder,
    SampleOrders,
    ShippingModel,
)
from souqsort.orders import find_sample_order, quote_order_both_ways
from souqsort.pipeline import (
    MAX_DUTY_ADJUST_POINTS,
    LocalisationError,
    duty_adjustment_from_points,
    find_market,
    localise_and_summarise,
)
from souqsort.report import build_report, render_report

DEFAULT_CATALOGUE = Path("data/raw/global_products.json")
DEFAULT_CONFIG = Path("data/raw/gcc_config.json")
DEFAULT_ORDERS = Path("data/raw/sample_orders.json")
# A string, not a Path, so the path is printed as given on every OS.
DEFAULT_REPORT = "outputs/GCC_EXPANSION_REPORT.md"

# CSV column names, each with the cell it takes from a row.
_CSV_COLUMNS: tuple[tuple[str, Callable[[DisplayRow], str]], ...] = (
    ("sku", lambda row: row.sku),
    ("name_en", lambda row: row.name_en),
    ("currency", lambda row: row.currency),
    ("shelf_price", lambda row: row.shelf_price),
    ("margin_percent", lambda row: row.margin_percent),
    ("duty_percent", lambda row: row.duty_percent),
    ("duty_waived", lambda row: "true" if row.duty_waived else "false"),
    ("delivery_date", lambda row: row.delivery_date),
    ("flags", lambda row: ";".join(row.flags)),
)

# A spreadsheet runs a cell that starts with one of these as a formula (issue #2).
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
# fullmatch, not $: in Python, $ also matches before a trailing newline. ASCII keeps \d to 0-9.
_PLAIN_NUMBER = re.compile(r"-?\d+(\.\d+)?", re.ASCII)

# An order's --item: a SKU with no colon or whitespace (Unicode's too, such as a no-break space),
# then optionally a colon and a quantity of one or two ASCII digits.
_ORDER_ITEM = re.compile(r"([^:\s]+)(:([0-9]{1,2}))?")
_MAX_QUANTITY = 99


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


def _order_item(text: str) -> OrderLine:
    """An ``--item``: ``SKU`` for one, or ``SKU:QTY`` with a quantity from 1 to 99."""
    match = _ORDER_ITEM.fullmatch(text)
    quantity = 1 if match is None or match[3] is None else int(match[3])
    if match is None or not 1 <= quantity <= _MAX_QUANTITY:
        raise argparse.ArgumentTypeError(
            "must be a SKU, or a SKU and a quantity from 1 to "
            f"{_MAX_QUANTITY} such as ELEC-HP-001:2, got {text!r}"
        )
    return OrderLine(sku=match[1], quantity=quantity)


def _iso_instant(text: str) -> datetime:
    """An ``--ordered-at`` for the report, which must say its offset: it covers every market."""
    moment = _iso_datetime(text)
    if moment.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "the report covers every market, so give a UTC offset, e.g. 2026-10-15T09:00Z"
        )
    return moment


def _add_data_file_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--catalogue",
        type=Path,
        default=DEFAULT_CATALOGUE,
        metavar="PATH",
        help=f"catalogue JSON file (default: {DEFAULT_CATALOGUE.as_posix()})",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        metavar="PATH",
        help=f"market config JSON file (default: {DEFAULT_CONFIG.as_posix()})",
    )


def _add_market_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--market", required=True, metavar="CODE", help="market code from the config, e.g. KSA"
    )


def _add_duty_adjust_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--duty-adjust",
        type=_percentage_points,
        default=0,
        metavar="POINTS",
        help=(
            "percentage points added to every duty rate, a whole number from 0 to "
            f"{MAX_DUTY_ADJUST_POINTS} (default: 0)"
        ),
    )


def _add_local_ordered_at_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ordered-at",
        type=_iso_datetime,
        metavar="ISO",
        help=(
            "order date and time, e.g. 2026-10-15T20:59Z or 2026-10-15T23:59+03:00; without an "
            "offset it is read as local time in the market's timezone (default: now)"
        ),
    )


def _build_parser() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    """The top-level parser, then each command's parser by name.

    Each command's parser reports that command's errors.
    """
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
    _add_market_option(price)
    price.add_argument(
        "--shipping",
        choices=SHIPPING_MODELS,
        default="consolidated",
        help=(
            "shipping model: consolidated (one commercial import, no de minimis) or parcel "
            "(each order cleared on its own, with its own freight rate, transit time and "
            "customs fee; duty-free under the market's de minimis threshold) "
            "(default: %(default)s)"
        ),
    )
    _add_duty_adjust_option(price)
    _add_local_ordered_at_option(price)
    price.add_argument(
        "--csv",
        dest="csv_path",
        type=Path,
        metavar="PATH",
        help="also write the rows to a CSV file, creating its folder if needed",
    )
    _add_data_file_options(price)

    order = commands.add_parser(
        "order",
        help="price an order of several items in a market",
        description=(
            "Price one order in one market as a consolidated import and as a direct parcel, "
            "side by side."
        ),
    )
    _add_market_option(order)
    lines = order.add_mutually_exclusive_group(required=True)
    lines.add_argument(
        "--sample", metavar="ID", help="the id of an order in the sample orders file"
    )
    lines.add_argument(
        "--item",
        dest="items",
        type=_order_item,
        action="append",
        metavar="SKU[:QTY]",
        help=(
            f"a product and its quantity from 1 to {_MAX_QUANTITY} (default 1), e.g. "
            "ELEC-HP-001:2; repeat it for each product"
        ),
    )
    _add_duty_adjust_option(order)
    _add_local_ordered_at_option(order)
    _add_data_file_options(order)
    order.add_argument(
        "--orders",
        type=Path,
        default=DEFAULT_ORDERS,
        metavar="PATH",
        help=f"sample orders JSON file, read for --sample (default: {DEFAULT_ORDERS.as_posix()})",
    )

    report = commands.add_parser(
        "report",
        help="write the GCC expansion report",
        description=(
            "Write the expansion report: every market in the config for one order, "
            "side by side, as Markdown."
        ),
    )
    report.add_argument(
        "--ordered-at",
        type=_iso_instant,
        metavar="ISO",
        help="order date and time with a UTC offset, e.g. 2026-10-15T09:00Z (default: now)",
    )
    report.add_argument(
        "--out",
        default=DEFAULT_REPORT,
        metavar="PATH",
        help=f"Markdown file to write, creating its folder if needed (default: {DEFAULT_REPORT})",
    )
    _add_data_file_options(report)
    return parser, {"price": price, "order": order, "report": report}


def _same_file(path: Path, other: Path) -> bool:
    try:
        return path.samefile(other)
    except OSError:  # one of them does not exist, so they cannot be the same file
        return False


def _refuse_input_files(
    parser: argparse.ArgumentParser, option: str, path: Path, args: argparse.Namespace
) -> None:
    """Exit with a usage error if ``path`` is the catalogue or the config file."""
    for source_option, source in (("--catalogue", args.catalogue), ("--config", args.config)):
        if _same_file(path, source):
            parser.error(
                f"argument {option}: {path} is the {source_option} file and would be overwritten"
            )


# --- output -------------------------------------------------------------------------------


@dataclass(frozen=True)
class _TableColumn[R]:
    header: str
    cell: Callable[[R], str]
    right_aligned: bool = False


def _scenario_line(market: MarketConfig, ordered_at_local: datetime, duty_points: int) -> str:
    return (
        f"Market: {market.code} ({market.name})   "
        f"Ordered at: {ordered_at_local:%Y-%m-%d %H:%M} {market.calendar.timezone}   "
        f"Duty adjustment: +{duty_points} pp"
    )


def _summary_line(
    market: MarketConfig, ordered_at_local: datetime, duty_points: int, shipping: ShippingModel
) -> str:
    return f"{_scenario_line(market, ordered_at_local, duty_points)}   Shipping: {shipping}"


def _price_table(rows: Sequence[DisplayRow], currency_code: str) -> list[str]:
    columns: tuple[_TableColumn[DisplayRow], ...] = (
        _TableColumn("SKU", lambda row: row.sku),
        _TableColumn("Name", lambda row: row.name_en),
        _TableColumn(f"Shelf price ({currency_code})", lambda row: row.shelf_price, True),
        _TableColumn("Margin %", lambda row: f"{row.margin_percent}%", True),
        _TableColumn("Duty", duty_text, True),
        _TableColumn("Delivery", lambda row: row.delivery_date),
        _TableColumn("Flags", lambda row: ",".join(row.flags) or "-"),
    )
    return _table_lines(columns, rows)


def _order_table(rows: Sequence[OrderRow], currency_code: str) -> list[str]:
    columns: tuple[_TableColumn[OrderRow], ...] = (
        _TableColumn("SKU", lambda row: row.label),
        _TableColumn("Name", lambda row: row.name),
        _TableColumn("Qty", lambda row: row.quantity, True),
        _TableColumn(f"Consolidated ({currency_code})", lambda row: row.consolidated, True),
        _TableColumn(f"Direct parcel ({currency_code})", lambda row: row.parcel, True),
    )
    return _table_lines(columns, rows)


def _not_sold_table(excluded: Sequence[ExcludedProduct]) -> list[str]:
    columns: tuple[_TableColumn[ExcludedProduct], ...] = (
        _TableColumn("SKU", lambda item: item.sku),
        _TableColumn("Name", lambda item: item.name_en),
        _TableColumn("Reasons", lambda item: ",".join(item.reasons)),
    )
    return _table_lines(columns, excluded)


def _table_lines[R](columns: Sequence[_TableColumn[R]], rows: Sequence[R]) -> list[str]:
    """A header, a rule and one line per row, with columns two spaces apart."""
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


def _csv_cell(text: str) -> str:
    """``text`` with a leading ``'`` if a spreadsheet would run it as a formula.

    A plain decimal number, such as a negative margin ``-12.3``, is kept as it is.
    """
    if text.startswith(_FORMULA_STARTS) and not _PLAIN_NUMBER.fullmatch(text):
        return f"'{text}"
    return text


def _write_csv(path: Path, rows: Sequence[DisplayRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" leaves line endings to the csv module; otherwise Windows writes \r\r\n.
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([name for name, _ in _CSV_COLUMNS])
        writer.writerows([_csv_cell(cell(row)) for _, cell in _CSV_COLUMNS] for row in rows)


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


def _load_data(args: argparse.Namespace) -> tuple[GccConfig, Catalogue] | str:
    """The config and the catalogue, or the message to fail with."""
    try:
        return load_gcc_config(args.config), load_catalogue(args.catalogue)
    except DataFileError as exc:
        return str(exc)
    except OSError as exc:
        return f"cannot read data file: {exc}"


def _load_sample_orders(path: Path) -> SampleOrders | str:
    """The sample orders, or the message to fail with."""
    try:
        return load_sample_orders(path)
    except DataFileError as exc:
        return str(exc)
    except OSError as exc:
        return f"cannot read data file: {exc}"


def _print_not_sold(market: MarketConfig, excluded: Sequence[ExcludedProduct]) -> None:
    """A blank line and the products the market does not sell, if there are any."""
    if excluded:
        _print()
        _print(f"Not sold in {market.code} ({len(excluded)}):")
        _print("\n".join(_not_sold_table(excluded)))


# --- entry point --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None, *, now: Callable[[], datetime] = _utc_now) -> int:
    """Run the CLI and return its exit code.

    ``now`` supplies the order time when ``--ordered-at`` is not given, and is not called
    otherwise. Usage errors, including an unknown market, exit with code 2 through argparse.
    A data file that cannot be read, a catalogue that cannot be localised, or a CSV or report
    that cannot be written returns 1 with a message. Any other exception is a bug and is left
    to raise.
    """
    parser, commands = _build_parser()
    args = parser.parse_args(argv)
    command_parser = commands[args.command]
    if args.command == "report":
        return _report(args, command_parser, now)
    if args.command == "order":
        return _order(args, command_parser, now)
    return _price(args, command_parser, now)


def _price(
    args: argparse.Namespace, price_parser: argparse.ArgumentParser, now: Callable[[], datetime]
) -> int:
    duty_points: int = args.duty_adjust
    shipping: ShippingModel = args.shipping
    csv_path: Path | None = args.csv_path

    if csv_path is not None:
        _refuse_input_files(price_parser, "--csv", csv_path, args)

    data = _load_data(args)
    if isinstance(data, str):
        return _fail(data)
    config, catalogue = data

    try:
        market = find_market(config, args.market)
    except LocalisationError as exc:
        price_parser.error(f"argument --market: {exc}")

    ordered_at = now() if args.ordered_at is None else in_market_time(args.ordered_at, market)

    try:
        localised = localise_and_summarise(
            catalogue.products,
            config,
            market.code,
            ordered_at,
            duty_adjustment_from_points(duty_points),  # to a fraction, at the boundary
            shipping,
        )
        rows = display_rows(localised.items)
    except LocalisationError as exc:
        return _fail(str(exc))

    # The delivery estimate has already made this conversion, so it cannot be out of range.
    ordered_at_local = to_market_time(ordered_at, market)

    _print(_summary_line(market, ordered_at_local, duty_points, shipping))
    _print()
    _print("\n".join(_price_table(rows, market.currency.code)))

    fee_note = parcel_fee_note(market, shipping)
    if fee_note is not None:
        _print()
        _print(fee_note)

    _print_not_sold(market, localised.excluded)

    if csv_path is not None:
        try:
            _write_csv(csv_path, rows)
        except OSError as exc:
            return _fail(f"cannot write {csv_path}: {exc.strerror or exc}")
        _print()
        _print(f"Wrote {len(rows)} rows to {csv_path}")

    return 0


def _order_lines(
    args: argparse.Namespace,
    order_parser: argparse.ArgumentParser,
    catalogue: Catalogue,
    sample_orders: SampleOrders | None,
) -> tuple[Sequence[OrderLine], SampleOrder | None]:
    """The order's lines, and the sample order they come from, if any.

    Exits with a usage error for an unknown sample order, or for a SKU that is not in the
    catalogue or is listed twice.
    """
    if sample_orders is not None:
        try:
            sample = find_sample_order(sample_orders, args.sample)
        except LocalisationError as exc:
            order_parser.error(f"argument --sample: {exc}")
        return sample.lines, sample

    items: list[OrderLine] = args.items
    in_catalogue = {product.sku for product in catalogue.products}
    for item in items:
        if item.sku not in in_catalogue:
            order_parser.error(f"argument --item: {item.sku} is not in the catalogue")
    seen: set[str] = set()
    for item in items:
        if item.sku in seen:
            order_parser.error(f"argument --item: {item.sku} is listed twice")
        seen.add(item.sku)
    return items, None


def _order(
    args: argparse.Namespace, order_parser: argparse.ArgumentParser, now: Callable[[], datetime]
) -> int:
    duty_points: int = args.duty_adjust

    data = _load_data(args)
    if isinstance(data, str):
        return _fail(data)
    config, catalogue = data
    sample_orders = None
    if args.sample is not None:  # an order of --item lines never reads the orders file
        loaded = _load_sample_orders(args.orders)
        if isinstance(loaded, str):
            return _fail(loaded)
        sample_orders = loaded

    try:
        market = find_market(config, args.market)
    except LocalisationError as exc:
        order_parser.error(f"argument --market: {exc}")

    lines, sample = _order_lines(args, order_parser, catalogue, sample_orders)
    ordered_at = now() if args.ordered_at is None else in_market_time(args.ordered_at, market)

    try:
        both = quote_order_both_ways(
            lines,
            catalogue,
            config,
            market.code,
            ordered_at,
            duty_adjustment_from_points(duty_points),  # to a fraction, at the boundary
        )
        rows = order_rows(both.consolidated, both.parcel)
        note = parcel_note(market, both.parcel)
    except LocalisationError as exc:
        return _fail(str(exc))

    # The delivery estimate has already made this conversion, so it cannot be out of range.
    _print(_scenario_line(market, to_market_time(ordered_at, market), duty_points))
    if sample is not None:
        _print(f"Order: {sample.name}")
    _print()
    if both.consolidated.lines:
        _print("\n".join(_order_table(rows, market.currency.code)))
        _print()
        _print(note)
    else:
        _print(f"{market.code} sells nothing in this order.")
    _print_not_sold(market, both.consolidated.not_sold)
    return 0


def _report(
    args: argparse.Namespace, report_parser: argparse.ArgumentParser, now: Callable[[], datetime]
) -> int:
    out_text: str = args.out
    out = Path(out_text)
    _refuse_input_files(report_parser, "--out", out, args)

    data = _load_data(args)
    if isinstance(data, str):
        return _fail(data)
    config, catalogue = data

    ordered_at = now() if args.ordered_at is None else args.ordered_at
    try:
        text = render_report(build_report(catalogue, config, ordered_at))
    except LocalisationError as exc:
        return _fail(str(exc))

    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(text.encode("utf-8"))  # bytes, so Windows does not write \r\n
    except OSError as exc:
        return _fail(f"cannot write {out_text}: {exc.strerror or exc}")

    _print(f"Wrote the expansion report to {out_text}")
    return 0
