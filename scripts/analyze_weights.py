from __future__ import annotations

"""
Weight & Sportsbook Evaluation — Tranche-Segmented Analysis.

Roadmap Item 1, Phase 1: backtest re-analysis.

Analyses:
  1. Outright calibration: DG predicted probs vs actual finishes
     (win, T10, T20, make-cut) segmented by tranche
  2. Matchup blend-weight sweep: optimal DG/books per tranche
  3. Per-book leave-one-out: marginal contribution of each book
  4. Per-book softness: which books give the most edge
  5. Simulated ROI with quarter-Kelly per tranche

Tranche definitions (by DG win probability):
  - Favorites: win_prob >= 5%
  - Mid-tier:  1% <= win_prob < 5%
  - Longshots: win_prob < 1%

Usage:
  python scripts/analyze_weights.py [--start-year 2022] [--end-year 2026]
"""

import json
import math
from collections import defaultdict
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.devig import parse_american_odds, devig_two_way
from src.backtest.analyze_matchups import (
    derive_matchup_prob_from_predictions, log_loss, brier_score,
)
import config

BACKTEST_DIR = Path("data/raw/backtest")

# Tranche thresholds (DG win probability)
TRANCHE_THRESHOLDS = {
    "favorite": 0.05,   # >= 5%
    "mid":      0.01,   # 1% - 5%
    # longshot: < 1%
}


def classify_tranche(win_prob: float) -> str:
    if win_prob >= TRANCHE_THRESHOLDS["favorite"]:
        return "favorite"
    elif win_prob >= TRANCHE_THRESHOLDS["mid"]:
        return "mid"
    return "longshot"


def parse_finish(fin_text: str) -> int | None:
    """Parse fin_text (e.g., '1', 'T11', 'CUT', 'WD') to numeric position.

    Returns integer position or None for CUT/WD/DQ/-.
    For ties like 'T11', returns 11 (the tied position).
    """
    if not fin_text or fin_text in ("-", "CUT", "WD", "DQ"):
        return None
    ft = fin_text.lstrip("T")
    try:
        return int(ft)
    except ValueError:
        return None


def made_cut(fin_text: str) -> bool | None:
    """Did the player make the cut? None if ambiguous."""
    if fin_text in ("CUT",):
        return False
    if fin_text in ("-", "WD", "DQ", ""):
        return None  # Ambiguous
    pos = parse_finish(fin_text)
    if pos is not None:
        return True
    return None


# ---------------------------------------------------------------------------
# 1. Outright Calibration
# ---------------------------------------------------------------------------

