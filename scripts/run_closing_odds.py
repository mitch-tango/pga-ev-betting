#!/usr/bin/env python3
from __future__ import annotations

"""
Closing odds capture — run just before tournament/round start.

Usage:
    python scripts/run_closing_odds.py [--tour pga] [--tournament NAME]

Captures closing odds for all placement and matchup markets, stores
snapshots in Supabase, and computes CLV for all placed bets.

Tournament ID is auto-detected (from outrights data or this week's bets).
Pass --tournament-id to override.

When to run:
- Pre-tournament placements: Thursday morning, before R1 tee times
- Round matchups/3-balls: Before each round's first tee time
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from datetime import datetime, timedelta

from src.pipeline.pull_closing import (
    pull_closing_outrights, pull_closing_matchups, build_closing_snapshots,
)
from src.pipeline.pull_kalshi import (
    pull_kalshi_outrights, pull_kalshi_matchups,
    merge_kalshi_into_outrights, merge_kalshi_into_matchups,
)
from src.pipeline.pull_polymarket import (
    pull_polymarket_outrights, merge_polymarket_into_outrights,
)
from src.pipeline.pull_prophetx import (
    pull_prophetx_outrights, pull_prophetx_matchups,
    merge_prophetx_into_outrights, merge_prophetx_into_matchups,
)
from src.core.devig import parse_american_odds
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


def build_closing_matchup_snapshots(
    round_matchups: list[dict],
    three_balls: list[dict],
    tournament_id: str | None,
) -> list[dict]:
    """Convert matchup/3-ball odds into closing snapshot records.

    DG matchup format: {"p1_player_name": ..., "p2_player_name": ...,
                        "odds": {"book": {"p1": "-130", "p2": "+110"}, ...}}
    """
    from datetime import timezone
    now = datetime.now(timezone.utc).isoformat()
    snapshots = []

    for m in round_matchups:
        odds_by_book = m.get("odds", {})
        for side in ("p1", "p2"):
            player_name = m.get(f"{side}_player_name", "").strip()
            if not player_name:
                continue
            opponent = "p2" if side == "p1" else "p1"

            # Extract this player's odds from each book
            book_odds = {}
            for book_name, book_data in odds_by_book.items():
                if isinstance(book_data, dict) and side in book_data:
                    book_odds[book_name] = book_data[side]

            snapshot = {
                "snapshot_type": "closing",
                "snapshot_timestamp": now,
                "market_type": "round_matchup",
                "player_name": player_name,
                "player_dg_id": str(m.get(f"{side}_dg_id", "")),
                "opponent_name": m.get(f"{opponent}_player_name", ""),
                "book_odds": book_odds if book_odds else None,
            }
            if tournament_id:
                snapshot["tournament_id"] = tournament_id
            snapshots.append(snapshot)

    for tb in three_balls:
        odds_by_book = tb.get("odds", {})
        for side in ("p1", "p2", "p3"):
            player_name = tb.get(f"{side}_player_name", "").strip()
            if not player_name:
                continue

            book_odds = {}
            for book_name, book_data in odds_by_book.items():
                if isinstance(book_data, dict) and side in book_data:
                    book_odds[book_name] = book_data[side]

            snapshot = {
                "snapshot_type": "closing",
                "snapshot_timestamp": now,
                "market_type": "3_ball",
                "player_name": player_name,
                "player_dg_id": str(tb.get(f"{side}_dg_id", "")),
                "book_odds": book_odds if book_odds else None,
            }
            if tournament_id:
                snapshot["tournament_id"] = tournament_id
            snapshots.append(snapshot)

    return snapshots


def detect_tournament_id(outrights: dict, cli_override: str | None) -> str | None:
    """Auto-detect tournament ID, matching run_pretournament/run_preround flow.

    Priority:
    1. CLI override (--tournament-id)
    2. DG event ID from outrights data -> DB lookup
    3. Most recent tournament_id from this week's bets
    """
    if cli_override:
        print(f"  Using CLI tournament_id: {cli_override}")
        return cli_override

    # Try resolving event name from outrights metadata (same as run_pretournament)
    event_name = outrights.get("_event_name")
    if event_name:
        from src.api.datagolf import DataGolfClient
        dg_event_id = DataGolfClient().resolve_event_id(event_name)
        if dg_event_id:
            season = datetime.now().year
            existing = db.get_tournament(dg_event_id, season)
            if existing:
                print(f"  Auto-detected: {existing['tournament_name']} (from DG event ID)")
                return existing["id"]

    # Fallback: most recent tournament from this week's bets (same as run_preround)
    existing_bets = db.get_open_bets_for_week()
    for b in sorted(existing_bets, key=lambda x: x.get("bet_timestamp", ""),
                    reverse=True):
        if b.get("tournament_id"):
            t = db.get_tournament_by_id(b["tournament_id"])
            name = t.get("tournament_name", b["tournament_id"]) if t else b["tournament_id"]
            print(f"  Auto-detected: {name} (from this week's bets)")
            return b["tournament_id"]

    print("  Warning: Could not detect tournament_id — CLV matching will be skipped")
    return None


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
    args = parser.parse_args()

    print(f"=== Closing Odds Capture ===")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Pull closing outright odds
    print("\nPulling closing outright odds...")
    outrights = pull_closing_outrights(args.tournament, args.tour)
    for market, data in outrights.items():
        if market.startswith("_"):
            continue
        count = len(data) if isinstance(data, list) else 0
        print(f"  {market}: {count} players")

    # Merge prediction market closing odds
    tournament_name = outrights.get("_event_name", "")
    today = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")

    # Kalshi
    if tournament_name:
        print("\nPulling Kalshi closing odds...")
        try:
            kalshi_outrights = pull_kalshi_outrights(
                tournament_name, today, end_date,
                tournament_slug=args.tournament,
            )
            if any(len(v) > 0 for v in kalshi_outrights.values()):
                merge_kalshi_into_outrights(outrights, kalshi_outrights)
                for mkt, players in kalshi_outrights.items():
                    if players:
                        print(f"  Kalshi {mkt}: {len(players)} players merged")
            else:
                print("  Kalshi: no data")
        except Exception as e:
            print(f"  Kalshi unavailable ({e})")

    # Polymarket
    if getattr(config, "POLYMARKET_ENABLED", False) and tournament_name:
        print("Pulling Polymarket closing odds...")
        try:
            pm_outrights = pull_polymarket_outrights(
                tournament_name, today, end_date,
                tournament_slug=args.tournament,
            )
            if any(len(v) > 0 for v in pm_outrights.values()):
                merge_polymarket_into_outrights(outrights, pm_outrights)
                for mkt, players in pm_outrights.items():
                    if players:
                        print(f"  Polymarket {mkt}: {len(players)} players merged")
            else:
                print("  Polymarket: no data")
        except Exception as e:
            print(f"  Polymarket unavailable ({e})")

    # ProphetX
    if getattr(config, "PROPHETX_ENABLED", False) and tournament_name:
        print("Pulling ProphetX closing odds...")
        try:
            px_outrights = pull_prophetx_outrights(
                tournament_name, today, end_date,
                tournament_slug=args.tournament,
            )
            if any(len(v) > 0 for v in px_outrights.values()):
                merge_prophetx_into_outrights(outrights, px_outrights)
                for mkt, players in px_outrights.items():
                    if players:
                        print(f"  ProphetX {mkt}: {len(players)} players merged")
            else:
                print("  ProphetX: no data")
        except Exception as e:
            print(f"  ProphetX unavailable ({e})")

    # Auto-detect tournament ID
    print("\nDetecting tournament...")
    tournament_id = detect_tournament_id(outrights, args.tournament_id)

    # Build outright snapshots
    snapshots = build_closing_snapshots(outrights, tournament_id)
    print(f"\nBuilt {len(snapshots)} outright closing snapshots")

    # Pull and build matchup snapshots
    # Auto-detect: capture matchups on Thu-Sun (round days) unless --no-matchups
    capture_matchups = args.matchups
    if capture_matchups is None and not args.no_matchups:
        day_of_week = datetime.now().weekday()  # 0=Mon, 3=Thu, 6=Sun
        capture_matchups = day_of_week >= 3  # Thu-Sun
        if capture_matchups:
            print(f"\nAuto-detecting round day — capturing matchup closing odds")

    if capture_matchups:
        print("\nPulling closing matchup odds...")
        matchup_data = pull_closing_matchups(args.tournament, args.tour)
        round_matchups = matchup_data.get("round_matchups", [])
        three_balls = matchup_data.get("3_balls", [])
        print(f"  Round matchups: {len(round_matchups)}")
        print(f"  3-balls: {len(three_balls)}")

        # Merge prediction market matchups
        if tournament_name:
            try:
                kalshi_matchups = pull_kalshi_matchups(
                    tournament_name, today, end_date,
                    tournament_slug=args.tournament,
                )
                if kalshi_matchups and round_matchups:
                    merge_kalshi_into_matchups(round_matchups, kalshi_matchups)
                    print(f"  Kalshi matchups: {len(kalshi_matchups)} merged")
            except Exception as e:
                print(f"  Kalshi matchups unavailable ({e})")

            if getattr(config, "PROPHETX_ENABLED", False):
                try:
                    px_matchups = pull_prophetx_matchups(
                        tournament_name, today, end_date,
                        tournament_slug=args.tournament,
                    )
                    if px_matchups and round_matchups:
                        merge_prophetx_into_matchups(round_matchups, px_matchups)
                        print(f"  ProphetX matchups: {len(px_matchups)} merged")
                except Exception as e:
                    print(f"  ProphetX matchups unavailable ({e})")

        matchup_snapshots = build_closing_matchup_snapshots(
            round_matchups, three_balls, tournament_id
        )
        snapshots.extend(matchup_snapshots)
        print(f"  Built {len(matchup_snapshots)} matchup closing snapshots")

    # Store in Supabase
    if snapshots:
        stored = db.insert_odds_snapshots(snapshots)
        print(f"Stored {len(stored)} total snapshots in Supabase")

    # Match to placed bets and compute CLV
    print("\nMatching closing odds to placed bets...")
    matched = match_closing_to_bets(snapshots, tournament_id)
    print(f"CLV computed for {matched} bets")

    # Show CLV summary
    if tournament_id:
        bets = db.get_bets_for_tournament(tournament_id)
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
