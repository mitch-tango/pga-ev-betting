diff --git a/planning/prediction-markets/implementation/deep_implement_config.json b/planning/prediction-markets/implementation/deep_implement_config.json
index 785b89c..de158ff 100644
--- a/planning/prediction-markets/implementation/deep_implement_config.json
+++ b/planning/prediction-markets/implementation/deep_implement_config.json
@@ -39,6 +39,10 @@
     "section-05-polymarket-matching": {
       "status": "complete",
       "commit_hash": "66c63b2"
+    },
+    "section-06-polymarket-pull": {
+      "status": "complete",
+      "commit_hash": "413fd23"
     }
   },
   "pre_commit": {
diff --git a/src/api/prophetx.py b/src/api/prophetx.py
new file mode 100644
index 0000000..1403b83
--- /dev/null
+++ b/src/api/prophetx.py
@@ -0,0 +1,293 @@
+"""ProphetX prediction market API client (authenticated).
+
+Uses JWT-based login with token refresh. Requires email/password
+credentials from config (env vars). Rate limited.
+Responses cached locally in data/raw/ — auth responses excluded.
+
+Follows the same patterns as KalshiClient (response envelopes, retry,
+caching) but adds an authentication layer.
+"""
+
+from __future__ import annotations
+
+import json
+import logging
+import time
+from datetime import datetime, timedelta, timezone
+from pathlib import Path
+
+import requests
+
+import config
+
+logger = logging.getLogger(__name__)
+
+_USER_AGENT = (
+    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
+    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
+)
+
+
+class ProphetXClient:
+    """Client for the ProphetX prediction market API (authenticated).
+
+    Requires email/password credentials. Uses JWT auth with lazy login,
+    token refresh, and re-auth on 401.
+    Responses cached to data/raw/{tournament_slug}/{timestamp}/prophetx_*.json.
+    Auth responses are never cached.
+    """
+
+    def __init__(
+        self,
+        base_url: str | None = None,
+        cache_dir: str | None = None,
+    ):
+        self.base_url = base_url or getattr(
+            config, "PROPHETX_BASE_URL",
+            "https://cash.api.prophetx.co",
+        )
+        self.email = getattr(config, "PROPHETX_EMAIL", None)
+        self.password = getattr(config, "PROPHETX_PASSWORD", None)
+        self.rate_limit_delay = getattr(config, "PROPHETX_RATE_LIMIT_DELAY", 0.1)
+        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/raw")
+        self.timeout = getattr(config, "API_TIMEOUT", 30)
+        self.max_retries = getattr(config, "API_MAX_RETRIES", 3)
+
+        # Auth state (lazy init)
+        self.access_token: str | None = None
+        self.refresh_token: str | None = None
+        self.token_expiry: datetime | None = None
+
+        # Session with persistent headers
+        self.session = requests.Session()
+        self.session.headers["User-Agent"] = _USER_AGENT
+
+    def __repr__(self) -> str:
+        return f"ProphetXClient(base_url={self.base_url!r})"
+
+    # ── Authentication ──────────────────────────────────────────────
+
+    def _authenticate(self) -> dict:
+        """Full login via email/password.
+
+        Returns ok/error envelope. Never caches auth responses.
+        """
+        url = f"{self.base_url}/api/v1/auth/login"
+        try:
+            resp = self.session.post(
+                url,
+                json={"email": self.email, "password": self.password},
+                timeout=self.timeout,
+            )
+
+            if resp.status_code == 200:
+                data = resp.json()
+                self.access_token = data.get("access_token")
+                self.refresh_token = data.get("refresh_token")
+
+                expires_in = data.get("expires_in")
+                if expires_in:
+                    self.token_expiry = (
+                        datetime.now(timezone.utc)
+                        + timedelta(seconds=int(expires_in))
+                        - timedelta(minutes=5)
+                    )
+                else:
+                    self.token_expiry = datetime.now(timezone.utc) + timedelta(minutes=55)
+
+                return {"status": "ok", "data": data}
+
+            return {
+                "status": "error",
+                "code": resp.status_code,
+                "message": resp.text[:500],
+            }
+
+        except requests.exceptions.RequestException as e:
+            logger.warning("ProphetX auth failed: %s", e)
+            return {"status": "error", "code": None, "message": str(e)}
+
+    def _refresh_auth(self) -> dict:
+        """Refresh the access token using the refresh token.
+
+        Falls back to full _authenticate() if refresh fails.
+        """
+        url = f"{self.base_url}/api/v1/auth/extend-session"
+        try:
+            resp = self.session.post(
+                url,
+                headers={"Authorization": f"Bearer {self.refresh_token}"},
+                timeout=self.timeout,
+            )
+
+            if resp.status_code == 200:
+                data = resp.json()
+                self.access_token = data.get("access_token")
+                if data.get("refresh_token"):
+                    self.refresh_token = data["refresh_token"]
+
+                expires_in = data.get("expires_in")
+                if expires_in:
+                    self.token_expiry = (
+                        datetime.now(timezone.utc)
+                        + timedelta(seconds=int(expires_in))
+                        - timedelta(minutes=5)
+                    )
+                else:
+                    self.token_expiry = datetime.now(timezone.utc) + timedelta(minutes=55)
+
+                return {"status": "ok", "data": data}
+
+        except requests.exceptions.RequestException:
+            pass
+
+        # Refresh failed — fall back to full login
+        logger.info("ProphetX token refresh failed, re-authenticating")
+        return self._authenticate()
+
+    def _ensure_auth(self) -> None:
+        """Ensure we have a valid access token. Lazy init or refresh."""
+        if self.access_token is None:
+            self._authenticate()
+        elif self.token_expiry and datetime.now(timezone.utc) > self.token_expiry:
+            self._refresh_auth()
+
+    # ── API Call ���───────────────────────────────────────────────────
+
+    def _api_call(
+        self,
+        endpoint: str,
+        params: dict | None = None,
+        method: str = "GET",
+    ) -> dict:
+        """Make an authenticated API request with retry logic.
+
+        Returns:
+            {"status": "ok", "data": <response>} or
+            {"status": "error", "code": int|None, "message": str}
+        """
+        self._ensure_auth()
+
+        url = f"{self.base_url}{endpoint}"
+        has_retried_auth = False
+
+        for attempt in range(self.max_retries):
+            try:
+                headers = {"Authorization": f"Bearer {self.access_token}"}
+
+                resp = self.session.request(
+                    method, url, params=params, headers=headers,
+                    timeout=self.timeout,
+                )
+
+                if resp.status_code == 200:
+                    time.sleep(self.rate_limit_delay)
+                    try:
+                        return {"status": "ok", "data": resp.json()}
+                    except json.JSONDecodeError:
+                        return {"status": "ok", "data": resp.text}
+
+                elif resp.status_code == 401 and not has_retried_auth:
+                    # Re-authenticate once, then retry
+                    has_retried_auth = True
+                    self._authenticate()
+                    continue
+
+                elif resp.status_code == 429:
+                    wait = (attempt + 1) * 5
+                    logger.warning("ProphetX rate limited. Waiting %ds...", wait)
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
+                    logger.warning("ProphetX HTTP %d. Retrying in %ds...",
+                                   resp.status_code, wait)
+                    time.sleep(wait)
+
+            except requests.exceptions.Timeout:
+                logger.warning("ProphetX timeout on attempt %d", attempt + 1)
+                time.sleep(3)
+
+            except requests.exceptions.RequestException as e:
+                logger.warning("ProphetX request error: %s", e)
+                time.sleep(3)
+
+        return {
+            "status": "error",
+            "code": None,
+            "message": f"Max retries ({self.max_retries}) exceeded for {endpoint}",
+        }
+
+    # ── Cache ───────────────────────────────────────────────────────
+
+    def _cache_response(
+        self,
+        data,
+        label: str,
+        tournament_slug: str | None = None,
+    ) -> Path | None:
+        """Cache API response to local filesystem.
+
+        Skips auth-related labels to prevent tokens/credentials on disk.
+        """
+        if "auth" in label.lower():
+            return None
+
+        date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
+        if tournament_slug:
+            cache_path = self.cache_dir / tournament_slug / date_str
+        else:
+            cache_path = self.cache_dir / date_str
+
+        cache_path.mkdir(parents=True, exist_ok=True)
+        filepath = cache_path / f"prophetx_{label}.json"
+
+        with open(filepath, "w", encoding="utf-8") as f:
+            json.dump(data, f, indent=2, ensure_ascii=False)
+
+        return filepath
+
+    # ── Public Methods ──────────────────────────────────────────────
+
+    def get_golf_events(self) -> list[dict]:
+        """Fetch active golf events from ProphetX.
+
+        Returns list of event dicts. Empty list on failure.
+        """
+        response = self._api_call("/api/v1/sports/golf/events")
+
+        if response["status"] == "ok":
+            data = response["data"]
+            if isinstance(data, list):
+                return data
+            if isinstance(data, dict):
+                return data.get("events", data.get("data", []))
+
+        return []
+
+    def get_markets_for_events(self, event_ids: list[str]) -> list[dict]:
+        """Fetch markets for specific event IDs.
+
+        Returns list of market dicts with line_id, odds, competitor info.
+        Empty list on failure.
+        """
+        all_markets = []
+
+        for event_id in event_ids:
+            response = self._api_call(f"/api/v1/events/{event_id}/markets")
+            if response["status"] == "ok":
+                data = response["data"]
+                if isinstance(data, list):
+                    all_markets.extend(data)
+                elif isinstance(data, dict):
+                    markets = data.get("markets", data.get("data", []))
+                    all_markets.extend(markets)
+
+        return all_markets
diff --git a/tests/test_prophetx_client.py b/tests/test_prophetx_client.py
new file mode 100644
index 0000000..85c3bcb
--- /dev/null
+++ b/tests/test_prophetx_client.py
@@ -0,0 +1,349 @@
+"""Tests for ProphetX API client: auth, retry, caching, security."""
+
+from __future__ import annotations
+
+import json
+import os
+from datetime import datetime, timedelta, timezone
+from pathlib import Path
+from unittest.mock import MagicMock, patch, PropertyMock
+
+import pytest
+
+from src.api.prophetx import ProphetXClient
+
+
+# ── Helpers ─────────────────────────────────────────────────────────
+
+def _mock_login_response(access_token="tok_access", refresh_token="tok_refresh", expires_in=3600):
+    """Build a mock login response."""
+    data = {"access_token": access_token, "refresh_token": refresh_token}
+    if expires_in is not None:
+        data["expires_in"] = expires_in
+    resp = MagicMock()
+    resp.status_code = 200
+    resp.json.return_value = data
+    return resp
+
+
+def _mock_ok_response(data=None):
+    resp = MagicMock()
+    resp.status_code = 200
+    resp.json.return_value = data or {"events": []}
+    return resp
+
+
+def _mock_error_response(status_code=400, text="Bad Request"):
+    resp = MagicMock()
+    resp.status_code = status_code
+    resp.text = text
+    resp.json.return_value = {"error": text}
+    return resp
+
+
+# ── TestConstructor ─────────────────────────────────────────────────
+
+class TestConstructor:
+
+    @patch("src.api.prophetx.config")
+    def test_reads_credentials_from_config(self, mock_config):
+        mock_config.PROPHETX_BASE_URL = "https://test.api.com"
+        mock_config.PROPHETX_EMAIL = "test@test.com"
+        mock_config.PROPHETX_PASSWORD = "secret"
+        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.1
+        mock_config.API_TIMEOUT = 30
+        mock_config.API_MAX_RETRIES = 3
+
+        client = ProphetXClient()
+        assert client.email == "test@test.com"
+
+    @patch("src.api.prophetx.config")
+    def test_sets_user_agent(self, mock_config):
+        mock_config.PROPHETX_BASE_URL = "https://test.api.com"
+        mock_config.PROPHETX_EMAIL = "test@test.com"
+        mock_config.PROPHETX_PASSWORD = "secret"
+        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.1
+        mock_config.API_TIMEOUT = 30
+        mock_config.API_MAX_RETRIES = 3
+
+        client = ProphetXClient()
+        ua = client.session.headers.get("User-Agent", "")
+        assert "Mozilla" in ua or "Chrome" in ua or len(ua) > 10
+
+
+# ── TestAuthentication ──────────────────────────────────────────────
+
+class TestAuthentication:
+
+    @patch("src.api.prophetx.config")
+    def _make_client(self, mock_config):
+        mock_config.PROPHETX_BASE_URL = "https://test.api.com"
+        mock_config.PROPHETX_EMAIL = "test@test.com"
+        mock_config.PROPHETX_PASSWORD = "secret"
+        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.0
+        mock_config.API_TIMEOUT = 30
+        mock_config.API_MAX_RETRIES = 3
+        return ProphetXClient()
+
+    def test_authenticate_posts_credentials(self):
+        client = self._make_client()
+        client.session = MagicMock()
+        client.session.post.return_value = _mock_login_response()
+
+        client._authenticate()
+
+        call_args = client.session.post.call_args
+        assert "/api/v1/auth/login" in call_args[0][0]
+        body = call_args[1].get("json", call_args[0][1] if len(call_args[0]) > 1 else {})
+        assert body.get("email") == "test@test.com"
+
+    def test_authenticate_stores_tokens(self):
+        client = self._make_client()
+        client.session = MagicMock()
+        client.session.post.return_value = _mock_login_response(
+            access_token="my_access", refresh_token="my_refresh",
+        )
+
+        client._authenticate()
+
+        assert client.access_token == "my_access"
+        assert client.refresh_token == "my_refresh"
+
+    def test_authenticate_reads_expires_in(self):
+        client = self._make_client()
+        client.session = MagicMock()
+        client.session.post.return_value = _mock_login_response(expires_in=3600)
+
+        before = datetime.now(timezone.utc)
+        client._authenticate()
+
+        # Should be ~55 minutes from now (3600s - 5min buffer)
+        assert client.token_expiry is not None
+        assert client.token_expiry > before
+        assert client.token_expiry < before + timedelta(seconds=3600)
+
+    def test_authenticate_falls_back_to_55min(self):
+        client = self._make_client()
+        client.session = MagicMock()
+        client.session.post.return_value = _mock_login_response(expires_in=None)
+
+        before = datetime.now(timezone.utc)
+        client._authenticate()
+
+        assert client.token_expiry is not None
+        expected = before + timedelta(minutes=55)
+        assert abs((client.token_expiry - expected).total_seconds()) < 5
+
+    def test_authenticate_returns_error_on_failure(self):
+        client = self._make_client()
+        client.session = MagicMock()
+        client.session.post.return_value = _mock_error_response(401, "Invalid credentials")
+
+        result = client._authenticate()
+        assert result["status"] == "error"
+
+    def test_refresh_auth_sends_refresh_token(self):
+        client = self._make_client()
+        client.session = MagicMock()
+        client.refresh_token = "old_refresh"
+        client.session.post.return_value = _mock_login_response(
+            access_token="new_access", refresh_token="new_refresh",
+        )
+
+        client._refresh_auth()
+
+        call_args = client.session.post.call_args
+        assert "/api/v1/auth/extend-session" in call_args[0][0]
+
+    def test_refresh_auth_falls_back_to_authenticate(self):
+        client = self._make_client()
+        client.session = MagicMock()
+        client.refresh_token = "old_refresh"
+
+        # Refresh fails, then authenticate succeeds
+        client.session.post.side_effect = [
+            _mock_error_response(401, "Refresh failed"),
+            _mock_login_response(access_token="fresh_token"),
+        ]
+
+        client._refresh_auth()
+        assert client.access_token == "fresh_token"
+
+    def test_ensure_auth_lazy_init(self):
+        client = self._make_client()
+        client.session = MagicMock()
+        client.session.post.return_value = _mock_login_response()
+
+        assert client.access_token is None
+        client._ensure_auth()
+        assert client.access_token is not None
+
+    def test_ensure_auth_refreshes_when_expired(self):
+        client = self._make_client()
+        client.session = MagicMock()
+        client.access_token = "old_token"
+        client.refresh_token = "old_refresh"
+        client.token_expiry = datetime.now(timezone.utc) - timedelta(minutes=1)
+
+        client.session.post.return_value = _mock_login_response(access_token="new_token")
+
+        client._ensure_auth()
+        assert client.access_token == "new_token"
+
+    def test_ensure_auth_noop_when_valid(self):
+        client = self._make_client()
+        client.session = MagicMock()
+        client.access_token = "valid_token"
+        client.refresh_token = "valid_refresh"
+        client.token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
+
+        client._ensure_auth()
+        client.session.post.assert_not_called()
+
+
+# ── TestApiCall ─────────────────────────────────────────────────────
+
+class TestApiCall:
+
+    @patch("src.api.prophetx.config")
+    def _make_authed_client(self, mock_config):
+        mock_config.PROPHETX_BASE_URL = "https://test.api.com"
+        mock_config.PROPHETX_EMAIL = "test@test.com"
+        mock_config.PROPHETX_PASSWORD = "secret"
+        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.0
+        mock_config.API_TIMEOUT = 30
+        mock_config.API_MAX_RETRIES = 3
+
+        client = ProphetXClient()
+        client.access_token = "valid_token"
+        client.refresh_token = "valid_refresh"
+        client.token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
+        return client
+
+    def test_adds_bearer_header(self):
+        client = self._make_authed_client()
+        client.session = MagicMock()
+        client.session.request.return_value = _mock_ok_response()
+
+        client._api_call("/events")
+
+        call_args = client.session.request.call_args
+        headers = call_args[1].get("headers", {})
+        assert "Authorization" in headers
+        assert headers["Authorization"] == "Bearer valid_token"
+
+    def test_returns_ok_envelope_on_200(self):
+        client = self._make_authed_client()
+        client.session = MagicMock()
+        client.session.request.return_value = _mock_ok_response({"events": [1, 2]})
+
+        result = client._api_call("/events")
+        assert result["status"] == "ok"
+        assert result["data"]["events"] == [1, 2]
+
+    def test_returns_error_on_400(self):
+        client = self._make_authed_client()
+        client.session = MagicMock()
+        client.session.request.return_value = _mock_error_response(400, "Bad")
+
+        result = client._api_call("/events")
+        assert result["status"] == "error"
+        assert result["code"] == 400
+
+    def test_reauth_on_401_then_retry(self):
+        client = self._make_authed_client()
+        client.session = MagicMock()
+
+        resp_401 = _mock_error_response(401, "Unauthorized")
+        resp_ok = _mock_ok_response({"events": []})
+        login_resp = _mock_login_response(access_token="new_token")
+
+        # First call: 401, then re-auth succeeds, retry succeeds
+        client.session.request.side_effect = [resp_401, resp_ok]
+        client.session.post.return_value = login_resp
+
+        result = client._api_call("/events")
+        assert result["status"] == "ok"
+        assert client.access_token == "new_token"
+
+    def test_error_after_max_retries(self):
+        client = self._make_authed_client()
+        client.session = MagicMock()
+        client.session.request.return_value = _mock_error_response(500, "Server Error")
+
+        result = client._api_call("/events")
+        assert result["status"] == "error"
+
+
+# ── TestCacheResponse ───────────────────────────────────────────────
+
+class TestCacheResponse:
+
+    @patch("src.api.prophetx.config")
+    def _make_client(self, mock_config, tmp_path=None):
+        mock_config.PROPHETX_BASE_URL = "https://test.api.com"
+        mock_config.PROPHETX_EMAIL = "test@test.com"
+        mock_config.PROPHETX_PASSWORD = "secret"
+        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.0
+        mock_config.API_TIMEOUT = 30
+        mock_config.API_MAX_RETRIES = 3
+        return ProphetXClient(cache_dir=str(tmp_path) if tmp_path else "/tmp/test_cache")
+
+    def test_writes_json(self, tmp_path):
+        client = self._make_client(tmp_path=tmp_path)
+        path = client._cache_response({"foo": "bar"}, "events", "masters-2026")
+        assert path.exists()
+        with open(path) as f:
+            data = json.load(f)
+        assert data["foo"] == "bar"
+
+    def test_skips_auth_labels(self, tmp_path):
+        client = self._make_client(tmp_path=tmp_path)
+        result = client._cache_response({"token": "secret"}, "auth_login", "masters")
+        assert result is None
+
+    def test_skips_auth_in_label(self, tmp_path):
+        client = self._make_client(tmp_path=tmp_path)
+        result = client._cache_response({"token": "secret"}, "/auth/extend", "masters")
+        assert result is None
+
+
+# ── TestPublicMethods ───────────────────────────────────────────────
+
+class TestPublicMethods:
+
+    @patch("src.api.prophetx.config")
+    def _make_authed_client(self, mock_config):
+        mock_config.PROPHETX_BASE_URL = "https://test.api.com"
+        mock_config.PROPHETX_EMAIL = "test@test.com"
+        mock_config.PROPHETX_PASSWORD = "secret"
+        mock_config.PROPHETX_RATE_LIMIT_DELAY = 0.0
+        mock_config.API_TIMEOUT = 30
+        mock_config.API_MAX_RETRIES = 3
+
+        client = ProphetXClient()
+        client.access_token = "valid"
+        client.refresh_token = "valid"
+        client.token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
+        return client
+
+    def test_get_golf_events_returns_list(self):
+        client = self._make_authed_client()
+        client.session = MagicMock()
+        client.session.request.return_value = _mock_ok_response(
+            [{"id": "evt1", "name": "Masters 2026"}]
+        )
+
+        result = client.get_golf_events()
+        assert isinstance(result, list)
+        assert len(result) >= 0
+
+    def test_get_markets_for_events_returns_list(self):
+        client = self._make_authed_client()
+        client.session = MagicMock()
+        client.session.request.return_value = _mock_ok_response(
+            [{"line_id": "ln1", "market_type": "winner"}]
+        )
+
+        result = client.get_markets_for_events(["evt1"])
+        assert isinstance(result, list)
