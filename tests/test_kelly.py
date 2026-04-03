"""Unit tests for src/core/kelly.py"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.kelly import kelly_stake, get_correlation_haircut, check_exposure


class TestKellyStake:
    def test_basic_calculation(self):
        # 5% edge, +200 odds (3.0 decimal), $1000 bankroll, quarter-Kelly
        stake = kelly_stake(0.05, 3.0, 1000.0)
        # Kelly% = 0.05 / (3.0 - 1) = 0.025
        # Stake = 1000 * 0.025 * 0.25 = 6.25 -> rounds to 6
        assert stake == 6.0

    def test_zero_edge(self):
        assert kelly_stake(0.0, 3.0, 1000.0) == 0.0

    def test_negative_edge(self):
        assert kelly_stake(-0.05, 3.0, 1000.0) == 0.0

    def test_max_bet_cap(self):
        # Huge edge should be capped at 3% of bankroll
        stake = kelly_stake(0.50, 2.0, 1000.0)
        assert stake <= 30.0  # 3% of $1000

    def test_correlation_haircut(self):
        # Same edge but with 50% haircut
        full = kelly_stake(0.05, 3.0, 1000.0, correlation_haircut=1.0)
        half = kelly_stake(0.05, 3.0, 1000.0, correlation_haircut=0.5)
        assert half <= full * 0.6  # Allow rounding tolerance

    def test_small_bankroll(self):
        # $100 bankroll, small edge
        stake = kelly_stake(0.03, 2.5, 100.0)
        assert stake >= 0.0
        assert stake <= 3.0  # 3% of $100

    def test_custom_fraction(self):
        half_kelly = kelly_stake(0.05, 3.0, 1000.0, kelly_fraction=0.5)
        quarter_kelly = kelly_stake(0.05, 3.0, 1000.0, kelly_fraction=0.25)
        assert half_kelly > quarter_kelly

    def test_invalid_odds(self):
        assert kelly_stake(0.05, 1.0, 1000.0) == 0.0
        assert kelly_stake(0.05, 0.5, 1000.0) == 0.0

    def test_zero_bankroll(self):
        assert kelly_stake(0.05, 3.0, 0.0) == 0.0


class TestCorrelationHaircut:
    def test_first_bet(self):
        haircut = get_correlation_haircut("Matsuyama", [])
        assert haircut == 1.0

    def test_second_bet(self):
        existing = [{"player_name": "Matsuyama", "opponent_name": None,
                     "opponent_2_name": None}]
        haircut = get_correlation_haircut("Matsuyama", existing)
        assert haircut == 0.5

    def test_third_bet(self):
        existing = [
            {"player_name": "Matsuyama", "opponent_name": None,
             "opponent_2_name": None},
            {"player_name": "Matsuyama", "opponent_name": None,
             "opponent_2_name": None},
        ]
        haircut = get_correlation_haircut("Matsuyama", existing)
        assert haircut == 0.25

    def test_fourth_plus(self):
        existing = [
            {"player_name": "Matsuyama", "opponent_name": None,
             "opponent_2_name": None},
        ] * 5
        haircut = get_correlation_haircut("Matsuyama", existing)
        assert haircut == 0.125

    def test_different_player(self):
        existing = [{"player_name": "Scheffler", "opponent_name": None,
                     "opponent_2_name": None}]
        haircut = get_correlation_haircut("Matsuyama", existing)
        assert haircut == 1.0  # No prior bets on Matsuyama

    def test_opponent_counts(self):
        # Player appears as opponent in a matchup
        existing = [{"player_name": "Scheffler", "opponent_name": "Matsuyama",
                     "opponent_2_name": None}]
        haircut = get_correlation_haircut("Matsuyama", existing)
        assert haircut == 0.5  # Matsuyama is involved

    def test_case_insensitive(self):
        existing = [{"player_name": "matsuyama", "opponent_name": None,
                     "opponent_2_name": None}]
        haircut = get_correlation_haircut("Matsuyama", existing)
        assert haircut == 0.5


class TestCheckExposure:
    def _make_bets(self, n, player="Matsuyama", tournament="t1", stake=10):
        return [
            {"player_name": player, "opponent_name": None,
             "opponent_2_name": None, "tournament_id": tournament,
             "stake": stake, "bet_timestamp": "2026-04-03"}
        ] * n

    def test_under_all_limits(self):
        result = check_exposure(10, "Matsuyama", "t1", 1000.0, [])
        assert result["approved"] is True
        assert result["stake"] == 10

    def test_weekly_limit(self):
        # $1000 bankroll, 15% weekly limit = $150
        existing = self._make_bets(14, stake=10)  # $140 already
        result = check_exposure(20, "Spieth", "t1", 1000.0, existing)
        # $140 + $20 = $160 > $150, should be reduced
        assert result["stake"] <= 10
        assert len(result["warnings"]) > 0

    def test_player_limit(self):
        # $1000 bankroll, 5% player limit = $50
        existing = self._make_bets(4, player="Matsuyama", stake=12)  # $48
        result = check_exposure(10, "Matsuyama", "t1", 1000.0, existing)
        # $48 + $10 = $58 > $50
        assert result["stake"] <= 2
        assert len(result["warnings"]) > 0

    def test_tournament_limit(self):
        # $1000 bankroll, 8% tournament limit = $80
        existing = self._make_bets(7, player="Various", tournament="t1", stake=10)  # $70
        result = check_exposure(20, "Spieth", "t1", 1000.0, existing)
        # $70 + $20 = $90 > $80
        assert result["stake"] <= 10

    def test_fully_blocked(self):
        # Weekly limit exhausted
        existing = self._make_bets(15, stake=10)  # $150 = exactly at 15% of $1000
        result = check_exposure(10, "NewPlayer", "t1", 1000.0, existing)
        assert result["approved"] is False
        assert result["blocked_by"] is not None
