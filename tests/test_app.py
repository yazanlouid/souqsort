"""M6: the Streamlit dashboard, run headlessly with Streamlit's AppTest (SPEC §10).

AppTest runs the script and exposes its widgets and elements; it does not render a browser.
These tests therefore check what the app sends to the grid (values and their types), not how
the browser draws or sorts it.
"""

import ast
import json
from dataclasses import astuple
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import streamlit
from streamlit.proto.Metric_pb2 import Metric as MetricProto
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Block, Metric

from helpers import FOR_SALE_COUNTS, REPORT_ORDERED_AT, decimal_places
from souqsort.display import display_summary, excluded_grid_rows, grid_rows
from souqsort.loaders import load_gcc_config, load_sample_orders
from souqsort.models import Catalogue, GccConfig, SampleOrders
from souqsort.pipeline import (
    MAX_DUTY_ADJUST_POINTS,
    LocalisationError,
    duty_adjustment_from_points,
    localise_and_summarise,
)
from souqsort.report import build_report, render_report

APP_PATH = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"
TABS = ["Products", "Order"]
SAMPLE_REPORT = Path(__file__).resolve().parents[1] / "docs" / "GCC_EXPANSION_REPORT.md"

HEADPHONES = "ELEC-HP-001"
CHARGER = "ELEC-CHG-002"
BAG = "FASH-BAG-014"
ESPRESSO = "HOME-ESP-031"
LIP_BALM = "BEAU-LIP-040"
SERUM = "BEAU-SRM-041"
LICENCE = "DIGI-LIC-050"
TEA = "GROC-TEA-060"
VANILLA = "GROC-VAN-061"
GUMMY_BEARS = "GROC-GUM-062"

# Grid columns.
SKU, NAME, PRICE, MARGIN, DUTY, DELIVERY, FLAGS = COLUMNS = (
    "SKU",
    "Name",
    "Shelf price (SAR)",
    "Margin %",
    "Duty",
    "Delivery",
    "Flags",
)

# Metric labels.
AVERAGE_MARGIN = "Average margin"
FLAGGED = "Flagged products"
PRICE_CHANGE = "Average price change vs 0 pp"
NOT_SOLD = "Not sold in KSA"

# The table of products the market does not sell, under the grid.
NOT_SOLD_COLUMNS = ("SKU", "Name", "Reason")
KSA_FOR_SALE = FOR_SALE_COUNTS["KSA"]

SCOPE_NOTE = "All 11 products for sale in KSA; search filters the table only"

SHIPPING_HELP = (
    "Consolidated: orders travel as one commercial import, so de minimis never applies. "
    "Direct parcel: each order is cleared on its own, with its own freight rate, transit time "
    "and customs fee; under the market's threshold it pays no duty."
)
KSA_FEE_NOTE = "Each parcel order also pays a customs fee of 15.00 SAR at checkout."

# The report download button in the sidebar (SPEC §9.6).
REPORT_LABEL = "Download expansion report"
REPORT_HELP = (
    "Every market and both shipping models for the order date and time above, at today's duty "
    "rates. The duty slider, shipping model and search don't change it."
)

# The moment the dashboard is opened: Sun 10:00 in Riyadh, before the cutoff (SPEC §8.1 row 1).
OPENED_AT = datetime(2026, 10, 11, 7, 0, tzinfo=UTC)
THU_EVENING = datetime(2026, 10, 15, 20, 59, tzinfo=UTC)  # Thu 23:59 in Riyadh


# --- helpers and fixtures -----------------------------------------------------------------


def _new_app() -> AppTest:
    # The first run imports Streamlit and pandas, which can take longer than the default 3 s.
    return AppTest.from_file(str(APP_PATH), default_timeout=30)


@pytest.fixture
def app() -> AppTest:
    """The dashboard after its first run, opened at a fixed moment instead of the real clock."""
    at = _new_app()
    at.session_state["opened_at"] = OPENED_AT
    return at.run()


def _products(at: AppTest) -> Block:
    """The "Products" tab: everything the page showed before it had tabs."""
    assert not at.exception, at.exception
    assert [tab.label for tab in at.tabs] == TABS
    return at.tabs[0]


def _grid(at: AppTest) -> pd.DataFrame:
    """The data sent to the main grid: the first table in the "Products" tab.

    The page has no error, except perhaps one in the "Order" tab, which its own tests check.
    """
    errors = [error.value for error in at.error]
    assert not at.exception, at.exception
    assert len(at.tabs) == len(TABS), errors
    assert errors == [error.value for error in at.tabs[1].error], errors
    frame: pd.DataFrame = _products(at).dataframe[0].value
    return frame


def _not_sold(at: AppTest) -> pd.DataFrame | None:
    """The table of products the market does not sell, or None when it is not shown."""
    tables = _products(at).dataframe
    assert len(tables) <= 2
    if len(tables) < 2:
        return None
    frame: pd.DataFrame = tables[1].value
    return frame


def _column(at: AppTest, column: str) -> dict[str, Any]:
    """One grid column, keyed by SKU."""
    frame = _grid(at)
    return dict(zip(frame[SKU], frame[column], strict=True))


def _metrics(at: AppTest) -> dict[str, str]:
    """The "Products" tab's metrics, by label."""
    return {metric.label: metric.value for metric in _products(at).metric}


def _captions(at: AppTest) -> str:
    """The "Products" tab's captions, one per line."""
    return "\n".join(caption.value for caption in _products(at).caption)


def _order(at: AppTest, day: date, clock: time) -> AppTest:
    """Set the order date and time pickers, then rerun."""
    at.date_input(key="order_date").set_value(day)
    at.time_input(key="order_time").set_value(clock)
    return at.run()


def _search(at: AppTest, text: str) -> AppTest:
    return at.text_input(key="search").input(text).run()


def _select_market(at: AppTest, code: str) -> AppTest:
    return at.selectbox(key="market").select(code).run()


def _ship(at: AppTest, shipping: str) -> AppTest:
    return at.radio(key="shipping").set_value(shipping).run()


# --- first load ---------------------------------------------------------------------------


def test_app_starts_and_shows_every_product(app: AppTest, catalogue: Catalogue) -> None:
    frame = _grid(app)

    assert list(frame.columns) == list(COLUMNS)
    not_sold = (VANILLA, GUMMY_BEARS)
    assert list(frame[SKU]) == [p.sku for p in catalogue.products if p.sku not in not_sold]
    assert len(frame) == KSA_FOR_SALE


def test_headline_metrics_on_first_load(app: AppTest) -> None:
    assert _metrics(app) == {
        AVERAGE_MARGIN: "64.6%",  # over the 11 products for sale
        FLAGGED: "2",
        PRICE_CHANGE: "0.0%",
        NOT_SOLD: "2",
    }


