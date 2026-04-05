# Kalshi Integration — Usage Guide

## Quick Start

The Kalshi integration adds prediction market odds as an additional "book" in the PGA EV betting system. It runs automatically as part of the existing workflow.

### Pre-Tournament Scan (automatic)

```bash
python scripts/run_pretournament.py --tournament masters-2026
```

The Kalshi pull-and-merge happens automatically after DG data is pulled. You'll see:
```
Pulling Kalshi odds...
  Kalshi win: 45 players merged
  Kalshi t10: 38 players merged
  Kalshi matchups: 12 merged
```

If Kalshi is unavailable, the pipeline proceeds with DG-only data:
```
  Warning: Kalshi unavailable (ConnectionError), proceeding with DG-only
```

### Pre-Round Scan

```bash
python scripts/run_preround.py --round 1 --tournament masters-2026
```

Kalshi tournament markets are currently **disabled** for pre-round scans (risk of stale DG model vs live Kalshi prices). When live DG predictions are implemented, set `kalshi_enabled = True` in `run_preround.py`.

## How It Works

### Pipeline Flow

1. **Pull DG outrights + matchups** (existing)
2. **Pull Kalshi odds** → `pull_kalshi_outrights()`, `pull_kalshi_matchups()`
3. **Merge** → Kalshi appears as `"kalshi"` book column in player data
4. **Edge calculation** → `calculate_placement_edges()` discovers "kalshi" automatically
5. **Dead-heat bypass** → Kalshi gets `deadheat_adj = 0.0` for T10/T20 (binary contract payout)

### Dead-Heat Advantage

Kalshi binary contracts pay full value on ties — no dead-heat reduction. This is a structural advantage for T10/T20 markets:

| Book | Raw Edge | DH Adj | Effective Edge |
|------|----------|--------|----------------|
| DraftKings | 8.0% | -4.4% | 3.6% |
| Kalshi | 7.0% | 0.0% | **7.0%** |

Kalshi can win "best book" even with worse raw odds.

### Configuration

Key settings in `config.py`:
- `KALSHI_SERIES_TICKERS` — maps market types to Kalshi series tickers
- `KALSHI_MIN_OPEN_INTEREST = 100` — minimum OI for inclusion
- `KALSHI_MAX_SPREAD = 0.05` — max bid-ask spread filter
- `KALSHI_RATE_LIMIT_DELAY = 0.1` — 100ms between API calls
- `KALSHI_NO_DEADHEAT_BOOKS = {"kalshi"}` — books exempt from DH adjustment
- `BOOK_WEIGHTS` — Kalshi weighted 2x for win (sharp), 1x for placement

### API Client

```python
from src.kalshi.client import KalshiClient

client = KalshiClient()
events = client.get_golf_events()           # All golf events
markets = client.get_event_markets(ticker)  # Markets for an event
orderbook = client.get_orderbook(ticker)    # Live orderbook
```

Environment: No API key required for public read-only endpoints.

## Key Files

| File | Purpose |
|------|---------|
| `src/kalshi/client.py` | Kalshi REST API client |
| `src/kalshi/odds_converter.py` | Kalshi price ↔ American/decimal conversion |
| `src/kalshi/tournament_matcher.py` | Match DG tournaments to Kalshi events |
| `src/pipeline/pull_kalshi.py` | Pull + merge Kalshi data into DG pipeline |
| `config.py` | All Kalshi config constants |
| `src/core/edge.py` | Per-book dead-heat adjustment |

## Test Coverage

```bash
python3 -m pytest tests/ -v   # 304 tests, all pass
```

Kalshi-specific test files:
- `tests/test_devig.py` — odds conversion (Kalshi-specific tests)
- `tests/test_kalshi_client.py` — API client
- `tests/test_kalshi_matching.py` — tournament matching
- `tests/test_pull_kalshi.py` — pipeline pull + merge
- `tests/test_kalshi_edge.py` — edge calculator (DH bypass)
- `tests/test_kalshi_workflow.py` — workflow integration
- `tests/test_kalshi_degradation.py` — graceful degradation
