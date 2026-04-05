"""ProphetX prediction market API client (authenticated).

Uses JWT-based login with token refresh. Requires email/password
credentials from config (env vars). Rate limited.
Responses cached locally in data/raw/ — auth responses excluded.

Follows the same patterns as KalshiClient (response envelopes, retry,
caching) but adds an authentication layer.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class ProphetXClient:
    """Client for the ProphetX prediction market API (authenticated).

    Requires email/password credentials. Uses JWT auth with lazy login,
    token refresh, and re-auth on 401.
    Responses cached to data/raw/{tournament_slug}/{timestamp}/prophetx_*.json.
    Auth responses are never cached.
    """

    def __init__(
        self,
        base_url: str | None = None,
        cache_dir: str | None = None,
    ):
        self.base_url = base_url or getattr(
            config, "PROPHETX_BASE_URL",
            "https://cash.api.prophetx.co",
        )
        self.email = getattr(config, "PROPHETX_EMAIL", None)
        self.password = getattr(config, "PROPHETX_PASSWORD", None)
        self.rate_limit_delay = getattr(config, "PROPHETX_RATE_LIMIT_DELAY", 0.1)
        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/raw")
        self.timeout = getattr(config, "API_TIMEOUT", 30)
        self.max_retries = getattr(config, "API_MAX_RETRIES", 3)

        # Auth state (lazy init)
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.token_expiry: datetime | None = None

        # Session with persistent headers
        self.session = requests.Session()
        self.session.headers["User-Agent"] = _USER_AGENT

    def __repr__(self) -> str:
        return f"ProphetXClient(base_url={self.base_url!r})"

    # ── Authentication ──────────────────────────────────────────────

    def _authenticate(self) -> dict:
        """Full login via email/password.

        Returns ok/error envelope. Never caches auth responses.
        """
        url = f"{self.base_url}/api/v1/auth/login"
        try:
            resp = self.session.post(
                url,
                json={"email": self.email, "password": self.password},
                timeout=self.timeout,
            )

            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")

                expires_in = data.get("expires_in")
                if expires_in:
                    self.token_expiry = (
                        datetime.now(timezone.utc)
                        + timedelta(seconds=int(expires_in))
                        - timedelta(minutes=5)
                    )
                else:
                    self.token_expiry = datetime.now(timezone.utc) + timedelta(minutes=55)

                return {"status": "ok", "data": data}

            return {
                "status": "error",
                "code": resp.status_code,
                "message": resp.text[:500],
            }

        except requests.exceptions.RequestException as e:
            # Redact any credentials that may appear in the exception
            err_msg = str(e)
            if self.password:
                err_msg = err_msg.replace(self.password, "[REDACTED]")
            logger.warning("ProphetX auth failed: %s", err_msg)
            return {"status": "error", "code": None, "message": err_msg}

    def _refresh_auth(self) -> dict:
        """Refresh the access token using the refresh token.

        Falls back to full _authenticate() if refresh fails.
        """
        url = f"{self.base_url}/api/v1/auth/extend-session"
        try:
            resp = self.session.post(
                url,
                headers={"Authorization": f"Bearer {self.refresh_token}"},
                timeout=self.timeout,
            )

            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data.get("access_token")
                if data.get("refresh_token"):
                    self.refresh_token = data["refresh_token"]

                expires_in = data.get("expires_in")
                if expires_in:
                    self.token_expiry = (
                        datetime.now(timezone.utc)
                        + timedelta(seconds=int(expires_in))
                        - timedelta(minutes=5)
                    )
                else:
                    self.token_expiry = datetime.now(timezone.utc) + timedelta(minutes=55)

                return {"status": "ok", "data": data}

        except requests.exceptions.RequestException as e:
            logger.info("ProphetX refresh request error: %s", type(e).__name__)

        # Refresh failed — fall back to full login
        logger.info("ProphetX token refresh failed, re-authenticating")
        return self._authenticate()

    def _ensure_auth(self) -> None:
        """Ensure we have a valid access token. Lazy init or refresh."""
        if self.access_token is None:
            self._authenticate()
        elif self.token_expiry and datetime.now(timezone.utc) > self.token_expiry:
            self._refresh_auth()

    # ── API Call ���───────────────────────────────────────────────────

    def _api_call(
        self,
        endpoint: str,
        params: dict | None = None,
        method: str = "GET",
    ) -> dict:
        """Make an authenticated API request with retry logic.

        Returns:
            {"status": "ok", "data": <response>} or
            {"status": "error", "code": int|None, "message": str}
        """
        self._ensure_auth()

        url = f"{self.base_url}{endpoint}"

        result = self._api_call_inner(url, params, method)

        # On 401, re-authenticate once and retry the full call
        if result.get("code") == 401:
            logger.info("ProphetX 401 — re-authenticating")
            self._authenticate()
            result = self._api_call_inner(url, params, method)

        return result

    def _api_call_inner(
        self,
        url: str,
        params: dict | None,
        method: str,
    ) -> dict:
        """Inner retry loop for API calls."""
        for attempt in range(self.max_retries):
            try:
                headers = {"Authorization": f"Bearer {self.access_token}"}

                resp = self.session.request(
                    method, url, params=params, headers=headers,
                    timeout=self.timeout,
                )

                if resp.status_code == 200:
                    time.sleep(self.rate_limit_delay)
                    try:
                        return {"status": "ok", "data": resp.json()}
                    except json.JSONDecodeError:
                        return {"status": "ok", "data": resp.text}

                elif resp.status_code == 401:
                    return {"status": "error", "code": 401, "message": "Unauthorized"}

                elif resp.status_code == 429:
                    wait = (attempt + 1) * 5
                    logger.warning("ProphetX rate limited. Waiting %ds...", wait)
                    time.sleep(wait)

                elif resp.status_code == 400:
                    return {
                        "status": "error",
                        "code": 400,
                        "message": resp.text[:500],
                    }

                else:
                    wait = (attempt + 1) * 3
                    logger.warning("ProphetX HTTP %d. Retrying in %ds...",
                                   resp.status_code, wait)
                    time.sleep(wait)

            except requests.exceptions.Timeout:
                logger.warning("ProphetX timeout on attempt %d", attempt + 1)
                time.sleep(3)

            except requests.exceptions.RequestException as e:
                logger.warning("ProphetX request error: %s", e)
                time.sleep(3)

        return {
            "status": "error",
            "code": None,
            "message": f"Max retries ({self.max_retries}) exceeded for {url}",
        }

    # ── Cache ───────────────────────────────────────────────────────

    def _cache_response(
        self,
        data,
        label: str,
        tournament_slug: str | None = None,
    ) -> Path | None:
        """Cache API response to local filesystem.

        Skips auth-related labels to prevent tokens/credentials on disk.
        """
        if "auth" in label.lower():
            return None

        date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
        if tournament_slug:
            cache_path = self.cache_dir / tournament_slug / date_str
        else:
            cache_path = self.cache_dir / date_str

        cache_path.mkdir(parents=True, exist_ok=True)
        filepath = cache_path / f"prophetx_{label}.json"

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return filepath

    # ── Public Methods ──────────────────────────────────────────────

    def get_golf_events(self) -> list[dict]:
        """Fetch active golf events from ProphetX.

        Returns list of event dicts. Empty list on failure.
        """
        response = self._api_call("/api/v1/sports/golf/events")

        if response["status"] == "ok":
            data = response["data"]
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("events", data.get("data", []))
            logger.warning("ProphetX: unexpected golf events response shape: %s", type(data).__name__)

        else:
            logger.warning("ProphetX: golf events request failed: %s", response.get("message", ""))

        return []

    def get_markets_for_events(self, event_ids: list[str]) -> list[dict]:
        """Fetch markets for specific event IDs.

        Returns list of market dicts with line_id, odds, competitor info.
        Empty list on failure.
        """
        all_markets = []

        for event_id in event_ids:
            response = self._api_call(f"/api/v1/events/{event_id}/markets")
            if response["status"] == "ok":
                data = response["data"]
                if isinstance(data, list):
                    all_markets.extend(data)
                elif isinstance(data, dict):
                    markets = data.get("markets", data.get("data", []))
                    all_markets.extend(markets)

        return all_markets
