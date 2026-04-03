from __future__ import annotations

"""
Live in-play predictions pull.

Pulls DG's live model (updates every 5 minutes) during tournament rounds.
Used by run_live_check.py for exploratory live edge detection.
"""

from src.api.datagolf import DataGolfClient


def pull_live_predictions(tournament_slug: str | None = None,
                           tour: str = "pga") -> list[dict]:
    """Pull live in-play predictions from DG.

    Returns player-level live probabilities for win, T5, T20, make-cut.
    """
    dg = DataGolfClient()
    result = dg.get_live_predictions(
        tour=tour, odds_format="percent",
        tournament_slug=tournament_slug,
    )

    if result["status"] == "ok":
        data = result["data"]
        if isinstance(data, dict):
            return data.get("live_stats", data.get("data", []))
        elif isinstance(data, list):
            return data
    else:
        print(f"  Warning: live predictions unavailable: "
              f"{result.get('message', '')[:100]}")
    return []
