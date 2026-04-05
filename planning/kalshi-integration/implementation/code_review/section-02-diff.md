diff --git a/planning/kalshi-integration/implementation/deep_implement_config.json b/planning/kalshi-integration/implementation/deep_implement_config.json
index 65a6179..ab4fb4d 100644
--- a/planning/kalshi-integration/implementation/deep_implement_config.json
+++ b/planning/kalshi-integration/implementation/deep_implement_config.json
@@ -16,7 +16,12 @@
     "section-07-edge-deadheat",
     "section-08-workflow-integration"
   ],
-  "sections_state": {},
+  "sections_state": {
+    "section-01-odds-conversion": {
+      "status": "complete",
+      "commit_hash": "a3bc514"
+    }
+  },
   "pre_commit": {
     "present": false,
     "type": "none",
diff --git a/src/api/kalshi.py b/src/api/kalshi.py
new file mode 100644
index 0000000..04d5e9d
--- /dev/null
+++ b/src/api/kalshi.py
@@ -0,0 +1,202 @@
+from __future__ import annotations
+
+"""
+Kalshi prediction market API client (read-only).
+
+Fetches golf binary contracts from Kalshi's public market data endpoints.
+No authentication required. Rate limited to 0.1s between calls.
+Responses cached locally in data/raw/ with timestamps.
+
+Follows the same patterns as DataGolfClient (response envelopes, retry,
+caching). Adds cursor-based pagination (Kalshi-specific).
+
+Future: src/api/polymarket.py would follow the same client pattern
+(Gamma API for discovery, CLOB API for prices, no auth for reads).
+"""
+
+import json
+import time
+from datetime import datetime
+from pathlib import Path
+
+import requests
+
+import config
+
+
+class KalshiClient:
+    """Client for the Kalshi prediction market API (read-only).
+
+    No authentication required for market data endpoints.
+    Rate limited to 0.1s between calls (conservative vs 20/sec limit).
+    Responses cached to data/raw/{tournament_slug}/{timestamp}/kalshi_*.json.
+    """
+
+    def __init__(self, base_url: str | None = None,
+                 cache_dir: str | None = None):
+        self.base_url = base_url or getattr(
+            config, "KALSHI_BASE_URL",
+            "https://api.elections.kalshi.com/trade-api/v2",
+        )
+        self.rate_limit_delay = getattr(config, "KALSHI_RATE_LIMIT_DELAY", 0.1)
+        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/raw")
+        self.timeout = config.API_TIMEOUT
+        self.max_retries = config.API_MAX_RETRIES
+
+    def _api_call(self, endpoint: str, params: dict | None = None) -> dict:
+        """Make a GET request with rate limiting and retry logic.
+
+        Returns:
+            {"status": "ok", "data": <response>} or
+            {"status": "error", "code": int|None, "message": str}
+        """
+        if params is None:
+            params = {}
+
+        url = f"{self.base_url}{endpoint}"
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
+                    print(f"  Rate limited. Waiting {wait}s...")
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
+                    print(f"  HTTP {resp.status_code}. Retrying in {wait}s...")
+                    time.sleep(wait)
+
+            except requests.exceptions.Timeout:
+                print(f"  Timeout on attempt {attempt + 1}. Retrying...")
+                time.sleep(3)
+
+            except requests.exceptions.RequestException as e:
+                print(f"  Request error: {e}. Retrying...")
+                time.sleep(3)
+
+        return {
+            "status": "error",
+            "code": None,
+            "message": f"Max retries ({self.max_retries}) exceeded for {endpoint}",
+        }
+
+    def _paginated_call(self, endpoint: str, params: dict | None = None,
+                        collection_key: str = "events") -> list:
+        """Handle Kalshi's cursor-based pagination.
+
+        Accumulates all results across pages into a single list.
+        """
+        if params is None:
+            params = {}
+
+        all_results = []
+        cursor = None
+
+        while True:
+            page_params = dict(params)
+            page_params["limit"] = 200
+            if cursor:
+                page_params["cursor"] = cursor
+
+            response = self._api_call(endpoint, page_params)
+
+            if response["status"] != "ok":
+                break
+
+            data = response["data"]
+            items = data.get(collection_key, [])
+            all_results.extend(items)
+
+            cursor = data.get("cursor", "")
+            if not cursor:
+                break
+
+        return all_results
+
+    def _cache_response(self, data, label: str,
+                        tournament_slug: str | None = None) -> Path:
+        """Cache API response to local filesystem.
+
+        Returns:
+            Path to cached file
+        """
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
+    def get_golf_events(self, series_ticker: str) -> list[dict]:
+        """Fetch open events for a Kalshi golf series.
+
+        Args:
+            series_ticker: e.g., "KXPGATOUR", "KXPGATOP10", "KXPGATOP20", "KXPGAH2H"
+
+        Returns:
+            List of event dicts with tickers, titles, expiration dates.
+            Empty list if none found or on error.
+        """
+        return self._paginated_call(
+            "/events",
+            {"series_ticker": series_ticker, "status": "open"},
+            collection_key="events",
+        )
+
+    def get_event_markets(self, event_ticker: str) -> list[dict]:
+        """Fetch all markets (player contracts) for a Kalshi event.
+
+        Each market dict includes ticker, title, subtitle, yes_bid, yes_ask,
+        open_interest, and other fields.
+
+        Returns:
+            List of market dicts. Empty list on error.
+        """
+        return self._paginated_call(
+            "/markets",
+            {"event_ticker": event_ticker},
+            collection_key="markets",
+        )
+
+    def get_market(self, ticker: str) -> dict:
+        """Fetch a single market by ticker."""
+        response = self._api_call(f"/markets/{ticker}")
+        if response["status"] == "ok":
+            return response["data"]
+        return response
+
+    def get_orderbook(self, ticker: str) -> dict:
+        """Fetch the full orderbook for a market.
+
+        Returns:
+            Orderbook dict with yes/no bids and asks at each price level.
+            Error envelope on failure.
+        """
+        response = self._api_call(f"/markets/{ticker}/orderbook")
+        if response["status"] == "ok":
+            return response["data"]
+        return response
diff --git a/tests/test_kalshi_client.py b/tests/test_kalshi_client.py
new file mode 100644
index 0000000..07b3cd9
--- /dev/null
+++ b/tests/test_kalshi_client.py
@@ -0,0 +1,278 @@
+"""Unit tests for src/api/kalshi.py"""
+
+import json
+import sys
+from pathlib import Path
+from unittest.mock import patch, MagicMock
+
+sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
+
+import requests
+from src.api.kalshi import KalshiClient
+
+
+class TestKalshiClientInit:
+    def test_default_config(self):
+        client = KalshiClient()
+        assert "kalshi.com" in client.base_url
+        assert client.rate_limit_delay == 0.1
+
+    def test_custom_base_url(self):
+        client = KalshiClient(base_url="https://custom.api.com/v2")
+        assert client.base_url == "https://custom.api.com/v2"
+
+    def test_cache_dir_creation(self, tmp_path):
+        cache_dir = tmp_path / "kalshi_cache"
+        client = KalshiClient(cache_dir=str(cache_dir))
+        assert client.cache_dir == cache_dir
+
+
+class TestKalshiApiCall:
+    @patch("src.api.kalshi.time.sleep")
+    @patch("src.api.kalshi.requests.get")
+    def test_successful_get(self, mock_get, mock_sleep):
+        mock_resp = MagicMock()
+        mock_resp.status_code = 200
+        mock_resp.json.return_value = {"events": [{"ticker": "EVT-1"}]}
+        mock_get.return_value = mock_resp
+
+        client = KalshiClient()
+        result = client._api_call("/events")
+
+        assert result["status"] == "ok"
+        assert result["data"]["events"][0]["ticker"] == "EVT-1"
+
+    @patch("src.api.kalshi.time.sleep")
+    @patch("src.api.kalshi.requests.get")
+    def test_429_triggers_retry(self, mock_get, mock_sleep):
+        resp_429 = MagicMock()
+        resp_429.status_code = 429
+
+        resp_200 = MagicMock()
+        resp_200.status_code = 200
+        resp_200.json.return_value = {"ok": True}
+
+        mock_get.side_effect = [resp_429, resp_200]
+
+        client = KalshiClient()
+        result = client._api_call("/events")
+
+        assert result["status"] == "ok"
+        # Should have slept for backoff on 429
+        assert any(call.args[0] >= 5 for call in mock_sleep.call_args_list)
+
+    @patch("src.api.kalshi.time.sleep")
+    @patch("src.api.kalshi.requests.get")
+    def test_5xx_triggers_retry(self, mock_get, mock_sleep):
+        resp_500 = MagicMock()
+        resp_500.status_code = 500
+
+        resp_200 = MagicMock()
+        resp_200.status_code = 200
+        resp_200.json.return_value = {"ok": True}
+
+        mock_get.side_effect = [resp_500, resp_200]
+
+        client = KalshiClient()
+        result = client._api_call("/events")
+
+        assert result["status"] == "ok"
+
+    @patch("src.api.kalshi.time.sleep")
+    @patch("src.api.kalshi.requests.get")
+    def test_persistent_failure(self, mock_get, mock_sleep):
+        resp_500 = MagicMock()
+        resp_500.status_code = 500
+        mock_get.return_value = resp_500
+
+        client = KalshiClient()
+        result = client._api_call("/events")
+
+        assert result["status"] == "error"
+        assert result["code"] is None
+        assert "Max retries" in result["message"]
+
+    @patch("src.api.kalshi.time.sleep")
+    @patch("src.api.kalshi.requests.get")
+    def test_network_timeout(self, mock_get, mock_sleep):
+        mock_get.side_effect = requests.exceptions.Timeout("timeout")
+
+        client = KalshiClient()
+        result = client._api_call("/events")
+
+        assert result["status"] == "error"
+
+    @patch("src.api.kalshi.time.sleep")
+    @patch("src.api.kalshi.requests.get")
+    def test_rate_limit_delay(self, mock_get, mock_sleep):
+        mock_resp = MagicMock()
+        mock_resp.status_code = 200
+        mock_resp.json.return_value = {}
+        mock_get.return_value = mock_resp
+
+        client = KalshiClient()
+        client._api_call("/events")
+
+        # Rate limit sleep of 0.1 should have been called
+        mock_sleep.assert_called_with(0.1)
+
+
+class TestKalshiPagination:
+    @patch("src.api.kalshi.time.sleep")
+    @patch("src.api.kalshi.requests.get")
+    def test_single_page(self, mock_get, mock_sleep):
+        mock_resp = MagicMock()
+        mock_resp.status_code = 200
+        mock_resp.json.return_value = {
+            "events": [{"ticker": "A"}, {"ticker": "B"}],
+            "cursor": "",
+        }
+        mock_get.return_value = mock_resp
+
+        client = KalshiClient()
+        results = client._paginated_call("/events", collection_key="events")
+
+        assert len(results) == 2
+        assert mock_get.call_count == 1
+
+    @patch("src.api.kalshi.time.sleep")
+    @patch("src.api.kalshi.requests.get")
+    def test_multi_page(self, mock_get, mock_sleep):
+        resp1 = MagicMock()
+        resp1.status_code = 200
+        resp1.json.return_value = {
+            "events": [{"ticker": "A"}, {"ticker": "B"}, {"ticker": "C"}],
+            "cursor": "abc123",
+        }
+
+        resp2 = MagicMock()
+        resp2.status_code = 200
+        resp2.json.return_value = {
+            "events": [{"ticker": "D"}, {"ticker": "E"}],
+            "cursor": "",
+        }
+
+        mock_get.side_effect = [resp1, resp2]
+
+        client = KalshiClient()
+        results = client._paginated_call("/events", collection_key="events")
+
+        assert len(results) == 5
+        assert mock_get.call_count == 2
+        # Second call should include cursor param
+        second_call_params = mock_get.call_args_list[1][1].get("params", {})
+        assert second_call_params.get("cursor") == "abc123"
+
+    @patch("src.api.kalshi.time.sleep")
+    @patch("src.api.kalshi.requests.get")
+    def test_empty_cursor_stops(self, mock_get, mock_sleep):
+        mock_resp = MagicMock()
+        mock_resp.status_code = 200
+        mock_resp.json.return_value = {
+            "events": [{"ticker": "A"}],
+            "cursor": "",
+        }
+        mock_get.return_value = mock_resp
+
+        client = KalshiClient()
+        results = client._paginated_call("/events", collection_key="events")
+
+        assert len(results) == 1
+        assert mock_get.call_count == 1
+
+
+class TestGetGolfEvents:
+    @patch.object(KalshiClient, "_paginated_call")
+    def test_returns_open_events(self, mock_paginated):
+        mock_paginated.return_value = [{"ticker": "EVT-1"}]
+
+        client = KalshiClient()
+        result = client.get_golf_events("KXPGATOUR")
+
+        assert len(result) == 1
+        call_args = mock_paginated.call_args
+        assert call_args[0][0] == "/events"
+        assert call_args[0][1]["series_ticker"] == "KXPGATOUR"
+        assert call_args[0][1]["status"] == "open"
+
+    @patch.object(KalshiClient, "_paginated_call")
+    def test_filters_open_only(self, mock_paginated):
+        mock_paginated.return_value = []
+
+        client = KalshiClient()
+        client.get_golf_events("KXPGATOUR")
+
+        call_params = mock_paginated.call_args[0][1]
+        assert call_params["status"] == "open"
+
+    @patch.object(KalshiClient, "_paginated_call")
+    def test_empty_result(self, mock_paginated):
+        mock_paginated.return_value = []
+
+        client = KalshiClient()
+        result = client.get_golf_events("KXPGATOUR")
+
+        assert result == []
+
+
+class TestGetEventMarkets:
+    @patch.object(KalshiClient, "_paginated_call")
+    def test_returns_markets(self, mock_paginated):
+        mock_paginated.return_value = [{"ticker": "MKT-1"}, {"ticker": "MKT-2"}]
+
+        client = KalshiClient()
+        result = client.get_event_markets("EVENT-123")
+
+        assert len(result) == 2
+        call_args = mock_paginated.call_args
+        assert call_args[0][0] == "/markets"
+        assert call_args[0][1]["event_ticker"] == "EVENT-123"
+
+    @patch.object(KalshiClient, "_paginated_call")
+    def test_paginated_markets(self, mock_paginated):
+        mock_paginated.return_value = [{"ticker": f"MKT-{i}"} for i in range(5)]
+
+        client = KalshiClient()
+        result = client.get_event_markets("EVENT-123")
+
+        assert len(result) == 5
+
+    @patch.object(KalshiClient, "_paginated_call")
+    def test_unknown_event(self, mock_paginated):
+        mock_paginated.return_value = []
+
+        client = KalshiClient()
+        result = client.get_event_markets("NONEXISTENT")
+
+        assert result == []
+
+
+class TestCacheResponse:
+    def test_cache_path_structure(self, tmp_path):
+        client = KalshiClient(cache_dir=str(tmp_path))
+        data = {"events": [{"ticker": "A"}]}
+
+        filepath = client._cache_response(data, "kalshi_win", "masters-2026")
+
+        assert "masters-2026" in str(filepath)
+        assert filepath.name == "kalshi_win.json"
+        assert filepath.exists()
+
+    def test_tournament_slug_subdir(self, tmp_path):
+        client = KalshiClient(cache_dir=str(tmp_path))
+        data = {"events": []}
+
+        filepath = client._cache_response(data, "kalshi_events", "the-masters")
+
+        parts = filepath.relative_to(tmp_path).parts
+        assert parts[0] == "the-masters"
+
+    def test_valid_json(self, tmp_path):
+        client = KalshiClient(cache_dir=str(tmp_path))
+        data = {"events": [{"ticker": "A", "title": "Test"}]}
+
+        filepath = client._cache_response(data, "test_cache")
+
+        with open(filepath) as f:
+            loaded = json.load(f)
+        assert loaded == data
