"""Tests for analytics aggregation functions in dashboard/lib/aggregations.py."""
from datetime import date

import pytest

from lib.aggregations import (
    compute_cumulative_pnl,
    compute_roi_by_group,
    compute_drawdown,
    compute_date_range,
)


# --- compute_cumulative_pnl ---


class TestComputeCumulativePnl:
    def test_cumulative_sum_sorted_by_timestamp(self):
        bets = [
            {"bet_timestamp": "2026-04-01", "pnl": 10, "id": 1},
            {"bet_timestamp": "2026-04-02", "pnl": -5, "id": 2},
        ]
        result = compute_cumulative_pnl(bets)
        assert result == [
            {"date": "2026-04-01", "cumulative_pnl": 10},
            {"date": "2026-04-02", "cumulative_pnl": 5},
        ]

    def test_single_bet(self):
        bets = [{"bet_timestamp": "2026-04-01", "pnl": 15, "id": 1}]
        result = compute_cumulative_pnl(bets)
        assert result == [{"date": "2026-04-01", "cumulative_pnl": 15}]

    def test_mix_of_positive_and_negative(self):
        bets = [
            {"bet_timestamp": "2026-04-01", "pnl": 20, "id": 1},
            {"bet_timestamp": "2026-04-02", "pnl": -30, "id": 2},
            {"bet_timestamp": "2026-04-03", "pnl": 15, "id": 3},
        ]
        result = compute_cumulative_pnl(bets)
        assert result[0]["cumulative_pnl"] == 20
        assert result[1]["cumulative_pnl"] == -10
        assert result[2]["cumulative_pnl"] == 5

    def test_stable_ordering_same_timestamp(self):
        bets = [
            {"bet_timestamp": "2026-04-01", "pnl": 10, "id": 1},
            {"bet_timestamp": "2026-04-01", "pnl": -5, "id": 2},
        ]
        result = compute_cumulative_pnl(bets)
        assert result[0]["cumulative_pnl"] == 10
        assert result[1]["cumulative_pnl"] == 5

    def test_empty_input(self):
        assert compute_cumulative_pnl([]) == []


# --- compute_roi_by_group ---


class TestComputeRoiByGroup:
    def test_groups_by_market_type(self, sample_settled_bets_analytics):
        result = compute_roi_by_group(sample_settled_bets_analytics, "market_type")
        groups = {r["group"]: r for r in result}
        assert "matchup" in groups
        assert "outright" in groups
        assert "placement" in groups
        assert "3-ball" in groups

    def test_computes_totals(self, sample_settled_bets_analytics):
        result = compute_roi_by_group(sample_settled_bets_analytics, "market_type")
        matchup = next(r for r in result if r["group"] == "matchup")
        assert matchup["total_bets"] == 4
        assert matchup["total_staked"] == pytest.approx(105.0)  # 25+30+28+22
        assert matchup["total_pnl"] == pytest.approx(46.49)  # 27.50+24.99-28+22

    def test_computes_roi_pct(self, sample_settled_bets_analytics):
        result = compute_roi_by_group(sample_settled_bets_analytics, "market_type")
        matchup = next(r for r in result if r["group"] == "matchup")
        expected_roi = 46.49 / 105.0 * 100
        assert matchup["roi_pct"] == pytest.approx(expected_roi)

    def test_computes_avg_edge_and_clv(self, sample_settled_bets_analytics):
        result = compute_roi_by_group(sample_settled_bets_analytics, "market_type")
        matchup = next(r for r in result if r["group"] == "matchup")
        # edges: 0.074, 0.075, 0.074, 0.08 -> avg * 100 = 7.575
        assert matchup["avg_edge_pct"] == pytest.approx(7.575)
        # clv: 0.03, 0.05, 0.02, 0.06 (all non-None) -> avg * 100 = 4.0
        assert matchup["avg_clv_pct"] == pytest.approx(4.0)

    def test_skips_none_clv(self, sample_settled_bets_analytics):
        result = compute_roi_by_group(sample_settled_bets_analytics, "market_type")
        outright = next(r for r in result if r["group"] == "outright")
        # Both outright bets have clv=None -> avg_clv_pct should be 0 or handled
        assert outright["avg_clv_pct"] == 0.0

    def test_counts_wins_and_losses(self, sample_settled_bets_analytics):
        result = compute_roi_by_group(sample_settled_bets_analytics, "market_type")
        matchup = next(r for r in result if r["group"] == "matchup")
        assert matchup["wins"] == 3  # 201, 202, 208
        assert matchup["losses"] == 1  # 206

    def test_single_group(self):
        bets = [
            {"market_type": "matchup", "stake": 25, "pnl": 10, "edge": 0.05,
             "clv": 0.02, "outcome": "win"},
        ]
        result = compute_roi_by_group(bets, "market_type")
        assert len(result) == 1
        assert result[0]["group"] == "matchup"

    def test_groups_by_book(self, sample_settled_bets_analytics):
        result = compute_roi_by_group(sample_settled_bets_analytics, "book")
        groups = {r["group"]: r for r in result}
        assert "DraftKings" in groups
        assert "FanDuel" in groups

    def test_empty_input(self):
        assert compute_roi_by_group([], "market_type") == []


