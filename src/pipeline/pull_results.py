from __future__ import annotations

"""
Pull tournament results from DG field-updates endpoint and match to unsettled bets.

Returns structured result records ready for settlement, with player name
fuzzy-matching to handle DG ↔ book name differences.
"""

import re
from difflib import SequenceMatcher

from src.api.datagolf import DataGolfClient


def _normalize(name: str) -> str:
    """Lowercase, strip suffixes, collapse whitespace."""
    name = name.strip().lower()
    name = re.sub(r"\s+(jr\.?|sr\.?|iii|ii|iv)$", "", name)
    return re.sub(r"\s+", " ", name)


def _name_similarity(a: str, b: str) -> float:
    """Score name similarity handling 'Last, First' and initial formats."""
    a, b = _normalize(a), _normalize(b)

    # Direct match
    if a == b:
        return 1.0

    # Split into parts
    def parts(n):
        if "," in n:
            p = n.split(",", 1)
            return (p[1].strip(), p[0].strip())
        p = n.split()
        return (p[0], p[-1]) if len(p) >= 2 else ("", p[0] if p else "")

    fa, la = parts(a)
    fb, lb = parts(b)

    # Last name must be close
    if la != lb:
        if SequenceMatcher(None, la, lb).ratio() < 0.85:
            return 0.0

    # First name: handle initials and nicknames
    if fa and fb:
        if fa == fb:
            return 1.0
        if fa[0] == fb[0] and (len(fa) <= 2 or len(fb) <= 2):
            return 0.9
        # Nickname / full-name prefix: "Cam" ↔ "Cameron", "Nick" ↔ "Nicholas".
        # Require at least 3 chars of agreement so we don't swallow arbitrary
        # unrelated first-name pairs with the same last name.
        short, long_ = (fa, fb) if len(fa) <= len(fb) else (fb, fa)
        if len(short) >= 3 and long_.startswith(short):
            return 0.92
        return 0.6 * SequenceMatcher(None, la, lb).ratio() + 0.4 * SequenceMatcher(None, fa, fb).ratio()

    return 0.8  # Last name match, one first name missing


def fetch_results(tour: str = "pga") -> dict:
    """Fetch current field/results from DG.

    Returns:
        {
            "event_name": str,
            "current_round": int,
            "players": {
                "player name (lowercase)": {
                    "name": str (original case),
                    "dg_id": str,
                    "pos": int | None,
                    "pos_str": str (e.g. "T3", "1", "MC"),
                    "status": str ("active"|"cut"|"wd"|"dq"),
                    "r1": int|None, "r2": int|None, "r3": int|None, "r4": int|None,
                    "total": int|None,
                },
                ...
            }
        }
    """
    dg = DataGolfClient()
    resp = dg.get_field_updates(tour=tour)

    if resp["status"] != "ok":
        raise RuntimeError(f"DG field-updates failed: {resp.get('message', 'unknown')}")

    raw = resp["data"]
    event_name = raw.get("event_name", "Unknown Event")
    current_round = raw.get("current_round", 0)
    field = raw.get("field", [])

    players = {}
    for p in field:
        name = p.get("player_name", "")
        if not name:
            continue

        # Parse position — can be int, str like "T3", or None
        raw_pos = p.get("current_pos")
        pos = None
        pos_str = ""
        status = (p.get("status") or "active").lower()

        if status == "cut":
            pos_str = "MC"
        elif status == "mdf":
            # MDF = Made Friday cut, eliminated on weekend secondary cut.
            # make_cut bets WIN (player cleared the Friday line); placement
            # bets LOSE (MDF finish is always bottom of the field). Preserve
            # the numeric position if DG recorded one so matchup settlement
            # can still resolve against an active or cut opponent.
            pos_str = "MDF"
            if raw_pos is not None:
                try:
                    pos = int(str(raw_pos).lstrip("T"))
                    pos_str = str(raw_pos)
                except (ValueError, TypeError):
                    pass
        elif status in ("wd",):
            pos_str = "WD"
        elif status in ("dq",):
            pos_str = "DQ"
        elif raw_pos is not None:
            # Position could be "T3" or 3
            pos_str = str(raw_pos)
            try:
                pos = int(str(raw_pos).lstrip("T"))
            except (ValueError, TypeError):
                pass

        players[_normalize(name)] = {
            "name": name,
            "dg_id": str(p.get("dg_id", "")),
            "pos": pos,
            "pos_str": pos_str,
            "status": status,
            "r1": p.get("r1"),
            "r2": p.get("r2"),
            "r3": p.get("r3"),
            "r4": p.get("r4"),
            "total": p.get("total"),
        }

    return {
        "event_name": event_name,
        "current_round": current_round,
        "players": players,
    }


