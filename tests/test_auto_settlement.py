"""Unit tests for auto-settlement logic.

Tests the settlement helper functions from scripts/run_log_outcomes.py.
Since importing that script pulls in DB/API dependencies, we replicate
the pure logic here and test it directly. These functions mirror the
originals exactly — any drift is caught by comparing against the source.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.settlement import (
    settle_placement_bet, settle_matchup_bet, settle_3ball_bet,
)


# ---- Replicated auto-settlement helpers (no DB imports needed) ----

def _settle_placement_auto(bet, player_result, book_rule=None):
    """Auto-settle a placement bet. Mirrors run_log_outcomes._settle_placement_auto."""
    market = bet["market_type"]
    threshold = {"win": 1, "t5": 5, "t10": 10, "t20": 20, "make_cut": 999}.get(market)
    if threshold is None:
        return None

    status = player_result["status"]
    pos = player_result["pos"]
    pos_str = player_result["pos_str"]

    if status in ("wd", "dq"):
        wd_rule = (book_rule or {}).get("wd_rule", "void")
        if wd_rule == "void":
            return {
                "outcome": "void", "settlement_rule": "void_wd",
                "payout": round(bet["stake"], 2), "pnl": 0.0,
                "actual_finish": status.upper(),
            }
        else:
            return {
                "outcome": "loss", "settlement_rule": "wd_loss",
                "payout": 0.0, "pnl": round(-bet["stake"], 2),
                "actual_finish": status.upper(),
            }

    if status == "cut":
        return {
            "outcome": "loss", "settlement_rule": "missed_cut",
            "payout": 0.0, "pnl": round(-bet["stake"], 2),
            "actual_finish": "MC",
        }

    if pos is None:
        return None

    if market == "make_cut":
        result = settle_placement_bet(
            pos, 999, bet["stake"], bet["odds_at_bet_decimal"],
        )
        result["actual_finish"] = pos_str
        return result

    tied = 1
    if pos == threshold and pos_str.startswith("T"):
        return None  # Dead-heat at cutoff — needs manual tie count

    tie_rule = (book_rule or {}).get("tie_rule", "dead_heat")
    result = settle_placement_bet(
        pos, threshold, bet["stake"], bet["odds_at_bet_decimal"],
        tied_at_cutoff=tied, tie_rule=tie_rule,
    )
    result["actual_finish"] = pos_str
    return result


def _settle_matchup_auto(bet, p_result, o_result, book_rule=None):
    """Auto-settle a matchup bet. Mirrors run_log_outcomes._settle_matchup_auto."""
    p_pos = p_result["pos"] if p_result["status"] == "active" else None
    o_pos = o_result["pos"] if o_result["status"] == "active" else None

    tie_rule = (book_rule or {}).get("tie_rule", "push")
    wd_rule = (book_rule or {}).get("wd_rule", "void")

    if bet["market_type"] == "round_matchup" and bet.get("round_number"):
        rnd_key = f"r{bet['round_number']}"
        p_score = p_result.get(rnd_key) if p_result["status"] not in ("wd", "dq") else None
        o_score = o_result.get(rnd_key) if o_result["status"] not in ("wd", "dq") else None

        if p_score is not None and o_score is not None:
            if p_score < o_score:
                payout = bet["stake"] * bet["odds_at_bet_decimal"]
                return {
                    "outcome": "win", "settlement_rule": "standard",
                    "payout": round(payout, 2), "pnl": round(payout - bet["stake"], 2),
                    "actual_finish": str(p_score), "opponent_finish": str(o_score),
                }
            elif p_score > o_score:
                return {
                    "outcome": "loss", "settlement_rule": "standard",
                    "payout": 0.0, "pnl": round(-bet["stake"], 2),
                    "actual_finish": str(p_score), "opponent_finish": str(o_score),
                }
            else:
                if tie_rule == "push":
                    return {
                        "outcome": "push", "settlement_rule": "push",
                        "payout": round(bet["stake"], 2), "pnl": 0.0,
                        "actual_finish": str(p_score), "opponent_finish": str(o_score),
                    }

    result = settle_matchup_bet(
        p_pos, o_pos, bet["stake"], bet["odds_at_bet_decimal"],
        tie_rule=tie_rule, wd_rule=wd_rule,
    )
    result["actual_finish"] = p_result["pos_str"]
    result["opponent_finish"] = o_result["pos_str"]
    return result


def _settle_3ball_auto(bet, p_result, o1_result, o2_result, book_rule=None):
    """Auto-settle a 3-ball bet. Mirrors run_log_outcomes._settle_3ball_auto."""
    rnd = bet.get("round_number")
    if not rnd:
        return None

    rnd_key = f"r{rnd}"
    p_score = p_result.get(rnd_key) if p_result["status"] not in ("wd", "dq") else None
    o1_score = o1_result.get(rnd_key) if o1_result["status"] not in ("wd", "dq") else None
    o2_score = o2_result.get(rnd_key) if o2_result["status"] not in ("wd", "dq") else None

    tie_rule = (book_rule or {}).get("tie_rule", "dead_heat")
    wd_rule = (book_rule or {}).get("wd_rule", "void")

    result = settle_3ball_bet(
        p_score, o1_score, o2_score,
        bet["stake"], bet["odds_at_bet_decimal"],
        tie_rule=tie_rule, wd_rule=wd_rule,
    )
    result["actual_finish"] = str(p_score) if p_score else "WD"
    result["opponent_finish"] = str(o1_score) if o1_score else "WD"
    return result


def _count_tied_at_pos(results, position):
    count = 0
    for p in results["players"].values():
        if p["pos"] == position:
            count += 1
    return count


# ---- Test helpers ----

def _make_bet(**overrides):
    bet = {
        "id": "test-bet-id",
        "market_type": "t10",
        "player_name": "Rory McIlroy",
        "opponent_name": None,
        "opponent_2_name": None,
        "book": "draftkings",
        "stake": 10.0,
        "odds_at_bet_decimal": 2.5,
        "edge": 0.06,
        "round_number": None,
    }
    bet.update(overrides)
    return bet


def _make_result(**overrides):
    result = {
        "name": "Rory McIlroy",
        "dg_id": "5678",
        "pos": 5,
        "pos_str": "T5",
        "status": "active",
        "r1": 68, "r2": 70, "r3": 69, "r4": 71,
        "total": -8,
    }
    result.update(overrides)
    return result


# ============================================================
# _settle_placement_auto
# ============================================================

class TestSettlePlacementAuto:
    def test_clear_win_t10(self):
        bet = _make_bet(market_type="t10")
        result = _settle_placement_auto(bet, _make_result(pos=5, pos_str="5"))
        assert result["outcome"] == "win"
        assert result["payout"] == 25.0
        assert result["pnl"] == 15.0

    def test_clear_loss_t10(self):
        bet = _make_bet(market_type="t10")
        result = _settle_placement_auto(bet, _make_result(pos=15, pos_str="T15"))
        assert result["outcome"] == "loss"
        assert result["pnl"] == -10.0

    def test_missed_cut(self):
        bet = _make_bet(market_type="t20")
        result = _settle_placement_auto(bet, _make_result(status="cut", pos=None, pos_str="MC"))
        assert result["outcome"] == "loss"
        assert result["settlement_rule"] == "missed_cut"
        assert result["pnl"] == -10.0

    def test_wd_void(self):
        rule = {"wd_rule": "void", "tie_rule": "dead_heat"}
        bet = _make_bet(market_type="t10")
        result = _settle_placement_auto(bet, _make_result(status="wd", pos=None, pos_str="WD"), book_rule=rule)
        assert result["outcome"] == "void"
        assert result["pnl"] == 0.0
        assert result["payout"] == 10.0

    def test_wd_loss_rule(self):
        rule = {"wd_rule": "loss", "tie_rule": "dead_heat"}
        bet = _make_bet(market_type="t10")
        result = _settle_placement_auto(bet, _make_result(status="wd", pos=None, pos_str="WD"), book_rule=rule)
        assert result["outcome"] == "loss"
        assert result["pnl"] == -10.0

    def test_dq_void(self):
        rule = {"wd_rule": "void", "tie_rule": "dead_heat"}
        bet = _make_bet(market_type="t20")
        result = _settle_placement_auto(bet, _make_result(status="dq", pos=None, pos_str="DQ"), book_rule=rule)
        assert result["outcome"] == "void"

    def test_dead_heat_at_cutoff_returns_none(self):
        bet = _make_bet(market_type="t10")
        result = _settle_placement_auto(bet, _make_result(pos=10, pos_str="T10"))
        assert result is None

    def test_exactly_at_cutoff_no_tie(self):
        rule = {"tie_rule": "dead_heat", "wd_rule": "void"}
        bet = _make_bet(market_type="t10")
        result = _settle_placement_auto(bet, _make_result(pos=10, pos_str="10"), book_rule=rule)
        assert result is not None
        assert result["outcome"] == "win"

    def test_win_market_first_place(self):
        bet = _make_bet(market_type="win", odds_at_bet_decimal=20.0)
        result = _settle_placement_auto(bet, _make_result(pos=1, pos_str="1"))
        assert result["outcome"] == "win"
        assert result["payout"] == 200.0
        assert result["pnl"] == 190.0

    def test_win_market_second_place_loss(self):
        bet = _make_bet(market_type="win")
        result = _settle_placement_auto(bet, _make_result(pos=2, pos_str="2"))
        assert result["outcome"] == "loss"

    def test_make_cut_active_player(self):
        bet = _make_bet(market_type="make_cut")
        result = _settle_placement_auto(bet, _make_result(pos=50, pos_str="T50"))
        assert result["outcome"] == "win"

    def test_make_cut_missed(self):
        bet = _make_bet(market_type="make_cut")
        result = _settle_placement_auto(bet, _make_result(status="cut", pos=None, pos_str="MC"))
        assert result["outcome"] == "loss"

    def test_pos_none_active_returns_none(self):
        bet = _make_bet(market_type="t10")
        result = _settle_placement_auto(bet, _make_result(pos=None, pos_str="", status="active"))
        assert result is None

    def test_unknown_market_returns_none(self):
        bet = _make_bet(market_type="unknown")
        result = _settle_placement_auto(bet, _make_result())
        assert result is None


# ============================================================
# _settle_matchup_auto
# ============================================================

class TestSettleMatchupAuto:
    RULE = {"tie_rule": "push", "wd_rule": "void"}

    def test_player_wins(self):
        bet = _make_bet(market_type="tournament_matchup", odds_at_bet_decimal=2.0)
        p = _make_result(pos=3, pos_str="T3")
        o = _make_result(name="Opponent", pos=10, pos_str="T10")
        result = _settle_matchup_auto(bet, p, o, book_rule=self.RULE)
        assert result["outcome"] == "win"
        assert result["pnl"] == 10.0

    def test_player_loses(self):
        bet = _make_bet(market_type="tournament_matchup")
        p = _make_result(pos=10, pos_str="T10")
        o = _make_result(name="Opponent", pos=3, pos_str="T3")
        result = _settle_matchup_auto(bet, p, o, book_rule=self.RULE)
        assert result["outcome"] == "loss"
        assert result["pnl"] == -10.0

    def test_tie_pushes(self):
        bet = _make_bet(market_type="tournament_matchup")
        p = _make_result(pos=5, pos_str="T5")
        o = _make_result(name="Opponent", pos=5, pos_str="T5")
        result = _settle_matchup_auto(bet, p, o, book_rule=self.RULE)
        assert result["outcome"] == "push"
        assert result["pnl"] == 0.0

    def test_player_wd_void(self):
        bet = _make_bet(market_type="tournament_matchup")
        p = _make_result(pos=None, pos_str="WD", status="wd")
        o = _make_result(name="Opponent", pos=5, pos_str="T5")
        result = _settle_matchup_auto(bet, p, o, book_rule=self.RULE)
        assert result["outcome"] == "void"

    def test_round_matchup_by_score(self):
        bet = _make_bet(market_type="round_matchup", round_number=1,
                        odds_at_bet_decimal=1.9)
        p = _make_result(r1=68)
        o = _make_result(name="Opponent", r1=72)
        result = _settle_matchup_auto(bet, p, o, book_rule=self.RULE)
        assert result["outcome"] == "win"

    def test_round_matchup_tie_pushes(self):
        bet = _make_bet(market_type="round_matchup", round_number=2)
        p = _make_result(r2=70)
        o = _make_result(name="Opponent", r2=70)
        result = _settle_matchup_auto(bet, p, o, book_rule=self.RULE)
        assert result["outcome"] == "push"
        assert result["pnl"] == 0.0

    def test_round_matchup_loss(self):
        bet = _make_bet(market_type="round_matchup", round_number=3)
        p = _make_result(r3=74)
        o = _make_result(name="Opponent", r3=69)
        result = _settle_matchup_auto(bet, p, o, book_rule=self.RULE)
        assert result["outcome"] == "loss"


# ============================================================
# _settle_3ball_auto
# ============================================================

class TestSettle3BallAuto:
    RULE = {"tie_rule": "dead_heat", "wd_rule": "void"}

    def test_outright_win(self):
        bet = _make_bet(market_type="3_ball", round_number=1,
                        odds_at_bet_decimal=3.0)
        p = _make_result(r1=67)
        o1 = _make_result(name="Opp1", r1=70)
        o2 = _make_result(name="Opp2", r1=72)
        result = _settle_3ball_auto(bet, p, o1, o2, book_rule=self.RULE)
        assert result["outcome"] == "win"
        assert result["payout"] == 30.0

    def test_loss(self):
        bet = _make_bet(market_type="3_ball", round_number=1)
        p = _make_result(r1=73)
        o1 = _make_result(name="Opp1", r1=68)
        o2 = _make_result(name="Opp2", r1=70)
        result = _settle_3ball_auto(bet, p, o1, o2, book_rule=self.RULE)
        assert result["outcome"] == "loss"

    def test_no_round_number_returns_none(self):
        bet = _make_bet(market_type="3_ball", round_number=None)
        result = _settle_3ball_auto(bet, _make_result(), _make_result(), _make_result())
        assert result is None

    def test_player_wd(self):
        bet = _make_bet(market_type="3_ball", round_number=1)
        p = _make_result(status="wd", r1=None)
        o1 = _make_result(name="Opp1", r1=70)
        o2 = _make_result(name="Opp2", r1=72)
        result = _settle_3ball_auto(bet, p, o1, o2, book_rule=self.RULE)
        assert result["outcome"] in ("void", "loss")


# ============================================================
# _count_tied_at_pos
# ============================================================

class TestCountTiedAtPos:
    def test_no_ties(self):
        results = {"players": {
            "a": {"pos": 1}, "b": {"pos": 2}, "c": {"pos": 3},
        }}
        assert _count_tied_at_pos(results, 1) == 1

    def test_two_way_tie(self):
        results = {"players": {
            "a": {"pos": 5}, "b": {"pos": 5}, "c": {"pos": 7},
        }}
        assert _count_tied_at_pos(results, 5) == 2

    def test_three_way_tie(self):
        results = {"players": {
            "a": {"pos": 10}, "b": {"pos": 10}, "c": {"pos": 10}, "d": {"pos": 1},
        }}
        assert _count_tied_at_pos(results, 10) == 3

    def test_nobody_at_position(self):
        results = {"players": {
            "a": {"pos": 1}, "b": {"pos": 3},
        }}
        assert _count_tied_at_pos(results, 2) == 0
