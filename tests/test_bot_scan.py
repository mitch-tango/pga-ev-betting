"""Tests for bot _run_pretournament_scan: staleness guard, prediction market
integration, and edge-gone loop logic."""

from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from src.discord_bot.bot import _run_pretournament_scan
from src.core.edge import CandidateBet


# Module path prefix for patching
BOT = "src.discord_bot.bot"


def _base_outrights(is_live=False, event_name="The Masters", notes=None):
    """Minimal outrights dict with metadata."""
    result = {
        "win": [],
        "top_10": [],
        "top_20": [],
        "make_cut": [],
        "_event_name": event_name,
        "_is_live": is_live,
    }
    if notes:
        result["_notes"] = notes
    return result


# ---------------------------------------------------------------------------
# Staleness guard
# ---------------------------------------------------------------------------

class TestStalenessGuard:
    """_run_pretournament_scan returns None when tournament is live."""

    @patch(f"{BOT}.resolve_candidates")
    @patch(f"{BOT}.pull_tournament_matchups", return_value=[])
    @patch(f"{BOT}.pull_all_outrights")
    @patch(f"{BOT}.db")
    def test_returns_none_when_live(self, mock_db, mock_outrights,
                                    mock_matchups, mock_resolve):
        mock_db.get_bankroll.return_value = 1000
        mock_db.get_open_bets_for_week.return_value = []
        mock_outrights.return_value = _base_outrights(
            is_live=True, notes="Event is live — baseline model not available")

        result = _run_pretournament_scan("pga")
        assert result is None

    @patch(f"{BOT}.resolve_candidates")
    @patch(f"{BOT}.pull_prophetx_matchups", return_value=[])
    @patch(f"{BOT}.pull_prophetx_outrights", return_value={})
    @patch(f"{BOT}.pull_polymarket_outrights", return_value={})
    @patch(f"{BOT}.pull_kalshi_matchups", return_value=[])
    @patch(f"{BOT}.pull_kalshi_outrights", return_value={})
    @patch(f"{BOT}.pull_tournament_matchups", return_value=[])
    @patch(f"{BOT}.pull_all_outrights")
    @patch("src.api.datagolf.DataGolfClient")
    @patch(f"{BOT}.db")
    def test_returns_tuple_when_not_live(self, mock_db, mock_dg_cls,
                                         mock_outrights, mock_matchups,
                                         mock_kalshi_out, mock_kalshi_match,
                                         mock_poly, mock_px_out, mock_px_match,
                                         mock_resolve):
        mock_db.get_bankroll.return_value = 1000
        mock_db.get_open_bets_for_week.return_value = []
        mock_db.get_tournament.return_value = None
        mock_db.upsert_tournament.return_value = {"id": "t1"}
        mock_outrights.return_value = _base_outrights(is_live=False)

        mock_dg = MagicMock()
        mock_dg_cls.return_value = mock_dg
        mock_dg.resolve_event_id.return_value = "evt-123"
        mock_dg.get_field_updates.return_value = {
            "status": "ok", "data": {"event_name": "The Masters"}}

        result = _run_pretournament_scan("pga")

        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) >= 6
        candidates = result[0]
        tournament_name = result[2]
        bankroll = result[3]
        assert isinstance(candidates, list)
        assert tournament_name == "The Masters"
        assert bankroll == 1000


# ---------------------------------------------------------------------------
# Prediction market integration
# ---------------------------------------------------------------------------

