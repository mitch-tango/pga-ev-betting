"""Active Bets page — primary tournament monitoring view."""
from datetime import datetime

import streamlit as st
import pandas as pd

from lib.queries import get_current_tournament, get_active_bets, get_weekly_pnl
from lib.aggregations import (
    compute_exposure,
    estimate_round,
    format_date_range,
)
from lib.theme import format_currency, format_percentage


def render():
    """Main render function for the Active Bets page."""
    # 1. Tournament header
    try:
        tournament = get_current_tournament()
    except Exception as e:
        st.error(f"Failed to load tournament data: {e}")
        return

    # 2. Empty state
    if tournament is None:
        st.info("No active tournament this week. Check back on Thursday!")
        st.stop()

    st.title(tournament["tournament_name"])

    # Date range and round estimate
    date_range = format_date_range(tournament["start_date"])
    round_num = estimate_round(tournament["start_date"])
    subtitle = date_range
    if round_num is not None:
        subtitle += f"  \u2022  Est. Round {round_num}"
    st.caption(subtitle)

    # 3. Fetch active bets
    try:
        bets = get_active_bets(tournament_id=tournament["id"])
    except Exception as e:
        st.error(f"Failed to load bets: {e}")
        return

    if not bets:
        st.info("No active bets for this tournament.")
    else:
        # 4. Exposure summary cards
        exposure = compute_exposure(bets)
        market_types = [k for k in exposure if k != "__total__"]

        cols = st.columns(len(market_types) + 1)
        for i, mt in enumerate(sorted(market_types)):
            with cols[i]:
                data = exposure[mt]
                st.markdown(f"**{mt.title()}**")
                st.metric("Bets", data["count"])
                st.metric("Stake", format_currency(data["total_stake"]))
                st.metric("Potential Return", format_currency(data["potential_return"]))

        with cols[-1]:
            total = exposure["__total__"]
            st.markdown("**Total**")
            st.metric("Bets", total["count"])
            st.metric("Stake", format_currency(total["total_stake"]))
            st.metric("Potential Return", format_currency(total["potential_return"]))

        st.caption("Potential return assumes no dead heats.")

        # 6. Filter controls + active bet table
        _render_bet_table(bets)

    # 7. Weekly P&L summary
    _render_weekly_pnl(tournament)

    # 8. Last-updated timestamp
    st.caption(f"Last updated: {datetime.now().strftime('%I:%M %p')}")


def _render_bet_table(bets: list[dict]):
    """Render filtered/sorted active bet table."""
    df = pd.DataFrame(bets)

    # Computed column
    df["potential_return"] = df["stake"] * df["odds_at_bet_decimal"]

    # Fill NaN opponent
    df["opponent_name"] = df["opponent_name"].fillna("")

    # Format edge/CLV for display
    df["edge_fmt"] = df["edge"].apply(format_percentage)
    df["clv_fmt"] = df["clv"].apply(format_percentage)

    # Filter controls
    filter_cols = st.columns(2)
    with filter_cols[0]:
        market_filter = st.multiselect(
            "Market Type", options=sorted(df["market_type"].unique())
        )
    with filter_cols[1]:
        book_filter = st.multiselect(
            "Book", options=sorted(df["book"].unique())
        )

    filtered = df.copy()
    if market_filter:
        filtered = filtered[filtered["market_type"].isin(market_filter)]
    if book_filter:
        filtered = filtered[filtered["book"].isin(book_filter)]

    # Sort by bet_timestamp descending
    filtered = filtered.sort_values("bet_timestamp", ascending=False)

    # Display columns
    display_df = filtered[
        [
            "player_name",
            "opponent_name",
            "market_type",
            "book",
            "odds_at_bet_american",
            "stake",
            "edge_fmt",
            "clv_fmt",
            "potential_return",
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
            "potential_return": st.column_config.NumberColumn(
                "Potential Return", format="$%.2f"
            ),
        },
        hide_index=True,
        use_container_width=True,
    )


def _render_weekly_pnl(tournament: dict):
    """Render weekly P&L summary metrics."""
    st.subheader("Weekly P&L")
    try:
        pnl = get_weekly_pnl(tournament["id"])
    except Exception as e:
        st.error(f"Failed to load P&L data: {e}")
        return

    cols = st.columns(3)
    with cols[0]:
        settled = pnl["settled_pnl"]
        delta_color = "normal" if settled >= 0 else "inverse"
        st.metric(
            "Settled P&L",
            format_currency(settled),
            delta=format_currency(settled) if settled != 0 else None,
            delta_color=delta_color,
        )
    with cols[1]:
        st.metric("Open Exposure", format_currency(pnl["unsettled_stake"]))
    with cols[2]:
        net = pnl["net_position"]
        delta_color = "normal" if net >= 0 else "inverse"
        st.metric(
            "Net Position",
            format_currency(net),
            delta=format_currency(net) if net != 0 else None,
            delta_color=delta_color,
        )


render()
