"""Pure aggregation helpers for bet data. No Streamlit dependency."""
from __future__ import annotations

from datetime import date, timedelta


def group_by_market_type(bets: list[dict]) -> dict[str, list[dict]]:
    """Group a list of bet dicts by their 'market_type' field."""
    groups: dict[str, list[dict]] = {}
    for bet in bets:
        key = bet["market_type"]
        groups.setdefault(key, []).append(bet)
    return groups


def compute_exposure(bets: list[dict]) -> dict[str, dict]:
    """Compute exposure metrics grouped by market type.

    Returns dict keyed by market_type with values:
        {"count": int, "total_stake": float, "potential_return": float}

    Also includes a "__total__" key with aggregate across all types.
    """
    if not bets:
        return {}

    groups = group_by_market_type(bets)
    result: dict[str, dict] = {}

    total_count = 0
    total_stake = 0.0
    total_return = 0.0

    for market_type, group_bets in groups.items():
        count = len(group_bets)
        stake = sum(b["stake"] for b in group_bets)
        potential_return = sum(b["stake"] * b["odds_at_bet_decimal"] for b in group_bets)
        result[market_type] = {
            "count": count,
            "total_stake": stake,
            "potential_return": potential_return,
        }
        total_count += count
        total_stake += stake
        total_return += potential_return

    result["__total__"] = {
        "count": total_count,
        "total_stake": total_stake,
        "potential_return": total_return,
    }
    return result


def compute_weekly_pnl(all_tournament_bets: list[dict]) -> dict:
    """Compute weekly P&L summary from all bets for a tournament."""
    settled = [b for b in all_tournament_bets if b["outcome"] is not None]
    unsettled = [b for b in all_tournament_bets if b["outcome"] is None]

    settled_pnl = sum(b["pnl"] or 0 for b in settled) if settled else 0.0
    unsettled_stake = sum(b["stake"] for b in unsettled) if unsettled else 0.0

    return {
        "settled_pnl": settled_pnl,
        "unsettled_stake": unsettled_stake,
        "net_position": settled_pnl - unsettled_stake,
    }


def estimate_round(start_date_str: str, today: date | None = None) -> int | None:
    """Estimate current tournament round from start date.

    Returns 1-4 if today is within the tournament window (start_date to start_date + 3).
    Returns None if today is before start_date or more than 3 days after.
    """
    if today is None:
        today = date.today()
    start = date.fromisoformat(start_date_str)
    delta = (today - start).days
    if 0 <= delta <= 3:
        return delta + 1
    return None


def format_date_range(start_date_str: str) -> str:
    """Format a tournament date range as 'Apr 3 – Apr 6, 2026'.

    Assumes 4-day tournament (Thu-Sun). Uses en-dash between dates.
    """
    start = date.fromisoformat(start_date_str)
    end = start + timedelta(days=3)
    start_fmt = f"{start.strftime('%b')} {start.day}"
    end_fmt = f"{end.strftime('%b')} {end.day}, {end.year}"
    return f"{start_fmt} \u2013 {end_fmt}"
