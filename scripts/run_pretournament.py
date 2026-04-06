#!/usr/bin/env python3
from __future__ import annotations

"""
Pre-tournament scan — the main weekly workflow script.

Usage:
    python scripts/run_pretournament.py [--dry-run] [--tour pga]

Workflow:
1. Pull outright odds (win, T10, T20, MC) from DG API
2. Pull tournament matchup odds from DG API
3. Run edge calculator on all markets
4. Display candidate bets with correlation haircuts
5. Interactive: select bets to place, confirm actual odds + notes
6. Log placed bets to Supabase
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from datetime import datetime, timedelta

from src.pipeline.pull_outrights import pull_all_outrights
from src.pipeline.pull_matchups import pull_tournament_matchups
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
from src.parsers.start_matchups import parse_start_matchups_from_file
from src.parsers.start_merger import merge_start_into_matchups
from src.core.edge import calculate_placement_edges, calculate_matchup_edges
from src.core.arb import detect_matchup_arbs, format_arb_table
from src.core.devig import american_to_decimal, decimal_to_american, parse_american_odds
from src.normalize.players import resolve_candidates
from src.db import supabase_client as db
import config


# Market type mapping from DG API market names to our internal names
MARKET_MAP = {
    "win": "win",
    "top_10": "t10",
    "top_20": "t20",
    "make_cut": "make_cut",
}


def display_candidates(candidates, bankroll, weekly_exposure, tournament_exposure):
    """Display candidate bets in a formatted table."""
    weekly_limit = bankroll * config.MAX_WEEKLY_EXPOSURE_PCT
    tournament_limit = bankroll * config.MAX_TOURNAMENT_EXPOSURE_PCT

    print(f"\nBankroll: ${bankroll:.2f} | "
          f"Weekly: ${weekly_exposure:.2f} / ${weekly_limit:.2f} | "
          f"Tournament: ${tournament_exposure:.2f} / ${tournament_limit:.2f}")

    if not candidates:
        print("\nNo +EV candidates found above threshold.")
        return

    print(f"\n{len(candidates)} candidate bets found:\n")
    print(f" {'#':>3}  {'Player':<22} {'Market':<8} {'Best Book':<12} "
          f"{'Odds':>7} {'Your%':>6} {'Book%':>6} {'Edge':>6} "
          f"{'Stake':>6} {'Corr':>5}")
    print(f" {'—'*3}  {'—'*22} {'—'*8} {'—'*12} {'—'*7} {'—'*6} {'—'*6} "
          f"{'—'*6} {'—'*6} {'—'*5}")

    for i, c in enumerate(candidates, 1):
        # Format opponent for matchups
        if c.opponent_name:
            display_name = f"{c.player_name[:10]} v {c.opponent_name[:10]}"
        else:
            display_name = c.player_name[:22]

        corr_flag = f"{c.correlation_haircut:.1f}x"
        if c.correlation_haircut < 1.0:
            corr_flag += " ⚠️"

        print(f" {i:>3}  {display_name:<22} {c.market_type:<8} "
              f"{c.best_book:<12} {c.best_odds_american:>7} "
              f"{c.your_prob*100:>5.1f}% {c.best_implied_prob*100:>5.1f}% "
              f"{c.edge*100:>5.1f}% ${c.suggested_stake:>4.0f} {corr_flag:>5}")


def interactive_place_bets(candidates, tournament_id, bankroll):
    """Interactive CLI for placing bets with actual odds confirmation."""
    if not candidates:
        return

    print(f"\nPlace bets? Enter numbers (e.g., 1,3,5) or 'skip all': ", end="")
    response = input().strip()

    if response.lower() in ("skip", "skip all", "s", ""):
        reason = input("Skip reason (optional): ").strip()
        # Mark all as skipped
        # (candidates haven't been inserted yet, so just print)
        print(f"Skipped all candidates.{' Reason: ' + reason if reason else ''}")
        return

    try:
        indices = [int(x.strip()) - 1 for x in response.split(",")]
    except ValueError:
        print("Invalid input. Skipping.")
        return

    placed_bets = []

    for idx in indices:
        if idx < 0 or idx >= len(candidates):
            print(f"Invalid bet number: {idx + 1}")
            continue

        c = candidates[idx]
        display = c.player_name
        if c.opponent_name:
            display = f"{c.player_name} vs {c.opponent_name}"

        print(f"\n--- Bet #{idx+1}: {display} {c.market_type} — "
              f"{c.best_book} {c.best_odds_american} (scanned) ---")

        # Actual odds
        actual_odds_str = input(
            f"  Actual odds placed? [{c.best_odds_american}]: "
        ).strip()
        if not actual_odds_str:
            actual_odds_str = c.best_odds_american

        actual_decimal = american_to_decimal(actual_odds_str)
        if actual_decimal is None:
            print(f"  Invalid odds: {actual_odds_str}. Skipping.")
            continue

        # Recalculate edge at actual odds
        actual_implied = 1.0 / actual_decimal if actual_decimal > 0 else 0
        actual_edge = c.your_prob - actual_implied

        if actual_edge <= 0:
            print(f"  Edge is gone at {actual_odds_str} "
                  f"(implied {actual_implied*100:.1f}% vs your {c.your_prob*100:.1f}%). "
                  f"Skip? [y/N]: ", end="")
            if input().strip().lower() in ("y", "yes"):
                continue

        # Stake
        stake_str = input(f"  Stake? [${c.suggested_stake:.0f}]: ").strip()
        if stake_str:
            try:
                stake = float(stake_str)
            except ValueError:
                stake = c.suggested_stake
        else:
            stake = c.suggested_stake

        # Notes
        notes = input("  Notes (optional): ").strip() or None

        # Log the bet
        bet = db.insert_bet(
            candidate_id=None,  # Will link after candidates are inserted
            tournament_id=tournament_id,
            market_type=c.market_type,
            player_name=c.player_name,
            book=c.best_book,
            odds_at_bet_decimal=actual_decimal,
            odds_at_bet_american=actual_odds_str,
            implied_prob_at_bet=actual_implied,
            your_prob=c.your_prob,
            edge=actual_edge,
            stake=stake,
            scanned_odds_decimal=c.best_odds_decimal,
            player_id=c.player_id,
            opponent_name=c.opponent_name,
            opponent_id=c.opponent_id,
            opponent_2_name=c.opponent_2_name,
            opponent_2_id=c.opponent_2_id,
            round_number=c.round_number,
            correlation_haircut=c.correlation_haircut,
            notes=notes,
        )

        if bet:
            print(f"  ✓ Logged: {display} {c.market_type} @ {c.best_book} "
                  f"{actual_odds_str}, ${stake:.0f} stake, "
                  f"edge {actual_edge*100:.1f}%")
            placed_bets.append(bet)
        else:
            print(f"  ✗ Failed to log bet")

    # Skip remaining
    skipped_count = len(candidates) - len(indices)
    if skipped_count > 0:
        reason = input(
            f"\nSkip remaining {skipped_count} candidates? "
            f"Reason (optional): "
        ).strip() or None
        if reason:
            print(f"  Noted: {reason}")

    # Updated exposure
    new_balance = db.get_bankroll()
    print(f"\nBankroll after bets: ${new_balance:.2f}")
    print(f"Bets placed this session: {len(placed_bets)}")


def _pull_polymarket_block(outrights, tournament_name, today, end_date,
                           tournament_slug=None):
    """Pull and merge Polymarket outrights. Graceful degradation on failure."""
    if not config.POLYMARKET_ENABLED:
        print("\nPolymarket: disabled")
        return
    print("\nPulling Polymarket odds...")
    try:
        polymarket_outrights = pull_polymarket_outrights(
            tournament_name, today, end_date,
            tournament_slug=tournament_slug,
        )
        if any(len(v) > 0 for v in polymarket_outrights.values()):
            merge_polymarket_into_outrights(outrights, polymarket_outrights)
            for mkt, players in polymarket_outrights.items():
                if players:
                    print(f"  Polymarket {mkt}: {len(players)} players merged")
        else:
            print("  Polymarket: no outright data available")
    except Exception as e:
        print(f"  Warning: Polymarket unavailable ({e}), proceeding without")


def _pull_prophetx_block(outrights, matchups, tournament_name, today, end_date,
                         tournament_slug=None):
    """Pull and merge ProphetX outrights + matchups. Graceful degradation."""
    if not config.PROPHETX_ENABLED:
        print("\nProphetX: disabled")
        return
    print("\nPulling ProphetX odds...")
    try:
        prophetx_outrights = pull_prophetx_outrights(
            tournament_name, today, end_date,
            tournament_slug=tournament_slug,
        )
        if any(len(v) > 0 for v in prophetx_outrights.values()):
            merge_prophetx_into_outrights(outrights, prophetx_outrights)
            for mkt, players in prophetx_outrights.items():
                if players:
                    print(f"  ProphetX {mkt}: {len(players)} players merged")

        prophetx_matchup_data = pull_prophetx_matchups(
            tournament_name, today, end_date,
            tournament_slug=tournament_slug,
        )
        if prophetx_matchup_data:
            merge_prophetx_into_matchups(matchups, prophetx_matchup_data)
            print(f"  ProphetX matchups: {len(prophetx_matchup_data)} merged")
    except Exception as e:
        print(f"  Warning: ProphetX unavailable ({e}), proceeding without")


def main():
    parser = argparse.ArgumentParser(
        description="Pre-tournament +EV scan"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't push to Supabase")
    parser.add_argument("--tour", default="pga",
                        help="Tour to scan (default: pga)")
    parser.add_argument("--tournament", default=None,
                        help="Tournament slug for cache folder")
    parser.add_argument("--start-file", default=None,
                        help="Path to copy-pasted Start matchup odds text file")
    args = parser.parse_args()

    tournament_slug = args.tournament
    tour = args.tour

    # Get current bankroll
    bankroll = db.get_bankroll()
    if bankroll <= 0:
        print("No bankroll found. Initialize with:")
        print("  python -c \"from src.db import supabase_client as db; "
              "db.initialize_bankroll(1000)\"")
        return

    # Get existing bets for exposure checks
    existing_bets = db.get_open_bets_for_week()
    weekly_exposure = sum(b.get("stake", 0) for b in existing_bets)

    print(f"=== Pre-Tournament Scan ({tour.upper()}) ===")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # ---- Pull Data ----
    print("\nPulling outright odds...")
    outrights = pull_all_outrights(tournament_slug, tour)

    # Staleness guard: abort if the tournament is live or completed
    if outrights.get("_is_live"):
        print(f"\n  Tournament is LIVE — DG baseline model not available.")
        if outrights.get("_notes"):
            print(f"  DG says: {outrights['_notes']}")
        if outrights.get("_last_updated"):
            print(f"  Last updated: {outrights['_last_updated']}")
        print(f"\n  Pre-tournament scan requires pre-tournament odds.")
        print(f"  Use 'run_live_check.py' for live edge detection instead.")
        return

    for market, data in outrights.items():
        if market.startswith("_"):
            continue
        count = len(data) if isinstance(data, list) else 0
        print(f"  {market}: {count} players")

    print("\nPulling tournament matchups...")
    matchups = pull_tournament_matchups(tournament_slug, tour)
    print(f"  Matchups: {len(matchups)}")

    # Date range for prediction market matching
    tournament_name_for_kalshi = outrights.get("_event_name", "")
    today = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")  # Thu-Sun

    # Pull Kalshi odds (graceful degradation — never blocks DG pipeline)
    print("\nPulling Kalshi odds...")
    try:
        if not tournament_name_for_kalshi:
            print("  Warning: tournament name unknown, skipping Kalshi")
            raise ValueError("No tournament name for Kalshi matching")

        kalshi_outrights = pull_kalshi_outrights(
            tournament_name_for_kalshi, today, end_date,
            tournament_slug=tournament_slug,
        )
        if any(len(v) > 0 for v in kalshi_outrights.values()):
            merge_kalshi_into_outrights(outrights, kalshi_outrights)
            for mkt, players in kalshi_outrights.items():
                if players:
                    print(f"  Kalshi {mkt}: {len(players)} players merged")
        else:
            print("  Kalshi: no outright data available")

        kalshi_matchup_data = pull_kalshi_matchups(
            tournament_name_for_kalshi, today, end_date,
            tournament_slug=tournament_slug,
        )
        if kalshi_matchup_data:
            merge_kalshi_into_matchups(matchups, kalshi_matchup_data)
            print(f"  Kalshi matchups: {len(kalshi_matchup_data)} merged")
    except Exception as e:
        print(f"  Warning: Kalshi unavailable ({e}), proceeding with DG-only")

    # Polymarket outrights
    _pull_polymarket_block(outrights, tournament_name_for_kalshi, today, end_date,
                           tournament_slug=tournament_slug)

    # ProphetX outrights + matchups
    _pull_prophetx_block(outrights, matchups, tournament_name_for_kalshi, today, end_date,
                         tournament_slug=tournament_slug)

    # Merge Start odds if provided
    if args.start_file and matchups:
        print(f"\nMerging Start odds from {args.start_file}...")
        start_matchups = parse_start_matchups_from_file(args.start_file)
        print(f"  Start matchups parsed: {len(start_matchups)}")
        matchups, unmatched = merge_start_into_matchups(matchups, start_matchups)
        matched = len(start_matchups) - len(unmatched)
        print(f"  Matched to DG: {matched} | Unmatched: {len(unmatched)}")
        for u in unmatched:
            print(f"    ? {u['p1_name']} vs {u['p2_name']}")

    # ---- Detect tournament info ----
    is_signature = False
    tournament_name = outrights.get("_event_name") or tournament_slug or "Unknown Tournament"
    tournament_id = None
    dg_event_id = None

    # Resolve event name to DG event ID via event list API
    if outrights.get("_event_name"):
        from src.api.datagolf import DataGolfClient
        dg_event_id = DataGolfClient().resolve_event_id(
            outrights["_event_name"], tour
        )

    # Create/find tournament record in DB
    season = datetime.now().year
    if dg_event_id:
        existing = db.get_tournament(dg_event_id, season)
        if existing:
            tournament_id = existing["id"]
            is_signature = existing.get("is_signature", False)
            print(f"Tournament: {existing['tournament_name']} (existing record)")
        else:
            # Create new tournament — purse defaults to 0, user can update later
            t = db.upsert_tournament(
                tournament_name=tournament_name,
                start_date=datetime.now().strftime("%Y-%m-%d"),
                purse=0,
                dg_event_id=dg_event_id,
                season=season,
            )
            tournament_id = t.get("id")
            print(f"Tournament: {tournament_name} (new record)")
    else:
        print(f"Tournament: {tournament_name} (no DG event ID — exposure limits approximate)")

    if is_signature:
        print(f"  Signature event — using tighter blend weights")

    # ---- Calculate Edges ----
    print(f"\nCalculating edges for {tournament_name}...")
    all_candidates = []

    # Placement edges
    for dg_market, our_market in MARKET_MAP.items():
        data = outrights.get(dg_market, [])
        if not data:
            continue

        edges = calculate_placement_edges(
            data, our_market,
            is_signature=is_signature,
            bankroll=bankroll,
            existing_bets=existing_bets + [
                {"player_name": c.player_name, "opponent_name": c.opponent_name,
                 "opponent_2_name": c.opponent_2_name}
                for c in all_candidates
            ],
        )
        if edges:
            print(f"  {our_market}: {len(edges)} candidates")
            all_candidates.extend(edges)

    # Matchup edges
    if matchups:
        edges = calculate_matchup_edges(
            matchups,
            is_signature=is_signature,
            bankroll=bankroll,
            existing_bets=existing_bets + [
                {"player_name": c.player_name, "opponent_name": c.opponent_name,
                 "opponent_2_name": c.opponent_2_name}
                for c in all_candidates
            ],
        )
        if edges:
            print(f"  matchups: {len(edges)} candidates")
            all_candidates.extend(edges)

    # Sort all candidates by edge
    all_candidates.sort(key=lambda c: c.edge, reverse=True)

    # Resolve player names to canonical IDs (builds alias table over time)
    if all_candidates:
        print("\nResolving player names...")
        resolve_candidates(all_candidates, source="datagolf")

    # Calculate tournament exposure
    tournament_exposure = sum(
        b.get("stake", 0) for b in existing_bets
        if b.get("tournament_id") == tournament_id
    )

    # ---- Arbitrage scan ----
    if matchups:
        print("\nScanning for cross-book arbitrage...")
        arbs = detect_matchup_arbs(matchups, market_type="tournament_matchup")
        if arbs:
            print(f"\n  {len(arbs)} arbitrage opportunit{'y' if len(arbs) == 1 else 'ies'} found:\n")
            print(format_arb_table(arbs))
        else:
            print("  No matchup arbs found.")

    # ---- Display ----
    display_candidates(all_candidates, bankroll, weekly_exposure,
                       tournament_exposure)

    # ---- Interactive Bet Placement ----
    if not args.dry_run and all_candidates:
        interactive_place_bets(all_candidates, tournament_id, bankroll)
    elif args.dry_run:
        print("\n[DRY RUN — no bets logged]")


if __name__ == "__main__":
    main()
