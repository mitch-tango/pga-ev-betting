from __future__ import annotations

"""
Parser for Start sportsbook matchup odds (copy-pasted from browser).

Takes raw text copied from the Start matchups page and extracts
player pairs with moneyline odds. Handles round matchups and
tournament matchups.

Usage:
    from src.parsers.start_matchups import parse_start_matchups

    text = open("start_paste.txt").read()
    matchups = parse_start_matchups(text)
    # [{"p1_name": "Si Woo Kim", "p2_name": "Michael Thorbjornsen",
    #   "p1_odds": "-155", "p2_odds": "+135", "round_number": 2}, ...]
"""

import re


def _clean_player_name(raw: str) -> str:
    """Convert 'SI WOO KIM (2RD)' -> 'Si Woo Kim'.

    Strips round indicators like (2RD), (3RD), (1ST), (4TH),
    trailing whitespace, and converts to title case.
    """
    # Remove round indicator parenthetical
    name = re.sub(r"\s*\(\d+\w{0,2}\)\s*$", "", raw.strip())
    # Title case, but handle suffixes like "III", "Jr", "II"
    parts = name.split()
    result = []
    for part in parts:
        upper = part.upper()
        if upper in ("II", "III", "IV", "JR", "JR.", "SR", "SR."):
            result.append(upper if not upper.endswith(".") else part.title())
        else:
            result.append(part.title())
    return " ".join(result)


def _extract_round_number(text: str) -> int | None:
    """Extract round number from header text like 'ROUND 2 MATCHUPS'."""
    m = re.search(r"ROUND\s+(\d)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _parse_line(line: str) -> dict | None:
    """Parse a single player line from Start matchup text.

    Expected patterns:
        '     Apr 03    7239    SI WOO KIM (2RD)    -155         -½-125'
        '     11:30 AM    7240    MICHAEL THORBJORNSEN (2RD)    +135         +½-105'

    Returns:
        {"number": 7239, "name": "Si Woo Kim", "moneyline": "-155"} or None
    """
    # Match: optional date/time, then 4-digit number, then player name + odds
    # The number is always 4 digits; moneyline is +/- followed by digits
    m = re.search(
        r"(\d{4,5})\s+"           # bet number (4-5 digits)
        r"(.+?)\s+"               # player name (greedy but stops at odds)
        r"([+-]\d{3,4})\s",       # moneyline odds (+135, -155)
        line,
    )
    if not m:
        return None

    number = int(m.group(1))
    raw_name = m.group(2).strip()
    moneyline = m.group(3)

    name = _clean_player_name(raw_name)
    if not name:
        return None

    return {"number": number, "name": name, "moneyline": moneyline}


def parse_start_matchups(text: str) -> list[dict]:
    """Parse copy-pasted Start matchup text into structured matchup records.

    Args:
        text: Raw text copied from Start sportsbook matchups page.

    Returns:
        List of matchup dicts, each with:
            p1_name: str — first player (title case)
            p2_name: str — second player (title case)
            p1_odds: str — American odds for p1 (e.g., "-155")
            p2_odds: str — American odds for p2 (e.g., "+135")
            round_number: int | None — round if detected from headers
    """
    lines = text.splitlines()

    # Detect round number from headers
    round_number = None
    for line in lines:
        rn = _extract_round_number(line)
        if rn is not None:
            round_number = rn
            break

    # Parse all player lines
    parsed_players = []
    for line in lines:
        result = _parse_line(line)
        if result:
            parsed_players.append(result)

    # Pair consecutive players into matchups
    # Start lists them in pairs: odd index = p1, even index = p2
    # (consecutive bet numbers like 7239/7240)
    matchups = []
    i = 0
    while i + 1 < len(parsed_players):
        p1 = parsed_players[i]
        p2 = parsed_players[i + 1]

        # Verify they're a pair (consecutive numbers)
        if abs(p1["number"] - p2["number"]) == 1:
            matchups.append({
                "p1_name": p1["name"],
                "p2_name": p2["name"],
                "p1_odds": p1["moneyline"],
                "p2_odds": p2["moneyline"],
                "round_number": round_number,
            })
            i += 2
        else:
            # Skip orphan line
            i += 1

    return matchups


def parse_start_matchups_from_file(filepath: str) -> list[dict]:
    """Convenience: read a file and parse it."""
    with open(filepath, "r", encoding="utf-8") as f:
        return parse_start_matchups(f.read())
