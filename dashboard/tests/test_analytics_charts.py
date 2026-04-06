"""Tests for analytics chart builder functions in dashboard/lib/charts.py."""
from __future__ import annotations

import plotly.graph_objects as go

from lib.charts import (
    build_pnl_curve,
    build_edge_histogram,
    build_bankroll_drawdown,
    build_weekly_exposure,
    build_clv_trend,
    build_calibration,
    build_roi_by_edge_tier,
)
from lib.theme import COLOR_POSITIVE, COLOR_NEGATIVE

SAMPLE_CUMULATIVE_PNL_POSITIVE = [
    {"date": "2026-01-15", "cumulative_pnl": 10.0},
    {"date": "2026-01-22", "cumulative_pnl": -5.0},
    {"date": "2026-01-29", "cumulative_pnl": 25.0},
]

SAMPLE_CUMULATIVE_PNL_NEGATIVE = [
    {"date": "2026-01-15", "cumulative_pnl": 10.0},
    {"date": "2026-01-22", "cumulative_pnl": -15.0},
]

SAMPLE_BETS_WITH_EDGE = [
    {"edge": 0.05}, {"edge": 0.12}, {"edge": -0.03},
    {"edge": 0.08}, {"edge": -0.01},
]

SAMPLE_BANKROLL = [
    {"entry_date": "2026-01-01", "running_balance": 1000.0},
    {"entry_date": "2026-01-15", "running_balance": 1100.0},
    {"entry_date": "2026-02-01", "running_balance": 950.0},
]

SAMPLE_DRAWDOWN = [
    {"entry_date": "2026-01-01", "drawdown_pct": 0.0},
    {"entry_date": "2026-01-15", "drawdown_pct": 0.0},
    {"entry_date": "2026-02-01", "drawdown_pct": -13.6},
]

SAMPLE_WEEKLY_EXPOSURE = [
    {"week": "2026-01-05", "total_exposure": 500.0, "bets_placed": 10},
    {"week": "2026-01-12", "total_exposure": 750.0, "bets_placed": 15},
    {"week": "2026-01-19", "total_exposure": 600.0, "bets_placed": 12},
]

SAMPLE_CLV_POSITIVE = [
    {"week": "2026-01-05", "avg_clv_pct": 1.5},
    {"week": "2026-01-12", "avg_clv_pct": 2.1},
    {"week": "2026-01-19", "avg_clv_pct": 0.8},
]

SAMPLE_CALIBRATION = [
    {"prob_bucket": "30-40%", "n": 20, "avg_predicted_pct": 35.0, "actual_hit_pct": 38.0},
    {"prob_bucket": "40-50%", "n": 45, "avg_predicted_pct": 45.0, "actual_hit_pct": 42.0},
    {"prob_bucket": "50-60%", "n": 30, "avg_predicted_pct": 55.0, "actual_hit_pct": 57.0},
]

SAMPLE_EDGE_TIERS = [
    {"edge_tier": "0-3%", "roi_pct": -2.5, "total_bets": 40},
    {"edge_tier": "3-5%", "roi_pct": 5.1, "total_bets": 30},
    {"edge_tier": "5-10%", "roi_pct": 12.3, "total_bets": 15},
]


# --- build_pnl_curve ---


