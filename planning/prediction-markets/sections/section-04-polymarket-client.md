# Section 04: Polymarket API Client

## Overview

This section implements `src/api/polymarket.py`, a read-only API client for the Polymarket prediction market. Polymarket uses two separate API hosts: the **Gamma API** for event/market discovery and the **CLOB API** for orderbook pricing data. No authentication is required for read operations.

The client follows the same patterns established by the existing `KalshiClient` in `src/api/kalshi.py`: response envelopes, retry with backoff, rate limiting, and local response caching.

## Dependencies

- **Section 01 (config):** Requires `POLYMARKET_GAMMA_URL`, `POLYMARKET_CLOB_URL`, `POLYMARKET_RATE_LIMIT_DELAY`, `POLYMARKET_GOLF_TAG_ID`, `API_TIMEOUT`, `API_MAX_RETRIES` constants in `config.py`.

## File to Create

`src/api/polymarket.py`

## Tests (Write First)

Create `tests/test_polymarket_client.py`. All tests use pytest and unittest.mock, following the same patterns as existing Kalshi tests. HTTP calls are mocked at the `requests.get` level.

### Test Stubs

```python
"""Tests for Polymarket API client."""

class TestConstructor:
    # Test: PolymarketClient() reads config defaults (gamma_url, clob_url, rate_limit_delay)
    # Test: PolymarketClient(gamma_url=..., clob_url=...) uses overrides

class TestApiCall:
    # Test: _api_call returns ok envelope on 200 response
    # Test: _api_call retries on 429 with exponential backoff
    # Test: _api_call retries on 5xx with backoff
    # Test: _api_call returns error envelope on 400 (no retry)
    # Test: _api_call returns error envelope after max retries exhausted
    # Test: _api_call uses correct base_url (gamma vs clob)
    # Test: _api_call respects rate_limit_delay between calls

class TestPaginatedCall:
    # Test: _paginated_call accumulates results across multiple pages
    # Test: _paginated_call stops when response has fewer items than limit
    # Test: _paginated_call stops at 50-page safety limit and logs warning
    # Test: _paginated_call returns partial results on mid-pagination failure

class TestCacheResponse:
    # Test: _cache_response writes JSON to data/raw/{slug}/{timestamp}/polymarket_{label}.json
    # Test: _cache_response creates directories if needed

class TestGetGolfTagId:
    # Test: get_golf_tag_id returns tag_id from /sports response
    # Test: get_golf_tag_id caches result on instance (second call doesn't hit API)
    # Test: get_golf_tag_id falls back to env var when API fails

class TestGetGolfEvents:
    # Test: get_golf_events passes golf tag_id and active/closed filters
    # Test: get_golf_events passes market_type_filter when provided
    # Test: get_golf_events returns list of event dicts with nested markets

class TestGetBooks:
    # Test: get_books returns bid/ask data for single token_id
    # Test: get_books chunks requests into batches of 50 when >50 token_ids
    # Test: get_books merges results across chunks correctly
    # Test: get_books handles empty response for unknown token_ids
```

## Implementation Details

### Class: `PolymarketClient`

### Constructor

Accepts optional `gamma_url`, `clob_url`, `cache_dir` for testability. Falls back to config values. Stores `rate_limit_delay`, `timeout`, `max_retries`. Initializes `_golf_tag_id = None` for lazy caching.

### `_api_call(base_url, endpoint, params=None)`

Core GET request method with retry/rate-limit logic. Takes `base_url` as a parameter since Polymarket uses two hosts. Behavior:

- **200**: return `{"status": "ok", "data": resp.json()}`
- **429**: exponential backoff `(attempt + 1) * 5` seconds, then retry
- **400**: immediate return `{"status": "error", "code": 400, "message": ...}` (no retry)
- **5xx**: backoff `(attempt + 1) * 3` seconds, then retry
- **Timeout**: 3-second wait, then retry
- After `max_retries` exhausted: return error envelope

Sleep `rate_limit_delay` after each successful 200 response. Identical to KalshiClient pattern except `base_url` is a parameter.

### `_paginated_call(base_url, endpoint, params=None, collection_key=None)`

Offset-based pagination (different from Kalshi's cursor-based):

- Uses `limit=100` and incrementing `offset` (starting at 0)
- If `collection_key` provided, extract items from `response["data"][collection_key]`; otherwise treat `response["data"]` as the item list
- Stop when a page returns fewer items than `limit`
- Safety limit: max 50 pages; log warning if hit
- On mid-pagination error, return accumulated results

### `_cache_response(data, label, tournament_slug=None)`

Identical to KalshiClient pattern. Writes to `data/raw/{slug}/{timestamp}/polymarket_{label}.json`.

### `get_golf_tag_id()`

Discovers the golf sport tag ID:

1. If `self._golf_tag_id` cached, return it
2. Call `GET {gamma_url}/sports`, find golf entry
3. Cache and return the `tag_id`
4. On failure, fall back to `config.POLYMARKET_GOLF_TAG_ID` env var
5. If all else fails, return `None`

### `get_golf_events(market_type_filter=None)`

1. Get golf `tag_id` via `get_golf_tag_id()`
2. Call `GET {gamma_url}/events` with `tag_id`, `active=true`, `closed=false`
3. If `market_type_filter` provided, pass as `sports_market_types` param
4. Use `_paginated_call` for multiple pages
5. Return list of event dicts (each includes nested `markets[]`)

### `get_event_markets(event_id)`

Calls `GET {gamma_url}/events/{event_id}`, returns the `markets` array.

### `get_midpoints(token_ids)`

Calls `GET {clob_url}/midpoints` with token IDs. Returns dict `token_id -> midpoint_price_string`.

### `get_books(token_ids)`

Fetches full orderbook data from CLOB API. **Chunks into batches of 50 token_ids** to avoid 414 URI Too Long:

1. Split `token_ids` into chunks of 50
2. For each chunk, call `GET {clob_url}/books` with token IDs as query params
3. Merge all response dicts
4. Return combined dict `token_id -> {"bids": [...], "asks": [...]}`

### Design Notes

- Batch CLOB endpoints preferred over per-token calls for efficiency
- No authentication required for any read endpoint
- Gamma API provides `outcomePrices` inline, but CLOB provides bid/ask spreads needed for filtering

### Key Differences from KalshiClient

1. **Dual base URLs** — `_api_call` takes `base_url` as parameter
2. **Offset pagination** instead of cursor pagination
3. **`get_golf_tag_id()`** — runtime sport tag discovery (Kalshi uses known series tickers)
4. **`get_books()` with chunking** — batch orderbook fetches in groups of 50

## Verification Checklist

1. `PolymarketClient()` initializes with correct config defaults
2. `_api_call` uses correct base_url for Gamma vs CLOB calls
3. `get_books` chunks 100+ token_ids into batches of 50
4. `get_golf_tag_id` caches on instance and falls back to env var
5. All pagination, retry, and caching behavior matches Kalshi patterns
6. `uv run pytest tests/test_polymarket_client.py` passes
