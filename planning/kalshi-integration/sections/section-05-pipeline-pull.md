# Section 05: Pipeline Pull — `src/pipeline/pull_kalshi.py`

## Overview

This section creates the new pipeline module `src/pipeline/pull_kalshi.py` containing two main functions: `pull_kalshi_outrights()` and `pull_kalshi_matchups()`. These functions fetch Kalshi prediction market data for the current PGA tournament, filter by liquidity/spread thresholds, normalize player names, and return structured dicts ready for merging into the existing pipeline data flow.

This module follows the same patterns as `src/pipeline/pull_outrights.py` and `src/pipeline/pull_matchups.py`.

## Dependencies

This section depends on:

- **section-01-odds-conversion**: `kalshi_midpoint()` from `src/core/devig.py` for computing midpoint probability from bid/ask
- **section-02-kalshi-client**: `KalshiClient` class in `src/api/kalshi.py` for API access
- **section-03-config-schema**: Config constants `KALSHI_SERIES_TICKERS`, `KALSHI_MIN_OPEN_INTEREST`, `KALSHI_MAX_SPREAD` in `config.py`
- **section-04-tournament-matching**: Tournament matching logic (date-based + fuzzy fallback) and player name extraction/matching functions

This section blocks **section-06-pipeline-merge**, which consumes the output of these pull functions.

## Files to Create

- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/src/pipeline/pull_kalshi.py`
- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/tests/test_pull_kalshi.py`

## Tests — `tests/test_pull_kalshi.py`

Write tests FIRST. All tests should mock the `KalshiClient` and matching functions (no real API calls).

### TestPullKalshiOutrights

- **returns dict with correct keys**: Call `pull_kalshi_outrights()` with mocked client returning valid data for win, t10, t20 events. Assert the return value is a dict with keys `"win"`, `"t10"`, `"t20"`.
- **each entry has required fields**: Each market entry in the returned lists must have `player_name` (str), `kalshi_mid_prob` (float), `kalshi_ask_prob` (float), and `open_interest` (int).
- **filters out players below OI threshold**: Mock a response with one player at OI=50 and another at OI=200. Assert only the OI=200 player appears in results. The threshold is `KALSHI_MIN_OPEN_INTEREST` (100).
- **filters out players with wide spread**: Mock a response with one player whose `(ask - bid) > 0.05` and one within spread. Assert only the tight-spread player appears. The threshold is `KALSHI_MAX_SPREAD` (0.05).
- **validates prices in 0-1 range**: If Kalshi returns prices as integers (e.g., 6 instead of 0.06), the module should divide by 100 to normalize. Test both formats.
- **returns empty dict on API failure**: Mock `KalshiClient` returning `{"status": "error", ...}`. Assert the function returns `{"win": [], "t10": [], "t20": []}` without raising.
- **returns empty dict when no golf events found**: Mock the events endpoint returning an empty list. Assert graceful empty return.
- **caches raw response**: Verify that the client's cache method is called for each series ticker pulled.

### TestPullKalshiMatchups

- **returns list of H2H matchup dicts**: Each dict should have `p1_name`, `p2_name`, `p1_prob`, `p2_prob`, `p1_oi`, `p2_oi`.
- **filters by OI threshold**: H2H matchups where either player's OI is below threshold are excluded.
- **filters by spread threshold**: H2H matchups where either side has a wide spread are excluded.
- **returns empty list when no H2H events found**: Graceful degradation.

## Implementation — `src/pipeline/pull_kalshi.py`

### Module Structure

```python
"""
Kalshi prediction market odds pull.

Pulls win, T10, T20 outright odds and H2H matchup odds from Kalshi.
Used by run_pretournament.py alongside DG API pulls.
"""
from __future__ import annotations

from src.api.kalshi import KalshiClient
from src.core.devig import kalshi_midpoint
import config

# Future: Polymarket would follow a similar pattern here.
# Polymarket covers outrights and top-N but NOT matchups,
# and requires keyword-based event discovery via the Gamma API.


def pull_kalshi_outrights(tournament_slug: str | None = None) -> dict[str, list[dict]]:
    """Pull Kalshi outright odds for win, t10, t20 markets.
    ...
    """

def pull_kalshi_matchups(tournament_slug: str | None = None) -> list[dict]:
    """Pull Kalshi H2H matchup odds.
    ...
    """
```

### `pull_kalshi_outrights()` — Processing Steps

1. **Instantiate client**: Create a `KalshiClient()` instance.

2. **Iterate over outright series tickers**: Loop through `config.KALSHI_SERIES_TICKERS` for keys `"win"`, `"t10"`, `"t20"` (skip `"tournament_matchup"` — that is handled by `pull_kalshi_matchups`).