def run_outright_calibration(start_year: int = 2022, end_year: int = 2026):
    """Analyze DG model calibration by tranche for outrights.

    For each player-event, we have DG predicted probabilities (win, T10, T20,
    make_cut) and actual finish position. Group by tranche and check calibration.
    """
    pred_dir = BACKTEST_DIR / "predictions"
    if not pred_dir.exists():
        print("No prediction data found.")
        return {}

    # Accumulate per-tranche, per-market
    # stats[tranche][market] = {"predicted_sum": float, "actual_sum": float, "n": int, "brier_sum": float}
    stats = defaultdict(lambda: defaultdict(lambda: {
        "predicted_sum": 0.0, "actual_sum": 0.0, "n": 0, "brier_sum": 0.0,
        "ll_sum": 0.0,
    }))

    events_processed = 0

    for pred_file in sorted(pred_dir.glob("pred_*.json")):
        with open(pred_file) as f:
            data = json.load(f)

        year = data.get("event_id", "")
        # Filter by year from filename
        parts = pred_file.stem.split("_")  # pred_10_2022
        if len(parts) >= 3:
            try:
                file_year = int(parts[-1])
                if file_year < start_year or file_year > end_year:
                    continue
            except ValueError:
                pass

        # Use best model
        players = data.get("baseline_history_fit")
        if not isinstance(players, list):
            players = data.get("baseline")
        if not isinstance(players, list):
            continue

        events_processed += 1

        for p in players:
            win_prob = p.get("win", 0) or 0
            if win_prob <= 0:
                continue

            tranche = classify_tranche(win_prob)
            fin_text = p.get("fin_text", "")
            pos = parse_finish(fin_text)
            cut = made_cut(fin_text)

            # Win
            actual_win = 1.0 if pos == 1 else 0.0
            if pos is not None or fin_text == "CUT":
                s = stats[tranche]["win"]
                s["predicted_sum"] += win_prob
                s["actual_sum"] += actual_win
                s["n"] += 1
                s["brier_sum"] += brier_score(win_prob, actual_win)
                s["ll_sum"] += log_loss(win_prob, actual_win)

            # Top 10
            t10_prob = p.get("top_10", 0) or 0
            if t10_prob > 0 and (pos is not None or fin_text == "CUT"):
                actual_t10 = 1.0 if (pos is not None and pos <= 10) else 0.0
                s = stats[tranche]["t10"]
                s["predicted_sum"] += t10_prob
                s["actual_sum"] += actual_t10
                s["n"] += 1
                s["brier_sum"] += brier_score(t10_prob, actual_t10)
                s["ll_sum"] += log_loss(t10_prob, actual_t10)

            # Top 20
            t20_prob = p.get("top_20", 0) or 0
            if t20_prob > 0 and (pos is not None or fin_text == "CUT"):
                actual_t20 = 1.0 if (pos is not None and pos <= 20) else 0.0
                s = stats[tranche]["t20"]
                s["predicted_sum"] += t20_prob
                s["actual_sum"] += actual_t20
                s["n"] += 1
                s["brier_sum"] += brier_score(t20_prob, actual_t20)
                s["ll_sum"] += log_loss(t20_prob, actual_t20)

            # Make cut
            mc_prob = p.get("make_cut", 0) or 0
            if mc_prob > 0 and cut is not None:
                actual_mc = 1.0 if cut else 0.0
                s = stats[tranche]["make_cut"]
                s["predicted_sum"] += mc_prob
                s["actual_sum"] += actual_mc
                s["n"] += 1
                s["brier_sum"] += brier_score(mc_prob, actual_mc)
                s["ll_sum"] += log_loss(mc_prob, actual_mc)

    # Print results
    print(f"\n{'='*70}")
    print(f"OUTRIGHT CALIBRATION ({start_year}-{end_year})")
    print(f"{'='*70}")
    print(f"Events: {events_processed}")

    for market in ("win", "t10", "t20", "make_cut"):
        print(f"\n--- {market.upper()} ---")
        print(f"{'Tranche':<12} {'N':>7} {'Avg Pred':>9} {'Avg Actual':>11} "
              f"{'Ratio':>7} {'Brier':>10} {'LogLoss':>10}")

        all_n = all_pred = all_act = all_brier = all_ll = 0
        for tranche in ("favorite", "mid", "longshot"):
            s = stats[tranche][market]
            n = s["n"]
            if n == 0:
                continue
            avg_pred = s["predicted_sum"] / n
            avg_act = s["actual_sum"] / n
            ratio = avg_act / avg_pred if avg_pred > 0 else 0
            avg_brier = s["brier_sum"] / n
            avg_ll = s["ll_sum"] / n

            all_n += n
            all_pred += s["predicted_sum"]
            all_act += s["actual_sum"]
            all_brier += s["brier_sum"]
            all_ll += s["ll_sum"]

            cal_emoji = ""
            if ratio > 1.1:
                cal_emoji = " (underpriced)"
            elif ratio < 0.9:
                cal_emoji = " (overpriced)"

            print(f"{tranche:<12} {n:>7} {avg_pred*100:>8.3f}% {avg_act*100:>10.3f}% "
                  f"{ratio:>6.2f}x {avg_brier:>10.6f} {avg_ll:>10.6f}{cal_emoji}")

        if all_n > 0:
            print(f"{'ALL':<12} {all_n:>7} {all_pred/all_n*100:>8.3f}% "
                  f"{all_act/all_n*100:>10.3f}% "
                  f"{(all_act/all_pred) if all_pred > 0 else 0:>6.2f}x "
                  f"{all_brier/all_n:>10.6f} {all_ll/all_n:>10.6f}")

    return dict(stats)


# ---------------------------------------------------------------------------
# 2. Matchup Analysis with Tranche Segmentation
# ---------------------------------------------------------------------------

