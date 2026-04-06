"""Tests for analytics query functions in dashboard/lib/queries.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import lib.queries  # noqa: F401 — force submodule into sys.modules for @patch resolution


def _make_mock_client():
    """Create a mock Supabase client with chainable query methods."""
    return MagicMock()


def _setup_query_chain(client, data, count=None):
    """Configure mock client to return data for a chainable query."""
    chain = client.table.return_value
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.is_.return_value = chain
    chain.lte.return_value = chain
    chain.gte.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    result = MagicMock(data=data)
    result.count = count
    chain.execute.return_value = result
    return chain


# --- get_settled_bets ---


class TestGetSettledBets:
    @patch("lib.queries.get_client")
    def test_returns_settled_bets_only(self, mock_get_client):
        from lib.queries import get_settled_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        bets = [{"id": 1, "outcome": "win", "pnl": 10.0}]
        chain = _setup_query_chain(client, bets)

        result = get_settled_bets.__wrapped__()
        assert result == bets
        chain.is_.assert_called_with("outcome", "not.null")

    @patch("lib.queries.get_client")
    def test_filters_by_start_date(self, mock_get_client):
        from lib.queries import get_settled_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [])

        get_settled_bets.__wrapped__(start_date="2026-01-01")
        chain.gte.assert_called_with("bet_timestamp", "2026-01-01")

    @patch("lib.queries.get_client")
    def test_filters_by_end_date(self, mock_get_client):
        from lib.queries import get_settled_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [])

        get_settled_bets.__wrapped__(end_date="2026-03-31")
        chain.lte.assert_called_with("bet_timestamp", "2026-03-31")

    @patch("lib.queries.get_client")
    def test_filters_by_both_dates(self, mock_get_client):
        from lib.queries import get_settled_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [])

        get_settled_bets.__wrapped__(start_date="2026-01-01", end_date="2026-03-31")
        chain.gte.assert_called_with("bet_timestamp", "2026-01-01")
        chain.lte.assert_called_with("bet_timestamp", "2026-03-31")

    @patch("lib.queries.get_client")
    def test_returns_all_when_no_date_params(self, mock_get_client):
        from lib.queries import get_settled_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [{"id": 1}, {"id": 2}])

        result = get_settled_bets.__wrapped__()
        assert len(result) == 2
        # gte/lte should not be called with bet_timestamp args
        for call in chain.gte.call_args_list:
            assert call[0][0] != "bet_timestamp"
        for call in chain.lte.call_args_list:
            assert call[0][0] != "bet_timestamp"

    @patch("lib.queries.get_client")
    def test_returns_empty_list_when_no_bets(self, mock_get_client):
        from lib.queries import get_settled_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        _setup_query_chain(client, [])

        result = get_settled_bets.__wrapped__()
        assert result == []

    @patch("lib.queries.get_client")
    def test_ordered_by_timestamp_and_id(self, mock_get_client):
        from lib.queries import get_settled_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [])

        get_settled_bets.__wrapped__()
        order_calls = [c[0][0] for c in chain.order.call_args_list]
        assert "bet_timestamp" in order_calls
        assert "id" in order_calls

    @patch("lib.queries.get_client")
    def test_selects_explicit_columns(self, mock_get_client):
        from lib.queries import get_settled_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [])

        get_settled_bets.__wrapped__()
        select_arg = chain.select.call_args[0][0]
        assert select_arg != "*"
        assert "pnl" in select_arg
        assert "outcome" in select_arg

    def test_has_cache_decorator(self):
        from lib.queries import get_settled_bets

        assert hasattr(get_settled_bets, "__wrapped__")


# --- get_settled_bet_stats ---


class TestGetSettledBetStats:
    @patch("lib.queries.get_client")
    def test_returns_total_count(self, mock_get_client):
        from lib.queries import get_settled_bet_stats

        client = _make_mock_client()
        mock_get_client.return_value = client
        data = [
            {"market_type": "matchup", "bet_timestamp": "2026-01-10T08:00:00Z"},
            {"market_type": "matchup", "bet_timestamp": "2026-01-15T09:00:00Z"},
            {"market_type": "outright", "bet_timestamp": "2026-02-05T14:00:00Z"},
        ]
        _setup_query_chain(client, data, count=3)

        result = get_settled_bet_stats.__wrapped__()
        assert result["total_count"] == 3

    @patch("lib.queries.get_client")
    def test_returns_by_market_type(self, mock_get_client):
        from lib.queries import get_settled_bet_stats

        client = _make_mock_client()
        mock_get_client.return_value = client
        data = [
            {"market_type": "matchup", "bet_timestamp": "2026-01-10T08:00:00Z"},
            {"market_type": "matchup", "bet_timestamp": "2026-01-15T09:00:00Z"},
            {"market_type": "outright", "bet_timestamp": "2026-02-05T14:00:00Z"},
        ]
        _setup_query_chain(client, data, count=3)

        result = get_settled_bet_stats.__wrapped__()
        assert result["by_market_type"]["matchup"] == 2
        assert result["by_market_type"]["outright"] == 1

    @patch("lib.queries.get_client")
    def test_returns_latest_timestamp(self, mock_get_client):
        from lib.queries import get_settled_bet_stats

        client = _make_mock_client()
        mock_get_client.return_value = client
        data = [
            {"market_type": "matchup", "bet_timestamp": "2026-01-10T08:00:00Z"},
            {"market_type": "outright", "bet_timestamp": "2026-02-05T14:00:00Z"},
        ]
        _setup_query_chain(client, data, count=2)

        result = get_settled_bet_stats.__wrapped__()
        assert result["latest_timestamp"] == "2026-02-05T14:00:00Z"

    @patch("lib.queries.get_client")
    def test_returns_zeros_when_no_bets(self, mock_get_client):
        from lib.queries import get_settled_bet_stats

        client = _make_mock_client()
        mock_get_client.return_value = client
        _setup_query_chain(client, [], count=0)

        result = get_settled_bet_stats.__wrapped__()
        assert result["total_count"] == 0
        assert result["by_market_type"] == {}
        assert result["latest_timestamp"] is None

    def test_has_cache_decorator(self):
        from lib.queries import get_settled_bet_stats

        assert hasattr(get_settled_bet_stats, "__wrapped__")


# --- get_bankroll_curve ---


class TestGetBankrollCurve:
    @patch("lib.queries.get_client")
    def test_returns_data_from_view(self, mock_get_client):
        from lib.queries import get_bankroll_curve

        client = _make_mock_client()
        mock_get_client.return_value = client
        data = [
            {"entry_date": "2026-01-01", "entry_type": "deposit", "amount": 500.0, "running_balance": 500.0},
            {"entry_date": "2026-01-10", "entry_type": "settlement", "amount": 27.50, "running_balance": 527.50},
        ]
        _setup_query_chain(client, data)

        result = get_bankroll_curve.__wrapped__()
        assert result == data
        client.table.assert_called_with("v_bankroll_curve")

    @patch("lib.queries.get_client")
    def test_returns_expected_columns(self, mock_get_client):
        from lib.queries import get_bankroll_curve

        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [])

        get_bankroll_curve.__wrapped__()
        select_arg = chain.select.call_args[0][0]
        for col in ["entry_date", "entry_type", "amount", "running_balance"]:
            assert col in select_arg

    @patch("lib.queries.get_client")
    def test_returns_empty_list_when_no_data(self, mock_get_client):
        from lib.queries import get_bankroll_curve

        client = _make_mock_client()
        mock_get_client.return_value = client
        _setup_query_chain(client, [])

        result = get_bankroll_curve.__wrapped__()
        assert result == []

    def test_has_cache_decorator(self):
        from lib.queries import get_bankroll_curve

        assert hasattr(get_bankroll_curve, "__wrapped__")


# --- get_weekly_exposure ---


class TestGetWeeklyExposure:
    @patch("lib.queries.get_client")
    def test_returns_data_from_view(self, mock_get_client):
        from lib.queries import get_weekly_exposure

        client = _make_mock_client()
        mock_get_client.return_value = client
        data = [{"week": "2026-01-05", "bets_placed": 5, "total_exposure": 120.0,
                 "largest_single_bet": 30.0, "unique_players": 4}]
        _setup_query_chain(client, data)

        result = get_weekly_exposure.__wrapped__()
        assert result == data
        client.table.assert_called_with("v_weekly_exposure")

    @patch("lib.queries.get_client")
    def test_returns_expected_columns(self, mock_get_client):
        from lib.queries import get_weekly_exposure

        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [])

        get_weekly_exposure.__wrapped__()
        select_arg = chain.select.call_args[0][0]
        for col in ["week", "bets_placed", "total_exposure", "largest_single_bet", "unique_players"]:
            assert col in select_arg

    def test_has_cache_decorator(self):
        from lib.queries import get_weekly_exposure

        assert hasattr(get_weekly_exposure, "__wrapped__")


# --- get_clv_weekly ---


class TestGetClvWeekly:
    @patch("lib.queries.get_client")
    def test_returns_data_from_view(self, mock_get_client):
        from lib.queries import get_clv_weekly

        client = _make_mock_client()
        mock_get_client.return_value = client
        data = [{"week": "2026-01-05", "bets": 5, "avg_clv_pct": 2.1,
                 "weekly_pnl": 52.49, "avg_edge_pct": 5.5}]
        _setup_query_chain(client, data)

        result = get_clv_weekly.__wrapped__()
        assert result == data
        client.table.assert_called_with("v_clv_weekly")

    @patch("lib.queries.get_client")
    def test_returns_expected_columns(self, mock_get_client):
        from lib.queries import get_clv_weekly

        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [])

        get_clv_weekly.__wrapped__()
        select_arg = chain.select.call_args[0][0]
        for col in ["week", "bets", "avg_clv_pct", "weekly_pnl", "avg_edge_pct"]:
            assert col in select_arg

    def test_has_cache_decorator(self):
        from lib.queries import get_clv_weekly

        assert hasattr(get_clv_weekly, "__wrapped__")


# --- get_calibration ---


class TestGetCalibration:
    @patch("lib.queries.get_client")
    def test_returns_data_from_view(self, mock_get_client):
        from lib.queries import get_calibration

        client = _make_mock_client()
        mock_get_client.return_value = client
        data = [{"prob_bucket": "10-20%", "n": 62, "avg_predicted_pct": 14.8, "actual_hit_pct": 16.1}]
        _setup_query_chain(client, data)

        result = get_calibration.__wrapped__()
        assert result == data
        client.table.assert_called_with("v_calibration")

    @patch("lib.queries.get_client")
    def test_returns_expected_columns(self, mock_get_client):
        from lib.queries import get_calibration

        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [])

        get_calibration.__wrapped__()
        select_arg = chain.select.call_args[0][0]
        for col in ["prob_bucket", "n", "avg_predicted_pct", "actual_hit_pct"]:
            assert col in select_arg

    def test_has_cache_decorator(self):
        from lib.queries import get_calibration

        assert hasattr(get_calibration, "__wrapped__")


# --- get_roi_by_edge_tier ---


class TestGetRoiByEdgeTier:
    @patch("lib.queries.get_client")
    def test_returns_data_from_view(self, mock_get_client):
        from lib.queries import get_roi_by_edge_tier

        client = _make_mock_client()
        mock_get_client.return_value = client
        data = [{"edge_tier": "2-5%", "total_bets": 80, "total_staked": 2000.0,
                 "total_pnl": 120.0, "roi_pct": 6.0, "avg_clv_pct": 2.1}]
        _setup_query_chain(client, data)

        result = get_roi_by_edge_tier.__wrapped__()
        assert result == data
        client.table.assert_called_with("v_roi_by_edge_tier")

    @patch("lib.queries.get_client")
    def test_returns_expected_columns(self, mock_get_client):
        from lib.queries import get_roi_by_edge_tier

        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [])

        get_roi_by_edge_tier.__wrapped__()
        select_arg = chain.select.call_args[0][0]
        for col in ["edge_tier", "total_bets", "total_staked", "total_pnl", "roi_pct", "avg_clv_pct"]:
            assert col in select_arg

    def test_has_cache_decorator(self):
        from lib.queries import get_roi_by_edge_tier

        assert hasattr(get_roi_by_edge_tier, "__wrapped__")
