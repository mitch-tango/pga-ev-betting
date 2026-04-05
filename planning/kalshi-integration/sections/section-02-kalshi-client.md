# Section 02: Kalshi API Client

## Overview

This section creates the `KalshiClient` class in `src/api/kalshi.py` -- a read-only REST client for the Kalshi prediction market API. It follows the same patterns as the existing `DataGolfClient` in `src/api/datagolf.py`: response envelope wrapping, retry with exponential backoff, rate limiting, and local JSON caching. The client has **no dependencies on other sections** and can be built in parallel with section-01 (odds conversion) and section-03 (config/schema).

The Kalshi API base URL is `https://api.elections.kalshi.com/trade-api/v2`. Market data endpoints are public -- no API key or authentication is needed. The basic tier allows 20 requests/second; the client should enforce a conservative 0.1s delay between calls.

## Files to Create

- `src/api/kalshi.py` -- the KalshiClient class
- `tests/test_kalshi_client.py` -- test file

## Files to Read for Context

- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/src/api/datagolf.py` -- the existing client pattern to follow
- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/config.py` -- where config constants live (section-03 will add Kalshi constants; for now, use defaults inline or import if already added)

## Dependencies

- **section-03-config-schema** adds `KALSHI_BASE_URL` and `KALSHI_RATE_LIMIT_DELAY` to `config.py`. If section-03 is not yet implemented, the client should fall back to hardcoded defaults (`"https://api.elections.kalshi.com/trade-api/v2"` and `0.1`).

## Tests First -- `tests/test_kalshi_client.py`

All tests should use `unittest.mock.patch` to mock `requests.get` -- no real HTTP calls. The test file should be class-based, consistent with the project's existing test conventions.

### TestKalshiClientInit

- **test_default_config**: Client initializes with default base_url (`https://api.elections.kalshi.com/trade-api/v2`) and rate_limit_delay (0.1s). Assert attributes are set correctly.
- **test_custom_base_url**: Client accepts a `base_url` override parameter and uses it instead of the default.
- **test_cache_dir_creation**: Client creates the cache directory (via `Path.mkdir`) if it does not already exist. Use `tmp_path` fixture.

### TestKalshiApiCall

The `_api_call` method should behave like `DataGolfClient._api_call` but without authentication headers.

- **test_successful_get**: Mock a 200 response with JSON body. Assert returns `{"status": "ok", "data": <parsed_json>}`.
- **test_429_triggers_retry**: Mock first response as 429, second as 200. Assert the method retries and ultimately returns success. Assert `time.sleep` was called with backoff delay.
- **test_5xx_triggers_retry**: Mock a 500 response followed by a 200. Assert retry and eventual success.
- **test_persistent_failure**: Mock all responses as 500 (3 attempts). Assert returns `{"status": "error", "code": None, "message": ...}` after exhausting retries.
- **test_network_timeout**: Mock `requests.get` raising `requests.exceptions.Timeout`. Assert retries then returns error envelope if persistent.
- **test_rate_limit_delay**: After a successful 200 response, assert `time.sleep(0.1)` is called (rate limiting between calls).

### TestKalshiPagination

The client must handle Kalshi's cursor-based pagination. Endpoints return `{"cursor": "...", "<collection_key>": [...]}`. When `cursor` is a non-empty string, there are more pages. The client should loop, accumulating results, until `cursor` is empty or absent.

- **test_single_page**: Mock response with `{"events": [...], "cursor": ""}`. Assert all items returned in a single list, no second request made.
- **test_multi_page**: Mock first response with `cursor: "abc123"` and 3 items, second response with `cursor: ""` and 2 items. Assert 5 total items returned and two HTTP requests were made (second includes `cursor=abc123` param).
- **test_empty_cursor_stops**: Mock response with empty cursor string. Assert pagination stops after one request.

### TestGetGolfEvents

- **test_returns_open_events**: Mock `_api_call` to return a list of events. Assert `get_golf_events("KXPGATOUR")` calls the correct endpoint (`/events`) with params `series_ticker=KXPGATOUR` and `status=open`.
- **test_filters_open_only**: The endpoint param `status=open` is passed, so filtering is server-side. Verify the param is included.
- **test_empty_result**: Mock empty events list. Assert returns empty list (not an error).

