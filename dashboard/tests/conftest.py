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


@pytest.fixture
def sample_settled_bets_analytics() -> list[dict]:
    """Settled bets spanning multiple market types, books, and dates for analytics tests."""
    return [
        {
            "id": 201, "tournament_id": 1, "market_type": "matchup",
            "player_name": "Scottie Scheffler", "opponent_name": "Rory McIlroy",
            "book": "DraftKings", "bet_timestamp": "2026-01-10T08:00:00Z",
            "odds_at_bet_decimal": 2.10, "odds_at_bet_american": "+110",
            "implied_prob_at_bet": 0.476, "your_prob": 0.55, "edge": 0.074,
            "stake": 25.0, "clv": 0.03, "outcome": "win", "pnl": 27.50,
        },
        {
            "id": 202, "tournament_id": 1, "market_type": "matchup",
            "player_name": "Collin Morikawa", "opponent_name": "Viktor Hovland",
            "book": "FanDuel", "bet_timestamp": "2026-01-15T09:30:00Z",
            "odds_at_bet_decimal": 1.833, "odds_at_bet_american": "-120",
            "implied_prob_at_bet": 0.545, "your_prob": 0.62, "edge": 0.075,
            "stake": 30.0, "clv": 0.05, "outcome": "win", "pnl": 24.99,
        },
        {
            "id": 203, "tournament_id": 2, "market_type": "outright",
            "player_name": "Xander Schauffele", "opponent_name": None,
            "book": "BetMGM", "bet_timestamp": "2026-02-05T14:00:00Z",
            "odds_at_bet_decimal": 15.0, "odds_at_bet_american": "+1400",
            "implied_prob_at_bet": 0.067, "your_prob": 0.09, "edge": 0.023,
            "stake": 10.0, "clv": None, "outcome": "loss", "pnl": -10.0,
        },
        {
            "id": 204, "tournament_id": 2, "market_type": "placement",
            "player_name": "Jon Rahm", "opponent_name": None,
            "book": "Caesars", "bet_timestamp": "2026-02-10T07:00:00Z",
            "odds_at_bet_decimal": 3.50, "odds_at_bet_american": "+250",
            "implied_prob_at_bet": 0.286, "your_prob": 0.35, "edge": 0.064,
            "stake": 20.0, "clv": -0.02, "outcome": "loss", "pnl": -20.0,
        },
        {
            "id": 205, "tournament_id": 3, "market_type": "3-ball",
            "player_name": "Jordan Spieth", "opponent_name": "Justin Thomas",
            "book": "DraftKings", "bet_timestamp": "2026-03-01T10:00:00Z",
            "odds_at_bet_decimal": 2.80, "odds_at_bet_american": "+180",
            "implied_prob_at_bet": 0.357, "your_prob": 0.42, "edge": 0.063,
            "stake": 15.0, "clv": 0.04, "outcome": "win", "pnl": 27.0,
        },
        {
            "id": 206, "tournament_id": 3, "market_type": "matchup",
            "player_name": "Patrick Cantlay", "opponent_name": "Sam Burns",
            "book": "FanDuel", "bet_timestamp": "2026-03-10T11:00:00Z",
            "odds_at_bet_decimal": 1.90, "odds_at_bet_american": "-111",
            "implied_prob_at_bet": 0.526, "your_prob": 0.60, "edge": 0.074,
            "stake": 28.0, "clv": 0.02, "outcome": "loss", "pnl": -28.0,
        },
        {
            "id": 207, "tournament_id": 4, "market_type": "outright",
            "player_name": "Wyndham Clark", "opponent_name": None,
            "book": "BetMGM", "bet_timestamp": "2026-03-20T13:00:00Z",
            "odds_at_bet_decimal": 25.0, "odds_at_bet_american": "+2400",
            "implied_prob_at_bet": 0.04, "your_prob": 0.06, "edge": 0.02,
            "stake": 5.0, "clv": None, "outcome": "loss", "pnl": -5.0,
        },
        {
            "id": 208, "tournament_id": 4, "market_type": "matchup",
            "player_name": "Ludvig Aberg", "opponent_name": "Tommy Fleetwood",
            "book": "Caesars", "bet_timestamp": "2026-04-01T09:00:00Z",
            "odds_at_bet_decimal": 2.00, "odds_at_bet_american": "+100",
            "implied_prob_at_bet": 0.50, "your_prob": 0.58, "edge": 0.08,
            "stake": 22.0, "clv": 0.06, "outcome": "win", "pnl": 22.0,
        },
    ]


