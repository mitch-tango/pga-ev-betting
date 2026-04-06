"""Tests for dashboard/pages/performance.py — performance page logic."""
from __future__ import annotations

import pytest

from lib.aggregations import compute_cumulative_pnl, compute_roi_by_group, compute_date_range
from lib.charts import build_pnl_curve, build_edge_histogram

MOCK_SETTLED = [
    {
        "id": 1, "tournament_id": 1, "market_type": "matchup",
        "player_name": "Scottie Scheffler", "opponent_name": "Rory McIlroy",
        "book": "DraftKings", "bet_timestamp": "2026-03-15T08:00:00Z",
        "odds_at_bet_decimal": 2.10, "odds_at_bet_american": "+110",
        "implied_prob_at_bet": 0.476, "your_prob": 0.55,
        "edge": 0.074, "stake": 25.0, "clv": 0.03,
        "outcome": "win", "pnl": 27.50,
    },
    {
        "id": 2, "tournament_id": 1, "market_type": "placement",
        "player_name": "Jon Rahm", "opponent_name": None,
        "book": "Caesars", "bet_timestamp": "2026-03-16T07:00:00Z",
        "odds_at_bet_decimal": 3.50, "odds_at_bet_american": "+250",
        "implied_prob_at_bet": 0.286, "your_prob": 0.35,
        "edge": 0.064, "stake": 20.0, "clv": -0.02,
        "outcome": "loss", "pnl": -20.0,
    },
    {
        "id": 3, "tournament_id": 2, "market_type": "matchup",
        "player_name": "Xander Schauffele", "opponent_name": "Collin Morikawa",
        "book": "FanDuel", "bet_timestamp": "2026-03-20T10:00:00Z",
        "odds_at_bet_decimal": 1.90, "odds_at_bet_american": "-111",
        "implied_prob_at_bet": 0.526, "your_prob": 0.60,
        "edge": 0.074, "stake": 28.0, "clv": 0.05,
        "outcome": "win", "pnl": 25.20,
    },
    {
        "id": 4, "tournament_id": 2, "market_type": "outright",
        "player_name": "Ludvig Aberg", "opponent_name": None,
        "book": "BetMGM", "bet_timestamp": "2026-03-22T14:00:00Z",
        "odds_at_bet_decimal": 20.0, "odds_at_bet_american": "+1900",
        "implied_prob_at_bet": 0.05, "your_prob": 0.07,
        "edge": 0.02, "stake": 5.0, "clv": None,
        "outcome": "loss", "pnl": -5.0,
    },
]


class TestPerformanceDataFlow:
    """Test the data pipeline: settled bets -> aggregations -> charts."""

    def test_cumulative_pnl_from_settled_bets(self):
        result = compute_cumulative_pnl(MOCK_SETTLED)
        assert len(result) == 4
        assert result[0]["cumulative_pnl"] == 27.50
        assert result[-1]["cumulative_pnl"] == pytest.approx(27.70)

    def test_pnl_curve_renders_from_settled(self):
        cumulative = compute_cumulative_pnl(MOCK_SETTLED)
        fig = build_pnl_curve(cumulative)
        assert fig is not None
        assert len(fig.data) == 1

    def test_pnl_curve_none_for_empty(self):
        assert build_pnl_curve([]) is None

    def test_roi_by_market_type(self):
        result = compute_roi_by_group(MOCK_SETTLED, "market_type")
        groups = {r["group"]: r for r in result}
        assert "matchup" in groups
        assert "placement" in groups
        assert "outright" in groups
        assert groups["matchup"]["total_bets"] == 2
        assert groups["matchup"]["wins"] == 2

    def test_roi_by_book(self):
        result = compute_roi_by_group(MOCK_SETTLED, "book")
        groups = {r["group"]: r for r in result}
        assert "DraftKings" in groups
        assert "Caesars" in groups
        assert "FanDuel" in groups
        assert "BetMGM" in groups

    def test_edge_histogram_renders(self):
        fig = build_edge_histogram(MOCK_SETTLED)
        assert fig is not None
        histograms = [t for t in fig.data if hasattr(t, "xbins") or t.type == "histogram"]
        assert len(histograms) == 2

    def test_edge_histogram_none_for_empty(self):
        assert build_edge_histogram([]) is None


class TestPerformanceFiltering:
    """Test filtering logic used in the bet detail table."""

    def test_filter_by_market_type(self):
        filtered = [b for b in MOCK_SETTLED if b["market_type"] == "matchup"]
        assert len(filtered) == 2

    def test_filter_by_book(self):
        filtered = [b for b in MOCK_SETTLED if b["book"] == "DraftKings"]
        assert len(filtered) == 1

    def test_filter_by_both(self):
        filtered = [
            b for b in MOCK_SETTLED
            if b["market_type"] == "matchup" and b["book"] == "FanDuel"
        ]
        assert len(filtered) == 1

    def test_no_filter_returns_all(self):
        assert len(MOCK_SETTLED) == 4

    def test_opponent_none_handled(self):
        none_opponents = [b for b in MOCK_SETTLED if b["opponent_name"] is None]
        assert len(none_opponents) == 2  # placement and outright


class TestPerformanceDateRange:
    """Test date range computation for time window selector."""

    def test_season_default(self):
        from datetime import date
        start, end = compute_date_range("Season", today=date(2026, 4, 6))
        assert start == "2026-01-01"
        assert end == "2026-04-06"

    def test_30d_window(self):
        from datetime import date
        start, end = compute_date_range("30D", today=date(2026, 4, 6))
        assert start == "2026-03-07"

    def test_90d_window(self):
        from datetime import date
        start, end = compute_date_range("90D", today=date(2026, 4, 6))
        assert start == "2026-01-06"
