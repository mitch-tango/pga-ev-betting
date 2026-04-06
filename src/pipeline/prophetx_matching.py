"""ProphetX tournament matching, market classification, and player extraction.

Matches ProphetX prediction market events to DataGolf tournaments,
classifies markets by type, and extracts player names from ProphetX
market data. Handles ProphetX's uncertain field names with flexible
field detection.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher

from src.normalize.players import resolve_player

logger = logging.getLogger(__name__)

# Explicit exclusions for non-PGA tours
_NON_PGA_EXCLUSIONS = ["liv", "dpwt", "dp world", "lpga", "korn ferry"]

# Tournament name aliases — prediction markets often use different names than DG.
_TOURNAMENT_ALIASES = {
    "masters tournament": ["augusta national invitational", "the masters", "masters"],
    "the open championship": ["open championship", "british open"],
    "u.s. open": ["us open"],
    "the players championship": ["players championship", "tpc sawgrass"],
}

# Strip common prefixes/suffixes before fuzzy comparison
_TITLE_PREFIX_PATTERN = re.compile(r"^pga\s+tour:\s*", re.IGNORECASE)
_TITLE_SUFFIX_PATTERN = re.compile(r"\s+(?:winner|top\s+\d+)\s*$", re.IGNORECASE)

# Player name field candidates (ordered by likelihood)
_NAME_FIELDS = ("competitor_name", "participant", "player", "name", "playerName")

# Competitors list field candidates
_COMPETITORS_FIELDS = ("competitors", "participants", "selections")

# Date field candidates for start
_START_DATE_FIELDS = ("start_date", "startDate", "event_date", "start", "scheduled")
# Date field candidates for end
_END_DATE_FIELDS = ("end_date", "endDate", "event_end_date", "end", "scheduled")
# Title field candidates
_TITLE_FIELDS = ("name", "title", "event_name", "eventName")


def _get_field(d: dict, *field_names: str, default=None):
    """Try each field name, return first non-None value."""
    for name in field_names:
        val = d.get(name)
        if val is not None:
            return val
    return default


def _parse_date(date_str: str) -> date:
    """Parse a date string into a date object."""
    if "T" in date_str:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
    return date.fromisoformat(date_str)


def _is_pga_event(title: str) -> bool:
    """Check if event is acceptable (not from an excluded tour)."""
    title_lower = title.lower()
    return not any(exclusion in title_lower for exclusion in _NON_PGA_EXCLUSIONS)


def _clean_name(name: str) -> str:
    """Clean and NFC-normalize a player name."""
    name = name.strip().rstrip("?").strip()
    name = unicodedata.normalize("NFC", name)
    return name


def _extract_name_from_entry(entry: dict) -> str | None:
    """Extract player name from a competitor/participant dict."""
    name = _get_field(entry, *_NAME_FIELDS)
    if name and isinstance(name, str):
        return _clean_name(name)
    return None


def match_tournament(
    events: list[dict],
    tournament_name: str,
    tournament_start: str,
    tournament_end: str,
) -> dict | None:
    """Find the ProphetX event matching the current DG tournament.

    Handles multiple field name variants for dates and titles.
    Uses date range overlap + fuzzy name matching.

    Returns full event dict, or None if no match.
    """
    start_date = _parse_date(tournament_start)
    end_date = _parse_date(tournament_end)
    tourney_lower = tournament_name.lower().strip()

    # Build list of names to match against (primary + aliases)
    match_names = [tourney_lower]
    match_names.extend(_TOURNAMENT_ALIASES.get(tourney_lower, []))

    def _name_score(event: dict) -> float:
        title = _get_field(event, *_TITLE_FIELDS, default="")
        title_lower = title.lower()
        cleaned = _TITLE_PREFIX_PATTERN.sub("", title_lower)
        cleaned = _TITLE_SUFFIX_PATTERN.sub("", cleaned).strip()

        best = 0.0
        for name in match_names:
            if name in title_lower:
                best = max(best, 1.0)
            score = SequenceMatcher(None, name, cleaned).ratio()
            best = max(best, score)
        # Tiebreaker: prefer events with "winner" in the title (outright markets)
        if "winner" in title_lower:
            best += 0.1
        return best

    # Pass 1: date range overlap — prefer best name match
    date_candidates = []
    for event in events:
        title = _get_field(event, *_TITLE_FIELDS, default="")
        if not _is_pga_event(title):
            continue

        event_start_str = _get_field(event, *_START_DATE_FIELDS)
        event_end_str = _get_field(event, *_END_DATE_FIELDS)
        if not event_start_str or not event_end_str:
            continue

        try:
            event_start = _parse_date(str(event_start_str))
            event_end = _parse_date(str(event_end_str))
        except (ValueError, TypeError):
            continue

        if event_start <= end_date and event_end >= start_date:
            score = _name_score(event)
            date_candidates.append((score, event))

    if date_candidates:
        date_candidates.sort(key=lambda x: x[0], reverse=True)
        return date_candidates[0][1]

    # Pass 2: fuzzy name fallback
    best_match = None
    best_score = 0.0

    for event in events:
        title = _get_field(event, *_TITLE_FIELDS, default="")
        if not _is_pga_event(title):
            continue

        score = _name_score(event)
        if score > best_score:
            best_score = score
            best_match = event

    if best_match and best_score >= 0.85:
        return best_match

    return None


def classify_markets(markets: list[dict]) -> dict[str, list[dict]]:
    """Classify ProphetX markets by type.

    Returns sparse dict: {"win": [...], "matchup": [...], "t10": [...], etc.}

    ProphetX market structure:
    - ``type`` = "moneyline" for outright winner, "custom" for props
    - ``name`` = player name (for outrights) or market title
    - ``selections`` = [[YES levels], [NO levels]] orderbook
    - ``outcomes`` = [{"id":1,"name":"YES"}, {"id":2,"name":"NO"}]
    """
    result: dict[str, list[dict]] = {}

    for market in markets:
        market_type = str(market.get("market_type", market.get("type", ""))).lower()
        sub_type = str(market.get("sub_type", "")).lower()
        name = str(market.get("name", "")).lower()

        classified = None

        # Check for top 10/20 first (more specific)
        if "top 10" in name or "top-10" in name or "top 10" in sub_type or "top-10" in sub_type:
            classified = "t10"
        elif "top 20" in name or "top-20" in name or "top 20" in sub_type or "top-20" in sub_type:
            classified = "t20"
        elif "cut" in name:
            classified = "make_cut"
        elif "matchup" in sub_type:
            classified = "matchup"
        elif market_type == "moneyline" and "outright" in sub_type:
            classified = "win"
        elif market_type == "moneyline":
            # ProphetX moneyline markets from a "Tournament Winner" event
            # are individual player outrights (YES/NO binary contracts).
            # Matchups come from separate "Matchups" events with 2 named outcomes.
            outcomes = market.get("outcomes", [])
            outcome_names = {str(o.get("name", "")).upper() for o in outcomes} if isinstance(outcomes, list) else set()
            if outcome_names == {"YES", "NO"}:
                classified = "win"

        if classified:
            result.setdefault(classified, []).append(market)
        else:
            logger.debug("ProphetX: unrecognized market type=%s sub=%s name='%s'",
                         market_type, sub_type, name)

    return result


def extract_player_name_outright(market: dict) -> str | None:
    """Extract player name from an outright market.

    ProphetX outright markets use the ``name`` field directly as the player
    name (e.g., "Scottie Scheffler"). Falls back to competitor entries and
    other field names for forward-compatibility.
    """
    # Primary: ProphetX uses market["name"] as the player name for outrights
    market_name = market.get("name")
    if market_name and isinstance(market_name, str):
        # Sanity check: skip names that look like event titles rather than players
        lower = market_name.lower()
        if not any(kw in lower for kw in ("tournament", "top 10", "top 20",
                                           "top 5", "winner", "matchup",
                                           "bogey", "hole in one", "will ")):
            return _clean_name(market_name)

    # Fallback: try competitor/participant entries
    competitors = _get_field(market, *_COMPETITORS_FIELDS, default=[])
    if isinstance(competitors, list) and competitors:
        first = competitors[0]
        if isinstance(first, dict):
            name = _extract_name_from_entry(first)
            if name:
                return name

    # Last resort: other name fields
    for field in ("competitor_name", "participant", "player", "playerName"):
        val = market.get(field)
        if val and isinstance(val, str):
            return _clean_name(val)

    logger.warning("ProphetX: could not extract player name from market: %s",
                   {k: v for k, v in market.items() if k != "selections"})
    return None


def extract_player_names_matchup(market: dict) -> tuple[str, str] | None:
    """Extract both player names from a H2H matchup market.

    Requires exactly 2 competitors. Returns (player_a, player_b) or None.
    """
    competitors = _get_field(market, *_COMPETITORS_FIELDS, default=[])
    if not isinstance(competitors, list) or len(competitors) != 2:
        return None

    name_a = _extract_name_from_entry(competitors[0])
    name_b = _extract_name_from_entry(competitors[1])

    if name_a and name_b:
        return (name_a, name_b)

    logger.warning("ProphetX: could not extract matchup names from: %s", market)
    return None


def resolve_prophetx_player(
    name: str,
    auto_create: bool = False,
) -> dict | None:
    """Resolve a ProphetX player name to a canonical DG player record.

    Delegates to resolve_player() with source="prophetx".
    """
    return resolve_player(name, source="prophetx", auto_create=auto_create)
