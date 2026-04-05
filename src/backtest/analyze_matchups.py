from __future__ import annotations

"""
Matchup Backtest Analysis — DG vs Books Accuracy on Matchups.

Uses historical matchup data (book opening/closing odds + outcomes) and
DG pre-tournament predictions to answer:

1. Can we construct a DG matchup probability from player-level predictions?
2. Does the DG-derived probability beat book implied probabilities?
3. Which books have the softest matchup lines?
4. What is the optimal DG/books blend weight for matchups?
5. What is the simulated ROI with quarter-Kelly?
6. What does historical CLV look like?

Methodology:
- For each historical matchup where we have both DG predictions and book odds:
  1. Derive DG P(A beats B) from pre-tournament finish probabilities
  2. De-vig book odds to get book implied P(A beats B)
  3. Compare both against actual outcome
  4. Compute log-loss and Brier score for DG and each book
  5. Simulate betting with various DG/book blend weights
"""

import json
import math
from pathlib import Path
from collections import defaultdict

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.core.devig import parse_american_odds, devig_two_way, devig_three_way


BACKTEST_DIR = Path("data/raw/backtest")


def log_loss(prob: float, outcome: float) -> float:
    """Binary log-loss. Clips prob to [1e-6, 1-1e-6]."""
    p = max(1e-6, min(1 - 1e-6, prob))
    if outcome == 1:
        return -math.log(p)
    return -math.log(1 - p)


def brier_score(prob: float, outcome: float) -> float:
    """Brier score for a single prediction."""
    return (prob - outcome) ** 2


def _player_finish_bins(data: dict) -> list[float] | None:
    """Convert a player's cumulative finish probabilities into discrete bins.

    Uses DG prediction fields (win, top_3, top_5, top_10, top_20, top_30,
    make_cut) to build 8 bins representing probability mass in each
    finish-position range.

    Returns:
        List of 8 probabilities (must sum to ~1.0):
            [0] 1st           (win)
            [1] 2nd-3rd       (top_3 - win)
            [2] 4th-5th       (top_5 - top_3)
            [3] 6th-10th      (top_10 - top_5)
            [4] 11th-20th     (top_20 - top_10)
            [5] 21st-30th     (top_30 - top_20)
            [6] 31st-cut line (make_cut - top_30)
            [7] miss cut      (1 - make_cut)
        Or None if essential fields are missing.
    """
    win = data.get("win", 0) or 0
    t3 = data.get("top_3", 0) or 0
    t5 = data.get("top_5", 0) or 0
    t10 = data.get("top_10", 0) or 0
    t20 = data.get("top_20", 0) or 0
    t30 = data.get("top_30", 0) or 0
    mc = data.get("make_cut", 0) or 0

    # Need at least win and make_cut to be meaningful
    if win <= 0 and mc <= 0:
        return None

    # Ensure monotonicity (cumulative probs should be non-decreasing)
    cumulative = [win, t3, t5, t10, t20, t30, mc]
    for i in range(1, len(cumulative)):
        if cumulative[i] < cumulative[i - 1]:
            cumulative[i] = cumulative[i - 1]

    # Build bins (clamp negatives from floating-point noise)
    bins = [
        cumulative[0],                          # 1st
        max(0, cumulative[1] - cumulative[0]),  # 2nd-3rd
        max(0, cumulative[2] - cumulative[1]),  # 4th-5th
        max(0, cumulative[3] - cumulative[2]),  # 6th-10th
        max(0, cumulative[4] - cumulative[3]),  # 11th-20th
        max(0, cumulative[5] - cumulative[4]),  # 21st-30th
        max(0, cumulative[6] - cumulative[5]),  # 31st-cut
        max(0, 1.0 - cumulative[6]),            # miss cut
    ]

    # Normalize to sum to 1.0 (handles minor float drift)
    total = sum(bins)
    if total <= 0:
        return None
    bins = [b / total for b in bins]

    return bins


