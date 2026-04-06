"""Database queries with Streamlit caching for the PGA +EV Dashboard."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from lib.supabase_client import get_client

_TOURNAMENT_COLUMNS = (
    "id, tournament_name, start_date, purse, is_signature, "
    "is_no_cut, putting_surface, dg_event_id, season"
)

_BET_COLUMNS = (
    "id, tournament_id, market_type, player_name, opponent_name, book, "
    "bet_timestamp, odds_at_bet_decimal, odds_at_bet_american, "
    "implied_prob_at_bet, your_prob, edge, stake, clv"
)

_SETTLED_BET_COLUMNS = (
    "id, tournament_id, market_type, player_name, opponent_name, book, "
    "bet_timestamp, odds_at_bet_decimal, odds_at_bet_american, "
    "implied_prob_at_bet, your_prob, edge, stake, clv, outcome, pnl"
)


@st.cache_data(ttl=300)
def get_current_tournament() -> dict | None:
    """Fetch the current week's tournament.

    Returns None during off-weeks.
    """
    client = get_client()
    today = date.today()
    # Tournament starts Thu, ends Sun. Buffer 1 day before for Wed arrivals.
    start_before = (today + timedelta(days=1)).isoformat()
    start_after = (today - timedelta(days=4)).isoformat()

    result = (
        client.table("tournaments")
        .select(_TOURNAMENT_COLUMNS)
        .lte("start_date", start_before)
        .gte("start_date", start_after)
        .order("start_date", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


@st.cache_data(ttl=300)
def get_active_bets(tournament_id: str | None = None) -> list[dict]:
    """Fetch all bets with outcome IS NULL."""
    client = get_client()
    query = (
        client.table("bets")
        .select(_BET_COLUMNS)
        .is_("outcome", "null")
    )
    if tournament_id is not None:
        query = query.eq("tournament_id", tournament_id)
    query = query.order("bet_timestamp", desc=True)
    result = query.execute()
    return result.data


@st.cache_data(ttl=300)
def get_weekly_pnl(tournament_id: str) -> dict:
    """Calculate P&L summary for a tournament."""
    client = get_client()
    result = (
        client.table("bets")
        .select("id, stake, pnl, outcome")
        .eq("tournament_id", tournament_id)
        .execute()
    )
    bets = result.data
    settled = [b for b in bets if b["outcome"] is not None]
    unsettled = [b for b in bets if b["outcome"] is None]

    settled_pnl = sum(b["pnl"] or 0 for b in settled) if settled else 0.0
    unsettled_stake = sum(b["stake"] for b in unsettled) if unsettled else 0.0

    return {
        "settled_pnl": settled_pnl,
        "unsettled_stake": unsettled_stake,
        "net_position": settled_pnl - unsettled_stake,
    }


@st.cache_data(ttl=300)
def get_settled_bets(start_date: str | None = None, end_date: str | None = None) -> list[dict]:
    """Fetch all settled bets (outcome IS NOT NULL), optionally filtered by date range."""
    client = get_client()
    query = (
        client.table("bets")
        .select(_SETTLED_BET_COLUMNS)
        .is_("outcome", "not.null")
    )
    if start_date is not None:
        query = query.gte("bet_timestamp", start_date)
    if end_date is not None:
        query = query.lte("bet_timestamp", end_date)
    query = query.order("bet_timestamp").order("id")
    result = query.execute()
    return result.data


@st.cache_data(ttl=3600)
def get_settled_bet_stats() -> dict:
    """Fetch summary stats for settled bets: count, breakdown by market type, latest timestamp."""
    client = get_client()
    result = (
        client.table("bets")
        .select("market_type, bet_timestamp", count="exact")
        .is_("outcome", "not.null")
        .execute()
    )
    rows = result.data
    by_market: dict[str, int] = {}
    for row in rows:
        mt = row["market_type"]
        by_market[mt] = by_market.get(mt, 0) + 1
    latest = max((r["bet_timestamp"] for r in rows), default=None)
    return {
        "total_count": result.count,
        "by_market_type": by_market,
        "latest_timestamp": latest,
    }


@st.cache_data(ttl=3600)
def get_bankroll_curve() -> list[dict]:
    """Fetch bankroll curve data from view."""
    client = get_client()
    result = (
        client.table("v_bankroll_curve")
        .select("entry_date, entry_type, amount, running_balance")
        .order("entry_date")
        .execute()
    )
    return result.data


@st.cache_data(ttl=3600)
def get_weekly_exposure() -> list[dict]:
    """Fetch weekly exposure data from view."""
    client = get_client()
    result = (
        client.table("v_weekly_exposure")
        .select("week, bets_placed, total_exposure, largest_single_bet, unique_players")
        .order("week")
        .execute()
    )
    return result.data


@st.cache_data(ttl=3600)
def get_clv_weekly() -> list[dict]:
    """Fetch weekly CLV data from view."""
    client = get_client()
    result = (
        client.table("v_clv_weekly")
        .select("week, bets, avg_clv_pct, weekly_pnl, avg_edge_pct")
        .order("week")
        .execute()
    )
    return result.data


@st.cache_data(ttl=3600)
def get_calibration() -> list[dict]:
    """Fetch calibration data from view."""
    client = get_client()
    result = (
        client.table("v_calibration")
        .select("prob_bucket, n, avg_predicted_pct, actual_hit_pct")
        .execute()
    )
    return result.data


@st.cache_data(ttl=3600)
def get_roi_by_edge_tier() -> list[dict]:
    """Fetch ROI by edge tier data from view."""
    client = get_client()
    result = (
        client.table("v_roi_by_edge_tier")
        .select("edge_tier, total_bets, total_staked, total_pnl, roi_pct, avg_clv_pct")
        .execute()
    )
    return result.data
