import pytest


@pytest.fixture
def sample_tournament() -> dict:
    """Dict matching the tournaments table schema."""
    return {
        "id": 1,
        "tournament_name": "The Masters",
        "start_date": "2026-04-02",
        "purse": 20000000,
        "dg_event_id": 14,
        "season": 2026,
        "is_signature": False,
        "is_no_cut": False,
        "putting_surface": "bentgrass",
    }


@pytest.fixture
def sample_bets() -> list[dict]:
    """List of bet dicts with varied market types, books, and outcomes."""
    return [
        {
            "id": 101,
            "tournament_id": 1,
            "player_name": "Scottie Scheffler",
            "opponent_name": "Rory McIlroy",
            "market_type": "matchup",
            "book": "DraftKings",
            "odds_at_bet_american": "+110",
            "odds_at_bet_decimal": 2.10,
            "implied_prob_at_bet": 0.476,
            "your_prob": 0.55,
            "edge": 0.074,
            "stake": 25.0,
            "clv": 0.03,
            "outcome": "win",
            "pnl": 27.50,
            "bet_timestamp": "2026-04-02T08:00:00Z",
            "is_live": False,
            "round_number": None,
        },
        {
            "id": 102,
            "tournament_id": 1,
            "player_name": "Collin Morikawa",
            "opponent_name": "Viktor Hovland",
            "market_type": "matchup",
            "book": "FanDuel",
            "odds_at_bet_american": "-120",
            "odds_at_bet_decimal": 1.833,
            "implied_prob_at_bet": 0.545,
            "your_prob": 0.62,
            "edge": 0.075,
            "stake": 30.0,
            "clv": None,
            "outcome": None,
            "pnl": None,
            "bet_timestamp": "2026-04-02T09:30:00Z",
            "is_live": False,
            "round_number": None,
        },
        {
            "id": 103,
            "tournament_id": 1,
            "player_name": "Xander Schauffele",
            "opponent_name": None,
            "market_type": "outright",
            "book": "BetMGM",
            "odds_at_bet_american": "+1400",
            "odds_at_bet_decimal": 15.0,
            "implied_prob_at_bet": 0.067,
            "your_prob": 0.09,
            "edge": 0.023,
            "stake": 10.0,
            "clv": None,
            "outcome": None,
            "pnl": None,
            "bet_timestamp": "2026-04-01T14:00:00Z",
            "is_live": False,
            "round_number": None,
        },
        {
            "id": 104,
            "tournament_id": 1,
            "player_name": "Jon Rahm",
            "opponent_name": None,
            "market_type": "placement",
            "book": "Caesars",
            "odds_at_bet_american": "+250",
            "odds_at_bet_decimal": 3.50,
            "implied_prob_at_bet": 0.286,
            "your_prob": 0.35,
            "edge": 0.064,
            "stake": 20.0,
            "clv": -0.02,
            "outcome": "loss",
            "pnl": -20.0,
            "bet_timestamp": "2026-04-02T07:00:00Z",
            "is_live": False,
            "round_number": None,
        },
        {
            "id": 105,
            "tournament_id": 1,
            "player_name": "Jordan Spieth",
            "opponent_name": "Justin Thomas",
            "market_type": "3-ball",
            "book": "DraftKings",
            "odds_at_bet_american": "+180",
            "odds_at_bet_decimal": 2.80,
            "implied_prob_at_bet": 0.357,
            "your_prob": 0.42,
            "edge": 0.063,
            "stake": 15.0,
            "clv": None,
            "outcome": None,
            "pnl": None,
            "bet_timestamp": "2026-04-03T10:00:00Z",
            "is_live": True,
            "round_number": 2,
        },
    ]


@pytest.fixture
def sample_active_bets(sample_bets) -> list[dict]:
    """Subset of sample_bets where outcome is None."""
    return [b for b in sample_bets if b["outcome"] is None]


@pytest.fixture
def sample_settled_bets(sample_bets) -> list[dict]:
    """Subset of sample_bets where outcome is not None."""
    return [b for b in sample_bets if b["outcome"] is not None]


@pytest.fixture
def mock_supabase_client(monkeypatch):
    """Patched Supabase client that returns fixture data."""
    from unittest.mock import MagicMock

    mock_client = MagicMock()
    # Make chainable: .table().select().eq().is_().execute()
    mock_client.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value.data = []
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    mock_client.table.return_value.select.return_value.execute.return_value.data = []

    monkeypatch.setattr(
        "lib.supabase_client.get_client", lambda: mock_client
    )
    return mock_client
