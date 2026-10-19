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
from streamlit.testing.v1 import AppTest

from helpers import FOR_SALE_COUNTS, decimal_places
from souqsort.display import display_summary, excluded_grid_rows, grid_rows
from souqsort.loaders import load_gcc_config
from souqsort.models import Catalogue, GccConfig
from souqsort.pipeline import (
    MAX_DUTY_ADJUST_POINTS,
    duty_adjustment_from_points,
    localise_and_summarise,
)

APP_PATH = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"

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
    "Direct parcel: each order is cleared on its own; under the market's threshold it pays no "
    "duty, but parcel freight costs more per kg."
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


def _grid(at: AppTest) -> pd.DataFrame:
    """The data sent to the main grid: the first table on the page."""
    assert not at.exception, at.exception
    assert not at.error, [error.value for error in at.error]
    frame: pd.DataFrame = at.dataframe[0].value
    return frame


def _not_sold(at: AppTest) -> pd.DataFrame | None:
    """The table of products the market does not sell, or None when it is not shown."""
    assert not at.exception, at.exception
    assert len(at.dataframe) <= 2
    if len(at.dataframe) < 2:
        return None
    frame: pd.DataFrame = at.dataframe[1].value
    return frame


def _column(at: AppTest, column: str) -> dict[str, Any]:
    """One grid column, keyed by SKU."""
    frame = _grid(at)
    return dict(zip(frame[SKU], frame[column], strict=True))


def _metrics(at: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in at.metric}


def _captions(at: AppTest) -> str:
    return "\n".join(caption.value for caption in at.caption)


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


def test_sidebar_holds_the_six_controls(app: AppTest) -> None:
    sidebar = app.sidebar

    assert [widget.key for widget in sidebar.selectbox] == ["market"]
    assert [widget.key for widget in sidebar.radio] == ["shipping"]
    assert [widget.key for widget in sidebar.slider] == ["duty_points"]
    assert [widget.key for widget in sidebar.date_input] == ["order_date"]
    assert [widget.key for widget in sidebar.time_input] == ["order_time"]
    assert [widget.key for widget in sidebar.text_input] == ["search"]


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
    assert duty[LICENCE] == "waived"  # SPEC §7.9.2: waived although its rate is already 0
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


def test_switching_markets_keeps_the_shipping_model(app: AppTest) -> None:
    _ship(app, "parcel")

    _select_market(app, "UAE")

    assert app.radio(key="shipping").value == "parcel"
    assert _column(app, "Shelf price (AED)")[HEADPHONES] == Decimal("589.99")  # SPEC §7.9.2


def test_shipping_model_does_not_change_delivery_dates(app: AppTest) -> None:
    before = _column(app, DELIVERY)

    _ship(app, "parcel")

    assert _column(app, DELIVERY) == before


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
    grid = app.dataframe[0]
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
    grid = app.dataframe[0]
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
    assert [info.value for info in app.info] == ["No product matches the search."]


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
    grid = app.dataframe[0]
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
    assert "Not sold in KSA" in [subheader.value for subheader in app.subheader]


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
    assert "Not sold in UAE" in [subheader.value for subheader in app.subheader]


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
    assert [info.value for info in at.info] == ["No product in the catalogue can be sold in KSA."]
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
    assert not [s.value for s in at.subheader if s.value.startswith("Not sold")]


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
    assert [info.value for info in at.info] == ["The catalogue has no products."]
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
    (error,) = at.error
    assert "too large to display" in error.value
    assert len(at.dataframe) == 0


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
