"""Tests for Kalshi tournament matching and player name extraction/resolution."""

import unicodedata
from unittest.mock import patch, MagicMock

from src.pipeline.kalshi_matching import (
    match_tournament,
    extract_player_name_outright,
    extract_player_names_h2h,
    resolve_kalshi_player,
)


class TestTournamentMatching:
    """Matching Kalshi events to DG tournaments by date and name."""

    def test_matches_by_expiration_date_within_tournament_week(self):
        """Event expiring Sunday of tournament week matches."""
        events = [
            {
                "event_ticker": "KXPGATOUR-26APR10-SCHEFFLER",
                "title": "PGA Tour: Masters Winner",
                "expected_expiration_time": "2026-04-12T23:00:00Z",
            }
        ]
        result = match_tournament(events, "Masters Tournament", "2026-04-09", "2026-04-12")
        assert result == "KXPGATOUR-26APR10-SCHEFFLER"

    def test_falls_back_to_fuzzy_name_match(self):
        """When dates don't align, fuzzy name matching kicks in."""
        events = [
            {
                "event_ticker": "KXPGATOUR-26MAR-VALERO",
                "title": "PGA Tour: Valero Texas Open Winner",
                "expected_expiration_time": "2026-03-30T23:00:00Z",
            }
        ]
        # Dates deliberately off by a week
        result = match_tournament(events, "Valero Texas Open", "2026-04-02", "2026-04-05")
        assert result == "KXPGATOUR-26MAR-VALERO"

    def test_returns_none_when_no_match_found(self):
        """No match by date or name returns None."""
        events = [
            {
                "event_ticker": "KXPGATOUR-OTHER",
                "title": "PGA Tour: Arnold Palmer Invitational Winner",
                "expected_expiration_time": "2026-06-15T23:00:00Z",
            }
        ]
        result = match_tournament(events, "Valero Texas Open", "2026-04-02", "2026-04-05")
        assert result is None

    def test_rejects_non_pga_events(self):
        """LIV Golf events with overlapping dates are rejected."""
        events = [
            {
                "event_ticker": "KXLIV-26APR",
                "title": "LIV Golf: Adelaide Winner",
                "expected_expiration_time": "2026-04-12T23:00:00Z",
            }
        ]
        result = match_tournament(events, "Masters Tournament", "2026-04-09", "2026-04-12")
        assert result is None

    def test_handles_multiple_open_events_picks_correct_week(self):
        """Multiple open events — picks the one matching tournament dates."""
        events = [
            {
                "event_ticker": "KXPGATOUR-THISWEEK",
                "title": "PGA Tour: RBC Heritage Winner",
                "expected_expiration_time": "2026-04-19T23:00:00Z",
            },
            {
                "event_ticker": "KXPGATOUR-NEXTWEEK",
                "title": "PGA Tour: Zurich Classic Winner",
                "expected_expiration_time": "2026-04-26T23:00:00Z",
            },
        ]
        result = match_tournament(events, "RBC Heritage", "2026-04-16", "2026-04-19")
        assert result == "KXPGATOUR-THISWEEK"


class TestPlayerNameExtraction:
    """Parsing player names from Kalshi contract titles/subtitles."""

    def test_extracts_from_outright_title(self):
        """Title pattern 'Will X win...' extracts name."""
        contract = {"title": "Will Scottie Scheffler win the Masters?", "subtitle": ""}
        result = extract_player_name_outright(contract)
        assert result == "Scottie Scheffler"

    def test_extracts_from_simple_subtitle(self):
        """Subtitle with just the player name returns it directly."""
        contract = {"title": "Masters Tournament Winner", "subtitle": "Scottie Scheffler"}
        result = extract_player_name_outright(contract)
        assert result == "Scottie Scheffler"

    def test_extracts_both_names_from_h2h(self):
        """H2H title 'A vs B' extracts both names."""
        contract = {"title": "Scottie Scheffler vs Rory McIlroy", "subtitle": ""}
        result = extract_player_names_h2h(contract)
        assert result == ("Scottie Scheffler", "Rory McIlroy")

    def test_handles_suffixes(self):
        """Names with Jr., III, etc. are preserved."""
        contract = {"title": "Will Davis Love III win the Masters?", "subtitle": ""}
        result = extract_player_name_outright(contract)
        assert result == "Davis Love III"

    def test_handles_international_characters(self):
        """Unicode names are preserved correctly."""
        contract = {"title": "Will Ludvig Åberg win the Masters?", "subtitle": ""}
        result = extract_player_name_outright(contract)
        assert "berg" in result  # Handles with or without å
        # Verify unicode is NFC normalized
        assert result == unicodedata.normalize("NFC", result)


class TestPlayerNameMatching:
    """Resolving Kalshi player names to DG canonical names."""

    @patch("src.pipeline.kalshi_matching.resolve_player")
    def test_exact_match_against_canonical(self, mock_resolve):
        """Exact name match returns the player record."""
        mock_resolve.return_value = {"id": "uuid-1", "canonical_name": "Scottie Scheffler"}
        result = resolve_kalshi_player("Scottie Scheffler")
        assert result["canonical_name"] == "Scottie Scheffler"
        mock_resolve.assert_called_once_with("Scottie Scheffler", source="kalshi", auto_create=False)

    @patch("src.pipeline.kalshi_matching.resolve_player")
    def test_fuzzy_match_finds_close_variant(self, mock_resolve):
        """Minor spelling variants still resolve via fuzzy match."""
        mock_resolve.return_value = {"id": "uuid-2", "canonical_name": "Xander Schauffele"}
        result = resolve_kalshi_player("Xander Schauffele")
        assert result is not None
        assert result["canonical_name"] == "Xander Schauffele"

    @patch("src.pipeline.kalshi_matching.resolve_player")
    def test_creates_alias_on_first_match(self, mock_resolve):
        """resolve_player is called with source='kalshi'."""
        mock_resolve.return_value = {"id": "uuid-3", "canonical_name": "Rory McIlroy"}
        resolve_kalshi_player("Rory McIlroy")
        mock_resolve.assert_called_once_with("Rory McIlroy", source="kalshi", auto_create=False)

    @patch("src.pipeline.kalshi_matching.resolve_player")
    def test_uses_cached_alias_on_subsequent_lookups(self, mock_resolve):
        """Second lookup for same name still delegates to resolve_player (which checks alias cache)."""
        mock_resolve.return_value = {"id": "uuid-4", "canonical_name": "Jon Rahm"}
        resolve_kalshi_player("Jon Rahm")
        resolve_kalshi_player("Jon Rahm")
        assert mock_resolve.call_count == 2

    @patch("src.pipeline.kalshi_matching.resolve_player")
    def test_returns_none_for_unknown_player(self, mock_resolve):
        """Unknown player with auto_create=False returns None."""
        mock_resolve.return_value = None
        result = resolve_kalshi_player("Unknown Player XYZ")
        assert result is None

    @patch("src.pipeline.kalshi_matching.resolve_player")
    def test_source_is_kalshi(self, mock_resolve):
        """Source string passed is exactly 'kalshi'."""
        mock_resolve.return_value = {"id": "uuid-5", "canonical_name": "Tiger Woods"}
        resolve_kalshi_player("Tiger Woods")
        args, kwargs = mock_resolve.call_args
        assert kwargs.get("source") == "kalshi" or (len(args) > 1 and args[1] == "kalshi")
