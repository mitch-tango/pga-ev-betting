"""Tests for ProphetX tournament matching, market classification, and player extraction."""

from __future__ import annotations

import unicodedata
from unittest.mock import patch

import pytest

from src.pipeline.prophetx_matching import (
    classify_markets,
    extract_player_name_outright,
    extract_player_names_matchup,
    match_tournament,
    resolve_prophetx_player,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_event(
    name: str = "PGA Tour: The Masters",
    start_date: str = "2026-04-09T00:00:00Z",
    end_date: str = "2026-04-13T00:00:00Z",
    event_id: str = "evt_123",
) -> dict:
    return {
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "id": event_id,
    }


def _make_market(
    market_type: str = "moneyline",
    sub_type: str = "outrights",
    name: str = "Masters Winner",
    competitors: list | None = None,
) -> dict:
    return {
        "market_type": market_type,
        "sub_type": sub_type,
        "name": name,
        "competitors": competitors or [{"competitor_name": "Scottie Scheffler"}],
    }


# ── TestTournamentMatching ──────────────────────────────────────────

class TestTournamentMatching:

    def test_matches_by_date_range_overlap(self):
        event = _make_event(start_date="2026-04-09T00:00:00Z", end_date="2026-04-13T00:00:00Z")
        result = match_tournament([event], "The Masters", "2026-04-09", "2026-04-13")
        assert result is not None
        assert result["id"] == "evt_123"

    def test_rejects_outside_date_range(self):
        event = _make_event(
            name="PGA Tour: Players Championship",
            start_date="2026-03-10T00:00:00Z",
            end_date="2026-03-14T00:00:00Z",
        )
        result = match_tournament([event], "The Masters", "2026-04-09", "2026-04-13")
        assert result is None

    def test_fuzzy_name_match(self):
        event = _make_event(
            name="PGA Tour: The Masters Tournament",
            start_date="2026-04-08T00:00:00Z",
            end_date="2026-04-08T00:00:00Z",  # No date overlap
        )
        result = match_tournament([event], "The Masters", "2026-04-09", "2026-04-13")
        assert result is not None

    def test_tries_multiple_date_fields(self):
        """ProphetX may use startDate instead of start_date."""
        event = {
            "name": "PGA Tour: The Masters",
            "startDate": "2026-04-09T00:00:00Z",
            "endDate": "2026-04-13T00:00:00Z",
            "id": "evt_alt",
        }
        result = match_tournament([event], "The Masters", "2026-04-09", "2026-04-13")
        assert result is not None

    def test_tries_multiple_title_fields(self):
        """ProphetX may use 'title' instead of 'name'."""
        event = {
            "title": "PGA Tour: The Masters",
            "start_date": "2026-04-09T00:00:00Z",
            "end_date": "2026-04-13T00:00:00Z",
            "id": "evt_title",
        }
        result = match_tournament([event], "The Masters", "2026-04-09", "2026-04-13")
        assert result is not None

    def test_excludes_non_pga_tours(self):
        non_pga = [
            _make_event(name="LIV Golf Portland"),
            _make_event(name="DPWT BMW Championship"),
            _make_event(name="LPGA Chevron Championship"),
            _make_event(name="Korn Ferry Tour Boise Open"),
        ]
        for event in non_pga:
            result = match_tournament([event], "The Masters", "2026-04-09", "2026-04-13")
            assert result is None, f"Should exclude: {event['name']}"


# ── TestClassifyMarkets ─────────────────────────────────────────────

class TestClassifyMarkets:

    def test_identifies_outright_winner(self):
        market = _make_market(market_type="moneyline", sub_type="outrights", name="Masters Winner")
        result = classify_markets([market])
        assert "win" in result
        assert len(result["win"]) == 1

    def test_identifies_h2h_matchup(self):
        market = _make_market(
            market_type="moneyline",
            sub_type="matchup",
            name="Scheffler vs McIlroy",
            competitors=[
                {"competitor_name": "Scottie Scheffler"},
                {"competitor_name": "Rory McIlroy"},
            ],
        )
        result = classify_markets([market])
        assert "matchup" in result

    def test_identifies_make_cut(self):
        market = _make_market(name="Will Scottie Scheffler make the cut?", market_type="prop", sub_type="")
        result = classify_markets([market])
        assert "make_cut" in result

    def test_discovers_t10_t20(self):
        t10 = _make_market(name="Masters Top 10", market_type="moneyline", sub_type="top 10")
        t20 = _make_market(name="Masters Top 20", market_type="moneyline", sub_type="top 20")
        result = classify_markets([t10, t20])
        assert "t10" in result
        assert "t20" in result

    def test_returns_sparse_dict(self):
        """Only found types should be in result."""
        market = _make_market(market_type="moneyline", sub_type="outrights")
        result = classify_markets([market])
        assert "win" in result
        assert "matchup" not in result
        assert "make_cut" not in result


# ── TestPlayerNameExtraction ────────────────────────────────────────

class TestPlayerNameExtraction:

    def test_extracts_from_competitor_name(self):
        market = _make_market(competitors=[{"competitor_name": "Scottie Scheffler"}])
        name = extract_player_name_outright(market)
        assert name == "Scottie Scheffler"

    def test_tries_multiple_field_names(self):
        """Should find name in 'participant' or 'player' fields."""
        market = _make_market(competitors=[{"participant": "Rory McIlroy"}])
        name = extract_player_name_outright(market)
        assert name == "Rory McIlroy"

    def test_returns_none_when_no_name(self):
        market = _make_market(competitors=[{"unknown_field": "???"}])
        name = extract_player_name_outright(market)
        assert name is None

    def test_extracts_both_matchup_names(self):
        market = _make_market(competitors=[
            {"competitor_name": "Scottie Scheffler"},
            {"competitor_name": "Rory McIlroy"},
        ])
        result = extract_player_names_matchup(market)
        assert result == ("Scottie Scheffler", "Rory McIlroy")

    def test_nfc_normalized(self):
        market = _make_market(competitors=[{"competitor_name": "Ludvig A\u030aberg"}])
        name = extract_player_name_outright(market)
        assert name is not None
        assert name == unicodedata.normalize("NFC", name)

    def test_matchup_requires_two_competitors(self):
        market = _make_market(competitors=[{"competitor_name": "Scottie Scheffler"}])
        result = extract_player_names_matchup(market)
        assert result is None


# ── TestPlayerNameResolution ────────────────────────────────────────

class TestPlayerNameResolution:

    @patch("src.pipeline.prophetx_matching.resolve_player")
    def test_delegates_to_resolve_player(self, mock_resolve):
        mock_resolve.return_value = {"id": 1, "canonical_name": "Scottie Scheffler"}
        result = resolve_prophetx_player("Scottie Scheffler", auto_create=True)
        mock_resolve.assert_called_once_with(
            "Scottie Scheffler", source="prophetx", auto_create=True,
        )
        assert result["canonical_name"] == "Scottie Scheffler"
