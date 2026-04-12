from __future__ import annotations

"""
Merge Start sportsbook odds into DataGolf data.

Takes parsed Start matchups (from start_matchups.py) and outrights
(from start_outrights.py) and injects them into the DG API format
so the existing edge calculator picks up Start as another book.

Name matching uses normalized last-name + first-initial comparison
to handle "SI WOO KIM" (Start) vs "Si Woo Kim" (DG).
"""

import re
from difflib import SequenceMatcher


def _normalize_for_match(name: str) -> str:
    """Normalize a name for matching: lowercase, strip accents, collapse spaces.

    Handles DG's "Last, First" format by converting to "first last".
    """
    name = name.strip().lower()
    name = re.sub(r"\s+", " ", name)
    # Convert "last, first" -> "first last"
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2 and parts[1]:
            name = f"{parts[1]} {parts[0]}"
    return name


def _last_name(name: str) -> str:
    """Extract last name (last token after normalization)."""
    parts = _normalize_for_match(name).split()
    return parts[-1] if parts else ""


def _names_match(start_name: str, dg_name: str) -> bool:
    """Check if a Start name matches a DG name.

    Handles case differences, "Last, First" vs "First Last" format,
    and minor spelling variations.
    """
    s = _normalize_for_match(start_name)
    d = _normalize_for_match(dg_name)

    # Exact match after normalization
    if s == d:
        return True

    # Last name must match
    if _last_name(start_name) != _last_name(dg_name):
        return False

    # Overall similarity with last name matching
    ratio = SequenceMatcher(None, s, d).ratio()
    return ratio >= 0.80


def merge_start_into_matchups(
    dg_matchups: list[dict],
    start_matchups: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Inject Start odds into DG matchup records.

    For each Start matchup, find the corresponding DG matchup by
    player name matching, then add "start" to the odds dict.

    Args:
        dg_matchups: DG API matchup data (list of matchup records with
            p1_player_name, p2_player_name, odds dict).
        start_matchups: Parsed Start matchups from parse_start_matchups().

    Returns:
        Tuple of (updated_dg_matchups, unmatched_start_matchups).
        DG matchups are modified in place with "start" added to odds.
        Unmatched Start matchups couldn't be paired to any DG matchup.
    """
    unmatched = []

    for sm in start_matchups:
        # Only merge tournament matchups (round_number=None) into DG
        # tournament matchups. Round matchups are tracked separately.
        if sm.get("round_number") is not None:
            continue

        matched = False

        for dg in dg_matchups:
            dg_p1 = dg.get("p1_player_name", "")
            dg_p2 = dg.get("p2_player_name", "")

            # Check both orientations:
            # Start p1/p2 might map to DG p1/p2 or DG p2/p1
            if (_names_match(sm["p1_name"], dg_p1) and
                    _names_match(sm["p2_name"], dg_p2)):
                # Same order
                dg["odds"]["start"] = {
                    "p1": sm["p1_odds"],
                    "p2": sm["p2_odds"],
                }
                matched = True
                break
            elif (_names_match(sm["p1_name"], dg_p2) and
                  _names_match(sm["p2_name"], dg_p1)):
                # Reversed order — swap odds
                dg["odds"]["start"] = {
                    "p1": sm["p2_odds"],
                    "p2": sm["p1_odds"],
                }
                matched = True
                break

        if not matched:
            unmatched.append(sm)

    return dg_matchups, unmatched


# DG API market names used in pull_all_outrights()
_MARKET_KEY_MAP = {
    "win": "win",
    "t10": "top_10",
    "t20": "top_20",
    "make_cut": "make_cut",
}


def merge_start_into_outrights(
    dg_outrights: dict[str, list[dict]],
    start_outrights: dict[str, list[dict]],
) -> dict[str, int]:
    """Inject Start odds into DG outright player records.

    For each Start outright market, find the corresponding DG player
    by name matching, then add ``"start"`` as a top-level key on the
    player dict (the same format used by DG for other books like
    ``"draftkings": "-370"``).

    Args:
        dg_outrights: Result of ``pull_all_outrights()`` — keys are DG
            market names (``"win"``, ``"top_10"``, etc.), values are
            lists of player dicts.
        start_outrights: Parsed Start outrights from
            ``parse_start_outrights()`` — keys are our market names
            (``"win"``, ``"t10"``, ``"t20"``, ``"make_cut"``).

    Returns:
        Dict mapping market type to number of matched players.
        DG outrights are modified in place.
    """
    stats: dict[str, int] = {}

    for our_market, start_players in start_outrights.items():
        dg_market = _MARKET_KEY_MAP.get(our_market)
        if not dg_market or dg_market not in dg_outrights:
            continue

        dg_players = dg_outrights[dg_market]
        matched = 0

        # Build a lookup from normalized name -> DG player dict
        dg_lookup: dict[str, dict] = {}
        for player in dg_players:
            name = player.get("player_name", "")
            dg_lookup[_normalize_for_match(name)] = player

        for sp in start_players:
            start_norm = _normalize_for_match(sp["name"])

            # Try exact normalized match first
            if start_norm in dg_lookup:
                dg_lookup[start_norm]["start"] = sp["odds"]
                matched += 1
                continue

            # Fall back to last-name + similarity matching
            for dg_name, dg_player in dg_lookup.items():
                if _names_match(sp["name"], dg_player.get("player_name", "")):
                    dg_player["start"] = sp["odds"]
                    matched += 1
                    break

        stats[our_market] = matched

    return stats
