"""Unit tests for src/core/settlement.py"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.settlement import (
    adjust_edge_for_deadheat,
    settle_placement_bet,
    settle_matchup_bet,
    settle_3ball_bet,
)


class TestAdjustEdgeForDeadheat:
    def test_t20_adjustment(self):
        edge, adj = adjust_edge_for_deadheat(0.05, "t20", 3.0)
        assert adj < 0
        assert edge < 0.05

    def test_non_placement_no_adjustment(self):
        edge, adj = adjust_edge_for_deadheat(0.05, "tournament_matchup", 2.0)
        assert adj == 0.0
        assert edge == 0.05

    def test_win_no_adjustment(self):
        edge, adj = adjust_edge_for_deadheat(0.05, "win", 20.0)
        assert adj == 0.0


class TestSettlePlacementBet:
    def test_clear_win(self):
        result = settle_placement_bet(
            actual_finish=5, threshold=20, stake=10, decimal_odds=2.5
        )
        assert result["outcome"] == "win"
        assert result["payout"] == 25.0
        assert result["pnl"] == 15.0

    def test_clear_loss(self):
        result = settle_placement_bet(
            actual_finish=25, threshold=20, stake=10, decimal_odds=2.5
        )
        assert result["outcome"] == "loss"
        assert result["payout"] == 0.0
        assert result["pnl"] == -10.0

    def test_exactly_at_threshold_no_tie(self):
        result = settle_placement_bet(
            actual_finish=20, threshold=20, stake=10, decimal_odds=2.5,
            tied_at_cutoff=1
        )
        assert result["outcome"] == "win"

    def test_dead_heat_two_way(self):
        result = settle_placement_bet(
            actual_finish=20, threshold=20, stake=10, decimal_odds=2.5,
            tied_at_cutoff=2, tie_rule="dead_heat"
        )
        assert result["outcome"] == "half_win"
        # Effective stake = 10/2 = 5, payout = 5 * 2.5 = 12.5
        assert result["payout"] == 12.5
        assert result["pnl"] == 2.5

    def test_dead_heat_three_way(self):
        result = settle_placement_bet(
            actual_finish=20, threshold=20, stake=10, decimal_odds=3.0,
            tied_at_cutoff=3, tie_rule="dead_heat"
        )
        assert result["outcome"] == "half_win"
        # Effective stake = 10/3 = 3.33, payout = 3.33 * 3.0 = 10.0
        assert abs(result["payout"] - 10.0) < 0.01

    def test_push_on_tie(self):
        result = settle_placement_bet(
            actual_finish=20, threshold=20, stake=10, decimal_odds=2.5,
            tied_at_cutoff=2, tie_rule="push"
        )
        assert result["outcome"] == "push"
        assert result["pnl"] == 0.0


class TestSettleMatchupBet:
    def test_win(self):
        result = settle_matchup_bet(
            player_finish=5, opponent_finish=15,
            stake=10, decimal_odds=2.0
        )
        assert result["outcome"] == "win"
        assert result["payout"] == 20.0
        assert result["pnl"] == 10.0

    def test_loss(self):
        result = settle_matchup_bet(
            player_finish=15, opponent_finish=5,
            stake=10, decimal_odds=2.0
        )
        assert result["outcome"] == "loss"
        assert result["pnl"] == -10.0

    def test_tie_push(self):
        result = settle_matchup_bet(
            player_finish=10, opponent_finish=10,
            stake=10, decimal_odds=2.0, tie_rule="push"
        )
        assert result["outcome"] == "push"
        assert result["pnl"] == 0.0

    def test_wd_void(self):
        result = settle_matchup_bet(
            player_finish=None, opponent_finish=10,
            stake=10, decimal_odds=2.0, wd_rule="void"
        )
        assert result["outcome"] == "void"
        assert result["pnl"] == 0.0

    def test_opponent_wd_loss_rule(self):
        result = settle_matchup_bet(
            player_finish=10, opponent_finish=None,
            stake=10, decimal_odds=2.0, wd_rule="loss"
        )
        assert result["outcome"] == "win"
        assert result["payout"] == 20.0


class TestSettle3BallBet:
    def test_outright_win(self):
        result = settle_3ball_bet(
            player_score=68, opp1_score=70, opp2_score=72,
            stake=10, decimal_odds=3.0
        )
        assert result["outcome"] == "win"
        assert result["payout"] == 30.0

    def test_loss(self):
        result = settle_3ball_bet(
            player_score=72, opp1_score=68, opp2_score=70,
            stake=10, decimal_odds=3.0
        )
        assert result["outcome"] == "loss"
        assert result["pnl"] == -10.0

    def test_two_way_tie_dead_heat(self):
        result = settle_3ball_bet(
            player_score=68, opp1_score=68, opp2_score=72,
            stake=10, decimal_odds=3.0, tie_rule="dead_heat"
        )
        assert result["outcome"] == "half_win"
        # Effective stake = 10/2 = 5, payout = 5 * 3.0 = 15
        assert result["payout"] == 15.0
        assert result["pnl"] == 5.0

    def test_three_way_tie(self):
        result = settle_3ball_bet(
            player_score=70, opp1_score=70, opp2_score=70,
            stake=10, decimal_odds=3.0, tie_rule="dead_heat"
        )
        assert result["outcome"] == "half_win"
        # 10/3 * 3.0 = 10.0
        assert abs(result["payout"] - 10.0) < 0.01

    def test_player_wd(self):
        result = settle_3ball_bet(
            player_score=None, opp1_score=68, opp2_score=70,
            stake=10, decimal_odds=3.0, wd_rule="void"
        )
        assert result["outcome"] == "void"
        assert result["pnl"] == 0.0
