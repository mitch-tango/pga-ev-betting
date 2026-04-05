"""Tests for graceful degradation when Kalshi is unavailable."""
from unittest.mock import patch, MagicMock
import pytest

from src.pipeline.pull_kalshi import (
    pull_kalshi_outrights,
    pull_kalshi_matchups,
    merge_kalshi_into_outrights,
    merge_kalshi_into_matchups,
)


class TestGracefulDegradation:
    """Pipeline completes with DG-only data under various Kalshi failure modes."""

    def test_api_unreachable(self):
        """Kalshi API network error -> returns empty data."""
        with patch("src.pipeline.pull_kalshi.KalshiClient") as mock_cls:
            mock_cls.return_value.get_golf_events.side_effect = ConnectionError("unreachable")
            result = pull_kalshi_outrights("The Masters", "2026-04-09", "2026-04-13")
        # Should return empty lists, not raise
        for market in result.values():
            assert isinstance(market, list)
            assert len(market) == 0

    def test_no_golf_events(self):
        """No open golf events on Kalshi -> returns empty data."""
        with patch("src.pipeline.pull_kalshi.KalshiClient") as mock_cls:
            mock_cls.return_value.get_golf_events.return_value = []
            result = pull_kalshi_outrights("The Masters", "2026-04-09", "2026-04-13")
        for market in result.values():
            assert len(market) == 0

    def test_tournament_cant_be_matched(self):
        """Tournament matching fails -> returns empty data."""
        with patch("src.pipeline.pull_kalshi.KalshiClient") as mock_cls:
            # Return events but none match the tournament name
            mock_cls.return_value.get_golf_events.return_value = [
                {"event_ticker": "KXPGATOUR-FOO", "title": "Some Other Tournament",
                 "series_ticker": "KXPGATOUR"}
            ]
            result = pull_kalshi_outrights("The Masters", "2026-04-09", "2026-04-13")
        for market in result.values():
            assert len(market) == 0

    def test_merge_with_empty_kalshi_is_noop(self):
        """Merging empty Kalshi data doesn't alter DG data."""
        dg_outrights = {
            "win": [{"player_name": "Player 1", "dg_id": "1",
                      "datagolf": {"baseline": "+200"}, "draftkings": "+300"}],
        }
        import copy
        original = copy.deepcopy(dg_outrights)
        result = merge_kalshi_into_outrights(dg_outrights, {"win": [], "t10": [], "t20": []})
        # DG data unchanged
        assert result["win"][0]["player_name"] == original["win"][0]["player_name"]
        assert "kalshi" not in result["win"][0]

    def test_merge_matchups_with_empty_kalshi_is_noop(self):
        """Merging empty Kalshi matchups doesn't alter DG data."""
        dg_matchups = [{"p1_player_name": "A", "p2_player_name": "B",
                        "odds": {"draftkings": {"p1": "-130", "p2": "+115"}}}]
        result = merge_kalshi_into_matchups(dg_matchups, [])
        assert "kalshi" not in result[0]["odds"]

    def test_partial_data_uses_available(self):
        """Some markets available (win OK, t10 empty) -> merges what's available."""
        dg = {
            "win": [{"player_name": "Scheffler, Scottie", "dg_id": "1",
                      "datagolf": {"baseline": "+150"}, "draftkings": "+200"}],
            "top_10": [{"player_name": "Scheffler, Scottie", "dg_id": "1",
                         "datagolf": {"baseline": "+100"}, "draftkings": "+110"}],
        }
        kalshi = {
            "win": [{"player_name": "Scheffler, Scottie",
                     "kalshi_mid_prob": 0.30, "kalshi_ask_prob": 0.32,
                     "open_interest": 500}],
            "t10": [],  # No t10 data
            "t20": [],
        }
        result = merge_kalshi_into_outrights(dg, kalshi)
        # Win market has Kalshi
        assert "kalshi" in result["win"][0]
        # T10 market does not
        assert "kalshi" not in result["top_10"][0]

    def test_rate_limit_client_handles_429(self):
        """Client handles 429 responses gracefully."""
        # The KalshiClient._request method has retry logic for 429s.
        # This is tested in test_kalshi_client.py; here we verify the
        # pull functions don't break when the client raises after retries.
        with patch("src.pipeline.pull_kalshi.KalshiClient") as mock_cls:
            mock_cls.return_value.get_golf_events.side_effect = Exception("429 Too Many Requests")
            result = pull_kalshi_outrights("The Masters", "2026-04-09", "2026-04-13")
        for market in result.values():
            assert len(market) == 0
