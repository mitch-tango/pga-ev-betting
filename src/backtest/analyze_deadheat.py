from __future__ import annotations

"""
Dead-Heat Placement Backtest (Amendment #8).

Re-validates that placement markets (T5/T10/T20) remain +EV after
accounting for dead-heat settlement rules.

Uses historical outright odds (book + DG predictions) and actual finish
positions to determine:
1. How often placement bets settle as dead-heat (by market)
2. Average payout reduction from dead-heat
3. Whether effective ROI remains positive after dead-heat adjustment
4. Whether edge thresholds need to be raised

This analysis uses the existing OAD backtest data (35,064 player-events)
if available, or pulls fresh data from DG.
"""

import json
import math
from pathlib import Path
from collections import defaultdict

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.core.devig import parse_american_odds, power_devig


BACKTEST_DIR = Path("data/raw/backtest")


def estimate_deadheat_impact(finish_positions: list[int],
                              threshold: int) -> dict:
    """Estimate dead-heat frequency and impact for a placement market.

    Given a list of actual finish positions for all players in a tournament,
    determine how often a player finishing at exactly the threshold position
    would face a dead-heat.

    Args:
        finish_positions: list of all player finish positions (1-based)
        threshold: market threshold (5, 10, or 20)

    Returns:
        {
            "at_cutoff": int — number of players at exactly the threshold
            "tied_at_cutoff": int — number of players tied at the threshold
            "dead_heat": bool — whether dead-heat applies
            "reduction_factor": float — payout multiplier (1.0 if no DH,
                                         1/N if N-way DH)
        }
    """
    # Count players at exactly the threshold position
    at_cutoff = sum(1 for fp in finish_positions if fp == threshold)

    if at_cutoff <= 1:
        return {
            "at_cutoff": at_cutoff,
            "tied_at_cutoff": 0,
            "dead_heat": False,
            "reduction_factor": 1.0,
        }

    # Dead-heat: multiple players tied at the cutoff
    # Standard dead-heat: stake is divided by number of tied players
    # who are at the boundary
    return {
        "at_cutoff": at_cutoff,
        "tied_at_cutoff": at_cutoff,
        "dead_heat": True,
        "reduction_factor": 1.0 / at_cutoff,
    }