def test_grid_shows_what_the_engine_returns(
    app: AppTest, catalogue: Catalogue, config: GccConfig
) -> None:
    expected = grid_rows(localise_and_summarise(catalogue.products, config, "KSA", OPENED_AT).items)

    shown = list(_grid(app).itertuples(index=False, name=None))

    assert shown == [astuple(row) for row in expected]


def test_worked_example_rows(app: AppTest) -> None:
    rows = {row[0]: row for row in _grid(app).itertuples(index=False, name=None)}

    assert rows[HEADPHONES] == (
        "ELEC-HP-001",
        "Wireless Noise-Cancelling Headphones",
        Decimal("686.95"),
        Decimal("58.7"),
        "5.0%",
        "2026-10-18",
        "",
    )
    assert rows[BAG] == (
        "FASH-BAG-014",
        "Leather Crossbody Bag",
        Decimal("594.95"),
        Decimal("64.6"),
        "12.0%",
        "2026-10-18",
        "No Arabic name",
    )


# --- sidebar ------------------------------------------------------------------------------


def test_sidebar_holds_the_seven_controls(app: AppTest) -> None:
    sidebar = app.sidebar

    assert [widget.key for widget in sidebar.selectbox] == ["market"]
    assert [widget.key for widget in sidebar.radio] == ["shipping"]
    assert [widget.key for widget in sidebar.slider] == ["duty_points"]
    assert [widget.key for widget in sidebar.date_input] == ["order_date"]
    assert [widget.key for widget in sidebar.time_input] == ["order_time"]
    assert [widget.key for widget in sidebar.text_input] == ["search"]
    assert [widget.key for widget in sidebar.download_button] == ["report_download"]


def test_market_selector_is_filled_from_the_config(app: AppTest, config: GccConfig) -> None:
    selector = app.selectbox(key="market")

    assert selector.value == "KSA"
    assert len(selector.options) == len(config.markets) == 3
    for option, (code, market) in zip(selector.options, config.markets.items(), strict=True):
        assert code in option
        assert market.name in option  # the name comes from the config too


def test_duty_slider_is_whole_points_from_0_to_20(app: AppTest) -> None:
    slider = app.slider(key="duty_points")

    assert (slider.min, slider.max, slider.step) == (0, MAX_DUTY_ADJUST_POINTS, 1)
    assert slider.value == 0
    assert type(slider.value) is int


def test_time_picker_steps_by_one_minute(app: AppTest) -> None:
    # Fine enough to pick 13:59 and 14:00, either side of the cutoff.
    assert app.time_input(key="order_time").step == 60


def test_search_box_starts_empty(app: AppTest) -> None:
    assert app.text_input(key="search").value == ""


# --- the shipping model (SPEC §7.7 and §9.2, M10) -----------------------------------------


def test_shipping_radio_offers_the_two_models_and_starts_consolidated(app: AppTest) -> None:
    radio = app.radio(key="shipping")

    assert radio.label == "Shipping model"
    assert list(radio.options) == ["Consolidated import", "Direct parcel"]
    assert radio.value == "consolidated"
    assert radio.help == SHIPPING_HELP


def test_shipping_radio_is_right_under_the_market_selector() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    widgets = [
        node.func.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"selectbox", "radio", "slider", "date_input", "time_input"}
    ]
    assert widgets[:2] == ["selectbox", "radio"]


def test_direct_parcel_switches_prices(app: AppTest) -> None:
    before = _column(app, PRICE)

    _ship(app, "parcel")
    after = _column(app, PRICE)

    assert before[HEADPHONES] == Decimal("686.95")
    assert after[HEADPHONES] == Decimal("660.95")  # SPEC §7.8 E
    assert after[ESPRESSO] == Decimal("4344.95")  # SPEC §7.8 G
    assert after[TEA] == Decimal("37.95")  # dearer: parcel freight costs more


def test_duty_column_shows_waived_for_a_waived_parcel(app: AppTest) -> None:
    assert _column(app, DUTY)[HEADPHONES] == "5.0%"

    _ship(app, "parcel")
    duty = _column(app, DUTY)

    assert duty[HEADPHONES] == "waived"
    assert duty[LICENCE] == "0.0%"  # SPEC §7.9.2: it weighs nothing, so it never travels
    assert duty[ESPRESSO] == "5.0%"  # above the threshold


@pytest.mark.parametrize("points", [0, 3])
def test_parcel_grid_and_metrics_follow_the_engine(
    app: AppTest, catalogue: Catalogue, config: GccConfig, points: int
) -> None:
    expected = localise_and_summarise(
        catalogue.products,
        config,
        "KSA",
        OPENED_AT,
        duty_adjustment_from_points(points),
        "parcel",
    )
    summary = display_summary(expected.summary)

    _ship(app, "parcel")
    app.slider(key="duty_points").set_value(points).run()

    shown = list(_grid(app).itertuples(index=False, name=None))
    assert shown == [astuple(row) for row in grid_rows(expected.items)]
    assert _metrics(app) == {
        AVERAGE_MARGIN: summary.average_margin,
        FLAGGED: summary.flagged_products,
        PRICE_CHANGE: summary.average_price_change,
        NOT_SOLD: "2",
    }


def test_price_change_compares_with_0_points_in_the_same_shipping_model(app: AppTest) -> None:
    _ship(app, "parcel")

    # Parcel prices differ from consolidated ones, but at 0 pp nothing has changed.
    assert _metrics(app)[PRICE_CHANGE] == "0.0%"


def test_caption_names_the_shipping_model(app: AppTest) -> None:
    assert "Shipping: Consolidated import" in _captions(app)

    _ship(app, "parcel")

    assert "Shipping: Direct parcel" in _captions(app)
    assert "Consolidated import" not in _captions(app)


def test_the_fee_caption_shows_for_ksa_parcels_only(app: AppTest) -> None:
    assert KSA_FEE_NOTE not in _captions(app)  # consolidated

    _ship(app, "parcel")
    assert KSA_FEE_NOTE in _captions(app)

    _select_market(app, "UAE")
    assert "customs fee" not in _captions(app)

    _select_market(app, "KWT")
    assert "customs fee" not in _captions(app)


def test_switching_markets_keeps_the_shipping_model(app: AppTest) -> None:
    _ship(app, "parcel")

    _select_market(app, "UAE")

    assert app.radio(key="shipping").value == "parcel"
    assert _column(app, "Shelf price (AED)")[HEADPHONES] == Decimal("589.99")  # SPEC §7.9.2


def test_delivery_column_follows_the_shipping_model(app: AppTest) -> None:
    _order(app, date(2026, 10, 15), time(12, 0))  # Thu 12:00 in Riyadh
    assert set(_column(app, DELIVERY).values()) == {"2026-10-22"}

    _ship(app, "parcel")

    assert set(_column(app, DELIVERY).values()) == {"2026-10-21"}  # SPEC §8.3


