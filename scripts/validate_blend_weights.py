"""
Blend-Weight Validation — Bootstrap CI + Make-Cut Deep Dive.

Roadmap Item 1, Phase 1 open validation items:
  1. Bootstrap confidence intervals on T10/T20 favorite tranche (N≈593):
     Confirm 100% DG is significantly better than 70-80% DG.
  2. Make-cut deep dive: verify the 35%→80% global revision isn't a data
     coverage artifact.

Usage:
  python scripts/validate_blend_weights.py [--bootstrap-iters 5000]
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.analyze_matchups import log_loss, brier_score
from scripts.analyze_weights import (
    _load_oad_outright_records, classify_tranche,
)


def _build_consensus_records(records: list[dict]) -> list[dict]:
    """Collapse per-book records into per-player-event with book consensus."""
    player_events: dict = defaultdict(lambda: {
        "books": [], "dg_prob": 0, "actual": 0,
        "tranche": "", "win_prob": 0, "player_name": "",
    })
    for r in records:
        key = (r["year"], r["event_id"], r["dg_id"])
        pe = player_events[key]
        pe["books"].append(r["book_prob"])
        pe["dg_prob"] = r["dg_prob"]
        pe["actual"] = r["actual"]
        pe["tranche"] = r["tranche"]
        pe["win_prob"] = r["win_prob"]
        pe["player_name"] = r["player_name"]

    out = []
    for key, pe in player_events.items():
        if not pe["books"]:
            continue
        out.append({
            "dg_prob": pe["dg_prob"],
            "book_prob": sum(pe["books"]) / len(pe["books"]),
            "actual": pe["actual"],
            "tranche": pe["tranche"],
            "n_books": len(pe["books"]),
            "event_key": key,
        })
    return out


def _avg_log_loss(subset: list[dict], dg_pct: int) -> float:
    """Compute average log-loss for a blend weight on a set of records."""
    dg_w = dg_pct / 100
    book_w = 1 - dg_w
    ll_sum = 0.0
    for r in subset:
        blended = dg_w * r["dg_prob"] + book_w * r["book_prob"]
        blended = max(min(blended, 0.9999), 0.0001)
        ll_sum += log_loss(blended, r["actual"])
    return ll_sum / len(subset)


# ---------------------------------------------------------------------------
# 1. Bootstrap CI on T10/T20 Favorite Tranche
# ---------------------------------------------------------------------------

def bootstrap_blend_comparison(market: str, n_iters: int = 5000,
                                seed: int = 42):
    """Bootstrap test: is 100% DG significantly better than alternatives?

    For each bootstrap resample of the favorite tranche:
      - Compute log-loss at 100% DG, 80% DG, 70% DG, 55% DG (old global)
      - Record the difference (alternative - 100% DG)

    Reports:
      - Mean and 95% CI for log-loss at each weight
      - P(100% DG beats alternative) across bootstrap samples
      - Mean and 95% CI for the log-loss difference
    """
    print(f"\n{'='*70}")
    print(f"BOOTSTRAP VALIDATION: {market.upper()} — FAVORITE TRANCHE")
    print(f"{'='*70}")

    records = _load_oad_outright_records(market)
    if not records:
        print("No records loaded.")
        return
    consensus = _build_consensus_records(records)
    favorites = [r for r in consensus if r["tranche"] == "favorite"]

    n = len(favorites)
    print(f"Favorite tranche records: {n}")
    if n < 30:
        print("Too few records for meaningful bootstrap.")
        return

    # Actuals rate
    actual_rate = sum(r["actual"] for r in favorites) / n
    avg_dg = sum(r["dg_prob"] for r in favorites) / n
    avg_book = sum(r["book_prob"] for r in favorites) / n
    print(f"Actual hit rate: {actual_rate:.4f}")
    print(f"Avg DG prob:     {avg_dg:.4f}")
    print(f"Avg book prob:   {avg_book:.4f}")

    # Test weights: 100% vs alternatives
    test_weights = [100, 80, 70, 55]

    rng = random.Random(seed)

    # Bootstrap
    results: dict[int, list[float]] = {w: [] for w in test_weights}
    for _ in range(n_iters):
        sample = rng.choices(favorites, k=n)
        for w in test_weights:
            results[w].append(_avg_log_loss(sample, w))

    # Report
    print(f"\nBootstrap iterations: {n_iters}")
    print(f"\n{'DG%':>5}  {'Mean LL':>10}  {'95% CI':>22}  {'SE':>8}")
    print("-" * 55)

    means = {}
    for w in test_weights:
        vals = sorted(results[w])
        mean = sum(vals) / len(vals)
        lo = vals[int(0.025 * len(vals))]
        hi = vals[int(0.975 * len(vals))]
        se = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        means[w] = mean
        print(f"  {w:>3}%  {mean:>10.6f}  [{lo:.6f}, {hi:.6f}]  {se:.6f}")

    # Pairwise comparison: 100% DG vs each alternative
    print(f"\n{'Comparison':>22}  {'Mean ΔLL':>10}  {'95% CI':>22}  {'P(100%DG wins)':>15}")
    print("-" * 75)

    for w in test_weights:
        if w == 100:
            continue
        diffs = [results[w][i] - results[100][i] for i in range(n_iters)]
        mean_diff = sum(diffs) / len(diffs)
        diffs_sorted = sorted(diffs)
        lo = diffs_sorted[int(0.025 * len(diffs))]
        hi = diffs_sorted[int(0.975 * len(diffs))]
        p_win = sum(1 for d in diffs if d > 0) / len(diffs)
        sig = "***" if lo > 0 else ("**" if p_win > 0.95 else ("*" if p_win > 0.90 else ""))
        print(f"  100%DG vs {w:>3}%DG  {mean_diff:>10.6f}  [{lo:.6f}, {hi:.6f}]  "
              f"{p_win:>13.1%} {sig}")

    print("\n  *** = 95% CI excludes zero (strong evidence)")
    print("  **  = P(win) > 95%")
    print("  *   = P(win) > 90%")

    # Also do event-level (clustered) bootstrap to account for within-event correlation
    print(f"\n{'='*70}")
    print(f"CLUSTERED BOOTSTRAP (resample by event, not player-event)")
    print(f"{'='*70}")

    # Group by event
    by_event: dict[tuple, list[dict]] = defaultdict(list)
    for r in favorites:
        event_key = (r["event_key"][0], r["event_key"][1])  # (year, event_id)
        by_event[event_key].append(r)
    events = list(by_event.values())
    n_events = len(events)
    print(f"Events with favorite-tranche records: {n_events}")

    clustered_results: dict[int, list[float]] = {w: [] for w in test_weights}
    for _ in range(n_iters):
        sampled_events = rng.choices(events, k=n_events)
        flat = [r for ev in sampled_events for r in ev]
        if not flat:
            continue
        for w in test_weights:
            clustered_results[w].append(_avg_log_loss(flat, w))

    print(f"\n{'DG%':>5}  {'Mean LL':>10}  {'95% CI':>22}")
    print("-" * 45)
    for w in test_weights:
        vals = sorted(clustered_results[w])
        mean = sum(vals) / len(vals)
        lo = vals[int(0.025 * len(vals))]
        hi = vals[int(0.975 * len(vals))]
        print(f"  {w:>3}%  {mean:>10.6f}  [{lo:.6f}, {hi:.6f}]")

    print(f"\n{'Comparison':>22}  {'Mean ΔLL':>10}  {'95% CI':>22}  {'P(100%DG wins)':>15}")
    print("-" * 75)
    for w in test_weights:
        if w == 100:
            continue
        diffs = [clustered_results[w][i] - clustered_results[100][i]
                 for i in range(len(clustered_results[100]))]
        mean_diff = sum(diffs) / len(diffs)
        diffs_sorted = sorted(diffs)
        lo = diffs_sorted[int(0.025 * len(diffs))]
        hi = diffs_sorted[int(0.975 * len(diffs))]
        p_win = sum(1 for d in diffs if d > 0) / len(diffs)
        sig = "***" if lo > 0 else ("**" if p_win > 0.95 else ("*" if p_win > 0.90 else ""))
        print(f"  100%DG vs {w:>3}%DG  {mean_diff:>10.6f}  [{lo:.6f}, {hi:.6f}]  "
              f"{p_win:>13.1%} {sig}")


# ---------------------------------------------------------------------------
# 2. Make-Cut Deep Dive — Data Coverage Artifact Check
# ---------------------------------------------------------------------------

def make_cut_deep_dive():
    """Investigate whether make-cut 35%→80% DG is a data coverage artifact.

    Checks:
      a) Coverage comparison: how many events/players overlap between the
         original OAD calibration dataset and the outright odds dataset
      b) Per-event breakdown: log-loss at 35% vs 80% DG for each event
      c) Temporal split: is the 80% result stable across time periods?
      d) Book-count sensitivity: does the result hold for players with
         different numbers of book quotes?
      e) Cross-validation: 5-fold CV to check for overfitting
    """
    print(f"\n{'='*70}")
    print("MAKE-CUT DEEP DIVE: DATA COVERAGE & ARTIFACT CHECK")
    print(f"{'='*70}")

    records = _load_oad_outright_records("make_cut")
    if not records:
        print("No make-cut records loaded.")
        return
    consensus = _build_consensus_records(records)

    n = len(consensus)
    actual_rate = sum(r["actual"] for r in consensus) / n
    print(f"Total player-events: {n}")
    print(f"Make-cut rate:       {actual_rate:.4f}")

    # --- (a) Event coverage ---
    events = set()
    players = set()
    for r in records:
        events.add((r["year"], r["event_id"]))
        players.add(r["dg_id"])
    print(f"Events with make-cut odds: {len(events)}")
    print(f"Unique players:            {len(players)}")

    years = sorted(set(e[0] for e in events))
    print(f"Year range: {min(years)} - {max(years)}")
    for y in years:
        n_ev = sum(1 for e in events if e[0] == y)
        n_pe = sum(1 for r in consensus
                   if r["event_key"][0] == y)
        print(f"  {y}: {n_ev} events, {n_pe} player-events")

    # --- (b) Per-event log-loss at 35% vs 80% ---
    print(f"\n{'='*60}")
    print("PER-EVENT LOG-LOSS: 35% DG vs 80% DG")
    print(f"{'='*60}")

    by_event: dict[tuple, list[dict]] = defaultdict(list)
    for r in consensus:
        by_event[(r["event_key"][0], r["event_key"][1])].append(r)

    event_diffs = []
    print(f"\n{'Event':>12} {'N':>5} {'LL@35%':>10} {'LL@80%':>10} {'Δ(35-80)':>10} {'Winner':>8}")
    print("-" * 60)
    for event_key in sorted(by_event.keys()):
        subset = by_event[event_key]
        ll_35 = _avg_log_loss(subset, 35)
        ll_80 = _avg_log_loss(subset, 80)
        diff = ll_35 - ll_80
        event_diffs.append(diff)
        winner = "80%DG" if diff > 0 else "35%DG"
        yr, eid = event_key
        print(f"  {yr}_{eid:>4} {len(subset):>5} {ll_35:>10.6f} {ll_80:>10.6f} "
              f"{diff:>+10.6f} {winner:>8}")

    n_events = len(event_diffs)
    n_80_wins = sum(1 for d in event_diffs if d > 0)
    print(f"\n80% DG wins {n_80_wins}/{n_events} events ({n_80_wins/n_events:.0%})")
    avg_diff = sum(event_diffs) / n_events
    print(f"Mean per-event ΔLL (35%-80%): {avg_diff:+.6f}")

    # Sign test
    from math import comb
    # Two-sided sign test p-value
    k = min(n_80_wins, n_events - n_80_wins)
    p_sign = 2 * sum(comb(n_events, i) * 0.5**n_events for i in range(k + 1))
    p_sign = min(p_sign, 1.0)
    print(f"Sign test p-value (two-sided): {p_sign:.4f}")

    # --- (c) Temporal split ---
    print(f"\n{'='*60}")
    print("TEMPORAL STABILITY: 2020-2022 vs 2023-2026")
    print(f"{'='*60}")

    for period_name, year_range in [("2020-2022", range(2020, 2023)),
                                      ("2023-2026", range(2023, 2027))]:
        subset = [r for r in consensus if r["event_key"][0] in year_range]
        if len(subset) < 30:
            print(f"  {period_name}: too few records ({len(subset)})")
            continue
        print(f"\n  {period_name}: N={len(subset)}")
        print(f"  {'DG%':>5} {'LL':>10}")
        best_ll = float("inf")
        best_w = 0
        for w in range(0, 105, 5):
            ll = _avg_log_loss(subset, w)
            marker = ""
            if ll < best_ll:
                best_ll = ll
                best_w = w
            if w in (35, 80):
                marker = f" <-- {'old' if w == 35 else 'new'}"
            print(f"    {w:>3}%  {ll:.6f}{marker}")
        print(f"  Best: {best_w}% DG (LL={best_ll:.6f})")

    # --- (d) Book-count sensitivity ---
    print(f"\n{'='*60}")
    print("BOOK-COUNT SENSITIVITY")
    print(f"{'='*60}")

    for min_books in [1, 3, 5]:
        subset = [r for r in consensus if r["n_books"] >= min_books]
        if len(subset) < 30:
            continue
        ll_35 = _avg_log_loss(subset, 35)
        ll_80 = _avg_log_loss(subset, 80)
        print(f"  >= {min_books} books: N={len(subset):>6}, "
              f"LL@35%={ll_35:.6f}, LL@80%={ll_80:.6f}, "
              f"Δ={ll_35 - ll_80:+.6f} ({'80%' if ll_35 > ll_80 else '35%'} better)")

    # --- (e) 5-fold cross-validation ---
    print(f"\n{'='*60}")
    print("5-FOLD CROSS-VALIDATION (by event)")
    print(f"{'='*60}")

    # Shuffle events and split into folds
    event_keys = sorted(by_event.keys())
    rng = random.Random(42)
    rng.shuffle(event_keys)

    n_folds = 5
    fold_size = len(event_keys) // n_folds

    cv_results: dict[int, list[float]] = defaultdict(list)

    for fold_idx in range(n_folds):
        test_start = fold_idx * fold_size
        test_end = test_start + fold_size if fold_idx < n_folds - 1 else len(event_keys)
        test_events = set(event_keys[test_start:test_end])
        train_events = set(event_keys) - test_events

        train_records = [r for r in consensus
                         if (r["event_key"][0], r["event_key"][1]) in train_events]
        test_records = [r for r in consensus
                        if (r["event_key"][0], r["event_key"][1]) in test_events]

        # Find best weight on train set
        best_train_w = 0
        best_train_ll = float("inf")
        for w in range(0, 105, 5):
            ll = _avg_log_loss(train_records, w)
            if ll < best_train_ll:
                best_train_ll = ll
                best_train_w = w

        # Evaluate test set at best-train weight, 35%, and 80%
        test_ll_best = _avg_log_loss(test_records, best_train_w)
        test_ll_35 = _avg_log_loss(test_records, 35)
        test_ll_80 = _avg_log_loss(test_records, 80)

        print(f"  Fold {fold_idx+1}: train best={best_train_w}%DG, "
              f"test LL@best={test_ll_best:.6f}, "
              f"test LL@35%={test_ll_35:.6f}, "
              f"test LL@80%={test_ll_80:.6f}")

        cv_results["best_train_w"].append(best_train_w)
        cv_results["test_ll_best"].append(test_ll_best)
        cv_results["test_ll_35"].append(test_ll_35)
        cv_results["test_ll_80"].append(test_ll_80)

    avg_best_w = sum(cv_results["best_train_w"]) / n_folds
    avg_test_best = sum(cv_results["test_ll_best"]) / n_folds
    avg_test_35 = sum(cv_results["test_ll_35"]) / n_folds
    avg_test_80 = sum(cv_results["test_ll_80"]) / n_folds

    print(f"\n  Avg train-optimal weight: {avg_best_w:.0f}% DG")
    print(f"  Avg test LL at train-optimal: {avg_test_best:.6f}")
    print(f"  Avg test LL at 35% DG:        {avg_test_35:.6f}")
    print(f"  Avg test LL at 80% DG:        {avg_test_80:.6f}")
    better = "80%" if avg_test_80 < avg_test_35 else "35%"
    print(f"  Cross-validated winner: {better} DG")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate blend-weight findings (bootstrap + make-cut)")
    parser.add_argument("--bootstrap-iters", type=int, default=5000,
                        help="Number of bootstrap iterations (default: 5000)")
    parser.add_argument("--analysis", type=str, default="all",
                        choices=["bootstrap", "makecut", "all"],
                        help="Which analysis to run")
    args = parser.parse_args()

    if args.analysis in ("bootstrap", "all"):
        for market in ("top_10", "top_20"):
            bootstrap_blend_comparison(market, n_iters=args.bootstrap_iters)

    if args.analysis in ("makecut", "all"):
        make_cut_deep_dive()


if __name__ == "__main__":
    main()
