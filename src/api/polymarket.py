from __future__ import annotations

"""
Polymarket prediction market API client (read-only).

Uses two API hosts:
- Gamma API: event/market discovery (events, markets, sports tags)
- CLOB API: orderbook pricing data (books, midpoints)

No authentication required for read operations. Rate limited.
Responses cached locally in data/raw/ with timestamps.

Follows the same patterns as KalshiClient (response envelopes, retry,
caching). Uses offset-based pagination instead of cursor-based.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)


class PolymarketClient:
    """Client for the Polymarket prediction market API (read-only).

    No authentication required. Rate limited to 0.1s between calls.
    Responses cached to data/raw/{tournament_slug}/{timestamp}/polymarket_*.json.
    """

    BOOK_CHUNK_SIZE = 50  # Max token_ids per CLOB /books request

    def __init__(
        self,
        gamma_url: str | None = None,
        clob_url: str | None = None,
        cache_dir: str | None = None,
    ):
        self.gamma_url = gamma_url or getattr(
            config, "POLYMARKET_GAMMA_URL",
            "https://gamma-api.polymarket.com",
        )
        self.clob_url = clob_url or getattr(
            config, "POLYMARKET_CLOB_URL",
            "https://clob.polymarket.com",
        )
        self.rate_limit_delay = getattr(config, "POLYMARKET_RATE_LIMIT_DELAY", 0.1)
        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/raw")
        self.timeout = getattr(config, "API_TIMEOUT", 30)
        self.max_retries = getattr(config, "API_MAX_RETRIES", 3)
        self._golf_tag_id: str | None = None

    def _api_call(self, base_url: str, endpoint: str,
                  params: dict | None = None) -> dict:
        """Make a GET request with rate limiting and retry logic.

        Args:
            base_url: Either gamma_url or clob_url.
            endpoint: API path (e.g., "/events", "/books").
            params: Query parameters.

        Returns:
            {"status": "ok", "data": <response>} or
            {"status": "error", "code": int|None, "message": str}
        """
        if params is None:
            params = {}

        url = f"{base_url}{endpoint}"

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
                    logger.warning("Rate limited. Waiting %ds...", wait)
                    time.sleep(wait)

                elif resp.status_code in (400, 404):
                    return {
                        "status": "error",
                        "code": resp.status_code,
                        "message": resp.text[:500],
                    }

                else:
                    wait = (attempt + 1) * 3
                    logger.warning("HTTP %d. Retrying in %ds...",
                                   resp.status_code, wait)
                    time.sleep(wait)

            except requests.exceptions.Timeout:
                logger.warning("Timeout on attempt %d. Retrying...", attempt + 1)
                time.sleep(3)

            except requests.exceptions.RequestException as e:
                logger.warning("Request error: %s. Retrying...", e)
                time.sleep(3)

        return {
            "status": "error",
            "code": None,
            "message": f"Max retries ({self.max_retries}) exceeded for {endpoint}",
        }

    def _paginated_call(
        self,
        base_url: str,
        endpoint: str,
        params: dict | None = None,
        collection_key: str | None = None,
    ) -> list:
        """Offset-based pagination for Polymarket APIs.

        Accumulates all results across pages into a single list.

        Args:
            base_url: Gamma or CLOB base URL.
            endpoint: API path.
            params: Base query parameters.
            collection_key: If set, extract items from response[collection_key].
                Otherwise treat the response as the item list directly.
        """
        if params is None:
            params = {}

        all_results = []
        limit = 100
        max_pages = 50

        for page in range(max_pages):
            page_params = dict(params)
            page_params["limit"] = limit
            page_params["offset"] = page * limit

            response = self._api_call(base_url, endpoint, page_params)

            if response["status"] != "ok":
                logger.warning(
                    "Pagination error on %s, returning %d partial results",
                    endpoint, len(all_results))
                break

            data = response["data"]
            if collection_key:
                items = data.get(collection_key, []) if isinstance(data, dict) else []
            else:
                items = data if isinstance(data, list) else []

            all_results.extend(items)

            if len(items) < limit:
                break

            if page == max_pages - 1:
                logger.warning(
                    "Hit %d-page safety limit on %s", max_pages, endpoint)

        return all_results

    def _cache_response(self, data, label: str,
                        tournament_slug: str | None = None) -> Path:
        """Cache API response to local filesystem."""
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

    def get_golf_tag_id(self) -> str | None:
        """Discover the golf sport tag ID from Gamma API.

        Caches the result on the instance. Falls back to
        config.POLYMARKET_GOLF_TAG_ID env var on API failure.
        """
        if self._golf_tag_id is not None:
            return self._golf_tag_id

        response = self._api_call(self.gamma_url, "/sports")

        if response["status"] == "ok":
            sports = response["data"]
            if isinstance(sports, list):
                for sport in sports:
                    if isinstance(sport, dict) and "golf" in sport.get("label", "").lower():
                        self._golf_tag_id = sport.get("tag_id")
                        return self._golf_tag_id

        # Fallback to env var
        fallback = getattr(config, "POLYMARKET_GOLF_TAG_ID", None)
        if fallback:
            self._golf_tag_id = fallback
            return self._golf_tag_id

        logger.warning("Could not discover golf tag_id from Polymarket")
        return None

    def get_golf_events(self, market_type_filter: str | None = None) -> list[dict]:
        """Fetch active golf events from Gamma API.

        Args:
            market_type_filter: Optional sports_market_types filter
                (e.g., "winner", "top-10").

        Returns:
            List of event dicts with nested markets[]. Empty list on failure.
        """
        tag_id = self.get_golf_tag_id()
        if not tag_id:
            return []

        params = {
            "tag_id": tag_id,
            "active": "true",
            "closed": "false",
        }
        if market_type_filter:
            params["sports_market_types"] = market_type_filter

        return self._paginated_call(self.gamma_url, "/events", params=params)

    def get_event_markets(self, event_id: str) -> list[dict]:
        """Fetch markets for a specific event.

        Returns:
            List of market dicts. Empty list on error.
        """
        response = self._api_call(self.gamma_url, f"/events/{event_id}")
        if response["status"] == "ok":
            data = response["data"]
            if isinstance(data, dict):
                return data.get("markets", [])
        return []

    def get_midpoints(self, token_ids: list[str]) -> dict[str, str]:
        """Fetch midpoint prices from CLOB API.

        Chunks requests into batches of 50 token_ids (same as get_books).

        Returns:
            Dict of token_id -> midpoint_price_string.
        """
        if not token_ids:
            return {}

        merged = {}
        for i in range(0, len(token_ids), self.BOOK_CHUNK_SIZE):
            chunk = token_ids[i:i + self.BOOK_CHUNK_SIZE]
            response = self._api_call(
                self.clob_url, "/midpoints",
                params={"token_ids": ",".join(chunk)},
            )
            if response["status"] == "ok" and isinstance(response["data"], dict):
                merged.update(response["data"])

        return merged

    def get_books(self, token_ids: list[str]) -> dict[str, dict]:
        """Fetch orderbook data from CLOB API.

        Calls the /book endpoint once per token_id (the CLOB API does
        not support batch requests).

        Returns:
            Dict of token_id -> {"bids": [...], "asks": [...]}.
        """
        if not token_ids:
            return {}

        merged = {}
        for token_id in token_ids:
            response = self._api_call(
                self.clob_url, "/book",
                params={"token_id": token_id},
            )
            if response["status"] == "ok":
                data = response["data"]
                if isinstance(data, dict):
                    asset_id = data.get("asset_id", token_id)
                    merged[asset_id] = data

        return merged