class TestBuildPnlCurve:
    def test_returns_figure_with_scatter_trace(self):
        fig = build_pnl_curve(SAMPLE_CUMULATIVE_PNL_POSITIVE)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Scatter)

    def test_returns_none_for_empty_input(self):
        assert build_pnl_curve([]) is None

    def test_line_color_positive(self):
        fig = build_pnl_curve(SAMPLE_CUMULATIVE_PNL_POSITIVE)
        assert fig.data[0].line.color == COLOR_POSITIVE

    def test_line_color_negative(self):
        fig = build_pnl_curve(SAMPLE_CUMULATIVE_PNL_NEGATIVE)
        assert fig.data[0].line.color == COLOR_NEGATIVE

    def test_has_zero_reference_line(self):
        fig = build_pnl_curve(SAMPLE_CUMULATIVE_PNL_POSITIVE)
        shapes = fig.layout.shapes
        assert any(getattr(s, "y0", None) == 0 and getattr(s, "y1", None) == 0 for s in shapes)

    def test_yaxis_dollar_prefix(self):
        fig = build_pnl_curve(SAMPLE_CUMULATIVE_PNL_POSITIVE)
        assert fig.layout.yaxis.tickprefix == "$"

    def test_common_layout_applied(self):
        fig = build_pnl_curve(SAMPLE_CUMULATIVE_PNL_POSITIVE)
        assert fig.layout.paper_bgcolor == "rgba(0,0,0,0)"
        assert fig.layout.font.color == "#E0E0E0"


# --- build_edge_histogram ---


class TestBuildEdgeHistogram:
    def test_returns_figure_with_two_histogram_traces(self):
        fig = build_edge_histogram(SAMPLE_BETS_WITH_EDGE)
        assert isinstance(fig, go.Figure)
        histograms = [t for t in fig.data if isinstance(t, go.Histogram)]
        assert len(histograms) == 2

    def test_returns_none_for_empty_input(self):
        assert build_edge_histogram([]) is None

    def test_positive_trace_color(self):
        fig = build_edge_histogram(SAMPLE_BETS_WITH_EDGE)
        assert fig.data[0].marker.color == COLOR_POSITIVE

    def test_negative_trace_color(self):
        fig = build_edge_histogram(SAMPLE_BETS_WITH_EDGE)
        assert fig.data[1].marker.color == COLOR_NEGATIVE

    def test_has_vertical_reference_line(self):
        fig = build_edge_histogram(SAMPLE_BETS_WITH_EDGE)
        shapes = fig.layout.shapes
        assert any(getattr(s, "x0", None) == 0 and getattr(s, "x1", None) == 0 for s in shapes)

    def test_xaxis_percent_suffix(self):
        fig = build_edge_histogram(SAMPLE_BETS_WITH_EDGE)
        assert fig.layout.xaxis.ticksuffix == "%"


# --- build_bankroll_drawdown ---


class TestBuildBankrollDrawdown:
    def test_returns_figure_with_subplots(self):
        fig = build_bankroll_drawdown(SAMPLE_BANKROLL, SAMPLE_DRAWDOWN)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 2

    def test_returns_none_when_both_empty(self):
        assert build_bankroll_drawdown([], []) is None

    def test_top_panel_has_balance_trace(self):
        fig = build_bankroll_drawdown(SAMPLE_BANKROLL, SAMPLE_DRAWDOWN)
        balance_trace = fig.data[0]
        assert isinstance(balance_trace, go.Scatter)

    def test_bottom_panel_has_fill(self):
        fig = build_bankroll_drawdown(SAMPLE_BANKROLL, SAMPLE_DRAWDOWN)
        dd_trace = fig.data[1]
        assert dd_trace.fill == "tozeroy"

    def test_top_yaxis_dollar_prefix(self):
        fig = build_bankroll_drawdown(SAMPLE_BANKROLL, SAMPLE_DRAWDOWN)
        assert fig.layout.yaxis.tickprefix == "$"

    def test_bottom_yaxis_percent_suffix(self):
        fig = build_bankroll_drawdown(SAMPLE_BANKROLL, SAMPLE_DRAWDOWN)
        assert fig.layout.yaxis2.ticksuffix == "%"


# --- build_weekly_exposure ---


