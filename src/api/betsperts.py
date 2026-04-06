"""Betsperts Golf API client (undocumented session-based API).

Wraps the internal JSON API at api.betspertsgolf.com, discovered via
browser network inspection. Requires a valid session_key from an
authenticated betspertsgolf.com session (stored in localStorage).

Primary value: ShotLink-powered strokes gained data with granular
condition filtering (greens surface, course length, field strength, etc.)
that complements DataGolf's model probabilities.

Key endpoints:
  POST /user/rabbit_hole/load       — Field-wide SG stats with 50+ filters
  POST /user/player/AvgSGsummaryEventWise — Per-golfer SG breakdown
  POST /user/leaderboard/by_tournament    — Course stats / leaderboard
  GET  /user/simulation/playerData        — Sim player list
  POST /user/tee_time                     — Tee time data
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


# ── Default request body for rabbit_hole/load ─────────────────────

def _default_rabbit_hole_body() -> dict:
    """Return the full default request body with all condition filters empty."""
    return {
        "playerID": "",
        "displayTourId": "14",
        "tyear": str(datetime.now().year),
        "tourIndex": 1,
        "date": "6 Months",
        "region": [],
        "ctype": [],
        "view": "Strokes Gained",
        "course": [],
        "courseName": ["All Courses"],
        "season": [],
        "condition": [],
        "clength": [],
        "fieldStrength": [],
        "par": [],
        "cut": [],
        "tournament": [],
        "eventSeason": [],
        "fieldSize": [],
        "bunkerDanger": [],
        "waterDanger": [],
        "green": [],
        "greenSize": [],
        "speed": [],
        "fairwaySurface": [],
        "roughSurface": [],
        "rough": [],
        "elevation": [],
        "architect": [],
        "gainOTT": [],
        "OTTClub": [],
        "fwyAccuracy": [],
        "missedFwyPenalty": [],
        "roughPenalty": [],
        "gainAPP": [],
        "GIRAccuracy": [],
        "par3Scoring": [],
        "par4Scoring": [],
        "par5Scoring": [],
        "gainARG": [],
        "scramblingRough": [],
        "scramblingShortGrass": [],
        "sandSavesCond": [],
        "gainPutting": [],
        "gainingPuttingInside15": [],
        "gainingPuttingOutside15": [],
        "PuttAVD": [],
        "display": "Average",
        "TempAVG": [],
        "GrassCondition": [],
        "PreferredLies": [],
        "play": [],
        "teeTime": [],
        "startDate": "",
        "endDate": "",
        "round": "",
        "wind": [],
        "min_round": "",
    }


# ── View name constants ───────────────────────────────────────────

VIEWS = [
    "Strokes Gained",
    "Off The Tee",
    "Approach",
    "Approach Scoring Opps",
    "Overall Approach Proximity",
    "Fairway Approach Proximity",
    "Rough Approach Proximity",
    "Around the Green",
    "Around the Green - Shot Types",
    "Putting",
    "Putting Ranges",
    "Scoring",
    "Par 3 Efficiency",
    "Par 4 Efficiency",
    "Par 5 Efficiency",
    "MISC Metrics",
    "Floor/Ceiling",
    "Finish Position",
    "Rolling Averages",
]

DISPLAY_MODES = ["Rank", "Average", "Total", "Rounds Gained %"]


class BetspertsClient:
    """Client for the Betsperts Golf internal API.

    Auth is session-based: a ``session_key`` header (hex string) obtained
    from an authenticated browser session. The key persists across browser
    sessions but may eventually expire, requiring a fresh login on the
    website and extracting the new key from localStorage.

    Responses are cached locally to data/raw/{slug}/{timestamp}/betsperts_*.json.
    """

    def __init__(
        self,
        session_key: str | None = None,
        base_url: str | None = None,
        cache_dir: str | None = None,
    ):
        self.session_key = session_key or getattr(
            config, "BETSPERTS_SESSION_KEY", None
        )
        if not self.session_key:
            raise ValueError(
                "Betsperts session_key required. Set BETSPERTS_SESSION_KEY in .env "
                "or pass session_key= to the constructor. Extract it from "
                "localStorage('session_key') on betspertsgolf.com."
            )
        self.base_url = base_url or getattr(
            config, "BETSPERTS_BASE_URL", "https://api.betspertsgolf.com"
        )
        self.rate_limit_delay = getattr(config, "BETSPERTS_RATE_LIMIT_DELAY", 1.0)
        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/raw")
        self.timeout = getattr(config, "API_TIMEOUT", 30)
        self.max_retries = getattr(config, "API_MAX_RETRIES", 3)

        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "session_key": self.session_key,
        })

    def __repr__(self) -> str:
        return f"BetspertsClient(base_url={self.base_url!r})"

    # ── Low-level API call ────────────────────────────────────────

    def _api_call(
        self,
        endpoint: str,
        method: str = "POST",
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        """Make an API request with retry logic.

        Returns:
            {"status": "ok", "data": <response>} or
            {"status": "error", "code": int|None, "message": str}
        """
        url = f"{self.base_url}{endpoint}"

        for attempt in range(self.max_retries):
            try:
                if method == "POST":
                    resp = self.session.post(
                        url, json=json_body, timeout=self.timeout,
                    )
                else:
                    resp = self.session.get(
                        url, params=params, timeout=self.timeout,
                    )

                if resp.status_code == 200:
                    time.sleep(self.rate_limit_delay)
                    try:
                        data = resp.json()
                    except json.JSONDecodeError:
                        return {"status": "ok", "data": resp.text}
                    # Betsperts wraps data in {"data": ..., "status": true}
                    if isinstance(data, dict) and "status" in data:
                        if not data["status"]:
                            return {
                                "status": "error",
                                "code": 200,
                                "message": "API returned status=false",
                            }
                    return {"status": "ok", "data": data}

                elif resp.status_code == 401:
                    return {
                        "status": "error",
                        "code": 401,
                        "message": (
                            "Session expired. Re-login at betspertsgolf.com and "
                            "update BETSPERTS_SESSION_KEY from localStorage."
                        ),
                    }

                elif resp.status_code == 429:
                    wait = (attempt + 1) * 5
                    logger.warning("Betsperts rate limited. Waiting %ds...", wait)
                    time.sleep(wait)

                elif resp.status_code == 400:
                    return {
                        "status": "error",
                        "code": 400,
                        "message": resp.text[:500],
                    }

                else:
                    wait = (attempt + 1) * 3
                    logger.warning(
                        "Betsperts HTTP %d. Retrying in %ds...",
                        resp.status_code, wait,
                    )
                    time.sleep(wait)

            except requests.exceptions.Timeout:
                logger.warning("Betsperts timeout on attempt %d", attempt + 1)
                time.sleep(3)

            except requests.exceptions.RequestException as e:
                logger.warning("Betsperts request error: %s", e)
                time.sleep(3)

        return {
            "status": "error",
            "code": None,
            "message": f"Max retries ({self.max_retries}) exceeded for {endpoint}",
        }

    # ── Cache ─────────────────────────────────────────────────────

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
        filepath = cache_path / f"betsperts_{label}.json"

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("Cached Betsperts %s → %s", label, filepath)
        return filepath

    # ── Rabbit Hole (main data endpoint) ──────────────────────────

    def get_field_stats(
        self,
        tournament_name: str,
        *,
        view: str = "Strokes Gained",
        display: str = "Average",
        time_frame: str = "6 Months",
        last_n_rounds: int | str = "",
        min_rounds: int | str = "",
        tour_id: str = "14",
        year: str | None = None,
        conditions: dict | None = None,
        tournament_slug: str | None = None,
    ) -> dict:
        """Fetch SG stats for an entire tournament field.

        Args:
            tournament_name: e.g. "Masters Tournament", "RBC Heritage"
            view: Stat category — one of VIEWS (default "Strokes Gained")
            display: "Average" (actual values), "Rank", "Total", "Rounds Gained %"
            time_frame: "6 Months", "12 Months", "2 Years", "3 Years"
            last_n_rounds: Filter to last N rounds (8, 12, 16, 20, 24, 30, 36, 50, 75)
            min_rounds: Minimum rounds played to include player
            tour_id: "14" for PGA Tour
            year: Tournament year (default: current year)
            conditions: Dict of condition filters to override defaults.
                Keys match the API body fields, e.g.:
                {"green": ["Bent"], "speed": ["Fast"], "clength": ["Long"]}
            tournament_slug: For cache directory naming

        Returns:
            Standard envelope: {"status": "ok", "data": {"data": [...], "status": true}}
            Each player record has: playerName, player_num, Rounds, ShotLink,
            SG:TOT, SG:T2G, SG:OTT, SG:APP, SG:BS, SG:ARG, SG:P, SG:SG,
            FanDuel, DraftKings (values are actual SG when display="Average")
        """
        body = _default_rabbit_hole_body()
        body["playerID"] = tournament_name
        body["view"] = view
        body["display"] = display
        body["date"] = time_frame
        body["round"] = last_n_rounds
        body["min_round"] = str(min_rounds) if min_rounds else ""
        body["displayTourId"] = tour_id
        body["tyear"] = year or str(datetime.now().year)

        if conditions:
            body.update(conditions)

        result = self._api_call("/user/rabbit_hole/load", json_body=body)

        if result["status"] == "ok" and tournament_slug:
            view_label = view.lower().replace(" ", "_").replace("/", "_")
            self._cache_response(
                result["data"],
                f"field_{view_label}_{display.lower()}",
                tournament_slug=tournament_slug,
            )

        return result

    def get_field_sg_averages(
        self,
        tournament_name: str,
        *,
        time_frame: str = "6 Months",
        last_n_rounds: int | str = "",
        conditions: dict | None = None,
        tournament_slug: str | None = None,
    ) -> list[dict] | None:
        """Convenience: fetch average SG values for a tournament field.

        Returns a list of player dicts with actual SG averages, or None on error.
        """
        result = self.get_field_stats(
            tournament_name,
            view="Strokes Gained",
            display="Average",
            time_frame=time_frame,
            last_n_rounds=last_n_rounds,
            conditions=conditions,
            tournament_slug=tournament_slug,
        )
        if result["status"] != "ok":
            logger.error("Failed to fetch field SG averages: %s", result.get("message"))
            return None

        data = result["data"]
        if isinstance(data, dict):
            return data.get("data", [])
        return data

    def get_field_condition_filtered(
        self,
        tournament_name: str,
        *,
        greens: list[str] | None = None,
        greens_speed: list[str] | None = None,
        course_length: list[str] | None = None,
        field_strength: list[str] | None = None,
        scoring_conditions: list[str] | None = None,
        elevation: list[str] | None = None,
        time_frame: str = "12 Months",
        last_n_rounds: int | str = 36,
        tournament_slug: str | None = None,
    ) -> list[dict] | None:
        """Fetch SG averages filtered by course conditions.

        This is the highest-value method for course-fit analysis — filter
        player SG performance to only rounds played under similar conditions
        to the target course.

        Args:
            greens: e.g. ["Bent"], ["Bermuda", "Bent"]
            greens_speed: e.g. ["Fast"], ["Average"]
            course_length: e.g. ["Long"], ["Very Long"]
            field_strength: e.g. ["Strong"], ["Very Strong"]
            scoring_conditions: e.g. ["Difficult"], ["Very Difficult"]
            elevation: e.g. ["Average"], ["High"]
        """
        conditions = {}
        if greens:
            conditions["green"] = greens
        if greens_speed:
            conditions["speed"] = greens_speed
        if course_length:
            conditions["clength"] = course_length
        if field_strength:
            conditions["fieldStrength"] = field_strength
        if scoring_conditions:
            conditions["condition"] = scoring_conditions
        if elevation:
            conditions["elevation"] = elevation

        return self.get_field_sg_averages(
            tournament_name,
            time_frame=time_frame,
            last_n_rounds=last_n_rounds,
            conditions=conditions,
            tournament_slug=tournament_slug,
        )

    # ── Golfer Profile ────────────────────────────────────────────

    def get_golfer_stats(
        self,
        player_id: str,
        *,
        tournament_slug: str | None = None,
    ) -> dict:
        """Fetch a golfer's SG summary broken down by event.

        Args:
            player_id: Betsperts player_num (e.g. "46046" for Scheffler)
        """
        result = self._api_call(
            "/user/player/AvgSGsummaryEventWise",
            json_body={"playerID": player_id},
        )

        if result["status"] == "ok" and tournament_slug:
            self._cache_response(
                result["data"],
                f"golfer_{player_id}",
                tournament_slug=tournament_slug,
            )

        return result

    # ── Course Stats ──────────────────────────────────────────────

    def get_course_leaderboard(
        self,
        tournament_name: str,
        *,
        tournament_slug: str | None = None,
    ) -> dict:
        """Fetch course leaderboard / stats for a tournament."""
        result = self._api_call(
            "/user/leaderboard/by_tournament",
            json_body={"tournament": tournament_name},
        )

        if result["status"] == "ok" and tournament_slug:
            self._cache_response(
                result["data"],
                "course_leaderboard",
                tournament_slug=tournament_slug,
            )

        return result

    # ── Simulation Player Data ────────────────────────────────────

    def get_simulation_players(self) -> dict:
        """Fetch available players for the custom matchup simulator."""
        return self._api_call(
            "/user/simulation/playerData",
            method="GET",
        )

    # ── Tee Times ─────────────────────────────────────────────────

    def get_tee_times(
        self,
        tour_id: str = "14",
        year: str | None = None,
    ) -> dict:
        """Fetch tee time data for the current tournament."""
        return self._api_call(
            "/user/tee_time",
            json_body={
                "year": year or str(datetime.now().year),
                "tourID": tour_id,
                "play": 1,
                "teeTime": "",
            },
        )

    # ── Session health check ──────────────────────────────────────

    def check_session(self) -> bool:
        """Quick check that the session key is still valid.

        Returns True if authenticated, False if session expired.
        """
        result = self.get_tee_times()
        if result["status"] == "error" and result.get("code") == 401:
            logger.error("Betsperts session expired. Update BETSPERTS_SESSION_KEY.")
            return False
        return result["status"] == "ok"
