"""ProphetX prediction market API client (public endpoints).

Uses ProphetX's public trade API — no authentication required.
Rate limited. Responses cached locally in data/raw/.

Endpoints:
  GET /trade/public/api/v1/tournaments — list all tournaments
  GET /trade/public/api/v1/tournaments/{id}/events — events for a tournament
  GET /trade/public/api/v1/events/{id}/markets — markets/odds for an event
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Known golf tournament IDs on ProphetX (speeds up discovery)
_GOLF_TOURNAMENT_IDS = {
    1600000234: "Golf Markets",
    1600000195: "Golf Matchups",
    1600000321: "Golf Props",
    1600000306: "Golf Round Matchups",
}


class ProphetXClient:
    """Client for the ProphetX public trade API.

    No authentication required. Uses public endpoints for tournament,
    event, and market data.
    Responses cached to data/raw/{tournament_slug}/{timestamp}/prophetx_*.json.
    """

    def __init__(
        self,
        base_url: str | None = None,
        cache_dir: str | None = None,
    ):
        self.base_url = (
            base_url
            or getattr(config, "PROPHETX_BASE_URL", "https://www.prophetx.co")
        )
        self.public_api = f"{self.base_url}/trade/public/api/v1"
        self.rate_limit_delay = getattr(config, "PROPHETX_RATE_LIMIT_DELAY", 0.1)
        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/raw")
        self.timeout = getattr(config, "API_TIMEOUT", 30)
        self.max_retries = getattr(config, "API_MAX_RETRIES", 3)

        # Session with persistent headers
        self.session = requests.Session()
        self.session.headers["User-Agent"] = _USER_AGENT

    def __repr__(self) -> str:
        return f"ProphetXClient(base_url={self.base_url!r})"

    # ── API Call ────────────────────────────────────────────────────

    def _api_call(
        self,
        url: str,
        params: dict | None = None,
    ) -> dict:
        """Make a public API request with retry logic.

        Returns:
            {"status": "ok", "data": <response>} or
            {"status": "error", "code": int|None, "message": str}
        """
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(
                    url, params=params, timeout=self.timeout,
                )

                if resp.status_code == 200:
                    time.sleep(self.rate_limit_delay)
                    try:
                        return {"status": "ok", "data": resp.json()}
                    except json.JSONDecodeError:
                        return {"status": "ok", "data": resp.text}

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
        """Cache API response to local filesystem."""
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

    def get_tournaments(self) -> list[dict]:
        """Fetch all available tournaments from ProphetX.

        Returns list of tournament dicts. Empty list on failure.
        """
        response = self._api_call(
            f"{self.public_api}/tournaments",
            params={"limit": "500"},
        )

        if response["status"] == "ok":
            data = response["data"]
            if isinstance(data, dict):
                return data.get("data", {}).get("tournaments", [])
            if isinstance(data, list):
                return data

        logger.warning("ProphetX: tournaments request failed: %s",
                       response.get("message", ""))
        return []

    def get_golf_events(self) -> list[dict]:
        """Fetch active golf events from ProphetX.

        Uses known golf tournament IDs for fast lookup, with fallback
        to keyword-based discovery from the full tournament list.

        Returns list of event dicts. Empty list on failure.
        """
        # Start with known golf tournament IDs
        golf_ids = set(_GOLF_TOURNAMENT_IDS.keys())

        # Also discover from full tournament list
        tournaments = self.get_tournaments()
        golf_keywords = ("golf", "pga", "masters", "open championship",
                         "us open", "ryder cup", "valero", "players")
        for t in tournaments:
            name = (t.get("name") or "").lower()
            if any(kw in name for kw in golf_keywords):
                t_id = t.get("id")
                if t_id:
                    golf_ids.add(t_id)

        if not golf_ids:
            logger.info("ProphetX: no golf tournaments found")
            return []

        # Fetch events for each golf tournament
        all_events = []
        for t_id in golf_ids:
            response = self._api_call(
                f"{self.public_api}/tournaments/{t_id}/events",
            )
            if response["status"] == "ok":
                data = response["data"]
                if isinstance(data, dict):
                    events = data.get("data", [])
                elif isinstance(data, list):
                    events = data
                else:
                    events = []
                all_events.extend(events)

        return all_events

    def get_markets_for_events(self, event_ids: list[str]) -> list[dict]:
        """Fetch markets for specific event IDs.

        Each market represents a player with YES/NO selections at various
        odds levels (orderbook style).

        Returns list of market dicts. Empty list on failure.
        """
        all_markets: list[dict] = []

        for event_id in event_ids:
            response = self._api_call(
                f"{self.public_api}/events/{event_id}/markets",
            )
            if response["status"] == "ok":
                data = response["data"]
                if isinstance(data, dict):
                    markets = data.get("data", {}).get("markets", [])
                    if not markets:
                        markets = data.get("markets", [])
                elif isinstance(data, list):
                    markets = data
                else:
                    markets = []
                all_markets.extend(markets)

        return all_markets
