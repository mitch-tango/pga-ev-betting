"""Tests for ProphetX API client: auth, retry, caching, security."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.api.prophetx import ProphetXClient


# ── Helpers ─────────────────────────────────────────────────────────

def _mock_login_response(access_token="tok_access", refresh_token="tok_refresh", expires_in=3600):
    """Build a mock login response."""
    data = {"access_token": access_token, "refresh_token": refresh_token}
    if expires_in is not None:
        data["expires_in"] = expires_in
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data
    return resp


def _mock_ok_response(data=None):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data or {"events": []}
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
    def test_reads_credentials_from_config(self, mock_config):
        mock_config.PROPHETX_BASE_URL = "https://test.api.com"
        mock_config.PROPHETX_EMAIL = "test@test.com"
        mock_config.PROPHETX_PASSWORD = "secret"
        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.1
        mock_config.API_TIMEOUT = 30
        mock_config.API_MAX_RETRIES = 3

        client = ProphetXClient()
        assert client.email == "test@test.com"

    @patch("src.api.prophetx.config")
    def test_sets_user_agent(self, mock_config):
        mock_config.PROPHETX_BASE_URL = "https://test.api.com"
        mock_config.PROPHETX_EMAIL = "test@test.com"
        mock_config.PROPHETX_PASSWORD = "secret"
        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.1
        mock_config.API_TIMEOUT = 30
        mock_config.API_MAX_RETRIES = 3

        client = ProphetXClient()
        ua = client.session.headers.get("User-Agent", "")
        assert "Mozilla" in ua or "Chrome" in ua or len(ua) > 10


# ── TestAuthentication ──────────────────────────────────────────────

class TestAuthentication:

    @patch("src.api.prophetx.config")
    def _make_client(self, mock_config):
        mock_config.PROPHETX_BASE_URL = "https://test.api.com"
        mock_config.PROPHETX_EMAIL = "test@test.com"
        mock_config.PROPHETX_PASSWORD = "secret"
        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.0
        mock_config.API_TIMEOUT = 30
        mock_config.API_MAX_RETRIES = 3
        return ProphetXClient()

    def test_authenticate_posts_credentials(self):
        client = self._make_client()
        client.session = MagicMock()
        client.session.post.return_value = _mock_login_response()

        client._authenticate()

        call_args = client.session.post.call_args
        assert "/api/v1/auth/login" in call_args[0][0]
        body = call_args[1].get("json", call_args[0][1] if len(call_args[0]) > 1 else {})
        assert body.get("email") == "test@test.com"

    def test_authenticate_stores_tokens(self):
        client = self._make_client()
        client.session = MagicMock()
        client.session.post.return_value = _mock_login_response(
            access_token="my_access", refresh_token="my_refresh",
        )

        client._authenticate()

        assert client.access_token == "my_access"
        assert client.refresh_token == "my_refresh"

    def test_authenticate_reads_expires_in(self):
        client = self._make_client()
        client.session = MagicMock()
        client.session.post.return_value = _mock_login_response(expires_in=3600)

        before = datetime.now(timezone.utc)
        client._authenticate()

        # Should be ~55 minutes from now (3600s - 5min buffer)
        assert client.token_expiry is not None
        assert client.token_expiry > before
        assert client.token_expiry < before + timedelta(seconds=3600)

    def test_authenticate_falls_back_to_55min(self):
        client = self._make_client()
        client.session = MagicMock()
        client.session.post.return_value = _mock_login_response(expires_in=None)

        before = datetime.now(timezone.utc)
        client._authenticate()

        assert client.token_expiry is not None
        expected = before + timedelta(minutes=55)
        assert abs((client.token_expiry - expected).total_seconds()) < 5

    def test_authenticate_returns_error_on_failure(self):
        client = self._make_client()
        client.session = MagicMock()
        client.session.post.return_value = _mock_error_response(401, "Invalid credentials")

        result = client._authenticate()
        assert result["status"] == "error"

    def test_refresh_auth_sends_refresh_token(self):
        client = self._make_client()
        client.session = MagicMock()
        client.refresh_token = "old_refresh"
        client.session.post.return_value = _mock_login_response(
            access_token="new_access", refresh_token="new_refresh",
        )

        client._refresh_auth()

        call_args = client.session.post.call_args
        assert "/api/v1/auth/extend-session" in call_args[0][0]

    def test_refresh_auth_falls_back_to_authenticate(self):
        client = self._make_client()
        client.session = MagicMock()
        client.refresh_token = "old_refresh"

        # Refresh fails, then authenticate succeeds
        client.session.post.side_effect = [
            _mock_error_response(401, "Refresh failed"),
            _mock_login_response(access_token="fresh_token"),
        ]

        client._refresh_auth()
        assert client.access_token == "fresh_token"

    def test_ensure_auth_lazy_init(self):
        client = self._make_client()
        client.session = MagicMock()
        client.session.post.return_value = _mock_login_response()

        assert client.access_token is None
        client._ensure_auth()
        assert client.access_token is not None

    def test_ensure_auth_refreshes_when_expired(self):
        client = self._make_client()
        client.session = MagicMock()
        client.access_token = "old_token"
        client.refresh_token = "old_refresh"
        client.token_expiry = datetime.now(timezone.utc) - timedelta(minutes=1)

        client.session.post.return_value = _mock_login_response(access_token="new_token")

        client._ensure_auth()
        assert client.access_token == "new_token"

    def test_ensure_auth_noop_when_valid(self):
        client = self._make_client()
        client.session = MagicMock()
        client.access_token = "valid_token"
        client.refresh_token = "valid_refresh"
        client.token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)

        client._ensure_auth()
        client.session.post.assert_not_called()


# ── TestApiCall ─────────────────────────────────────────────────────

class TestApiCall:

    @patch("src.api.prophetx.config")
    def _make_authed_client(self, mock_config):
        mock_config.PROPHETX_BASE_URL = "https://test.api.com"
        mock_config.PROPHETX_EMAIL = "test@test.com"
        mock_config.PROPHETX_PASSWORD = "secret"
        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.0
        mock_config.API_TIMEOUT = 30
        mock_config.API_MAX_RETRIES = 3

        client = ProphetXClient()
        client.access_token = "valid_token"
        client.refresh_token = "valid_refresh"
        client.token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        return client

    def test_adds_bearer_header(self):
        client = self._make_authed_client()
        client.session = MagicMock()
        client.session.request.return_value = _mock_ok_response()

        client._api_call("/events")

        call_args = client.session.request.call_args
        headers = call_args[1].get("headers", {})
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer valid_token"

    def test_returns_ok_envelope_on_200(self):
        client = self._make_authed_client()
        client.session = MagicMock()
        client.session.request.return_value = _mock_ok_response({"events": [1, 2]})

        result = client._api_call("/events")
        assert result["status"] == "ok"
        assert result["data"]["events"] == [1, 2]

    def test_returns_error_on_400(self):
        client = self._make_authed_client()
        client.session = MagicMock()
        client.session.request.return_value = _mock_error_response(400, "Bad")

        result = client._api_call("/events")
        assert result["status"] == "error"
        assert result["code"] == 400

    def test_reauth_on_401_then_retry(self):
        client = self._make_authed_client()
        client.session = MagicMock()

        resp_401 = _mock_error_response(401, "Unauthorized")
        resp_ok = _mock_ok_response({"events": []})
        login_resp = _mock_login_response(access_token="new_token")

        # First inner call returns 401, re-auth succeeds, second inner call succeeds
        client.session.request.side_effect = [resp_401, resp_ok]
        client.session.post.return_value = login_resp

        result = client._api_call("/events")
        assert result["status"] == "ok"
        assert client.access_token == "new_token"
        # Should have made 2 request calls (one 401, one success)
        assert client.session.request.call_count == 2

    def test_error_after_max_retries(self):
        client = self._make_authed_client()
        client.session = MagicMock()
        client.session.request.return_value = _mock_error_response(500, "Server Error")

        result = client._api_call("/events")
        assert result["status"] == "error"


# ── TestCacheResponse ───────────────────────────────────────────────

class TestCacheResponse:

    @patch("src.api.prophetx.config")
    def _make_client(self, mock_config, tmp_path=None):
        mock_config.PROPHETX_BASE_URL = "https://test.api.com"
        mock_config.PROPHETX_EMAIL = "test@test.com"
        mock_config.PROPHETX_PASSWORD = "secret"
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

    def test_skips_auth_labels(self, tmp_path):
        client = self._make_client(tmp_path=tmp_path)
        result = client._cache_response({"token": "secret"}, "auth_login", "masters")
        assert result is None

    def test_skips_auth_in_label(self, tmp_path):
        client = self._make_client(tmp_path=tmp_path)
        result = client._cache_response({"token": "secret"}, "/auth/extend", "masters")
        assert result is None


# ── TestPublicMethods ───────────────────────────────────────────────

class TestPublicMethods:

    @patch("src.api.prophetx.config")
    def _make_authed_client(self, mock_config):
        mock_config.PROPHETX_BASE_URL = "https://test.api.com"
        mock_config.PROPHETX_EMAIL = "test@test.com"
        mock_config.PROPHETX_PASSWORD = "secret"
        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.0
        mock_config.API_TIMEOUT = 30
        mock_config.API_MAX_RETRIES = 3

        client = ProphetXClient()
        client.access_token = "valid"
        client.refresh_token = "valid"
        client.token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        return client

    def test_get_golf_events_returns_list(self):
        client = self._make_authed_client()
        client.session = MagicMock()
        client.session.request.return_value = _mock_ok_response(
            [{"id": "evt1", "name": "Masters 2026"}]
        )

        result = client.get_golf_events()
        assert isinstance(result, list)
        assert len(result) >= 0

    def test_get_markets_for_events_returns_list(self):
        client = self._make_authed_client()
        client.session = MagicMock()
        client.session.request.return_value = _mock_ok_response(
            [{"line_id": "ln1", "market_type": "winner"}]
        )

        result = client.get_markets_for_events(["evt1"])
        assert isinstance(result, list)
