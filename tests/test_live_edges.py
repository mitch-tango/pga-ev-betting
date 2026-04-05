"""Tests for live edge detection pipeline."""

from __future__ import annotations

import pytest

from src.pipeline.pull_live_edges import (
    _match_live_to_outright,
    _get_live_prob,
    _override_dg_with_live,
)


class TestMatchLiveToOutright:
    """Test player name matching between live and outright data."""

    def test_exact_match(self):
        live = [{"player_name": "Scottie Scheffler"}]
        outrights = [{"player_name": "Scottie Scheffler"}]
        matches = _match_live_to_outright(live, outrights)
        assert 0 in matches
        assert matches[0]["player_name"] == "Scottie Scheffler"

    def test_case_insensitive_match(self):
        live = [{"player_name": "scottie scheffler"}]
        outrights = [{"player_name": "Scottie Scheffler"}]
        matches = _match_live_to_outright(live, outrights)
        assert 0 in matches

    def test_quoted_name_match(self):
        """Outright names sometimes have quotes from DG API."""
        live = [{"player_name": "Rory McIlroy"}]
        outrights = [{"player_name": '"Rory McIlroy"'}]
        matches = _match_live_to_outright(live, outrights)
        # Outright names get stripped of quotes before matching
        # The fuzzy match should handle minor differences
        assert 0 in matches

    def test_fuzzy_match(self):
        live = [{"player_name": "Si Woo Kim"}]
        outrights = [{"player_name": "S.W. Kim"}]
        matches = _match_live_to_outright(live, outrights)
        # Should match with fuzzy threshold >= 0.80
        # This may or may not match depending on ratio — test the logic
        # SequenceMatcher("si woo kim", "s.w. kim").ratio() ≈ 0.59 — won't match
        # That's correct behavior — ambiguous names should NOT match
        assert 0 not in matches

    def test_no_match_low_similarity(self):
        live = [{"player_name": "Tiger Woods"}]
        outrights = [{"player_name": "Jon Rahm"}]
        matches = _match_live_to_outright(live, outrights)
        assert 0 not in matches

    def test_multiple_players(self):
        live = [
            {"player_name": "Scottie Scheffler"},
            {"player_name": "Rory McIlroy"},
            {"player_name": "Jon Rahm"},
        ]
        outrights = [
            {"player_name": "Scottie Scheffler"},
            {"player_name": "Jon Rahm"},
            {"player_name": "Rory McIlroy"},
        ]
        matches = _match_live_to_outright(live, outrights)
        assert len(matches) == 3
        assert matches[0]["player_name"] == "Scottie Scheffler"
        assert matches[1]["player_name"] == "Jon Rahm"
        assert matches[2]["player_name"] == "Rory McIlroy"

    def test_empty_live(self):
        matches = _match_live_to_outright([], [{"player_name": "Tiger"}])
        assert matches == {}

    def test_empty_outrights(self):
        matches = _match_live_to_outright([{"player_name": "Tiger"}], [])
        assert matches == {}


class TestGetLiveProb:
    """Test extracting probabilities from live prediction records."""

    def test_win_probability(self):
        live = {"win": 0.15, "top_10": 0.45}
        assert _get_live_prob(live, "win") == 0.15

    def test_top_10_primary_key(self):
        live = {"top_10": 0.45}
        assert _get_live_prob(live, "top_10") == 0.45

    def test_top_10_alias(self):
        live = {"t10": 0.45}
        assert _get_live_prob(live, "top_10") == 0.45

    def test_top_20_alias(self):
        live = {"t20": 0.70}
        assert _get_live_prob(live, "top_20") == 0.70

    def test_make_cut_alias(self):
        live = {"mc": 0.85}
        assert _get_live_prob(live, "make_cut") == 0.85

    def test_missing_key(self):
        live = {"win": 0.15}
        assert _get_live_prob(live, "top_10") is None

    def test_string_value_converted(self):
        live = {"win": "0.15"}
        assert _get_live_prob(live, "win") == 0.15

    def test_none_value(self):
        live = {"win": None}
        assert _get_live_prob(live, "win") is None


class TestOverrideDgWithLive:
    """Test replacing DG model probs with live predictions."""

    def _make_outrights(self, players):
        """Create minimal outrights data structure."""
        return {
            "win": [
                {
                    "player_name": name,
                    "datagolf": {"baseline_history_fit": old_odds, "baseline": old_odds},
                    "draftkings": "+400",
                }
                for name, old_odds in players
            ],
            "_event_name": "Test Open",
        }

    def test_override_replaces_dg_odds(self):
        outrights = self._make_outrights([
            ("Scottie Scheffler", "+500"),
            ("Rory McIlroy", "+1000"),
        ])
        live = [
            {"player_name": "Scottie Scheffler", "win": 0.25},  # ~+300
            {"player_name": "Rory McIlroy", "win": 0.10},       # ~+900
        ]

        matched = _override_dg_with_live(outrights, live)
        assert matched == 2

        # DG odds should now reflect live probabilities
        scheffler_dg = outrights["win"][0]["datagolf"]
        assert scheffler_dg["baseline_history_fit"] != "+500"
        assert scheffler_dg["baseline"] != "+500"

    def test_unmatched_players_unchanged(self):
        outrights = self._make_outrights([
            ("Scottie Scheffler", "+500"),
            ("Unknown Player", "+2000"),
        ])
        live = [{"player_name": "Scottie Scheffler", "win": 0.25}]

        _override_dg_with_live(outrights, live)

        # Unknown Player should keep original odds
        assert outrights["win"][1]["datagolf"]["baseline_history_fit"] == "+2000"

    def test_skips_metadata_keys(self):
        outrights = {
            "win": [{"player_name": "Test", "datagolf": {"baseline": "+500"}}],
            "_event_name": "Masters",
        }
        live = [{"player_name": "Test", "win": 0.20}]

        # Should not crash on _event_name key
        matched = _override_dg_with_live(outrights, live)
        assert matched == 1

    def test_zero_probability_not_overridden(self):
        outrights = self._make_outrights([("Test Player", "+500")])
        live = [{"player_name": "Test Player", "win": 0.0}]

        _override_dg_with_live(outrights, live)
        # Zero prob should be skipped — original odds preserved
        assert outrights["win"][0]["datagolf"]["baseline_history_fit"] == "+500"


class TestLiveMonitorConfig:
    """Test live monitoring configuration."""

    def test_monitor_interval(self):
        import config
        assert config.LIVE_MONITOR_INTERVAL_MIN > 0
        assert config.LIVE_MONITOR_INTERVAL_MIN <= 60

    def test_monitor_hours(self):
        import config
        assert config.LIVE_MONITOR_START_HOUR < config.LIVE_MONITOR_END_HOUR
        assert 0 <= config.LIVE_MONITOR_START_HOUR <= 23
        assert 0 <= config.LIVE_MONITOR_END_HOUR <= 23
