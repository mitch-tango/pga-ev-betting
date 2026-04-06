"""Tests for post-tournament performance summary."""

from unittest.mock import patch, MagicMock
from datetime import datetime

from src.discord_bot.bot import _build_tournament_summary

BOT = "src.discord_bot.bot"


def _make_bet(market_type="win", book="draftkings", stake=50, pnl=25,
              outcome="win", edge=0.06, clv=0.03):
    return {
        "id": "bet-1",
        "tournament_id": "t-1",
        "market_type": market_type,
        "player_name": "Scottie Scheffler",
        "book": book,
        "stake": stake,
        "pnl": pnl,
        "outcome": outcome,
        "edge": edge,
        "clv": clv,
        "odds_at_bet_decimal": 7.0,
    }


class TestBuildTournamentSummary:

    @patch(f"{BOT}.db")
    def test_returns_none_when_no_bets(self, mock_db):
        mock_db.get_bets_for_tournament.return_value = []
        assert _build_tournament_summary("t-1") is None

    @patch(f"{BOT}.db")
    def test_returns_none_when_not_fully_settled(self, mock_db):
        bets = [_make_bet(), _make_bet(outcome=None)]
        mock_db.get_bets_for_tournament.return_value = bets
        assert _build_tournament_summary("t-1") is None

    @patch(f"{BOT}.db")
    def test_returns_embed_when_fully_settled(self, mock_db):
        bets = [
            _make_bet(pnl=50, outcome="win"),
            _make_bet(pnl=-30, outcome="loss", market_type="t10", book="kalshi"),
        ]
        mock_db.get_bets_for_tournament.return_value = bets
        mock_db.get_tournament_by_id.return_value = {"tournament_name": "The Masters"}
        mock_db.get_bankroll.return_value = 1200.0
        mock_db.get_roi_by_market.return_value = [
            {"total_bets": 20, "total_staked": 1000, "total_pnl": 150},
        ]

        embed = _build_tournament_summary("t-1")
        assert embed is not None
        assert "The Masters" in embed.title
        # Green for positive P&L
        assert embed.color.value == 0x2ECC71

    @patch(f"{BOT}.db")
    def test_red_color_for_negative_pnl(self, mock_db):
        bets = [_make_bet(pnl=-50, outcome="loss")]
        mock_db.get_bets_for_tournament.return_value = bets
        mock_db.get_tournament_by_id.return_value = {"tournament_name": "Valero"}
        mock_db.get_bankroll.return_value = 900.0
        mock_db.get_roi_by_market.return_value = []

        embed = _build_tournament_summary("t-1")
        assert embed is not None
        assert embed.color.value == 0xE74C3C

    @patch(f"{BOT}.db")
    def test_embed_has_expected_fields(self, mock_db):
        bets = [
            _make_bet(pnl=100, outcome="win", market_type="win", book="draftkings"),
            _make_bet(pnl=-20, outcome="loss", market_type="t10", book="kalshi"),
            _make_bet(pnl=0, outcome="push", market_type="win", book="draftkings"),
        ]
        mock_db.get_bets_for_tournament.return_value = bets
        mock_db.get_tournament_by_id.return_value = {"tournament_name": "The Masters"}
        mock_db.get_bankroll.return_value = 1500.0
        mock_db.get_roi_by_market.return_value = [
            {"total_bets": 50, "total_staked": 2500, "total_pnl": 300},
        ]

        embed = _build_tournament_summary("t-1")
        field_names = [f.name for f in embed.fields]
        assert "P&L" in field_names
        assert "ROI" in field_names
        assert "Record" in field_names
        assert "By Market" in field_names
        assert "By Book" in field_names
        assert "Edge Calibration" in field_names

    @patch(f"{BOT}.db")
    def test_record_includes_pushes(self, mock_db):
        bets = [
            _make_bet(pnl=50, outcome="win"),
            _make_bet(pnl=0, outcome="push"),
        ]
        mock_db.get_bets_for_tournament.return_value = bets
        mock_db.get_tournament_by_id.return_value = {"tournament_name": "Test"}
        mock_db.get_bankroll.return_value = 1000.0
        mock_db.get_roi_by_market.return_value = []

        embed = _build_tournament_summary("t-1")
        record_field = next(f for f in embed.fields if f.name == "Record")
        assert "1-0-1" in record_field.value

    @patch(f"{BOT}.db")
    def test_season_footer(self, mock_db):
        bets = [_make_bet(pnl=50, outcome="win")]
        mock_db.get_bets_for_tournament.return_value = bets
        mock_db.get_tournament_by_id.return_value = {"tournament_name": "Test"}
        mock_db.get_bankroll.return_value = 1500.0
        mock_db.get_roi_by_market.return_value = [
            {"total_bets": 30, "total_staked": 1500, "total_pnl": 200},
        ]

        embed = _build_tournament_summary("t-1")
        assert "Season: 30 bets" in embed.footer.text
        assert "Bankroll:" in embed.footer.text


class TestDuplicatePrevention:
    """_summary_posted_for prevents duplicate posts."""

    def test_set_starts_empty(self):
        from src.discord_bot.bot import EVBot
        bot = EVBot()
        assert len(bot._summary_posted_for) == 0

    def test_adding_to_set_prevents_repost(self):
        from src.discord_bot.bot import EVBot
        bot = EVBot()
        bot._summary_posted_for.add("t-1")
        assert "t-1" in bot._summary_posted_for
        assert "t-2" not in bot._summary_posted_for
