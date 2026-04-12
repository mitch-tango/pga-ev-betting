from __future__ import annotations

"""
Matchup and 3-ball odds pull.

Pulls tournament matchups, round matchups, and 3-ball odds from DG API.
Used by run_pretournament.py and run_preround.py.
"""

from datetime import datetime, timedelta, timezone

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


def build_field_status_lookup(tour: str = "pga") -> dict:
    """Return field/timing info for filtering stale round matchups.

    DG's field_updates payload exposes `current_round`, `tz_offset` (seconds
    from UTC), and a per-player `teetimes` list (one entry per scheduled
    round). It does NOT expose live `thru` or `status`, so staleness must
    be derived from the current round's tee time vs. the venue-local clock.
    A player with no tee time entry for the current round is treated as
    cut / WD / MDF.

    Returned shape:
        {
          "current_round": int,
          "now_local": datetime,    # naive, in venue timezone
          "players": {
              dg_id: {
                  "round_teetime": datetime | None,   # naive, venue tz
                  "in_field_for_round": bool,
              },
              ...
          },
        }

    Returns an empty dict if the endpoint fails or `current_round` is
    missing — callers treat that as "skip filtering".
    """
    dg = DataGolfClient()
    resp = dg.get_field_updates(tour=tour)
    if resp.get("status") != "ok":
        return {}

    raw = resp.get("data") or {}
    if not isinstance(raw, dict):
        return {}

    current_round = raw.get("current_round")
    if not current_round:
        return {}

    tz_offset_seconds = raw.get("tz_offset") or 0
    now_local = (
        datetime.now(timezone.utc) + timedelta(seconds=tz_offset_seconds)
    ).replace(tzinfo=None)

    players: dict[str, dict] = {}
    for p in raw.get("field", []) or []:
        dg_id = str(p.get("dg_id", "")).strip()
        if not dg_id:
            continue
        round_teetime = None
        in_field_for_round = False
        for tt in p.get("teetimes") or []:
            if tt.get("round_num") != current_round:
                continue
            in_field_for_round = True
            ts = tt.get("teetime")
            if isinstance(ts, str) and ts:
                try:
                    round_teetime = datetime.strptime(ts, "%Y-%m-%d %H:%M")
                except ValueError:
                    round_teetime = None
            break
        players[dg_id] = {
            "round_teetime": round_teetime,
            "in_field_for_round": in_field_for_round,
        }

    return {
        "current_round": current_round,
        "now_local": now_local,
        "players": players,
    }


def _is_player_stale(dg_id: str, field_lookup: dict) -> bool:
    """Return True if a player has already teed off the current round
    or has no tee time for it (cut / WD / MDF).

    Conservative: players missing from the field lookup entirely (and
    empty/missing lookups) are treated as NOT stale.
    """
    if not field_lookup:
        return False
    players = field_lookup.get("players") or {}
    info = players.get(str(dg_id).strip())
    if not info:
        return False
    if not info.get("in_field_for_round"):
        return True
    teetime = info.get("round_teetime")
    now_local = field_lookup.get("now_local")
    if teetime is None or now_local is None:
        return False
    return teetime <= now_local


def filter_stale_matchups(
    matchups: list[dict],
    field_lookup: dict,
    *,
    n_players: int = 2,
) -> list[dict]:
    """Drop round matchups / 3-balls whose players have already teed off
    or aren't in the field for the current round.

    Empty `field_lookup` short-circuits (returns input unchanged) so
    staleness filtering never hides edges when the field endpoint fails.
    """
    if not field_lookup or not field_lookup.get("players") or not matchups:
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
