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


def build_field_status_lookup(tour: str = "pga") -> dict[str, dict]:
    """Return {dg_id: {thru, status}} for the current field.

    `thru` comes through as DG sends it (None/"", numeric string, or "F").
    Used to drop stale round matchups / 3-balls whose players have already
    teed off.
    """
    dg = DataGolfClient()
    resp = dg.get_field_updates(tour=tour)
    if resp.get("status") != "ok":
        return {}

    raw = resp.get("data") or {}
    field = raw.get("field", []) if isinstance(raw, dict) else []

    lookup: dict[str, dict] = {}
    for p in field:
        dg_id = str(p.get("dg_id", "")).strip()
        if not dg_id:
            continue
        lookup[dg_id] = {
            "thru": p.get("thru"),
            "status": (p.get("status") or "active").lower(),
        }
    return lookup


def _is_player_stale(dg_id: str, field_lookup: dict[str, dict]) -> bool:
    """Return True if a player has already teed off the current round,
    finished it, or is otherwise unavailable (cut/WD/DQ).

    Conservative: players missing from the field lookup are treated as
    NOT stale (we'd rather surface a false positive than silently drop
    a valid matchup when the field endpoint is incomplete).
    """
    info = field_lookup.get(str(dg_id).strip())
    if not info:
        return False

    status = info.get("status", "active")
    if status in ("cut", "mdf", "wd", "dq"):
        return True

    thru = info.get("thru")
    if thru is None:
        return False
    # DG sends "" or None for "hasn't teed off"
    if isinstance(thru, str):
        s = thru.strip()
        if not s:
            return False
        # "F" = finished this round; any numeric string = in progress
        return s.upper() == "F" or s.isdigit()
    if isinstance(thru, (int, float)):
        return thru > 0
    return False


def filter_stale_matchups(
    matchups: list[dict],
    field_lookup: dict[str, dict],
    *,
    n_players: int = 2,
) -> list[dict]:
    """Drop round matchups / 3-balls whose players have already teed off
    (or are finished / cut / WD / DQ).

    Args:
        matchups: DG matchup records (round_matchups or 3_balls)
        field_lookup: output of `build_field_status_lookup`
        n_players: 2 for H2H matchups, 3 for 3-balls

    Returns:
        Filtered list. Empty field_lookup short-circuits (returns input
        unchanged) so staleness filtering never hides edges when the
        field endpoint fails.
    """
    if not field_lookup or not matchups:
        return matchups

    keys = [f"p{i}_dg_id" for i in range(1, n_players + 1)]
    kept = []
    for m in matchups:
        stale = False
        for k in keys:
            if _is_player_stale(str(m.get(k, "")), field_lookup):
                stale = True
                break
        if not stale:
            kept.append(m)
    return kept
