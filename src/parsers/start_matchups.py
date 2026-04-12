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
        r"([+-]\d{3,4})(?:\s|$)",  # moneyline odds (+135, -155)
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


_STOP_PATTERNS = re.compile(
    r"(ODDS TO WIN|TOP \d+ FINISH|TO MAKE.*CUT|TOP \d+\s*\(INCLUDING)",
    re.IGNORECASE,
)


_TOURNAMENT_MATCHUP_RE = re.compile(
    r"TOURNAMENT\s+MATCHUP", re.IGNORECASE,
)

_ROUND_MATCHUP_RE = re.compile(
    r"ROUND\s+(\d)\s+MATCHUP", re.IGNORECASE,
)


def parse_start_matchups(text: str) -> list[dict]:
    """Parse copy-pasted Start matchup text into structured matchup records.

    Tracks round_number per section: tournament matchup headers set
    round_number=None, round matchup headers (e.g. "ROUND 1 MATCHUPS")
    set round_number to the detected round.

    Args:
        text: Raw text copied from Start sportsbook matchups page.
              May contain outright sections after the matchup section;
              parsing stops at the first non-matchup header.

    Returns:
        List of matchup dicts, each with:
            p1_name: str — first player (title case)
            p2_name: str — second player (title case)
            p1_odds: str — American odds for p1 (e.g., "-155")
            p2_odds: str — American odds for p2 (e.g., "+135")
            round_number: int | None — None for tournament matchups,
                integer for round matchups
    """
    lines = text.splitlines()

    # Parse player lines with per-section round tracking
    parsed_players = []  # list of (player_dict, round_number)
    in_matchup_section = False
    current_round: int | None = None

    for line in lines:
        upper_line = line.upper()

        # Detect matchup section headers and update round context
        if "MATCHUP" in upper_line:
            in_matchup_section = True

            # Check for round matchup header first (more specific)
            rm = _ROUND_MATCHUP_RE.search(line)
            if rm:
                current_round = int(rm.group(1))
            elif _TOURNAMENT_MATCHUP_RE.search(line):
                current_round = None

        # Stop at outright/placement section headers
        if in_matchup_section and _STOP_PATTERNS.search(line):
            break

        result = _parse_line(line)
        if result:
            parsed_players.append((result, current_round))

    # Pair consecutive players into matchups
    # Start lists them in pairs: odd index = p1, even index = p2
    # (consecutive bet numbers like 7239/7240)
    matchups = []
    i = 0
    while i + 1 < len(parsed_players):
        p1, p1_round = parsed_players[i]
        p2, p2_round = parsed_players[i + 1]

        # Verify they're a pair (consecutive numbers)
        if abs(p1["number"] - p2["number"]) == 1:
            matchups.append({
                "p1_name": p1["name"],
                "p2_name": p2["name"],
                "p1_odds": p1["moneyline"],
                "p2_odds": p2["moneyline"],
                "round_number": p1_round,
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