### TestGetEventMarkets

- **test_returns_markets**: Mock `_api_call` returning a list of market dicts. Assert `get_event_markets("EVENT-123")` calls `/markets` with `event_ticker=EVENT-123`.
- **test_paginated_markets**: Mock multi-page response. Assert all markets from all pages are concatenated.
- **test_unknown_event**: Mock empty markets list. Assert returns empty list.

### TestCacheResponse

- **test_cache_path_structure**: Call `_cache_response(data, "kalshi_win", "masters-2026")`. Assert file written to `{cache_dir}/masters-2026/{timestamp}/kalshi_win.json`.
- **test_tournament_slug_subdir**: When `tournament_slug` is provided, it creates a subdirectory.
- **test_valid_json**: Read back the cached file and assert it parses as valid JSON matching the input data.

## Implementation Details -- `src/api/kalshi.py`

### Class Signature

```python
class KalshiClient:
    """Client for the Kalshi prediction market API (read-only).

    No authentication required for market data endpoints.
    Rate limited to 0.1s between calls (conservative vs 20/sec limit).
    Responses cached to data/raw/{tournament_slug}/{timestamp}/kalshi_*.json.
    """

    def __init__(self, base_url: str | None = None, cache_dir: str | None = None): ...
    def _api_call(self, endpoint: str, params: dict | None = None) -> dict: ...
    def _paginated_call(self, endpoint: str, params: dict | None = None, collection_key: str = "events") -> list: ...
    def _cache_response(self, data: dict, label: str, tournament_slug: str | None = None) -> Path: ...
    def get_golf_events(self, series_ticker: str) -> list[dict]: ...
    def get_event_markets(self, event_ticker: str) -> list[dict]: ...
    def get_market(self, ticker: str) -> dict: ...
    def get_orderbook(self, ticker: str) -> dict: ...
```

### Constructor (`__init__`)

- Set `self.base_url` from parameter or from `config.KALSHI_BASE_URL` (with fallback to `"https://api.elections.kalshi.com/trade-api/v2"`).
- Set `self.rate_limit_delay` from `config.KALSHI_RATE_LIMIT_DELAY` (fallback `0.1`).
- Set `self.cache_dir` as `Path(cache_dir)` or `Path("data/raw")`.
- Set `self.timeout` from `config.API_TIMEOUT` (same as DG: 30s).
- Set `self.max_retries` from `config.API_MAX_RETRIES` (same as DG: 3).
- No API key needed. No validation/error on missing key.
- Use `getattr(config, "KALSHI_BASE_URL", "https://...")` pattern to gracefully handle the case where section-03 config constants have not been added yet.

### `_api_call(endpoint, params)`

Follow the same structure as `DataGolfClient._api_call`:

1. Build URL as `{base_url}{endpoint}`.
2. No API key injection (unlike DG).
3. Loop up to `max_retries` attempts:
   - `requests.get(url, params=params, timeout=self.timeout)`
   - **200**: sleep `rate_limit_delay`, return `{"status": "ok", "data": resp.json()}`.
   - **429**: exponential backoff `(attempt + 1) * 5` seconds, retry.
   - **400**: return error immediately (no retry).
   - **5xx**: backoff `(attempt + 1) * 3` seconds, retry.
   - **Timeout/RequestException**: sleep 3s, retry.
4. After all retries exhausted: return `{"status": "error", "code": None, "message": f"Max retries ({max_retries}) exceeded for {endpoint}"}`.

### `_paginated_call(endpoint, params, collection_key)`

This is a new method not present in `DataGolfClient` (DG does not use pagination). It handles Kalshi's cursor-based pagination:

