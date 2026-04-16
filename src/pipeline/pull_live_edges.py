from __future__ import annotations
import logging

"""
Live edge detection — combines DG live predictions with current book odds.

During tournament rounds, DG's live model updates every ~5 minutes with
fresh win/T5/T10/T20/MC probabilities that reflect actual on-course
performance. This module:

1. Pulls DG live predictions (the "truth" source during rounds)
2. Pulls current book odds from DG's outrights endpoint
3. Overrides the DG model column in the outrights data with live predictions
4. Feeds the result into the standard edge calculator

The key insight: books update their odds during rounds, but the DG live
model tracks reality faster. The gap between DG-live and stale-ish book
lines is where live edges appear.
"""

from src.pipeline.pull_live import pull_live_predictions
from src.pipeline.pull_outrights import pull_all_outrights
from src.pipeline.pull_matchups import (
    pull_round_matchups, pull_3balls,
    build_field_status_lookup, filter_stale_matchups,
)
from src.pipeline.pull_kalshi import (
    pull_kalshi_outrights, pull_kalshi_matchups,
    merge_kalshi_into_outrights, merge_kalshi_into_matchups,
)
from src.pipeline.pull_polymarket import (
    pull_polymarket_outrights,
    merge_polymarket_into_outrights,
)
from src.pipeline.pull_prophetx import (
    pull_prophetx_outrights, pull_prophetx_matchups,
    merge_prophetx_into_outrights, merge_prophetx_into_matchups,
)
from src.core.edge import calculate_placement_edges, calculate_matchup_edges, calculate_3ball_edges, CandidateBet
from src.core.kelly import get_correlation_haircut
from src.normalize.players import resolve_candidates
from src.db import supabase_client as db
import config

from datetime import datetime, timedelta
from difflib import SequenceMatcher


# DG live prediction keys → outright market names
LIVE_MARKET_MAP = {
    "win":      "win",
    "top_10":   "top_10",
    "top_20":   "top_20",
    "make_cut": "make_cut",
}

# DG live response keys (varies between "top_10" and "t10" depending on format)
LIVE_KEY_ALIASES = {
    "win":      ["win"],
    "top_10":   ["top_10", "t10"],
    "top_20":   ["top_20", "t20"],
    "make_cut": ["make_cut", "mc"],
}


def _match_live_to_outright(live_players: list[dict], outright_players: list[dict]) -> dict[int, dict]:
    """Match live prediction players to outright odds players by name.

    Returns:
        {outright_index: live_player_dict}
    """
    # Build a lookup from normalized name → live player
    live_by_name: dict[str, dict] = {}
    for lp in live_players:
        name = (lp.get("player_name") or "").strip().lower()
        if name:
            live_by_name[name] = lp

    matches = {}
    for i, op in enumerate(outright_players):
        op_name = (op.get("player_name") or "").strip().strip('"').lower()
        if not op_name:
            continue

        # Exact match first
        if op_name in live_by_name:
            matches[i] = live_by_name[op_name]
            continue

        # Fuzzy match
        best_name, best_score = None, 0.0
        for ln in live_by_name:
            score = SequenceMatcher(None, op_name, ln).ratio()
            if score > best_score:
                best_name, best_score = ln, score
        if best_name and best_score >= 0.80:
            matches[i] = live_by_name[best_name]

    return matches


def _get_live_prob(live_player: dict, market: str) -> float | None:
    """Extract a probability from a live prediction record for a given market."""
    for key in LIVE_KEY_ALIASES.get(market, [market]):
        val = live_player.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
    return None


def _override_dg_with_live(outrights: dict[str, list[dict]], live_players: list[dict]) -> int:
    """Replace DG model probabilities in outrights data with live predictions.

    Modifies outrights in-place. Returns number of players matched.
    """
    total_matched = 0

    for market, players in outrights.items():
        if market.startswith("_") or not isinstance(players, list):
            continue

        matches = _match_live_to_outright(live_players, players)

        for idx, live_p in matches.items():
            live_prob = _get_live_prob(live_p, market)
            if live_prob is None or live_prob <= 0:
                continue

            # Convert probability to American odds for the DG column
            # DG column format: {"baseline_history_fit": "+250", "baseline": "+250"}
            from src.core.devig import decimal_to_american, implied_prob_to_decimal
            decimal_odds = implied_prob_to_decimal(live_prob)
            american_odds = decimal_to_american(decimal_odds)

            player = players[idx]
            if isinstance(player.get("datagolf"), dict):
                player["datagolf"]["baseline_history_fit"] = american_odds
                player["datagolf"]["baseline"] = american_odds
            else:
                player["datagolf"] = {
                    "baseline_history_fit": american_odds,
                    "baseline": american_odds,
                }

        total_matched = max(total_matched, len(matches))

    return total_matched


