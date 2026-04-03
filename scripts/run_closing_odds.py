#!/usr/bin/env python3
from __future__ import annotations

"""
Closing odds capture — run just before tournament/round start.

Usage:
    python scripts/run_closing_odds.py [--tour pga] [--tournament NAME]

Captures closing odds for all placement markets, stores snapshots
in Supabase, and computes CLV for all placed bets.

When to run:
- Pre-tournament placements: Thursday morning, before R1 tee times
- Round matchups/3-balls: Before each round's first tee time
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from datetime import datetime

from src.pipeline.pull_closing import (
    pull_closing_outrights, build_closing_snapshots,
)
from src.core.devig import parse_american_odds, devig_independent, power_devig
from src.db import supabase_client as db
import config


def match_closing_to_bets(snapshots: list[dict], tournament_id: str | None):
    """Match closing odds to placed bets and compute CLV.

    For each unsettled bet, find the matching closing snapshot and
    update the bet with closing odds + CLV.
    """
    if not tournament_id:
        print("  No tournament_id — skipping CLV matching")
        return 0

    # Get all unsettled bets for this tournament
    bets = db.get_unsettled_bets(tournament_id)
    if not bets:
        print("  No unsettled bets to match")
        return 0

    # Build lookup from snapshots
    # Key: (market_type, player_name_lower)
    snapshot_lookup = {}
    for snap in snapshots:
        key = (snap["market_type"], snap["player_name"].lower().strip())
        snapshot_lookup[key] = snap

    matched = 0
    for bet in bets:
        if bet.get("clv") is not None:
            continue  # Already has CLV

        market = bet["market_type"]
        player = bet["player_name"].lower().strip()
        key = (market, player)

        snap = snapshot_lookup.get(key)
        if not snap:
            continue

        # Find the closing odds at the book where the bet was placed
        book = bet["book"]
        book_odds = snap.get("book_odds", {})
        closing_odds_str = book_odds.get(book)

        if not closing_odds_str:
            continue

        closing_implied = parse_american_odds(closing_odds_str)
        if closing_implied is None:
            continue

        # Compute decimal odds for storage
        from src.core.devig import american_to_decimal
        closing_decimal = american_to_decimal(closing_odds_str)

        # Update the bet
        db.update_bet_closing(
            bet_id=bet["id"],
            closing_odds_decimal=closing_decimal,
            closing_implied_prob=closing_implied,
        )
        matched += 1

    return matched


def main():
    parser = argparse.ArgumentParser(
        description="Capture closing odds and compute CLV"
    )
    parser.add_argument("--tour", default="pga")
    parser.add_argument("--tournament", default=None,
                        help="Tournament slug for cache")
    parser.add_argument("--tournament-id", default=None,
                        help="Supabase tournament UUID")
    args = parser.parse_args()

    print(f"=== Closing Odds Capture ===")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Pull closing outright odds
    print("\nPulling closing outright odds...")
    outrights = pull_closing_outrights(args.tournament, args.tour)
    for market, data in outrights.items():
        count = len(data) if isinstance(data, list) else 0
        print(f"  {market}: {count} players")

    # Build snapshots
    snapshots = build_closing_snapshots(outrights, args.tournament_id)
    print(f"\nBuilt {len(snapshots)} closing snapshots")

    # Store in Supabase
    if snapshots:
        stored = db.insert_odds_snapshots(snapshots)
        print(f"Stored {len(stored)} snapshots in Supabase")

    # Match to placed bets and compute CLV
    print("\nMatching closing odds to placed bets...")
    matched = match_closing_to_bets(snapshots, args.tournament_id)
    print(f"CLV computed for {matched} bets")

    # Show CLV summary
    if args.tournament_id:
        bets = db.get_bets_for_tournament(args.tournament_id)
        clv_bets = [b for b in bets if b.get("clv") is not None]
        if clv_bets:
            avg_clv = sum(b["clv"] for b in clv_bets) / len(clv_bets)
            positive = sum(1 for b in clv_bets if b["clv"] > 0)
            print(f"\nCLV Summary:")
            print(f"  Bets with CLV: {len(clv_bets)}")
            print(f"  Avg CLV: {avg_clv*100:.2f}%")
            print(f"  Positive CLV: {positive}/{len(clv_bets)}")


if __name__ == "__main__":
    main()
