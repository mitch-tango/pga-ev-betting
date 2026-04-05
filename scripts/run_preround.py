#!/usr/bin/env python3
from __future__ import annotations

"""
Pre-round scan — daily workflow for round matchups and 3-balls.

Usage:
    python scripts/run_preround.py [--dry-run] [--round N] [--tour pga]

Run each morning Thu-Sun once pairings are set.
Pulls round matchup and 3-ball odds, calculates edges, interactive bet placement.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from datetime import datetime, timedelta

from src.pipeline.pull_matchups import pull_round_matchups, pull_3balls
from src.pipeline.pull_kalshi import (
    pull_kalshi_matchups, merge_kalshi_into_matchups,
)
from src.parsers.start_matchups import parse_start_matchups_from_file
from src.parsers.start_merger import merge_start_into_matchups
from src.core.edge import calculate_matchup_edges, calculate_3ball_edges
from src.core.devig import american_to_decimal, decimal_to_american
from src.normalize.players import resolve_candidates
from src.db import supabase_client as db
import config


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
    print(f" {'#':>3}  {'Player':<22} {'Market':<10} {'Best Book':<12} "
          f"{'Odds':>7} {'Your%':>6} {'Book%':>6} {'Edge':>6} "
          f"{'Stake':>6} {'Corr':>5}")
    print(f" {'—'*3}  {'—'*22} {'—'*10} {'—'*12} {'—'*7} {'—'*6} {'—'*6} "
          f"{'—'*6} {'—'*6} {'—'*5}")

    for i, c in enumerate(candidates, 1):
        if c.opponent_2_name:
            display_name = f"{c.player_name[:7]} 3B"
        elif c.opponent_name:
            display_name = f"{c.player_name[:10]} v {c.opponent_name[:10]}"
        else:
            display_name = c.player_name[:22]

        corr_flag = f"{c.correlation_haircut:.1f}x"
        if c.correlation_haircut < 1.0:
            corr_flag += " ⚠️"

        market_display = c.market_type
        if c.round_number:
            market_display = f"R{c.round_number} " + (
                "3ball" if c.market_type == "3_ball" else "H2H"
            )

        print(f" {i:>3}  {display_name:<22} {market_display:<10} "
              f"{c.best_book:<12} {c.best_odds_american:>7} "
              f"{c.your_prob*100:>5.1f}% {c.best_implied_prob*100:>5.1f}% "
              f"{c.edge*100:>5.1f}% ${c.suggested_stake:>4.0f} {corr_flag:>5}")


def interactive_place_bets(candidates, tournament_id, bankroll):
    """Interactive CLI for placing bets."""
    if not candidates:
        return

    print(f"\nPlace bets? Enter numbers (e.g., 1,3,5) or 'skip all': ", end="")
    response = input().strip()

    if response.lower() in ("skip", "skip all", "s", ""):
        reason = input("Skip reason (optional): ").strip()
        print(f"Skipped all.{' Reason: ' + reason if reason else ''}")
        return

    try:
        indices = [int(x.strip()) - 1 for x in response.split(",")]
    except ValueError:
        print("Invalid input. Skipping.")
        return

    for idx in indices:
        if idx < 0 or idx >= len(candidates):
            print(f"Invalid bet number: {idx + 1}")
            continue

        c = candidates[idx]
        display = c.player_name
        if c.opponent_name:
            display = f"{c.player_name} vs {c.opponent_name}"
            if c.opponent_2_name:
                display += f" vs {c.opponent_2_name}"

        market_display = c.market_type
        if c.round_number:
            market_display = f"R{c.round_number} {c.market_type}"

        print(f"\n--- Bet #{idx+1}: {display} {market_display} — "
              f"{c.best_book} {c.best_odds_american} (scanned) ---")

        actual_odds_str = input(
            f"  Actual odds placed? [{c.best_odds_american}]: "
        ).strip()
        if not actual_odds_str:
            actual_odds_str = c.best_odds_american

        actual_decimal = american_to_decimal(actual_odds_str)
        if actual_decimal is None:
            print(f"  Invalid odds. Skipping.")
            continue

        actual_implied = 1.0 / actual_decimal if actual_decimal > 0 else 0
        actual_edge = c.your_prob - actual_implied

        if actual_edge <= 0:
            print(f"  Edge gone at {actual_odds_str}. Skip? [y/N]: ", end="")
            if input().strip().lower() in ("y", "yes"):
                continue

        stake_str = input(f"  Stake? [${c.suggested_stake:.0f}]: ").strip()
        stake = float(stake_str) if stake_str else c.suggested_stake

        notes = input("  Notes (optional): ").strip() or None

        bet = db.insert_bet(
            candidate_id=None,
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
            print(f"  ✓ Logged: {display} @ {c.best_book} {actual_odds_str}, "
                  f"${stake:.0f}, edge {actual_edge*100:.1f}%")

    new_balance = db.get_bankroll()
    print(f"\nBankroll: ${new_balance:.2f}")


def main():
    parser = argparse.ArgumentParser(description="Pre-round matchup + 3-ball scan")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--round", type=int, default=None,
                        help="Round number (1-4)")
    parser.add_argument("--tour", default="pga")
    parser.add_argument("--tournament", default=None)
    parser.add_argument("--start-file", default=None,
                        help="Path to copy-pasted Start matchup odds text file")
    args = parser.parse_args()

    bankroll = db.get_bankroll()
    if bankroll <= 0:
        print("No bankroll found.")
        return

    existing_bets = db.get_open_bets_for_week()
    weekly_exposure = sum(b.get("stake", 0) for b in existing_bets)

    round_str = f" R{args.round}" if args.round else ""
    print(f"=== Pre-Round Scan{round_str} ({args.tour.upper()}) ===")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Detect active tournament from this week's bets
    tournament_id = None
    if existing_bets:
        # Most recent tournament_id from this week's bets
        for b in sorted(existing_bets, key=lambda x: x.get("bet_timestamp", ""),
                        reverse=True):
            if b.get("tournament_id"):
                tournament_id = b["tournament_id"]
                break
    if tournament_id:
        t = db.get_tournament_by_id(tournament_id)
        if t:
            print(f"Active tournament: {t.get('tournament_name', tournament_id)}")
    else:
        print("Warning: No active tournament detected (exposure limits approximate)")

    # Pull round matchups
    print("\nPulling round matchups...")
    round_matchups = pull_round_matchups(args.tournament, args.tour)
    print(f"  Round matchups: {len(round_matchups)}")

    # Merge Start odds if provided
    if args.start_file and round_matchups:
        print(f"\nMerging Start odds from {args.start_file}...")
        start_matchups = parse_start_matchups_from_file(args.start_file)
        print(f"  Start matchups parsed: {len(start_matchups)}")
        round_matchups, unmatched = merge_start_into_matchups(
            round_matchups, start_matchups
        )
        matched = len(start_matchups) - len(unmatched)
        print(f"  Matched to DG: {matched} | Unmatched: {len(unmatched)}")
        for u in unmatched:
            print(f"    ? {u['p1_name']} vs {u['p2_name']}")

    # Kalshi tournament matchups (guard: skip if no live DG model)
    # Kalshi tournament-long prices reflect in-tournament performance.
    # Comparing live Kalshi prices against stale pre-tournament DG would
    # create false-positive edges, so we skip unless live DG is available.
    # For now, live DG predictions are not yet implemented, so always skip.
    kalshi_enabled = False  # TODO: set True when get_live_predictions() exists
    if kalshi_enabled:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            # PGA tournaments run Thu-Sun (4 days)
            end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
            tournament_name_for_kalshi = ""
            if tournament_id:
                t = db.get_tournament_by_id(tournament_id)
                if t:
                    tournament_name_for_kalshi = t.get("tournament_name", "")
            if tournament_name_for_kalshi:
                kalshi_matchup_data = pull_kalshi_matchups(
                    tournament_name_for_kalshi, today, end_date,
                    tournament_slug=args.tournament,
                )
                if kalshi_matchup_data and round_matchups:
                    merge_kalshi_into_matchups(round_matchups, kalshi_matchup_data)
                    print(f"  Kalshi tournament matchups: {len(kalshi_matchup_data)} merged")
        except Exception as e:
            print(f"  Warning: Kalshi unavailable ({e}), proceeding without")
    else:
        print("  Skipping Kalshi tournament markets (no live DG model — stale model risk)")

    # TODO: Polymarket integration — pull_polymarket_outrights() would follow
    # the same pattern here. Polymarket covers win/T10/T20 but NOT matchups.
    # Requires keyword-based event discovery (no golf-specific ticker).

    # Pull 3-balls
    print("Pulling 3-ball odds...")
    three_balls = pull_3balls(args.tournament, args.tour)
    print(f"  3-balls: {len(three_balls)}")

    # Calculate edges
    all_candidates = []

    if round_matchups:
        edges = calculate_matchup_edges(
            round_matchups, bankroll=bankroll,
            existing_bets=existing_bets,
            market_type="round_matchup",
        )
        # Tag with round number
        for e in edges:
            e.round_number = args.round
        if edges:
            print(f"  Round matchup edges: {len(edges)}")
            all_candidates.extend(edges)

    if three_balls:
        edges = calculate_3ball_edges(
            three_balls, bankroll=bankroll,
            existing_bets=existing_bets + [
                {"player_name": c.player_name, "opponent_name": c.opponent_name,
                 "opponent_2_name": c.opponent_2_name}
                for c in all_candidates
            ],
            round_number=args.round,
        )
        if edges:
            print(f"  3-ball edges: {len(edges)}")
            all_candidates.extend(edges)

    all_candidates.sort(key=lambda c: c.edge, reverse=True)

    # Resolve player names to canonical IDs
    if all_candidates:
        print("\nResolving player names...")
        resolve_candidates(all_candidates, source="datagolf")

    tournament_exposure = sum(
        b.get("stake", 0) for b in existing_bets
        if b.get("tournament_id") == tournament_id
    ) if tournament_id else 0

    display_candidates(all_candidates, bankroll, weekly_exposure, tournament_exposure)

    if not args.dry_run and all_candidates:
        interactive_place_bets(all_candidates, tournament_id, bankroll)
    elif args.dry_run:
        print("\n[DRY RUN — no bets logged]")


if __name__ == "__main__":
    main()
