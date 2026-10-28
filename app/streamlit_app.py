"""Streamlit dashboard. Displays results from souqsort; holds no business logic."""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from souqsort.display import (
    SHIPPING_LABELS,
    ExcludedGridRow,
    display_summary,
    excluded_grid_rows,
    grid_rows,
    order_rows,
    order_totals,
    parcel_fee_note,
    parcel_note,
    search_products,
)
from souqsort.loaders import (
    DataFileError,
    load_catalogue,
    load_gcc_config,
    load_sample_orders,
)
from souqsort.logistics.calendar import in_market_time, to_market_time
from souqsort.models import OrderLine
from souqsort.orders import find_sample_order, quote_order_both_ways
from souqsort.pipeline import (
    MAX_DUTY_ADJUST_POINTS,
    LocalisationError,
    duty_adjustment_from_points,
    find_market,
    localise_and_summarise,
)
from souqsort.report import build_report, render_report

# Found from this file, so the app starts from any working directory.
DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

# The "Order" selectbox's last option. Order ids are lower case, so none can be this.
BUILD_YOUR_OWN = "Build your own"

st.set_page_config(page_title="SouqSort", layout="wide")

try:
    config = load_gcc_config(DATA_DIR / "gcc_config.json")
    catalogue = load_catalogue(DATA_DIR / "global_products.json")
    sample_orders = load_sample_orders(DATA_DIR / "sample_orders.json")
except DataFileError as exc:
    st.error(str(exc))
    st.stop()
except OSError as exc:
    st.error(f"Cannot read data file: {exc}")
    st.stop()

# The clock is read once per session: the pickers below start at the moment the dashboard
# was opened, and a rerun must not move them.
if "opened_at" not in st.session_state:
    st.session_state["opened_at"] = datetime.now(UTC)

# --- sidebar ------------------------------------------------------------------------------

with st.sidebar:
    st.header("Scenario")

    market_code = st.selectbox(
        "Market",
        options=list(config.markets),
        format_func=lambda code: f"{code} - {config.markets[code].name}",
        key="market",
    )
    market = find_market(config, market_code)
    timezone = market.calendar.timezone

    shipping = st.radio(
        "Shipping model",
        options=list(SHIPPING_LABELS),
        format_func=SHIPPING_LABELS.__getitem__,
        help=(
            "Consolidated: orders travel as one commercial import, so de minimis never applies. "
            "Direct parcel: each order is cleared on its own, with its own freight rate, transit "
            "time and customs fee; under the market's threshold it pays no duty."
        ),
        key="shipping",
    )

    # The pickers hold a local date and time, read on the selected market's clock, as the CLI
    # reads --ordered-at without an offset. They start once per session at the opening moment
    # on the selected market's clock, to the minute; switching markets keeps the date and time,
    # so the same reading is then read on the new market's clock.
    if "order_date" not in st.session_state:
        opened_local = to_market_time(st.session_state["opened_at"], market)
        st.session_state["order_date"] = opened_local.date()
        st.session_state["order_time"] = opened_local.time().replace(second=0, microsecond=0)

    duty_points = st.slider(
        "Duty adjustment",
        min_value=0,
        max_value=MAX_DUTY_ADJUST_POINTS,
        value=0,
        step=1,
        format="+%d pp",
        help="Percentage points added to every category's duty rate.",
        key="duty_points",
    )

    order_date = st.date_input("Order date", key="order_date")
    order_time = st.time_input(
        "Order time",
        step=60,
        help=(
            f"Local time in the selected market ({timezone}). "
            "Switching markets keeps the date and time."
        ),
        key="order_time",
    )

    query = st.text_input("Search", placeholder="SKU or English name", key="search")

    # The pickers give a date and a time with no offset: the same case as the CLI's --ordered-at.
    ordered_at = in_market_time(datetime.combine(order_date, order_time), market)

    # The report covers every market and both shipping models at today's duty rates, for the
    # order picked above, so the slider, the shipping model and the search never change it.
    try:
        report = render_report(build_report(catalogue, config, ordered_at))
    except LocalisationError as exc:
        st.error(f"Cannot build the expansion report: {exc}")
    else:
        st.download_button(
            "Download expansion report",
            data=report.encode("utf-8"),  # bytes, as the CLI writes them: \n on every OS
            file_name="GCC_EXPANSION_REPORT.md",
            mime="text/markdown",
            help=(
                "Every market and both shipping models for the order date and time above, at "
                "today's duty rates. The duty slider, shipping model and search don't change it."
            ),
            on_click="ignore",  # downloading changes nothing on the page, so no rerun
            key="report_download",
        )

# --- results ------------------------------------------------------------------------------

try:
    localised = localise_and_summarise(
        catalogue.products,
        config,
        market.code,
        ordered_at,
        duty_adjustment_from_points(duty_points),
        shipping,
    )
    summary = localised.summary
    headline = display_summary(summary)
    rows = grid_rows(search_products(localised.items, query))
    not_sold = excluded_grid_rows(localised.excluded)
    fee_note = parcel_fee_note(market, shipping)
except LocalisationError as exc:
    st.error(str(exc))
    st.stop()

# --- main area ----------------------------------------------------------------------------


def show_not_sold(code: str, rows: list[ExcludedGridRow]) -> None:
    """Products the market does not allow: reported with their reasons, never silently dropped."""
    if rows:
        st.subheader(f"Not sold in {code}")
        st.dataframe(
            pd.DataFrame(
                {
                    "SKU": [row.sku for row in rows],
                    "Name": [row.name_en for row in rows],
                    "Reason": [row.reasons for row in rows],
                }
            ),
            hide_index=True,
        )


