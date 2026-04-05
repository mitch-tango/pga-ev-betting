"""ProphetX prediction market odds pull & merge.

Pulls outrights (win, t10, t20) and H2H matchups from ProphetX,
with format-aware handling for American vs binary odds.
"""

from __future__ import annotations

import logging
import re

import config
from src.api.prophetx import ProphetXClient
from src.core.devig import binary_midpoint, binary_price_to_american, parse_american_odds
from src.pipeline.prophetx_matching import (
    classify_markets,
    extract_player_name_outright,
    extract_player_names_matchup,
    match_tournament,
    resolve_prophetx_player,
)

logger = logging.getLogger(__name__)

# DG uses "top_10"/"top_20"; ProphetX classification uses "t10"/"t20"
_DG_TO_PROPHETX_MARKET = {"win": "win", "top_10": "t10", "top_20": "t20"}

_AMERICAN_STR_RE = re.compile(r"^[+-]\d+$")


def _detect_odds_format(markets: list[dict], odds_key: str = "odds") -> str:
    """Detect whether markets use American or binary odds format.

    Samples the first valid odds value found:
    - int/float with abs > 1 → american (e.g. 400, -150)
    - string matching [+-]digits → american (e.g. "+400")
    - float in (0, 1) exclusive → binary
    - Default: binary
    """
    for market in markets:
        # Check competitor-level odds first
        competitors = market.get("competitors", market.get("participants", market.get("selections", [])))
        if isinstance(competitors, list):
            for comp in competitors:
                val = comp.get(odds_key)
                if val is not None:
                    return _classify_odds_value(val)

        # Check market-level odds
        val = market.get(odds_key)
        if val is not None:
            return _classify_odds_value(val)

    return "binary"


def _classify_odds_value(val) -> str:
    """Classify a single odds value as american or binary."""
    if isinstance(val, str):
        return "american" if _AMERICAN_STR_RE.match(val.strip()) else "binary"
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return "american" if abs(val) > 1 else "binary"
    return "binary"


def _get_odds_value(entry: dict, key: str = "odds"):
    """Extract odds value from a competitor/market entry."""
    return entry.get(key)


def _american_to_prob(odds_val) -> float | None:
    """Convert an American odds value (int or string) to implied probability."""
    if isinstance(odds_val, int):
        odds_str = f"+{odds_val}" if odds_val > 0 else str(odds_val)
    elif isinstance(odds_val, str):
        odds_str = odds_val.strip()
    else:
        return None
    return parse_american_odds(odds_str)


def _american_to_string(odds_val) -> str:
    """Convert American odds value to display string."""
    if isinstance(odds_val, int):
        return f"+{odds_val}" if odds_val > 0 else str(odds_val)
    if isinstance(odds_val, str):
        return odds_val.strip()
    return str(odds_val)