# --- the duty slider changes prices -------------------------------------------------------


def test_moving_the_duty_slider_changes_prices(app: AppTest) -> None:
    before = _column(app, PRICE)

    app.slider(key="duty_points").set_value(3).run()
    after = _column(app, PRICE)

    assert before[HEADPHONES] == Decimal("686.95")
    assert after[HEADPHONES] == Decimal("705.95")  # duty 5% + 3 points
    assert after[LICENCE] == Decimal("350.95")  # 0% override + 3 points, from 340.95
    assert after[LIP_BALM] == before[LIP_BALM] == Decimal("16.95")  # absorbed by the charm ending
    assert all(after[sku] >= price for sku, price in before.items())


@pytest.mark.parametrize("points", [1, 3, 20])
def test_grid_and_metrics_follow_the_engine_at_any_slider_value(
    app: AppTest, catalogue: Catalogue, config: GccConfig, points: int
) -> None:
    adjusted = localise_and_summarise(
        catalogue.products, config, "KSA", OPENED_AT, duty_adjustment_from_points(points)
    )
    summary = display_summary(adjusted.summary)

    app.slider(key="duty_points").set_value(points).run()

    shown = list(_grid(app).itertuples(index=False, name=None))
    assert shown == [astuple(row) for row in grid_rows(adjusted.items)]
    assert _metrics(app) == {
        AVERAGE_MARGIN: summary.average_margin,
        FLAGGED: summary.flagged_products,
        PRICE_CHANGE: summary.average_price_change,
        NOT_SOLD: str(len(adjusted.excluded)),
    }


def test_price_change_metric_reacts_to_the_slider(app: AppTest) -> None:
    assert _metrics(app)[PRICE_CHANGE] == "0.0%"

    app.slider(key="duty_points").set_value(3).run()
    assert _metrics(app)[PRICE_CHANGE] == "+2.3%"
    assert _metrics(app)[AVERAGE_MARGIN] == "64.5%"  # barely moves: duty is passed through

    app.slider(key="duty_points").set_value(20).run()
    assert _metrics(app)[PRICE_CHANGE] == "+18.6%"

    app.slider(key="duty_points").set_value(0).run()
    assert _metrics(app)[PRICE_CHANGE] == "0.0%"


def test_duty_slider_does_not_change_delivery_dates(app: AppTest) -> None:
    before = _column(app, DELIVERY)

    app.slider(key="duty_points").set_value(20).run()

    assert _column(app, DELIVERY) == before


def test_caption_names_the_duty_adjustment(app: AppTest) -> None:
    assert "+0 pp" in _captions(app)

    app.slider(key="duty_points").set_value(3).run()

    assert "+3 pp" in _captions(app)


# --- price and margin are numbers, so the grid sorts them by value ------------------------


def test_price_and_margin_reach_the_grid_as_decimals(app: AppTest) -> None:
    frame = _grid(app)

    for price, margin in zip(frame[PRICE], frame[MARGIN], strict=True):
        assert type(price) is Decimal  # not text, and never a float
        assert type(margin) is Decimal
        assert decimal_places(price) == 2  # SAR minor units
        assert decimal_places(margin) == 1


def test_price_column_sorts_by_value_not_as_text(app: AppTest) -> None:
    frame = _grid(app)

    by_price = list(frame.sort_values(PRICE)[SKU])

    assert by_price.index(LIP_BALM) < by_price.index(SERUM)  # 16.95 before 111.95
    assert by_price[0] == LIP_BALM
    assert by_price[-1] == ESPRESSO
    assert sorted(map(str, frame[PRICE]))[0] == "111.95"  # where text order would start


def test_price_and_margin_columns_have_a_fixed_number_of_decimals(app: AppTest) -> None:
    # The column settings travel to the browser as JSON next to the data.
    grid = _products(app).dataframe[0]
    settings = grid.proto.columns

    assert "%.2f" in settings  # shelf price: the currency's minor units
    assert "%.1f%%" in settings  # margin


# --- flags --------------------------------------------------------------------------------


def test_flags_are_shown_as_labels(app: AppTest) -> None:
    flags = _column(app, FLAGS)

    assert flags[BAG] == flags[TEA] == "No Arabic name"
    assert set(flags.values()) == {"", "No Arabic name"}


def test_flags_column_has_a_fixed_width(app: AppTest) -> None:
    # Left to size itself, a column can end up narrower than its text. AppTest cannot measure
    # pixels, so this checks only that a fixed width was asked for.
    grid = _products(app).dataframe[0]
    settings = json.loads(grid.proto.columns)

    assert settings[FLAGS]["width"] in {"medium", "large"}  # 200 px or 400 px


def test_grid_is_as_tall_as_its_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    # Left at its default height, the grid scrolls after about ten rows and hides the rest.
    # AppTest does not keep an element's height, so this records what the app asks for.
    asked: list[dict[str, Any]] = []
    show = streamlit.dataframe

    def recording(*args: Any, **kwargs: Any) -> Any:
        asked.append(kwargs)
        return show(*args, **kwargs)

    monkeypatch.setattr(streamlit, "dataframe", recording)
    at = _new_app()
    at.session_state["opened_at"] = OPENED_AT
    at.run()

    assert len(_grid(at)) == KSA_FOR_SALE  # more rows than the default height shows
    assert asked[0].get("height") == "content"


# --- search filters rows ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("crossbody", [BAG]),  # part of an English name
        ("ELEC-", [HEADPHONES, CHARGER]),  # part of a SKU
        ("elec-", [HEADPHONES, CHARGER]),  # any case
        ("bag", [BAG, TEA]),  # "FASH-BAG-014" and "English Breakfast Tea, 80 bags"
    ],
)
def test_search_filters_rows(app: AppTest, text: str, expected: list[str]) -> None:
    _search(app, text)

    assert list(_grid(app)[SKU]) == expected


def test_clearing_the_search_brings_every_row_back(app: AppTest) -> None:
    _search(app, "crossbody")
    assert len(_grid(app)) == 1

    _search(app, "")

    assert len(_grid(app)) == KSA_FOR_SALE


def test_search_with_no_match_shows_an_empty_grid_not_an_error(app: AppTest) -> None:
    _search(app, "no such product")

    frame = _grid(app)
    assert len(frame) == 0
    assert list(frame.columns) == list(COLUMNS)
    assert [info.value for info in _products(app).info] == ["No product matches the search."]


def test_search_and_slider_work_together(app: AppTest) -> None:
    app.slider(key="duty_points").set_value(3)
    _search(app, "elec-")

    assert _column(app, PRICE) == {HEADPHONES: Decimal("705.95"), CHARGER: Decimal("190.95")}