def fetch_archived_results(event_id: str | int, year: int,
                           tour: str = "pga") -> dict | None:
    """Fetch results for a completed event from the DG historical archive.

    Returns a results dict in the same shape as ``fetch_results()``, or
    ``None`` if the archive doesn't yet have outcomes for this event
    (``event_completed`` missing). DG typically populates the archive
    within a few hours of the final round ending — once it does, this
    path is authoritative and remains available after the live
    field-updates endpoint has rolled over to the next tournament.

    Only win-market archive rows are pulled since they cover the full
    field (including cut players), which is all we need for settlement.
    """
    dg = DataGolfClient()
    resp = dg.get_historical_outrights(
        event_id=str(event_id), year=year, market="win",
        book="pinnacle", tour=tour,
    )
    if resp.get("status") != "ok":
        return None
    data = resp.get("data") or {}
    if not data.get("event_completed"):
        return None

    players = {}
    for p in data.get("odds", []) or []:
        name = p.get("player_name", "")
        if not name:
            continue
        outcome = str(p.get("outcome", "")).strip()
        up = outcome.upper()
        pos = None
        pos_str = outcome
        status = "active"

        if up in ("CUT", "MC"):
            pos_str = "MC"
            status = "cut"
        elif up == "MDF":
            # See fetch_results() — MDF is distinct from cut.
            pos_str = "MDF"
            status = "mdf"
        elif up == "WD":
            pos_str = "WD"
            status = "wd"
        elif up == "DQ":
            pos_str = "DQ"
            status = "dq"
        else:
            try:
                pos = int(outcome.lstrip("T"))
            except (ValueError, TypeError):
                pass

        players[_normalize(name)] = {
            "name": name,
            "dg_id": str(p.get("dg_id", "")),
            "pos": pos,
            "pos_str": pos_str,
            "status": status,
            # The archive doesn't expose per-round scores on the
            # outrights endpoint, so round_matchup fallback to
            # settle_matchup_bet will have to rely on final position.
            "r1": None, "r2": None, "r3": None, "r4": None,
            "total": None,
        }

    return {
        "event_name": data.get("event_name", "Unknown Event"),
        "current_round": 4,
        "players": players,
    }


def match_player(bet_name: str, results: dict[str, dict],
                 threshold: float = 0.85) -> dict | None:
    """Find the best matching player in results for a bet's player name.

    Args:
        bet_name: player name as recorded on the bet
        results: the 'players' dict from fetch_results()
        threshold: minimum similarity score to accept

    Returns:
        Player result dict, or None if no good match
    """
    norm = _normalize(bet_name)

    # Exact match
    if norm in results:
        return results[norm]

    # Fuzzy match
    best_match = None
    best_score = 0.0

    for key, player in results.items():
        score = _name_similarity(bet_name, player["name"])
        if score > best_score:
            best_score = score
            best_match = player

    if best_match and best_score >= threshold:
        return best_match

    return None


def match_bets_to_results(bets: list[dict], results: dict) -> list[dict]:
    """Match unsettled bets to tournament results.

    For each bet, attaches:
        - player_result: matched player dict (or None)
        - opponent_result: matched opponent dict (or None, for matchups)
        - opponent_2_result: matched opponent 2 dict (or None, for 3-balls)
        - auto_settleable: True if all needed results were found

    Returns:
        list of bets with result attachments
    """
    players = results["players"]

    for bet in bets:
        bet["player_result"] = match_player(bet["player_name"], players)

        if bet.get("opponent_name"):
            bet["opponent_result"] = match_player(bet["opponent_name"], players)
        else:
            bet["opponent_result"] = None

        if bet.get("opponent_2_name"):
            bet["opponent_2_result"] = match_player(bet["opponent_2_name"], players)
        else:
            bet["opponent_2_result"] = None

        # Determine if we have enough data to auto-settle
        market = bet["market_type"]
        if market in ("win", "t5", "t10", "t20", "make_cut"):
            bet["auto_settleable"] = bet["player_result"] is not None
        elif market in ("tournament_matchup", "round_matchup"):
            bet["auto_settleable"] = (
                bet["player_result"] is not None
                and bet["opponent_result"] is not None
            )
        elif market == "3_ball":
            bet["auto_settleable"] = (
                bet["player_result"] is not None
                and bet["opponent_result"] is not None
                and bet["opponent_2_result"] is not None
            )
        else:
            bet["auto_settleable"] = False

    return bets
