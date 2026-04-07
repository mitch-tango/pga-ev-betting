from __future__ import annotations

"""
DataGolf API client.

Wraps all DG endpoints used by the betting system:
- Pre-tournament outrights (win, T5, T10, T20, MC, FRL)
- Matchups (tournament H2H, round H2H, 3-balls)
- All-pairings matchup/3-ball odds
- Live in-play predictions
- Pre-tournament predictions (skill decomposition)
- Historical odds archives (outrights + matchups)

Authentication via API key in .env file.
Rate-limited to 1.5s between calls with 3-retry exponential backoff.
Responses cached locally in data/raw/ with timestamps.
"""

import json
import time
from datetime import datetime
from pathlib import Path

import requests

import config


class DataGolfClient:
    """Client for the DataGolf API."""

    def __init__(self, api_key: str | None = None,
                 base_url: str | None = None,
                 cache_dir: str | None = None):
        self.api_key = api_key or config.DG_API_KEY
        self.base_url = base_url or config.DG_BASE_URL
        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/raw")
        self.rate_limit_delay = config.RATE_LIMIT_DELAY
        self.timeout = config.API_TIMEOUT
        self.max_retries = config.API_MAX_RETRIES

        if not self.api_key:
            raise ValueError("DG_API_KEY not set. Check .env file.")

    def _api_call(self, endpoint: str, params: dict | None = None,
                  retries: int | None = None) -> dict:
        """Make an authenticated API call with rate limiting and retry logic.

        Args:
            endpoint: API endpoint path (e.g., "/betting-tools/outrights")
            params: Query parameters (api key added automatically)
            retries: Max retry attempts (defaults to config)

        Returns:
            {"status": "ok", "data": <response>} or
            {"status": "error", "code": int, "message": str}
        """
        if params is None:
            params = {}
        params["key"] = self.api_key

        url = f"{self.base_url}{endpoint}"
        max_retries = retries or self.max_retries

        for attempt in range(max_retries):
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
                    print(f"  Rate limited. Waiting {wait}s...")
                    time.sleep(wait)

                elif resp.status_code == 400:
                    return {
                        "status": "error",
                        "code": 400,
                        "message": resp.text[:500],
                    }

                else:
                    wait = (attempt + 1) * 3
                    print(f"  HTTP {resp.status_code}. Retrying in {wait}s...")
                    time.sleep(wait)

            except requests.exceptions.Timeout:
                print(f"  Timeout on attempt {attempt + 1}. Retrying...")
                time.sleep(3)

            except requests.exceptions.RequestException as e:
                print(f"  Request error: {e}. Retrying...")
                time.sleep(3)

        return {
            "status": "error",
            "code": None,
            "message": f"Max retries ({max_retries}) exceeded for {endpoint}",
        }

    def _cache_response(self, data: dict, label: str,
                        tournament_slug: str | None = None) -> Path:
        """Cache API response to local filesystem.

        Args:
            data: Response data to cache
            label: Descriptive label (e.g., "outrights_win")
            tournament_slug: Optional tournament folder name

        Returns:
            Path to cached file
        """
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

    # ---- Betting Tools: Outrights ----

    def get_outrights(self, market: str = "win", tour: str = "pga",
                      odds_format: str = "american",
                      tournament_slug: str | None = None) -> dict:
        """Get outright/finish-position odds from DG + sportsbooks.

        Args:
            market: "win", "top_5", "top_10", "top_20", "make_cut",
                    "first_round_leader"
            tour: "pga", "euro", "opp", "alt"
            odds_format: "american", "decimal", "percent"
            tournament_slug: For local cache folder naming

        Returns:
            API response dict with DG model odds + book odds
        """
        result = self._api_call("/betting-tools/outrights", {
            "tour": tour,
            "market": market,
            "odds_format": odds_format,
        })

        if result["status"] == "ok" and tournament_slug:
            self._cache_response(result["data"], f"outrights_{market}",
                                 tournament_slug)

        return result

    # ---- Betting Tools: Matchups ----

    def get_matchups(self, market: str = "tournament_matchups",
                     tour: str = "pga", odds_format: str = "american",
                     tournament_slug: str | None = None) -> dict:
        """Get matchup odds from DG + sportsbooks.

        Args:
            market: "tournament_matchups", "round_matchups", "3_balls"
            tour: "pga", "euro", "opp", "alt"
            odds_format: "american", "decimal", "percent"
            tournament_slug: For local cache folder naming

        Returns:
            API response with DG model odds + book odds for each matchup
        """
        result = self._api_call("/betting-tools/matchups", {
            "tour": tour,
            "market": market,
            "odds_format": odds_format,
        })

        if result["status"] == "ok" and tournament_slug:
            self._cache_response(result["data"], f"matchups_{market}",
                                 tournament_slug)

        return result

    def get_all_pairings(self, tour: str = "pga",
                         odds_format: str = "american",
                         tournament_slug: str | None = None) -> dict:
        """Get DG matchup/3-ball odds for every pairing in the next round.

        Available once pairings are set for the upcoming round.

        Returns:
            API response with DG odds for all pairings
        """
        result = self._api_call("/betting-tools/matchups-all-pairings", {
            "tour": tour,
            "odds_format": odds_format,
        })

        if result["status"] == "ok" and tournament_slug:
            self._cache_response(result["data"], "all_pairings",
                                 tournament_slug)

        return result

    # ---- Predictions ----

    def get_pre_tournament_predictions(self, tour: str = "pga",
                                       odds_format: str = "percent",
                                       tournament_slug: str | None = None) -> dict:
        """Get DG pre-tournament predictions (skill decomposition).

        Returns win/T5/T10/T20/MC probabilities and skill adjustments
        for every player in the field.
        """
        result = self._api_call("/preds/pre-tournament", {
            "tour": tour,
            "odds_format": odds_format,
        })

        if result["status"] == "ok" and tournament_slug:
            self._cache_response(result["data"], "pre_tournament_preds",
                                 tournament_slug)

        return result

    def get_live_predictions(self, tour: str = "pga",
                             odds_format: str = "percent",
                             tournament_slug: str | None = None) -> dict:
        """Get live in-play predictions (updates every 5 minutes).

        Returns live win/T5/T20/MC probabilities for all players in
        an ongoing tournament.
        """
        result = self._api_call("/preds/in-play", {
            "tour": tour,
            "odds_format": odds_format,
        })

        if result["status"] == "ok" and tournament_slug:
            self._cache_response(result["data"], "live_predictions",
                                 tournament_slug)

        return result

    def get_skill_decompositions(self, tour: str = "pga",
                                  tournament_slug: str | None = None) -> dict:
        """Get player skill decompositions for the current tournament.

        Returns course-fit adjustments, SG category breakdowns, etc.
        """
        result = self._api_call("/preds/skill-decompositions", {
            "tour": tour,
        })

        if result["status"] == "ok" and tournament_slug:
            self._cache_response(result["data"], "skill_decompositions",
                                 tournament_slug)

        return result

    def get_skill_ratings(self, tour: str = "pga",
                          tournament_slug: str | None = None) -> dict:
        """Get SG category skill ratings for all players.

        Returns sg_ott, sg_app, sg_arg, sg_putt, sg_total plus driving
        stats for ~430 players across all tours (PGA + LIV + DP World).
        Used as a fallback for players missing from Betsperts ShotLink
        data (e.g., LIV Tour players).

        Returns:
            {"status": "ok", "data": {"last_updated": ..., "players": [...]}}
        """
        result = self._api_call("/preds/skill-ratings", {
            "display": "value",
            "tour": tour,
        })

        if result["status"] == "ok" and tournament_slug:
            self._cache_response(result["data"], "skill_ratings",
                                 tournament_slug)

        return result

    # ---- Field / Results ----

    def get_field_updates(self, tour: str = "pga",
                          tournament_slug: str | None = None) -> dict:
        """Get current tournament field with positions and round scores.

        After tournament completion, returns final results including:
        - current_pos: final finish position (e.g., 1, 2, T3)
        - r1/r2/r3/r4: individual round scores
        - status: "active", "cut", "wd", "dq"
        - thru: holes completed ("F" = finished)

        This is the primary endpoint for auto-settling bets.
        """
        result = self._api_call("/field-updates", {
            "tour": tour,
            "file_format": "json",
        })

        if result["status"] == "ok" and tournament_slug:
            self._cache_response(result["data"], "field_updates",
                                 tournament_slug)

        return result

    # ---- Historical Data (for backtesting) ----

    def get_historical_outrights(self, event_id: str, year: int,
                                  market: str = "win", book: str = "pinnacle",
                                  tour: str = "pga",
                                  odds_format: str = "american") -> dict:
        """Get historical outright odds for backtesting.

        Returns opening/closing lines with outcomes.
        """
        return self._api_call("/historical-odds/outrights", {
            "tour": tour,
            "event_id": event_id,
            "year": year,
            "market": market,
            "book": book,
            "odds_format": odds_format,
            "file_format": "json",
        })

    def get_historical_matchups(self, event_id: str, year: int,
                                 market: str = "tournament_matchups",
                                 book: str = "draftkings",
                                 tour: str = "pga",
                                 odds_format: str = "american") -> dict:
        """Get historical matchup odds for backtesting.

        Returns opening/closing lines at sportsbooks with outcomes.
        """
        return self._api_call("/historical-odds/matchups", {
            "tour": tour,
            "event_id": event_id,
            "year": year,
            "market": market,
            "book": book,
            "odds_format": odds_format,
            "file_format": "json",
        })

    def get_event_list(self, tour: str = "pga") -> dict:
        """Get list of events with IDs (for backtesting iteration)."""
        return self._api_call("/historical-odds/event-list", {
            "tour": tour,
            "file_format": "json",
        })

    def resolve_event_id(self, event_name: str, tour: str = "pga") -> str | None:
        """Look up the DG event_id for a given event name.

        Searches the event list for the best match. Returns the event_id
        string or None if not found.
        """
        result = self.get_event_list(tour=tour)
        if result["status"] != "ok":
            return None

        events = result["data"]
        if not isinstance(events, list):
            return None

        # Exact match first (case-insensitive)
        target = event_name.lower().strip()
        for e in events:
            if e.get("event_name", "").lower().strip() == target:
                return str(e["event_id"])

        # Substring match fallback
        for e in events:
            if target in e.get("event_name", "").lower():
                return str(e["event_id"])

        return None

    def get_historical_predictions(self, event_id: str, year: int,
                                    tour: str = "pga",
                                    odds_format: str = "percent") -> dict:
        """Get historical pre-tournament predictions for backtesting."""
        return self._api_call("/preds/pre-tournament-archive", {
            "event_id": event_id,
            "year": year,
            "odds_format": odds_format,
            "file_format": "json",
        })