def test_metrics_cover_the_whole_market_whatever_the_search(app: AppTest) -> None:
    app.slider(key="duty_points").set_value(3).run()
    whole_market = _metrics(app)

    for text in ("crossbody", "elec-", "no such product"):
        _search(app, text)
        assert _metrics(app) == whole_market, text

    assert whole_market[FLAGGED] == "2"  # "elec-" alone has no flagged product


def test_page_says_that_the_metrics_cover_the_whole_market(app: AppTest) -> None:
    assert SCOPE_NOTE in _captions(app)

    _search(app, "crossbody")

    assert SCOPE_NOTE in _captions(app)  # still all of them, with one row showing


# --- order date and time ------------------------------------------------------------------


def test_thursday_evening_order_gives_sunday_based_delivery_dates(app: AppTest) -> None:
    # SPEC §8.1 row 4: Thu 23:59 in Riyadh misses the cutoff, Fri-Sat is the weekend, so the
    # order is dispatched on Sun 18 and delivered five business days later, on Sun 25.
    _order(app, date(2026, 10, 15), time(23, 59))

    deliveries = set(_grid(app)[DELIVERY])
    assert deliveries == {"2026-10-25"}
    assert date(2026, 10, 25).strftime("%A") == "Sunday"
    assert "Thu 2026-10-15 23:59 Asia/Riyadh" in _captions(app)


@pytest.mark.parametrize(
    ("day", "clock", "delivery"),
    [
        (date(2026, 10, 11), time(10, 0), "2026-10-18"),  # SPEC §8.1 row 1
        (date(2026, 10, 15), time(13, 30), "2026-10-22"),  # row 3
        (date(2026, 10, 15), time(13, 59), "2026-10-22"),  # the last minute before the cutoff
        (date(2026, 10, 15), time(14, 0), "2026-10-25"),  # exactly at the cutoff misses it
        (date(2026, 10, 16), time(1, 30), "2026-10-25"),  # row 5: Friday, the weekend
    ],
)
def test_order_pickers_are_in_market_local_time(
    app: AppTest, day: date, clock: time, delivery: str
) -> None:
    # Read as UTC, 13:30 and 13:59 would be after the 14:00 cutoff in Riyadh.
    _order(app, day, clock)

    assert set(_grid(app)[DELIVERY]) == {delivery}


def test_order_time_matches_the_engine_for_the_same_moment(
    app: AppTest, catalogue: Catalogue, config: GccConfig
) -> None:
    expected = grid_rows(
        localise_and_summarise(catalogue.products, config, "KSA", THU_EVENING).items
    )

    _order(app, date(2026, 10, 15), time(23, 59))

    shown = list(_grid(app).itertuples(index=False, name=None))
    assert shown == [astuple(row) for row in expected]


def test_order_time_does_not_change_prices(app: AppTest) -> None:
    before = _column(app, PRICE)

    _order(app, date(2026, 10, 15), time(23, 59))

    assert _column(app, PRICE) == before


def test_order_pickers_default_to_the_opening_moment_in_market_local_time(app: AppTest) -> None:
    # 07:00 UTC is 10:00 on the same day in Riyadh.
    assert app.date_input(key="order_date").value == date(2026, 10, 11)
    assert app.time_input(key="order_time").value == time(10, 0)
    assert set(_grid(app)[DELIVERY]) == {"2026-10-18"}
    assert "Sun 2026-10-11 10:00 Asia/Riyadh" in _captions(app)


def test_order_date_default_is_the_market_date_not_the_utc_date() -> None:
    at = _new_app()
    at.session_state["opened_at"] = datetime(2026, 10, 15, 22, 30, tzinfo=UTC)  # Fri 01:30 there

    at.run()

    assert at.date_input(key="order_date").value == date(2026, 10, 16)
    assert at.time_input(key="order_time").value == time(1, 30)


def test_opening_the_app_reads_the_clock_once_per_session() -> None:
    before = datetime.now(UTC)
    at = _new_app().run()
    after = datetime.now(UTC)

    opened_at = at.session_state["opened_at"]
    assert not at.exception
    assert before <= opened_at <= after  # timezone-aware, or this comparison would raise
    assert len(_grid(at)) == KSA_FOR_SALE

    at.slider(key="duty_points").set_value(3).run()

    assert at.session_state["opened_at"] == opened_at  # a rerun does not move the pickers


def test_order_time_default_is_to_the_minute() -> None:
    at = _new_app()
    at.session_state["opened_at"] = datetime(2026, 10, 11, 7, 0, 45, 500000, tzinfo=UTC)

    at.run()

    assert at.time_input(key="order_time").value == time(10, 0)
    assert "Sun 2026-10-11 10:00 Asia/Riyadh" in _captions(at)


def test_order_pickers_start_on_the_selected_market_clock() -> None:
    at = _new_app()
    at.session_state["opened_at"] = OPENED_AT
    at.session_state["market"] = "UAE"  # a session that starts with another market selected

    at.run()

    assert at.time_input(key="order_time").value == time(11, 0)  # 07:00 UTC in Dubai
    assert "Sun 2026-10-11 11:00 Asia/Dubai" in _captions(at)


# --- switching markets (SPEC §10.2, issue #3) ---------------------------------------------


def test_switching_markets_keeps_the_picked_date_and_time(app: AppTest) -> None:
    # The pickers hold a local date and time, read on the selected market's clock: 13:30 stays
    # 13:30 and becomes 13:30 in the new market, as the CLI reads --ordered-at without an offset.
    _order(app, date(2026, 10, 15), time(13, 30))
    assert set(_grid(app)[DELIVERY]) == {"2026-10-22"}

    _select_market(app, "KWT")

    assert app.date_input(key="order_date").value == date(2026, 10, 15)
    assert app.time_input(key="order_time").value == time(13, 30)
    assert "Thu 2026-10-15 13:30 Asia/Kuwait" in _captions(app)
    assert set(_grid(app)[DELIVERY]) == {"2026-10-25"}  # after Kuwait's 13:00 cutoff

    _select_market(app, "UAE")

    assert app.time_input(key="order_time").value == time(13, 30)
    assert "Thu 2026-10-15 13:30 Asia/Dubai" in _captions(app)
    assert set(_grid(app)[DELIVERY]) == {"2026-10-21"}  # the UAE's shorter last mile


def test_time_picker_help_names_the_selected_market_and_says_switching_keeps_it(
    app: AppTest,
) -> None:
    help_text = app.time_input(key="order_time").help
    assert help_text == (
        "Local time in the selected market (Asia/Riyadh). "
        "Switching markets keeps the date and time."
    )

    _select_market(app, "UAE")

    assert "(Asia/Dubai)" in app.time_input(key="order_time").help