def load_all_matchup_records(start_year: int = 2022, end_year: int = 2026):
    """Load all matchup records with DG probs and book probs, enriched with tranche."""
    event_list_path = BACKTEST_DIR / "event_list.json"
    if not event_list_path.exists():
        return []

    with open(event_list_path) as f:
        events = json.load(f)

    target_events = [
        e for e in events
        if start_year <= e["calendar_year"] <= end_year
        and e.get("matchups") == "yes"
    ]

    all_records = []

    for event in target_events:
        eid = str(event["event_id"])
        year = event["calendar_year"]
        name = event["event_name"]

        # Load predictions
        pred_path = BACKTEST_DIR / "predictions" / f"pred_{eid}_{year}.json"
        if not pred_path.exists():
            continue
        with open(pred_path) as f:
            preds = json.load(f)

        # Build player lookup for tranche classification
        player_win_probs = {}
        for model_key in ("baseline_history_fit", "baseline"):
            model_data = preds.get(model_key)
            if isinstance(model_data, list):
                for p in model_data:
                    dg_id = p.get("dg_id")
                    if dg_id:
                        player_win_probs[dg_id] = p.get("win", 0) or 0
                break

        # Load matchup odds from all books
        event_dir = BACKTEST_DIR / "matchups" / f"{eid}_{year}"
        if not event_dir.exists():
            continue

        # Index matchups by player pair
        matchup_index = {}

        for book_file in event_dir.glob("*.json"):
            book_name = book_file.stem
            with open(book_file) as f:
                records = json.load(f)
            if not isinstance(records, list):
                continue

            for r in records:
                if r.get("bet_type") != "72-hole Match":
                    continue

                p1_id = r.get("p1_dg_id")
                p2_id = r.get("p2_dg_id")
                if not p1_id or not p2_id:
                    continue

                key = (min(p1_id, p2_id), max(p1_id, p2_id))

                if key not in matchup_index:
                    matchup_index[key] = {
                        "p1_dg_id": r["p1_dg_id"],
                        "p2_dg_id": r["p2_dg_id"],
                        "p1_name": r.get("p1_player_name", ""),
                        "p2_name": r.get("p2_player_name", ""),
                        "p1_outcome": r.get("p1_outcome"),
                        "books": {},
                    }

                matchup_index[key]["books"][book_name] = {
                    "p1_open": r.get("p1_open"),
                    "p1_close": r.get("p1_close"),
                    "p2_open": r.get("p2_open"),
                    "p2_close": r.get("p2_close"),
                }

        # Process each matchup
        for key, matchup in matchup_index.items():
            p1_outcome = matchup["p1_outcome"]
            if p1_outcome not in (0.0, 1.0):
                continue

            dg_prob = derive_matchup_prob_from_predictions(
                preds, matchup["p1_dg_id"], matchup["p2_dg_id"]
            )
            if dg_prob is None:
                continue

            # Classify tranche by higher-ranked player's win prob
            p1_win = player_win_probs.get(matchup["p1_dg_id"], 0)
            p2_win = player_win_probs.get(matchup["p2_dg_id"], 0)
            higher_win = max(p1_win, p2_win)
            tranche = classify_tranche(higher_win)

            for book_name, odds_data in matchup["books"].items():
                p1_close_raw = parse_american_odds(odds_data["p1_close"])
                p2_close_raw = parse_american_odds(odds_data["p2_close"])
                if p1_close_raw is None or p2_close_raw is None:
                    continue

                p1_fair, p2_fair = devig_two_way(p1_close_raw, p2_close_raw)
                if p1_fair is None or p1_fair <= 0 or p1_fair >= 1:
                    continue

                # Opening odds for CLV
                p1_open_raw = parse_american_odds(odds_data.get("p1_open"))
                p2_open_raw = parse_american_odds(odds_data.get("p2_open"))
                p1_open_fair = None
                if p1_open_raw and p2_open_raw:
                    p1_open_fair, _ = devig_two_way(p1_open_raw, p2_open_raw)

                all_records.append({
                    "event": f"{name} ({year})",
                    "p1_dg_id": matchup["p1_dg_id"],
                    "p2_dg_id": matchup["p2_dg_id"],
                    "p1_name": matchup["p1_name"],
                    "p2_name": matchup["p2_name"],
                    "p1_outcome": p1_outcome,
                    "book": book_name,
                    "dg_prob": dg_prob,
                    "book_prob": p1_fair,
                    "tranche": tranche,
                    "p1_win_prob": p1_win,
                    "p2_win_prob": p2_win,
                    "clv": (p1_fair - p1_open_fair) if p1_open_fair else None,
                })

    return all_records


def run_matchup_analysis(records: list[dict]):
    """Matchup blend-weight sweep segmented by tranche."""
    if not records:
        print("No matchup records to analyze.")
        return

    print(f"\n{'='*70}")
    print(f"MATCHUP BLEND-WEIGHT ANALYSIS")
    print(f"{'='*70}")
    print(f"Total records: {len(records)}")

    # Split by tranche
    by_tranche = defaultdict(list)
    for r in records:
        by_tranche[r["tranche"]].append(r)
        by_tranche["ALL"].append(r)

    for tranche in ("favorite", "mid", "longshot", "ALL"):
        subset = by_tranche[tranche]
        if not subset:
            continue

        print(f"\n{'='*60}")
        print(f"TRANCHE: {tranche.upper()} ({len(subset)} records)")
        print(f"{'='*60}")

        # Blend weight sweep
        print(f"\n{'DG%':>5} {'Books%':>6} {'Bets':>6} {'ROI':>8} {'Avg LL':>10} {'Brier':>10}")

        best_ll = float("inf")
        best_dg_pct = 0
        best_roi_dg_pct = 0
        best_roi = -999

        for dg_pct in range(0, 105, 5):
            dg_w = dg_pct / 100
            book_w = 1 - dg_w

            ll_sum = 0.0
            brier_sum = 0.0
            bets = 0
            staked = 0.0
            pnl = 0.0

            for r in subset:
                blended = dg_w * r["dg_prob"] + book_w * r["book_prob"]
                ll_sum += log_loss(blended, r["p1_outcome"])
                brier_sum += brier_score(blended, r["p1_outcome"])

                edge_p1 = blended - r["book_prob"]
                edge = abs(edge_p1)
                if edge < 0.05:
                    continue

                if edge_p1 > 0:
                    bet_on_p1 = True
                    bp = r["book_prob"]
                else:
                    bet_on_p1 = False
                    bp = 1 - r["book_prob"]

                dec_odds = 1.0 / bp if bp > 0 else 100
                kelly_pct = edge / (dec_odds - 1) if dec_odds > 1 else 0
                stake = min(1000 * kelly_pct * 0.25, 30)
                if stake < 1:
                    continue

                bets += 1
                staked += stake
                won = (bet_on_p1 and r["p1_outcome"] == 1.0) or \
                      (not bet_on_p1 and r["p1_outcome"] == 0.0)
                pnl += stake * (dec_odds - 1) if won else -stake

            roi = (pnl / staked * 100) if staked > 0 else 0
            avg_ll = ll_sum / len(subset)
            avg_brier = brier_sum / len(subset)

            marker = ""
            if avg_ll < best_ll:
                best_ll = avg_ll
                best_dg_pct = dg_pct
            if roi > best_roi and bets >= 10:
                best_roi = roi
                best_roi_dg_pct = dg_pct

            if dg_pct == 20:
                marker = " <-- current"

            print(f"  {dg_pct:>3}%  {100-dg_pct:>4}% {bets:>6} {roi:>7.1f}% "
                  f"{avg_ll:>10.6f} {avg_brier:>10.6f}{marker}")

        print(f"\n  Best log-loss:  {best_dg_pct}% DG (LL={best_ll:.6f})")
        print(f"  Best ROI:       {best_roi_dg_pct}% DG (ROI={best_roi:.1f}%)")