# --- compute_drawdown ---


class TestComputeDrawdown:
    def test_high_water_mark_and_drawdown(self):
        data = [
            {"entry_date": "2026-01-01", "running_balance": 100},
            {"entry_date": "2026-01-02", "running_balance": 120},
            {"entry_date": "2026-01-03", "running_balance": 110},
            {"entry_date": "2026-01-04", "running_balance": 130},
            {"entry_date": "2026-01-05", "running_balance": 115},
        ]
        result = compute_drawdown(data)
        series = result["series"]
        assert series[0]["drawdown_pct"] == 0  # at peak
        assert series[1]["drawdown_pct"] == 0  # new peak
        assert series[2]["drawdown_pct"] == pytest.approx((110 - 120) / 120 * 100)
        assert series[3]["drawdown_pct"] == 0  # new peak
        assert series[4]["drawdown_pct"] == pytest.approx((115 - 130) / 130 * 100)

    def test_drawdown_is_zero_at_peak(self):
        data = [
            {"entry_date": "2026-01-01", "running_balance": 100},
            {"entry_date": "2026-01-02", "running_balance": 150},
        ]
        result = compute_drawdown(data)
        assert result["series"][1]["drawdown_pct"] == 0

    def test_drawdown_is_negative_below_peak(self):
        data = [
            {"entry_date": "2026-01-01", "running_balance": 200},
            {"entry_date": "2026-01-02", "running_balance": 180},
        ]
        result = compute_drawdown(data)
        assert result["series"][1]["drawdown_pct"] < 0

    def test_max_drawdown_pct(self):
        data = [
            {"entry_date": "2026-01-01", "running_balance": 100},
            {"entry_date": "2026-01-02", "running_balance": 120},
            {"entry_date": "2026-01-03", "running_balance": 110},
            {"entry_date": "2026-01-04", "running_balance": 130},
            {"entry_date": "2026-01-05", "running_balance": 115},
        ]
        result = compute_drawdown(data)
        # Max drawdown is (115-130)/130*100 = -11.538...
        assert result["max_drawdown_pct"] == pytest.approx((115 - 130) / 130 * 100)

    def test_current_drawdown_pct(self):
        data = [
            {"entry_date": "2026-01-01", "running_balance": 100},
            {"entry_date": "2026-01-02", "running_balance": 80},
        ]
        result = compute_drawdown(data)
        assert result["current_drawdown_pct"] == pytest.approx((80 - 100) / 100 * 100)

    def test_peak_lte_zero_no_division_error(self):
        data = [
            {"entry_date": "2026-01-01", "running_balance": 0},
            {"entry_date": "2026-01-02", "running_balance": -10},
        ]
        result = compute_drawdown(data)
        assert result["series"][0]["drawdown_pct"] == 0
        assert result["series"][1]["drawdown_pct"] == 0

    def test_single_entry(self):
        data = [{"entry_date": "2026-01-01", "running_balance": 500}]
        result = compute_drawdown(data)
        assert result["series"][0]["drawdown_pct"] == 0
        assert result["max_drawdown_pct"] == 0
        assert result["current_drawdown_pct"] == 0

    def test_empty_input(self):
        result = compute_drawdown([])
        assert result == {"series": [], "max_drawdown_pct": 0, "current_drawdown_pct": 0}


# --- compute_date_range ---


class TestComputeDateRange:
    def test_30d(self):
        today = date(2026, 4, 6)
        start, end = compute_date_range("30D", today=today)
        assert start == "2026-03-07"
        assert end == "2026-04-06"

    def test_90d(self):
        today = date(2026, 4, 6)
        start, end = compute_date_range("90D", today=today)
        assert start == "2026-01-06"
        assert end == "2026-04-06"

    def test_season(self):
        today = date(2026, 4, 6)
        start, end = compute_date_range("Season", today=today)
        assert start == "2026-01-01"
        assert end == "2026-04-06"