@pytest.mark.parametrize(
    ("market", "currency", "headphones", "places"),
    [
        ("UAE", "AED", Decimal("612.99"), 2),  # SPEC §7.8, worked example C
        ("KWT", "KWD", Decimal("48.950"), 3),  # worked example D
    ],
)
def test_switching_markets_changes_the_currency_header_and_prices(
    app: AppTest, market: str, currency: str, headphones: Decimal, places: int
) -> None:
    _select_market(app, market)

    price_column = f"Shelf price ({currency})"
    frame = _grid(app)
    assert list(frame.columns) == [SKU, NAME, price_column, MARGIN, DUTY, DELIVERY, FLAGS]
    assert _column(app, price_column)[HEADPHONES] == headphones
    assert all(decimal_places(price) == places for price in frame[price_column])
    grid = _products(app).dataframe[0]
    assert f"%.{places}f" in grid.proto.columns
    assert f"All {FOR_SALE_COUNTS[market]} products for sale in {market}" in _captions(app)


# --- not sold (SPEC §7.6, §9.2; M9) -------------------------------------------------------


def test_products_ksa_does_not_sell_are_listed_under_the_grid(app: AppTest) -> None:
    table = _not_sold(app)

    assert table is not None
    assert list(table.columns) == list(NOT_SOLD_COLUMNS)
    assert list(table.itertuples(index=False, name=None)) == [
        (VANILLA, "Pure Vanilla Extract", "Contains alcohol"),
        (GUMMY_BEARS, "Gummy Bears (pork gelatine)", "Contains pork"),
    ]
    assert "Not sold in KSA" in [subheader.value for subheader in _products(app).subheader]


def test_not_sold_table_shows_what_the_engine_returns(
    app: AppTest, catalogue: Catalogue, config: GccConfig
) -> None:
    excluded = localise_and_summarise(catalogue.products, config, "KSA", OPENED_AT).excluded
    table = _not_sold(app)

    assert table is not None
    shown = list(table.itertuples(index=False, name=None))
    assert shown == [astuple(row) for row in excluded_grid_rows(excluded)]


def test_switching_to_the_uae_shows_one_product_not_sold(app: AppTest) -> None:
    _select_market(app, "UAE")

    assert _metrics(app)["Not sold in UAE"] == "1"
    table = _not_sold(app)
    assert table is not None
    assert list(table[SKU]) == [GUMMY_BEARS]
    assert "Not sold in UAE" in [subheader.value for subheader in _products(app).subheader]


def test_search_filters_the_grid_but_not_the_not_sold_table(app: AppTest) -> None:
    _search(app, "headphones")

    assert list(_grid(app)[SKU]) == [HEADPHONES]
    table = _not_sold(app)
    assert table is not None
    assert list(table[SKU]) == [VANILLA, GUMMY_BEARS]
    assert _metrics(app)[NOT_SOLD] == "2"


def test_a_catalogue_of_only_banned_products_says_none_can_be_sold(
    monkeypatch: pytest.MonkeyPatch, catalogue: Catalogue
) -> None:
    banned = [p for p in catalogue.products if p.sku in (VANILLA, GUMMY_BEARS)]
    only_banned = catalogue.model_copy(update={"products": banned})

    at = _run_with(monkeypatch, load_catalogue=lambda path: only_banned)

    assert len(_grid(at)) == 0
    assert [info.value for info in _products(at).info] == [
        "No product in the catalogue can be sold in KSA."
    ]
    assert _metrics(at)[NOT_SOLD] == "2"
    table = _not_sold(at)
    assert table is not None
    assert list(table[SKU]) == [VANILLA, GUMMY_BEARS]


def test_a_market_that_bans_nothing_shows_no_not_sold_table(
    monkeypatch: pytest.MonkeyPatch, zero_vat_config: GccConfig
) -> None:
    at = _run_with(monkeypatch, load_gcc_config=lambda path: zero_vat_config)

    assert len(_grid(at)) == 13  # every sample product
    assert _metrics(at)["Not sold in TEST-KWD"] == "0"
    assert _not_sold(at) is None
    assert not [s.value for s in _products(at).subheader if s.value.startswith("Not sold")]


# --- the expansion report (SPEC §9.6, M14) ------------------------------------------------


@pytest.fixture
def offers(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """What the app passes to ``st.download_button`` on each run, latest last.

    AppTest keeps the button's label and help, but not its file name, type or data.
    """
    recorded: list[dict[str, Any]] = []
    offer = streamlit.download_button

    def recording(*args: Any, **kwargs: Any) -> Any:
        recorded.append(kwargs)
        return offer(*args, **kwargs)

    monkeypatch.setattr(streamlit, "download_button", recording)
    return recorded


@pytest.fixture
def report_app(offers: list[dict[str, Any]]) -> AppTest:
    """The dashboard after its first run, with what its download button offers recorded."""
    at = _new_app()
    at.session_state["opened_at"] = OPENED_AT
    return at.run()


def _offered(offers: list[dict[str, Any]]) -> bytes:
    """The file the download button offers after the latest run."""
    data = offers[-1]["data"]
    assert type(data) is bytes  # encoded by the app, as the CLI writes the file
    return data


def _report_bytes(catalogue: Catalogue, config: GccConfig, ordered_at: datetime) -> bytes:
    return render_report(build_report(catalogue, config, ordered_at)).encode("utf-8")


def test_sidebar_has_the_report_download_button(
    report_app: AppTest, offers: list[dict[str, Any]]
) -> None:
    (button,) = report_app.sidebar.download_button

    assert button.label == REPORT_LABEL
    assert button.help == REPORT_HELP
    assert offers[-1]["file_name"] == "GCC_EXPANSION_REPORT.md"
    assert offers[-1]["mime"] == "text/markdown"


def _sidebar_calls() -> list[str]:
    """Every ``st.<name>(...)`` call in the app's ``with st.sidebar:`` block, in source order."""
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    (sidebar,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.With) and ast.unparse(node.items[0].context_expr) == "st.sidebar"
    ]
    # Sorted by line: ast.walk goes breadth first, and the button is nested in a try statement.
    return [
        name
        for _, name in sorted(
            (node.lineno, node.func.attr)
            for node in ast.walk(sidebar)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "st"
        )
    ]


def test_report_button_is_right_under_the_search_box() -> None:
    calls = _sidebar_calls()

    # After the search box, only the button, or the error that takes its place, of any kind of
    # element: a widget added below the button would fail here.
    after_search = calls[calls.index("text_input") + 1 :]
    assert after_search == ["error", "download_button"]


def test_thursday_noon_in_ksa_offers_the_sample_report(
    report_app: AppTest, offers: list[dict[str, Any]], catalogue: Catalogue, config: GccConfig
) -> None:
    # 12:00 in Riyadh is 09:00 UTC, the sample report's order (SPEC §9.5).
    _order(report_app, date(2026, 10, 15), time(12, 0))

    offered = _offered(offers)
    assert offered == _report_bytes(catalogue, config, REPORT_ORDERED_AT)
    assert offered == SAMPLE_REPORT.read_bytes()


