"""
Kalshi prediction market odds pull.

Pulls win, T10, T20 outright odds and H2H matchup odds from Kalshi.
Used by run_pretournament.py alongside DG API pulls.
"""
from __future__ import annotations

import logging

from src.api.kalshi import KalshiClient
from src.core.devig import kalshi_midpoint, kalshi_price_to_american
from src.pipeline.kalshi_matching import (
    extract_player_name_outright,
    extract_player_names_h2h,
    match_tournament,
    resolve_kalshi_player,
)
import config

# Future: Polymarket would follow a similar pattern here.
# Polymarket covers outrights and top-N but NOT matchups,
# and requires keyword-based event discovery via the Gamma API.

logger = logging.getLogger(__name__)

# Outright market types to pull (skip tournament_matchup — handled by pull_kalshi_matchups)
_OUTRIGHT_KEYS = ("win", "t10", "t20")


def _normalize_price(value) -> float | None:
    """Normalize a Kalshi price to 0-1 range.

    Kalshi may return prices as floats (0.06) or integer cents (6).
    Returns None for missing/zero/invalid values.
    """
    if value is None:
        return None
    v = float(value)
    if v <= 0:
        return None
    if v > 1.0:
        v /= 100.0
    return v


def _get_yes_bid(mkt: dict) -> float | None:
    """Extract YES bid price from a Kalshi market dict.

    Handles both legacy (yes_bid) and current (yes_bid_dollars) field names.
    """
    val = mkt.get("yes_bid") or mkt.get("yes_bid_dollars")
    return float(val) if val is not None else None


def _get_yes_ask(mkt: dict) -> float | None:
    """Extract YES ask price from a Kalshi market dict.

    Handles both legacy (yes_ask) and current (yes_ask_dollars) field names.
    """
    val = mkt.get("yes_ask") or mkt.get("yes_ask_dollars")
    return float(val) if val is not None else None


def _get_open_interest(mkt: dict) -> int:
    """Extract open interest from a Kalshi market dict.

    Handles both legacy (open_interest) and current (open_interest_fp) field names.
    """
    val = mkt.get("open_interest") or mkt.get("open_interest_fp")
    if val is None:
        return 0
    return int(float(val))


def _detect_cent_format(markets: list[dict]) -> bool:
    """Detect if markets use integer cent format (values > 1.0)."""
    for mkt in markets:
        for getter in (_get_yes_bid, _get_yes_ask):
            val = getter(mkt)
            if val is not None:
                try:
                    if val > 1.0:
                        return True
                except (ValueError, TypeError):
                    pass
    return False


