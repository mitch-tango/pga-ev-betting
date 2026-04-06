"""Tests for dashboard/lib/aggregations.py — pure aggregation logic."""

import pytest
from datetime import date

from lib.aggregations import (
    group_by_market_type,
    compute_exposure,
    compute_weekly_pnl,
    estimate_round,
    format_date_range,
)


# --- group_by_market_type ---


class TestGroupByMarketType:
    def test_groups_bets_by_market_type(self, sample_bets):
        result = group_by_market_type(sample_bets)
        assert set(result.keys()) == {"matchup", "outright", "placement", "3-ball"}
        assert len(result["matchup"]) == 2
        assert len(result["outright"]) == 1
        assert len(result["placement"]) == 1
        assert len(result["3-ball"]) == 1

    def test_empty_list_returns_empty_dict(self):
        assert group_by_market_type([]) == {}


# --- compute_exposure ---


class TestComputeExposure:
    def test_correct_count_stake_and_return_per_group(self, sample_active_bets):
        result = compute_exposure(sample_active_bets)
        # sample_active_bets: matchup (id102, stake=30, odds=1.833),
        #   outright (id103, stake=10, odds=15.0), 3-ball (id105, stake=15, odds=2.80)
        assert result["matchup"]["count"] == 1
        assert result["matchup"]["total_stake"] == 30.0
        assert result["matchup"]["potential_return"] == pytest.approx(30.0 * 1.833)

        assert result["outright"]["count"] == 1
        assert result["outright"]["total_stake"] == 10.0
        assert result["outright"]["potential_return"] == pytest.approx(10.0 * 15.0)

        assert result["3-ball"]["count"] == 1
        assert result["3-ball"]["total_stake"] == 15.0
        assert result["3-ball"]["potential_return"] == pytest.approx(15.0 * 2.80)

    def test_empty_bets_returns_empty_dict(self):
        assert compute_exposure([]) == {}

    def test_totals_row_sums_all_market_types(self, sample_active_bets):
        result = compute_exposure(sample_active_bets)
        total = result["__total__"]
        assert total["count"] == 3
        assert total["total_stake"] == pytest.approx(55.0)
        expected_return = 30.0 * 1.833 + 10.0 * 15.0 + 15.0 * 2.80
        assert total["potential_return"] == pytest.approx(expected_return)


# --- compute_weekly_pnl ---


class TestComputeWeeklyPnl:
    def test_sums_settled_and_unsettled(self, sample_bets):
        result = compute_weekly_pnl(sample_bets)
        # settled: id101 pnl=27.50, id104 pnl=-20.0 => settled_pnl=7.50
        # unsettled: id102 stake=30, id103 stake=10, id105 stake=15 => 55.0
        assert result["settled_pnl"] == pytest.approx(7.50)
        assert result["unsettled_stake"] == pytest.approx(55.0)

    def test_net_position(self, sample_bets):
        result = compute_weekly_pnl(sample_bets)
        assert result["net_position"] == pytest.approx(7.50 - 55.0)

    def test_all_open(self, sample_active_bets):
        result = compute_weekly_pnl(sample_active_bets)
        assert result["settled_pnl"] == 0.0
        assert result["unsettled_stake"] == pytest.approx(55.0)
        assert result["net_position"] == pytest.approx(-55.0)

    def test_all_settled(self, sample_settled_bets):
        result = compute_weekly_pnl(sample_settled_bets)
        assert result["settled_pnl"] == pytest.approx(7.50)
        assert result["unsettled_stake"] == 0.0
        assert result["net_position"] == pytest.approx(7.50)


# --- estimate_round ---


class TestEstimateRound:
    def test_round_1_on_start_date(self):
        assert estimate_round("2026-04-02", today=date(2026, 4, 2)) == 1

    def test_round_2_day_after_start(self):
        assert estimate_round("2026-04-02", today=date(2026, 4, 3)) == 2

    def test_round_3(self):
        assert estimate_round("2026-04-02", today=date(2026, 4, 4)) == 3

    def test_round_4(self):
        assert estimate_round("2026-04-02", today=date(2026, 4, 5)) == 4

    def test_none_before_start(self):
        assert estimate_round("2026-04-02", today=date(2026, 4, 1)) is None

    def test_none_after_tournament(self):
        assert estimate_round("2026-04-02", today=date(2026, 4, 7)) is None


# --- format_date_range ---


class TestFormatDateRange:
    def test_formats_correctly(self):
        assert format_date_range("2026-04-03") == "Apr 3 \u2013 Apr 6, 2026"

    def test_month_boundary(self):
        # Start Mar 30 -> end Apr 2
        assert format_date_range("2026-03-30") == "Mar 30 \u2013 Apr 2, 2026"