def run_book_leave_one_out(records: list[dict]):
    """Per-book leave-one-out: how much does each book contribute?

    For each book, compute consensus-without-that-book and measure
    impact on calibration.
    """
    print(f"\n{'='*70}")
    print("PER-BOOK LEAVE-ONE-OUT ANALYSIS")
    print(f"{'='*70}")

    # Group records by matchup (unique by event + player pair)
    # Then for each matchup, we have multiple book records
    matchup_groups = defaultdict(list)
    for r in records:
        key = (r["event"], r["p1_dg_id"], r["p2_dg_id"])
        matchup_groups[key].append(r)

    # For each book, measure: what happens to consensus accuracy when we drop it?
    all_books = sorted({r["book"] for r in records})

    print(f"\nBooks in dataset: {', '.join(all_books)}")
    print(f"Unique matchups: {len(matchup_groups)}")

    # Build per-matchup consensus with and without each book
    print(f"\n{'Book Dropped':<15} {'Matchups':>8} {'Avg LL':>10} {'Brier':>10} {'Delta LL':>10}")

    # Baseline: consensus with all books
    baseline_ll = 0.0
    baseline_brier = 0.0
    baseline_n = 0

    for key, group in matchup_groups.items():
        if len(group) < 2:
            continue
        # Simple average of book probs as consensus
        avg_book = sum(r["book_prob"] for r in group) / len(group)
        outcome = group[0]["p1_outcome"]
        baseline_ll += log_loss(avg_book, outcome)
        baseline_brier += brier_score(avg_book, outcome)
        baseline_n += 1

    if baseline_n == 0:
        print("Not enough multi-book matchups.")
        return

    baseline_avg_ll = baseline_ll / baseline_n
    baseline_avg_brier = baseline_brier / baseline_n
    print(f"{'(none/all)':<15} {baseline_n:>8} {baseline_avg_ll:>10.6f} "
          f"{baseline_avg_brier:>10.6f} {'baseline':>10}")

    book_impacts = {}
    for drop_book in all_books:
        drop_ll = 0.0
        drop_brier = 0.0
        drop_n = 0

        for key, group in matchup_groups.items():
            remaining = [r for r in group if r["book"] != drop_book]
            if len(remaining) < 1:
                continue
            avg_book = sum(r["book_prob"] for r in remaining) / len(remaining)
            outcome = group[0]["p1_outcome"]
            drop_ll += log_loss(avg_book, outcome)
            drop_brier += brier_score(avg_book, outcome)
            drop_n += 1

        if drop_n == 0:
            continue

        avg_ll = drop_ll / drop_n
        avg_brier = drop_brier / drop_n
        delta = avg_ll - baseline_avg_ll  # Positive = dropping this book hurts

        book_impacts[drop_book] = delta
        direction = "hurts" if delta > 0.0001 else ("helps" if delta < -0.0001 else "neutral")
        print(f"{drop_book:<15} {drop_n:>8} {avg_ll:>10.6f} {avg_brier:>10.6f} "
              f"{delta:>+10.6f} ({direction})")

    # Rank books by marginal value
    print(f"\nBook value ranking (most → least valuable to consensus):")
    for i, (book, delta) in enumerate(sorted(book_impacts.items(), key=lambda x: -x[1]), 1):
        print(f"  {i}. {book:<15} (removing it {'hurts' if delta > 0 else 'helps'} by {abs(delta)*100:.4f}%)")


