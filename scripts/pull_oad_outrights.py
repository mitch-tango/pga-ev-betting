#!/usr/bin/env python3
"""Pull historical outright odds for T10 and make-cut into the OAD directory.

Usage:
    python3 scripts/pull_oad_outrights.py --markets top_10 make_cut
    python3 scripts/pull_oad_outrights.py --markets top_10  # just one market
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api.datagolf import DataGolfClient

OAD_DIR = Path("/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/"
               "Maitland Thompson/Working/EV/PGA OAD/Analytics/"
               "Rubric Backtest/raw_data")

BOOKS = ["pinnacle", "betcris", "betonline", "draftkings", "fanduel"]


def pull_outright_market(market: str, force: bool = False):
    """Pull historical outright odds for a given market into OAD directory."""
    dg = DataGolfClient()
    pred_dir = OAD_DIR / "predictions"
    odds_dir = OAD_DIR / "outrights"
    odds_dir.mkdir(parents=True, exist_ok=True)

    # Discover events from prediction files
    events = []
    for pred_file in sorted(pred_dir.glob("pred_*.json")):
        parts = pred_file.stem.split("_")  # pred_2024_10
        if len(parts) >= 3:
            try:
                year = int(parts[1])
                event_id = parts[2]
                events.append((year, event_id))
            except ValueError:
                pass

    print(f"\nPulling {market} odds for {len(events)} events × {len(BOOKS)} books")
    total_calls = len(events) * len(BOOKS)
    skipped = 0
    pulled = 0
    errors = 0

    for i, (year, event_id) in enumerate(events):
        for book in BOOKS:
            cache_path = odds_dir / f"odds_{year}_{event_id}_{book}_{market}.json"

            if cache_path.exists() and not force:
                skipped += 1
                continue

            try:
                result = dg.get_historical_outrights(
                    event_id=event_id, year=year,
                    market=market, book=book,
                )

                if result["status"] == "ok":
                    with open(cache_path, "w") as f:
                        json.dump(result["data"], f, indent=2)
                    pulled += 1
                else:
                    # Save empty so we don't retry
                    with open(cache_path, "w") as f:
                        json.dump({"odds": []}, f)
                    errors += 1

            except Exception as e:
                print(f"  Error {year}/{event_id}/{book}: {e}")
                errors += 1

            done = skipped + pulled + errors
            if done % 50 == 0 or done == total_calls:
                print(f"  [{done}/{total_calls}] pulled={pulled} "
                      f"skipped={skipped} errors={errors}")

    print(f"\nDone: {pulled} pulled, {skipped} cached, {errors} errors")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Pull historical outright odds into OAD directory")
    parser.add_argument("--markets", nargs="+", required=True,
                        choices=["win", "top_5", "top_10", "top_20", "make_cut"],
                        help="Markets to pull")
    parser.add_argument("--force", action="store_true",
                        help="Re-pull even if cached")
    args = parser.parse_args()

    for market in args.markets:
        pull_outright_market(market, force=args.force)


if __name__ == "__main__":
    main()