def _pull_polymarket_block(outrights, stats, tournament_name, today, end_date,
                           tournament_slug=None):
    """Pull and merge Polymarket outrights into live data. Graceful degradation."""
    if not config.POLYMARKET_ENABLED:
        return
    try:
        polymarket_outrights = pull_polymarket_outrights(
            tournament_name, today, end_date,
            tournament_slug=tournament_slug,
        )
        if any(len(v) > 0 for v in polymarket_outrights.values()):
            merge_polymarket_into_outrights(outrights, polymarket_outrights)
            stats["polymarket_merged"] = True
    except Exception as e:
        stats["polymarket_error"] = str(e)


def _pull_prophetx_block(outrights, matchups, stats, tournament_name, today, end_date,
                         tournament_slug=None):
    """Pull and merge ProphetX outrights + matchups into live data. Graceful degradation."""
    if not config.PROPHETX_ENABLED:
        return
    try:
        prophetx_outrights = pull_prophetx_outrights(
            tournament_name, today, end_date,
            tournament_slug=tournament_slug,
        )
        if any(len(v) > 0 for v in prophetx_outrights.values()):
            merge_prophetx_into_outrights(outrights, prophetx_outrights)
            stats["prophetx_merged"] = True

        prophetx_matchup_data = pull_prophetx_matchups(
            tournament_name, today, end_date,
            tournament_slug=tournament_slug,
        )
        if prophetx_matchup_data and isinstance(matchups, list):
            merge_prophetx_into_matchups(matchups, prophetx_matchup_data)
    except Exception as e:
        stats["prophetx_error"] = str(e)


