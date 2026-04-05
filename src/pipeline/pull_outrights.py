from __future__ import annotations

"""
Pre-tournament outright odds pull.

Pulls win, T10, T20, and make-cut odds from DG API
(DG model + all sportsbooks). Used by run_pretournament.py.
"""

from src.api.datagolf import DataGolfClient


OUTRIGHT_MARKETS = ["win", "top_10", "top_20", "make_cut"]


def pull_all_outrights(tournament_slug: str | None = None,
                       tour: str = "pga") -> dict[str, list[dict]]:
    """Pull all outright markets for the current tournament.

    Returns:
        {"win": [player_records], "top_10": [...], ...,
         "_event_name": "Valero Texas Open"}

    The "_event_name" key (if present) carries the event name from the
    DG API response, used for tournament auto-detection.
    """
    dg = DataGolfClient()
    results = {}
    event_name = None

    for market in OUTRIGHT_MARKETS:
        result = dg.get_outrights(
            market=market, tour=tour, odds_format="american",
            tournament_slug=tournament_slug,
        )
        if result["status"] == "ok":
            data = result["data"]
            if isinstance(data, dict) and "odds" in data:
                # Live API returns {"odds": [...], "event_name": ..., ...}
                if not event_name and data.get("event_name"):
                    event_name = data["event_name"]
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

    if event_name:
        results["_event_name"] = event_name

    return results
