from __future__ import annotations

"""
Parser for Start sportsbook outright odds (copy-pasted from browser).

Takes raw text from the Start outrights page and extracts player odds
for win, top 10, top 20, and make-cut markets.

Usage:
    from src.parsers.start_outrights import parse_start_outrights

    text = open("start_paste.txt").read()
    outrights = parse_start_outrights(text)
    # {"win": [{"name": "Scottie Scheffler", "odds": "+485"}, ...],
    #  "t10": [...], "t20": [...], "make_cut": [...]}
"""

import re


# Header patterns that identify each market section
_MARKET_PATTERNS = [
    ("win", re.compile(r"ODDS TO WIN", re.IGNORECASE)),
    ("t10", re.compile(r"TOP 10 FINISH", re.IGNORECASE)),
    ("t20", re.compile(r"TOP 20 FINISH", re.IGNORECASE)),
    ("make_cut", re.compile(r"TO MAKE THE CUT", re.IGNORECASE)),
]

# Line pattern: number, player name, odds
_LINE_RE = re.compile(
    r"(\d{4,5})\s+"       # bet number
    r"(.+?)\s+"            # player name
    r"([+-]\d{2,5})\s*$",  # American odds
)


def _clean_name(raw: str) -> str:
    """Convert 'SCOTTIE SCHEFFLER' -> 'Scottie Scheffler'."""
    raw = raw.strip()
    parts = raw.split()
    result = []
    for part in parts:
        upper = part.upper()
        if upper in ("II", "III", "IV", "JR", "JR.", "SR", "SR."):
            result.append(upper if not upper.endswith(".") else part.title())
        elif upper == "J.J.":
            result.append("J.J.")
        elif "." in part and len(part) <= 4:
            result.append(part.upper())
        else:
            result.append(part.title())
    return " ".join(result)


def _detect_market(line: str) -> str | None:
    """Check if a line is a market header and return the market type."""
    for market_type, pattern in _MARKET_PATTERNS:
        if pattern.search(line):
            return market_type
    return None


def parse_start_outrights(text: str) -> dict[str, list[dict]]:
    """Parse copy-pasted Start outright text into structured records.

    Args:
        text: Raw text containing one or more outright market sections.

    Returns:
        Dict mapping market type to list of player records:
        {"win": [{"name": "Scottie Scheffler", "odds": "+485"}, ...], ...}
        Only markets found in the text are included.
    """
    lines = text.splitlines()
    results: dict[str, list[dict]] = {}
    current_market: str | None = None

    for line in lines:
        # Check for market header
        detected = _detect_market(line)
        if detected is not None:
            current_market = detected
            if current_market not in results:
                results[current_market] = []
            continue

        if current_market is None:
            continue

        # Try to parse a player line
        m = _LINE_RE.match(line.strip())
        if m:
            name = _clean_name(m.group(2))
            odds = m.group(3)
            results[current_market].append({
                "name": name,
                "odds": odds,
            })

    return results


def parse_start_outrights_from_file(filepath: str) -> dict[str, list[dict]]:
    """Convenience: read a file and parse it."""
    with open(filepath, "r", encoding="utf-8") as f:
        return parse_start_outrights(f.read())
