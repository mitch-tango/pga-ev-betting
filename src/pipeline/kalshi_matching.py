"""Kalshi tournament matching and player name extraction.

Matches Kalshi prediction market events to DataGolf tournaments by date
and fuzzy name, and extracts/resolves player names from contract titles.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from src.normalize.players import resolve_player

logger = logging.getLogger(__name__)

# PGA safety check — event title must contain one of these
_PGA_INDICATORS = [
    "pga", "masters", "u.s. open", "us open", "open championship",
    "pga championship",
]

# Common prefixes/suffixes in Kalshi titles to strip before fuzzy comparison
_TITLE_STRIP_PATTERNS = re.compile(
    r"^(?:pga\s+tour:\s*)|(?:\s+winner\s*$)|(?:\s+top\s+\d+\s*$)",
    re.IGNORECASE,
)


def _is_pga_event(title: str) -> bool:
    """Check if event title indicates a PGA Tour event."""
    title_lower = title.lower()
    return any(indicator in title_lower for indicator in _PGA_INDICATORS)


def match_tournament(
    kalshi_events: list[dict],
    tournament_name: str,
    tournament_start: str,
    tournament_end: str,
) -> str | None:
    """Find the Kalshi event ticker matching the current DG tournament.

    Matching strategy:
    1. Date-based: event expiration within [start, end + 1 day]
    2. Fuzzy name fallback: substring or SequenceMatcher on title
    3. Safety check: reject non-PGA events

    Returns event_ticker string, or None if no match found.
    """
    start_date = datetime.fromisoformat(tournament_start).date()
    end_date = datetime.fromisoformat(tournament_end).date()
    end_date_padded = end_date + timedelta(days=1)

    # Normalize tournament name for comparison
    tourney_lower = tournament_name.lower().strip()

    # Pass 1: date-based matching
    for event in kalshi_events:
        if not _is_pga_event(event.get("title", "")):
            continue

        exp_str = event.get("expected_expiration_time", "")
        if not exp_str:
            continue

        try:
            exp_date = datetime.fromisoformat(exp_str.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            continue

        if start_date <= exp_date <= end_date_padded:
            ticker = event.get("event_ticker")
            if ticker:
                return ticker

    # Pass 2: fuzzy name fallback (only PGA events)
    best_match = None
    best_score = 0.0

    for event in kalshi_events:
        if not _is_pga_event(event.get("title", "")):
            continue

        title_lower = event.get("title", "").lower()

        # Substring check
        if tourney_lower in title_lower:
            ticker = event.get("event_ticker")
            if ticker:
                return ticker

        # Strip common prefixes/suffixes before fuzzy comparison
        cleaned_title = _TITLE_STRIP_PATTERNS.sub("", title_lower).strip()
        score = SequenceMatcher(None, tourney_lower, cleaned_title).ratio()
        if score > best_score:
            best_score = score
            best_match = event

    if best_match and best_score >= 0.7:
        return best_match.get("event_ticker")

    return None


def match_all_series(
    client,
    tournament_name: str,
    tournament_start: str,
    tournament_end: str,
    series_tickers: dict[str, str],
) -> dict[str, str]:
    """Match all Kalshi series to the current tournament.

    Returns {"win": "KXPGATOUR-...", "t10": "KXPGATOP10-...", ...}
    with only successfully matched entries.
    """
    matched = {}
    for market_type, series_ticker in series_tickers.items():
        try:
            events = client.get_golf_events(series_ticker)
        except Exception:
            logger.warning("Failed to fetch Kalshi events for %s", series_ticker)
            continue

        ticker = match_tournament(events, tournament_name, tournament_start, tournament_end)
        if ticker:
            matched[market_type] = ticker
        else:
            logger.info("No Kalshi match for %s (%s)", market_type, series_ticker)

    return matched


# --- Player Name Extraction ---

# Patterns for outright contracts
_OUTRIGHT_PATTERNS = [
    re.compile(r"^Will\s+(.+?)\s+(?:win|finish)\b", re.IGNORECASE),
    re.compile(r"^(.+?)\s+to\s+(?:win|finish)\b", re.IGNORECASE),
]

# Patterns for H2H contracts
_H2H_PATTERNS = [
    re.compile(r"^(.+?)\s+vs\.?\s+(.+?)(?:\s*\?)?$", re.IGNORECASE),
    re.compile(r"^Will\s+(.+?)\s+beat\s+(.+?)(?:\s+(?:in|at|during)\b.*)?\s*\??$", re.IGNORECASE),
]


def _clean_name(name: str) -> str:
    """Clean and NFC-normalize a player name."""
    name = name.strip().rstrip("?").strip()
    name = unicodedata.normalize("NFC", name)
    return name


def extract_player_name_outright(contract: dict) -> str | None:
    """Extract player name from a Kalshi outright contract.

    Tries subtitle first (often just the player name), then title patterns.
    """
    subtitle = contract.get("subtitle", "").strip()
    if subtitle and not any(kw in subtitle.lower() for kw in ["win", "finish", "top", "vs"]):
        return _clean_name(subtitle)

    title = contract.get("title", "")
    for pattern in _OUTRIGHT_PATTERNS:
        m = pattern.match(title)
        if m:
            return _clean_name(m.group(1))

    logger.warning("Could not extract player name from outright contract: %s", title)
    return None


def extract_player_names_h2h(contract: dict) -> tuple[str, str] | None:
    """Extract both player names from a Kalshi H2H contract.

    Returns (player_a, player_b) or None if unparseable.
    """
    title = contract.get("title", "")
    for pattern in _H2H_PATTERNS:
        m = pattern.match(title)
        if m:
            return (_clean_name(m.group(1)), _clean_name(m.group(2)))

    logger.warning("Could not extract player names from H2H contract: %s", title)
    return None


# --- Player Name Resolution ---

def resolve_kalshi_player(
    kalshi_name: str,
    auto_create: bool = False,
) -> dict | None:
    """Resolve a Kalshi player name to a canonical DG player record.

    Delegates to resolve_player() with source="kalshi".
    """
    return resolve_player(kalshi_name, source="kalshi", auto_create=auto_create)
