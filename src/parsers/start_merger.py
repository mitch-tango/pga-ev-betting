from __future__ import annotations

"""
Merge Start sportsbook odds into DataGolf matchup data.

Takes parsed Start matchups (from start_matchups.py) and injects them
into the DG API matchup format so the existing edge calculator
picks up Start as another book automatically.

Name matching uses normalized last-name + first-initial comparison
to handle "SI WOO KIM" (Start) vs "Si Woo Kim" (DG).
"""

import re
from difflib import SequenceMatcher


def _normalize_for_match(name: str) -> str:
    """Normalize a name for matching: lowercase, strip accents, collapse spaces."""
    name = name.strip().lower()
    name = re.sub(r"\s+", " ", name)
    return name


def _last_name(name: str) -> str:
    """Extract last name (last token)."""
    parts = _normalize_for_match(name).split()
    return parts[-1] if parts else ""


def _names_match(start_name: str, dg_name: str) -> bool:
    """Check if a Start name matches a DG name.

    Handles case differences and minor format variations.
    Uses last name exact match + overall similarity.
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
