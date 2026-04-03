from __future__ import annotations

"""
Matchup and 3-ball odds pull.

Pulls tournament matchups, round matchups, and 3-ball odds from DG API.
Used by run_pretournament.py and run_preround.py.
"""

from src.api.datagolf import DataGolfClient


def pull_tournament_matchups(tournament_slug: str | None = None,
                              tour: str = "pga") -> list[dict]:
    """Pull tournament-long matchup odds (DG model + books)."""
    dg = DataGolfClient()
    result = dg.get_matchups(
        market="tournament_matchups", tour=tour, odds_format="american",
        tournament_slug=tournament_slug,
    )
    if result["status"] == "ok":
        data = result["data"]
        if isinstance(data, dict):
            match_list = data.get("match_list", [])
            if isinstance(match_list, list):
                return match_list
        elif isinstance(data, list):
            return data
    else:
        print(f"  Warning: failed to pull tournament matchups: "
              f"{result.get('message', '')[:100]}")
    return []


def pull_round_matchups(tournament_slug: str | None = None,
                         tour: str = "pga") -> list[dict]:
    """Pull round matchup odds (available after pairings are set)."""
    dg = DataGolfClient()
    result = dg.get_matchups(
        market="round_matchups", tour=tour, odds_format="american",
        tournament_slug=tournament_slug,
    )
    if result["status"] == "ok":
        data = result["data"]
        if isinstance(data, dict):
            match_list = data.get("match_list", [])
            if isinstance(match_list, list):
                return match_list
        elif isinstance(data, list):
            return data
    return []


def pull_3balls(tournament_slug: str | None = None,
                tour: str = "pga") -> list[dict]:
    """Pull 3-ball odds (available after pairings are set)."""
    dg = DataGolfClient()
    result = dg.get_matchups(
        market="3_balls", tour=tour, odds_format="american",
        tournament_slug=tournament_slug,
    )
    if result["status"] == "ok":
        data = result["data"]
        if isinstance(data, dict):
            match_list = data.get("match_list", [])
            if isinstance(match_list, list):
                return match_list
        elif isinstance(data, list):
            return data
    return []


def pull_all_pairings(tournament_slug: str | None = None,
                       tour: str = "pga") -> list[dict]:
    """Pull DG matchup/3-ball odds for all pairings in the next round."""
    dg = DataGolfClient()
    result = dg.get_all_pairings(
        tour=tour, odds_format="american",
        tournament_slug=tournament_slug,
    )
    if result["status"] == "ok":
        data = result["data"]
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return data.get("match_list", [])
    return []