def pull_kalshi_outrights(
    tournament_name: str,
    tournament_start: str,
    tournament_end: str,
    tournament_slug: str | None = None,
) -> dict[str, list[dict]]:
    """Pull Kalshi outright odds for win, t10, t20 markets.

    Args:
        tournament_name: DG tournament name for matching.
        tournament_start: ISO date string for tournament start.
        tournament_end: ISO date string for tournament end.
        tournament_slug: Optional slug for cache labeling.

    Returns:
        {"win": [...], "t10": [...], "t20": [...]} with player dicts.
        Each dict has: player_name, kalshi_mid_prob, kalshi_ask_prob, open_interest.
        Returns empty lists on any failure.
    """
    results = {k: [] for k in _OUTRIGHT_KEYS}

    try:
        client = KalshiClient()
    except Exception:
        logger.warning("Kalshi: failed to create client", exc_info=True)
        return results

    for market_key in _OUTRIGHT_KEYS:
        try:
            series_ticker = config.KALSHI_SERIES_TICKERS.get(market_key)
            if not series_ticker:
                continue

            # Find the current tournament event
            events = client.get_golf_events(series_ticker)
            event_ticker = match_tournament(
                events, tournament_name, tournament_start, tournament_end,
            )
            if not event_ticker:
                logger.info("Kalshi: no %s event matched for %s", market_key, tournament_name)
                continue

            # Fetch all markets (player contracts) for the event
            markets = client.get_event_markets(event_ticker)

            # Cache raw response
            client._cache_response(
                markets, f"kalshi_{market_key}",
                tournament_slug=tournament_slug,
            )

            # Process each contract
            players = []
            for mkt in markets:
                # Extract player name
                raw_name = extract_player_name_outright(mkt)
                if not raw_name:
                    continue

                # Read and normalize prices
                try:
                    bid = _normalize_price(_get_yes_bid(mkt))
                    ask = _normalize_price(_get_yes_ask(mkt))
                except (ValueError, TypeError):
                    logger.warning("Kalshi: invalid price data for %s", raw_name)
                    continue

                if bid is None or ask is None:
                    continue

                # Compute midpoint
                mid = kalshi_midpoint(str(bid), str(ask))
                if mid is None:
                    continue

                # Read open interest
                try:
                    oi = _get_open_interest(mkt)
                except (ValueError, TypeError):
                    continue

                # Filter: OI threshold
                if oi < config.KALSHI_MIN_OPEN_INTEREST:
                    continue

                # Filter: spread threshold
                if (ask - bid) > config.KALSHI_MAX_SPREAD:
                    continue

                # Resolve player name to DG canonical
                resolved = resolve_kalshi_player(raw_name)
                if not resolved:
                    logger.warning("Kalshi: could not resolve player '%s'", raw_name)
                    continue

                players.append({
                    "player_name": resolved["canonical_name"],
                    "kalshi_mid_prob": mid,
                    "kalshi_ask_prob": ask,
                    "open_interest": oi,
                })

            results[market_key] = players

        except Exception:
            logger.warning("Kalshi: %s pull failed", market_key, exc_info=True)

    return results


def pull_kalshi_matchups(
    tournament_name: str,
    tournament_start: str,
    tournament_end: str,
    tournament_slug: str | None = None,
) -> list[dict]:
    """Pull Kalshi H2H matchup odds.

    Args:
        tournament_name: DG tournament name for matching.
        tournament_start: ISO date string for tournament start.
        tournament_end: ISO date string for tournament end.
        tournament_slug: Optional slug for cache labeling.

    Returns:
        List of matchup dicts with p1_name, p2_name, p1_prob, p2_prob, p1_oi, p2_oi.
        Empty list on any failure.
    """
    try:
        client = KalshiClient()

        series_ticker = config.KALSHI_SERIES_TICKERS.get("tournament_matchup")
        if not series_ticker:
            return []

        events = client.get_golf_events(series_ticker)
        event_ticker = match_tournament(
            events, tournament_name, tournament_start, tournament_end,
        )
        if not event_ticker:
            logger.info("Kalshi: no H2H event matched for %s", tournament_name)
            return []

        markets = client.get_event_markets(event_ticker)

        # Cache raw response
        client._cache_response(
            markets, "kalshi_h2h", tournament_slug=tournament_slug,
        )

        results = []
        for mkt in markets:
            # Extract both player names from H2H title
            names = extract_player_names_h2h(mkt)
            if not names:
                continue
            p1_raw, p2_raw = names

            # Read and normalize prices
            try:
                p1_bid = _normalize_price(_get_yes_bid(mkt))
                p1_ask = _normalize_price(_get_yes_ask(mkt))
            except (ValueError, TypeError):
                continue

            if p1_bid is None or p1_ask is None:
                continue

            # P2 is the complement (NO side)
            p2_bid = 1.0 - p1_ask
            p2_ask = 1.0 - p1_bid

            # Open interest (same for both sides of a binary contract)
            try:
                oi = _get_open_interest(mkt)
            except (ValueError, TypeError):
                continue

            # Filter: OI threshold
            if oi < config.KALSHI_MIN_OPEN_INTEREST:
                continue

            # Filter: spread threshold (YES side spread)
            if (p1_ask - p1_bid) > config.KALSHI_MAX_SPREAD:
                continue

            # Compute midpoints
            p1_mid = kalshi_midpoint(str(p1_bid), str(p1_ask))
            p2_mid = kalshi_midpoint(str(p2_bid), str(p2_ask))
            if p1_mid is None or p2_mid is None:
                continue

            # Resolve player names
            p1_resolved = resolve_kalshi_player(p1_raw)
            p2_resolved = resolve_kalshi_player(p2_raw)
            if not p1_resolved or not p2_resolved:
                logger.warning("Kalshi: could not resolve H2H players '%s' vs '%s'", p1_raw, p2_raw)
                continue

            results.append({
                "p1_name": p1_resolved["canonical_name"],
                "p2_name": p2_resolved["canonical_name"],
                "p1_prob": p1_mid,
                "p2_prob": p2_mid,
                "p1_oi": oi,
                "p2_oi": oi,
            })

        return results

    except Exception:
        logger.warning("Kalshi: matchup pull failed", exc_info=True)
        return []