def derive_matchup_prob_from_predictions(
    preds: dict, p1_dg_id: int, p2_dg_id: int
) -> float | None:
    """Derive P(player1 beats player2) from DG pre-tournament predictions.

    Uses the "baseline_history_fit" model when available (includes course
    history), otherwise falls back to "baseline".

    Converts each player's cumulative finish probabilities (win, T3, T5,
    T10, T20, T30, MC) into 8 discrete position bins, then computes
    P(A beats B) by integrating over all bin-pair combinations:

        P(A beats B) = sum over all (i < j) of bins_A[i] * bins_B[j]
                      + 0.5 * sum over all i of bins_A[i] * bins_B[i]

    where lower bin index = better finish. The 0.5 factor for same-bin
    pairs reflects that within a bin, each player is equally likely to
    finish ahead (ties are pushes in matchup betting, so this is
    conservative).
    """
    if not preds:
        return None

    # Get the best available model
    model_key = "baseline_history_fit"
    players = preds.get(model_key)
    if not players or not isinstance(players, list):
        model_key = "baseline"
        players = preds.get(model_key)
    if not players or not isinstance(players, list):
        return None

    # Find both players
    p1_data = None
    p2_data = None
    for player in players:
        dg_id = player.get("dg_id")
        if dg_id == p1_dg_id:
            p1_data = player
        elif dg_id == p2_dg_id:
            p2_data = player

    if not p1_data or not p2_data:
        return None

    bins_a = _player_finish_bins(p1_data)
    bins_b = _player_finish_bins(p2_data)
    if bins_a is None or bins_b is None:
        return None

    n = len(bins_a)

    # P(A beats B) = P(A in better bin) + 0.5 * P(same bin)
    p_a_wins = 0.0
    for i in range(n):
        # A in bin i beats B in any worse bin j > i
        for j in range(i + 1, n):
            p_a_wins += bins_a[i] * bins_b[j]
        # Same bin: 50/50 split
        p_a_wins += 0.5 * bins_a[i] * bins_b[i]

    # Clamp to valid probability range
    return max(0.01, min(0.99, p_a_wins))


def load_matchup_data(event_id: str, year: int) -> dict:
    """Load cached matchup odds and predictions for one event.

    Returns:
        {
            "books": {"draftkings": [records], ...},
            "predictions": {DG preds dict},
        }
    """
    event_dir = BACKTEST_DIR / "matchups" / f"{event_id}_{year}"
    pred_path = BACKTEST_DIR / "predictions" / f"pred_{event_id}_{year}.json"

    books = {}
    if event_dir.exists():
        for f in event_dir.glob("*.json"):
            book_name = f.stem
            with open(f) as fh:
                data = json.load(fh)
                if isinstance(data, list) and data:
                    books[book_name] = data

    preds = None
    if pred_path.exists():
        with open(pred_path) as f:
            preds = json.load(f)

    return {"books": books, "predictions": preds}