class TestBuildWeeklyExposure:
    def test_returns_figure_with_bar_and_line(self):
        fig = build_weekly_exposure(SAMPLE_WEEKLY_EXPOSURE)
        assert isinstance(fig, go.Figure)
        bars = [t for t in fig.data if isinstance(t, go.Bar)]
        lines = [t for t in fig.data if isinstance(t, go.Scatter)]
        assert len(bars) == 1
        assert len(lines) == 1

    def test_returns_none_for_empty_input(self):
        assert build_weekly_exposure([]) is None

    def test_bar_on_primary_yaxis(self):
        fig = build_weekly_exposure(SAMPLE_WEEKLY_EXPOSURE)
        bar = [t for t in fig.data if isinstance(t, go.Bar)][0]
        assert bar.yaxis in (None, "y", "y1")

    def test_line_on_secondary_yaxis(self):
        fig = build_weekly_exposure(SAMPLE_WEEKLY_EXPOSURE)
        line = [t for t in fig.data if isinstance(t, go.Scatter)][0]
        assert line.yaxis == "y2"


# --- build_clv_trend ---


class TestBuildClvTrend:
    def test_returns_figure_with_scatter_trace(self):
        fig = build_clv_trend(SAMPLE_CLV_POSITIVE)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Scatter)

    def test_returns_none_for_empty_input(self):
        assert build_clv_trend([]) is None

    def test_has_zero_reference_line(self):
        fig = build_clv_trend(SAMPLE_CLV_POSITIVE)
        shapes = fig.layout.shapes
        assert any(getattr(s, "y0", None) == 0 and getattr(s, "y1", None) == 0 for s in shapes)

    def test_line_color_positive(self):
        fig = build_clv_trend(SAMPLE_CLV_POSITIVE)
        assert fig.data[0].line.color == COLOR_POSITIVE


# --- build_calibration ---


class TestBuildCalibration:
    def test_returns_figure_with_scatter_trace(self):
        fig = build_calibration(SAMPLE_CALIBRATION)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Scatter)

    def test_returns_none_for_empty_input(self):
        assert build_calibration([]) is None

    def test_has_diagonal_reference_line(self):
        fig = build_calibration(SAMPLE_CALIBRATION)
        shapes = fig.layout.shapes
        assert any(
            getattr(s, "x0", None) == 0 and getattr(s, "y0", None) == 0
            and getattr(s, "x1", None) == 100 and getattr(s, "y1", None) == 100
            for s in shapes
        )

    def test_marker_sizemode_area(self):
        fig = build_calibration(SAMPLE_CALIBRATION)
        assert fig.data[0].marker.sizemode == "area"

    def test_axes_have_percent_suffix(self):
        fig = build_calibration(SAMPLE_CALIBRATION)
        assert fig.layout.xaxis.ticksuffix == "%"
        assert fig.layout.yaxis.ticksuffix == "%"


# --- build_roi_by_edge_tier ---


class TestBuildRoiByEdgeTier:
    def test_returns_figure_with_bar_and_line(self):
        fig = build_roi_by_edge_tier(SAMPLE_EDGE_TIERS)
        assert isinstance(fig, go.Figure)
        bars = [t for t in fig.data if isinstance(t, go.Bar)]
        lines = [t for t in fig.data if isinstance(t, go.Scatter)]
        assert len(bars) == 1
        assert len(lines) == 1

    def test_returns_none_for_empty_input(self):
        assert build_roi_by_edge_tier([]) is None

    def test_bar_colors_by_roi_sign(self):
        fig = build_roi_by_edge_tier(SAMPLE_EDGE_TIERS)
        bar = [t for t in fig.data if isinstance(t, go.Bar)][0]
        colors = list(bar.marker.color)
        assert colors[0] == COLOR_NEGATIVE  # -2.5%
        assert colors[1] == COLOR_POSITIVE  # 5.1%
        assert colors[2] == COLOR_POSITIVE  # 12.3%

    def test_has_zero_reference_line(self):
        fig = build_roi_by_edge_tier(SAMPLE_EDGE_TIERS)
        shapes = fig.layout.shapes
        assert any(getattr(s, "y0", None) == 0 and getattr(s, "y1", None) == 0 for s in shapes)

    def test_line_on_secondary_yaxis(self):
        fig = build_roi_by_edge_tier(SAMPLE_EDGE_TIERS)
        line = [t for t in fig.data if isinstance(t, go.Scatter)][0]
        assert line.yaxis == "y2"
