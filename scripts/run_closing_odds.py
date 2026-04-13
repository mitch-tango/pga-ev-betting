#!/usr/bin/env python3
from __future__ import annotations

"""
Closing odds capture — run just before tournament/round start.

Usage:
    python scripts/run_closing_odds.py [--tour pga] [--tournament NAME]

Thin CLI wrapper around `src.pipeline.pull_closing.run_closing_capture`.
That function contains all the orchestration (pull + merge + store + CLV
match) and is shared with the Discord bot's scheduled closing capture
(`_run_scheduled_closing_capture` in `src/discord_bot/bot.py`).

When to run:
- Pre-tournament placements: Thursday morning, before R1 tee times
- Round matchups/3-balls: Before each round's first tee time
- Tournament matchups: Thursday morning only (one snapshot per week)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from datetime import datetime

from src.pipeline.pull_closing import run_closing_capture


def main():
    parser = argparse.ArgumentParser(
        description="Capture closing odds and compute CLV"
    )
    parser.add_argument("--tour", default="pga")
    parser.add_argument("--tournament", default=None,
                        help="Tournament slug for cache")
    parser.add_argument("--tournament-id", default=None,
                        help="Supabase tournament UUID (auto-detected if omitted)")
    parser.add_argument("--matchups", action="store_true", default=None,
                        help="Capture closing matchup/3-ball odds (auto-detected Thu-Sun)")
    parser.add_argument("--no-matchups", action="store_true",
                        help="Skip matchup closing capture even on round days")
    parser.add_argument("--tournament-matchups", action="store_true",
                        default=None,
                        help="Force-capture tournament matchup closing odds "
                             "(auto-detected on Thursday; use this to "
                             "recover if Thursday run was missed)")
    args = parser.parse_args()

    day_of_week = datetime.now().weekday()  # 0=Mon, 3=Thu, 6=Sun

    # Auto-detect capture flags the same way the scheduler does
    capture_matchups = args.matchups
    if capture_matchups is None and not args.no_matchups:
        capture_matchups = day_of_week >= 3  # Thu-Sun

    capture_tournament_matchups = args.tournament_matchups
    if capture_tournament_matchups is None:
        capture_tournament_matchups = day_of_week == 3  # Thursday only

    print(f"=== Closing Odds Capture ===")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Matchups: {capture_matchups} | "
          f"Tournament matchups: {capture_tournament_matchups}")

    summary = run_closing_capture(
        tour=args.tour,
        tournament_slug=args.tournament,
        tournament_id_override=args.tournament_id,
        capture_matchups=bool(capture_matchups),
        capture_tournament_matchups=bool(capture_tournament_matchups),
    )

    print(f"\nTournament: {summary['tournament_name']}")
    print(f"Outright snapshots: {summary['outright_snapshots']}")
    if summary['captured_matchups']:
        print(f"Round matchup snapshots: {summary['round_matchup_snapshots']}")
        print(f"3-ball snapshots: {summary['three_ball_snapshots']}")
    if summary['captured_tournament_matchups']:
        print(f"Tournament matchup snapshots: "
              f"{summary['tournament_matchup_snapshots']}")
    print(f"Total stored in Supabase: {summary['total_snapshots_stored']}")
    print(f"\nCLV newly computed for {summary['bets_matched']} bet(s)")

    if summary['clv_bets_total']:
        print(f"\nCLV Summary ({summary['clv_bets_total']} bets with CLV):")
        if summary['avg_clv_pct'] is not None:
            print(f"  Avg CLV: {summary['avg_clv_pct']:.2f}%")
        print(f"  Positive CLV: "
              f"{summary['positive_clv']}/{summary['clv_bets_total']}")

    if summary['errors']:
        print(f"\nNon-fatal errors: {', '.join(summary['errors'])}")


if __name__ == "__main__":
    main()
