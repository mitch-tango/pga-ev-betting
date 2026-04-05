"""Tests for Polymarket tournament matching and player name extraction."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.polymarket_matching import (
    extract_player_name,
    match_all_market_types,
    match_tournament,
    resolve_polymarket_player,
)


# ── Fixtures / helpers ──────────────────────────────────────────────

def _make_event(
    title: str = "PGA Tour: The Masters Winner",
    start_date: str = "2026-04-09T00:00:00Z",
    end_date: str = "2026-04-13T00:00:00Z",
    slug: str = "pga-tour-the-masters-winner",
    markets: list | None = None,
) -> dict:
    return {
        "title": title,
        "startDate": start_date,
        "endDate": end_date,
        "slug": slug,
        "markets": markets or [],
    }


def _make_market(
    slug: str = "pga-tour-the-masters-winner-scottie-scheffler",
    question: str = "Will Scottie Scheffler win the Masters?",
    outcome: str = "Yes",
    tokens: list | None = None,
) -> dict:
    return {
        "slug": slug,
        "question": question,
        "outcome": outcome,
        "groupItemTitle": "Scottie Scheffler",
        "tokens": tokens or [{"token_id": "0x123", "outcome": "Yes"}],
    }


# ── TestTournamentMatching ──────────────────────────────────────────

class TestTournamentMatching:
    """match_tournament: date range overlap + fuzzy name + PGA check."""

    def test_match_by_date_range_overlap(self):
        """Event overlapping tournament dates should match."""
        event = _make_event(
            start_date="2026-04-09T00:00:00Z",
            end_date="2026-04-13T00:00:00Z",
        )
        result = match_tournament(
            [event], "The Masters", "2026-04-09", "2026-04-13",
        )
        assert result is not None
        assert result["slug"] == event["slug"]

    def test_reject_outside_date_range(self):
        """Event fully outside tournament dates should not match."""
        event = _make_event(
            title="PGA Tour: Players Championship Winner",
            start_date="2026-03-10T00:00:00Z",
            end_date="2026-03-14T00:00:00Z",
            slug="pga-tour-players-championship-winner",
        )
        result = match_tournament(
            [event], "The Masters", "2026-04-09", "2026-04-13",
        )
        assert result is None

    def test_match_by_fuzzy_name(self):
        """Fuzzy name match ≥0.85 should match even with date mismatch."""
        # Dates don't overlap, but name is close enough
        event = _make_event(
            title="PGA Tour: The Masters Winner",
            start_date="2026-04-08T00:00:00Z",
            end_date="2026-04-08T00:00:00Z",  # ends before tournament
        )
        # Use a tournament name very similar to the event title
        result = match_tournament(
            [event], "The Masters", "2026-04-09", "2026-04-13",
        )
        # Should still match via fuzzy name
        assert result is not None

    def test_reject_similar_but_wrong_event(self):
        """'US Open' vs 'US Women's Open' should not match (below 0.85)."""
        event = _make_event(
            title="PGA Tour: US Women's Open Winner",
            start_date="2026-06-01T00:00:00Z",
            end_date="2026-06-05T00:00:00Z",
        )
        result = match_tournament(
            [event], "US Open", "2026-06-12", "2026-06-15",
        )
        assert result is None

    def test_exclude_non_pga_tours(self):
        """LIV, DPWT, LPGA, Korn Ferry events should be excluded."""
        non_pga = [
            _make_event(title="LIV Golf: Portland Winner", start_date="2026-04-09T00:00:00Z", end_date="2026-04-13T00:00:00Z"),
            _make_event(title="DPWT: BMW Championship Winner", start_date="2026-04-09T00:00:00Z", end_date="2026-04-13T00:00:00Z"),
            _make_event(title="LPGA: Chevron Championship Winner", start_date="2026-04-09T00:00:00Z", end_date="2026-04-13T00:00:00Z"),
            _make_event(title="Korn Ferry Tour: Boise Open Winner", start_date="2026-04-09T00:00:00Z", end_date="2026-04-13T00:00:00Z"),
        ]
        for event in non_pga:
            result = match_tournament(
                [event], "The Masters", "2026-04-09", "2026-04-13",
            )
            assert result is None, f"Should exclude: {event['title']}"

    def test_prefers_best_name_among_overlapping_dates(self):
        """When multiple events overlap in dates, prefer the best name match."""
        wrong = _make_event(
            title="Arnold Palmer Invitational Winner",
            start_date="2026-04-09T00:00:00Z",
            end_date="2026-04-13T00:00:00Z",
            slug="arnold-palmer-invitational-winner",
        )
        correct = _make_event(
            title="PGA Tour: The Masters Winner",
            start_date="2026-04-09T00:00:00Z",
            end_date="2026-04-13T00:00:00Z",
            slug="pga-tour-the-masters-winner",
        )
        # Put the wrong event first to confirm name-preference wins
        result = match_tournament(
            [wrong, correct], "The Masters", "2026-04-09", "2026-04-13",
        )
        assert result is not None
        assert result["slug"] == "pga-tour-the-masters-winner"

    def test_accepts_non_excluded_non_pga_titled_event(self):
        """Events without 'PGA' in title should still match if not excluded."""
        event = _make_event(
            title="Arnold Palmer Invitational Winner",
            start_date="2026-03-06T00:00:00Z",
            end_date="2026-03-09T00:00:00Z",
            slug="arnold-palmer-invitational-winner",
        )
        result = match_tournament(
            [event], "Arnold Palmer Invitational", "2026-03-06", "2026-03-09",
        )
        assert result is not None

    def test_handles_date_only_format(self):
        """Events with date-only strings (no T/Z) should parse fine."""
        event = _make_event(
            start_date="2026-04-09",
            end_date="2026-04-13",
        )
        result = match_tournament(
            [event], "The Masters", "2026-04-09", "2026-04-13",
        )
        assert result is not None


