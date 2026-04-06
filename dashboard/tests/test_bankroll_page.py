"""Tests for dashboard/pages/bankroll.py — bankroll page logic."""
from __future__ import annotations

import pytest

from lib.aggregations import compute_drawdown
from lib.charts import build_bankroll_drawdown, build_weekly_exposure


SAMPLE_BANKROLL = [
    {"entry_date": "2026-01-01", "entry_type": "deposit", "amount": 500.0, "running_balance": 500.0},
    {"entry_date": "2026-01-10", "entry_type": "settlement", "amount": 27.50, "running_balance": 527.50},
    {"entry_date": "2026-01-15", "entry_type": "settlement", "amount": 24.99, "running_balance": 552.49},
    {"entry_date": "2026-02-05", "entry_type": "settlement", "amount": -10.0, "running_balance": 542.49},
    {"entry_date": "2026-02-10", "entry_type": "settlement", "amount": -20.0, "running_balance": 522.49},
    {"entry_date": "2026-02-15", "entry_type": "deposit", "amount": 200.0, "running_balance": 722.49},
    {"entry_date": "2026-03-01", "entry_type": "settlement", "amount": 27.0, "running_balance": 749.49},
    {"entry_date": "2026-03-10", "entry_type": "settlement", "amount": -28.0, "running_balance": 721.49},
    {"entry_date": "2026-03-20", "entry_type": "settlement", "amount": -5.0, "running_balance": 716.49},
    {"entry_date": "2026-03-25", "entry_type": "withdrawal", "amount": -100.0, "running_balance": 616.49},
    {"entry_date": "2026-04-01", "entry_type": "settlement", "amount": 22.0, "running_balance": 638.49},
]

SAMPLE_EXPOSURE = [
    {"week": "2026-01-05", "total_exposure": 500.0, "bets_placed": 10, "largest_single_bet": 30.0, "unique_players": 4},
    {"week": "2026-01-12", "total_exposure": 750.0, "bets_placed": 15, "largest_single_bet": 40.0, "unique_players": 6},
    {"week": "2026-01-19", "total_exposure": 600.0, "bets_placed": 12, "largest_single_bet": 30.0, "unique_players": 5},
]


class TestBankrollMetrics:
    """Test metric computation from bankroll data."""

    def test_current_balance_is_last_entry(self):
        assert SAMPLE_BANKROLL[-1]["running_balance"] == 638.49

    def test_balance_delta_from_previous(self):
        current = SAMPLE_BANKROLL[-1]["running_balance"]
        previous = SAMPLE_BANKROLL[-2]["running_balance"]
        delta = current - previous
        assert delta == pytest.approx(22.0)

    def test_drawdown_computation(self):
        result = compute_drawdown(SAMPLE_BANKROLL)
        assert result["max_drawdown_pct"] < 0
        assert len(result["series"]) == len(SAMPLE_BANKROLL)

    def test_current_drawdown_at_end(self):
        result = compute_drawdown(SAMPLE_BANKROLL)
        # Peak is 749.49, current is 638.49 -> drawdown = (638.49-749.49)/749.49*100
        expected = (638.49 - 749.49) / 749.49 * 100
        assert result["current_drawdown_pct"] == pytest.approx(expected)

    def test_max_drawdown_value(self):
        result = compute_drawdown(SAMPLE_BANKROLL)
        # Max drawdown is current since it's the lowest relative to peak
        assert result["max_drawdown_pct"] == pytest.approx(
            (616.49 - 749.49) / 749.49 * 100
        )

    def test_empty_bankroll(self):
        result = compute_drawdown([])
        assert result["series"] == []
        assert result["max_drawdown_pct"] == 0
        assert result["current_drawdown_pct"] == 0


class TestBankrollCharts:
    """Test chart rendering from bankroll data."""

    def test_bankroll_drawdown_chart_renders(self):
        dd = compute_drawdown(SAMPLE_BANKROLL)
        fig = build_bankroll_drawdown(SAMPLE_BANKROLL, dd["series"])
        assert fig is not None
        assert len(fig.data) == 2

    def test_bankroll_drawdown_chart_none_for_empty(self):
        assert build_bankroll_drawdown([], []) is None

    def test_weekly_exposure_chart_renders(self):
        fig = build_weekly_exposure(SAMPLE_EXPOSURE)
        assert fig is not None
        assert len(fig.data) == 2

    def test_weekly_exposure_chart_none_for_empty(self):
        assert build_weekly_exposure([]) is None