def pull_live_edges(
    tour: str = "pga",
    tournament_slug: str | None = None,
    include_kalshi: bool = True,
    include_matchups: bool = True,
    round_number: int | None = None,
) -> tuple[list[CandidateBet], str, dict]:
    """Pull live edges by combining DG live predictions with current book odds.

    Returns:
        (candidates, tournament_name, stats_dict)
        where stats_dict has keys like "live_players", "matched", "markets", etc.
    """
    stats = {}

    # Step 1: Pull DG live predictions
    live_players = pull_live_predictions(tournament_slug, tour)
    stats["live_players"] = len(live_players)

    if not live_players:
        return [], "Unknown", stats

    # Step 2: Pull current book odds
    outrights = pull_all_outrights(tournament_slug, tour)
    tournament_name = outrights.get("_event_name", "Unknown")
    stats["tournament_name"] = tournament_name

    # Step 3: Override DG model with live predictions
    matched = _override_dg_with_live(outrights, live_players)
    stats["matched"] = matched

    # Date range for prediction market matching
    today = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")

    # Step 4: Pull and merge Kalshi odds (now safe — we have live DG data)
    if include_kalshi:
        try:
            kalshi_outrights = pull_kalshi_outrights(
                tournament_name, today, end_date,
                tournament_slug=tournament_slug,
            )
            if any(len(v) > 0 for v in kalshi_outrights.values()):
                merge_kalshi_into_outrights(outrights, kalshi_outrights)
                stats["kalshi_merged"] = True
        except Exception as e:
            stats["kalshi_error"] = str(e)

    # Step 4b: Pull and merge Polymarket outrights
    _pull_polymarket_block(outrights, stats, tournament_name, today, end_date,
                           tournament_slug=tournament_slug)

    # Step 4c: Pull and merge ProphetX outrights only (matchups merged in step 7)
    if config.PROPHETX_ENABLED:
        try:
            prophetx_outrights = pull_prophetx_outrights(
                tournament_name, today, end_date,
                tournament_slug=tournament_slug,
            )
            if any(len(v) > 0 for v in prophetx_outrights.values()):
                merge_prophetx_into_outrights(outrights, prophetx_outrights)
                stats["prophetx_merged"] = True
        except Exception as e:
            stats["prophetx_error"] = str(e)

    # Step 5: Get bankroll and existing bets
    bankroll = db.get_bankroll()
    existing_bets = db.get_open_bets_for_week()
    stats["bankroll"] = bankroll

    # Detect tournament for exposure
    tournament_id = None
    for b in sorted(existing_bets, key=lambda x: x.get("bet_timestamp", ""), reverse=True):
        if b.get("tournament_id"):
            tournament_id = b["tournament_id"]
            break
    stats["tournament_id"] = tournament_id

    # Step 6: Calculate edges using the live-adjusted data
    all_candidates = []

    market_map = {"win": "win", "top_10": "t10", "top_20": "t20", "make_cut": "make_cut"}
    for dg_market, our_market in market_map.items():
        data = outrights.get(dg_market, [])
        if not data:
            continue

        edges = calculate_placement_edges(
            data, our_market,
            bankroll=bankroll,
            existing_bets=existing_bets + [
                {"player_name": c.player_name, "opponent_name": c.opponent_name,
                 "opponent_2_name": c.opponent_2_name}
                for c in all_candidates
            ],
            exchange_only=True,
            win_outrights_data=outrights.get("win"),
            display_min_edge=config.DISPLAY_MIN_EDGE,
        )
        if edges:
            stats[f"{our_market}_edges"] = len(edges)
            all_candidates.extend(edges)

    # Step 7: Round matchups and 3-balls (if requested)
    if include_matchups:
        # Build a field-status lookup once so we can drop stale matchups
        # (players already teed off, finished, cut, WD, or DQ).
        field_lookup = build_field_status_lookup(tour=tour)
        stats["field_players"] = len(field_lookup)

        round_matchups = pull_round_matchups(tournament_slug, tour)
        if round_matchups:
            before = len(round_matchups)
            round_matchups = filter_stale_matchups(
                round_matchups, field_lookup, n_players=2)
            stats["matchups_dropped_stale"] = before - len(round_matchups)
        if round_matchups:
            # Merge Kalshi matchups if available
            if include_kalshi:
                try:
                    kalshi_matchup_data = pull_kalshi_matchups(
                        tournament_name, today, end_date,
                        tournament_slug=tournament_slug,
                    )
                    if kalshi_matchup_data:
                        merge_kalshi_into_matchups(round_matchups, kalshi_matchup_data)
                except Exception:
                    pass

            # Merge ProphetX matchups
            if config.PROPHETX_ENABLED:
                try:
                    prophetx_matchup_data = pull_prophetx_matchups(
                        tournament_name, today, end_date,
                        tournament_slug=tournament_slug,
                    )
                    if prophetx_matchup_data:
                        merge_prophetx_into_matchups(round_matchups, prophetx_matchup_data)
                except Exception:
                    pass

            edges = calculate_matchup_edges(
                round_matchups, bankroll=bankroll,
                existing_bets=existing_bets + [
                    {"player_name": c.player_name, "opponent_name": c.opponent_name,
                     "opponent_2_name": c.opponent_2_name}
                    for c in all_candidates
                ],
                market_type="round_matchup",
                display_min_edge=config.DISPLAY_MIN_EDGE,
            )
            for e in edges:
                e.round_number = round_number
            if edges:
                stats["matchup_edges"] = len(edges)
                all_candidates.extend(edges)

        three_balls = pull_3balls(tournament_slug, tour)
        if three_balls:
            before = len(three_balls)
            three_balls = filter_stale_matchups(
                three_balls, field_lookup, n_players=3)
            stats["3balls_dropped_stale"] = before - len(three_balls)
        if three_balls:
            edges = calculate_3ball_edges(
                three_balls, bankroll=bankroll,
                existing_bets=existing_bets + [
                    {"player_name": c.player_name, "opponent_name": c.opponent_name,
                     "opponent_2_name": c.opponent_2_name}
                    for c in all_candidates
                ],
                round_number=round_number,
                display_min_edge=config.DISPLAY_MIN_EDGE,
            )
            if edges:
                stats["3ball_edges"] = len(edges)
                all_candidates.extend(edges)

    # Step 8: Sort and resolve
    all_candidates.sort(key=lambda c: c.edge, reverse=True)

    if all_candidates:
        try:
            from src.core.expert_picks import enrich_candidates_from_cache
            enrich_candidates_from_cache(all_candidates, tournament_name)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Expert-pick enrichment failed: %s", e)
        resolve_candidates(all_candidates, source="datagolf")

    stats["total_candidates"] = len(all_candidates)
    return all_candidates, tournament_name, stats
