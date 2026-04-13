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
from src.pipeline.pull_prophetx import (
    pull_prophetx_matchups, merge_prophetx_into_matchups,
)
from src.parsers.start_matchups import parse_start_matchups_from_file
from src.parsers.start_merger import merge_start_into_matchups
from src.core.edge import calculate_matchup_edges, calculate_3ball_edges
from src.core.arb import (
    arb_legs_to_candidates,
    detect_matchup_arbs, detect_3ball_arbs, format_arb_table,
)
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


def _candidate_key(c):
    """Build a lookup key for matching a candidate to its DB record."""
    return (c.player_name, c.market_type, c.opponent_name or "",
            c.opponent_2_name or "", c.round_number)


def insert_all_candidates(candidates, tournament_id, scan_type="preround"):
    """Insert all candidates to DB and return a lookup dict."""
    if not candidates or not tournament_id:
        return {}

    # Re-running a scan for the same (tournament, scan_type) supersedes
    # any previous pending rows — mark them skipped before inserting the
    # new batch so the fill-rate view stays honest.
    superseded = db.mark_superseded_pending(tournament_id, scan_type)
    if superseded:
        print(f"  Superseded {superseded} prior pending "
              f"{scan_type} candidate(s) from earlier run")

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


def interactive_place_bets(candidates, tournament_id, bankroll, candidate_lookup=None):
    """Interactive CLI for placing bets."""
    if not candidates:
        return
    if candidate_lookup is None:
        candidate_lookup = {}

    print(f"\nPlace bets? Enter numbers (e.g., 1,3,5) or 'skip all': ", end="")
    response = input().strip()

    if response.lower() in ("skip", "skip all", "s", ""):
        reason = input("Skip reason (optional): ").strip() or "user skipped all"
        for c in candidates:
            cid = candidate_lookup.get(_candidate_key(c))
            if cid:
                db.update_candidate_status(cid, "skipped", skip_reason=reason)
        print(f"Skipped all.{' Reason: ' + reason if reason else ''}")
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
            print(f"Invalid bet number: {idx + 1}")
            continue

        c = candidates[idx]
        candidate_id = candidate_lookup.get(_candidate_key(c))

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
            if candidate_id:
                db.update_candidate_status(candidate_id, "skipped",
                                           skip_reason="invalid odds entry")
            continue

        actual_implied = 1.0 / actual_decimal if actual_decimal > 0 else 0
        actual_edge = c.your_prob - actual_implied

        if actual_edge <= 0:
            print(f"  Edge gone at {actual_odds_str}. Skip? [y/N]: ", end="")
            if input().strip().lower() in ("y", "yes"):
                if candidate_id:
                    db.update_candidate_status(candidate_id, "skipped",
                                               skip_reason="edge gone at actual odds")
                continue

        stake_str = input(f"  Stake? [${c.suggested_stake:.0f}]: ").strip()
        stake = float(stake_str) if stake_str else c.suggested_stake

        notes = input("  Notes (optional): ").strip() or None

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
            notes=notes,
        )

        if bet:
            print(f"  ✓ Logged: {display} @ {c.best_book} {actual_odds_str}, "
                  f"${stake:.0f}, edge {actual_edge*100:.1f}%")
            placed_indices.add(idx)

    # Mark remaining as skipped
    skipped_indices = set(range(len(candidates))) - placed_indices
    if skipped_indices:
        reason = input(
            f"\nSkip reason for remaining {len(skipped_indices)} candidates? "
            f"(optional): "
        ).strip() or "not selected"
        for idx in skipped_indices:
            c = candidates[idx]
            cid = candidate_lookup.get(_candidate_key(c))
            if cid:
                db.update_candidate_status(cid, "skipped", skip_reason=reason)

    new_balance = db.get_bankroll()
    print(f"\nBankroll: ${new_balance:.2f}")


