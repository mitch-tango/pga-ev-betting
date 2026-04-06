"""Tests for dashboard/pages/active_bets.py — page rendering and display logic."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import date

from lib.aggregations import (
    compute_exposure,
    compute_weekly_pnl,
    estimate_round,
    format_date_range,
)


# ===== Aggregation-based tests (pure logic, no Streamlit) =====


class TestExposureSummary:
    def test_aggregates_count_by_market(self, sample_active_bets):
        result = compute_exposure(sample_active_bets)
        assert result["matchup"]["count"] == 1
        assert result["outright"]["count"] == 1
        assert result["3-ball"]["count"] == 1

    def test_aggregates_stake_by_market(self, sample_active_bets):
        result = compute_exposure(sample_active_bets)
        assert result["matchup"]["total_stake"] == 30.0
        assert result["outright"]["total_stake"] == 10.0

    def test_potential_return_per_market(self, sample_active_bets):
        result = compute_exposure(sample_active_bets)
        assert result["outright"]["potential_return"] == pytest.approx(150.0)

    def test_totals_across_markets(self, sample_active_bets):
        result = compute_exposure(sample_active_bets)
        assert result["__total__"]["count"] == 3


class TestEdgeClvDisplay:
    def test_positive_edge_color(self):
        from lib.theme import color_value, COLOR_POSITIVE
        assert color_value(0.05) == COLOR_POSITIVE

    def test_negative_edge_color(self):
        from lib.theme import color_value, COLOR_NEGATIVE
        assert color_value(-0.02) == COLOR_NEGATIVE

    def test_null_clv_formatted_as_dash(self):
        from lib.theme import format_percentage
        assert format_percentage(None) == "\u2014"

    def test_clv_formatted_with_sign(self):
        from lib.theme import format_percentage
        assert format_percentage(0.032) == "+3.2%"
        assert format_percentage(-0.011) == "-1.1%"


class TestWeeklyPnl:
    def test_settled_pnl_computed(self, sample_bets):
        result = compute_weekly_pnl(sample_bets)
        assert result["settled_pnl"] == pytest.approx(7.50)

    def test_open_exposure(self, sample_bets):
        result = compute_weekly_pnl(sample_bets)
        assert result["unsettled_stake"] == pytest.approx(55.0)

    def test_net_position(self, sample_bets):
        result = compute_weekly_pnl(sample_bets)
        assert result["net_position"] == pytest.approx(7.50 - 55.0)

    def test_zero_settled_all_open(self, sample_active_bets):
        result = compute_weekly_pnl(sample_active_bets)
        assert result["settled_pnl"] == 0.0


# ===== Page-level smoke tests (using Streamlit AppTest) =====


class TestActiveBetsPageSmoke:
    @patch("lib.queries.get_current_tournament", return_value=None)
    def test_no_tournament_shows_info(self, mock_get_tournament):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("pages/active_bets.py", default_timeout=10)
        at.run()
        info_values = [el.value for el in at.info]
        assert any("No active tournament" in v for v in info_values)

    @patch("lib.queries.get_current_tournament", return_value=None)
    def test_no_tournament_hides_table(self, mock_get_tournament):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("pages/active_bets.py", default_timeout=10)
        at.run()
        # Should not have any dataframes when no tournament
        assert len(at.dataframe) == 0

    @patch("lib.queries.get_weekly_pnl", return_value={"settled_pnl": 0, "unsettled_stake": 0, "net_position": 0})
    @patch("lib.queries.get_active_bets", return_value=[])
    @patch("lib.queries.get_current_tournament")
    def test_tournament_name_shown(self, mock_tournament, mock_bets, mock_pnl, sample_tournament):
        from streamlit.testing.v1 import AppTest

        mock_tournament.return_value = sample_tournament
        at = AppTest.from_file("pages/active_bets.py", default_timeout=10)
        at.run()
        title_values = [el.value for el in at.title]
        assert any("The Masters" in v for v in title_values)


class TestFormatDateRange:
    def test_standard_range(self):
        assert format_date_range("2026-04-03") == "Apr 3 \u2013 Apr 6, 2026"


class TestEstimateRound:
    def test_round_1(self):
        assert estimate_round("2026-04-02", today=date(2026, 4, 2)) == 1

    def test_round_2(self):
        assert estimate_round("2026-04-02", today=date(2026, 4, 3)) == 2

    def test_before_tournament(self):
        assert estimate_round("2026-04-02", today=date(2026, 4, 1)) is None

    def test_after_tournament(self):
        assert estimate_round("2026-04-02", today=date(2026, 4, 7)) is None
