"""Model Health page — calibration, CLV trends, and edge tier analysis."""
from datetime import datetime, timezone

import streamlit as st

from lib.queries import get_settled_bet_stats, get_clv_weekly, get_calibration, get_roi_by_edge_tier
from lib.charts import build_clv_trend, build_calibration, build_roi_by_edge_tier


def _format_relative_time(iso_timestamp: str) -> str:
    """Convert ISO timestamp to human-readable relative time string."""
    dt = datetime.fromisoformat(iso_timestamp)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return "just now"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = total_seconds // 3600
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = total_seconds // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


def render():
    """Main render function for the Model Health page."""
    st.title("Model Health")

    # Sample size indicators
    try:
        stats = get_settled_bet_stats()
    except Exception as e:
        st.error(f"Failed to load bet stats: {e}")
        stats = None

    if stats is not None:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Settled Bets", stats["total_count"])
        with col2:
            market_summary = ", ".join(
                f"{k}: {v}" for k, v in stats["by_market_type"].items()
            )
            st.metric("By Market Type", market_summary)
        with col3:
            if stats.get("latest_timestamp"):
                st.metric("Latest Bet", _format_relative_time(stats["latest_timestamp"]))
            else:
                st.metric("Latest Bet", "N/A")

    # CLV trend chart
    try:
        clv_data = get_clv_weekly()
    except Exception as e:
        st.error(f"Failed to load CLV data: {e}")
        return

    if not clv_data:
        st.info("Not enough settled bets to analyze model health.")
        st.stop()

    fig_clv = build_clv_trend(clv_data)
    if fig_clv is not None:
        st.plotly_chart(
            fig_clv, theme="streamlit", use_container_width=True,
            config={"responsive": True}, key="clv_trend",
        )
        st.caption("Positive CLV indicates your model consistently beats closing lines.")

    # Calibration chart
    try:
        cal_data = get_calibration()
        fig_cal = build_calibration(cal_data)
        if fig_cal is not None:
            st.plotly_chart(
                fig_cal, theme="streamlit", use_container_width=True,
                config={"responsive": True}, key="calibration",
            )
            st.caption("Points near the diagonal indicate well-calibrated predictions. Above = underconfident, below = overconfident.")
    except Exception as e:
        st.error(f"Failed to load calibration data: {e}")

    # Edge tier analysis
    try:
        tier_data = get_roi_by_edge_tier()
        fig_tier = build_roi_by_edge_tier(tier_data)
        if fig_tier is not None:
            st.plotly_chart(
                fig_tier, theme="streamlit", use_container_width=True,
                config={"responsive": True}, key="roi_edge_tier",
            )
            st.caption("Higher-edge bets should produce higher returns if the model is well-calibrated.")
    except Exception as e:
        st.error(f"Failed to load edge tier data: {e}")

    # Timestamp footer
    st.caption(f"Last updated: {datetime.now().strftime('%I:%M %p')}")


render()
