#!/usr/bin/env python3
from __future__ import annotations

"""
Live spot-check — exploratory edge detection during rounds.

Usage:
    python scripts/run_live_check.py [--dry-run] [--tour pga]

IMPORTANT: Live betting is EXPLORATORY in v1 (Amendment #6).
- Edge threshold is 8% (vs 3-5% for pre-tournament)
- Book odds may be stale — ALWAYS manually verify before placing
- Only act on edges that are clearly large enough to survive line movement
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from datetime import datetime

from src.pipeline.pull_live import pull_live_predictions
from src.core.devig import parse_american_odds, implied_prob_to_decimal, decimal_to_american, american_to_decimal
from src.db import supabase_client as db
import config


def main():
    parser = argparse.ArgumentParser(description="Live in-play edge spot-check")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tour", default="pga")
    parser.add_argument("--tournament", default=None)
    args = parser.parse_args()

    bankroll = db.get_bankroll()
    min_edge = config.MIN_EDGE["live"]  # 8%

    print(f"=== Live Spot-Check ({args.tour.upper()}) ===")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Edge threshold: {min_edge*100:.0f}% (EXPLORATORY)")
    print(f"Bankroll: ${bankroll:.2f}")
    print()

    # Pull DG live predictions
    print("Pulling DG live predictions...")
    live_data = pull_live_predictions(args.tournament, args.tour)

    if not live_data:
        print("No live data available (tournament may not be in progress).")
        return

    print(f"  {len(live_data)} players in live model")

    # Display players where DG's live T20 probability is notably high
    # These are the ones where stale book odds might still offer value
    print(f"\n{'--- DG Live T20 Probabilities (Top 30) ---':^60}")
    print(f" {'#':>3}  {'Player':<25} {'Win%':>6} {'T5%':>6} {'T20%':>6} {'MC%':>6}")

    # Sort by T20 probability
    sorted_players = sorted(
        live_data,
        key=lambda p: p.get("top_20", p.get("t20", 0)) or 0,
        reverse=True,
    )

    for i, player in enumerate(sorted_players[:30], 1):
        name = player.get("player_name", "Unknown")
        win_pct = (player.get("win", 0) or 0) * 100
        t5_pct = (player.get("top_5", player.get("t5", 0)) or 0) * 100
        t20_pct = (player.get("top_20", player.get("t20", 0)) or 0) * 100
        mc_pct = (player.get("make_cut", player.get("mc", 0)) or 0) * 100

        print(f" {i:>3}  {name:<25} {win_pct:>5.1f}% {t5_pct:>5.1f}% "
              f"{t20_pct:>5.1f}% {mc_pct:>5.1f}%")

    print(f"\n{'--- How to Use ---':^60}")
    print(f"1. Compare DG's T20% above against the current book line")
    print(f"2. If DG T20% exceeds book implied prob by {min_edge*100:.0f}%+, "
          f"consider betting")
    print(f"3. MANUALLY verify the book's current odds before placing")
    print(f"4. Log the bet using the interactive prompt below")

    if not args.dry_run:
        print(f"\nLog a live bet? [y/N]: ", end="")
        response = input().strip()

        if response.lower() in ("y", "yes"):
            player_name = input("  Player name: ").strip()
            market_type = input("  Market (t20/t10/t5/win): ").strip()
            book = input("  Book: ").strip()
            odds_str = input("  Odds (American): ").strip()
            your_prob_str = input("  Your probability (from DG above, e.g., 0.45): ").strip()
            stake_str = input("  Stake: $").strip()
            notes = input("  Notes: ").strip() or None

            try:
                actual_decimal = american_to_decimal(odds_str)
                actual_implied = 1.0 / actual_decimal if actual_decimal else 0
                your_prob = float(your_prob_str)
                stake = float(stake_str)
                edge = your_prob - actual_implied

                if edge < min_edge:
                    print(f"  Warning: edge is only {edge*100:.1f}% "
                          f"(below {min_edge*100:.0f}% threshold)")
                    print(f"  Place anyway? [y/N]: ", end="")
                    if input().strip().lower() not in ("y", "yes"):
                        print("  Skipped.")
                        return

                bet = db.insert_bet(
                    candidate_id=None,
                    tournament_id=None,
                    market_type=market_type,
                    player_name=player_name,
                    book=book,
                    odds_at_bet_decimal=actual_decimal,
                    odds_at_bet_american=odds_str,
                    implied_prob_at_bet=actual_implied,
                    your_prob=your_prob,
                    edge=edge,
                    stake=stake,
                    is_live=True,
                    notes=notes,
                )

                if bet:
                    print(f"  ✓ Logged LIVE bet: {player_name} {market_type} "
                          f"@ {book} {odds_str}, ${stake:.0f}, "
                          f"edge {edge*100:.1f}%")
            except (ValueError, TypeError) as e:
                print(f"  Error: {e}")
    else:
        print("\n[DRY RUN — no bets logged]")


if __name__ == "__main__":
    main()
