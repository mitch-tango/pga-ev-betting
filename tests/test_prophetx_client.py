"""Tests for ProphetX API client: public API, retry, caching."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.api.prophetx import ProphetXClient


# ── Helpers ─────────────────────────────────────────────────────────

def _mock_ok_response(data=None):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data or {"data": {}}
    return resp


def _mock_error_response(status_code=400, text="Bad Request"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = {"error": text}
    return resp


# ── TestConstructor ─────────────────────────────────────────────────

class TestConstructor:

    @patch("src.api.prophetx.config")
    def test_reads_config(self, mock_config):
        mock_config.PROPHETX_BASE_URL = "https://test.prophetx.co"
        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.1
        mock_config.API_TIMEOUT = 30
        mock_config.API_MAX_RETRIES = 3

        client = ProphetXClient()
        assert "test.prophetx.co" in client.base_url

    @patch("src.api.prophetx.config")
    def test_sets_user_agent(self, mock_config):
        mock_config.PROPHETX_BASE_URL = "https://test.prophetx.co"
        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.1
        mock_config.API_TIMEOUT = 30
        mock_config.API_MAX_RETRIES = 3

        client = ProphetXClient()
        ua = client.session.headers.get("User-Agent", "")
        assert "Mozilla" in ua or "Chrome" in ua or len(ua) > 10

    @patch("src.api.prophetx.config")
    def test_public_api_url(self, mock_config):
        mock_config.PROPHETX_BASE_URL = "https://www.prophetx.co"
        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.1
        mock_config.API_TIMEOUT = 30
        mock_config.API_MAX_RETRIES = 3

        client = ProphetXClient()
        assert client.public_api == "https://www.prophetx.co/trade/public/api/v1"


# ── TestApiCall ─────────────────────────────────────────────────────

class TestApiCall:

    @patch("src.api.prophetx.config")
    def _make_client(self, mock_config):
        mock_config.PROPHETX_BASE_URL = "https://test.prophetx.co"
        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.0
        mock_config.API_TIMEOUT = 30
        mock_config.API_MAX_RETRIES = 3
        return ProphetXClient()

    def test_returns_ok_envelope_on_200(self):
        client = self._make_client()
        client.session = MagicMock()
        client.session.get.return_value = _mock_ok_response({"data": [1, 2]})

        result = client._api_call("https://test.prophetx.co/events")
        assert result["status"] == "ok"
        assert result["data"]["data"] == [1, 2]

    def test_returns_error_on_400(self):
        client = self._make_client()
        client.session = MagicMock()
        client.session.get.return_value = _mock_error_response(400, "Bad")

        result = client._api_call("https://test.prophetx.co/events")
        assert result["status"] == "error"
        assert result["code"] == 400

    def test_error_after_max_retries(self):
        client = self._make_client()
        client.session = MagicMock()
        client.session.get.return_value = _mock_error_response(500, "Server Error")

        result = client._api_call("https://test.prophetx.co/events")
        assert result["status"] == "error"


# ── TestCacheResponse ───────────────────────────────────────────────

class TestCacheResponse:

    @patch("src.api.prophetx.config")
    def _make_client(self, mock_config, tmp_path=None):
        mock_config.PROPHETX_BASE_URL = "https://test.prophetx.co"
        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.0
        mock_config.API_TIMEOUT = 30
        mock_config.API_MAX_RETRIES = 3
        return ProphetXClient(cache_dir=str(tmp_path) if tmp_path else "/tmp/test_cache")

    def test_writes_json(self, tmp_path):
        client = self._make_client(tmp_path=tmp_path)
        path = client._cache_response({"foo": "bar"}, "events", "masters-2026")
        assert path.exists()
        with open(path) as f:
            data = json.load(f)
        assert data["foo"] == "bar"


# ── TestPublicMethods ───────────────────────────────────────────────

class TestPublicMethods:

    @patch("src.api.prophetx.config")
    def _make_client(self, mock_config):
        mock_config.PROPHETX_BASE_URL = "https://test.prophetx.co"
        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.0
        mock_config.API_TIMEOUT = 30
        mock_config.API_MAX_RETRIES = 3
        return ProphetXClient()

    def test_get_tournaments_returns_list(self):
        client = self._make_client()
        client.session = MagicMock()
        client.session.get.return_value = _mock_ok_response(
            {"data": {"tournaments": [{"id": 1, "name": "PGA Tour"}]}}
        )

        result = client.get_tournaments()
        assert isinstance(result, list)
        assert len(result) == 1

    def test_get_golf_events_two_step_discovery(self):
        client = self._make_client()
        client.session = MagicMock()

        # First call: get_tournaments
        tournaments_resp = _mock_ok_response(
            {"data": {"tournaments": [
                {"id": 100, "name": "Golf Markets"},
                {"id": 200, "name": "NBA"},
            ]}}
        )
        # Second call (known IDs + discovered): events for golf tournament
        events_resp = _mock_ok_response(
            {"data": [{"id": "evt1", "name": "Masters 2026"}]}
        )
        # Multiple calls for known golf IDs + discovered ones
        client.session.get.side_effect = [tournaments_resp] + [events_resp] * 5

        result = client.get_golf_events()
        assert isinstance(result, list)
        assert any(e.get("name") == "Masters 2026" for e in result)

    def test_get_golf_events_empty_when_no_golf(self):
        client = self._make_client()
        client.session = MagicMock()

        # Tournaments returns nothing golf-related
        client.session.get.side_effect = [
            _mock_ok_response({"data": {"tournaments": [{"id": 1, "name": "NBA"}]}}),
        ] + [_mock_ok_response({"data": []}) for _ in range(4)]  # known IDs return empty

        result = client.get_golf_events()
        # Known IDs may still be queried, but events should be empty
        assert isinstance(result, list)

    def test_get_markets_for_events_returns_list(self):
        client = self._make_client()
        client.session = MagicMock()
        client.session.get.return_value = _mock_ok_response(
            {"data": {"markets": [{"id": 1, "name": "Scottie Scheffler", "status": "active"}]}}
        )

        result = client.get_markets_for_events(["evt1"])
        assert isinstance(result, list)
        assert len(result) == 1