def run_book_softness(records: list[dict]):
    """Per-book softness: which books offer the most edge?"""
    print(f"\n{'='*70}")
    print("PER-BOOK SOFTNESS & ROI ANALYSIS")
    print(f"{'='*70}")

    # Stats per book per tranche
    stats = defaultdict(lambda: defaultdict(lambda: {
        "n": 0, "edge_sum": 0.0, "bet_n": 0, "staked": 0.0, "pnl": 0.0,
        "best_book_count": 0,
    }))

    for r in records:
        book = r["book"]
        tranche = r["tranche"]

        for t in (tranche, "ALL"):
            s = stats[book][t]
            s["n"] += 1

            edge = abs(r["dg_prob"] - r["book_prob"])
            s["edge_sum"] += edge

            if edge >= 0.05:
                s["bet_n"] += 1

                if r["dg_prob"] - r["book_prob"] > 0:
                    bp = r["book_prob"]
                    bet_on_p1 = True
                else:
                    bp = 1 - r["book_prob"]
                    bet_on_p1 = False

                dec_odds = 1.0 / bp if bp > 0 else 100
                kelly_pct = edge / (dec_odds - 1) if dec_odds > 1 else 0
                stake = min(1000 * kelly_pct * 0.25, 30)
                if stake >= 1:
                    s["staked"] += stake
                    won = (bet_on_p1 and r["p1_outcome"] == 1.0) or \
                          (not bet_on_p1 and r["p1_outcome"] == 0.0)
                    s["pnl"] += stake * (dec_odds - 1) if won else -stake

    for tranche_label in ("ALL", "favorite", "mid", "longshot"):
        print(f"\n--- {tranche_label.upper()} ---")
        print(f"{'Book':<15} {'Records':>8} {'Avg Edge':>9} {'Bets 5%+':>9} "
              f"{'Staked':>9} {'PnL':>9} {'ROI':>8}")

        book_rows = []
        for book in sorted(stats.keys()):
            s = stats[book][tranche_label]
            if s["n"] == 0:
                continue
            avg_edge = s["edge_sum"] / s["n"]
            roi = (s["pnl"] / s["staked"] * 100) if s["staked"] > 0 else 0
            book_rows.append((book, s, avg_edge, roi))

        # Sort by avg edge descending (softest first)
        book_rows.sort(key=lambda x: -x[2])

        for book, s, avg_edge, roi in book_rows:
            print(f"{book:<15} {s['n']:>8} {avg_edge*100:>8.2f}% {s['bet_n']:>9} "
                  f"${s['staked']:>8.0f} ${s['pnl']:>8.0f} {roi:>7.1f}%")


def run_edge_threshold_analysis(records: list[dict]):
    """Test different edge thresholds per tranche."""
    print(f"\n{'='*70}")
    print("EDGE THRESHOLD ANALYSIS BY TRANCHE")
    print(f"{'='*70}")

    by_tranche = defaultdict(list)
    for r in records:
        by_tranche[r["tranche"]].append(r)
        by_tranche["ALL"].append(r)

    for tranche in ("favorite", "mid", "longshot", "ALL"):
        subset = by_tranche[tranche]
        if not subset:
            continue

        print(f"\n--- {tranche.upper()} ({len(subset)} records) ---")
        print(f"{'Threshold':>10} {'Bets':>6} {'Win%':>7} {'Staked':>9} "
              f"{'PnL':>9} {'ROI':>8} {'Avg Edge':>9}")

        for min_edge in (0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10):
            bets = 0
            wins = 0
            staked = 0.0
            pnl = 0.0
            edge_sum = 0.0

            for r in subset:
                # Use 20% DG / 80% books blend (current config)
                blended = 0.20 * r["dg_prob"] + 0.80 * r["book_prob"]
                edge_p1 = blended - r["book_prob"]
                edge = abs(edge_p1)
                if edge < min_edge:
                    continue

                if edge_p1 > 0:
                    bp = r["book_prob"]
                    bet_on_p1 = True
                else:
                    bp = 1 - r["book_prob"]
                    bet_on_p1 = False

                dec_odds = 1.0 / bp if bp > 0 else 100
                kelly_pct = edge / (dec_odds - 1) if dec_odds > 1 else 0
                stake = min(1000 * kelly_pct * 0.25, 30)
                if stake < 1:
                    continue

                bets += 1
                staked += stake
                edge_sum += edge

                won = (bet_on_p1 and r["p1_outcome"] == 1.0) or \
                      (not bet_on_p1 and r["p1_outcome"] == 0.0)
                if won:
                    pnl += stake * (dec_odds - 1)
                    wins += 1
                else:
                    pnl -= stake

            roi = (pnl / staked * 100) if staked > 0 else 0
            win_pct = (wins / bets * 100) if bets > 0 else 0
            avg_e = (edge_sum / bets * 100) if bets > 0 else 0
            marker = " <--" if min_edge == 0.05 else ""

            print(f"  {min_edge*100:>7.0f}%  {bets:>6} {win_pct:>6.1f}% "
                  f"${staked:>8.0f} ${pnl:>8.0f} {roi:>7.1f}% {avg_e:>8.2f}%{marker}")


