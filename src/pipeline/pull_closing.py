from __future__ import annotations

"""
Closing odds capture for CLV tracking.

Pulls the same outright and matchup odds right before tournament/round start.
These become the "closing line" for computing CLV on placed bets.
"""

from datetime import datetime, timezone

from src.api.datagolf import DataGolfClient
from src.core.devig import parse_american_odds


def pull_closing_outrights(tournament_slug: str | None = None,
                            tour: str = "pga") -> dict[str, list[dict]]:
    """Pull closing outright odds for all placement markets.

    Same as pull_outrights but tagged as 'closing' snapshots.
    """
    from src.pipeline.pull_outrights import pull_all_outrights
    return pull_all_outrights(tournament_slug, tour)


def pull_closing_matchups(tournament_slug: str | None = None,
                           tour: str = "pga") -> dict:
    """Pull closing matchup odds."""
    from src.pipeline.pull_matchups import (
        pull_round_matchups, pull_3balls
    )
    return {
        "round_matchups": pull_round_matchups(tournament_slug, tour),
        "3_balls": pull_3balls(tournament_slug, tour),
    }


def build_closing_snapshots(outrights: dict[str, list[dict]],
                             tournament_id: str | None) -> list[dict]:
    """Convert outright odds data into snapshot records for Supabase.

    Args:
        outrights: {"top_20": [player_records], ...}
        tournament_id: UUID of the tournament

    Returns:
        List of snapshot dicts ready for odds_snapshots table
    """
    market_map = {
        "win": "win", "top_10": "t10",
        "top_20": "t20", "make_cut": "make_cut",
    }
    now = datetime.now(timezone.utc).isoformat()
    snapshots = []

    for dg_market, records in outrights.items():
        market_type = market_map.get(dg_market, dg_market)
        if not isinstance(records, list):
            continue

        for player in records:
            player_name = player.get("player_name", "").strip().strip('"')
            dg_id = str(player.get("dg_id", ""))

            # Extract DG probability
            dg_data = player.get("datagolf", {})
            if isinstance(dg_data, dict):
                dg_odds_str = str(dg_data.get("baseline_history_fit") or
                                  dg_data.get("baseline") or "")
            else:
                dg_odds_str = str(dg_data or "")
            dg_prob = parse_american_odds(dg_odds_str)

            # Collect all book odds
            skip_keys = {"player_name", "dg_id", "datagolf", "dk_salary",
                         "dk_ownership", "early_late", "tee_time",
                         "r1_teetime", "event_name"}
            book_odds = {}
            for key, val in player.items():
                if key in skip_keys:
                    continue
                if isinstance(val, str) and (val.startswith("+") or val.startswith("-")):
                    book_odds[key] = val

            snapshot = {
                "snapshot_type": "closing",
                "snapshot_timestamp": now,
                "market_type": market_type,
                "player_name": player_name,
                "player_dg_id": dg_id,
                "dg_prob": dg_prob,
                "book_odds": book_odds if book_odds else None,
            }
            if tournament_id:
                snapshot["tournament_id"] = tournament_id

            snapshots.append(snapshot)

    return snapshots
