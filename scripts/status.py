#!/usr/bin/env python3
from __future__ import annotations

"""
System status — quick dashboard of bankroll, exposure, and season stats.

Usage:
    python scripts/status.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime
from src.db import supabase_client as db
import config


def main():
    print(f"=== PGA +EV Betting System — Status ===")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Bankroll
    bankroll = db.get_bankroll()
    print(f"\nBankroll: ${bankroll:.2f}")

    # Weekly exposure
    weekly_bets = db.get_open_bets_for_week()
    weekly_exposure = sum(b.get("stake", 0) for b in weekly_bets)
    weekly_limit = bankroll * config.MAX_WEEKLY_EXPOSURE_PCT
    print(f"Weekly exposure: ${weekly_exposure:.2f} / ${weekly_limit:.2f} "
          f"({weekly_exposure/weekly_limit*100:.0f}%)" if weekly_limit > 0 else "")

    # Season stats
    print(f"\n{'--- Season Statistics ---':^50}")

    roi_by_market = db.get_roi_by_market()
    if roi_by_market:
        total_bets = sum(r.get("total_bets", 0) for r in roi_by_market)
        total_staked = sum(r.get("total_staked", 0) for r in roi_by_market)
        total_pnl = sum(r.get("total_pnl", 0) for r in roi_by_market)
        overall_roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0

        print(f"\nTotal bets: {total_bets}")
        print(f"Total staked: ${total_staked:.2f}")
        print(f"Total P&L: ${total_pnl:+.2f}")
        print(f"Overall ROI: {overall_roi:+.1f}%")

        print(f"\n{'Market':<18} {'Bets':>5} {'Staked':>9} {'P&L':>9} "
              f"{'ROI':>7} {'CLV':>7} {'W-L':>7}")
        for r in roi_by_market:
            wins = r.get("wins", 0)
            losses = r.get("losses", 0)
            print(f"{r['market_type']:<18} {r['total_bets']:>5} "
                  f"${r.get('total_staked', 0):>7.0f} "
                  f"${r.get('total_pnl', 0):>+7.0f} "
                  f"{r.get('roi_pct', 0):>6.1f}% "
                  f"{r.get('avg_clv_pct', 0):>6.2f}% "
                  f"{wins}-{losses}")
    else:
        print("\nNo settled bets yet.")

    # CLV trend
    clv_data = db.get_clv_weekly()
    if clv_data:
        print(f"\n{'--- CLV Trend ---':^50}")
        print(f"{'Week':<12} {'Bets':>5} {'Avg CLV':>8} {'P&L':>9}")
        for row in clv_data:
            week = str(row.get("week", ""))[:10]
            print(f"{week:<12} {row.get('bets', 0):>5} "
                  f"{row.get('avg_clv_pct', 0):>7.2f}% "
                  f"${row.get('weekly_pnl', 0):>+7.0f}")

    # ROI by book
    roi_by_book = db.get_roi_by_book()
    if roi_by_book:
        print(f"\n{'--- ROI by Book ---':^50}")
        print(f"{'Book':<15} {'Bets':>5} {'ROI':>7} {'CLV':>7}")
        for r in roi_by_book:
            print(f"{r['book']:<15} {r['total_bets']:>5} "
                  f"{r.get('roi_pct', 0):>6.1f}% "
                  f"{r.get('avg_clv_pct', 0):>6.2f}%")

    # Calibration
    cal_data = db.get_calibration()
    if cal_data:
        print(f"\n{'--- Calibration ---':^50}")
        print(f"{'Predicted':>10} {'Actual':>8} {'N':>5}")
        for row in cal_data:
            print(f"{row.get('avg_predicted_pct', 0):>9.1f}% "
                  f"{row.get('actual_hit_pct', 0):>7.1f}% "
                  f"{row.get('n', 0):>5}")

    # Config summary
    print(f"\n{'--- Current Config ---':^50}")
    print(f"Kelly fraction: {config.KELLY_FRACTION}")
    print(f"Edge thresholds:")
    for market, threshold in sorted(config.MIN_EDGE.items()):
        print(f"  {market:<22} {threshold*100:.0f}%")
    print(f"Blend weights:")
    for market, weights in sorted(config.BLEND_WEIGHTS.items()):
        print(f"  {market:<22} DG {weights['dg']*100:.0f}% / Books {weights['books']*100:.0f}%")


if __name__ == "__main__":
    main()