def run_clv_analysis(records: list[dict]):
    """CLV analysis by tranche."""
    clv_records = [r for r in records if r.get("clv") is not None]
    if not clv_records:
        print("\nNo CLV data available.")
        return

    print(f"\n{'='*70}")
    print("CLV ANALYSIS BY TRANCHE")
    print(f"{'='*70}")

    by_tranche = defaultdict(list)
    for r in clv_records:
        by_tranche[r["tranche"]].append(r)
        by_tranche["ALL"].append(r)

    print(f"\n{'Tranche':<12} {'N':>7} {'Avg CLV':>9} {'Positive':>9} {'Pos%':>7}")

    for tranche in ("favorite", "mid", "longshot", "ALL"):
        subset = by_tranche[tranche]
        if not subset:
            continue
        avg_clv = sum(r["clv"] for r in subset) / len(subset)
        pos = sum(1 for r in subset if r["clv"] > 0)
        pos_pct = pos / len(subset) * 100

        print(f"{tranche:<12} {len(subset):>7} {avg_clv*100:>8.3f}% "
              f"{pos:>9} {pos_pct:>6.1f}%")


def print_summary_and_recommendations(records: list[dict], outright_stats: dict):
    """Print final summary with recommendations."""
    print(f"\n{'='*70}")
    print("SUMMARY & RECOMMENDATIONS")
    print(f"{'='*70}")

    # Matchup blend weights per tranche
    by_tranche = defaultdict(list)
    for r in records:
        by_tranche[r["tranche"]].append(r)

    print(f"\nOptimal matchup blend weights by tranche (by log-loss):")
    for tranche in ("favorite", "mid", "longshot"):
        subset = by_tranche[tranche]
        if not subset:
            continue

        best_ll = float("inf")
        best_dg = 20  # default

        for dg_pct in range(0, 105, 5):
            dg_w = dg_pct / 100
            book_w = 1 - dg_w
            ll = sum(
                log_loss(dg_w * r["dg_prob"] + book_w * r["book_prob"], r["p1_outcome"])
                for r in subset
            ) / len(subset)
            if ll < best_ll:
                best_ll = ll
                best_dg = dg_pct

        print(f"  {tranche:<12}: {best_dg}% DG / {100-best_dg}% books "
              f"(LL={best_ll:.6f}, N={len(subset)})")

    # Outright calibration summary
    if outright_stats:
        print(f"\nOutright calibration issues:")
        for tranche in ("favorite", "mid", "longshot"):
            ts = outright_stats.get(tranche, {})
            for market in ("win", "t10", "t20"):
                s = ts.get(market, {})
                if s.get("n", 0) == 0:
                    continue
                ratio = (s["actual_sum"] / s["predicted_sum"]) if s["predicted_sum"] > 0 else 0
                if ratio > 1.15 or ratio < 0.85:
                    direction = "underpriced" if ratio > 1 else "overpriced"
                    print(f"  {tranche}/{market}: DG {direction} "
                          f"(pred {s['predicted_sum']/s['n']*100:.2f}% vs "
                          f"actual {s['actual_sum']/s['n']*100:.2f}%, ratio {ratio:.2f}x)")

    print(f"\nAction items:")
    print(f"  1. Review tranche-specific blend weights above vs current config")
    print(f"  2. Check per-book softness to identify which books offer most edge")
    print(f"  3. Consider tranche-aware Kelly sizing after collecting more live data")
    print(f"  4. Create Supabase views for ongoing monitoring (Phase 2)")


# ---------------------------------------------------------------------------
# 6. Outright Blend-Weight Sweep (DG vs Books by Tranche)
# ---------------------------------------------------------------------------

OAD_DIR = Path("/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/"
               "Maitland Thompson/Working/EV/PGA OAD/Analytics/"
               "Rubric Backtest/raw_data")

OAD_BOOKS = ["pinnacle", "betcris", "betonline", "draftkings", "fanduel"]


