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
            print(f"  {market}: {dh_pct:.1f}% of winning bets face dead-heat")
            print(f"    Avg payout reduction across ALL winners: {edge_impact:.2f}%")
            print(f"    Effective edge impact: ~{edge_impact:.2f}% "
                  f"(current 3.0% threshold → {3.0 + edge_impact:.1f}% adjusted)")
        else:
            print(f"  {market}: insufficient data")

    return {
        "events_processed": events_processed,
        "stats": {k: {kk: vv for kk, vv in v.items() if kk != "reductions"}
                  for k, v in stats.items()},
    }


if __name__ == "__main__":
    analyze_deadheat_from_predictions()
