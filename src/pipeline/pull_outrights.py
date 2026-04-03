from __future__ import annotations

"""
Pre-tournament outright odds pull.

Pulls win, T5, T10, T20, and make-cut odds from DG API
(DG model + all sportsbooks). Used by run_pretournament.py.
"""

from src.api.datagolf import DataGolfClient


OUTRIGHT_MARKETS = ["win", "top_5", "top_10", "top_20", "make_cut"]


def pull_all_outrights(tournament_slug: str | None = None,
                       tour: str = "pga") -> dict[str, list[dict]]:
    """Pull all outright markets for the current tournament.

    Returns:
        {"win": [player_records], "top_5": [...], ...}
    """
    dg = DataGolfClient()
    results = {}

    for market in OUTRIGHT_MARKETS:
        result = dg.get_outrights(
            market=market, tour=tour, odds_format="american",
            tournament_slug=tournament_slug,
        )
        if result["status"] == "ok":
            data = result["data"]
            if isinstance(data, dict) and "odds" in data:
                # Live API returns {"odds": [...], "event_name": ..., ...}
                odds_list = data.get("odds", [])
                if isinstance(odds_list, list):
                    results[market] = odds_list
                else:
                    results[market] = []
            elif isinstance(data, list):
                results[market] = data
        else:
            print(f"  Warning: failed to pull {market}: {result.get('message', '')[:100]}")
            results[market] = []

    return results