def _pull_prophetx_matchup_block(matchups, tournament_name, today, end_date,
                                 tournament_slug=None):
    """Pull and merge ProphetX matchups. Graceful degradation on failure."""
    if not config.PROPHETX_ENABLED:
        print("\nProphetX: disabled")
        return
    if not tournament_name:
        return
    print("\nPulling ProphetX matchups...")
    try:
        prophetx_matchup_data = pull_prophetx_matchups(
            tournament_name, today, end_date,
            tournament_slug=tournament_slug,
        )
        if prophetx_matchup_data and matchups:
            merge_prophetx_into_matchups(matchups, prophetx_matchup_data)
            print(f"  ProphetX matchups: {len(prophetx_matchup_data)} merged")
        else:
            print("  ProphetX: no matchup data available")
    except Exception as e:
        print(f"  Warning: ProphetX unavailable ({e}), proceeding without")


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
        # No active tournament from bets — create fallback record for candidate linkage
        if args.tournament:
            season = datetime.now().year
            t = db.upsert_tournament(
                tournament_name=args.tournament,
                start_date=datetime.now().strftime("%Y-%m-%d"),
                purse=0,
                dg_event_id=args.tournament,
                season=season,
            )
            tournament_id = t.get("id")
            print(f"Warning: No active tournament from bets — created fallback: {args.tournament}")
        else:
            print("Warning: No active tournament detected and no --tournament flag. "
                  "Candidate linkage will be unavailable.")

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

    # Date range and tournament name for prediction market matching
    today = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")  # Thu-Sun
    tournament_name_for_kalshi = ""
    if tournament_id:
        t = db.get_tournament_by_id(tournament_id)
        if t:
            tournament_name_for_kalshi = t.get("tournament_name", "")

    # Kalshi tournament matchups: enabled when live DG model is available.
    # Kalshi tournament-long prices reflect in-tournament performance.
    # We pull DG live predictions to avoid comparing stale DG vs live Kalshi.
    from src.pipeline.pull_live import pull_live_predictions
    live_data = pull_live_predictions(args.tournament, args.tour)
    kalshi_enabled = len(live_data) > 0
    if live_data:
        print(f"  DG live model: {len(live_data)} players — Kalshi comparison enabled")
    if kalshi_enabled:
        try:
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
        print("  Skipping Kalshi tournament markets (no live DG data available)")

    # Polymarket: skip in preround (outrights only, not relevant for round analysis)

    # ProphetX matchups
    _pull_prophetx_matchup_block(round_matchups, tournament_name_for_kalshi, today, end_date,
                                 tournament_slug=args.tournament)

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

    # ---- Arbitrage scan ----
    print("\nScanning for cross-book arbitrage...")
    arbs = []
    arb_leg_candidates = []
    if round_matchups:
        arbs.extend(detect_matchup_arbs(
            round_matchups, market_type="round_matchup",
            round_number=args.round))
    if three_balls:
        arbs.extend(detect_3ball_arbs(three_balls, round_number=args.round))
    if arbs:
        arbs.sort(key=lambda a: a.margin, reverse=True)
        print(f"\n  {len(arbs)} arbitrage opportunit{'y' if len(arbs) == 1 else 'ies'} found:\n")
        print(format_arb_table(arbs))
        arb_leg_candidates = arb_legs_to_candidates(arbs)
        if arb_leg_candidates:
            resolve_candidates(arb_leg_candidates, source="datagolf")
    else:
        print("  No arbs found.")

    display_candidates(all_candidates, bankroll, weekly_exposure, tournament_exposure)

    # ---- Insert candidates to DB ----
    candidate_lookup = {}
    if not args.dry_run and all_candidates and tournament_id:
        candidate_lookup = insert_all_candidates(
            all_candidates, tournament_id, scan_type="preround"
        )

    # Arb legs get a distinct scan_type so +EV analytics views can
    # filter them out.
    if not args.dry_run and arb_leg_candidates and tournament_id:
        arb_lookup = insert_all_candidates(
            arb_leg_candidates, tournament_id, scan_type="preround_arb"
        )
        candidate_lookup.update(arb_lookup)
        all_candidates = list(all_candidates) + list(arb_leg_candidates)

    if not args.dry_run and all_candidates:
        interactive_place_bets(all_candidates, tournament_id, bankroll,
                               candidate_lookup=candidate_lookup)
    elif args.dry_run:
        print("\n[DRY RUN — no bets logged]")


if __name__ == "__main__":
    main()