def test_slider_shipping_model_and_search_do_not_change_the_report(
    report_app: AppTest, offers: list[dict[str, Any]]
) -> None:
    _order(report_app, date(2026, 10, 15), time(12, 0))
    sample = _offered(offers)

    report_app.slider(key="duty_points").set_value(20).run()
    assert _offered(offers) == sample

    _ship(report_app, "parcel")
    assert _offered(offers) == sample

    _search(report_app, "no such product")
    assert _offered(offers) == sample


def test_switching_to_the_uae_offers_the_report_for_the_same_reading_on_its_clock(
    report_app: AppTest, offers: list[dict[str, Any]], catalogue: Catalogue, config: GccConfig
) -> None:
    _order(report_app, date(2026, 10, 15), time(12, 0))

    _select_market(report_app, "UAE")

    # The pickers keep 12:00, now read in Dubai: 08:00 UTC (issue #3).
    offered = _offered(offers)
    assert offered == _report_bytes(catalogue, config, datetime(2026, 10, 15, 8, 0, tzinfo=UTC))
    assert offered != SAMPLE_REPORT.read_bytes()


def test_report_button_is_there_when_the_search_matches_nothing(
    report_app: AppTest, offers: list[dict[str, Any]], catalogue: Catalogue, config: GccConfig
) -> None:
    _search(report_app, "no such product")

    assert len(_grid(report_app)) == 0
    (button,) = report_app.sidebar.download_button
    assert button.label == REPORT_LABEL
    assert _offered(offers) == _report_bytes(catalogue, config, OPENED_AT)


