"""Polymarket prediction market odds pull. Win, T10, T20 outrights only."""

from __future__ import annotations

import json
import logging

import config
from src.api.polymarket import PolymarketClient
from src.core.devig import binary_price_to_american
from src.pipeline.polymarket_matching import (
    extract_player_name,
    match_all_market_types,
    resolve_polymarket_player,
)

logger = logging.getLogger(__name__)

# DG uses "top_10"/"top_20", our pull returns "t10"/"t20"
_DG_TO_POLYMARKET_MARKET = {"win": "win", "top_10": "t10", "top_20": "t20"}


def _identify_yes_token(market: dict) -> str | None:
    """Find the YES token ID from the market's outcomes array.

    Returns the clobTokenId corresponding to the "Yes" outcome,
    or None if not found.
    """
    outcomes_raw = market.get("outcomes", "[]")
    token_ids_raw = market.get("clobTokenIds", "[]")

    try:
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
    except (json.JSONDecodeError, TypeError):
        return None

    for i, outcome in enumerate(outcomes):
        if isinstance(outcome, str) and outcome.lower() == "yes":
            if i < len(token_ids):
                return token_ids[i]
    return None


def _best_bid(orderbook: dict) -> float:
    """Extract the highest bid price. Returns 0.0 if no bids."""
    bids = orderbook.get("bids", [])
    if not bids:
        return 0.0
    return max(float(b["price"]) for b in bids)


def _best_ask(orderbook: dict) -> float:
    """Extract the lowest ask price. Returns 1.0 if no asks."""
    asks = orderbook.get("asks", [])
    if not asks:
        return 1.0
    return min(float(a["price"]) for a in asks)


def pull_polymarket_outrights(
    tournament_name: str,
    tournament_start: str,
    tournament_end: str,
    tournament_slug: str | None = None,
) -> dict[str, list[dict]]:
    """Pull Polymarket outright odds for win, t10, t20.

    Returns {"win": [...], "t10": [...], "t20": [...]} with only
    market types that had matched events.
    """
    client = PolymarketClient()
    matched_events = match_all_market_types(
        client, tournament_name, tournament_start, tournament_end,
    )

    if not matched_events:
        return {}

    results = {}

    for market_type, event in matched_events.items():
        try:
            markets = event.get("markets", [])
            if not markets:
                continue

            # Collect YES token IDs for batch book fetch
            token_map = {}  # token_id → market
            for market in markets:
                yes_token = _identify_yes_token(market)
                if yes_token:
                    token_map[yes_token] = market
                else:
                    logger.warning(
                        "Polymarket: no YES token for market '%s'",
                        market.get("slug", "unknown"),
                    )

            if not token_map:
                continue

            # Batch fetch orderbooks
            books = client.get_books(list(token_map.keys()))

            players = []
            event_slug = event.get("slug", "")

            for token_id, market in token_map.items():
                orderbook = books.get(token_id, {})

                # Require both sides for a meaningful midpoint
                if not orderbook.get("bids") or not orderbook.get("asks"):
                    continue

                bid = _best_bid(orderbook)
                ask = _best_ask(orderbook)
                midpoint = (bid + ask) / 2.0

                # Relative spread filter
                spread = ask - bid
                max_allowed = max(
                    config.POLYMARKET_MAX_SPREAD_ABS,
                    config.POLYMARKET_MAX_SPREAD_REL * midpoint,
                )
                if spread > max_allowed:
                    continue

                # Volume filter
                volume = float(market.get("volume", 0))
                if volume < config.POLYMARKET_MIN_VOLUME:
                    continue

                # Extract and resolve player name
                name = extract_player_name(market, event_slug=event_slug)
                if not name:
                    continue

                resolved = resolve_polymarket_player(name)
                canonical = resolved["canonical_name"] if resolved else name

                # Fee-adjusted ask (clamped to valid probability)
                adjusted_ask = min(1.0, ask + config.POLYMARKET_FEE_RATE)

                players.append({
                    "player_name": canonical,
                    "polymarket_mid_prob": midpoint,
                    "polymarket_ask_prob": adjusted_ask,
                    "volume": volume,
                })

            if players:
                results[market_type] = players

        except Exception:
            logger.warning("Polymarket: pull failed for %s", market_type, exc_info=True)
            continue

    # Cache raw responses
    if results and tournament_slug:
        try:
            client._cache_response(results, "polymarket_outrights", tournament_slug)
        except Exception:
            logger.debug("Polymarket: cache write failed", exc_info=True)

    return results


def merge_polymarket_into_outrights(
    dg_outrights: dict[str, list[dict]],
    polymarket_outrights: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """Inject Polymarket data as book columns into DG outright data.

    For each market type, finds matching players by canonical name, then:
    1. Adds "polymarket" key with American odds string (from midpoint prob)
    2. Adds "_polymarket_ask_prob" key with fee-adjusted ask probability (float)

    Mutates dg_outrights in-place and returns it.
    """
    for dg_key, poly_key in _DG_TO_POLYMARKET_MARKET.items():
        dg_players = dg_outrights.get(dg_key)
        poly_players = polymarket_outrights.get(poly_key, [])

        if not dg_players or not poly_players:
            continue

        # Build lookup by normalized player name
        poly_lookup = {}
        for pp in poly_players:
            name = pp["player_name"].strip().lower()
            if name not in poly_lookup:
                poly_lookup[name] = pp

        # Match and inject
        for player in dg_players:
            pname = player.get("player_name", "").strip().lower()
            pp = poly_lookup.get(pname)
            if not pp:
                continue

            mid_prob = pp["polymarket_mid_prob"]
            if mid_prob <= 0 or mid_prob >= 1:
                continue

            american = binary_price_to_american(str(mid_prob))
            if not american:
                continue

            player["polymarket"] = american
            player["_polymarket_ask_prob"] = pp["polymarket_ask_prob"]

    return dg_outrights
