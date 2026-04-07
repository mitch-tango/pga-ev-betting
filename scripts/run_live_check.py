#!/usr/bin/env python3
from __future__ import annotations

"""
Live edge detection — automated edge finding during rounds.

Usage:
    python scripts/run_live_check.py [--dry-run] [--tour pga] [--round N]

Combines DG's live in-play model with current book odds to find edges.
The live model updates every ~5 minutes during rounds and reflects actual
on-course performance — books are often slower to adjust.

For fully manual spot-checking (just DG probabilities, no edge calc),
use the Discord bot's /live command.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from datetime import datetime

from src.pipeline.pull_live_edges import pull_live_edges
from src.core.devig import american_to_decimal
from src.db import supabase_client as db
import config


def _candidate_key(c):
    """Build a lookup key for matching a candidate to its DB record."""
    return (c.player_name, c.market_type, c.opponent_name or "",
            c.opponent_2_name or "", c.round_number)


def insert_all_candidates(candidates, tournament_id, scan_type="live"):
    """Insert all candidates to DB and return a lookup dict."""
    if not candidates or not tournament_id:
        return {}

    rows = [c.to_db_dict(tournament_id, scan_type) for c in candidates]
    inserted = db.insert_candidates(rows)

    lookup = {}
    for record in inserted:
        key = (record["player_name"], record["market_type"],
               record.get("opponent_name") or "",
               record.get("opponent_2_name") or "",
               record.get("round_number"))
        lookup[key] = record["id"]

    print(f"\n  Logged {len(inserted)} candidates to candidate_bets")
    return lookup


def main():
    parser = argparse.ArgumentParser(description="Live in-play edge detection")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tour", default="pga")
    parser.add_argument("--tournament", default=None)
    parser.add_argument("--round", type=int, default=None,
                        help="Round number (1-4)")
    parser.add_argument("--no-kalshi", action="store_true",
                        help="Skip Kalshi odds")
    parser.add_argument("--no-matchups", action="store_true",
                        help="Skip round matchups and 3-balls")
    args = parser.parse_args()

    print(f"=== Live Edge Detection ({args.tour.upper()}) ===")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Edge threshold: {config.MIN_EDGE['live']*100:.0f}% (live)")
    print()

    print("Running live edge scan...")
    candidates, tournament_name, stats = pull_live_edges(
        tour=args.tour,
        tournament_slug=args.tournament,
        include_kalshi=not args.no_kalshi,
        include_matchups=not args.no_matchups,
        round_number=args.round,
    )

    print(f"\nTournament: {tournament_name}")
    print(f"DG live model: {stats.get('live_players', 0)} players")
    print(f"Matched to book odds: {stats.get('matched', 0)}")
    if stats.get("kalshi_merged"):
        print("Kalshi: merged")
    elif stats.get("kalshi_error"):
        print(f"Kalshi: unavailable ({stats['kalshi_error'][:60]})")
    if stats.get("polymarket_merged"):
        print("Polymarket: merged")
    elif stats.get("polymarket_error"):
        print(f"Polymarket: unavailable ({stats['polymarket_error'][:60]})")
    if stats.get("prophetx_merged"):
        print("ProphetX: merged")
    elif stats.get("prophetx_error"):
        print(f"ProphetX: unavailable ({stats['prophetx_error'][:60]})")
    print(f"Bankroll: ${stats.get('bankroll', 0):,.2f}")

    # Show edge breakdown
    for key in ("win_edges", "t10_edges", "t20_edges", "make_cut_edges",
                "matchup_edges", "3ball_edges"):
        if key in stats:
            print(f"  {key.replace('_', ' ').title()}: {stats[key]}")

    if not candidates:
        print("\nNo live edges found above threshold.")
        return

    print(f"\n{len(candidates)} live edge(s) found:\n")
    print(f" {'#':>3}  {'Player':<22} {'Market':<8} {'Best Book':<12} "
          f"{'Odds':>7} {'Your%':>6} {'Book%':>6} {'Edge':>6} "
          f"{'Stake':>6}")
    print(f" {'—'*3}  {'—'*22} {'—'*8} {'—'*12} {'—'*7} {'—'*6} {'—'*6} "
          f"{'—'*6} {'—'*6}")

    for i, c in enumerate(candidates, 1):
        if c.opponent_name:
            display_name = f"{c.player_name[:10]} v {c.opponent_name[:10]}"
        else:
            display_name = c.player_name[:22]

        mkt = c.market_type
        if c.round_number:
            mkt = f"R{c.round_number} " + ("3B" if c.market_type == "3_ball" else "H2H")

        print(f" {i:>3}  {display_name:<22} {mkt:<8} "
              f"{c.best_book:<12} {c.best_odds_american:>7} "
              f"{c.your_prob*100:>5.1f}% {c.best_implied_prob*100:>5.1f}% "
              f"{c.edge*100:>5.1f}% ${c.suggested_stake:>4.0f}")

    print(f"\nIMPORTANT: VERIFY book odds are still available before placing.")

    # ---- Ensure tournament_id for candidate linkage ----
    tournament_id = stats.get("tournament_id")
    if not tournament_id and args.tournament:
        from datetime import datetime as _dt
        season = _dt.now().year
        t = db.upsert_tournament(
            tournament_name=args.tournament,
            start_date=_dt.now().strftime("%Y-%m-%d"),
            purse=0,
            dg_event_id=args.tournament,
            season=season,
        )
        tournament_id = t.get("id")
        print(f"  Created fallback tournament record: {args.tournament}")
    elif not tournament_id:
        print("  Warning: No tournament_id — candidate linkage unavailable. "
              "Use --tournament flag.")

    # ---- Insert candidates to DB ----
    candidate_lookup = {}
    if not args.dry_run and candidates and tournament_id:
        candidate_lookup = insert_all_candidates(
            candidates, tournament_id, scan_type="live"
        )

    if not args.dry_run and candidates:
        print(f"\nLog a live bet? Enter numbers (e.g., 1,3) or 'skip': ", end="")
        response = input().strip()

        if response.lower() in ("skip", "s", ""):
            for c in candidates:
                cid = candidate_lookup.get(_candidate_key(c))
                if cid:
                    db.update_candidate_status(cid, "skipped",
                                               skip_reason="user skipped all")
            print("Skipped.")
            return

        try:
            indices = [int(x.strip()) - 1 for x in response.split(",")]
        except ValueError:
            print("Invalid input. Marking all candidates as skipped.")
            for c in candidates:
                cid = candidate_lookup.get(_candidate_key(c))
                if cid:
                    db.update_candidate_status(cid, "skipped",
                                               skip_reason="malformed selection input")
            return

        placed_indices = set()

        for idx in indices:
            if idx < 0 or idx >= len(candidates):
                print(f"Invalid number: {idx + 1}")
                continue

            c = candidates[idx]
            candidate_id = candidate_lookup.get(_candidate_key(c))

            display = c.player_name
            if c.opponent_name:
                display = f"{c.player_name} vs {c.opponent_name}"

            print(f"\n--- Bet #{idx+1}: {display} {c.market_type} — "
                  f"{c.best_book} {c.best_odds_american} ---")

            actual_odds_str = input(
                f"  Actual odds? [{c.best_odds_american}]: "
            ).strip()
            if not actual_odds_str:
                actual_odds_str = c.best_odds_american

            actual_decimal = american_to_decimal(actual_odds_str)
            if actual_decimal is None:
                print("  Invalid odds. Skipping.")
                if candidate_id:
                    db.update_candidate_status(candidate_id, "skipped",
                                               skip_reason="invalid odds entry")
                continue

            actual_implied = 1.0 / actual_decimal if actual_decimal > 0 else 0
            actual_edge = c.your_prob - actual_implied

            if actual_edge <= 0:
                print(f"  Edge gone at {actual_odds_str}. Skipping.")
                if candidate_id:
                    db.update_candidate_status(candidate_id, "skipped",
                                               skip_reason="edge gone at actual odds")
                continue

            stake_str = input(f"  Stake? [${c.suggested_stake:.0f}]: ").strip()
            stake = float(stake_str) if stake_str else c.suggested_stake

            notes = input("  Notes: ").strip() or "live edge"

            bet = db.insert_bet(
                candidate_id=candidate_id,
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
                is_live=True,
                notes=notes,
            )

            if bet:
                print(f"  ✓ Logged LIVE: {display} @ {c.best_book} "
                      f"{actual_odds_str}, ${stake:.0f}, edge {actual_edge*100:.1f}%")
                placed_indices.add(idx)

        # Mark remaining as skipped
        for idx in range(len(candidates)):
            if idx not in placed_indices:
                c = candidates[idx]
                cid = candidate_lookup.get(_candidate_key(c))
                if cid:
                    db.update_candidate_status(cid, "skipped",
                                               skip_reason="not selected")

    elif args.dry_run:
        print("\n[DRY RUN — no bets logged]")


if __name__ == "__main__":
    main()