def _load_oad_outright_records(market: str, start_year: int = 2020,
                                end_year: int = 2026) -> list[dict]:
    """Load outright records with DG probs and book probs from OAD data.

    For each player-event, joins DG predicted probability with book closing
    odds (de-vigged) and actual outcome.

    Args:
        market: 'win' or 'top_20'
    """
    pred_dir = OAD_DIR / "predictions"
    odds_dir = OAD_DIR / "outrights"

    if not pred_dir.exists() or not odds_dir.exists():
        print(f"OAD data not found at {OAD_DIR}")
        return []

    # Map market name to DG prediction field
    dg_field = {"win": "win", "top_20": "top_20", "top_10": "top_10",
                "make_cut": "make_cut"}.get(market, market)

    all_records = []

    for pred_file in sorted(pred_dir.glob("pred_*.json")):
        parts = pred_file.stem.split("_")  # pred_2024_10
        if len(parts) < 3:
            continue
        try:
            year = int(parts[1])
            event_id = parts[2]
        except (ValueError, IndexError):
            continue

        if year < start_year or year > end_year:
            continue

        with open(pred_file) as f:
            pred_data = json.load(f)

        players = pred_data.get("baseline_history_fit")
        if not isinstance(players, list):
            players = pred_data.get("baseline")
        if not isinstance(players, list):
            continue

        # Build player lookup: dg_id -> {win_prob, market_prob, fin_text}
        player_lookup = {}
        for p in players:
            dg_id = p.get("dg_id")
            if not dg_id:
                continue
            win_prob = p.get("win", 0) or 0
            market_prob = p.get(dg_field, 0) or 0
            if market_prob <= 0:
                continue
            player_lookup[dg_id] = {
                "win_prob": win_prob,
                "dg_prob": market_prob,
                "fin_text": p.get("fin_text", ""),
                "player_name": p.get("player_name", ""),
            }

        # Load book odds for this event
        for book in OAD_BOOKS:
            odds_file = odds_dir / f"odds_{year}_{event_id}_{book}_{market}.json"
            if not odds_file.exists():
                continue

            with open(odds_file) as f:
                odds_data = json.load(f)

            odds_list = odds_data.get("odds", []) if isinstance(odds_data, dict) else odds_data
            if not isinstance(odds_list, list):
                continue

            # Collect all closing odds for de-vig
            raw_probs = []
            player_odds_map = {}
            for o in odds_list:
                dg_id = o.get("dg_id")
                close_raw = parse_american_odds(o.get("close_odds"))
                if close_raw is not None and close_raw > 0:
                    raw_probs.append(close_raw)
                    player_odds_map[dg_id] = {
                        "close_raw": close_raw,
                        "outcome": o.get("outcome", ""),
                    }
                else:
                    raw_probs.append(None)

            if sum(1 for p in raw_probs if p is not None and p > 0) < 10:
                continue

            # De-vig the full field
            if market == "win":
                from src.core.devig import power_devig
                devigged = power_devig(raw_probs)
            else:
                from src.core.devig import devig_independent
                expected = {"top_20": 20, "top_10": 10}.get(market, 20)
                if market == "make_cut":
                    # Use DG model sum as event-specific expected outcomes
                    expected = sum(v["dg_prob"] for v in player_lookup.values()) or 65
                devigged = devig_independent(raw_probs, expected, len(raw_probs))

            # Build dg_id -> devigged prob
            devig_by_id = {}
            odds_list_ids = [o.get("dg_id") for o in odds_list]
            for idx, dg_id in enumerate(odds_list_ids):
                if idx < len(devigged) and devigged[idx] is not None:
                    devig_by_id[dg_id] = devigged[idx]

            # Join with predictions
            for dg_id, book_data in player_odds_map.items():
                if dg_id not in player_lookup or dg_id not in devig_by_id:
                    continue

                pl = player_lookup[dg_id]
                book_prob = devig_by_id[dg_id]
                if book_prob <= 0 or book_prob >= 1:
                    continue

                # Determine actual outcome
                fin_text = pl["fin_text"]
                pos = parse_finish(fin_text)

                if market == "win":
                    actual = 1.0 if pos == 1 else 0.0
                elif market == "top_20":
                    actual = 1.0 if (pos is not None and pos <= 20) else 0.0
                elif market == "top_10":
                    actual = 1.0 if (pos is not None and pos <= 10) else 0.0
                elif market == "make_cut":
                    mc = made_cut(fin_text)
                    if mc is None:
                        continue
                    actual = 1.0 if mc else 0.0
                else:
                    continue

                # Skip ambiguous outcomes
                if pos is None and fin_text not in ("CUT",):
                    continue

                tranche = classify_tranche(pl["win_prob"])

                all_records.append({
                    "event_id": event_id,
                    "year": year,
                    "dg_id": dg_id,
                    "player_name": pl["player_name"],
                    "book": book,
                    "dg_prob": pl["dg_prob"],
                    "book_prob": book_prob,
                    "actual": actual,
                    "tranche": tranche,
                    "win_prob": pl["win_prob"],
                })

    return all_records


