from __future__ import annotations

"""
Kalshi prediction market API client (read-only).

Fetches golf binary contracts from Kalshi's public market data endpoints.
No authentication required. Rate limited to 0.1s between calls.
Responses cached locally in data/raw/ with timestamps.

Follows the same patterns as DataGolfClient (response envelopes, retry,
caching). Adds cursor-based pagination (Kalshi-specific).

Future: src/api/polymarket.py would follow the same client pattern
(Gamma API for discovery, CLOB API for prices, no auth for reads).
"""

import json
import time
from datetime import datetime
from pathlib import Path

import requests

import config


class KalshiClient:
    """Client for the Kalshi prediction market API (read-only).

    No authentication required for market data endpoints.
    Rate limited to 0.1s between calls (conservative vs 20/sec limit).
    Responses cached to data/raw/{tournament_slug}/{timestamp}/kalshi_*.json.
    """

    def __init__(self, base_url: str | None = None,
                 cache_dir: str | None = None):
        self.base_url = base_url or getattr(
            config, "KALSHI_BASE_URL",
            "https://api.elections.kalshi.com/trade-api/v2",
        )
        self.rate_limit_delay = getattr(config, "KALSHI_RATE_LIMIT_DELAY", 0.1)
        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/raw")
        self.timeout = getattr(config, "API_TIMEOUT", 30)
        self.max_retries = getattr(config, "API_MAX_RETRIES", 3)

    def _api_call(self, endpoint: str, params: dict | None = None) -> dict:
        """Make a GET request with rate limiting and retry logic.

        Returns:
            {"status": "ok", "data": <response>} or
            {"status": "error", "code": int|None, "message": str}
        """
        if params is None:
            params = {}

        url = f"{self.base_url}{endpoint}"

        for attempt in range(self.max_retries):
            try:
                resp = requests.get(url, params=params, timeout=self.timeout)

                if resp.status_code == 200:
                    time.sleep(self.rate_limit_delay)
                    try:
                        return {"status": "ok", "data": resp.json()}
                    except json.JSONDecodeError:
                        return {"status": "ok", "data": resp.text}

                elif resp.status_code == 429:
                    wait = (attempt + 1) * 5
                    print(f"  Rate limited. Waiting {wait}s...")
                    time.sleep(wait)

                elif resp.status_code == 400:
                    return {
                        "status": "error",
                        "code": 400,
                        "message": resp.text[:500],
                    }

                else:
                    wait = (attempt + 1) * 3
                    print(f"  HTTP {resp.status_code}. Retrying in {wait}s...")
                    time.sleep(wait)

            except requests.exceptions.Timeout:
                print(f"  Timeout on attempt {attempt + 1}. Retrying...")
                time.sleep(3)

            except requests.exceptions.RequestException as e:
                print(f"  Request error: {e}. Retrying...")
                time.sleep(3)

        return {
            "status": "error",
            "code": None,
            "message": f"Max retries ({self.max_retries}) exceeded for {endpoint}",
        }

    def _paginated_call(self, endpoint: str, params: dict | None = None,
                        collection_key: str = "events") -> list:
        """Handle Kalshi's cursor-based pagination.

        Accumulates all results across pages into a single list.
        """
        if params is None:
            params = {}

        all_results = []
        cursor = None
        max_pages = 50

        for _page in range(max_pages):
            page_params = dict(params)
            page_params["limit"] = 200
            if cursor:
                page_params["cursor"] = cursor

            response = self._api_call(endpoint, page_params)

            if response["status"] != "ok":
                print(f"  Warning: pagination error on {endpoint}, returning {len(all_results)} partial results")
                break

            data = response["data"]
            items = data.get(collection_key, [])
            all_results.extend(items)

            cursor = data.get("cursor", "")
            if not cursor:
                break

        return all_results

    def _cache_response(self, data, label: str,
                        tournament_slug: str | None = None) -> Path:
        """Cache API response to local filesystem.

        Returns:
            Path to cached file
        """
        date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
        if tournament_slug:
            cache_path = self.cache_dir / tournament_slug / date_str
        else:
            cache_path = self.cache_dir / date_str

        cache_path.mkdir(parents=True, exist_ok=True)
        filepath = cache_path / f"{label}.json"

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return filepath

    def get_golf_events(self, series_ticker: str) -> list[dict]:
        """Fetch open events for a Kalshi golf series.

        Args:
            series_ticker: e.g., "KXPGATOUR", "KXPGATOP10", "KXPGATOP20", "KXPGAH2H"

        Returns:
            List of event dicts with tickers, titles, expiration dates.
            Empty list if none found or on error.
        """
        return self._paginated_call(
            "/events",
            {"series_ticker": series_ticker, "status": "open"},
            collection_key="events",
        )

    def get_event_markets(self, event_ticker: str) -> list[dict]:
        """Fetch all markets (player contracts) for a Kalshi event.

        Each market dict includes ticker, title, subtitle, yes_bid, yes_ask,
        open_interest, and other fields.

        Returns:
            List of market dicts. Empty list on error.
        """
        return self._paginated_call(
            "/markets",
            {"event_ticker": event_ticker},
            collection_key="markets",
        )

    def get_market(self, ticker: str) -> dict:
        """Fetch a single market by ticker."""
        response = self._api_call(f"/markets/{ticker}")
        if response["status"] == "ok":
            return response["data"]
        return response

    def get_orderbook(self, ticker: str) -> dict:
        """Fetch the full orderbook for a market.

        Returns:
            Orderbook dict with yes/no bids and asks at each price level.
            Error envelope on failure.
        """
        response = self._api_call(f"/markets/{ticker}/orderbook")
        if response["status"] == "ok":
            return response["data"]
        return response
