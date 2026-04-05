"""Tests for Polymarket pipeline pull and merge (outrights only)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.pull_polymarket import (
    merge_polymarket_into_outrights,
    pull_polymarket_outrights,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_polymarket_market(
    question: str = "Will Scottie Scheffler win the Masters?",
    slug: str = "pga-tour-masters-scottie-scheffler",
    outcomes: str = '["Yes","No"]',
    clob_token_ids: str = '["0xYES","0xNO"]',
    outcome_prices: str = '["0.30","0.70"]',
    volume: float = 5000.0,
    group_item_title: str = "Scottie Scheffler",
) -> dict:
    return {
        "question": question,
        "slug": slug,
        "outcomes": outcomes,
        "clobTokenIds": clob_token_ids,
        "outcomePrices": outcome_prices,
        "volume": volume,
        "groupItemTitle": group_item_title,
    }


def _make_event_with_markets(markets: list[dict]) -> dict:
    return {
        "title": "PGA Tour: The Masters Winner",
        "startDate": "2026-04-09T00:00:00Z",
        "endDate": "2026-04-13T00:00:00Z",
        "slug": "pga-tour-masters",
        "markets": markets,
    }


def _make_orderbook(best_bid: float = 0.28, best_ask: float = 0.32) -> dict:
    """Build a simple orderbook with one bid and one ask."""
    bids = [{"price": str(best_bid), "size": "100"}] if best_bid > 0 else []
    asks = [{"price": str(best_ask), "size": "100"}] if best_ask < 1.0 else []
    return {"bids": bids, "asks": asks}


# ── TestPullPolymarketOutrights ─────────────────────────────────────

class TestPullPolymarketOutrights:

    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
    @patch("src.pipeline.pull_polymarket.extract_player_name")
    @patch("src.pipeline.pull_polymarket.match_all_market_types")
    @patch("src.pipeline.pull_polymarket.PolymarketClient")
    def test_returns_market_type_dict(self, MockClient, mock_match, mock_extract, mock_resolve):
        """Should return dict with win, t10, t20 keys."""
        market = _make_polymarket_market()
        event = _make_event_with_markets([market])
        mock_match.return_value = {"win": event}

        client = MockClient.return_value
        client.get_books.return_value = {"0xYES": _make_orderbook(0.28, 0.32)}

        mock_extract.return_value = "Scottie Scheffler"
        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}

        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
        assert "win" in result
        assert len(result["win"]) == 1

    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
    @patch("src.pipeline.pull_polymarket.extract_player_name")
    @patch("src.pipeline.pull_polymarket.match_all_market_types")
    @patch("src.pipeline.pull_polymarket.PolymarketClient")
    def test_player_entry_fields(self, MockClient, mock_match, mock_extract, mock_resolve):
        """Each entry should have player_name, polymarket_mid_prob, polymarket_ask_prob, volume."""
        market = _make_polymarket_market(volume=5000.0)
        event = _make_event_with_markets([market])
        mock_match.return_value = {"win": event}

        client = MockClient.return_value
        client.get_books.return_value = {"0xYES": _make_orderbook(0.28, 0.32)}

        mock_extract.return_value = "Scottie Scheffler"
        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}

        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
        entry = result["win"][0]
        assert "player_name" in entry
        assert "polymarket_mid_prob" in entry
        assert "polymarket_ask_prob" in entry
        assert "volume" in entry
        assert entry["player_name"] == "Scottie Scheffler"

    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
    @patch("src.pipeline.pull_polymarket.extract_player_name")
    @patch("src.pipeline.pull_polymarket.match_all_market_types")
    @patch("src.pipeline.pull_polymarket.PolymarketClient")
    def test_yes_token_identified_by_outcome_label(self, MockClient, mock_match, mock_extract, mock_resolve):
        """YES token found via outcomes array, not assumed index 0."""
        # Swap order: No first, Yes second
        market = _make_polymarket_market(
            outcomes='["No","Yes"]',
            clob_token_ids='["0xNO","0xYES"]',
            outcome_prices='["0.70","0.30"]',
        )
        event = _make_event_with_markets([market])
        mock_match.return_value = {"win": event}

        client = MockClient.return_value
        # Only provide book for 0xYES
        client.get_books.return_value = {"0xYES": _make_orderbook(0.28, 0.32)}

        mock_extract.return_value = "Scottie Scheffler"
        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}

        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
        assert len(result["win"]) == 1

    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
    @patch("src.pipeline.pull_polymarket.extract_player_name")
    @patch("src.pipeline.pull_polymarket.match_all_market_types")
    @patch("src.pipeline.pull_polymarket.PolymarketClient")
    def test_skips_when_yes_token_not_found(self, MockClient, mock_match, mock_extract, mock_resolve):
        """Market with no 'Yes' outcome should be skipped."""
        market = _make_polymarket_market(
            outcomes='["Up","Down"]',
            clob_token_ids='["0xUP","0xDOWN"]',
        )
        event = _make_event_with_markets([market])
        mock_match.return_value = {"win": event}

        client = MockClient.return_value
        client.get_books.return_value = {}

        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
        assert result.get("win", []) == []

    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
    @patch("src.pipeline.pull_polymarket.extract_player_name")
    @patch("src.pipeline.pull_polymarket.match_all_market_types")
    @patch("src.pipeline.pull_polymarket.PolymarketClient")
    def test_skips_empty_bids(self, MockClient, mock_match, mock_extract, mock_resolve):
        """No bids (one-sided book) → skip player."""
        market = _make_polymarket_market()
        event = _make_event_with_markets([market])
        mock_match.return_value = {"win": event}

        client = MockClient.return_value
        client.get_books.return_value = {"0xYES": {"bids": [], "asks": [{"price": "0.32", "size": "100"}]}}

        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
        assert result.get("win", []) == []

    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
    @patch("src.pipeline.pull_polymarket.extract_player_name")
    @patch("src.pipeline.pull_polymarket.match_all_market_types")
    @patch("src.pipeline.pull_polymarket.PolymarketClient")
    def test_skips_empty_asks(self, MockClient, mock_match, mock_extract, mock_resolve):
        """No asks (one-sided book) → skip player."""
        market = _make_polymarket_market()
        event = _make_event_with_markets([market])
        mock_match.return_value = {"win": event}

        client = MockClient.return_value
        client.get_books.return_value = {"0xYES": {"bids": [{"price": "0.28", "size": "100"}], "asks": []}}

        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
        assert result.get("win", []) == []

    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
    @patch("src.pipeline.pull_polymarket.extract_player_name")
    @patch("src.pipeline.pull_polymarket.match_all_market_types")
    @patch("src.pipeline.pull_polymarket.PolymarketClient")
    def test_skips_both_sides_empty(self, MockClient, mock_match, mock_extract, mock_resolve):
        """Both bids and asks empty → skip player."""
        market = _make_polymarket_market()
        event = _make_event_with_markets([market])
        mock_match.return_value = {"win": event}

        client = MockClient.return_value
        client.get_books.return_value = {"0xYES": {"bids": [], "asks": []}}

        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
        assert result.get("win", []) == []

    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
    @patch("src.pipeline.pull_polymarket.extract_player_name")
    @patch("src.pipeline.pull_polymarket.match_all_market_types")
    @patch("src.pipeline.pull_polymarket.PolymarketClient")
    def test_relative_spread_filter(self, MockClient, mock_match, mock_extract, mock_resolve):
        """spread > max(abs_max, rel_factor * mid) → skip."""
        market = _make_polymarket_market()
        event = _make_event_with_markets([market])
        mock_match.return_value = {"win": event}

        client = MockClient.return_value
        # Wide spread: bid=0.10, ask=0.50 → spread=0.40, mid=0.30
        # max(0.10, 0.15*0.30) = max(0.10, 0.045) = 0.10
        # 0.40 > 0.10 → filtered
        client.get_books.return_value = {"0xYES": _make_orderbook(0.10, 0.50)}

        mock_extract.return_value = "Scottie Scheffler"
        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}

        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
        assert result.get("win", []) == []

    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
    @patch("src.pipeline.pull_polymarket.extract_player_name")
    @patch("src.pipeline.pull_polymarket.match_all_market_types")
    @patch("src.pipeline.pull_polymarket.PolymarketClient")
    def test_volume_filter(self, MockClient, mock_match, mock_extract, mock_resolve):
        """Markets below MIN_VOLUME should be skipped."""
        market = _make_polymarket_market(volume=50.0)  # Below 100
        event = _make_event_with_markets([market])
        mock_match.return_value = {"win": event}

        client = MockClient.return_value
        client.get_books.return_value = {"0xYES": _make_orderbook(0.28, 0.32)}

        mock_extract.return_value = "Scottie Scheffler"
        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}

        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
        assert result.get("win", []) == []

    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
    @patch("src.pipeline.pull_polymarket.extract_player_name")
    @patch("src.pipeline.pull_polymarket.match_all_market_types")
    @patch("src.pipeline.pull_polymarket.PolymarketClient")
    def test_fee_adjusted_ask(self, MockClient, mock_match, mock_extract, mock_resolve):
        """polymarket_ask_prob = ask + POLYMARKET_FEE_RATE."""
        market = _make_polymarket_market()
        event = _make_event_with_markets([market])
        mock_match.return_value = {"win": event}

        client = MockClient.return_value
        client.get_books.return_value = {"0xYES": _make_orderbook(0.28, 0.32)}

        mock_extract.return_value = "Scottie Scheffler"
        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}

        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
        entry = result["win"][0]
        # ask=0.32, fee=0.002 → adjusted=0.322
        assert entry["polymarket_ask_prob"] == pytest.approx(0.322)

    @patch("src.pipeline.pull_polymarket.match_all_market_types")
    @patch("src.pipeline.pull_polymarket.PolymarketClient")
    def test_returns_empty_on_no_match(self, MockClient, mock_match):
        """No tournament match → empty dict."""
        mock_match.return_value = {}

        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
        assert result == {}


# ── TestMergePolymarketIntoOutrights ────────────────────────────────

class TestMergePolymarketIntoOutrights:

    def test_adds_polymarket_odds_key(self):
        """Merge adds 'polymarket' American odds key."""
        dg = {"win": [{"player_name": "Scottie Scheffler"}]}
        poly = {"win": [{"player_name": "Scottie Scheffler", "polymarket_mid_prob": 0.30, "polymarket_ask_prob": 0.322, "volume": 5000}]}

        result = merge_polymarket_into_outrights(dg, poly)
        assert "polymarket" in result["win"][0]

    def test_adds_ask_prob_key(self):
        """Merge adds '_polymarket_ask_prob' float."""
        dg = {"win": [{"player_name": "Scottie Scheffler"}]}
        poly = {"win": [{"player_name": "Scottie Scheffler", "polymarket_mid_prob": 0.30, "polymarket_ask_prob": 0.322, "volume": 5000}]}

        result = merge_polymarket_into_outrights(dg, poly)
        assert result["win"][0]["_polymarket_ask_prob"] == pytest.approx(0.322)

    def test_skips_unmatched_dg_players(self):
        """DG players not in Polymarket should be unchanged."""
        dg = {"win": [
            {"player_name": "Scottie Scheffler"},
            {"player_name": "Jon Rahm"},
        ]}
        poly = {"win": [{"player_name": "Scottie Scheffler", "polymarket_mid_prob": 0.30, "polymarket_ask_prob": 0.322, "volume": 5000}]}

        result = merge_polymarket_into_outrights(dg, poly)
        assert "polymarket" in result["win"][0]
        assert "polymarket" not in result["win"][1]

    def test_case_insensitive_matching(self):
        """Name matching should be case-insensitive."""
        dg = {"win": [{"player_name": "scottie scheffler"}]}
        poly = {"win": [{"player_name": "Scottie Scheffler", "polymarket_mid_prob": 0.30, "polymarket_ask_prob": 0.322, "volume": 5000}]}

        result = merge_polymarket_into_outrights(dg, poly)
        assert "polymarket" in result["win"][0]

    def test_uses_binary_price_to_american(self):
        """Odds should be converted via binary_price_to_american."""
        dg = {"win": [{"player_name": "Scottie Scheffler"}]}
        poly = {"win": [{"player_name": "Scottie Scheffler", "polymarket_mid_prob": 0.30, "polymarket_ask_prob": 0.322, "volume": 5000}]}

        result = merge_polymarket_into_outrights(dg, poly)
        odds = result["win"][0]["polymarket"]
        # 0.30 prob → +233 (approx)
        assert odds.startswith("+")

    def test_existing_books_not_modified(self):
        """Existing book columns should be untouched."""
        dg = {"win": [{"player_name": "Scottie Scheffler", "draftkings": "+300", "fanduel": "+280"}]}
        poly = {"win": [{"player_name": "Scottie Scheffler", "polymarket_mid_prob": 0.30, "polymarket_ask_prob": 0.322, "volume": 5000}]}

        result = merge_polymarket_into_outrights(dg, poly)
        assert result["win"][0]["draftkings"] == "+300"
        assert result["win"][0]["fanduel"] == "+280"


# ── TestNoMatchupPull ───────────────────────────────────────────────

class TestNoMatchupPull:

    def test_no_matchup_function(self):
        """pull_polymarket_matchups should not exist."""
        import src.pipeline.pull_polymarket as mod
        assert not hasattr(mod, "pull_polymarket_matchups")
