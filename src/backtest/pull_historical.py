from __future__ import annotations

"""
Pull historical data from DataGolf for backtesting.

Pulls:
1. Event list (all events with matchup + outright data)
2. Historical matchup/3-ball odds from multiple books (opening + closing + outcomes)
3. Historical pre-tournament predictions (DG model probabilities)
4. Historical outright odds (for placement dead-heat analysis)

Data is saved as JSON files in data/raw/backtest/ to avoid repeated API calls.

Note: The historical matchups endpoint does NOT include DG model predictions.
DG model predictions come from the pre-tournament archive endpoint, which gives
win/T5/T10/T20/MC probabilities per player. We can derive expected matchup
probabilities from these individual finish probabilities.
"""

import json
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.api.datagolf import DataGolfClient


BACKTEST_DIR = Path("data/raw/backtest")

# Books available for historical matchup data
MATCHUP_BOOKS = [
    "draftkings", "fanduel", "betonline", "bovada", "pinnacle",
    "betcris", "bet365",
]

# Books available for historical outright data
OUTRIGHT_BOOKS = [
    "draftkings", "fanduel", "betonline", "bovada", "pinnacle",
    "betcris",
]


def pull_event_list(dg: DataGolfClient) -> list[dict]:
    """Pull and cache the master event list."""
    cache_path = BACKTEST_DIR / "event_list.json"

    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)

    result = dg.get_event_list()
    if result["status"] != "ok":
        raise RuntimeError(f"Failed to pull event list: {result}")

    events = result["data"]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(events, f, indent=2)

    print(f"Cached {len(events)} events")
    return events


def pull_matchup_odds(dg: DataGolfClient, event_id: str, year: int,
                      books: list[str] | None = None,
                      force: bool = False) -> dict[str, list[dict]]:
    """Pull historical matchup odds for one event from multiple books.

    Returns:
        {"draftkings": [matchup_records], "fanduel": [...], ...}
    """
    books = books or MATCHUP_BOOKS
    event_dir = BACKTEST_DIR / "matchups" / f"{event_id}_{year}"
    event_dir.mkdir(parents=True, exist_ok=True)

    all_odds = {}

    for book in books:
        cache_path = event_dir / f"{book}.json"

        if cache_path.exists() and not force:
            with open(cache_path) as f:
                data = json.load(f)
                if isinstance(data, list):
                    all_odds[book] = data
                continue

        result = dg.get_historical_matchups(
            event_id=event_id, year=year,
            market="tournament_matchups", book=book
        )

        if result["status"] == "ok":
            odds = result["data"].get("odds", [])
            if isinstance(odds, list):
                with open(cache_path, "w") as f:
                    json.dump(odds, f, indent=2)
                all_odds[book] = odds
            else:
                # "no data" string
                with open(cache_path, "w") as f:
                    json.dump([], f)
                all_odds[book] = []
        else:
            print(f"  Warning: {book} failed for event {event_id}/{year}: "
                  f"{result.get('message', '')[:100]}")
            all_odds[book] = []

    return all_odds


def pull_predictions(dg: DataGolfClient, event_id: str, year: int,
                     force: bool = False) -> dict | None:
    """Pull historical DG pre-tournament predictions for one event.

    Returns the predictions dict with player-level finish probabilities.
    """
    cache_path = BACKTEST_DIR / "predictions" / f"pred_{event_id}_{year}.json"

    if cache_path.exists() and not force:
        with open(cache_path) as f:
            return json.load(f)

    result = dg.get_historical_predictions(event_id=event_id, year=year)

    if result["status"] == "ok":
        data = result["data"]
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(data, f, indent=2)
        return data
    else:
        print(f"  Warning: predictions failed for {event_id}/{year}: "
              f"{result.get('message', '')[:100]}")
        return None


