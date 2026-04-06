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
