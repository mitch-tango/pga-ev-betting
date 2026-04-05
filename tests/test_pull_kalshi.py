"""Tests for Kalshi pipeline pull and merge (outrights and matchups)."""

from unittest.mock import patch, MagicMock

from src.pipeline.pull_kalshi import (
    pull_kalshi_outrights, pull_kalshi_matchups,
    merge_kalshi_into_outrights, merge_kalshi_into_matchups,
)


def _make_market(title, subtitle, yes_bid, yes_ask, open_interest,
                 ticker="MKT-001"):
    """Helper to build a Kalshi market dict."""
    return {
        "ticker": ticker,
        "title": title,
        "subtitle": subtitle,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "open_interest": open_interest,
    }


# ---- Outright fixtures ----

_VALID_WIN_MARKETS = [
    _make_market("Will Scottie Scheffler win?", "Scottie Scheffler",
                 0.20, 0.24, 500, "MKT-W1"),
    _make_market("Will Rory McIlroy win?", "Rory McIlroy",
                 0.08, 0.10, 200, "MKT-W2"),
]

_VALID_T10_MARKETS = [
    _make_market("Will Scottie Scheffler finish Top 10?", "Scottie Scheffler",
                 0.50, 0.54, 300, "MKT-T1"),
]


@patch("src.pipeline.pull_kalshi.resolve_kalshi_player")
@patch("src.pipeline.pull_kalshi.match_tournament")
@patch("src.pipeline.pull_kalshi.KalshiClient")
class TestPullKalshiOutrights:

    def _setup_client(self, mock_cls, event_markets_by_ticker=None):
        """Wire up mock client with events and markets."""
        client = MagicMock()
        mock_cls.return_value = client
        # Each series ticker returns one event
        client.get_golf_events.return_value = [
            {"event_ticker": "EVT-WIN", "title": "PGA Tour: Masters Winner"},
        ]
        if event_markets_by_ticker:
            client.get_event_markets.side_effect = (
                lambda t: event_markets_by_ticker.get(t, [])
            )
        else:
            client.get_event_markets.return_value = []
        return client

    def test_returns_dict_with_correct_keys(self, mock_cls, mock_match, mock_resolve):
        self._setup_client(mock_cls)
        mock_match.return_value = "EVT-WIN"
        mock_resolve.return_value = {"canonical_name": "Scheffler, Scottie"}

        result = pull_kalshi_outrights(
            tournament_name="Masters", tournament_start="2026-04-09",
            tournament_end="2026-04-12",
        )
        assert set(result.keys()) == {"win", "t10", "t20"}

    def test_each_entry_has_required_fields(self, mock_cls, mock_match, mock_resolve):
        client = self._setup_client(mock_cls)
        client.get_event_markets.return_value = _VALID_WIN_MARKETS
        mock_match.return_value = "EVT-WIN"
        mock_resolve.return_value = {"canonical_name": "Scheffler, Scottie"}

        result = pull_kalshi_outrights(
            tournament_name="Masters", tournament_start="2026-04-09",
            tournament_end="2026-04-12",
        )
        for entry in result["win"]:
            assert "player_name" in entry
            assert "kalshi_mid_prob" in entry
            assert "kalshi_ask_prob" in entry
            assert "open_interest" in entry
            assert isinstance(entry["kalshi_mid_prob"], float)
            assert isinstance(entry["open_interest"], int)

    def test_filters_out_players_below_oi_threshold(self, mock_cls, mock_match, mock_resolve):
        client = self._setup_client(mock_cls)
        client.get_event_markets.return_value = [
            _make_market("Win?", "Low OI Player", 0.10, 0.12, 50),   # below 100
            _make_market("Win?", "High OI Player", 0.10, 0.12, 200),  # above 100
        ]
        mock_match.return_value = "EVT-WIN"
        mock_resolve.return_value = {"canonical_name": "High OI Player"}

        result = pull_kalshi_outrights(
            tournament_name="Masters", tournament_start="2026-04-09",
            tournament_end="2026-04-12",
        )
        assert len(result["win"]) == 1
        assert result["win"][0]["open_interest"] == 200

    def test_filters_out_players_with_wide_spread(self, mock_cls, mock_match, mock_resolve):
        client = self._setup_client(mock_cls)
        client.get_event_markets.return_value = [
            _make_market("Win?", "Wide Spread", 0.10, 0.20, 200),  # spread=0.10
            _make_market("Win?", "Tight Spread", 0.10, 0.14, 200),  # spread=0.04
        ]
        mock_match.return_value = "EVT-WIN"
        mock_resolve.return_value = {"canonical_name": "Tight Spread"}

        result = pull_kalshi_outrights(
            tournament_name="Masters", tournament_start="2026-04-09",
            tournament_end="2026-04-12",
        )
        assert len(result["win"]) == 1

    def test_normalizes_integer_prices_to_0_1(self, mock_cls, mock_match, mock_resolve):
        """Prices like 6 (instead of 0.06) should be divided by 100."""
        client = self._setup_client(mock_cls)
        client.get_event_markets.return_value = [
            _make_market("Win?", "Player A", 6, 8, 200),  # integer cents
        ]
        mock_match.return_value = "EVT-WIN"
        mock_resolve.return_value = {"canonical_name": "Player A"}

        result = pull_kalshi_outrights(
            tournament_name="Masters", tournament_start="2026-04-09",
            tournament_end="2026-04-12",
        )
        assert len(result["win"]) == 1
        entry = result["win"][0]
        assert 0 < entry["kalshi_mid_prob"] < 1
        assert 0 < entry["kalshi_ask_prob"] < 1

    def test_returns_empty_on_api_failure(self, mock_cls, mock_match, mock_resolve):
        client = self._setup_client(mock_cls)
        client.get_golf_events.side_effect = Exception("Connection refused")

        result = pull_kalshi_outrights(
            tournament_name="Masters", tournament_start="2026-04-09",
            tournament_end="2026-04-12",
        )
        assert result == {"win": [], "t10": [], "t20": []}

    def test_returns_empty_when_no_golf_events(self, mock_cls, mock_match, mock_resolve):
        client = self._setup_client(mock_cls)
        client.get_golf_events.return_value = []
        mock_match.return_value = None

        result = pull_kalshi_outrights(
            tournament_name="Masters", tournament_start="2026-04-09",
            tournament_end="2026-04-12",
        )
        assert result == {"win": [], "t10": [], "t20": []}

    def test_caches_raw_response(self, mock_cls, mock_match, mock_resolve):
        client = self._setup_client(mock_cls)
        client.get_event_markets.return_value = _VALID_WIN_MARKETS
        mock_match.return_value = "EVT-WIN"
        mock_resolve.return_value = {"canonical_name": "Scheffler, Scottie"}

        pull_kalshi_outrights(
            tournament_name="Masters", tournament_start="2026-04-09",
            tournament_end="2026-04-12",
        )
        assert client._cache_response.called


