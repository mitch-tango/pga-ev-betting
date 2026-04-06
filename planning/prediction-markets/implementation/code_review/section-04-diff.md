diff --git a/planning/prediction-markets/implementation/deep_implement_config.json b/planning/prediction-markets/implementation/deep_implement_config.json
index c71d736..309550b 100644
--- a/planning/prediction-markets/implementation/deep_implement_config.json
+++ b/planning/prediction-markets/implementation/deep_implement_config.json
@@ -27,6 +27,10 @@
     "section-02-devig-refactor": {
       "status": "complete",
       "commit_hash": "ae995e0"
+    },
+    "section-03-edge-updates": {
+      "status": "complete",
+      "commit_hash": "e31f2b1"
     }
   },
   "pre_commit": {
diff --git a/src/api/polymarket.py b/src/api/polymarket.py
new file mode 100644
index 0000000..1d76174
--- /dev/null
+++ b/src/api/polymarket.py
@@ -0,0 +1,303 @@
+from __future__ import annotations
+
+"""
+Polymarket prediction market API client (read-only).
+
+Uses two API hosts:
+- Gamma API: event/market discovery (events, markets, sports tags)
+- CLOB API: orderbook pricing data (books, midpoints)
+
+No authentication required for read operations. Rate limited.
+Responses cached locally in data/raw/ with timestamps.
+
+Follows the same patterns as KalshiClient (response envelopes, retry,
+caching). Uses offset-based pagination instead of cursor-based.
+"""
+
+import json
+import logging
+import time
+from datetime import datetime
+from pathlib import Path
+
+import requests
+
+import config
+
+logger = logging.getLogger(__name__)
+
+
+class PolymarketClient:
+    """Client for the Polymarket prediction market API (read-only).
+
+    No authentication required. Rate limited to 0.1s between calls.
+    Responses cached to data/raw/{tournament_slug}/{timestamp}/polymarket_*.json.
+    """
+
+    BOOK_CHUNK_SIZE = 50  # Max token_ids per CLOB /books request
+
+    def __init__(
+        self,
+        gamma_url: str | None = None,
+        clob_url: str | None = None,
+        cache_dir: str | None = None,
+    ):
+        self.gamma_url = gamma_url or getattr(
+            config, "POLYMARKET_GAMMA_URL",
+            "https://gamma-api.polymarket.com",
+        )
+        self.clob_url = clob_url or getattr(
+            config, "POLYMARKET_CLOB_URL",
+            "https://clob.polymarket.com",
+        )
+        self.rate_limit_delay = getattr(config, "POLYMARKET_RATE_LIMIT_DELAY", 0.1)
+        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/raw")
+        self.timeout = getattr(config, "API_TIMEOUT", 30)
+        self.max_retries = getattr(config, "API_MAX_RETRIES", 3)
+        self._golf_tag_id: str | None = None
+
+    def _api_call(self, base_url: str, endpoint: str,
+                  params: dict | None = None) -> dict:
+        """Make a GET request with rate limiting and retry logic.
+
+        Args:
+            base_url: Either gamma_url or clob_url.
+            endpoint: API path (e.g., "/events", "/books").
+            params: Query parameters.
+
+        Returns:
+            {"status": "ok", "data": <response>} or
+            {"status": "error", "code": int|None, "message": str}
+        """
+        if params is None:
+            params = {}
+
+        url = f"{base_url}{endpoint}"
+
+        for attempt in range(self.max_retries):
+            try:
+                resp = requests.get(url, params=params, timeout=self.timeout)
+
+                if resp.status_code == 200:
+                    time.sleep(self.rate_limit_delay)
+                    try:
+                        return {"status": "ok", "data": resp.json()}
+                    except json.JSONDecodeError:
+                        return {"status": "ok", "data": resp.text}
+
+                elif resp.status_code == 429:
+                    wait = (attempt + 1) * 5
+                    logger.warning("Rate limited. Waiting %ds...", wait)
+                    time.sleep(wait)
+
+                elif resp.status_code == 400:
+                    return {
+                        "status": "error",
+                        "code": 400,
+                        "message": resp.text[:500],
+                    }
+
+                else:
+                    wait = (attempt + 1) * 3
+                    logger.warning("HTTP %d. Retrying in %ds...",
+                                   resp.status_code, wait)
+                    time.sleep(wait)
+
+            except requests.exceptions.Timeout:
+                logger.warning("Timeout on attempt %d. Retrying...", attempt + 1)
+                time.sleep(3)
+
+            except requests.exceptions.RequestException as e:
+                logger.warning("Request error: %s. Retrying...", e)
+                time.sleep(3)
+
+        return {
+            "status": "error",
+            "code": None,
+            "message": f"Max retries ({self.max_retries}) exceeded for {endpoint}",
+        }
+
+    def _paginated_call(
+        self,
+        base_url: str,
+        endpoint: str,
+        params: dict | None = None,
+        collection_key: str | None = None,
+    ) -> list:
+        """Offset-based pagination for Polymarket APIs.
+
+        Accumulates all results across pages into a single list.
+
+        Args:
+            base_url: Gamma or CLOB base URL.
+            endpoint: API path.
+            params: Base query parameters.
+            collection_key: If set, extract items from response[collection_key].
+                Otherwise treat the response as the item list directly.
+        """
+        if params is None:
+            params = {}
+
+        all_results = []
+        limit = 100
+        max_pages = 50
+
+        for page in range(max_pages):
+            page_params = dict(params)
+            page_params["limit"] = limit
+            page_params["offset"] = page * limit
+
+            response = self._api_call(base_url, endpoint, page_params)
+
+            if response["status"] != "ok":
+                logger.warning(
+                    "Pagination error on %s, returning %d partial results",
+                    endpoint, len(all_results))
+                break
+
+            data = response["data"]
+            if collection_key:
+                items = data.get(collection_key, []) if isinstance(data, dict) else []
+            else:
+                items = data if isinstance(data, list) else []
+
+            all_results.extend(items)
+
+            if len(items) < limit:
+                break
+
+            if page == max_pages - 1:
+                logger.warning(
+                    "Hit %d-page safety limit on %s", max_pages, endpoint)
+
+        return all_results
+
+    def _cache_response(self, data, label: str,
+                        tournament_slug: str | None = None) -> Path:
+        """Cache API response to local filesystem."""
+        date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
+        if tournament_slug:
+            cache_path = self.cache_dir / tournament_slug / date_str
+        else:
+            cache_path = self.cache_dir / date_str
+
+        cache_path.mkdir(parents=True, exist_ok=True)
+        filepath = cache_path / f"{label}.json"
+
+        with open(filepath, "w", encoding="utf-8") as f:
+            json.dump(data, f, indent=2, ensure_ascii=False)
+
+        return filepath
+
+    def get_golf_tag_id(self) -> str | None:
+        """Discover the golf sport tag ID from Gamma API.
+
+        Caches the result on the instance. Falls back to
+        config.POLYMARKET_GOLF_TAG_ID env var on API failure.
+        """
+        if self._golf_tag_id is not None:
+            return self._golf_tag_id
+
+        response = self._api_call(self.gamma_url, "/sports")
+
+        if response["status"] == "ok":
+            sports = response["data"]
+            if isinstance(sports, list):
+                for sport in sports:
+                    if isinstance(sport, dict) and "golf" in sport.get("label", "").lower():
+                        self._golf_tag_id = sport.get("tag_id")
+                        return self._golf_tag_id
+
+        # Fallback to env var
+        fallback = getattr(config, "POLYMARKET_GOLF_TAG_ID", None)
+        if fallback:
+            self._golf_tag_id = fallback
+            return self._golf_tag_id
+
+        logger.warning("Could not discover golf tag_id from Polymarket")
+        return None
+
+    def get_golf_events(self, market_type_filter: str | None = None) -> list[dict]:
+        """Fetch active golf events from Gamma API.
+
+        Args:
+            market_type_filter: Optional sports_market_types filter
+                (e.g., "winner", "top-10").
+
+        Returns:
+            List of event dicts with nested markets[]. Empty list on failure.
+        """
+        tag_id = self.get_golf_tag_id()
+        if not tag_id:
+            return []
+
+        params = {
+            "tag_id": tag_id,
+            "active": "true",
+            "closed": "false",
+        }
+        if market_type_filter:
+            params["sports_market_types"] = market_type_filter
+
+        return self._paginated_call(self.gamma_url, "/events", params=params)
+
+    def get_event_markets(self, event_id: str) -> list[dict]:
+        """Fetch markets for a specific event.
+
+        Returns:
+            List of market dicts. Empty list on error.
+        """
+        response = self._api_call(self.gamma_url, f"/events/{event_id}")
+        if response["status"] == "ok":
+            data = response["data"]
+            if isinstance(data, dict):
+                return data.get("markets", [])
+        return []
+
+    def get_midpoints(self, token_ids: list[str]) -> dict[str, str]:
+        """Fetch midpoint prices from CLOB API.
+
+        Returns:
+            Dict of token_id -> midpoint_price_string.
+        """
+        if not token_ids:
+            return {}
+
+        response = self._api_call(
+            self.clob_url, "/midpoints",
+            params={"token_ids": token_ids},
+        )
+        if response["status"] == "ok":
+            return response["data"] if isinstance(response["data"], dict) else {}
+        return {}
+
+    def get_books(self, token_ids: list[str]) -> dict[str, dict]:
+        """Fetch orderbook data from CLOB API.
+
+        Chunks requests into batches of 50 token_ids to avoid
+        414 URI Too Long errors.
+
+        Returns:
+            Dict of token_id -> {"bids": [...], "asks": [...]}.
+        """
+        if not token_ids:
+            return {}
+
+        merged = {}
+        for i in range(0, len(token_ids), self.BOOK_CHUNK_SIZE):
+            chunk = token_ids[i:i + self.BOOK_CHUNK_SIZE]
+            response = self._api_call(
+                self.clob_url, "/books",
+                params={"token_ids": chunk},
+            )
+            if response["status"] == "ok":
+                data = response["data"]
+                if isinstance(data, list):
+                    for book in data:
+                        asset_id = book.get("asset_id")
+                        if asset_id:
+                            merged[asset_id] = book
+                elif isinstance(data, dict):
+                    merged.update(data)
+
+        return merged
diff --git a/tests/test_polymarket_client.py b/tests/test_polymarket_client.py
new file mode 100644
index 0000000..b80b564
--- /dev/null
+++ b/tests/test_polymarket_client.py
@@ -0,0 +1,331 @@
+"""Unit tests for src/api/polymarket.py"""
+
+import json
+import logging
+from pathlib import Path
+from unittest.mock import patch, MagicMock
+
+import requests
+from src.api.polymarket import PolymarketClient
+
+
+class TestConstructor:
+    def test_default_config(self):
+        client = PolymarketClient()
+        assert "gamma-api.polymarket.com" in client.gamma_url
+        assert "clob.polymarket.com" in client.clob_url
+        assert client.rate_limit_delay == 0.1
+
+    def test_custom_urls(self):
+        client = PolymarketClient(
+            gamma_url="https://custom-gamma.com",
+            clob_url="https://custom-clob.com",
+        )
+        assert client.gamma_url == "https://custom-gamma.com"
+        assert client.clob_url == "https://custom-clob.com"
+
+    def test_cache_dir(self, tmp_path):
+        client = PolymarketClient(cache_dir=str(tmp_path))
+        assert client.cache_dir == tmp_path
+
+
+class TestApiCall:
+    @patch("src.api.polymarket.time.sleep")
+    @patch("src.api.polymarket.requests.get")
+    def test_successful_get(self, mock_get, mock_sleep):
+        mock_resp = MagicMock()
+        mock_resp.status_code = 200
+        mock_resp.json.return_value = [{"id": "1"}]
+        mock_get.return_value = mock_resp
+
+        client = PolymarketClient()
+        result = client._api_call(client.gamma_url, "/events")
+
+        assert result["status"] == "ok"
+        assert result["data"] == [{"id": "1"}]
+
+    @patch("src.api.polymarket.time.sleep")
+    @patch("src.api.polymarket.requests.get")
+    def test_429_retry(self, mock_get, mock_sleep):
+        resp_429 = MagicMock()
+        resp_429.status_code = 429
+
+        resp_200 = MagicMock()
+        resp_200.status_code = 200
+        resp_200.json.return_value = {"ok": True}
+
+        mock_get.side_effect = [resp_429, resp_200]
+
+        client = PolymarketClient()
+        result = client._api_call(client.gamma_url, "/events")
+
+        assert result["status"] == "ok"
+        assert any(call.args[0] >= 5 for call in mock_sleep.call_args_list)
+
+    @patch("src.api.polymarket.time.sleep")
+    @patch("src.api.polymarket.requests.get")
+    def test_5xx_retry(self, mock_get, mock_sleep):
+        resp_500 = MagicMock()
+        resp_500.status_code = 500
+
+        resp_200 = MagicMock()
+        resp_200.status_code = 200
+        resp_200.json.return_value = {"ok": True}
+
+        mock_get.side_effect = [resp_500, resp_200]
+
+        client = PolymarketClient()
+        result = client._api_call(client.gamma_url, "/events")
+
+        assert result["status"] == "ok"
+
+    @patch("src.api.polymarket.time.sleep")
+    @patch("src.api.polymarket.requests.get")
+    def test_400_no_retry(self, mock_get, mock_sleep):
+        resp_400 = MagicMock()
+        resp_400.status_code = 400
+        resp_400.text = "Bad request"
+        mock_get.return_value = resp_400
+
+        client = PolymarketClient()
+        result = client._api_call(client.gamma_url, "/events")
+
+        assert result["status"] == "error"
+        assert result["code"] == 400
+        assert mock_get.call_count == 1
+
+    @patch("src.api.polymarket.time.sleep")
+    @patch("src.api.polymarket.requests.get")
+    def test_max_retries_exhausted(self, mock_get, mock_sleep):
+        resp_500 = MagicMock()
+        resp_500.status_code = 500
+        mock_get.return_value = resp_500
+
+        client = PolymarketClient()
+        result = client._api_call(client.gamma_url, "/events")
+
+        assert result["status"] == "error"
+        assert "Max retries" in result["message"]
+
+    @patch("src.api.polymarket.time.sleep")
+    @patch("src.api.polymarket.requests.get")
+    def test_uses_correct_base_url(self, mock_get, mock_sleep):
+        mock_resp = MagicMock()
+        mock_resp.status_code = 200
+        mock_resp.json.return_value = {}
+        mock_get.return_value = mock_resp
+
+        client = PolymarketClient()
+        client._api_call(client.clob_url, "/books")
+
+        called_url = mock_get.call_args[0][0]
+        assert called_url.startswith("https://clob.polymarket.com")
+
+    @patch("src.api.polymarket.time.sleep")
+    @patch("src.api.polymarket.requests.get")
+    def test_rate_limit_delay(self, mock_get, mock_sleep):
+        mock_resp = MagicMock()
+        mock_resp.status_code = 200
+        mock_resp.json.return_value = {}
+        mock_get.return_value = mock_resp
+
+        client = PolymarketClient()
+        client._api_call(client.gamma_url, "/events")
+
+        mock_sleep.assert_called_with(0.1)
+
+
+class TestPaginatedCall:
+    @patch("src.api.polymarket.time.sleep")
+    @patch("src.api.polymarket.requests.get")
+    def test_accumulates_pages(self, mock_get, mock_sleep):
+        # Page 1: 100 items (full page -> fetch next)
+        resp1 = MagicMock()
+        resp1.status_code = 200
+        resp1.json.return_value = [{"id": str(i)} for i in range(100)]
+
+        # Page 2: 50 items (less than limit -> stop)
+        resp2 = MagicMock()
+        resp2.status_code = 200
+        resp2.json.return_value = [{"id": str(i)} for i in range(100, 150)]
+
+        mock_get.side_effect = [resp1, resp2]
+
+        client = PolymarketClient()
+        results = client._paginated_call(client.gamma_url, "/events")
+
+        assert len(results) == 150
+        assert mock_get.call_count == 2
+
+    @patch("src.api.polymarket.time.sleep")
+    @patch("src.api.polymarket.requests.get")
+    def test_stops_on_short_page(self, mock_get, mock_sleep):
+        resp = MagicMock()
+        resp.status_code = 200
+        resp.json.return_value = [{"id": "1"}, {"id": "2"}]
+        mock_get.return_value = resp
+
+        client = PolymarketClient()
+        results = client._paginated_call(client.gamma_url, "/events")
+
+        assert len(results) == 2
+        assert mock_get.call_count == 1
+
+    @patch("src.api.polymarket.time.sleep")
+    @patch("src.api.polymarket.requests.get")
+    def test_collection_key(self, mock_get, mock_sleep):
+        resp = MagicMock()
+        resp.status_code = 200
+        resp.json.return_value = {"data": [{"id": "1"}]}
+        mock_get.return_value = resp
+
+        client = PolymarketClient()
+        results = client._paginated_call(
+            client.gamma_url, "/events", collection_key="data")
+
+        assert len(results) == 1
+
+    @patch("src.api.polymarket.time.sleep")
+    @patch("src.api.polymarket.requests.get")
+    def test_partial_results_on_error(self, mock_get, mock_sleep):
+        resp1 = MagicMock()
+        resp1.status_code = 200
+        resp1.json.return_value = [{"id": str(i)} for i in range(100)]
+
+        resp2 = MagicMock()
+        resp2.status_code = 500
+        mock_get.side_effect = [resp1] + [resp2] * 3  # retries exhaust
+
+        client = PolymarketClient()
+        results = client._paginated_call(client.gamma_url, "/events")
+
+        assert len(results) == 100
+
+
+class TestCacheResponse:
+    def test_cache_path_structure(self, tmp_path):
+        client = PolymarketClient(cache_dir=str(tmp_path))
+        data = [{"id": "1"}]
+
+        filepath = client._cache_response(data, "polymarket_events", "masters-2026")
+
+        assert "masters-2026" in str(filepath)
+        assert filepath.name == "polymarket_events.json"
+        assert filepath.exists()
+
+    def test_valid_json(self, tmp_path):
+        client = PolymarketClient(cache_dir=str(tmp_path))
+        data = [{"id": "1", "title": "Test"}]
+
+        filepath = client._cache_response(data, "test_cache")
+
+        with open(filepath) as f:
+            loaded = json.load(f)
+        assert loaded == data
+
+
+class TestGetGolfTagId:
+    @patch.object(PolymarketClient, "_api_call")
+    def test_returns_tag_id(self, mock_api):
+        mock_api.return_value = {
+            "status": "ok",
+            "data": [
+                {"label": "Basketball", "tag_id": "111"},
+                {"label": "Golf", "tag_id": "222"},
+            ],
+        }
+
+        client = PolymarketClient()
+        tag_id = client.get_golf_tag_id()
+
+        assert tag_id == "222"
+
+    @patch.object(PolymarketClient, "_api_call")
+    def test_caches_on_instance(self, mock_api):
+        mock_api.return_value = {
+            "status": "ok",
+            "data": [{"label": "Golf", "tag_id": "222"}],
+        }
+
+        client = PolymarketClient()
+        client.get_golf_tag_id()
+        client.get_golf_tag_id()
+
+        assert mock_api.call_count == 1
+
+    @patch.object(PolymarketClient, "_api_call")
+    def test_fallback_to_env_var(self, mock_api):
+        mock_api.return_value = {"status": "error", "code": 500, "message": "fail"}
+
+        client = PolymarketClient()
+        with patch("src.api.polymarket.config.POLYMARKET_GOLF_TAG_ID", "env-tag-123"):
+            tag_id = client.get_golf_tag_id()
+
+        assert tag_id == "env-tag-123"
+
+
+class TestGetGolfEvents:
+    @patch.object(PolymarketClient, "get_golf_tag_id", return_value="222")
+    @patch.object(PolymarketClient, "_paginated_call")
+    def test_passes_tag_and_filters(self, mock_paginated, mock_tag):
+        mock_paginated.return_value = [{"id": "ev1"}]
+
+        client = PolymarketClient()
+        result = client.get_golf_events()
+
+        assert len(result) == 1
+        call_args = mock_paginated.call_args
+        params = call_args[1].get("params") or call_args[0][2]
+        assert params.get("tag_id") == "222"
+        assert params.get("active") == "true"
+        assert params.get("closed") == "false"
+
+    @patch.object(PolymarketClient, "get_golf_tag_id", return_value=None)
+    def test_returns_empty_when_no_tag(self, mock_tag):
+        client = PolymarketClient()
+        result = client.get_golf_events()
+
+        assert result == []
+
+
+class TestGetBooks:
+    @patch.object(PolymarketClient, "_api_call")
+    def test_single_token(self, mock_api):
+        mock_api.return_value = {
+            "status": "ok",
+            "data": [{"asset_id": "tok1", "bids": [{"price": "0.50"}], "asks": [{"price": "0.55"}]}],
+        }
+
+        client = PolymarketClient()
+        result = client.get_books(["tok1"])
+
+        assert "tok1" in result
+        assert result["tok1"]["asks"][0]["price"] == "0.55"
+
+    @patch.object(PolymarketClient, "_api_call")
+    def test_chunks_into_batches_of_50(self, mock_api):
+        # 75 tokens -> 2 calls (50 + 25)
+        tokens = [f"tok{i}" for i in range(75)]
+
+        def side_effect(base_url, endpoint, params=None):
+            token_ids = params.get("token_ids", []) if params else []
+            return {
+                "status": "ok",
+                "data": [{"asset_id": tid, "bids": [], "asks": []} for tid in token_ids],
+            }
+
+        mock_api.side_effect = side_effect
+
+        client = PolymarketClient()
+        result = client.get_books(tokens)
+
+        assert mock_api.call_count == 2
+        assert len(result) == 75
+
+    @patch.object(PolymarketClient, "_api_call")
+    def test_empty_token_list(self, mock_api):
+        client = PolymarketClient()
+        result = client.get_books([])
+
+        assert result == {}
+        assert mock_api.call_count == 0