def pull_outright_odds(dg: DataGolfClient, event_id: str, year: int,
                       market: str = "top_20",
                       books: list[str] | None = None,
                       force: bool = False) -> dict[str, list[dict]]:
    """Pull historical outright odds for one event from multiple books.

    Used for dead-heat analysis on placement markets.
    """
    books = books or OUTRIGHT_BOOKS
    event_dir = BACKTEST_DIR / "outrights" / f"{event_id}_{year}"
    event_dir.mkdir(parents=True, exist_ok=True)

    all_odds = {}

    for book in books:
        cache_path = event_dir / f"{book}_{market}.json"

        if cache_path.exists() and not force:
            with open(cache_path) as f:
                data = json.load(f)
                if isinstance(data, list):
                    all_odds[book] = data
                continue

        result = dg.get_historical_outrights(
            event_id=event_id, year=year, market=market, book=book
        )

        if result["status"] == "ok":
            odds = result["data"].get("odds", [])
            if isinstance(odds, list):
                with open(cache_path, "w") as f:
                    json.dump(odds, f, indent=2)
                all_odds[book] = odds
            else:
                with open(cache_path, "w") as f:
                    json.dump([], f)
                all_odds[book] = []
        else:
            all_odds[book] = []

    return all_odds


def pull_all_backtest_data(start_year: int = 2022, end_year: int = 2026,
                           matchups: bool = True,
                           predictions: bool = True,
                           outrights: bool = False,
                           outright_markets: list[str] | None = None,
                           force: bool = False):
    """Pull all historical data needed for backtesting.

    Args:
        start_year: first year to pull (default 2022 — enough for meaningful sample)
        end_year: last year to pull
        matchups: pull matchup/3-ball odds
        predictions: pull DG pre-tournament predictions
        outrights: pull outright odds (for dead-heat analysis)
        outright_markets: which outright markets to pull (default: ["top_20"])
        force: re-pull even if cached
    """
    dg = DataGolfClient()
    outright_markets = outright_markets or ["top_20"]

    # Get event list
    events = pull_event_list(dg)

    # Filter to target years and events with data
    target_events = [
        e for e in events
        if start_year <= e["calendar_year"] <= end_year
        and e.get("matchups") == "yes"
    ]

    print(f"\nPulling data for {len(target_events)} events "
          f"({start_year}-{end_year})")
    print(f"  Matchups: {matchups}, Predictions: {predictions}, "
          f"Outrights: {outrights}")

    for i, event in enumerate(target_events):
        eid = str(event["event_id"])
        year = event["calendar_year"]
        name = event["event_name"]

        print(f"\n[{i+1}/{len(target_events)}] {name} ({year}) "
              f"[event_id={eid}]")

        if matchups:
            odds = pull_matchup_odds(dg, eid, year, force=force)
            total = sum(len(v) for v in odds.values())
            books_with_data = sum(1 for v in odds.values() if v)
            print(f"  Matchups: {total} records from {books_with_data} books")

        if predictions:
            preds = pull_predictions(dg, eid, year, force=force)
            if preds:
                # Count players in predictions
                baseline = preds.get("baseline", [])
                if isinstance(baseline, list):
                    print(f"  Predictions: {len(baseline)} players")
                else:
                    print(f"  Predictions: loaded")
            else:
                print(f"  Predictions: not available")

        if outrights:
            for market in outright_markets:
                odds = pull_outright_odds(dg, eid, year, market=market,
                                          force=force)
                total = sum(len(v) for v in odds.values())
                print(f"  Outrights ({market}): {total} records")

    print(f"\nBacktest data pull complete.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pull historical DG data for backtesting")
    parser.add_argument("--start-year", type=int, default=2022)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--matchups", action="store_true", default=True)
    parser.add_argument("--predictions", action="store_true", default=True)
    parser.add_argument("--outrights", action="store_true", default=False)
    parser.add_argument("--force", action="store_true", default=False)
    args = parser.parse_args()

    pull_all_backtest_data(
        start_year=args.start_year,
        end_year=args.end_year,
        matchups=args.matchups,
        predictions=args.predictions,
        outrights=args.outrights,
        force=args.force,
    )
