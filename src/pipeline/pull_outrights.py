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
         "_event_name": "Valero Texas Open",
         "_last_updated": "2026-04-05 02:35:17 UTC",
         "_notes": "...",
         "_is_live": True/False}

    Metadata keys (prefixed with ``_``) carry API response info used by
    callers to detect stale data or live-tournament conditions.
    """
    dg = DataGolfClient()
    results = {}
    event_name = None
    last_updated = None
    notes = None

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
                if not last_updated and data.get("last_updated"):
                    last_updated = data["last_updated"]
                if not notes and data.get("notes"):
                    notes = data["notes"]
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
    if last_updated:
        results["_last_updated"] = last_updated
    if notes:
        results["_notes"] = notes

    # Detect live/completed tournament — DG sets notes to indicate the
    # baseline model is unavailable once a tournament is in progress.
    is_live = False
    if notes:
        notes_lower = notes.lower()
        if "live" in notes_lower or "baseline model not available" in notes_lower:
            is_live = True
    results["_is_live"] = is_live

    return results