def test_a_report_that_cannot_be_built_is_an_error_where_the_button_would_be(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing(*args: Any, **kwargs: Any) -> Any:
        raise LocalisationError("KWT: something cannot be priced")

    monkeypatch.setattr("souqsort.report.build_report", failing)
    at = _new_app()
    at.session_state["opened_at"] = OPENED_AT
    at.run()

    assert not at.exception, at.exception
    assert [error.value for error in at.sidebar.error] == [
        "Cannot build the expansion report: KWT: something cannot be priced"
    ]
    assert len(at.sidebar.download_button) == 0
    # The rest of the page keeps working.
    assert len(at.main.error) == 0
    assert len(_products(at).dataframe[0].value) == KSA_FOR_SALE
    assert _metrics(at)[AVERAGE_MARGIN] == "64.6%"
    assert len(_products(at).dataframe) == 2  # the not-sold table too


# --- problems are shown as a message, not a traceback -------------------------------------


def _run_with(monkeypatch: pytest.MonkeyPatch, **loaders: Any) -> AppTest:
    """Run the app with one or both of its loaders replaced.

    The app has no option for other data files, so this is how a test hands it a different
    catalogue or config.
    """
    for name, loader in loaders.items():
        monkeypatch.setattr(f"souqsort.loaders.{name}", loader)
    at = _new_app()
    at.session_state["opened_at"] = OPENED_AT
    return at.run()


def test_empty_catalogue_says_so_instead_of_blaming_the_search(
    monkeypatch: pytest.MonkeyPatch, catalogue: Catalogue
) -> None:
    empty = catalogue.model_copy(update={"products": []})

    at = _run_with(monkeypatch, load_catalogue=lambda path: empty)

    assert len(_grid(at)) == 0
    assert [info.value for info in _products(at).info] == ["The catalogue has no products."]
    assert _metrics(at) == {AVERAGE_MARGIN: "-", FLAGGED: "0", PRICE_CHANGE: "-", NOT_SOLD: "0"}
    assert "All 0 products for sale in KSA" in _captions(at)
    assert _not_sold(at) is None


def test_config_with_no_markets_is_reported_as_a_bad_data_file(
    monkeypatch: pytest.MonkeyPatch, raw_config: dict[str, Any], tmp_path: Path
) -> None:
    raw_config["markets"] = {}
    no_markets = tmp_path / "no_markets.json"
    no_markets.write_text(json.dumps(raw_config), encoding="utf-8")

    at = _run_with(monkeypatch, load_gcc_config=lambda path: load_gcc_config(no_markets))

    assert not at.exception, at.exception
    (error,) = at.error
    assert "no_markets.json" in error.value
    assert "at least one market" in error.value
    assert len(at.dataframe) == 0  # nothing is drawn after the message


def test_margin_too_large_to_display_is_a_message(
    monkeypatch: pytest.MonkeyPatch, catalogue: Catalogue
) -> None:
    # A cost of 1E+30 USD still prices, but its margin is far beyond what one decimal can show.
    headphones, *others = catalogue.products
    absurd = headphones.model_copy(update={"unit_cost": Decimal("1E+30")})
    broken = catalogue.model_copy(update={"products": [absurd, *others]})

    at = _run_with(monkeypatch, load_catalogue=lambda path: broken)

    assert not at.exception, at.exception
    (error,) = at.main.error
    assert "too large to display" in error.value
    assert len(at.dataframe) == 0
    # The report cannot format that margin either, so the sidebar says so instead of a button.
    (report_error,) = at.sidebar.error
    assert report_error.value == (
        "Cannot build the expansion report: KSA: average margin is too large to display"
    )
    assert len(at.sidebar.download_button) == 0


# --- the "Order" tab (SPEC §10.5, M17) ----------------------------------------------------

ORDER_SCOPE = (
    "Both shipping models, with the market, duty adjustment and order time from the sidebar."
)
BUILD_YOUR_OWN = "Build your own"
CONSOLIDATED_METRIC = "Consolidated import"
PARCEL_METRIC = "Direct parcel"
ORDER_COLUMNS = ["SKU", "Name", "Qty", "Consolidated (SAR)", "Direct parcel (SAR)"]
THU_NOON = (date(2026, 10, 15), time(12, 0))  # the sample report's order in Riyadh


def _order_tab(at: AppTest) -> Block:
    assert not at.exception, at.exception
    assert [tab.label for tab in at.tabs] == TABS
    return at.tabs[1]


@pytest.fixture
def noon(app: AppTest) -> AppTest:
    """The dashboard with an order at Thu 2026-10-15 12:00, market time."""
    return _order(app, *THU_NOON)


def _pick_order(at: AppTest, order_id: str) -> AppTest:
    return at.selectbox(key="order").select(order_id).run()


def _build_your_own(at: AppTest, *skus: str) -> AppTest:
    picker = at.selectbox(key="order")
    picker.select_index(len(picker.options) - 1).run()
    return at.multiselect(key="order_products").set_value(list(skus)).run()


def _order_table(at: AppTest) -> dict[str, tuple[str, ...]]:
    """The order's rows keyed by their first cell, each the rest of its cells.

    The order grid is the tab's first dataframe; a "Not sold" table may follow it.
    """
    frame: pd.DataFrame = _order_tab(at).dataframe[0].value
    assert list(frame.columns)[:3] == ORDER_COLUMNS[:3]
    return {row[0]: tuple(row[1:]) for row in frame.itertuples(index=False, name=None)}


def _order_metrics(at: AppTest) -> dict[str, Metric]:
    return {metric.label: metric for metric in _order_tab(at).metric}


def _delta(metric: Metric) -> tuple[str, str, str]:
    """A metric's delta, with its colour and arrow as Streamlit draws them."""
    proto = metric.proto
    return (
        proto.delta,
        MetricProto.MetricColor.Name(proto.color),
        MetricProto.MetricDirection.Name(proto.direction),
    )


def _layout(at: AppTest) -> list[str]:
    """The kinds of the main area's top-level elements, in order."""
    return [getattr(node, "type", type(node).__name__) for node in at.main.children.values()]


def test_the_main_area_has_two_tabs(app: AppTest) -> None:
    assert [tab.label for tab in app.tabs] == TABS
    assert app.title[0].value == "SouqSort"


def test_order_tab_starts_with_the_sample_orders_then_build_your_own(
    app: AppTest, sample_orders: SampleOrders
) -> None:
    picker = _order_tab(app).selectbox[0]

    assert picker.label == "Order"
    assert picker.options == [order.name for order in sample_orders.orders] + [BUILD_YOUR_OWN]
    assert picker.value == sample_orders.orders[0].id
    assert _order_tab(app).caption[0].value == ORDER_SCOPE


def test_two_lip_balms_at_noon_in_ksa(noon: AppTest) -> None:
    metrics = _order_metrics(noon)

    assert metrics[CONSOLIDATED_METRIC].value == "33.90 SAR"
    assert metrics[PARCEL_METRIC].value == "46.90 SAR"
    assert _delta(metrics[PARCEL_METRIC]) == ("+38.3%", "RED", "UP")  # 46.90 / 33.90 - 1
    assert _delta(metrics[CONSOLIDATED_METRIC]) == ("", "GRAY", "NONE")
    rows = _order_table(noon)
    assert rows[LIP_BALM] == ("Lip Balm", "2", "33.90", "31.90")
    assert rows["Customs fee"] == ("", "", "-", "15.00")
    assert "Duty and VAT" not in rows
    assert rows["Total"] == ("", "", "33.90", "46.90")
    assert rows["Delivery"] == ("", "", "2026-10-22", "2026-10-21")
    assert _order_tab(noon).caption[1].value == (
        "Direct parcel: the order's CIF, 27.53 SAR, is below 1000.00 SAR, so de minimis applies."
    )


def test_headphones_and_a_bag_at_noon_in_ksa(noon: AppTest) -> None:
    at = _pick_order(noon, "headphones-and-bag")

    metrics = _order_metrics(at)
    assert metrics[CONSOLIDATED_METRIC].value == "1281.90 SAR"
    assert metrics[PARCEL_METRIC].value == "1321.47 SAR"
    assert _delta(metrics[PARCEL_METRIC]) == ("+3.1%", "RED", "UP")  # dearer is worse
    rows = _order_table(at)
    assert rows["Duty and VAT"] == ("", "", "-", "98.57")
    assert rows["Customs fee"] == ("", "", "-", "15.00")
    assert rows["Total"] == ("", "", "1281.90", "1321.47")


def test_headphones_and_a_bag_at_three_points(noon: AppTest) -> None:
    at = _pick_order(noon, "headphones-and-bag")
    at.slider(key="duty_points").set_value(3).run()

    rows = _order_table(at)
    assert rows["Duty and VAT"][-1] == "134.77"
    assert rows["Total"][-1] == "1357.67"
    assert _order_metrics(at)[PARCEL_METRIC].value == "1357.67 SAR"


def test_headphones_and_a_bag_in_the_uae(noon: AppTest) -> None:
    at = _select_market(_pick_order(noon, "headphones-and-bag"), "UAE")

    rows = _order_table(at)
    assert "Customs fee" not in rows
    assert rows["Duty and VAT"] == ("", "", "-", "53.73")
    frame: pd.DataFrame = _order_tab(at).dataframe[0].value
    assert list(frame.columns)[3:] == ["Consolidated (AED)", "Direct parcel (AED)"]
    assert "is not at or below 1000.00 AED" in _order_tab(at).caption[1].value


def test_an_order_that_costs_the_same_both_ways_shows_no_change(noon: AppTest) -> None:
    at = _select_market(noon, "UAE")  # two lip balms: 29.98 AED either way

    metrics = _order_metrics(at)
    assert metrics[CONSOLIDATED_METRIC].value == metrics[PARCEL_METRIC].value == "29.98 AED"
    assert _delta(metrics[PARCEL_METRIC]) == ("0.0%", "GRAY", "NONE")


def test_build_your_own_with_nothing_picked(noon: AppTest) -> None:
    at = _build_your_own(noon)
    tab = _order_tab(at)

    assert [info.value for info in tab.info] == ["Pick at least one product."]
    assert len(tab.metric) == 0
    assert len(tab.dataframe) == 0
    assert [caption.value for caption in tab.caption] == [ORDER_SCOPE]
    assert len(tab.number_input) == 0


def test_build_your_own_offers_every_product(noon: AppTest, catalogue: Catalogue) -> None:
    at = _build_your_own(noon)
    products = at.multiselect(key="order_products")

    assert products.label == "Products"
    assert products.options == [f"{p.sku} - {p.name.en}" for p in catalogue.products]


def test_build_your_own_asks_a_quantity_for_each_product(noon: AppTest) -> None:
    at = _build_your_own(noon, LIP_BALM, LICENCE)
    quantities = _order_tab(at).number_input

    assert [box.label for box in quantities] == [
        f"Quantity of {LIP_BALM}",
        f"Quantity of {LICENCE}",
    ]
    assert [box.value for box in quantities] == [1, 1]
    assert [(box.proto.min, box.proto.max) for box in quantities] == [(1, 99), (1, 99)]

    quantities[0].set_value(2).run()

    rows = _order_table(at)
    assert rows[LIP_BALM][:2] == ("Lip Balm", "2")
    assert rows["Total"][-1] == "387.85"


def test_a_long_order_shows_every_row(noon: AppTest, catalogue: Catalogue) -> None:
    # Left at its default height, the grid would scroll after about ten rows and hide Total
    # and Delivery (test_the_order_grid_is_as_tall_as_its_rows).
    skus = [p.sku for p in catalogue.products if p.sku not in (VANILLA, GUMMY_BEARS)][:8]

    at = _build_your_own(noon, *skus)

    assert list(_order_table(at)) == [
        *skus,
        "Items",
        "Customs fee",
        "Duty and VAT",
        "Total",
        "Delivery",
    ]


def test_the_order_grid_is_as_tall_as_its_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    # As test_grid_is_as_tall_as_its_rows: AppTest does not keep an element's height, so this
    # records what the app asks for.
    asked: list[dict[str, Any]] = []
    show = streamlit.dataframe

    def recording(data: Any = None, *args: Any, **kwargs: Any) -> Any:
        if "Qty" in getattr(data, "columns", ()):
            asked.append(kwargs)
        return show(data, *args, **kwargs)

    monkeypatch.setattr(streamlit, "dataframe", recording)
    at = _new_app()
    at.session_state["opened_at"] = OPENED_AT
    at.run()
    _pick_order(at, "headphones-and-bag")

    assert asked
    assert all(kwargs.get("height") == "content" for kwargs in asked)
    # The cells are text, so they would sit on the left; aligned right, they line up as in
    # the CLI. The column settings travel to the browser as JSON next to the data.
    settings = json.loads(_order_tab(at).dataframe[0].proto.columns)
    right = ORDER_COLUMNS[2:]  # Qty and the two money columns
    assert {column: settings[column].get("alignment") for column in right} == dict.fromkeys(
        right, "right"
    )
    assert not {"SKU", "Name"} & settings.keys()


def test_build_your_own_licence_alone_sends_no_parcel(noon: AppTest) -> None:
    at = _build_your_own(noon, LICENCE)

    assert "Customs fee" not in _order_table(at)
    assert _order_tab(at).caption[1].value == (
        "Direct parcel: nothing in the order travels, so no parcel is sent."
    )
    assert _delta(_order_metrics(at)[PARCEL_METRIC]) == ("0.0%", "GRAY", "NONE")


def test_build_your_own_lists_what_the_market_does_not_sell(noon: AppTest) -> None:
    at = _build_your_own(noon, VANILLA, TEA)
    tab = _order_tab(at)

    assert VANILLA not in _order_table(at)
    assert [subheader.value for subheader in tab.subheader] == ["Not sold in KSA"]
    not_sold: pd.DataFrame = tab.dataframe[1].value  # after the order grid
    assert list(not_sold.columns) == list(NOT_SOLD_COLUMNS)
    assert list(not_sold.itertuples(index=False, name=None)) == [
        (VANILLA, "Pure Vanilla Extract", "Contains alcohol")
    ]


def test_an_order_the_market_sells_nothing_of(noon: AppTest) -> None:
    at = _build_your_own(noon, GUMMY_BEARS)
    tab = _order_tab(at)

    metrics = _order_metrics(at)
    assert metrics[CONSOLIDATED_METRIC].value == metrics[PARCEL_METRIC].value == "-"
    assert _delta(metrics[PARCEL_METRIC]) == ("", "GRAY", "NONE")
    assert [info.value for info in tab.info] == ["KSA sells nothing in this order."]
    (not_sold,) = tab.dataframe  # the not-sold table only
    assert list(not_sold.value.columns) == list(NOT_SOLD_COLUMNS)
    assert [subheader.value for subheader in tab.subheader] == ["Not sold in KSA"]
    assert [caption.value for caption in tab.caption] == [ORDER_SCOPE]


def test_the_order_tab_ignores_the_radio_and_the_search(noon: AppTest) -> None:
    at = _pick_order(noon, "headphones-and-bag")
    layout, rows = _layout(at), _order_table(at)

    _ship(at, "parcel")
    assert _layout(at) == layout
    assert [tab.label for tab in at.tabs] == TABS
    assert _order_table(at) == rows

    _search(at, "no such product")
    assert _layout(at) == layout
    assert [tab.label for tab in at.tabs] == TABS
    assert _order_table(at) == rows
    assert at.selectbox(key="order").value == "headphones-and-bag"


def test_the_tabs_come_right_after_the_title(app: AppTest) -> None:
    # The browser keeps the selected tab across reruns as long as the tabs stay in the same
    # place, so nothing that comes and goes may be drawn above them.
    assert _layout(app)[:2] == ["title", "tab_container"]
    assert _layout(_ship(app, "parcel")) == _layout(app)
    assert _layout(_search(app, "zzz")) == _layout(app)


def test_a_sample_order_missing_from_the_catalogue_is_an_error_in_its_tab(
    monkeypatch: pytest.MonkeyPatch, catalogue: Catalogue
) -> None:
    no_lip_balm = catalogue.model_copy(
        update={"products": [p for p in catalogue.products if p.sku != LIP_BALM]}
    )

    at = _run_with(monkeypatch, load_catalogue=lambda path: no_lip_balm)

    assert [error.value for error in _order_tab(at).error] == [f"{LIP_BALM}: not in the catalogue"]
    assert len(_order_tab(at).metric) == 0
    assert len(_grid(at)) == KSA_FOR_SALE - 1  # "Products" keeps working


def _orders_file_problem(at: AppTest) -> str:
    """The "Order" tab's one error, after checking that nothing else in the tab is drawn and
    that "Products" and the report download keep working."""
    tab = _order_tab(at)
    (error,) = tab.error
    assert len(tab.selectbox) == len(tab.metric) == len(tab.dataframe) == len(tab.caption) == 0
    assert len(_grid(at)) == KSA_FOR_SALE
    assert _metrics(at)[AVERAGE_MARGIN] == "64.6%"
    assert [button.label for button in at.sidebar.download_button] == [REPORT_LABEL]
    value: str = error.value
    return value


def test_sample_orders_that_cannot_be_read_are_an_error_in_the_order_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(path: Path) -> Any:
        raise FileNotFoundError(2, "No such file or directory", str(path))

    at = _run_with(monkeypatch, load_sample_orders=missing)

    message = _orders_file_problem(at)
    assert message.startswith("Cannot read data file: ")
    assert "sample_orders.json" in message


def test_invalid_sample_orders_are_an_error_in_the_order_tab(
    monkeypatch: pytest.MonkeyPatch, raw_orders: dict[str, Any], tmp_path: Path
) -> None:
    raw_orders["orders"][0]["lines"][0]["quantity"] = 0
    bad = tmp_path / "bad_orders.json"
    bad.write_text(json.dumps(raw_orders), encoding="utf-8")

    at = _run_with(monkeypatch, load_sample_orders=lambda path: load_sample_orders(bad))

    message = _orders_file_problem(at)
    assert "bad_orders.json" in message
    assert "invalid data file" in message


# --- no business logic in the app ---------------------------------------------------------


def test_app_does_no_decimal_or_float_arithmetic_of_its_own() -> None:
    tree = ast.parse(APP_PATH.read_text("utf-8"))

    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "souqsort" in imported
    assert "decimal" not in imported  # prices and rates are worked out in src/
    assert not called & {"float", "round", "Decimal"}
