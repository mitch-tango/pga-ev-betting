"""Performance page — historical bet analysis with time-window filtering."""
from datetime import datetime

import streamlit as st
import pandas as pd

from lib.queries import get_settled_bets
from lib.aggregations import compute_cumulative_pnl, compute_roi_by_group, compute_date_range
from lib.charts import build_pnl_curve, build_edge_histogram
from lib.theme import format_currency, format_percentage


def render():
    """Main render function for the Performance page."""
    st.title("Performance")

    # Time window selector
    window = st.segmented_control(
        "Time Window", options=["30D", "90D", "Season"], default="Season"
    )
    if window is None:
        window = "Season"
    start_date, end_date = compute_date_range(window)

    # Fetch settled bets
    try:
        bets = get_settled_bets(start_date, end_date)
    except Exception as e:
        st.error(f"Failed to load settled bets: {e}")
        return

    if not bets:
        st.info("No settled bets in this time window.")
        st.stop()

    # P&L curve
    cumulative = compute_cumulative_pnl(bets)
    fig = build_pnl_curve(cumulative)
    if fig is not None:
        st.plotly_chart(
            fig, theme="streamlit", use_container_width=True,
            config={"responsive": True}, key="pnl_curve",
        )

    # ROI summary tables
    col_market, col_book = st.columns(2)
    with col_market:
        st.subheader("ROI by Market Type")
        roi_market = compute_roi_by_group(bets, "market_type")
        if roi_market:
            df_market = pd.DataFrame(roi_market)
            st.dataframe(
                df_market,
                column_config={
                    "group": st.column_config.TextColumn("Market"),
                    "total_bets": st.column_config.NumberColumn("Bets"),
                    "total_staked": st.column_config.NumberColumn("Staked", format="$%.2f"),
                    "total_pnl": st.column_config.NumberColumn("P&L", format="$%.2f"),
                    "roi_pct": st.column_config.NumberColumn("ROI", format="%.1f%%"),
                    "avg_edge_pct": st.column_config.NumberColumn("Avg Edge", format="%.1f%%"),
                    "avg_clv_pct": st.column_config.NumberColumn("Avg CLV", format="%.1f%%"),
                    "wins": st.column_config.NumberColumn("W"),
                    "losses": st.column_config.NumberColumn("L"),
                },
                hide_index=True,
                use_container_width=True,
            )

    with col_book:
        st.subheader("ROI by Sportsbook")
        roi_book = compute_roi_by_group(bets, "book")
        if roi_book:
            df_book = pd.DataFrame(roi_book)
            st.dataframe(
                df_book,
                column_config={
                    "group": st.column_config.TextColumn("Book"),
                    "total_bets": st.column_config.NumberColumn("Bets"),
                    "total_staked": st.column_config.NumberColumn("Staked", format="$%.2f"),
                    "total_pnl": st.column_config.NumberColumn("P&L", format="$%.2f"),
                    "roi_pct": st.column_config.NumberColumn("ROI", format="%.1f%%"),
                    "avg_edge_pct": st.column_config.NumberColumn("Avg Edge", format="%.1f%%"),
                    "avg_clv_pct": st.column_config.NumberColumn("Avg CLV", format="%.1f%%"),
                    "wins": st.column_config.NumberColumn("W"),
                    "losses": st.column_config.NumberColumn("L"),
                },
                hide_index=True,
                use_container_width=True,
            )

    # Edge distribution histogram
    fig_edge = build_edge_histogram(bets)
    if fig_edge is not None:
        st.plotly_chart(
            fig_edge, theme="streamlit", use_container_width=True,
            config={"responsive": True}, key="edge_histogram",
        )

    # Bet detail table with filters
    _render_bet_detail(bets)

    # Timestamp footer
    st.caption(f"Last updated: {datetime.now().strftime('%I:%M %p')}")


def _render_bet_detail(bets: list[dict]):
    """Render filtered bet detail table."""
    df = pd.DataFrame(bets)
    df["opponent_name"] = df["opponent_name"].fillna("")
    df["edge_fmt"] = df["edge"].apply(format_percentage)
    df["clv_fmt"] = df["clv"].apply(format_percentage)

    # Filter controls
    filter_cols = st.columns(2)
    with filter_cols[0]:
        market_filter = st.multiselect(
            "Market Type", options=sorted(df["market_type"].unique()),
            key="perf_market_filter",
        )
    with filter_cols[1]:
        book_filter = st.multiselect(
            "Book", options=sorted(df["book"].unique()),
            key="perf_book_filter",
        )

    filtered = df.copy()
    if market_filter:
        filtered = filtered[filtered["market_type"].isin(market_filter)]
    if book_filter:
        filtered = filtered[filtered["book"].isin(book_filter)]

    filtered = filtered.sort_values("bet_timestamp", ascending=False)

    display_df = filtered[
        [
            "player_name", "opponent_name", "market_type", "book",
            "odds_at_bet_american", "stake", "edge_fmt", "clv_fmt",
            "outcome", "pnl", "bet_timestamp",
        ]
    ].copy()

    st.dataframe(
        display_df,
        column_config={
            "player_name": st.column_config.TextColumn("Player"),
            "opponent_name": st.column_config.TextColumn("Opponent"),
            "market_type": st.column_config.TextColumn("Market"),
            "book": st.column_config.TextColumn("Book"),
            "odds_at_bet_american": st.column_config.TextColumn("Odds"),
            "stake": st.column_config.NumberColumn("Stake", format="$%.2f"),
            "edge_fmt": st.column_config.TextColumn("Edge"),
            "clv_fmt": st.column_config.TextColumn("CLV"),
            "outcome": st.column_config.TextColumn("Outcome"),
            "pnl": st.column_config.NumberColumn("P&L", format="$%.2f"),
            "bet_timestamp": st.column_config.TextColumn("Date"),
        },
        hide_index=True,
        use_container_width=True,
    )


render()