# ---- Merge Functions ----

# DG uses "top_10"/"top_20", Kalshi pull returns "t10"/"t20"
_DG_TO_KALSHI_MARKET = {"win": "win", "top_10": "t10", "top_20": "t20"}


def merge_kalshi_into_outrights(
    dg_outrights: dict[str, list[dict]],
    kalshi_outrights: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """Inject Kalshi data as book columns into DG outright data.

    For each market type, finds matching players by canonical name, then:
    1. Adds "kalshi" key with American odds string (from midpoint prob)
    2. Adds "_kalshi_ask_prob" key with raw ask probability (float)

    Mutates dg_outrights in-place and returns it.
    """
    for dg_key, kalshi_key in _DG_TO_KALSHI_MARKET.items():
        dg_players = dg_outrights.get(dg_key)
        kalshi_players = kalshi_outrights.get(kalshi_key, [])

        if not dg_players or not kalshi_players:
            continue

        # Build lookup by normalized player name
        kalshi_lookup = {}
        for kp in kalshi_players:
            name = kp["player_name"].strip().lower()
            if name not in kalshi_lookup:
                kalshi_lookup[name] = kp

        # Match and inject
        for player in dg_players:
            pname = player.get("player_name", "").strip().lower()
            kp = kalshi_lookup.get(pname)
            if not kp:
                continue

            mid_prob = kp["kalshi_mid_prob"]
            if mid_prob <= 0 or mid_prob >= 1:
                continue

            american = kalshi_price_to_american(str(mid_prob))
            if not american:
                continue

            player["kalshi"] = american
            player["_kalshi_ask_prob"] = kp["kalshi_ask_prob"]

    return dg_outrights


def merge_kalshi_into_matchups(
    dg_matchups: list[dict],
    kalshi_matchups: list[dict],
) -> list[dict]:
    """Inject Kalshi H2H data into DG matchup odds dicts.

    Finds matching pairings by player names (order-independent), then
    adds a "kalshi" entry to the matchup's odds dict with p1/p2 American
    odds strings aligned to the DG matchup's player order.

    Mutates dg_matchups in-place and returns it.
    """
    if not kalshi_matchups:
        return dg_matchups

    # Build lookup by frozenset of normalized names
    kalshi_lookup = {}
    for km in kalshi_matchups:
        key = frozenset({km["p1_name"].strip().lower(),
                         km["p2_name"].strip().lower()})
        if key not in kalshi_lookup:
            kalshi_lookup[key] = km

    for matchup in dg_matchups:
        p1 = matchup.get("p1_player_name", "").strip().lower()
        p2 = matchup.get("p2_player_name", "").strip().lower()
        key = frozenset({p1, p2})

        km = kalshi_lookup.get(key)
        if not km:
            continue

        # Align player order: determine which Kalshi player is DG's p1
        km_p1_lower = km["p1_name"].strip().lower()
        if km_p1_lower == p1:
            p1_prob, p2_prob = km["p1_prob"], km["p2_prob"]
        else:
            p1_prob, p2_prob = km["p2_prob"], km["p1_prob"]

        p1_american = kalshi_price_to_american(str(p1_prob))
        p2_american = kalshi_price_to_american(str(p2_prob))

        if not p1_american or not p2_american:
            continue

        odds_dict = matchup.setdefault("odds", {})
        odds_dict["kalshi"] = {"p1": p1_american, "p2": p2_american}
