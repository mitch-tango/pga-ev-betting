"""Polymarket tournament matching and player name extraction.

Matches Polymarket prediction market events to DataGolf tournaments by
UTC date range overlap and fuzzy name, and extracts/resolves player names
from Polymarket market data (slug-based and regex-based).

Follows the same architectural pattern as kalshi_matching.py but adapts
for Polymarket-specific data structures.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher

import config
from src.normalize.players import resolve_player

logger = logging.getLogger(__name__)

# Explicit exclusions for non-PGA tours
_NON_PGA_EXCLUSIONS = ["liv", "dpwt", "lpga", "korn ferry"]

# Strip common prefixes before fuzzy comparison
_TITLE_PREFIX_PATTERN = re.compile(r"^pga\s+tour:\s*", re.IGNORECASE)
# Strip common suffixes before fuzzy comparison
_TITLE_SUFFIX_PATTERN = re.compile(r"\s+(?:winner|top\s+\d+)\s*$", re.IGNORECASE)

# Question-based player extraction patterns
_QUESTION_PATTERNS = [
    re.compile(r"^Will\s+(.+?)\s+(?:win|finish)\b", re.IGNORECASE),
    re.compile(r"^(.+?)\s+to\s+(?:win|finish)\b", re.IGNORECASE),
]


def _parse_date(date_str: str) -> date:
    """Parse a date string into a date object.

    Handles both "2026-04-10T00:00:00Z" and "2026-04-10" formats.
    """
    if "T" in date_str:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
    return date.fromisoformat(date_str)


def _is_pga_event(title: str) -> bool:
    """Check if event is acceptable (not from an excluded tour).

    Accepts any event NOT from LIV, DPWT, LPGA, or Korn Ferry.
    """
    title_lower = title.lower()
    return not any(exclusion in title_lower for exclusion in _NON_PGA_EXCLUSIONS)


def _clean_name(name: str) -> str:
    """Clean and NFC-normalize a player name."""
    name = name.strip().rstrip("?").strip()
    name = unicodedata.normalize("NFC", name)
    return name


def match_tournament(
    events: list[dict],
    tournament_name: str,
    tournament_start: str,
    tournament_end: str,
) -> dict | None:
    """Find the Polymarket event matching the current DG tournament.

    Matching strategy:
    1. Date-based: UTC date range overlap (event_start <= tourn_end AND event_end >= tourn_start)
    2. Fuzzy name fallback: token-based similarity ≥ 0.85
    3. Safety check: reject non-PGA events

    Returns full event dict (with nested markets[]), or None if no match.
    """
    start_date = _parse_date(tournament_start)
    end_date = _parse_date(tournament_end)

    tourney_lower = tournament_name.lower().strip()

    def _name_score(title: str) -> float:
        """Score how well an event title matches the tournament name."""
        title_lower = title.lower()
        if tourney_lower in title_lower:
            return 1.0
        cleaned = _TITLE_PREFIX_PATTERN.sub("", title_lower)
        cleaned = _TITLE_SUFFIX_PATTERN.sub("", cleaned).strip()
        return SequenceMatcher(None, tourney_lower, cleaned).ratio()

    # Pass 1: date range overlap — prefer best name match among overlapping
    date_candidates = []
    for event in events:
        if not _is_pga_event(event.get("title", "")):
            continue

        event_start_str = event.get("startDate", "")
        event_end_str = event.get("endDate", "")
        if not event_start_str or not event_end_str:
            continue

        try:
            event_start = _parse_date(event_start_str)
            event_end = _parse_date(event_end_str)
        except (ValueError, TypeError):
            continue

        if event_start <= end_date and event_end >= start_date:
            score = _name_score(event.get("title", ""))
            date_candidates.append((score, event))

    if date_candidates:
        date_candidates.sort(key=lambda x: x[0], reverse=True)
        return date_candidates[0][1]

    # Pass 2: fuzzy name fallback
    best_match = None
    best_score = 0.0

    for event in events:
        if not _is_pga_event(event.get("title", "")):
            continue

        score = _name_score(event.get("title", ""))
        if score > best_score:
            best_score = score
            best_match = event

    if best_match and best_score >= 0.85:
        return best_match

    return None


def match_all_market_types(
    client,
    tournament_name: str,
    tournament_start: str,
    tournament_end: str,
) -> dict[str, dict]:
    """Match all Polymarket market types to the current tournament.

    Iterates config.POLYMARKET_MARKET_TYPES. For each type, fetches events
    and attempts tournament matching.

    Returns {"win": event_dict, "t10": event_dict, ...} with only matched entries.
    """
    matched = {}
    for market_type, filter_value in config.POLYMARKET_MARKET_TYPES.items():
        try:
            events = client.get_golf_events(market_type_filter=filter_value)
        except Exception:
            logger.warning("Failed to fetch Polymarket events for %s", market_type)
            continue

        event = match_tournament(events, tournament_name, tournament_start, tournament_end)
        if event:
            matched[market_type] = event
        else:
            logger.info("No Polymarket match for %s (%s)", market_type, filter_value)

    return matched


def extract_player_name(market: dict, event_slug: str = "") -> str | None:
    """Extract player name from a Polymarket market dict.

    Priority order:
    1. groupItemTitle (most reliable when present)
    2. Slug-based: strip event prefix from market slug, convert hyphens to spaces
    3. Question regex: "Will X win..." patterns

    Returns cleaned, NFC-normalized name or None.
    """
    # 1. groupItemTitle — often just the player name
    group_title = market.get("groupItemTitle", "").strip()
    if group_title and not re.search(
        r"\b(?:win|finish|top|yes|no)\b", group_title, re.IGNORECASE
    ):
        return _clean_name(group_title)

    # 2. Slug-based extraction (only when slug starts with event prefix)
    market_slug = market.get("slug", "")
    if market_slug and event_slug and market_slug.startswith(event_slug):
        player_part = market_slug[len(event_slug):].lstrip("-")
        if player_part:
            name = player_part.replace("-", " ").strip()
            if name and len(name) > 1:
                name = name.title()
                return _clean_name(name)

    # 3. Question regex
    question = market.get("question", "")
    for pattern in _QUESTION_PATTERNS:
        m = pattern.match(question)
        if m:
            return _clean_name(m.group(1))

    logger.warning("Could not extract player name from Polymarket market: %s", market.get("slug", ""))
    return None


def resolve_polymarket_player(
    name: str,
    auto_create: bool = False,
) -> dict | None:
    """Resolve a Polymarket player name to a canonical DG player record.

    Delegates to resolve_player() with source="polymarket".
    """
    return resolve_player(name, source="polymarket", auto_create=auto_create)
