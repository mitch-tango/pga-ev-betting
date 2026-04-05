"""Tests for Kalshi pipeline pull (outrights and matchups)."""

from unittest.mock import patch, MagicMock

from src.pipeline.pull_kalshi import pull_kalshi_outrights, pull_kalshi_matchups


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