st.title("SouqSort")

# Nothing that comes and goes is drawn above the tabs: the browser keeps the selected tab
# across reruns only while the tabs stay in the same place.
products_tab, order_tab = st.tabs(["Products", "Order"])

with products_tab:
    st.caption(
        f"Market: {market.code} ({market.name}) | "
        f"Ordered at: {ordered_at:%a %Y-%m-%d %H:%M} {timezone} | "
        f"Duty adjustment: +{duty_points} pp | "
        f"Shipping: {SHIPPING_LABELS[shipping]} | "
        "All market data is illustrative"
    )

    margin_metric, flagged_metric, change_metric, not_sold_metric = st.columns(4)
    margin_metric.metric("Average margin", headline.average_margin)
    flagged_metric.metric("Flagged products", headline.flagged_products)
    change_metric.metric("Average price change vs 0 pp", headline.average_price_change)
    not_sold_metric.metric(f"Not sold in {market.code}", str(len(localised.excluded)))
    st.caption(
        f"All {summary.product_count} products for sale in {market.code}; "
        "search filters the table only"
    )

    price_column = f"Shelf price ({market.currency.code})"
    margin_column = "Margin %"

    # Price and margin stay Decimal, so the grid sorts them by value and no float is made here.
    st.dataframe(
        pd.DataFrame(
            {
                "SKU": [row.sku for row in rows],
                "Name": [row.name_en for row in rows],
                price_column: [row.shelf_price for row in rows],
                margin_column: [row.margin_percent for row in rows],
                "Duty": [row.duty for row in rows],
                "Delivery": [row.delivery_date for row in rows],
                "Flags": [row.flags for row in rows],
            }
        ),
        hide_index=True,
        # As tall as its rows: the default height scrolls after about ten and hides the rest.
        height="content",
        column_config={
            price_column: st.column_config.NumberColumn(format=f"%.{market.currency.minor_units}f"),
            margin_column: st.column_config.NumberColumn(format="%.1f%%"),
            # A fixed width, so a flag's label is not cut short when the column sizes itself.
            "Flags": st.column_config.TextColumn(width="medium"),
        },
    )

    if fee_note is not None:
        st.caption(fee_note)

    if summary.product_count == 0 and not localised.excluded:
        st.info("The catalogue has no products.")
    elif summary.product_count == 0:
        st.info(f"No product in the catalogue can be sold in {market.code}.")
    elif not rows:
        st.info("No product matches the search.")

    show_not_sold(market.code, not_sold)

with order_tab:
    names = {order.id: order.name for order in sample_orders.orders}
    product_names = {product.sku: product.name.en for product in catalogue.products}
    order_id = st.selectbox(
        "Order",
        options=[*names, BUILD_YOUR_OWN],
        format_func=lambda choice: names.get(choice, choice),
        key="order",
    )
    st.caption(
        "Both shipping models, with the market, duty adjustment and order time from the sidebar."
    )

    if order_id == BUILD_YOUR_OWN:
        picked = st.multiselect(
            "Products",
            options=list(product_names),
            format_func=lambda sku: f"{sku} - {product_names[sku]}",
            key="order_products",
        )
        lines = [
            OrderLine(
                sku=sku,
                quantity=st.number_input(
                    f"Quantity of {sku}",
                    min_value=1,
                    max_value=99,
                    value=1,
                    step=1,
                    key=f"quantity_{sku}",
                ),
            )
            for sku in picked
        ]
    else:
        lines = list(find_sample_order(sample_orders, order_id).lines)

    if not lines:
        st.info("Pick at least one product.")
    else:
        try:
            both = quote_order_both_ways(
                lines,
                catalogue,
                config,
                market.code,
                ordered_at,
                duty_adjustment_from_points(duty_points),
            )
            totals = order_totals(both.consolidated, both.parcel)
            order_table = order_rows(both.consolidated, both.parcel)
            note = parcel_note(market, both.parcel)
            order_not_sold = excluded_grid_rows(both.consolidated.not_sold)
        except LocalisationError as exc:
            st.error(str(exc))
        else:
            consolidated_metric, parcel_metric = st.columns(2)
            consolidated_metric.metric(SHIPPING_LABELS["consolidated"], totals.consolidated)
            # Dearer is worse, so a rise is red. Streamlit draws every text delta but "0" as a
            # rise, so no change is grey, with no arrow.
            parcel_metric.metric(
                SHIPPING_LABELS["parcel"],
                totals.parcel,
                delta=totals.change,
                delta_color="off" if totals.unchanged else "inverse",
                delta_arrow="off" if totals.unchanged else "auto",
            )
            if both.consolidated.lines:
                currency = market.currency.code
                st.dataframe(
                    pd.DataFrame(
                        {
                            "SKU": [row.label for row in order_table],
                            "Name": [row.name for row in order_table],
                            "Qty": [row.quantity for row in order_table],
                            f"Consolidated ({currency})": [row.consolidated for row in order_table],
                            f"Direct parcel ({currency})": [row.parcel for row in order_table],
                        }
                    ),
                    hide_index=True,
                )
                st.caption(note)
            else:
                st.info(f"{market.code} sells nothing in this order.")
            show_not_sold(market.code, order_not_sold)