1. Initialize `all_results = []` and `cursor = None`.
2. Loop:
   - If `cursor` is not None, add `"cursor": cursor` to params.
   - Set `"limit": 200` in params (Kalshi's max page size).
   - Call `self._api_call(endpoint, params)`.
   - If status is "error", return whatever results were collected so far (or empty list).
   - Extract items from `response["data"][collection_key]` and extend `all_results`.
   - Extract `cursor = response["data"].get("cursor", "")`.
   - If cursor is empty or falsy, break.
3. Return `all_results`.

### `get_golf_events(series_ticker)`

```python
def get_golf_events(self, series_ticker: str) -> list[dict]:
    """Fetch open events for a Kalshi golf series.

    Args:
        series_ticker: e.g., "KXPGATOUR", "KXPGATOP10", "KXPGATOP20", "KXPGAH2H"

    Returns:
        List of event dicts with tickers, titles, expiration dates.
        Empty list if none found or on error.
    """
```

Calls `_paginated_call("/events", {"series_ticker": series_ticker, "status": "open"}, collection_key="events")`.

### `get_event_markets(event_ticker)`

```python
def get_event_markets(self, event_ticker: str) -> list[dict]:
    """Fetch all markets (player contracts) for a Kalshi event.

    Each market dict includes ticker, title, subtitle, yes_bid, yes_ask,
    open_interest, and other fields.

    Returns:
        List of market dicts. Empty list on error.
    """
```

Calls `_paginated_call("/markets", {"event_ticker": event_ticker}, collection_key="markets")`.

The key fields to expect in each market dict (used by downstream pipeline code in section-05):
- `ticker` -- unique market identifier
- `title` / `subtitle` -- contains player name
- `yes_bid` / `yes_ask` -- current best bid/ask in cents (integer, 1-99) **or** `yes_bid_dollars` / `yes_ask_dollars` as dollar strings. The client should not transform these -- leave that to the pipeline module.
- `open_interest` -- number of contracts traded
- `status` -- should be "open" for active markets

### `get_market(ticker)`

```python
def get_market(self, ticker: str) -> dict:
    """Fetch a single market by ticker. Returns market dict or error envelope."""
```

Calls `_api_call(f"/markets/{ticker}")`. Returns `response["data"]` on success or error envelope on failure. This is used for individual market detail when needed (not for bulk pulls).

### `get_orderbook(ticker)`

```python
def get_orderbook(self, ticker: str) -> dict:
    """Fetch the full orderbook for a market. Used for deeper liquidity analysis.

    Returns:
        Orderbook dict with yes/no bids and asks at each price level.
        Error envelope on failure.
    """
```

Calls `_api_call(f"/markets/{ticker}/orderbook")`. Only called for markets that pass initial filtering in the pipeline (section-05), not for every market.

### `_cache_response(data, label, tournament_slug)`

Identical to `DataGolfClient._cache_response`. Writes JSON to `{cache_dir}/{tournament_slug}/{YYYY-MM-DD_HHMM}/{label}.json`. Creates directories as needed.

## Key Design Decisions

1. **No authentication.** Kalshi market data is public. If Kalshi ever requires auth for these endpoints, the client can be extended with an API key header, but for now it is not needed.

2. **Pagination is mandatory.** Unlike DataGolf, Kalshi paginates results. The `_paginated_call` helper abstracts this so callers (`get_golf_events`, `get_event_markets`) get flat lists.

3. **Raw data passthrough.** The client returns raw Kalshi API responses without transformation. Price normalization (cents vs dollars), player name extraction, and filtering happen in the pipeline module (section-05). This keeps the client simple and testable.

4. **Error envelope consistency.** The `{"status": "ok"/"error", ...}` envelope matches `DataGolfClient` exactly, so downstream code can handle both clients with the same error-checking pattern.

5. **Conservative rate limiting.** 0.1s between calls (10 req/sec effective) leaves margin vs Kalshi's 20 req/sec limit. This is configurable via `config.KALSHI_RATE_LIMIT_DELAY` (added in section-03).

6. **Future: Polymarket.** Leave a comment at the top of `src/api/kalshi.py` noting that `src/api/polymarket.py` would follow the same client pattern (Gamma API for discovery, CLOB API for prices, no auth for reads).

---

## Implementation Notes (Post-Build)

**Files created:** `src/api/kalshi.py`, `tests/test_kalshi_client.py`

**Deviations from plan:**
- Added getattr fallback for `API_TIMEOUT` and `API_MAX_RETRIES` (consistency with KALSHI_BASE_URL pattern).
- Added max_pages=50 guard on `_paginated_call` to prevent infinite loops from stuck cursors.
- Added print warning when pagination encounters mid-stream API errors (previously silent).

**Final test count:** 21 tests, all passing.