def analyze_event_matchups(event_data: dict, event_name: str = "") -> list[dict]:
    """Analyze matchup accuracy for one event.

    For each 72-hole matchup where we have both DG predictions and
    at least one book's odds:
    - Derive DG probability
    - De-vig each book's odds
    - Compare against actual outcome
    - Compute metrics

    Returns list of analysis records.
    """
    books = event_data["books"]
    preds = event_data["predictions"]

    if not books or not preds:
        return []

    # Collect all 72-hole matchups from all books
    # Key by player pair to align across books
    matchup_index = {}  # (p1_id, p2_id) -> {book: record}

    for book_name, records in books.items():
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
                    "tie_rule": r.get("tie_rule", ""),
                    "books": {},
                }

            # Store this book's closing odds
            matchup_index[key]["books"][book_name] = {
                "p1_open": r.get("p1_open"),
                "p1_close": r.get("p1_close"),
                "p2_open": r.get("p2_open"),
                "p2_close": r.get("p2_close"),
            }

    results = []

    for key, matchup in matchup_index.items():
        p1_outcome = matchup["p1_outcome"]
        if p1_outcome is None:
            continue

        # Skip ties (outcome is typically 0.5 for void/push)
        if p1_outcome not in (0.0, 1.0):
            continue

        # Derive DG probability
        dg_prob = derive_matchup_prob_from_predictions(
            preds, matchup["p1_dg_id"], matchup["p2_dg_id"]
        )
        if dg_prob is None:
            continue

        # For each book, compute de-vigged probability and metrics
        for book_name, odds_data in matchup["books"].items():
            p1_close_raw = parse_american_odds(odds_data["p1_close"])
            p2_close_raw = parse_american_odds(odds_data["p2_close"])

            if p1_close_raw is None or p2_close_raw is None:
                continue

            # De-vig the two-way matchup
            p1_fair, p2_fair = devig_two_way(p1_close_raw, p2_close_raw)

            if p1_fair is None or p1_fair <= 0 or p1_fair >= 1:
                continue

            # Also get opening odds for CLV
            p1_open_raw = parse_american_odds(odds_data.get("p1_open"))
            p2_open_raw = parse_american_odds(odds_data.get("p2_open"))
            p1_open_fair = None
            if p1_open_raw and p2_open_raw:
                p1_open_fair, _ = devig_two_way(p1_open_raw, p2_open_raw)

            # Metrics
            dg_ll = log_loss(dg_prob, p1_outcome)
            book_ll = log_loss(p1_fair, p1_outcome)
            dg_brier = brier_score(dg_prob, p1_outcome)
            book_brier = brier_score(p1_fair, p1_outcome)

            # Edge (what we'd have bet)
            edge_on_p1 = dg_prob - p1_fair  # positive = DG says p1 more likely
            edge_on_p2 = (1 - dg_prob) - (1 - p1_fair)  # = -(edge_on_p1)

            # CLV: would opening line have been profitable?
            clv = None
            if p1_open_fair is not None:
                clv = p1_fair - p1_open_fair  # positive = line moved toward opener

            results.append({
                "event": event_name,
                "p1_name": matchup["p1_name"],
                "p2_name": matchup["p2_name"],
                "p1_dg_id": matchup["p1_dg_id"],
                "p2_dg_id": matchup["p2_dg_id"],
                "p1_outcome": p1_outcome,
                "book": book_name,
                "dg_prob": dg_prob,
                "book_prob": p1_fair,
                "dg_log_loss": dg_ll,
                "book_log_loss": book_ll,
                "dg_brier": dg_brier,
                "book_brier": book_brier,
                "dg_better": dg_ll < book_ll,
                "edge_p1": edge_on_p1,
                "edge_p2": edge_on_p2,
                "clv": clv,
            })

    return results