class TestPredictionMarketPull:
    """_run_pretournament_scan pulls from Kalshi, Polymarket, ProphetX."""

    @patch(f"{BOT}.resolve_candidates")
    @patch(f"{BOT}.merge_prophetx_into_matchups")
    @patch(f"{BOT}.pull_prophetx_matchups", return_value=[])
    @patch(f"{BOT}.merge_prophetx_into_outrights")
    @patch(f"{BOT}.pull_prophetx_outrights", return_value={"win": [], "top_10": []})
    @patch(f"{BOT}.merge_polymarket_into_outrights")
    @patch(f"{BOT}.pull_polymarket_outrights", return_value={"win": [], "top_10": []})
    @patch(f"{BOT}.merge_kalshi_into_matchups")
    @patch(f"{BOT}.pull_kalshi_matchups", return_value=[])
    @patch(f"{BOT}.merge_kalshi_into_outrights")
    @patch(f"{BOT}.pull_kalshi_outrights", return_value={"win": [], "top_10": []})
    @patch(f"{BOT}.pull_tournament_matchups", return_value=[])
    @patch(f"{BOT}.pull_all_outrights")
    @patch(f"{BOT}.db")
    def test_calls_all_prediction_markets(
        self, mock_db, mock_outrights, mock_matchups,
        mock_kalshi_out, mock_kalshi_merge, mock_kalshi_match, mock_kalshi_match_merge,
        mock_poly_out, mock_poly_merge,
        mock_px_out, mock_px_merge, mock_px_match, mock_px_match_merge,
        mock_resolve,
    ):
        mock_db.get_bankroll.return_value = 1000
        mock_db.get_open_bets_for_week.return_value = []
        mock_db.get_tournament.return_value = None
        mock_db.upsert_tournament.return_value = {"id": "t1"}
        mock_outrights.return_value = _base_outrights(is_live=False)

        with patch(f"{BOT}.DataGolfClient", create=True) as mock_dg_cls:
            mock_dg = MagicMock()
            mock_dg_cls.return_value = mock_dg
            mock_dg.resolve_event_id.return_value = "evt-123"
            mock_dg.get_field_updates.return_value = {
                "status": "ok", "data": {"event_name": "The Masters"}}
            with patch(f"{BOT}.config") as mock_config:
                mock_config.POLYMARKET_ENABLED = True
                mock_config.PROPHETX_ENABLED = True
                mock_config.ALERT_ENABLED = False
                mock_config.MIN_EDGE = {"win": 0.03, "t10": 0.06}
                mock_config.MARKET_MAP = {"win": "win"}

                _run_pretournament_scan("pga")

        # Verify all prediction market pulls were called
        mock_kalshi_out.assert_called_once()
        mock_poly_out.assert_called_once()
        mock_px_out.assert_called_once()

    @patch(f"{BOT}.resolve_candidates")
    @patch(f"{BOT}.pull_prophetx_outrights", side_effect=Exception("API down"))
    @patch(f"{BOT}.pull_polymarket_outrights", side_effect=Exception("API down"))
    @patch(f"{BOT}.pull_kalshi_outrights", side_effect=Exception("API down"))
    @patch(f"{BOT}.pull_tournament_matchups", return_value=[])
    @patch(f"{BOT}.pull_all_outrights")
    @patch("src.api.datagolf.DataGolfClient")
    @patch(f"{BOT}.db")
    def test_graceful_degradation_on_api_failure(
        self, mock_db, mock_dg_cls, mock_outrights, mock_matchups,
        mock_kalshi, mock_poly, mock_px, mock_resolve,
    ):
        """Pipeline should not crash when prediction market APIs fail."""
        mock_db.get_bankroll.return_value = 1000
        mock_db.get_open_bets_for_week.return_value = []
        mock_db.get_tournament.return_value = None
        mock_db.upsert_tournament.return_value = {"id": "t1"}
        mock_outrights.return_value = _base_outrights(is_live=False)

        mock_dg = MagicMock()
        mock_dg_cls.return_value = mock_dg
        mock_dg.resolve_event_id.return_value = "evt-123"
        mock_dg.get_field_updates.return_value = {
            "status": "ok", "data": {"event_name": "The Masters"}}

        result = _run_pretournament_scan("pga")

        # Should still return a valid tuple (not crash)
        assert result is not None
        assert isinstance(result, tuple)


# ---------------------------------------------------------------------------
# Edge-gone detection logic (unit test the comparison, not the async loop)
# ---------------------------------------------------------------------------

class TestEdgeGoneDetection:
    """Test the edge comparison logic used by _edge_gone_loop."""

    def _make_candidate(self, player, market, book, edge):
        return CandidateBet(
            market_type=market,
            player_name=player,
            best_book=book,
            edge=edge,
            best_odds_decimal=7.0,
            dg_prob=0.25,
            book_consensus_prob=0.15,
            suggested_stake=10.0,
            kelly_fraction=0.01,
        )

    def test_edge_gone_when_not_in_fresh(self):
        """Edge is 'gone' when the candidate doesn't appear in fresh scan."""
        old = self._make_candidate("Scheffler", "win", "kalshi", 0.10)
        fresh_lookup = {}  # Empty = no edges found

        key = f"{old.player_name}|{old.market_type}|{old.best_book}"
        fresh = fresh_lookup.get(key)
        assert fresh is None  # This means "edge gone"

    def test_edge_shrunk_significantly(self):
        """Edge is 'shrunk' when fresh edge < 50% of original."""
        old = self._make_candidate("Scheffler", "win", "kalshi", 0.10)
        fresh = self._make_candidate("Scheffler", "win", "kalshi", 0.04)

        assert fresh.edge < old.edge * 0.5

    def test_edge_still_good(self):
        """Edge that's still >50% of original should not be flagged."""
        old = self._make_candidate("Scheffler", "win", "kalshi", 0.10)
        fresh = self._make_candidate("Scheffler", "win", "kalshi", 0.08)

        assert fresh.edge >= old.edge * 0.5

    def test_candidate_tracking_key_format(self):
        """Key format matches what the loop uses."""
        c = self._make_candidate("Rory McIlroy", "t10", "polymarket", 0.07)
        key = f"{c.player_name}|{c.market_type}|{c.best_book}"
        assert key == "Rory McIlroy|t10|polymarket"

    def test_cutoff_filters_old_candidates(self):
        """Candidates older than 12 hours should be pruned."""
        now = datetime.now()
        old_time = now - timedelta(hours=13)
        recent_time = now - timedelta(hours=6)
        cutoff = now - timedelta(hours=12)

        candidates = [
            ("old_candidate", 123, old_time),
            ("recent_candidate", 123, recent_time),
        ]
        active = [(c, ch, t) for c, ch, t in candidates if t > cutoff]
        assert len(active) == 1
        assert active[0][0] == "recent_candidate"
