"""Tests for ProphetX odds pull & merge (section 09)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.pull_prophetx import (
    _detect_odds_format,
    merge_prophetx_into_matchups,
    merge_prophetx_into_outrights,
    pull_prophetx_matchups,
    pull_prophetx_outrights,
)


# ── Odds format detection ───────────────────────────────────────────


class TestDetectOddsFormat:
    def test_american_int_positive(self):
        markets = [{"odds": 400}]
        assert _detect_odds_format(markets, "odds") == "american"

    def test_american_int_negative(self):
        markets = [{"odds": -150}]
        assert _detect_odds_format(markets, "odds") == "american"

    def test_american_string_positive(self):
        markets = [{"odds": "+400"}]
        assert _detect_odds_format(markets, "odds") == "american"

    def test_american_string_negative(self):
        markets = [{"odds": "-150"}]
        assert _detect_odds_format(markets, "odds") == "american"

    def test_binary_float(self):
        markets = [{"odds": 0.55}]
        assert _detect_odds_format(markets, "odds") == "binary"

    def test_binary_small_float(self):
        markets = [{"odds": 0.02}]
        assert _detect_odds_format(markets, "odds") == "binary"

    def test_empty_markets(self):
        assert _detect_odds_format([], "odds") == "binary"  # default

    def test_missing_key(self):
        markets = [{"other": 123}]
        assert _detect_odds_format(markets, "odds") == "binary"


# ── Helpers: fake data builders ──────────────────────────────────────


def _make_competitor(name, odds=0.25, oi=200, bid=0.23, ask=0.27):
    """Legacy competitor format for matchup tests."""
    return {
        "competitor_name": name,
        "odds": odds,
        "open_interest": oi,
        "bid": bid,
        "ask": ask,
    }


def _make_outright_market(player_name, odds=600, total_stake=500):
    """Build a ProphetX outright market in the real orderbook format.

    Each market is one player with selections = [[YES levels], [NO levels]].
    """
    return {
        "name": player_name,
        "type": "moneyline",
        "status": "active",
        "totalStake": total_stake,
        "outcomes": [{"id": 1, "name": "YES"}, {"id": 2, "name": "NO"}],
        "selections": [
            [{"id": 1, "name": "YES", "odds": odds, "displayOdds": f"+{odds}",
              "value": 100, "stake": total_stake}],
            None,
        ],
    }


def _make_market(market_type, sub_type, name, competitors):
    """Legacy market format for matchup tests."""
    return {
        "market_type": market_type,
        "sub_type": sub_type,
        "name": name,
        "competitors": competitors,
    }


def _make_event(title, start, end, event_id="evt-1"):
    return {
        "name": title,
        "start_date": start,
        "end_date": end,
        "id": event_id,
    }


# ── pull_prophetx_outrights ─────────────────────────────────────────


class TestPullProphetxOutrights:
    @patch("src.pipeline.pull_prophetx.ProphetXClient")
    @patch("src.pipeline.pull_prophetx.match_tournament")
    @patch("src.pipeline.pull_prophetx.classify_markets")
    @patch("src.pipeline.pull_prophetx.resolve_prophetx_player")
    def test_american_format_outrights(
        self, mock_resolve, mock_classify, mock_match, mock_client_cls,
    ):
        """American format via orderbook: returns mid_prob and American string."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        event = _make_event("The Masters", "2026-04-09", "2026-04-12")
        mock_match.return_value = event

        win_market = _make_outright_market("Scottie Scheffler", odds=600)
        mock_client.get_markets_for_events.return_value = [win_market]
        mock_classify.return_value = {"win": [win_market]}
        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}

        result = pull_prophetx_outrights("The Masters", "2026-04-09", "2026-04-12")

        assert "win" in result
        assert len(result["win"]) == 1
        player = result["win"][0]
        assert player["player_name"] == "Scottie Scheffler"
        assert player["odds_format"] == "american"
        assert "prophetx_american" in player
        assert "prophetx_mid_prob" in player

    @patch("src.pipeline.pull_prophetx.ProphetXClient")
    @patch("src.pipeline.pull_prophetx.match_tournament")
    @patch("src.pipeline.pull_prophetx.classify_markets")
    @patch("src.pipeline.pull_prophetx.resolve_prophetx_player")
    def test_multiple_players(
        self, mock_resolve, mock_classify, mock_match, mock_client_cls,
    ):
        """Multiple outright markets produce multiple players."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        event = _make_event("The Masters", "2026-04-09", "2026-04-12")
        mock_match.return_value = event

        m1 = _make_outright_market("Rory McIlroy", odds=1350)
        m2 = _make_outright_market("Jon Rahm", odds=1150)
        mock_client.get_markets_for_events.return_value = [m1, m2]
        mock_classify.return_value = {"win": [m1, m2]}
        mock_resolve.side_effect = [
            {"canonical_name": "Rory McIlroy"},
            {"canonical_name": "Jon Rahm"},
        ]

        result = pull_prophetx_outrights("The Masters", "2026-04-09", "2026-04-12")

        assert "win" in result
        assert len(result["win"]) == 2

    @patch("src.pipeline.pull_prophetx.ProphetXClient")
    @patch("src.pipeline.pull_prophetx.match_tournament")
    def test_no_tournament_match(self, mock_match, mock_client_cls):
        mock_client_cls.return_value = MagicMock()
        mock_match.return_value = None

        result = pull_prophetx_outrights("Fake Event", "2026-01-01", "2026-01-04")
        assert result == {}

    @patch("src.pipeline.pull_prophetx.ProphetXClient")
    @patch("src.pipeline.pull_prophetx.match_tournament")
    @patch("src.pipeline.pull_prophetx.classify_markets")
    @patch("src.pipeline.pull_prophetx.resolve_prophetx_player")
    def test_filters_low_stake(
        self, mock_resolve, mock_classify, mock_match, mock_client_cls,
    ):
        """Markets below totalStake threshold are filtered out."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        event = _make_event("The Masters", "2026-04-09", "2026-04-12")
        mock_match.return_value = event

        win_market = _make_outright_market("Low Stake Player", odds=600, total_stake=5)
        mock_client.get_markets_for_events.return_value = [win_market]
        mock_classify.return_value = {"win": [win_market]}
        mock_resolve.return_value = {"canonical_name": "Low Stake Player"}

        result = pull_prophetx_outrights("The Masters", "2026-04-09", "2026-04-12")
        assert result == {} or len(result.get("win", [])) == 0

    @patch("src.pipeline.pull_prophetx.ProphetXClient")
    @patch("src.pipeline.pull_prophetx.match_tournament")
    @patch("src.pipeline.pull_prophetx.classify_markets")
    @patch("src.pipeline.pull_prophetx.resolve_prophetx_player")
    def test_skips_market_without_selections(
        self, mock_resolve, mock_classify, mock_match, mock_client_cls,
    ):
        """Markets with no orderbook levels are skipped."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        event = _make_event("The Masters", "2026-04-09", "2026-04-12")
        mock_match.return_value = event

        win_market = {
            "name": "Inactive Player",
            "type": "moneyline",
            "status": "inactive",
            "totalStake": 0,
            "outcomes": [{"id": 1, "name": "YES"}, {"id": 2, "name": "NO"}],
            "selections": [None, None],
        }
        mock_client.get_markets_for_events.return_value = [win_market]
        mock_classify.return_value = {"win": [win_market]}
        mock_resolve.return_value = {"canonical_name": "Inactive Player"}

        result = pull_prophetx_outrights("The Masters", "2026-04-09", "2026-04-12")
        assert result == {} or len(result.get("win", [])) == 0


# ── pull_prophetx_matchups ──────────────────────────────────────────


class TestPullProphetxMatchups:
    @patch("src.pipeline.pull_prophetx.ProphetXClient")
    @patch("src.pipeline.pull_prophetx.match_tournament")
    @patch("src.pipeline.pull_prophetx.classify_markets")
    @patch("src.pipeline.pull_prophetx.resolve_prophetx_player")
    def test_matchup_extraction(
        self, mock_resolve, mock_classify, mock_match, mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        event = _make_event("The Masters", "2026-04-09", "2026-04-12")
        mock_match.return_value = event

        competitors = [
            _make_competitor("Player A", odds=0.55),
            _make_competitor("Player B", odds=0.45),
        ]
        matchup_market = _make_market("moneyline", "matchup", "A vs B", competitors)
        mock_client.get_markets_for_events.return_value = [matchup_market]
        mock_classify.return_value = {"matchup": [matchup_market]}
        mock_resolve.side_effect = [
            {"canonical_name": "Player A"},
            {"canonical_name": "Player B"},
        ]

        result = pull_prophetx_matchups("The Masters", "2026-04-09", "2026-04-12")

        assert len(result) == 1
        m = result[0]
        assert m["p1_name"] == "Player A"
        assert m["p2_name"] == "Player B"
        assert "p1_prob" in m
        assert "p2_prob" in m

    @patch("src.pipeline.pull_prophetx.ProphetXClient")
    @patch("src.pipeline.pull_prophetx.match_tournament")
    @patch("src.pipeline.pull_prophetx.classify_markets")
    @patch("src.pipeline.pull_prophetx.resolve_prophetx_player")
    def test_matchup_american_odds(
        self, mock_resolve, mock_classify, mock_match, mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        event = _make_event("The Masters", "2026-04-09", "2026-04-12")
        mock_match.return_value = event

        competitors = [
            _make_competitor("Player A", odds=-150),
            _make_competitor("Player B", odds=130),
        ]
        matchup_market = _make_market("moneyline", "matchup", "A vs B", competitors)
        mock_client.get_markets_for_events.return_value = [matchup_market]
        mock_classify.return_value = {"matchup": [matchup_market]}
        mock_resolve.side_effect = [
            {"canonical_name": "Player A"},
            {"canonical_name": "Player B"},
        ]

        result = pull_prophetx_matchups("The Masters", "2026-04-09", "2026-04-12")

        assert len(result) == 1
        m = result[0]
        assert "p1_prob" in m
        assert "p2_prob" in m


# ── merge_prophetx_into_outrights ───────────────────────────────────


class TestMergeProphetxIntoOutrights:
    def test_adds_american_odds(self):
        dg = {"win": [{"player_name": "Scottie Scheffler"}]}
        prophetx = {"win": [{
            "player_name": "Scottie Scheffler",
            "prophetx_mid_prob": 0.20,
            "prophetx_american": "+400",
            "odds_format": "american",
        }]}

        result = merge_prophetx_into_outrights(dg, prophetx)
        player = result["win"][0]
        assert player["prophetx"] == "+400"

    def test_adds_ask_prob_for_binary(self):
        dg = {"win": [{"player_name": "Rory McIlroy"}]}
        prophetx = {"win": [{
            "player_name": "Rory McIlroy",
            "prophetx_mid_prob": 0.22,
            "prophetx_ask_prob": 0.25,
            "odds_format": "binary",
        }]}

        result = merge_prophetx_into_outrights(dg, prophetx)
        player = result["win"][0]
        assert "_prophetx_ask_prob" in player
        assert player["_prophetx_ask_prob"] == 0.25

    def test_no_ask_prob_for_american(self):
        dg = {"win": [{"player_name": "Jon Rahm"}]}
        prophetx = {"win": [{
            "player_name": "Jon Rahm",
            "prophetx_mid_prob": 0.20,
            "prophetx_american": "+400",
            "odds_format": "american",
        }]}

        result = merge_prophetx_into_outrights(dg, prophetx)
        player = result["win"][0]
        assert "_prophetx_ask_prob" not in player

    def test_skips_unmatched_dg_players(self):
        dg = {"win": [
            {"player_name": "Scottie Scheffler"},
            {"player_name": "Unknown Player"},
        ]}
        prophetx = {"win": [{
            "player_name": "Scottie Scheffler",
            "prophetx_mid_prob": 0.20,
            "prophetx_american": "+400",
            "odds_format": "american",
        }]}

        result = merge_prophetx_into_outrights(dg, prophetx)
        assert "prophetx" in result["win"][0]
        assert "prophetx" not in result["win"][1]

    def test_case_insensitive_matching(self):
        dg = {"win": [{"player_name": "SCOTTIE SCHEFFLER"}]}
        prophetx = {"win": [{
            "player_name": "scottie scheffler",
            "prophetx_mid_prob": 0.20,
            "prophetx_american": "+400",
            "odds_format": "american",
        }]}

        result = merge_prophetx_into_outrights(dg, prophetx)
        assert "prophetx" in result["win"][0]


# ── merge_prophetx_into_matchups ────────────────────────────────────


class TestMergeProphetxIntoMatchups:
    def test_frozenset_matching(self):
        """Order-independent matching via frozenset."""
        dg = [
            {
                "p1_player_name": "Player A",
                "p2_player_name": "Player B",
                "odds": {"draftkings": {"p1": "-110", "p2": "+100"}},
            },
        ]
        prophetx = [{
            "p1_name": "Player B",
            "p2_name": "Player A",
            "p1_prob": 0.45,
            "p2_prob": 0.55,
        }]

        result = merge_prophetx_into_matchups(dg, prophetx)
        odds = result[0]["odds"]["prophetx"]
        # Player A is DG's p1, but ProphetX has them as p2
        # So p1 odds should correspond to Player A's prob (0.55)
        assert "p1" in odds
        assert "p2" in odds

    def test_adds_prophetx_odds(self):
        dg = [
            {
                "p1_player_name": "Player A",
                "p2_player_name": "Player B",
                "odds": {},
            },
        ]
        prophetx = [{
            "p1_name": "Player A",
            "p2_name": "Player B",
            "p1_prob": 0.55,
            "p2_prob": 0.45,
        }]

        result = merge_prophetx_into_matchups(dg, prophetx)
        assert "prophetx" in result[0]["odds"]