def run_full_backtest(start_year: int = 2022, end_year: int = 2026) -> dict:
    """Run the complete matchup backtest across all available events.

    Returns summary statistics and the full record list.
    """
    event_list_path = BACKTEST_DIR / "event_list.json"
    if not event_list_path.exists():
        print("No event list found. Run pull_historical.py first.")
        return {}

    with open(event_list_path) as f:
        events = json.load(f)

    target_events = [
        e for e in events
        if start_year <= e["calendar_year"] <= end_year
        and e.get("matchups") == "yes"
    ]

    all_records = []
    events_processed = 0

    for event in target_events:
        eid = str(event["event_id"])
        year = event["calendar_year"]
        name = event["event_name"]

        event_data = load_matchup_data(eid, year)
        if not event_data["books"] or not event_data["predictions"]:
            continue

        records = analyze_event_matchups(event_data, f"{name} ({year})")
        if records:
            all_records.extend(records)
            events_processed += 1

    if not all_records:
        print("No matchup records found for analysis.")
        return {}

    # ---- Aggregate Statistics ----
    print(f"\n{'='*60}")
    print(f"MATCHUP BACKTEST RESULTS ({start_year}-{end_year})")
    print(f"{'='*60}")
    print(f"Events analyzed: {events_processed}")
    print(f"Total matchup-book records: {len(all_records)}")

    # DG vs Books — aggregate
    dg_wins = sum(1 for r in all_records if r["dg_better"])
    total = len(all_records)
    print(f"\nDG beats book (log-loss): {dg_wins}/{total} "
          f"({100*dg_wins/total:.1f}%)")

    avg_dg_ll = sum(r["dg_log_loss"] for r in all_records) / total
    avg_book_ll = sum(r["book_log_loss"] for r in all_records) / total
    print(f"Avg DG log-loss:   {avg_dg_ll:.6f}")
    print(f"Avg book log-loss: {avg_book_ll:.6f}")
    print(f"DG advantage:      {avg_book_ll - avg_dg_ll:.6f}")

    avg_dg_brier = sum(r["dg_brier"] for r in all_records) / total
    avg_book_brier = sum(r["book_brier"] for r in all_records) / total
    print(f"\nAvg DG Brier:   {avg_dg_brier:.6f}")
    print(f"Avg book Brier: {avg_book_brier:.6f}")

    # Per-book breakdown
    print(f"\n{'--- Per-Book Accuracy ---':^60}")
    book_stats = defaultdict(lambda: {"dg_wins": 0, "total": 0,
                                       "dg_ll_sum": 0, "book_ll_sum": 0})
    for r in all_records:
        b = r["book"]
        book_stats[b]["total"] += 1
        book_stats[b]["dg_ll_sum"] += r["dg_log_loss"]
        book_stats[b]["book_ll_sum"] += r["book_log_loss"]
        if r["dg_better"]:
            book_stats[b]["dg_wins"] += 1

    print(f"{'Book':<15} {'N':>6} {'DG Win%':>8} {'DG LL':>10} {'Book LL':>10} {'DG Edge':>10}")
    for book, stats in sorted(book_stats.items(), key=lambda x: -x[1]["total"]):
        n = stats["total"]
        dg_pct = 100 * stats["dg_wins"] / n
        dg_ll = stats["dg_ll_sum"] / n
        bk_ll = stats["book_ll_sum"] / n
        print(f"{book:<15} {n:>6} {dg_pct:>7.1f}% {dg_ll:>10.6f} {bk_ll:>10.6f} {bk_ll-dg_ll:>10.6f}")

    # Simulated ROI with various edge thresholds
    print(f"\n{'--- Simulated ROI (Quarter-Kelly, 100% DG) ---':^60}")
    for min_edge in [0.02, 0.03, 0.05, 0.08]:
        bets = 0
        total_staked = 0
        total_pnl = 0

        for r in all_records:
            # Use DG prob vs book prob to find edge
            edge = abs(r["edge_p1"])
            if edge < min_edge:
                continue

            # Bet on the side with positive edge
            if r["edge_p1"] > 0:
                bet_on_p1 = True
                bet_prob = r["dg_prob"]
                book_prob = r["book_prob"]
            else:
                bet_on_p1 = False
                bet_prob = 1 - r["dg_prob"]
                book_prob = 1 - r["book_prob"]

            decimal_odds = 1.0 / book_prob if book_prob > 0 else 100
            kelly_pct = edge / (decimal_odds - 1) if decimal_odds > 1 else 0
            stake = 1000 * kelly_pct * 0.25  # quarter-Kelly on $1K
            stake = min(stake, 30)  # cap at 3%

            if stake < 1:
                continue

            bets += 1
            total_staked += stake

            # Outcome
            if bet_on_p1:
                won = r["p1_outcome"] == 1.0
            else:
                won = r["p1_outcome"] == 0.0

            if won:
                total_pnl += stake * (decimal_odds - 1)
            else:
                total_pnl -= stake

        roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0
        print(f"  Edge >= {min_edge*100:.0f}%: {bets:>5} bets, "
              f"staked ${total_staked:>8.0f}, "
              f"PnL ${total_pnl:>8.0f}, "
              f"ROI {roi:>6.1f}%")

    # Blend weight sweep
    print(f"\n{'--- Blend Weight Sweep (DG% / Books%) ---':^60}")
    print(f"{'DG Weight':>10} {'Bets':>6} {'ROI':>8} {'Avg LL':>10}")
    for dg_pct in range(0, 110, 10):
        dg_w = dg_pct / 100
        book_w = 1 - dg_w

        blend_bets = 0
        blend_staked = 0
        blend_pnl = 0
        blend_ll_sum = 0
        blend_n = 0

        for r in all_records:
            blended = dg_w * r["dg_prob"] + book_w * r["book_prob"]
            blend_ll_sum += log_loss(blended, r["p1_outcome"])
            blend_n += 1

            edge_p1 = blended - r["book_prob"]
            edge = abs(edge_p1)
            if edge < 0.03:
                continue

            if edge_p1 > 0:
                bet_on_p1 = True
                book_prob = r["book_prob"]
            else:
                bet_on_p1 = False
                book_prob = 1 - r["book_prob"]

            decimal_odds = 1.0 / book_prob if book_prob > 0 else 100
            kelly_pct = edge / (decimal_odds - 1) if decimal_odds > 1 else 0
            stake = min(1000 * kelly_pct * 0.25, 30)
            if stake < 1:
                continue

            blend_bets += 1
            blend_staked += stake

            if bet_on_p1:
                won = r["p1_outcome"] == 1.0
            else:
                won = r["p1_outcome"] == 0.0

            if won:
                blend_pnl += stake * (decimal_odds - 1)
            else:
                blend_pnl -= stake

        roi = (blend_pnl / blend_staked * 100) if blend_staked > 0 else 0
        avg_ll = blend_ll_sum / blend_n if blend_n > 0 else 0
        marker = " <-- current" if dg_pct == 100 else ""
        print(f"  {dg_pct:>3}% / {100-dg_pct:>3}% {blend_bets:>6} {roi:>7.1f}% {avg_ll:>10.6f}{marker}")

    # CLV analysis
    clv_records = [r for r in all_records if r["clv"] is not None]
    if clv_records:
        avg_clv = sum(r["clv"] for r in clv_records) / len(clv_records)
        positive_clv = sum(1 for r in clv_records if r["clv"] > 0)
        print(f"\n{'--- CLV Analysis ---':^60}")
        print(f"Records with CLV data: {len(clv_records)}")
        print(f"Avg CLV: {avg_clv*100:.3f}%")
        print(f"Positive CLV: {positive_clv}/{len(clv_records)} "
              f"({100*positive_clv/len(clv_records):.1f}%)")

    # Pass/fail assessment
    print(f"\n{'='*60}")
    print("PASS/FAIL ASSESSMENT")
    print(f"{'='*60}")

    dg_pct = 100 * dg_wins / total
    passed_accuracy = dg_pct > 55
    print(f"DG beats books >55%: {'PASS' if passed_accuracy else 'FAIL'} ({dg_pct:.1f}%)")

    # Check if 100% DG simulated ROI is positive at 3% threshold
    # (recompute quickly)
    sim_pnl = 0
    sim_staked = 0
    for r in all_records:
        edge = abs(r["edge_p1"])
        if edge < 0.03:
            continue
        if r["edge_p1"] > 0:
            bet_on_p1 = True
            book_prob = r["book_prob"]
        else:
            bet_on_p1 = False
            book_prob = 1 - r["book_prob"]
        decimal_odds = 1.0 / book_prob if book_prob > 0 else 100
        kelly_pct = edge / (decimal_odds - 1) if decimal_odds > 1 else 0
        stake = min(1000 * kelly_pct * 0.25, 30)
        if stake < 1:
            continue
        sim_staked += stake
        if (bet_on_p1 and r["p1_outcome"] == 1.0) or \
           (not bet_on_p1 and r["p1_outcome"] == 0.0):
            sim_pnl += stake * (decimal_odds - 1)
        else:
            sim_pnl -= stake

    sim_roi = (sim_pnl / sim_staked * 100) if sim_staked > 0 else 0
    passed_roi = sim_roi > 0
    print(f"Simulated ROI > 0%:  {'PASS' if passed_roi else 'FAIL'} ({sim_roi:.1f}%)")

    if clv_records:
        passed_clv = avg_clv > 0
        print(f"Avg CLV > 0:         {'PASS' if passed_clv else 'FAIL'} ({avg_clv*100:.3f}%)")
    else:
        passed_clv = None
        print(f"Avg CLV > 0:         N/A (no CLV data)")

    overall = passed_accuracy and passed_roi
    print(f"\nOVERALL: {'PASS — matchups included in v1' if overall else 'FAIL — re-evaluate matchup strategy'}")

    # Find optimal blend weight (lowest log-loss)
    best_dg_pct = 100
    best_ll = float("inf")
    blend_results = {}
    for dg_pct_sweep in range(0, 110, 10):
        dg_w = dg_pct_sweep / 100
        book_w = 1 - dg_w
        ll_sum = sum(
            log_loss(dg_w * r["dg_prob"] + book_w * r["book_prob"], r["p1_outcome"])
            for r in all_records
        )
        avg = ll_sum / total
        blend_results[dg_pct_sweep] = avg
        if avg < best_ll:
            best_ll = avg
            best_dg_pct = dg_pct_sweep

    print(f"\nOptimal blend weight (min log-loss): {best_dg_pct}% DG / {100 - best_dg_pct}% Books")
    print(f"Config recommendation: BLEND_WEIGHTS['matchup'] = "
          f"{{'dg': {best_dg_pct/100:.2f}, 'books': {(100-best_dg_pct)/100:.2f}}}")

    # Per-book softness ranking (which books give us the most edge)
    print(f"\n{'--- Book Softness (Avg |Edge| when DG disagrees) ---':^60}")
    book_edge_stats = defaultdict(lambda: {"edge_sum": 0, "n": 0, "bet_n": 0,
                                            "pnl": 0, "staked": 0})
    for r in all_records:
        b = r["book"]
        edge = abs(r["edge_p1"])
        book_edge_stats[b]["edge_sum"] += edge
        book_edge_stats[b]["n"] += 1
        if edge >= 0.03:
            book_edge_stats[b]["bet_n"] += 1
            book_prob = r["book_prob"] if r["edge_p1"] > 0 else 1 - r["book_prob"]
            dec_odds = 1.0 / book_prob if book_prob > 0 else 100
            kelly_pct = edge / (dec_odds - 1) if dec_odds > 1 else 0
            stake = min(1000 * kelly_pct * 0.25, 30)
            if stake >= 1:
                book_edge_stats[b]["staked"] += stake
                won = (r["edge_p1"] > 0 and r["p1_outcome"] == 1.0) or \
                      (r["edge_p1"] < 0 and r["p1_outcome"] == 0.0)
                book_edge_stats[b]["pnl"] += stake * (dec_odds - 1) if won else -stake

    print(f"{'Book':<15} {'Matchups':>8} {'Avg Edge':>9} {'Bets 3%+':>9} {'ROI':>8}")
    for book, stats in sorted(book_edge_stats.items(),
                               key=lambda x: -x[1]["edge_sum"]/max(x[1]["n"],1)):
        avg_edge = stats["edge_sum"] / stats["n"] if stats["n"] > 0 else 0
        roi = (stats["pnl"] / stats["staked"] * 100) if stats["staked"] > 0 else 0
        print(f"{book:<15} {stats['n']:>8} {avg_edge*100:>8.2f}% {stats['bet_n']:>9} {roi:>7.1f}%")

    # Save summary to disk
    summary = {
        "date_range": f"{start_year}-{end_year}",
        "events_processed": events_processed,
        "total_records": total,
        "dg_win_pct": round(dg_pct, 1),
        "avg_dg_log_loss": round(avg_dg_ll, 6),
        "avg_book_log_loss": round(avg_book_ll, 6),
        "dg_advantage": round(avg_book_ll - avg_dg_ll, 6),
        "optimal_blend_dg_pct": best_dg_pct,
        "blend_log_losses": {str(k): round(v, 6) for k, v in blend_results.items()},
        "sim_roi_pct": round(sim_roi, 1),
        "passed": overall,
        "per_book": {
            book: {
                "n": stats["total"],
                "dg_win_pct": round(100 * stats["dg_wins"] / stats["total"], 1),
                "avg_dg_ll": round(stats["dg_ll_sum"] / stats["total"], 6),
                "avg_book_ll": round(stats["book_ll_sum"] / stats["total"], 6),
            }
            for book, stats in book_stats.items()
        },
    }

    out_path = BACKTEST_DIR / "matchup_backtest_results.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nResults saved to {out_path}")

    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run matchup backtest analysis")
    parser.add_argument("--start-year", type=int, default=2022)
    parser.add_argument("--end-year", type=int, default=2026)
    args = parser.parse_args()

    run_full_backtest(args.start_year, args.end_year)