def pull_prophetx_outrights(
    tournament_name: str,
    tournament_start: str,
    tournament_end: str,
    tournament_slug: str | None = None,
) -> dict[str, list[dict]]:
    """Pull ProphetX outright odds for win, t10, t20.

    Returns {"win": [...], "t10": [...], "t20": [...]} with format-aware
    player dicts. Empty dict on failure or no match.
    """
    try:
        client = ProphetXClient()
        events = client.get_golf_events()

        matched = match_tournament(events, tournament_name, tournament_start, tournament_end)
        if not matched:
            logger.info("ProphetX: no tournament match for '%s'", tournament_name)
            return {}

        event_id = matched.get("id") or matched.get("event_id")
        if not event_id:
            logger.warning("ProphetX: matched event has no id field")
            return {}

        all_markets = client.get_markets_for_events([str(event_id)])
        classified = classify_markets(all_markets)

        results: dict[str, list[dict]] = {}

        for market_type in ("win", "t10", "t20"):
            type_markets = classified.get(market_type, [])
            if not type_markets:
                continue

            odds_format = _detect_odds_format(type_markets)
            players = []

            for market in type_markets:
                competitors = market.get("competitors",
                              market.get("participants",
                              market.get("selections", [])))
                if not isinstance(competitors, list):
                    competitors = [market]

                for comp in competitors:
                    name = extract_player_name_outright(
                        {"competitors": [comp]} if comp is not market else market,
                    )
                    if not name:
                        continue

                    odds_val = _get_odds_value(comp)
                    if odds_val is None:
                        continue

                    # Quality filters — skip filter if field absent
                    oi = comp.get("open_interest")
                    if oi is not None and isinstance(oi, (int, float)) and oi < config.PROPHETX_MIN_OPEN_INTEREST:
                        continue

                    bid = comp.get("bid")
                    ask = comp.get("ask")
                    if (bid is not None and ask is not None
                            and isinstance(bid, (int, float)) and isinstance(ask, (int, float))):
                        spread = abs(ask - bid)
                        if spread > config.PROPHETX_MAX_SPREAD:
                            continue

                    # Resolve canonical name
                    resolved = resolve_prophetx_player(name)
                    canonical = resolved["canonical_name"] if resolved else name

                    if odds_format == "american":
                        american_str = _american_to_string(odds_val)
                        prob = _american_to_prob(odds_val)
                        if prob is None or prob <= 0 or prob >= 1:
                            continue
                        players.append({
                            "player_name": canonical,
                            "prophetx_american": american_str,
                            "prophetx_mid_prob": prob,
                            "odds_format": "american",
                        })
                    else:
                        # Binary format — use binary_midpoint for validation
                        bid_s = str(bid) if bid is not None else None
                        ask_s = str(ask) if ask is not None else None

                        midpoint = binary_midpoint(bid_s, ask_s) if bid_s and ask_s else None
                        if midpoint is None:
                            # Fall back to odds value as midpoint estimate
                            try:
                                midpoint = float(odds_val)
                            except (ValueError, TypeError):
                                midpoint = None

                        ask_f = float(ask) if ask is not None else None

                        if midpoint is None or midpoint <= 0 or midpoint >= 1:
                            continue

                        american_str = binary_price_to_american(str(midpoint))
                        if not american_str:
                            continue

                        player_dict = {
                            "player_name": canonical,
                            "prophetx_mid_prob": midpoint,
                            "odds_format": "binary",
                        }
                        if ask_f is not None and 0 < ask_f < 1:
                            player_dict["prophetx_ask_prob"] = ask_f

                        players.append(player_dict)

            if players:
                results[market_type] = players

        # Cache raw responses
        if results and tournament_slug:
            try:
                client._cache_response(results, "prophetx_outrights", tournament_slug)
            except Exception:
                logger.debug("ProphetX: cache write failed", exc_info=True)

        return results

    except Exception:
        logger.warning("ProphetX: outrights pull failed", exc_info=True)
        return {}


def pull_prophetx_matchups(
    tournament_name: str,
    tournament_start: str,
    tournament_end: str,
    tournament_slug: str | None = None,
) -> list[dict]:
    """Pull ProphetX H2H matchup odds.

    Returns list of {p1_name, p2_name, p1_prob, p2_prob} dicts.
    Empty list on failure or no match.
    """
    try:
        client = ProphetXClient()
        events = client.get_golf_events()

        matched = match_tournament(events, tournament_name, tournament_start, tournament_end)
        if not matched:
            return []

        event_id = matched.get("id") or matched.get("event_id")
        if not event_id:
            return []

        all_markets = client.get_markets_for_events([str(event_id)])
        classified = classify_markets(all_markets)

        matchup_markets = classified.get("matchup", [])
        if not matchup_markets:
            return []

        odds_format = _detect_odds_format(matchup_markets)
        matchups = []

        for market in matchup_markets:
            names = extract_player_names_matchup(market)
            if not names:
                continue

            name_a, name_b = names
            competitors = market.get("competitors",
                          market.get("participants",
                          market.get("selections", [])))
            if not isinstance(competitors, list) or len(competitors) != 2:
                continue

            odds_a = _get_odds_value(competitors[0])
            odds_b = _get_odds_value(competitors[1])
            if odds_a is None or odds_b is None:
                continue

            if odds_format == "american":
                prob_a = _american_to_prob(odds_a)
                prob_b = _american_to_prob(odds_b)
            else:
                prob_a = float(odds_a) if odds_a else None
                prob_b = float(odds_b) if odds_b else None

            if prob_a is None or prob_b is None:
                continue

            resolved_a = resolve_prophetx_player(name_a)
            resolved_b = resolve_prophetx_player(name_b)
            canonical_a = resolved_a["canonical_name"] if resolved_a else name_a
            canonical_b = resolved_b["canonical_name"] if resolved_b else name_b

            matchups.append({
                "p1_name": canonical_a,
                "p2_name": canonical_b,
                "p1_prob": prob_a,
                "p2_prob": prob_b,
            })

        # Cache
        if matchups and tournament_slug:
            try:
                client._cache_response(matchups, "prophetx_matchups", tournament_slug)
            except Exception:
                logger.debug("ProphetX: matchup cache write failed", exc_info=True)

        return matchups

    except Exception:
        logger.warning("ProphetX: matchups pull failed", exc_info=True)
        return []


