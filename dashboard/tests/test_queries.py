from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

import lib.queries  # noqa: F401 — force submodule into sys.modules for @patch resolution


def _make_mock_client():
    """Create a mock Supabase client with chainable query methods."""
    client = MagicMock()
    return client


def _setup_query_chain(client, data):
    """Configure mock client to return data for a chainable query."""
    chain = client.table.return_value
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.is_.return_value = chain
    chain.lte.return_value = chain
    chain.gte.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(data=data)
    return chain


# --- get_current_tournament ---

class TestGetCurrentTournament:
    @patch("lib.queries.get_client")
    @patch("lib.queries.date")
    def test_returns_tournament_when_active(self, mock_date, mock_get_client):
        from lib.queries import get_current_tournament

        mock_date.today.return_value = date(2026, 4, 3)  # Friday of tournament
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        client = _make_mock_client()
        mock_get_client.return_value = client
        tournament = {"id": 1, "tournament_name": "The Masters", "start_date": "2026-04-02"}
        chain = _setup_query_chain(client, [tournament])

        result = get_current_tournament.__wrapped__()
        assert result == tournament
        # Verify date filters: lte("start_date", "2026-04-04"), gte("start_date", "2026-03-30")
        chain.lte.assert_called_with("start_date", "2026-04-04")
        chain.gte.assert_called_with("start_date", "2026-03-30")

    @patch("lib.queries.get_client")
    @patch("lib.queries.date")
    def test_returns_none_during_off_week(self, mock_date, mock_get_client):
        from lib.queries import get_current_tournament

        mock_date.today.return_value = date(2026, 3, 15)  # Off week
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        client = _make_mock_client()
        mock_get_client.return_value = client
        _setup_query_chain(client, [])

        result = get_current_tournament.__wrapped__()
        assert result is None

    @patch("lib.queries.get_client")
    @patch("lib.queries.date")
    def test_wednesday_before_tournament(self, mock_date, mock_get_client):
        from lib.queries import get_current_tournament

        mock_date.today.return_value = date(2026, 4, 1)  # Wednesday before Thu start
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        client = _make_mock_client()
        mock_get_client.return_value = client
        tournament = {"id": 1, "tournament_name": "The Masters", "start_date": "2026-04-02"}
        chain = _setup_query_chain(client, [tournament])

        result = get_current_tournament.__wrapped__()
        assert result == tournament
        # Wed Apr 1: lte = Apr 2, gte = Mar 28 — tournament start_date Apr 2 is within range
        chain.lte.assert_called_with("start_date", "2026-04-02")
        chain.gte.assert_called_with("start_date", "2026-03-28")

    @patch("lib.queries.get_client")
    @patch("lib.queries.date")
    def test_monday_after_tournament_returns_none(self, mock_date, mock_get_client):
        from lib.queries import get_current_tournament

        mock_date.today.return_value = date(2026, 4, 7)  # Monday after Thu-Sun
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [])

        result = get_current_tournament.__wrapped__()
        assert result is None
        # Mon Apr 7: lte = Apr 8, gte = Apr 3 — tournament start_date Apr 2 is outside range
        chain.lte.assert_called_with("start_date", "2026-04-08")
        chain.gte.assert_called_with("start_date", "2026-04-03")

    @patch("lib.queries.get_client")
    @patch("lib.queries.date")
    def test_selects_explicit_columns(self, mock_date, mock_get_client):
        from lib.queries import get_current_tournament

        mock_date.today.return_value = date(2026, 4, 3)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [])

        get_current_tournament.__wrapped__()
        select_arg = chain.select.call_args[0][0]
        assert select_arg != "*"
        assert "tournament_name" in select_arg


# --- get_active_bets ---

class TestGetActiveBets:
    @patch("lib.queries.get_client")
    def test_returns_open_bets(self, mock_get_client):
        from lib.queries import get_active_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        bets = [
            {"id": 1, "player_name": "Scottie Scheffler", "outcome": None},
            {"id": 2, "player_name": "Rory McIlroy", "outcome": None},
        ]
        _setup_query_chain(client, bets)

        result = get_active_bets.__wrapped__()
        assert len(result) == 2

    @patch("lib.queries.get_client")
    def test_filters_by_tournament_id(self, mock_get_client):
        from lib.queries import get_active_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [])

        get_active_bets.__wrapped__(tournament_id="abc-123")
        chain.eq.assert_called_with("tournament_id", "abc-123")

    @patch("lib.queries.get_client")
    def test_returns_empty_list_when_no_bets(self, mock_get_client):
        from lib.queries import get_active_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        _setup_query_chain(client, [])

        result = get_active_bets.__wrapped__()
        assert result == []

    @patch("lib.queries.get_client")
    def test_returned_dicts_contain_display_columns(self, mock_get_client):
        from lib.queries import get_active_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        bet = {
            "id": 1, "tournament_id": "t1", "player_name": "Scottie",
            "opponent_name": "Rory", "market_type": "matchup", "book": "DK",
            "odds_at_bet_american": "+110", "odds_at_bet_decimal": 2.1,
            "stake": 25, "edge": 0.05, "clv": 0.03, "bet_timestamp": "2026-04-02",
            "implied_prob_at_bet": 0.476, "your_prob": 0.55,
        }
        _setup_query_chain(client, [bet])

        result = get_active_bets.__wrapped__()
        required = ["player_name", "market_type", "book", "odds_at_bet_american",
                     "odds_at_bet_decimal", "stake", "edge", "clv"]
        for col in required:
            assert col in result[0]

    @patch("lib.queries.get_client")
    def test_selects_explicit_columns(self, mock_get_client):
        from lib.queries import get_active_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = _setup_query_chain(client, [])

        get_active_bets.__wrapped__()
        select_arg = chain.select.call_args[0][0]
        assert select_arg != "*"
        assert "player_name" in select_arg


