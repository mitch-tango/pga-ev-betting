#!/usr/bin/env python3
from __future__ import annotations

"""
Post-tournament outcome logging and settlement.

Usage:
    python scripts/run_log_outcomes.py [--tournament-id UUID] [--manual]

Workflow:
1. Pull current results from DG field-updates API
2. Match results to unsettled bets by player name (fuzzy)
3. Show auto-matched results for confirmation
4. Apply settlement rules (dead-heat, push, void)
5. Update bets with outcome + P&L
6. Update bankroll ledger
7. Print weekly summary

Use --manual to skip auto-pull and enter all results by hand.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from datetime import datetime

from src.core.settlement import (
    settle_placement_bet, settle_matchup_bet, settle_3ball_bet,
)
from src.pipeline.pull_results import fetch_results, match_bets_to_results
from src.db import supabase_client as db
import config


# ---- Settlement helpers (shared between auto and manual paths) ----

def _settle_placement_auto(bet: dict, player_result: dict) -> dict | None:
    """Auto-settle a placement bet from DG results."""
    market = bet["market_type"]
    threshold = {"win": 1, "t5": 5, "t10": 10, "t20": 20, "make_cut": 999}.get(market)
    if threshold is None:
        return None

    status = player_result["status"]
    pos = player_result["pos"]
    pos_str = player_result["pos_str"]

    # WD / DQ
    if status in ("wd", "dq"):
        rule = db.get_book_rule(bet["book"], market)
        wd_rule = rule.get("wd_rule", "void") if rule else "void"
        if wd_rule == "void":
            return {
                "outcome": "void", "settlement_rule": "void_wd",
                "payout": round(bet["stake"], 2), "pnl": 0.0,
                "actual_finish": status.upper(),
            }
        else:
            return {
                "outcome": "loss", "settlement_rule": "wd_loss",
                "payout": 0.0, "pnl": round(-bet["stake"], 2),
                "actual_finish": status.upper(),
            }

    # Missed cut
    if status == "cut":
        return {
            "outcome": "loss", "settlement_rule": "missed_cut",
            "payout": 0.0, "pnl": round(-bet["stake"], 2),
            "actual_finish": "MC",
        }

    if pos is None:
        return None  # Can't determine finish

    if market == "make_cut":
        result = settle_placement_bet(
            pos, 999, bet["stake"], bet["odds_at_bet_decimal"],
        )
        result["actual_finish"] = pos_str
        return result

    # For placement bets, we need to know tied count at cutoff.
    # The DG field-updates "pos_str" uses "T" prefix for ties (e.g., "T5").
    # We can count players at the same position to determine dead-heat count.
    # For now, check if pos_str starts with "T" as a tie indicator.
    tied = 1
    if pos == threshold and pos_str.startswith("T"):
        # We'll need the full field to count ties — handled in the caller.
        # For auto-settle, we flag dead-heat as needing confirmation.
        tied = -1  # Sentinel: needs manual input

    if tied == -1:
        return None  # Dead-heat at cutoff — needs manual tie count

    rule = db.get_book_rule(bet["book"], market)
    tie_rule = rule.get("tie_rule", "dead_heat") if rule else "dead_heat"

    result = settle_placement_bet(
        pos, threshold, bet["stake"], bet["odds_at_bet_decimal"],
        tied_at_cutoff=tied, tie_rule=tie_rule,
    )
    result["actual_finish"] = pos_str
    return result


def _settle_matchup_auto(bet: dict, p_result: dict, o_result: dict) -> dict | None:
    """Auto-settle a matchup bet from DG results."""
    p_pos = p_result["pos"] if p_result["status"] == "active" else None
    o_pos = o_result["pos"] if o_result["status"] == "active" else None

    rule = db.get_book_rule(bet["book"], bet["market_type"])
    tie_rule = rule.get("tie_rule", "push") if rule else "push"
    wd_rule = rule.get("wd_rule", "void") if rule else "void"

    # For round matchups, compare round scores instead of positions
    if bet["market_type"] == "round_matchup" and bet.get("round_number"):
        rnd = bet["round_number"]
        rnd_key = f"r{rnd}"
        p_score = p_result.get(rnd_key)
        o_score = o_result.get(rnd_key)

        if p_score is None and p_result["status"] in ("wd", "dq"):
            p_score = None
        if o_score is None and o_result["status"] in ("wd", "dq"):
            o_score = None

        if p_score is not None and o_score is not None:
            # Lower score wins in matchup (strokes, not position)
            if p_score < o_score:
                payout = bet["stake"] * bet["odds_at_bet_decimal"]
                return {
                    "outcome": "win", "settlement_rule": "standard",
                    "payout": round(payout, 2), "pnl": round(payout - bet["stake"], 2),
                    "actual_finish": str(p_score), "opponent_finish": str(o_score),
                }
            elif p_score > o_score:
                return {
                    "outcome": "loss", "settlement_rule": "standard",
                    "payout": 0.0, "pnl": round(-bet["stake"], 2),
                    "actual_finish": str(p_score), "opponent_finish": str(o_score),
                }
            else:
                # Tie
                if tie_rule == "push":
                    return {
                        "outcome": "push", "settlement_rule": "push",
                        "payout": round(bet["stake"], 2), "pnl": 0.0,
                        "actual_finish": str(p_score), "opponent_finish": str(o_score),
                    }

        # Fall through to tournament position comparison if round scores unavailable

    result = settle_matchup_bet(
        p_pos, o_pos, bet["stake"], bet["odds_at_bet_decimal"],
        tie_rule=tie_rule, wd_rule=wd_rule,
    )
    result["actual_finish"] = p_result["pos_str"]
    result["opponent_finish"] = o_result["pos_str"]
    return result


def _settle_3ball_auto(bet: dict, p_result: dict,
                       o1_result: dict, o2_result: dict) -> dict | None:
    """Auto-settle a 3-ball bet from DG round scores."""
    rnd = bet.get("round_number")
    if not rnd:
        return None

    rnd_key = f"r{rnd}"
    p_score = p_result.get(rnd_key) if p_result["status"] not in ("wd", "dq") else None
    o1_score = o1_result.get(rnd_key) if o1_result["status"] not in ("wd", "dq") else None
    o2_score = o2_result.get(rnd_key) if o2_result["status"] not in ("wd", "dq") else None

    rule = db.get_book_rule(bet["book"], "3_ball")
    tie_rule = rule.get("tie_rule", "dead_heat") if rule else "dead_heat"
    wd_rule = rule.get("wd_rule", "void") if rule else "void"

    result = settle_3ball_bet(
        p_score, o1_score, o2_score,
        bet["stake"], bet["odds_at_bet_decimal"],
        tie_rule=tie_rule, wd_rule=wd_rule,
    )
    result["actual_finish"] = str(p_score) if p_score else "WD"
    result["opponent_finish"] = str(o1_score) if o1_score else "WD"
    return result


# ---- Manual settlement (fallback) ----

def settle_placement_manual(bet: dict) -> dict | None:
    """Interactive settlement for a placement bet."""
    market = bet["market_type"]
    threshold = {"win": 1, "t5": 5, "t10": 10, "t20": 20, "make_cut": 999}.get(market)
    if threshold is None:
        return None

    finish_str = input(f"  Actual finish position (or MC/WD/DQ): ").strip()

    if finish_str.upper() in ("MC", "CUT", "MDF"):
        return {
            "outcome": "loss", "settlement_rule": "missed_cut",
            "payout": 0.0, "pnl": round(-bet["stake"], 2),
            "actual_finish": "MC",
        }
    elif finish_str.upper() in ("WD", "DQ", "DNS"):
        rule = db.get_book_rule(bet["book"], market)
        wd_rule = rule.get("wd_rule", "void") if rule else "void"
        if wd_rule == "void":
            return {
                "outcome": "void", "settlement_rule": "void_wd",
                "payout": round(bet["stake"], 2), "pnl": 0.0,
                "actual_finish": finish_str.upper(),
            }
        else:
            return {
                "outcome": "loss", "settlement_rule": "wd_loss",
                "payout": 0.0, "pnl": round(-bet["stake"], 2),
                "actual_finish": finish_str.upper(),
            }

    try:
        finish = int(finish_str.lstrip("T"))
    except ValueError:
        print(f"  Invalid finish: {finish_str}")
        return None

    if market == "make_cut":
        result = settle_placement_bet(
            finish, 999, bet["stake"], bet["odds_at_bet_decimal"],
        )
        result["actual_finish"] = str(finish)
        return result

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


def settle_matchup_manual(bet: dict) -> dict | None:
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


def settle_3ball_manual(bet: dict) -> dict | None:
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


# ---- Count ties at a position from full results ----

def _count_tied_at_pos(results: dict, position: int) -> int:
    """Count how many players share a given finish position."""
    count = 0
    for p in results["players"].values():
        if p["pos"] == position:
            count += 1
    return count


# ---- Main ----

def main():
    parser = argparse.ArgumentParser(description="Post-tournament settlement")
    parser.add_argument("--tournament-id", default=None,
                        help="Supabase tournament UUID")
    parser.add_argument("--manual", action="store_true",
                        help="Skip auto-pull, enter all results by hand")
    parser.add_argument("--tour", default="pga",
                        help="Tour (pga, euro, opp, alt)")
    args = parser.parse_args()

    print(f"=== Post-Tournament Settlement ===")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Get unsettled bets
    if args.tournament_id:
        bets = db.get_unsettled_bets(args.tournament_id)
    else:
        all_bets = db.get_open_bets_for_week()
        bets = [b for b in all_bets if b.get("outcome") is None]

    if not bets:
        print("\nNo unsettled bets found.")
        return

    print(f"\n{len(bets)} unsettled bets found.")

    # Auto-pull results from DG
    results = None
    if not args.manual:
        print("\nPulling results from DataGolf...")
        try:
            results = fetch_results(tour=args.tour)
            print(f"Event: {results['event_name']} (Round {results['current_round']})")
            print(f"Field: {len(results['players'])} players")
            bets = match_bets_to_results(bets, results)

            matched = sum(1 for b in bets if b.get("auto_settleable"))
            unmatched = len(bets) - matched
            print(f"Auto-matched: {matched}/{len(bets)} bets"
                  f"{f' ({unmatched} need manual input)' if unmatched else ''}")
        except Exception as e:
            print(f"Auto-pull failed: {e}")
            print("Falling back to manual entry.\n")
            results = None

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

        edge_str = f"  Edge: {bet['edge']*100:.1f}%"
        if bet.get('clv') is not None:
            edge_str += f" | CLV: {bet['clv']*100:.2f}%"
        print(edge_str)

        # Show auto-matched result if available
        pr = bet.get("player_result")
        result = None

        if pr and bet.get("auto_settleable"):
            # Show what DG says
            match_info = f"  DG: {pr['name']} → {pr['pos_str'] or pr['status'].upper()}"
            or_ = bet.get("opponent_result")
            if or_:
                match_info += f" | {or_['name']} → {or_['pos_str'] or or_['status'].upper()}"
            o2r = bet.get("opponent_2_result")
            if o2r:
                match_info += f" | {o2r['name']} → {o2r['pos_str'] or o2r['status'].upper()}"
            print(match_info)

            # Try auto-settlement
            if market in ("win", "t5", "t10", "t20", "make_cut"):
                result = _settle_placement_auto(bet, pr)
                # If dead-heat at cutoff, we need tie count from full results
                if result is None and pr["pos"] is not None and results:
                    threshold = {"t5": 5, "t10": 10, "t20": 20}.get(market)
                    if threshold and pr["pos"] == threshold:
                        tied = _count_tied_at_pos(results, threshold)
                        print(f"  Dead-heat: {tied} players tied at {threshold}")
                        rule = db.get_book_rule(bet["book"], market)
                        tie_rule = rule.get("tie_rule", "dead_heat") if rule else "dead_heat"
                        result = settle_placement_bet(
                            pr["pos"], threshold, bet["stake"],
                            bet["odds_at_bet_decimal"],
                            tied_at_cutoff=tied, tie_rule=tie_rule,
                        )
                        result["actual_finish"] = pr["pos_str"]
            elif market in ("tournament_matchup", "round_matchup"):
                result = _settle_matchup_auto(bet, pr, bet["opponent_result"])
            elif market == "3_ball":
                result = _settle_3ball_auto(
                    bet, pr, bet["opponent_result"], bet["opponent_2_result"],
                )

            if result:
                # Ask for confirmation
                emoji = "+" if result["pnl"] >= 0 else "-"
                print(f"  [{emoji}] Auto: {result['outcome'].upper()} "
                      f"(${result['pnl']:+.2f}, {result['settlement_rule']})")
                confirm = input("  Accept? [Y/n/manual]: ").strip().lower()
                if confirm == "n":
                    continue
                elif confirm == "manual":
                    result = None  # Fall through to manual
            else:
                print("  Could not auto-settle (missing data or dead-heat)")

        # Manual fallback
        if result is None:
            if not pr:
                print("  No DG match found — entering manually")

            skip = input("  Settle this bet? [Y/n]: ").strip()
            if skip.lower() == "n":
                continue

            if market in ("win", "t5", "t10", "t20", "make_cut"):
                result = settle_placement_manual(bet)
            elif market in ("tournament_matchup", "round_matchup"):
                result = settle_matchup_manual(bet)
            elif market == "3_ball":
                result = settle_3ball_manual(bet)
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
