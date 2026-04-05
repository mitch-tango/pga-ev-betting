"""Unit tests for src/api/polymarket.py"""

import json
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

import requests
from src.api.polymarket import PolymarketClient


class TestConstructor:
    def test_default_config(self):
        client = PolymarketClient()
        assert "gamma-api.polymarket.com" in client.gamma_url
        assert "clob.polymarket.com" in client.clob_url
        assert client.rate_limit_delay == 0.1

    def test_custom_urls(self):
        client = PolymarketClient(
            gamma_url="https://custom-gamma.com",
            clob_url="https://custom-clob.com",
        )
        assert client.gamma_url == "https://custom-gamma.com"
        assert client.clob_url == "https://custom-clob.com"

    def test_cache_dir(self, tmp_path):
        client = PolymarketClient(cache_dir=str(tmp_path))
        assert client.cache_dir == tmp_path


class TestApiCall:
    @patch("src.api.polymarket.time.sleep")
    @patch("src.api.polymarket.requests.get")
    def test_successful_get(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"id": "1"}]
        mock_get.return_value = mock_resp

        client = PolymarketClient()
        result = client._api_call(client.gamma_url, "/events")

        assert result["status"] == "ok"
        assert result["data"] == [{"id": "1"}]

    @patch("src.api.polymarket.time.sleep")
    @patch("src.api.polymarket.requests.get")
    def test_429_retry(self, mock_get, mock_sleep):
        resp_429 = MagicMock()
        resp_429.status_code = 429

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"ok": True}

        mock_get.side_effect = [resp_429, resp_200]

        client = PolymarketClient()
        result = client._api_call(client.gamma_url, "/events")

        assert result["status"] == "ok"
        assert any(call.args[0] >= 5 for call in mock_sleep.call_args_list)

    @patch("src.api.polymarket.time.sleep")
    @patch("src.api.polymarket.requests.get")
    def test_5xx_retry(self, mock_get, mock_sleep):
        resp_500 = MagicMock()
        resp_500.status_code = 500

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"ok": True}

        mock_get.side_effect = [resp_500, resp_200]

        client = PolymarketClient()
        result = client._api_call(client.gamma_url, "/events")

        assert result["status"] == "ok"

    @patch("src.api.polymarket.time.sleep")
    @patch("src.api.polymarket.requests.get")
    def test_400_no_retry(self, mock_get, mock_sleep):
        resp_400 = MagicMock()
        resp_400.status_code = 400
        resp_400.text = "Bad request"
        mock_get.return_value = resp_400

        client = PolymarketClient()
        result = client._api_call(client.gamma_url, "/events")

        assert result["status"] == "error"
        assert result["code"] == 400
        assert mock_get.call_count == 1

    @patch("src.api.polymarket.time.sleep")
    @patch("src.api.polymarket.requests.get")
    def test_max_retries_exhausted(self, mock_get, mock_sleep):
        resp_500 = MagicMock()
        resp_500.status_code = 500
        mock_get.return_value = resp_500

        client = PolymarketClient()
        result = client._api_call(client.gamma_url, "/events")

        assert result["status"] == "error"
        assert "Max retries" in result["message"]

    @patch("src.api.polymarket.time.sleep")
    @patch("src.api.polymarket.requests.get")
    def test_uses_correct_base_url(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_get.return_value = mock_resp

        client = PolymarketClient()
        client._api_call(client.clob_url, "/books")

        called_url = mock_get.call_args[0][0]
        assert called_url.startswith("https://clob.polymarket.com")

    @patch("src.api.polymarket.time.sleep")
    @patch("src.api.polymarket.requests.get")
    def test_rate_limit_delay(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_get.return_value = mock_resp

        client = PolymarketClient()
        client._api_call(client.gamma_url, "/events")

        mock_sleep.assert_called_with(0.1)


class TestPaginatedCall:
    @patch("src.api.polymarket.time.sleep")
    @patch("src.api.polymarket.requests.get")
    def test_accumulates_pages(self, mock_get, mock_sleep):
        # Page 1: 100 items (full page -> fetch next)
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.json.return_value = [{"id": str(i)} for i in range(100)]

        # Page 2: 50 items (less than limit -> stop)
        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = [{"id": str(i)} for i in range(100, 150)]

        mock_get.side_effect = [resp1, resp2]

        client = PolymarketClient()
        results = client._paginated_call(client.gamma_url, "/events")

        assert len(results) == 150
        assert mock_get.call_count == 2

    @patch("src.api.polymarket.time.sleep")
    @patch("src.api.polymarket.requests.get")
    def test_stops_on_short_page(self, mock_get, mock_sleep):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = [{"id": "1"}, {"id": "2"}]
        mock_get.return_value = resp

        client = PolymarketClient()
        results = client._paginated_call(client.gamma_url, "/events")

        assert len(results) == 2
        assert mock_get.call_count == 1

    @patch("src.api.polymarket.time.sleep")
    @patch("src.api.polymarket.requests.get")
    def test_collection_key(self, mock_get, mock_sleep):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": [{"id": "1"}]}
        mock_get.return_value = resp

        client = PolymarketClient()
        results = client._paginated_call(
            client.gamma_url, "/events", collection_key="data")

        assert len(results) == 1

    @patch("src.api.polymarket.time.sleep")
    @patch("src.api.polymarket.requests.get")
    def test_partial_results_on_error(self, mock_get, mock_sleep):
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.json.return_value = [{"id": str(i)} for i in range(100)]

        resp2 = MagicMock()
        resp2.status_code = 500
        mock_get.side_effect = [resp1] + [resp2] * 3  # retries exhaust

        client = PolymarketClient()
        results = client._paginated_call(client.gamma_url, "/events")

        assert len(results) == 100


    @patch("src.api.polymarket.time.sleep")
    @patch("src.api.polymarket.requests.get")
    def test_safety_limit_logs_warning(self, mock_get, mock_sleep, caplog):
        """Stops at 50-page safety limit and logs warning."""
        full_page = MagicMock()
        full_page.status_code = 200
        full_page.json.return_value = [{"id": str(i)} for i in range(100)]
        mock_get.return_value = full_page

        client = PolymarketClient()
        with caplog.at_level(logging.WARNING):
            results = client._paginated_call(client.gamma_url, "/events")

        assert mock_get.call_count == 50
        assert any("safety limit" in r.message for r in caplog.records)


class TestCacheResponse:
    def test_cache_path_structure(self, tmp_path):
        client = PolymarketClient(cache_dir=str(tmp_path))
        data = [{"id": "1"}]

        filepath = client._cache_response(data, "polymarket_events", "masters-2026")

        assert "masters-2026" in str(filepath)
        assert filepath.name == "polymarket_events.json"
        assert filepath.exists()

    def test_valid_json(self, tmp_path):
        client = PolymarketClient(cache_dir=str(tmp_path))
        data = [{"id": "1", "title": "Test"}]

        filepath = client._cache_response(data, "test_cache")

        with open(filepath) as f:
            loaded = json.load(f)
        assert loaded == data


class TestGetGolfTagId:
    @patch.object(PolymarketClient, "_api_call")
    def test_returns_tag_id(self, mock_api):
        mock_api.return_value = {
            "status": "ok",
            "data": [
                {"label": "Basketball", "tag_id": "111"},
                {"label": "Golf", "tag_id": "222"},
            ],
        }

        client = PolymarketClient()
        tag_id = client.get_golf_tag_id()

        assert tag_id == "222"

    @patch.object(PolymarketClient, "_api_call")
    def test_caches_on_instance(self, mock_api):
        mock_api.return_value = {
            "status": "ok",
            "data": [{"label": "Golf", "tag_id": "222"}],
        }

        client = PolymarketClient()
        client.get_golf_tag_id()
        client.get_golf_tag_id()

        assert mock_api.call_count == 1

    @patch.object(PolymarketClient, "_api_call")
    def test_fallback_to_env_var(self, mock_api):
        mock_api.return_value = {"status": "error", "code": 500, "message": "fail"}

        client = PolymarketClient()
        with patch("src.api.polymarket.config.POLYMARKET_GOLF_TAG_ID", "env-tag-123"):
            tag_id = client.get_golf_tag_id()

        assert tag_id == "env-tag-123"


class TestGetGolfEvents:
    @patch.object(PolymarketClient, "get_golf_tag_id", return_value="222")
    @patch.object(PolymarketClient, "_paginated_call")
    def test_passes_tag_and_filters(self, mock_paginated, mock_tag):
        mock_paginated.return_value = [{"id": "ev1"}]

        client = PolymarketClient()
        result = client.get_golf_events()

        assert len(result) == 1
        call_args = mock_paginated.call_args
        params = call_args[1].get("params") or call_args[0][2]
        assert params.get("tag_id") == "222"
        assert params.get("active") == "true"
        assert params.get("closed") == "false"

    @patch.object(PolymarketClient, "get_golf_tag_id", return_value="222")
    @patch.object(PolymarketClient, "_paginated_call")
    def test_passes_market_type_filter(self, mock_paginated, mock_tag):
        mock_paginated.return_value = []

        client = PolymarketClient()
        client.get_golf_events(market_type_filter="winner")

        call_args = mock_paginated.call_args
        params = call_args[1].get("params") or call_args[0][2]
        assert params.get("sports_market_types") == "winner"

    @patch.object(PolymarketClient, "get_golf_tag_id", return_value=None)
    def test_returns_empty_when_no_tag(self, mock_tag):
        client = PolymarketClient()
        result = client.get_golf_events()

        assert result == []


class TestGetBooks:
    @patch.object(PolymarketClient, "_api_call")
    def test_single_token(self, mock_api):
        mock_api.return_value = {
            "status": "ok",
            "data": [{"asset_id": "tok1", "bids": [{"price": "0.50"}], "asks": [{"price": "0.55"}]}],
        }

        client = PolymarketClient()
        result = client.get_books(["tok1"])

        assert "tok1" in result
        assert result["tok1"]["asks"][0]["price"] == "0.55"

    @patch.object(PolymarketClient, "_api_call")
    def test_chunks_into_batches_of_50(self, mock_api):
        # 75 tokens -> 2 calls (50 + 25)
        tokens = [f"tok{i}" for i in range(75)]

        def side_effect(base_url, endpoint, params=None):
            csv = params.get("token_ids", "") if params else ""
            token_ids = csv.split(",") if csv else []
            return {
                "status": "ok",
                "data": [{"asset_id": tid, "bids": [], "asks": []} for tid in token_ids],
            }

        mock_api.side_effect = side_effect

        client = PolymarketClient()
        result = client.get_books(tokens)

        assert mock_api.call_count == 2
        assert len(result) == 75

    @patch.object(PolymarketClient, "_api_call")
    def test_empty_token_list(self, mock_api):
        client = PolymarketClient()
        result = client.get_books([])

        assert result == {}
        assert mock_api.call_count == 0