# --- get_weekly_pnl ---

class TestGetWeeklyPnl:
    @patch("lib.queries.get_client")
    def test_computes_settled_pnl(self, mock_get_client):
        from lib.queries import get_weekly_pnl

        client = _make_mock_client()
        mock_get_client.return_value = client
        bets = [
            {"id": 1, "stake": 25, "pnl": 27.5, "outcome": "win"},
            {"id": 2, "stake": 20, "pnl": -20.0, "outcome": "loss"},
            {"id": 3, "stake": 15, "pnl": None, "outcome": None},
        ]
        _setup_query_chain(client, bets)

        result = get_weekly_pnl.__wrapped__("t1")
        assert result["settled_pnl"] == pytest.approx(7.5)

    @patch("lib.queries.get_client")
    def test_computes_unsettled_stake(self, mock_get_client):
        from lib.queries import get_weekly_pnl

        client = _make_mock_client()
        mock_get_client.return_value = client
        bets = [
            {"id": 1, "stake": 25, "pnl": 27.5, "outcome": "win"},
            {"id": 3, "stake": 15, "pnl": None, "outcome": None},
        ]
        _setup_query_chain(client, bets)

        result = get_weekly_pnl.__wrapped__("t1")
        assert result["unsettled_stake"] == pytest.approx(15.0)

    @patch("lib.queries.get_client")
    def test_computes_net_position(self, mock_get_client):
        from lib.queries import get_weekly_pnl

        client = _make_mock_client()
        mock_get_client.return_value = client
        bets = [
            {"id": 1, "stake": 25, "pnl": 27.5, "outcome": "win"},
            {"id": 2, "stake": 20, "pnl": -20.0, "outcome": "loss"},
            {"id": 3, "stake": 15, "pnl": None, "outcome": None},
        ]
        _setup_query_chain(client, bets)

        result = get_weekly_pnl.__wrapped__("t1")
        assert result["net_position"] == pytest.approx(7.5 - 15.0)

    @patch("lib.queries.get_client")
    def test_all_open_bets(self, mock_get_client):
        from lib.queries import get_weekly_pnl

        client = _make_mock_client()
        mock_get_client.return_value = client
        bets = [
            {"id": 1, "stake": 25, "pnl": None, "outcome": None},
            {"id": 2, "stake": 15, "pnl": None, "outcome": None},
        ]
        _setup_query_chain(client, bets)

        result = get_weekly_pnl.__wrapped__("t1")
        assert result["settled_pnl"] == 0.0
        assert result["unsettled_stake"] == pytest.approx(40.0)

    @patch("lib.queries.get_client")
    def test_all_settled_bets(self, mock_get_client):
        from lib.queries import get_weekly_pnl

        client = _make_mock_client()
        mock_get_client.return_value = client
        bets = [
            {"id": 1, "stake": 25, "pnl": 27.5, "outcome": "win"},
            {"id": 2, "stake": 20, "pnl": -20.0, "outcome": "loss"},
        ]
        _setup_query_chain(client, bets)

        result = get_weekly_pnl.__wrapped__("t1")
        assert result["unsettled_stake"] == 0.0
        assert result["settled_pnl"] == pytest.approx(7.5)


# --- error handling ---

class TestErrorHandling:
    @patch("lib.queries.get_client")
    def test_query_raises_on_supabase_failure(self, mock_get_client):
        from lib.queries import get_active_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        chain = client.table.return_value
        chain.select.return_value = chain
        chain.is_.return_value = chain
        chain.order.return_value = chain
        chain.execute.side_effect = Exception("Supabase error")

        with pytest.raises(Exception, match="Supabase error"):
            get_active_bets.__wrapped__()

    @patch("lib.queries.get_client")
    def test_results_are_serializable(self, mock_get_client):
        from lib.queries import get_active_bets

        client = _make_mock_client()
        mock_get_client.return_value = client
        _setup_query_chain(client, [{"id": 1, "player_name": "Test"}])

        result = get_active_bets.__wrapped__()
        assert isinstance(result, list)
        assert isinstance(result[0], dict)