def run_outright_blend_sweep(market: str, start_year: int = 2020,
                              end_year: int = 2026):
    """Sweep DG/books blend weights for an outright market by tranche.

    For each player-event, we have DG predicted prob + book consensus prob
    (average across books). Sweep DG weight 0-100%, measure log-loss and
    Brier score, segmented by tranche.
    """
    records = _load_oad_outright_records(market, start_year, end_year)
    if not records:
        print(f"No OAD outright records for {market}.")
        return

    # Build per-player-event consensus (average book prob across books)
    from collections import defaultdict
    player_events = defaultdict(lambda: {"books": [], "dg_prob": 0, "actual": 0,
                                          "tranche": "", "win_prob": 0,
                                          "player_name": ""})
    for r in records:
        key = (r["year"], r["event_id"], r["dg_id"])
        pe = player_events[key]
        pe["books"].append(r["book_prob"])
        pe["dg_prob"] = r["dg_prob"]
        pe["actual"] = r["actual"]
        pe["tranche"] = r["tranche"]
        pe["win_prob"] = r["win_prob"]
        pe["player_name"] = r["player_name"]

    # Build final records with book consensus
    consensus_records = []
    for key, pe in player_events.items():
        if not pe["books"]:
            continue
        consensus_records.append({
            "dg_prob": pe["dg_prob"],
            "book_prob": sum(pe["books"]) / len(pe["books"]),
            "actual": pe["actual"],
            "tranche": pe["tranche"],
            "n_books": len(pe["books"]),
        })

    print(f"\n{'='*70}")
    print(f"OUTRIGHT BLEND-WEIGHT SWEEP: {market.upper()}")
    print(f"{'='*70}")
    print(f"Player-events: {len(consensus_records)} "
          f"(from {len(records)} player-book records)")

    by_tranche = defaultdict(list)
    for r in consensus_records:
        by_tranche[r["tranche"]].append(r)
        by_tranche["ALL"].append(r)

    results = {}

    for tranche in ("favorite", "mid", "longshot", "ALL"):
        subset = by_tranche[tranche]
        if not subset:
            continue

        print(f"\n{'='*60}")
        print(f"TRANCHE: {tranche.upper()} ({len(subset)} player-events)")
        print(f"{'='*60}")
        print(f"{'DG%':>5} {'Books%':>6} {'Avg LL':>10} {'Brier':>10}")

        best_ll = float("inf")
        best_dg_pct = 0

        for dg_pct in range(0, 105, 5):
            dg_w = dg_pct / 100
            book_w = 1 - dg_w

            ll_sum = 0.0
            brier_sum = 0.0

            for r in subset:
                blended = dg_w * r["dg_prob"] + book_w * r["book_prob"]
                # Clamp to avoid log(0)
                blended = max(min(blended, 0.9999), 0.0001)
                ll_sum += log_loss(blended, r["actual"])
                brier_sum += brier_score(blended, r["actual"])

            avg_ll = ll_sum / len(subset)
            avg_brier = brier_sum / len(subset)

            marker = ""
            if avg_ll < best_ll:
                best_ll = avg_ll
                best_dg_pct = dg_pct

            # Mark current config weight
            current_dg = None
            if market == "win":
                current_dg = int(config.BLEND_WEIGHTS["win"]["dg"] * 100)
            elif market in ("top_20", "top_10"):
                current_dg = int(config.BLEND_WEIGHTS["placement"]["dg"] * 100)
            elif market == "make_cut":
                current_dg = int(config.BLEND_WEIGHTS["make_cut"]["dg"] * 100)
            if current_dg is not None and dg_pct == current_dg:
                marker = " <-- current"

            print(f"  {dg_pct:>3}%  {100-dg_pct:>4}% {avg_ll:>10.6f} "
                  f"{avg_brier:>10.6f}{marker}")

        print(f"\n  Best log-loss: {best_dg_pct}% DG (LL={best_ll:.6f})")
        results[tranche] = {"best_dg_pct": best_dg_pct, "best_ll": best_ll,
                             "n": len(subset)}

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Weight & sportsbook evaluation")
    parser.add_argument("--start-year", type=int, default=2022)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--outright-sweep", type=str, default=None,
                        choices=["win", "top_20", "top_10", "make_cut", "all"],
                        help="Run outright blend-weight sweep for a specific market")
    args = parser.parse_args()

    # Outright blend-weight sweep (standalone mode)
    if args.outright_sweep:
        markets = (["win", "top_20"] if args.outright_sweep == "all"
                   else [args.outright_sweep])
        for market in markets:
            run_outright_blend_sweep(market, args.start_year, args.end_year)
        return

    # 1. Outright calibration
    outright_stats = run_outright_calibration(args.start_year, args.end_year)

    # 2. Load all matchup records
    print(f"\nLoading matchup backtest data...")
    records = load_all_matchup_records(args.start_year, args.end_year)
    print(f"Loaded {len(records)} matchup-book records")

    if records:
        # 3. Matchup blend-weight sweep by tranche
        run_matchup_analysis(records)

        # 4. Per-book leave-one-out
        run_book_leave_one_out(records)

        # 5. Per-book softness
        run_book_softness(records)

        # 6. Edge threshold analysis
        run_edge_threshold_analysis(records)

        # 7. CLV analysis
        run_clv_analysis(records)

    # 8. Summary
    print_summary_and_recommendations(records, outright_stats)

    # Save results
    out_path = BACKTEST_DIR / "weight_analysis_results.json"
    summary = {
        "date_range": f"{args.start_year}-{args.end_year}",
        "matchup_records": len(records),
        "tranche_counts": {
            t: sum(1 for r in records if r["tranche"] == t)
            for t in ("favorite", "mid", "longshot")
        },
    }
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
