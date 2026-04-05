"""Unit tests for src/api/kalshi.py"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from src.api.kalshi import KalshiClient


class TestKalshiClientInit:
    def test_default_config(self):
        client = KalshiClient()
        assert "kalshi.com" in client.base_url
        assert client.rate_limit_delay == 0.1

    def test_custom_base_url(self):
        client = KalshiClient(base_url="https://custom.api.com/v2")
        assert client.base_url == "https://custom.api.com/v2"

    def test_cache_dir_creation(self, tmp_path):
        cache_dir = tmp_path / "kalshi_cache"
        client = KalshiClient(cache_dir=str(cache_dir))
        assert client.cache_dir == cache_dir


class TestKalshiApiCall:
    @patch("src.api.kalshi.time.sleep")
    @patch("src.api.kalshi.requests.get")
    def test_successful_get(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"events": [{"ticker": "EVT-1"}]}
        mock_get.return_value = mock_resp

        client = KalshiClient()
        result = client._api_call("/events")

        assert result["status"] == "ok"
        assert result["data"]["events"][0]["ticker"] == "EVT-1"

    @patch("src.api.kalshi.time.sleep")
    @patch("src.api.kalshi.requests.get")
    def test_429_triggers_retry(self, mock_get, mock_sleep):
        resp_429 = MagicMock()
        resp_429.status_code = 429

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"ok": True}

        mock_get.side_effect = [resp_429, resp_200]

        client = KalshiClient()
        result = client._api_call("/events")

        assert result["status"] == "ok"
        # Should have slept for backoff on 429
        assert any(call.args[0] >= 5 for call in mock_sleep.call_args_list)

    @patch("src.api.kalshi.time.sleep")
    @patch("src.api.kalshi.requests.get")
    def test_5xx_triggers_retry(self, mock_get, mock_sleep):
        resp_500 = MagicMock()
        resp_500.status_code = 500

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"ok": True}

        mock_get.side_effect = [resp_500, resp_200]

        client = KalshiClient()
        result = client._api_call("/events")

        assert result["status"] == "ok"

    @patch("src.api.kalshi.time.sleep")
    @patch("src.api.kalshi.requests.get")
    def test_persistent_failure(self, mock_get, mock_sleep):
        resp_500 = MagicMock()
        resp_500.status_code = 500
        mock_get.return_value = resp_500

        client = KalshiClient()
        result = client._api_call("/events")

        assert result["status"] == "error"
        assert result["code"] is None
        assert "Max retries" in result["message"]

    @patch("src.api.kalshi.time.sleep")
    @patch("src.api.kalshi.requests.get")
    def test_network_timeout(self, mock_get, mock_sleep):
        mock_get.side_effect = requests.exceptions.Timeout("timeout")

        client = KalshiClient()
        result = client._api_call("/events")

        assert result["status"] == "error"

    @patch("src.api.kalshi.time.sleep")
    @patch("src.api.kalshi.requests.get")
    def test_rate_limit_delay(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_get.return_value = mock_resp

        client = KalshiClient()
        client._api_call("/events")

        # Rate limit sleep of 0.1 should have been called
        mock_sleep.assert_called_with(0.1)


class TestKalshiPagination:
    @patch("src.api.kalshi.time.sleep")
    @patch("src.api.kalshi.requests.get")
    def test_single_page(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "events": [{"ticker": "A"}, {"ticker": "B"}],
            "cursor": "",
        }
        mock_get.return_value = mock_resp

        client = KalshiClient()
        results = client._paginated_call("/events", collection_key="events")

        assert len(results) == 2
        assert mock_get.call_count == 1

    @patch("src.api.kalshi.time.sleep")
    @patch("src.api.kalshi.requests.get")
    def test_multi_page(self, mock_get, mock_sleep):
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.json.return_value = {
            "events": [{"ticker": "A"}, {"ticker": "B"}, {"ticker": "C"}],
            "cursor": "abc123",
        }

        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = {
            "events": [{"ticker": "D"}, {"ticker": "E"}],
            "cursor": "",
        }

        mock_get.side_effect = [resp1, resp2]

        client = KalshiClient()
        results = client._paginated_call("/events", collection_key="events")

        assert len(results) == 5
        assert mock_get.call_count == 2
        # Second call should include cursor param
        second_call_params = mock_get.call_args_list[1][1].get("params", {})
        assert second_call_params.get("cursor") == "abc123"

    @patch("src.api.kalshi.time.sleep")
    @patch("src.api.kalshi.requests.get")
    def test_empty_cursor_stops(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "events": [{"ticker": "A"}],
            "cursor": "",
        }
        mock_get.return_value = mock_resp

        client = KalshiClient()
        results = client._paginated_call("/events", collection_key="events")

        assert len(results) == 1
        assert mock_get.call_count == 1


class TestGetGolfEvents:
    @patch.object(KalshiClient, "_paginated_call")
    def test_returns_open_events(self, mock_paginated):
        mock_paginated.return_value = [{"ticker": "EVT-1"}]

        client = KalshiClient()
        result = client.get_golf_events("KXPGATOUR")

        assert len(result) == 1
        call_args = mock_paginated.call_args
        assert call_args[0][0] == "/events"
        assert call_args[0][1]["series_ticker"] == "KXPGATOUR"
        assert call_args[0][1]["status"] == "open"

    @patch.object(KalshiClient, "_paginated_call")
    def test_filters_open_only(self, mock_paginated):
        mock_paginated.return_value = []

        client = KalshiClient()
        client.get_golf_events("KXPGATOUR")

        call_params = mock_paginated.call_args[0][1]
        assert call_params["status"] == "open"

    @patch.object(KalshiClient, "_paginated_call")
    def test_empty_result(self, mock_paginated):
        mock_paginated.return_value = []

        client = KalshiClient()
        result = client.get_golf_events("KXPGATOUR")

        assert result == []


class TestGetEventMarkets:
    @patch.object(KalshiClient, "_paginated_call")
    def test_returns_markets(self, mock_paginated):
        mock_paginated.return_value = [{"ticker": "MKT-1"}, {"ticker": "MKT-2"}]

        client = KalshiClient()
        result = client.get_event_markets("EVENT-123")

        assert len(result) == 2
        call_args = mock_paginated.call_args
        assert call_args[0][0] == "/markets"
        assert call_args[0][1]["event_ticker"] == "EVENT-123"

    @patch.object(KalshiClient, "_paginated_call")
    def test_paginated_markets(self, mock_paginated):
        mock_paginated.return_value = [{"ticker": f"MKT-{i}"} for i in range(5)]

        client = KalshiClient()
        result = client.get_event_markets("EVENT-123")

        assert len(result) == 5

    @patch.object(KalshiClient, "_paginated_call")
    def test_unknown_event(self, mock_paginated):
        mock_paginated.return_value = []

        client = KalshiClient()
        result = client.get_event_markets("NONEXISTENT")

        assert result == []


class TestCacheResponse:
    def test_cache_path_structure(self, tmp_path):
        client = KalshiClient(cache_dir=str(tmp_path))
        data = {"events": [{"ticker": "A"}]}

        filepath = client._cache_response(data, "kalshi_win", "masters-2026")

        assert "masters-2026" in str(filepath)
        assert filepath.name == "kalshi_win.json"
        assert filepath.exists()

    def test_tournament_slug_subdir(self, tmp_path):
        client = KalshiClient(cache_dir=str(tmp_path))
        data = {"events": []}

        filepath = client._cache_response(data, "kalshi_events", "the-masters")

        parts = filepath.relative_to(tmp_path).parts
        assert parts[0] == "the-masters"

    def test_valid_json(self, tmp_path):
        client = KalshiClient(cache_dir=str(tmp_path))
        data = {"events": [{"ticker": "A", "title": "Test"}]}

        filepath = client._cache_response(data, "test_cache")

        with open(filepath) as f:
            loaded = json.load(f)
        assert loaded == data