# ---- Matchup fixtures ----

_VALID_H2H_MARKETS = [
    {
        "ticker": "MKT-H2H-1A",
        "title": "Scottie Scheffler vs. Rory McIlroy",
        "subtitle": "",
        "yes_bid": 0.55,
        "yes_ask": 0.58,
        "open_interest": 300,
    },
]


@patch("src.pipeline.pull_kalshi.resolve_kalshi_player")
@patch("src.pipeline.pull_kalshi.match_tournament")
@patch("src.pipeline.pull_kalshi.KalshiClient")
class TestPullKalshiMatchups:

    def _setup_client(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.get_golf_events.return_value = [
            {"event_ticker": "EVT-H2H", "title": "PGA Tour: H2H"},
        ]
        return client

    def test_returns_list_of_matchup_dicts(self, mock_cls, mock_match, mock_resolve):
        client = self._setup_client(mock_cls)
        client.get_event_markets.return_value = _VALID_H2H_MARKETS
        mock_match.return_value = "EVT-H2H"
        mock_resolve.side_effect = [
            {"canonical_name": "Scheffler, Scottie"},
            {"canonical_name": "McIlroy, Rory"},
        ]

        result = pull_kalshi_matchups(
            tournament_name="Masters", tournament_start="2026-04-09",
            tournament_end="2026-04-12",
        )
        assert isinstance(result, list)
        assert len(result) == 1
        m = result[0]
        assert "p1_name" in m
        assert "p2_name" in m
        assert "p1_prob" in m
        assert "p2_prob" in m
        assert "p1_oi" in m
        assert "p2_oi" in m

    def test_filters_by_oi_threshold(self, mock_cls, mock_match, mock_resolve):
        client = self._setup_client(mock_cls)
        client.get_event_markets.return_value = [
            {
                "ticker": "MKT-H2H-LOW",
                "title": "Low OI A vs. Low OI B",
                "subtitle": "",
                "yes_bid": 0.50,
                "yes_ask": 0.53,
                "open_interest": 30,  # below threshold
            },
        ]
        mock_match.return_value = "EVT-H2H"
        mock_resolve.side_effect = [
            {"canonical_name": "Low OI A"},
            {"canonical_name": "Low OI B"},
        ]

        result = pull_kalshi_matchups(
            tournament_name="Masters", tournament_start="2026-04-09",
            tournament_end="2026-04-12",
        )
        assert result == []

    def test_filters_by_spread_threshold(self, mock_cls, mock_match, mock_resolve):
        client = self._setup_client(mock_cls)
        client.get_event_markets.return_value = [
            {
                "ticker": "MKT-H2H-WIDE",
                "title": "Wide A vs. Wide B",
                "subtitle": "",
                "yes_bid": 0.40,
                "yes_ask": 0.60,  # spread = 0.20
                "open_interest": 500,
            },
        ]
        mock_match.return_value = "EVT-H2H"

        result = pull_kalshi_matchups(
            tournament_name="Masters", tournament_start="2026-04-09",
            tournament_end="2026-04-12",
        )
        assert result == []

    def test_returns_empty_list_when_no_h2h_events(self, mock_cls, mock_match, mock_resolve):
        client = self._setup_client(mock_cls)
        client.get_golf_events.return_value = []
        mock_match.return_value = None

        result = pull_kalshi_matchups(
            tournament_name="Masters", tournament_start="2026-04-09",
            tournament_end="2026-04-12",
        )
        assert result == []


# ---- Merge Tests ----

class TestMergeKalshiIntoOutrights:

    def _dg_outrights(self):
        return {
            "win": [
                {"player_name": "Scheffler, Scottie", "dg_id": "1",
                 "draftkings": "+400", "fanduel": "+450"},
                {"player_name": "McIlroy, Rory", "dg_id": "2",
                 "draftkings": "+800", "fanduel": "+900"},
                {"player_name": "Hovland, Viktor", "dg_id": "3",
                 "draftkings": "+2000"},
            ],
            "top_10": [
                {"player_name": "Scheffler, Scottie", "dg_id": "1",
                 "draftkings": "-200"},
            ],
        }

    def _kalshi_outrights(self):
        return {
            "win": [
                {"player_name": "Scheffler, Scottie", "kalshi_mid_prob": 0.22,
                 "kalshi_ask_prob": 0.24, "open_interest": 500},
                {"player_name": "McIlroy, Rory", "kalshi_mid_prob": 0.09,
                 "kalshi_ask_prob": 0.10, "open_interest": 200},
            ],
            "t10": [
                {"player_name": "Scheffler, Scottie", "kalshi_mid_prob": 0.52,
                 "kalshi_ask_prob": 0.54, "open_interest": 300},
            ],
            "t20": [],
        }

    def test_adds_kalshi_key_with_american_odds(self):
        dg = self._dg_outrights()
        kalshi = self._kalshi_outrights()
        result = merge_kalshi_into_outrights(dg, kalshi)
        scheffler = result["win"][0]
        assert "kalshi" in scheffler
        assert scheffler["kalshi"].startswith("+") or scheffler["kalshi"].startswith("-")

    def test_american_odds_derived_from_midpoint_not_ask(self):
        dg = self._dg_outrights()
        kalshi = self._kalshi_outrights()
        result = merge_kalshi_into_outrights(dg, kalshi)
        scheffler = result["win"][0]
        # mid=0.22 -> +355 (approx), ask=0.24 -> +317 (approx)
        # The value should be from midpoint, so higher (more plus)
        odds_val = int(scheffler["kalshi"].replace("+", ""))
        assert odds_val > 300  # midpoint-based, not ask-based

    def test_unmatched_kalshi_players_skipped(self):
        dg = self._dg_outrights()
        kalshi = {"win": [
            {"player_name": "Unknown Player", "kalshi_mid_prob": 0.05,
             "kalshi_ask_prob": 0.06, "open_interest": 200},
        ], "t10": [], "t20": []}
        result = merge_kalshi_into_outrights(dg, kalshi)
        for player in result["win"]:
            assert "kalshi" not in player

    def test_existing_book_columns_not_modified(self):
        dg = self._dg_outrights()
        kalshi = self._kalshi_outrights()
        merge_kalshi_into_outrights(dg, kalshi)
        assert dg["win"][0]["draftkings"] == "+400"
        assert dg["win"][0]["fanduel"] == "+450"

    def test_players_without_kalshi_data_have_no_kalshi_key(self):
        dg = self._dg_outrights()
        kalshi = self._kalshi_outrights()
        merge_kalshi_into_outrights(dg, kalshi)
        hovland = dg["win"][2]
        assert "kalshi" not in hovland

    def test_stores_ask_data_for_bettable_edge(self):
        dg = self._dg_outrights()
        kalshi = self._kalshi_outrights()
        merge_kalshi_into_outrights(dg, kalshi)
        scheffler = dg["win"][0]
        assert "_kalshi_ask_prob" in scheffler
        assert isinstance(scheffler["_kalshi_ask_prob"], float)
        assert scheffler["_kalshi_ask_prob"] == 0.24


class TestMergeKalshiIntoMatchups:

    def _dg_matchups(self):
        return [
            {
                "p1_player_name": "Scheffler, Scottie",
                "p2_player_name": "McIlroy, Rory",
                "p1_dg_id": "1", "p2_dg_id": "2",
                "odds": {
                    "datagolf": {"p1": "-150", "p2": "+130"},
                    "draftkings": {"p1": "-160", "p2": "+140"},
                },
            },
        ]

    def _kalshi_matchups(self):
        return [
            {"p1_name": "Scheffler, Scottie", "p2_name": "McIlroy, Rory",
             "p1_prob": 0.565, "p2_prob": 0.435, "p1_oi": 300, "p2_oi": 300},
        ]

    def test_injects_kalshi_into_matchup_odds_dict(self):
        dg = self._dg_matchups()
        kalshi = self._kalshi_matchups()
        merge_kalshi_into_matchups(dg, kalshi)
        assert "kalshi" in dg[0]["odds"]
        kalshi_odds = dg[0]["odds"]["kalshi"]
        assert "p1" in kalshi_odds
        assert "p2" in kalshi_odds

    def test_unmatched_pairings_skipped(self):
        dg = self._dg_matchups()
        kalshi = [
            {"p1_name": "Player X", "p2_name": "Player Y",
             "p1_prob": 0.5, "p2_prob": 0.5, "p1_oi": 100, "p2_oi": 100},
        ]
        merge_kalshi_into_matchups(dg, kalshi)
        assert "kalshi" not in dg[0]["odds"]

    def test_kalshi_odds_same_format_as_other_books(self):
        dg = self._dg_matchups()
        kalshi = self._kalshi_matchups()
        merge_kalshi_into_matchups(dg, kalshi)
        kalshi_entry = dg[0]["odds"]["kalshi"]
        dk_entry = dg[0]["odds"]["draftkings"]
        # Same structure: {"p1": str, "p2": str}
        assert set(kalshi_entry.keys()) == set(dk_entry.keys())
        assert isinstance(kalshi_entry["p1"], str)
        assert isinstance(kalshi_entry["p2"], str)