@pytest.fixture
def sample_bankroll_data() -> list[dict]:
    """Bankroll entries with a clear peak followed by drawdown."""
    return [
        {"entry_date": "2026-01-01", "entry_type": "deposit", "amount": 500.0, "running_balance": 500.0},
        {"entry_date": "2026-01-10", "entry_type": "settlement", "amount": 27.50, "running_balance": 527.50},
        {"entry_date": "2026-01-15", "entry_type": "settlement", "amount": 24.99, "running_balance": 552.49},
        {"entry_date": "2026-02-05", "entry_type": "settlement", "amount": -10.0, "running_balance": 542.49},
        {"entry_date": "2026-02-10", "entry_type": "settlement", "amount": -20.0, "running_balance": 522.49},
        {"entry_date": "2026-02-15", "entry_type": "deposit", "amount": 200.0, "running_balance": 722.49},
        {"entry_date": "2026-03-01", "entry_type": "settlement", "amount": 27.0, "running_balance": 749.49},
        {"entry_date": "2026-03-10", "entry_type": "settlement", "amount": -28.0, "running_balance": 721.49},
        {"entry_date": "2026-03-20", "entry_type": "settlement", "amount": -5.0, "running_balance": 716.49},
        {"entry_date": "2026-03-25", "entry_type": "withdrawal", "amount": -100.0, "running_balance": 616.49},
        {"entry_date": "2026-04-01", "entry_type": "settlement", "amount": 22.0, "running_balance": 638.49},
    ]


@pytest.fixture
def sample_weekly_exposure() -> list[dict]:
    """Weekly exposure data for bankroll page."""
    return [
        {"week": "2026-01-05", "bets_placed": 5, "total_exposure": 120.0, "largest_single_bet": 30.0, "unique_players": 4},
        {"week": "2026-01-12", "bets_placed": 8, "total_exposure": 200.0, "largest_single_bet": 40.0, "unique_players": 6},
        {"week": "2026-01-19", "bets_placed": 3, "total_exposure": 75.0, "largest_single_bet": 30.0, "unique_players": 3},
        {"week": "2026-01-26", "bets_placed": 6, "total_exposure": 150.0, "largest_single_bet": 35.0, "unique_players": 5},
        {"week": "2026-02-02", "bets_placed": 4, "total_exposure": 95.0, "largest_single_bet": 25.0, "unique_players": 4},
    ]


@pytest.fixture
def sample_clv_weekly() -> list[dict]:
    """Weekly CLV data for model health page."""
    return [
        {"week": "2026-01-05", "bets": 5, "avg_clv_pct": 2.1, "weekly_pnl": 52.49, "avg_edge_pct": 5.5},
        {"week": "2026-01-12", "bets": 8, "avg_clv_pct": 1.8, "weekly_pnl": -10.0, "avg_edge_pct": 4.2},
        {"week": "2026-01-19", "bets": 3, "avg_clv_pct": -0.5, "weekly_pnl": -20.0, "avg_edge_pct": 3.1},
        {"week": "2026-01-26", "bets": 6, "avg_clv_pct": 3.2, "weekly_pnl": 27.0, "avg_edge_pct": 6.3},
        {"week": "2026-02-02", "bets": 4, "avg_clv_pct": 0.9, "weekly_pnl": -28.0, "avg_edge_pct": 4.8},
        {"week": "2026-02-09", "bets": 7, "avg_clv_pct": 2.5, "weekly_pnl": -5.0, "avg_edge_pct": 5.0},
        {"week": "2026-02-16", "bets": 5, "avg_clv_pct": -1.2, "weekly_pnl": 22.0, "avg_edge_pct": 3.8},
        {"week": "2026-02-23", "bets": 6, "avg_clv_pct": 1.5, "weekly_pnl": 15.0, "avg_edge_pct": 4.5},
    ]


@pytest.fixture
def sample_calibration() -> list[dict]:
    """Calibration data for model health page."""
    return [
        {"prob_bucket": "0-10%", "n": 45, "avg_predicted_pct": 6.2, "actual_hit_pct": 4.4},
        {"prob_bucket": "10-20%", "n": 62, "avg_predicted_pct": 14.8, "actual_hit_pct": 16.1},
        {"prob_bucket": "20-30%", "n": 78, "avg_predicted_pct": 25.1, "actual_hit_pct": 23.1},
        {"prob_bucket": "30-40%", "n": 55, "avg_predicted_pct": 34.9, "actual_hit_pct": 36.4},
        {"prob_bucket": "40-50%", "n": 90, "avg_predicted_pct": 45.3, "actual_hit_pct": 44.4},
        {"prob_bucket": "50-60%", "n": 72, "avg_predicted_pct": 54.7, "actual_hit_pct": 55.6},
        {"prob_bucket": "60-70%", "n": 38, "avg_predicted_pct": 64.2, "actual_hit_pct": 63.2},
    ]


@pytest.fixture
def sample_edge_tiers() -> list[dict]:
    """Edge tier ROI data for model health page."""
    return [
        {"edge_tier": "0-2%", "total_bets": 45, "total_staked": 900.0, "total_pnl": -18.0, "roi_pct": -2.0, "avg_clv_pct": 0.5},
        {"edge_tier": "2-5%", "total_bets": 80, "total_staked": 2000.0, "total_pnl": 120.0, "roi_pct": 6.0, "avg_clv_pct": 2.1},
        {"edge_tier": "5-8%", "total_bets": 50, "total_staked": 1250.0, "total_pnl": 112.5, "roi_pct": 9.0, "avg_clv_pct": 3.8},
        {"edge_tier": "8%+", "total_bets": 20, "total_staked": 400.0, "total_pnl": 52.0, "roi_pct": 13.0, "avg_clv_pct": 5.2},
    ]