3. **Find the current tournament event**: For each series ticker (e.g., `"KXPGATOUR"`), call `client.get_golf_events(series_ticker)`. Use the tournament matching logic from section-04 to find the event corresponding to the current DG tournament. The matching function takes the list of Kalshi events and either `tournament_slug` or the current tournament dates, and returns the matching `event_ticker` or `None`.

4. **Fetch all markets for the event**: Call `client.get_event_markets(event_ticker)` to get all player contracts in a single paginated call. This bulk endpoint should return `yes_bid_dollars` and `yes_ask_dollars` per market, avoiding the need for individual orderbook calls.

5. **Process each contract**:
   - Extract the player name from the market's `title` or `subtitle` field using the name extraction utility from section-04.
   - Read `yes_bid_dollars` (bid) and `yes_ask_dollars` (ask) as floats.
   - If values appear to be in 0-100 range (i.e., any value > 1.0), divide by 100 to normalize to 0-1.
   - Compute `mid = kalshi_midpoint(bid, ask)`. Skip if `None`.
   - Read `open_interest` (or `volume` depending on API field name).
   - **Filter: OI check** — skip if `open_interest < config.KALSHI_MIN_OPEN_INTEREST`.
   - **Filter: spread check** — skip if `(ask - bid) > config.KALSHI_MAX_SPREAD`.
   - Normalize the player name to DG canonical format using the player matching logic from section-04.
   - If the player cannot be matched, log a warning and skip.
   - Append to the results list: `{"player_name": canonical_name, "kalshi_mid_prob": mid, "kalshi_ask_prob": ask, "open_interest": oi}`.

6. **Cache raw responses**: Use the client's `_cache_response()` method for each series ticker, storing under the tournament slug directory.

7. **Return**: `{"win": [...], "t10": [...], "t20": [...]}`. Any market that failed or had no events returns an empty list for that key.

8. **Error handling**: Wrap the entire function in a try/except. On any unhandled exception, log a warning and return `{"win": [], "t10": [], "t20": []}`. The system must never fail due to Kalshi issues.

### `pull_kalshi_matchups()` — Processing Steps

1. **Find the H2H event**: Call `client.get_golf_events(config.KALSHI_SERIES_TICKERS["tournament_matchup"])` and match to the current tournament using the same matching logic.

2. **Fetch markets**: Call `client.get_event_markets(event_ticker)`.

3. **Group H2H contracts**: Each H2H matchup has two contracts (Player A YES, Player B YES). These need to be paired — they share the same event or have a common grouping field in the Kalshi response. Group contracts by their parent H2H event/market grouping.

4. **Process each pair**:
   - Extract both player names.
   - Read bid/ask for each side. Normalize to 0-1 if needed.
   - Compute midpoint for each side.
   - Check OI and spread thresholds for both sides.
   - Normalize both player names to DG canonical.
   - Build result: `{"p1_name": str, "p2_name": str, "p1_prob": float, "p2_prob": float, "p1_oi": int, "p2_oi": int}`.

5. **Return**: List of matchup dicts. Empty list on failure.

### Graceful Degradation

The module must handle all failure modes silently (with logging):

| Failure | Behavior |
|---|---|
| Kalshi API unreachable | Return empty containers, log warning |
| No open golf events | Return empty containers, log info |
| Tournament cannot be matched | Return empty containers, log warning |
| Player name unmatched | Skip that player, log warning |
| OI below threshold | Exclude from results silently |
| Spread exceeds max | Exclude from results silently |
| Unexpected response format | Return empty containers, log warning |

Every log message should clearly indicate it is Kalshi-related so it is distinguishable from DG pipeline issues.

### Key Design Decisions

- **No per-market orderbook calls during initial pull.** The bulk `get_event_markets` endpoint should provide bid/ask prices. Individual `get_orderbook()` calls are expensive (one per player) and should only be used later if deeper liquidity analysis is needed. This keeps the pull fast and within rate limits.

- **Midpoint vs. ask separation.** The pull function returns both `kalshi_mid_prob` and `kalshi_ask_prob` for each player. The merge step (section-06) uses mid for consensus blending and ask for bettable edge evaluation. Keeping both in the pull output avoids re-fetching or re-computing later.

- **DG market key mapping.** The Kalshi series tickers map to DG market names differently: `KXPGATOUR` → `"win"`, `KXPGATOP10` → `"t10"`, `KXPGATOP20` → `"t20"`. The `config.KALSHI_SERIES_TICKERS` dict encodes this mapping. The pull function uses the DG-side key names (`"win"`, `"t10"`, `"t20"`) in its return dict so downstream consumers do not need to know about Kalshi ticker naming.

- **Polymarket future note.** Leave a comment at the top of the module noting that a future `pull_polymarket_outrights()` would follow the same pattern but use keyword-based event discovery via the Gamma API instead of series ticker lookup.