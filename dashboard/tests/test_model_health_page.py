"""Tests for dashboard/pages/model_health.py — model health diagnostics page."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from lib.charts import build_clv_trend, build_calibration, build_roi_by_edge_tier

MOCK_STATS = {
    "total_count": 142,
    "by_market_type": {"matchup": 85, "outright": 32, "placement": 25},
    "latest_timestamp": "2026-04-04T18:30:00Z",
}

MOCK_CLV_WEEKLY = [
    {"week": "2026-03-02", "bets": 18, "avg_clv_pct": 1.2, "weekly_pnl": 45.0, "avg_edge_pct": 3.1},
    {"week": "2026-03-09", "bets": 22, "avg_clv_pct": -0.5, "weekly_pnl": -12.0, "avg_edge_pct": 2.8},
    {"week": "2026-03-16", "bets": 15, "avg_clv_pct": 2.1, "weekly_pnl": 67.0, "avg_edge_pct": 4.0},
]

MOCK_CALIBRATION = [
    {"prob_bucket": "30-40%", "n": 20, "avg_predicted_pct": 35.0, "actual_hit_pct": 38.0},
    {"prob_bucket": "40-50%", "n": 45, "avg_predicted_pct": 45.0, "actual_hit_pct": 42.0},
    {"prob_bucket": "50-60%", "n": 30, "avg_predicted_pct": 55.0, "actual_hit_pct": 57.0},
]

MOCK_EDGE_TIERS = [
    {"edge_tier": "0-2%", "total_bets": 40, "total_staked": 800.0, "total_pnl": -32.0, "roi_pct": -4.0, "avg_clv_pct": -0.5},
    {"edge_tier": "2-5%", "total_bets": 55, "total_staked": 1375.0, "total_pnl": 96.25, "roi_pct": 7.0, "avg_clv_pct": 1.2},
    {"edge_tier": "5-10%", "total_bets": 35, "total_staked": 875.0, "total_pnl": 131.25, "roi_pct": 15.0, "avg_clv_pct": 3.1},
]


class TestModelHealthCharts:
    """Test chart rendering for model health page."""

    def test_clv_trend_renders(self):
        fig = build_clv_trend(MOCK_CLV_WEEKLY)
        assert fig is not None
        assert len(fig.data) >= 1

    def test_clv_trend_none_for_empty(self):
        assert build_clv_trend([]) is None

    def test_calibration_renders(self):
        fig = build_calibration(MOCK_CALIBRATION)
        assert fig is not None
        assert len(fig.data) >= 1

    def test_calibration_none_for_empty(self):
        assert build_calibration([]) is None

    def test_roi_by_edge_tier_renders(self):
        fig = build_roi_by_edge_tier(MOCK_EDGE_TIERS)
        assert fig is not None
        assert len(fig.data) >= 1

    def test_roi_by_edge_tier_none_for_empty(self):
        assert build_roi_by_edge_tier([]) is None


class TestModelHealthDataFlow:
    """Test the data shape expectations for model health page."""

    def test_stats_has_required_fields(self):
        assert "total_count" in MOCK_STATS
        assert "by_market_type" in MOCK_STATS
        assert "latest_timestamp" in MOCK_STATS

    def test_market_type_breakdown_sums(self):
        total = sum(MOCK_STATS["by_market_type"].values())
        assert total == MOCK_STATS["total_count"]

    def test_clv_weekly_has_required_fields(self):
        for row in MOCK_CLV_WEEKLY:
            assert "week" in row
            assert "avg_clv_pct" in row
            assert "weekly_pnl" in row

    def test_edge_tiers_ordered_by_roi(self):
        rois = [t["roi_pct"] for t in MOCK_EDGE_TIERS]
        assert rois == sorted(rois)


class TestFormatRelativeTime:
    """Test the _format_relative_time helper."""

    def test_just_now(self):
        from pages.model_health import _format_relative_time
        now = datetime.now(timezone.utc)
        ts = now.isoformat()
        assert _format_relative_time(ts) == "just now"

    def test_minutes_ago(self):
        from pages.model_health import _format_relative_time
        ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        assert "5 minutes ago" in _format_relative_time(ts)

    def test_hours_ago(self):
        from pages.model_health import _format_relative_time
        ts = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        assert "3 hours ago" in _format_relative_time(ts)

    def test_days_ago(self):
        from pages.model_health import _format_relative_time
        ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        assert "2 days ago" in _format_relative_time(ts)

    def test_singular_minute(self):
        from pages.model_health import _format_relative_time
        ts = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        assert _format_relative_time(ts) == "1 minute ago"

    def test_singular_hour(self):
        from pages.model_health import _format_relative_time
        ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert _format_relative_time(ts) == "1 hour ago"

    def test_singular_day(self):
        from pages.model_health import _format_relative_time
        ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        assert _format_relative_time(ts) == "1 day ago"