def merge_prophetx_into_outrights(
    dg_outrights: dict[str, list[dict]],
    prophetx_outrights: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """Inject ProphetX data as book columns into DG outright data.

    Format-aware merge:
    - Always adds "prophetx" key with American odds string
    - Adds "_prophetx_ask_prob" ONLY when binary format (American IS the bettable price)

    Mutates dg_outrights in-place and returns it.
    """
    for dg_key, px_key in _DG_TO_PROPHETX_MARKET.items():
        dg_players = dg_outrights.get(dg_key)
        px_players = prophetx_outrights.get(px_key, [])

        if not dg_players or not px_players:
            continue

        # Build case-insensitive lookup
        px_lookup: dict[str, dict] = {}
        for pp in px_players:
            name = pp["player_name"].strip().lower()
            if name not in px_lookup:
                px_lookup[name] = pp

        for player in dg_players:
            pname = player.get("player_name", "").strip().lower()
            pp = px_lookup.get(pname)
            if not pp:
                continue

            mid_prob = pp.get("prophetx_mid_prob", 0)
            if mid_prob <= 0 or mid_prob >= 1:
                continue

            # Get American odds: either stored directly or convert from mid_prob
            if pp.get("prophetx_american"):
                american = pp["prophetx_american"]
            else:
                american = binary_price_to_american(str(mid_prob))
                if not american:
                    continue

            player["prophetx"] = american

            # Only add ask_prob for binary format
            if pp.get("odds_format") == "binary" and "prophetx_ask_prob" in pp:
                player["_prophetx_ask_prob"] = pp["prophetx_ask_prob"]

    return dg_outrights


def merge_prophetx_into_matchups(
    dg_matchups: list[dict],
    prophetx_matchups: list[dict],
) -> list[dict]:
    """Inject ProphetX H2H data into DG matchup odds dicts.

    Uses frozenset for order-independent name matching, then aligns
    player order to DG's p1/p2.

    Mutates dg_matchups in-place and returns it.
    """
    # Build lookup by frozenset of normalized names
    px_lookup: dict[frozenset, dict] = {}
    for pm in prophetx_matchups:
        key = frozenset({pm["p1_name"].strip().lower(),
                         pm["p2_name"].strip().lower()})
        if key not in px_lookup:
            px_lookup[key] = pm

    for matchup in dg_matchups:
        p1 = matchup.get("p1_player_name", "").strip().lower()
        p2 = matchup.get("p2_player_name", "").strip().lower()
        key = frozenset({p1, p2})

        pm = px_lookup.get(key)
        if not pm:
            continue

        # Align player order
        pm_p1_lower = pm["p1_name"].strip().lower()
        if pm_p1_lower == p1:
            p1_prob, p2_prob = pm["p1_prob"], pm["p2_prob"]
        else:
            p1_prob, p2_prob = pm["p2_prob"], pm["p1_prob"]

        p1_american = binary_price_to_american(str(p1_prob))
        p2_american = binary_price_to_american(str(p2_prob))

        if not p1_american or not p2_american:
            continue

        odds_dict = matchup.setdefault("odds", {})
        odds_dict["prophetx"] = {"p1": p1_american, "p2": p2_american}

    return dg_matchups
