"""
Kalshi prediction market odds pull.

Pulls win, T10, T20 outright odds and H2H matchup odds from Kalshi.
Used by run_pretournament.py alongside DG API pulls.
"""
from __future__ import annotations

import logging

from src.api.kalshi import KalshiClient
from src.core.devig import kalshi_midpoint
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


def _detect_cent_format(markets: list[dict]) -> bool:
    """Detect if markets use integer cent format (values > 1.0)."""
    for mkt in markets:
        for field in ("yes_bid", "yes_ask"):
            val = mkt.get(field)
            if val is not None:
                try:
                    if float(val) > 1.0:
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
                    bid = _normalize_price(mkt.get("yes_bid"))
                    ask = _normalize_price(mkt.get("yes_ask"))
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
                    oi = int(mkt.get("open_interest", 0))
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
                p1_bid = _normalize_price(mkt.get("yes_bid"))
                p1_ask = _normalize_price(mkt.get("yes_ask"))
            except (ValueError, TypeError):
                continue

            if p1_bid is None or p1_ask is None:
                continue

            # P2 is the complement (NO side)
            p2_bid = 1.0 - p1_ask
            p2_ask = 1.0 - p1_bid

            # Open interest (same for both sides of a binary contract)
            try:
                oi = int(mkt.get("open_interest", 0))
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
