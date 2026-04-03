#!/usr/bin/env python3
from __future__ import annotations

"""
Post-tournament outcome logging and settlement.

Usage:
    python scripts/run_log_outcomes.py [--tournament-id UUID]

Workflow:
1. Get all unsettled bets for the tournament
2. Prompt for each bet's outcome (finish position, opponent finish, etc.)
3. Apply settlement rules (dead-heat, push, void)
4. Update bets with outcome + P&L
5. Update bankroll ledger
6. Print weekly summary

TODO v2: Automate by pulling final results from DG API.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from datetime import datetime

from src.core.settlement import (
    settle_placement_bet, settle_matchup_bet, settle_3ball_bet,
)
from src.db import supabase_client as db
import config


def settle_placement(bet: dict) -> dict | None:
    """Interactive settlement for a placement bet."""
    market = bet["market_type"]
    threshold = {"win": 1, "t5": 5, "t10": 10, "t20": 20, "make_cut": 999}.get(market)

    if threshold is None:
        return None

    finish_str = input(f"  Actual finish position (or MC/WD/DQ): ").strip()

    if finish_str.upper() in ("MC", "CUT", "MDF"):
        return {
            "outcome": "loss",
            "settlement_rule": "missed_cut",
            "payout": 0.0,
            "pnl": round(-bet["stake"], 2),
            "actual_finish": "MC",
        }
    elif finish_str.upper() in ("WD", "DQ", "DNS"):
        # Check book rule
        rule = db.get_book_rule(bet["book"], market)
        wd_rule = rule.get("wd_rule", "void") if rule else "void"
        if wd_rule == "void":
            return {
                "outcome": "void",
                "settlement_rule": "void_wd",
                "payout": round(bet["stake"], 2),
                "pnl": 0.0,
                "actual_finish": finish_str.upper(),
            }
        else:
            return {
                "outcome": "loss",
                "settlement_rule": "wd_loss",
                "payout": 0.0,
                "pnl": round(-bet["stake"], 2),
                "actual_finish": finish_str.upper(),
            }

    try:
        finish = int(finish_str.lstrip("T"))
    except ValueError:
        print(f"  Invalid finish: {finish_str}")
        return None

    if market == "make_cut":
        # Made the cut
        result = settle_placement_bet(
            finish, 999, bet["stake"], bet["odds_at_bet_decimal"],
        )
        result["actual_finish"] = str(finish)
        return result

    # Check for dead-heat
    tied = 1
    if finish == threshold:
        tied_str = input(f"  Players tied at T{threshold}? [1]: ").strip()
        if tied_str:
            try:
                tied = int(tied_str)
            except ValueError:
                tied = 1

    rule = db.get_book_rule(bet["book"], market)
    tie_rule = rule.get("tie_rule", "dead_heat") if rule else "dead_heat"

    result = settle_placement_bet(
        finish, threshold, bet["stake"], bet["odds_at_bet_decimal"],
        tied_at_cutoff=tied, tie_rule=tie_rule,
    )
    result["actual_finish"] = str(finish)
    return result


def settle_matchup(bet: dict) -> dict | None:
    """Interactive settlement for a matchup bet."""
    print(f"  {bet['player_name']} vs {bet.get('opponent_name', '?')}")

    p_finish = input(f"  {bet['player_name']} finish (or WD): ").strip()
    o_finish = input(f"  {bet.get('opponent_name', 'Opponent')} finish (or WD): ").strip()

    p_pos = None
    o_pos = None

    if p_finish.upper() not in ("WD", "DQ", "DNS"):
        try:
            p_pos = int(p_finish.lstrip("T"))
        except ValueError:
            print(f"  Invalid: {p_finish}")
            return None

    if o_finish.upper() not in ("WD", "DQ", "DNS"):
        try:
            o_pos = int(o_finish.lstrip("T"))
        except ValueError:
            print(f"  Invalid: {o_finish}")
            return None

    rule = db.get_book_rule(bet["book"], bet["market_type"])
    tie_rule = rule.get("tie_rule", "push") if rule else "push"
    wd_rule = rule.get("wd_rule", "void") if rule else "void"

    result = settle_matchup_bet(
        p_pos, o_pos, bet["stake"], bet["odds_at_bet_decimal"],
        tie_rule=tie_rule, wd_rule=wd_rule,
    )
    result["actual_finish"] = p_finish
    result["opponent_finish"] = o_finish
    return result


def settle_3ball(bet: dict) -> dict | None:
    """Interactive settlement for a 3-ball bet."""
    print(f"  {bet['player_name']} vs {bet.get('opponent_name', '?')} "
          f"vs {bet.get('opponent_2_name', '?')}")

    p_score = input(f"  {bet['player_name']} round score (or WD): ").strip()
    o1_score = input(f"  {bet.get('opponent_name', 'Opp1')} score (or WD): ").strip()
    o2_score = input(f"  {bet.get('opponent_2_name', 'Opp2')} score (or WD): ").strip()

    scores = []
    for s in [p_score, o1_score, o2_score]:
        if s.upper() in ("WD", "DQ", "DNS"):
            scores.append(None)
        else:
            try:
                scores.append(int(s))
            except ValueError:
                print(f"  Invalid: {s}")
                return None

    rule = db.get_book_rule(bet["book"], "3_ball")
    tie_rule = rule.get("tie_rule", "dead_heat") if rule else "dead_heat"
    wd_rule = rule.get("wd_rule", "void") if rule else "void"

    result = settle_3ball_bet(
        scores[0], scores[1], scores[2],
        bet["stake"], bet["odds_at_bet_decimal"],
        tie_rule=tie_rule, wd_rule=wd_rule,
    )
    result["actual_finish"] = p_score
    result["opponent_finish"] = o1_score
    return result


def main():
    parser = argparse.ArgumentParser(description="Post-tournament settlement")
    parser.add_argument("--tournament-id", default=None,
                        help="Supabase tournament UUID")
    args = parser.parse_args()

    print(f"=== Post-Tournament Settlement ===")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Get unsettled bets
    if args.tournament_id:
        bets = db.get_unsettled_bets(args.tournament_id)
    else:
        # Get all unsettled bets across all tournaments
        all_bets = db.get_open_bets_for_week()
        bets = [b for b in all_bets if b.get("outcome") is None]

    if not bets:
        print("\nNo unsettled bets found.")
        return

    print(f"\n{len(bets)} unsettled bets:\n")

    total_pnl = 0
    settled_count = 0

    for i, bet in enumerate(bets, 1):
        display = bet["player_name"]
        if bet.get("opponent_name"):
            display = f"{bet['player_name']} vs {bet['opponent_name']}"
            if bet.get("opponent_2_name"):
                display += f" vs {bet['opponent_2_name']}"

        market = bet["market_type"]
        round_str = f" R{bet['round_number']}" if bet.get("round_number") else ""

        print(f"\n[{i}/{len(bets)}] {display}")
        print(f"  Market: {market}{round_str} | Book: {bet['book']} | "
              f"Odds: {bet.get('odds_at_bet_american', '?')} | "
              f"Stake: ${bet['stake']:.2f}")
        print(f"  Edge: {bet['edge']*100:.1f}% | "
              f"CLV: {bet['clv']*100:.2f}%" if bet.get('clv') else "  Edge: {:.1f}%".format(bet['edge']*100))

        skip = input("  Settle this bet? [Y/n]: ").strip()
        if skip.lower() == "n":
            continue

        # Route to appropriate settlement handler
        if market in ("win", "t5", "t10", "t20", "make_cut"):
            result = settle_placement(bet)
        elif market in ("tournament_matchup", "round_matchup"):
            result = settle_matchup(bet)
        elif market == "3_ball":
            result = settle_3ball(bet)
        else:
            print(f"  Unknown market type: {market}")
            continue

        if result is None:
            continue

        # Update in Supabase
        db.settle_bet(
            bet_id=bet["id"],
            outcome=result["outcome"],
            settlement_rule=result["settlement_rule"],
            payout=result["payout"],
            pnl=result["pnl"],
            actual_finish=result.get("actual_finish"),
            opponent_finish=result.get("opponent_finish"),
        )

        emoji = "✓" if result["pnl"] >= 0 else "✗"
        print(f"  {emoji} {result['outcome'].upper()}: "
              f"payout ${result['payout']:.2f}, "
              f"P&L ${result['pnl']:+.2f} "
              f"({result['settlement_rule']})")

        total_pnl += result["pnl"]
        settled_count += 1

    # Summary
    bankroll = db.get_bankroll()
    print(f"\n{'='*50}")
    print(f"Settlement complete: {settled_count} bets")
    print(f"Session P&L: ${total_pnl:+.2f}")
    print(f"Current bankroll: ${bankroll:.2f}")

    # Show analytics if we have enough data
    roi_data = db.get_roi_by_market()
    if roi_data:
        print(f"\n{'--- Season ROI by Market ---':^50}")
        print(f"{'Market':<15} {'Bets':>5} {'ROI':>7} {'CLV':>7}")
        for row in roi_data:
            print(f"{row['market_type']:<15} {row['total_bets']:>5} "
                  f"{row.get('roi_pct', 0):>6.1f}% "
                  f"{row.get('avg_clv_pct', 0):>6.2f}%")


if __name__ == "__main__":
    main()
