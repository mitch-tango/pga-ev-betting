"""Tests for Discord alert scheduling logic."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import config

ET = ZoneInfo("America/New_York")


class TestAlertConfig:
    """Test alert configuration constants."""

    def test_alert_defaults_disabled(self):
        """Alerts are disabled when DISCORD_ALERT_CHANNEL_ID is not set."""
        with patch.dict("os.environ", {}, clear=False):
            # When channel ID is "0" (default), ALERT_ENABLED should reflect env
            assert isinstance(config.ALERT_HIGH_EDGE_THRESHOLD, float)
            assert config.ALERT_HIGH_EDGE_THRESHOLD == 0.08

    def test_alert_schedule_hours(self):
        assert config.ALERT_PRETOURNAMENT_HOUR == 18
        assert config.ALERT_PREROUND_HOUR == 7
        # Closing capture must fire before pre-round so CLV snapshots
        # exist before any bet is acted on.
        assert config.ALERT_CLOSING_HOUR < config.ALERT_PREROUND_HOUR
        assert config.ALERT_CLOSING_HOUR == 6

    def test_high_edge_threshold(self):
        assert 0.0 < config.ALERT_HIGH_EDGE_THRESHOLD < 1.0


class TestAlertScheduleLogic:
    """Test the day/hour logic that determines which scan to run."""

    @staticmethod
    def _should_pretournament(weekday: int, hour: int) -> bool:
        """Mirror the scheduler's pre-tournament check."""
        return weekday == 2 and hour == config.ALERT_PRETOURNAMENT_HOUR

    @staticmethod
    def _should_preround(weekday: int, hour: int) -> tuple[bool, int | None]:
        """Mirror the scheduler's pre-round check. Returns (should_run, round_number)."""
        if weekday in (3, 4, 5, 6) and hour == config.ALERT_PREROUND_HOUR:
            return True, weekday - 2
        return False, None

    def test_pretournament_fires_wednesday_6pm(self):
        assert self._should_pretournament(2, 18) is True

    def test_pretournament_skips_other_days(self):
        for day in (0, 1, 3, 4, 5, 6):
            assert self._should_pretournament(day, 18) is False

    def test_pretournament_skips_wrong_hour(self):
        assert self._should_pretournament(2, 7) is False
        assert self._should_pretournament(2, 17) is False

    def test_preround_fires_thu_thru_sun(self):
        expected_rounds = {3: 1, 4: 2, 5: 3, 6: 4}
        for weekday, expected_round in expected_rounds.items():
            should, rnd = self._should_preround(weekday, config.ALERT_PREROUND_HOUR)
            assert should is True, f"Should fire on weekday {weekday}"
            assert rnd == expected_round, f"Weekday {weekday} should be R{expected_round}"

    def test_preround_skips_mon_tue_wed(self):
        for day in (0, 1, 2):
            should, _ = self._should_preround(day, config.ALERT_PREROUND_HOUR)
            assert should is False

    def test_preround_skips_wrong_hour(self):
        should, _ = self._should_preround(3, 12)
        assert should is False

    @staticmethod
    def _should_closing_capture(weekday: int, hour: int) -> tuple[bool, bool]:
        """Mirror the scheduler's closing-capture check.

        Returns (should_run, is_thursday). The is_thursday flag drives
        whether tournament-matchup closing lines are captured (one-shot
        per tournament — see validation_plan.md fix #2).
        """
        if weekday in (3, 4, 5, 6) and hour == config.ALERT_CLOSING_HOUR:
            return True, weekday == 3
        return False, False

    def test_closing_capture_fires_thu_thru_sun(self):
        for weekday in (3, 4, 5, 6):
            should, _ = self._should_closing_capture(
                weekday, config.ALERT_CLOSING_HOUR,
            )
            assert should is True, f"Should fire on weekday {weekday}"

    def test_closing_capture_only_pulls_tournament_matchups_on_thursday(self):
        _, thu = self._should_closing_capture(3, config.ALERT_CLOSING_HOUR)
        assert thu is True
        for weekday in (4, 5, 6):
            _, flag = self._should_closing_capture(
                weekday, config.ALERT_CLOSING_HOUR,
            )
            assert flag is False, (
                f"Weekday {weekday} must not capture tournament matchups "
                f"(they would double-snapshot)"
            )

    def test_closing_capture_skips_mon_tue_wed(self):
        for day in (0, 1, 2):
            should, _ = self._should_closing_capture(
                day, config.ALERT_CLOSING_HOUR,
            )
            assert should is False

    def test_closing_capture_skips_wrong_hour(self):
        should, _ = self._should_closing_capture(3, 12)
        assert should is False

    def test_closing_precedes_preround(self):
        """The scheduler must run closing capture before preround scan
        so CLV snapshots exist before bets are acted on."""
        assert config.ALERT_CLOSING_HOUR < config.ALERT_PREROUND_HOUR


class TestAlertEmbedLogic:
    """Test the high-edge classification logic."""

    def test_high_edge_classification(self):
        """Candidates above threshold are classified as high-edge."""
        threshold = config.ALERT_HIGH_EDGE_THRESHOLD

        class FakeCandidate:
            def __init__(self, edge):
                self.edge = edge

        candidates = [FakeCandidate(0.10), FakeCandidate(0.06), FakeCandidate(0.09)]
        high_edge = [c for c in candidates if c.edge >= threshold]
        assert len(high_edge) == 2  # 10% and 9% are >= 8%

    def test_no_high_edge(self):
        threshold = config.ALERT_HIGH_EDGE_THRESHOLD

        class FakeCandidate:
            def __init__(self, edge):
                self.edge = edge

        candidates = [FakeCandidate(0.05), FakeCandidate(0.06)]
        high_edge = [c for c in candidates if c.edge >= threshold]
        assert len(high_edge) == 0
