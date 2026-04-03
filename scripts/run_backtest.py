#!/usr/bin/env python3
from __future__ import annotations

"""
Run backtests — matchup accuracy and dead-heat placement analysis.

Usage:
    python scripts/run_backtest.py [--matchups] [--deadheat] [--all]
        [--start-year 2022] [--end-year 2026]
    python scripts/run_backtest.py --pull [--start-year 2022] [--end-year 2026]
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse


def main():
    parser = argparse.ArgumentParser(description="Run backtests")
    parser.add_argument("--matchups", action="store_true",
                        help="Run matchup accuracy backtest")
    parser.add_argument("--deadheat", action="store_true",
                        help="Run dead-heat placement analysis")
    parser.add_argument("--all", action="store_true",
                        help="Run all backtests")
    parser.add_argument("--pull", action="store_true",
                        help="Pull historical data from DG API")
    parser.add_argument("--start-year", type=int, default=2022)
    parser.add_argument("--end-year", type=int, default=2026)
    args = parser.parse_args()

    if args.pull:
        from src.backtest.pull_historical import pull_all_backtest_data
        pull_all_backtest_data(
            start_year=args.start_year, end_year=args.end_year,
            matchups=True, predictions=True,
        )
        return

    if args.all or (not args.matchups and not args.deadheat):
        args.matchups = True
        args.deadheat = True

    if args.matchups:
        from src.backtest.analyze_matchups import run_full_backtest
        run_full_backtest(args.start_year, args.end_year)

    if args.deadheat:
        from src.backtest.analyze_deadheat import analyze_deadheat_from_predictions
        analyze_deadheat_from_predictions(args.start_year, args.end_year)


if __name__ == "__main__":
    main()
