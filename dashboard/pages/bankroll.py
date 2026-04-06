"""Bankroll page — equity curve, drawdown, and exposure tracking."""
from datetime import datetime

import streamlit as st

from lib.queries import get_bankroll_curve, get_weekly_exposure
from lib.aggregations import compute_drawdown
from lib.theme import format_currency
from lib.charts import build_bankroll_drawdown, build_weekly_exposure as build_weekly_exposure_chart


def render():
    """Main render function for the Bankroll page."""
    st.title("Bankroll")

    # Fetch bankroll data
    try:
        bankroll_data = get_bankroll_curve()
    except Exception as e:
        st.error(f"Failed to load bankroll data: {e}")
        return

    if not bankroll_data:
        st.info("No bankroll data available. Add entries to the bankroll_ledger table to see your bankroll curve.")
        st.stop()

    # Current balance metric
    current_balance = bankroll_data[-1]["running_balance"]
    delta = None
    if len(bankroll_data) > 1:
        delta = current_balance - bankroll_data[-2]["running_balance"]
    st.metric(
        "Current Balance",
        format_currency(current_balance),
        delta=format_currency(delta) if delta is not None else None,
    )

    # Drawdown metrics
    dd = compute_drawdown(bankroll_data)
    col_max, col_current = st.columns(2)
    with col_max:
        st.metric("Max Drawdown", f"{dd['max_drawdown_pct']:.1f}%")
    with col_current:
        st.metric("Current Drawdown", f"{dd['current_drawdown_pct']:.1f}%")

    # Bankroll + drawdown chart
    fig = build_bankroll_drawdown(bankroll_data, dd["series"])
    if fig is not None:
        st.plotly_chart(
            fig, theme="streamlit", use_container_width=True,
            config={"responsive": True}, key="bankroll_drawdown",
        )

    # Weekly exposure chart
    try:
        exposure_data = get_weekly_exposure()
    except Exception as e:
        st.error(f"Failed to load exposure data: {e}")
        exposure_data = []

    if exposure_data:
        fig_exp = build_weekly_exposure_chart(exposure_data)
        if fig_exp is not None:
            st.plotly_chart(
                fig_exp, theme="streamlit", use_container_width=True,
                config={"responsive": True}, key="weekly_exposure",
            )

    # Timestamp footer
    st.caption(f"Last updated: {datetime.now().strftime('%I:%M %p')}")


render()