def analyze_deadheat_from_predictions(start_year: int = 2022,
                                       end_year: int = 2026) -> dict:
    """Analyze dead-heat frequency using DG prediction data.

    Since DG predictions include actual finish positions (in the outcome),
    we can estimate how often dead-heats occur at T5/T10/T20 cutoffs.

    This is an estimation based on the historical frequency of ties at
    cutoff positions across all PGA Tour events.
    """
    pred_dir = BACKTEST_DIR / "predictions"
    if not pred_dir.exists():
        print("No prediction data found. Run pull_historical.py first.")
        return {}

    thresholds = {"t5": 5, "t10": 10, "t20": 20}
    stats = {market: {"total_bets": 0, "deadheat_bets": 0,
                       "avg_reduction": 0, "reductions": []}
             for market in thresholds}

    events_processed = 0

    for pred_file in sorted(pred_dir.glob("pred_*.json")):
        year_str = pred_file.stem.split("_")[-1]
        try:
            year = int(year_str)
        except ValueError:
            continue

        if year < start_year or year > end_year:
            continue

        with open(pred_file) as f:
            preds = json.load(f)

        # Get actual finish positions from the prediction data
        # DG predictions include 'fin_text' in some archive formats
        model_key = "baseline_history_fit"
        players = preds.get(model_key)
        if not players or not isinstance(players, list):
            model_key = "baseline"
            players = preds.get(model_key)
        if not players or not isinstance(players, list):
            continue

        # Check if finish data is available
        has_finish = any(p.get("fin_text") for p in players)
        if not has_finish:
            # Try to use top_20 probability as a proxy
            # We can estimate dead-heat frequency from the T20 probability
            # distribution: if many players cluster near P(T20) = threshold,
            # ties are more likely
            continue

        # Parse finish positions
        finishes = []
        for p in players:
            fin = p.get("fin_text", "")
            if not fin:
                continue
            fin_str = str(fin).strip().upper()
            if fin_str in ("CUT", "MC", "MDF", "WD", "DQ", "W/D", "DNS", ""):
                continue
            try:
                pos = int(fin_str.lstrip("T"))
                finishes.append(pos)
            except ValueError:
                continue

        if len(finishes) < 20:
            continue

        events_processed += 1

        # For each threshold, analyze all winning bets
        for market, threshold in thresholds.items():
            # All players who finished <= threshold are winning bets
            winners = [f for f in finishes if f <= threshold]
            stats[market]["total_bets"] += len(winners)

            # Dead-heat only affects players at EXACTLY the threshold
            # position when multiple players tie there
            at_threshold = sum(1 for f in finishes if f == threshold)

            if at_threshold > 1:
                # These players face dead-heat reduction
                stats[market]["deadheat_bets"] += at_threshold
                reduction = 1.0 / at_threshold
                stats[market]["reductions"].extend(
                    [reduction] * at_threshold
                )

    if events_processed == 0:
        print("No events with finish data found.")
        return {}

    # Compute summary statistics
    print(f"\n{'='*60}")
    print(f"DEAD-HEAT PLACEMENT ANALYSIS ({start_year}-{end_year})")
    print(f"{'='*60}")
    print(f"Events analyzed: {events_processed}")

    print(f"\n{'Market':<8} {'Total@Cut':>10} {'DH Bets':>8} {'DH%':>8} "
          f"{'Avg Reduction':>14}")

    for market in ["t5", "t10", "t20"]:
        s = stats[market]
        if s["total_bets"] > 0:
            dh_pct = 100 * s["deadheat_bets"] / s["total_bets"]
            avg_red = (sum(s["reductions"]) / len(s["reductions"])
                       if s["reductions"] else 1.0)
        else:
            dh_pct = 0
            avg_red = 1.0

        print(f"{market:<8} {s['total_bets']:>10} {s['deadheat_bets']:>8} "
              f"{dh_pct:>7.1f}% {avg_red:>13.3f}")

    # Impact on edge
    print(f"\n{'--- Impact on Minimum Edge Threshold ---':^60}")
    print(f"If dead-heat reduces average payout by X%, the effective edge")
    print(f"is reduced by approximately the same amount.")
    print()

    import config
    edge_impacts = {}

    for market in ["t5", "t10", "t20"]:
        s = stats[market]
        if s["total_bets"] > 0 and s["reductions"]:
            # Average payout reduction across ALL winning bets
            # Most winning bets pay full (reduction = 1.0)
            # Only those at the cutoff with ties get reduced
            non_dh = s["total_bets"] - s["deadheat_bets"]
            all_reductions = [1.0] * non_dh + s["reductions"]
            overall_avg = sum(all_reductions) / len(all_reductions)
            edge_impact = (1.0 - overall_avg) * 100
            dh_pct = 100 * s["deadheat_bets"] / s["total_bets"]

            edge_impacts[market] = {
                "dh_pct": round(dh_pct, 1),
                "avg_payout_reduction_pct": round(edge_impact, 2),
            }

            current_threshold = config.MIN_EDGE.get(market, 0.03) * 100
            recommended = max(current_threshold, edge_impact + 2.0)  # 2% buffer above DH impact

            print(f"  {market}: {dh_pct:.1f}% of winning bets face dead-heat")
            print(f"    Avg payout reduction across ALL winners: {edge_impact:.2f}%")
            print(f"    Current threshold: {current_threshold:.0f}%")
            print(f"    Recommended threshold: {recommended:.0f}% "
                  f"(DH impact + 2% buffer)")

            edge_impacts[market]["current_threshold_pct"] = current_threshold
            edge_impacts[market]["recommended_threshold_pct"] = round(recommended, 0)
        else:
            print(f"  {market}: insufficient data")

    # Simulated ROI comparison: with vs without dead-heat adjustment
    print(f"\n{'--- Simulated ROI: DH-Adjusted vs Naive ---':^60}")
    print(f"Compares betting with current DH edge adjustment vs betting naively.")
    print(f"Uses historical DH rates to simulate actual payouts.\n")

    print(f"{'Market':<8} {'Threshold':>10} {'DH Rate':>8} "
          f"{'Naive EV':>9} {'Adj EV':>8} {'Verdict':>10}")

    for market in ["t5", "t10", "t20"]:
        s = stats[market]
        if s["total_bets"] == 0:
            continue

        threshold_val = thresholds[market]
        dh_rate = s["deadheat_bets"] / s["total_bets"] if s["total_bets"] else 0
        current_adj = config.DEADHEAT_AVG_REDUCTION.get(market, 0) * 100

        # Naive: ignoring dead-heat (overestimates edge)
        # On average, a bet priced at X% edge loses ~DH_impact% to dead-heat
        # So naive EV on a $100 bet with 5% edge = $5 - DH_impact
        edge_impacts_data = edge_impacts.get(market, {})
        avg_reduction = edge_impacts_data.get("avg_payout_reduction_pct", 0)

        # Naive: assumes full payout on all wins
        naive_ev = 5.0  # hypothetical 5% edge
        # Adjusted: accounts for DH impact
        adj_ev = 5.0 - avg_reduction

        if adj_ev > 0:
            verdict = "PROFITABLE"
        else:
            verdict = "SKIP"

        print(f"{market:<8} {threshold_val:>10} {dh_rate*100:>7.1f}% "
              f"{naive_ev:>8.1f}% {adj_ev:>7.1f}% {verdict:>10}")

    # Pass/fail assessment
    print(f"\n{'='*60}")
    print("PASS/FAIL ASSESSMENT")
    print(f"{'='*60}")

    for market in ["t5", "t10", "t20"]:
        data = edge_impacts.get(market, {})
        if not data:
            print(f"  {market}: N/A (insufficient data)")
            continue

        impact = data["avg_payout_reduction_pct"]
        current = data["current_threshold_pct"]

        if impact > current - 1:
            status = "FAIL — threshold too low, raise it"
        elif impact > 10:
            status = "FAIL — DH impact too high, consider skipping"
        else:
            status = "PASS — current threshold covers DH impact"

        print(f"  {market}: {status}")
        print(f"    DH impact: {impact:.1f}% | Threshold: {current:.0f}% | "
              f"Margin: {current - impact:.1f}%")

    # Config recommendations
    print(f"\n{'--- Config Recommendations ---':^60}")
    for market in ["t5", "t10", "t20"]:
        data = edge_impacts.get(market, {})
        if data:
            rec = data["recommended_threshold_pct"]
            cur = data["current_threshold_pct"]
            cur_adj = config.DEADHEAT_AVG_REDUCTION.get(market, 0) * 100
            actual = data["avg_payout_reduction_pct"]

            if abs(cur_adj - actual) > 0.5:
                print(f"  DEADHEAT_AVG_REDUCTION['{market}']: "
                      f"{cur_adj:.1f}% -> {actual:.1f}% (measured)")
            else:
                print(f"  DEADHEAT_AVG_REDUCTION['{market}']: "
                      f"{cur_adj:.1f}% — OK (measured: {actual:.1f}%)")

            if rec > cur:
                print(f"  MIN_EDGE['{market}']: {cur:.0f}% -> {rec:.0f}% (raise)")
            else:
                print(f"  MIN_EDGE['{market}']: {cur:.0f}% — OK")

    # Save results to disk
    summary = {
        "date_range": f"{start_year}-{end_year}",
        "events_processed": events_processed,
        "markets": {},
    }

    for market in ["t5", "t10", "t20"]:
        s = stats[market]
        summary["markets"][market] = {
            "total_winning_bets": s["total_bets"],
            "deadheat_bets": s["deadheat_bets"],
            "dh_rate_pct": round(100 * s["deadheat_bets"] / s["total_bets"], 1)
                if s["total_bets"] else 0,
        }
        if market in edge_impacts:
            summary["markets"][market].update(edge_impacts[market])

    out_path = BACKTEST_DIR / "deadheat_backtest_results.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nResults saved to {out_path}")

    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run dead-heat placement backtest")
    parser.add_argument("--start-year", type=int, default=2022)
    parser.add_argument("--end-year", type=int, default=2026)
    args = parser.parse_args()

    analyze_deadheat_from_predictions(args.start_year, args.end_year)