# ── TestMatchAllMarketTypes ─────────────────────────────────────────

class TestMatchAllMarketTypes:

    def test_returns_matched_events_for_all_types(self):
        """Should return matched events keyed by market type."""
        win_event = _make_event(title="PGA Tour: The Masters Winner")
        t10_event = _make_event(title="PGA Tour: The Masters Top 10")
        t20_event = _make_event(title="PGA Tour: The Masters Top 20")

        client = MagicMock()
        client.get_golf_events.side_effect = lambda market_type_filter=None: {
            "winner": [win_event],
            "top-10": [t10_event],
            "top-20": [t20_event],
        }.get(market_type_filter, [])

        result = match_all_market_types(
            client, "The Masters", "2026-04-09", "2026-04-13",
        )
        assert "win" in result
        assert "t10" in result
        assert "t20" in result

    def test_sparse_dict_when_some_types_missing(self):
        """Missing types should just be absent from result dict."""
        win_event = _make_event(title="PGA Tour: The Masters Winner")

        client = MagicMock()
        client.get_golf_events.side_effect = lambda market_type_filter=None: {
            "winner": [win_event],
        }.get(market_type_filter, [])

        result = match_all_market_types(
            client, "The Masters", "2026-04-09", "2026-04-13",
        )
        assert "win" in result
        assert "t10" not in result
        assert "t20" not in result

    def test_handles_complete_miss(self):
        """No golf events → empty dict."""
        client = MagicMock()
        client.get_golf_events.return_value = []

        result = match_all_market_types(
            client, "The Masters", "2026-04-09", "2026-04-13",
        )
        assert result == {}


# ── TestPlayerNameExtraction ────────────────────────────────────────

class TestPlayerNameExtraction:

    def test_extracts_from_slug(self):
        """'pga-tour-the-masters-winner-scottie-scheffler' → 'Scottie Scheffler'."""
        market = _make_market(
            slug="pga-tour-the-masters-winner-scottie-scheffler",
        )
        name = extract_player_name(market, event_slug="pga-tour-the-masters-winner")
        assert name == "Scottie Scheffler"

    def test_extracts_from_question_regex(self):
        """Falls back to question regex when slug doesn't help."""
        market = _make_market(
            slug="",
            question="Will Rory McIlroy win the Masters?",
        )
        market["groupItemTitle"] = ""  # Clear so we test question path
        name = extract_player_name(market, event_slug="")
        assert name == "Rory McIlroy"

    def test_handles_special_characters(self):
        """McIlroy, DeChambeau should preserve casing from slug."""
        market = _make_market(
            slug="pga-tour-masters-rory-mcilroy",
        )
        market["groupItemTitle"] = ""  # Clear so we test slug path
        name = extract_player_name(market, event_slug="pga-tour-masters")
        assert name is not None
        assert "mcilroy" in name.lower()

    def test_applies_nfc_normalization(self):
        """Unicode combining chars should be NFC normalized."""
        # Å can be either single char or A + combining ring
        market = _make_market(
            slug="pga-tour-masters-ludvig-a\u030aberg",
            question="Will Ludvig Åberg win?",
        )
        name = extract_player_name(market, event_slug="pga-tour-masters")
        assert name is not None
        # NFC form: the combining sequence should be normalized
        import unicodedata
        assert name == unicodedata.normalize("NFC", name)

    def test_returns_none_on_unparseable(self):
        """Totally unparseable market should return None."""
        market = {"slug": "", "question": "", "outcome": "Yes"}
        name = extract_player_name(market, event_slug="")
        assert name is None

    def test_extracts_from_group_item_title(self):
        """groupItemTitle is a reliable fallback."""
        market = _make_market(
            slug="some-generic-slug",
            question="Some weird question format",
        )
        market["groupItemTitle"] = "Scottie Scheffler"
        name = extract_player_name(market, event_slug="some-event")
        assert name == "Scottie Scheffler"


# ── TestPlayerNameResolution ────────────────────────────────────────

class TestPlayerNameResolution:

    @patch("src.pipeline.polymarket_matching.resolve_player")
    def test_delegates_to_resolve_player(self, mock_resolve):
        """Should call resolve_player with source='polymarket'."""
        mock_resolve.return_value = {"id": 1, "canonical_name": "Scottie Scheffler"}
        result = resolve_polymarket_player("Scottie Scheffler", auto_create=True)
        mock_resolve.assert_called_once_with(
            "Scottie Scheffler", source="polymarket", auto_create=True,
        )
        assert result["canonical_name"] == "Scottie Scheffler"
