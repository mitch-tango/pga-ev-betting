"""Unit tests for src/core/blend.py"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.blend import (
    get_blend_weights,
    blend_probabilities,
    build_book_consensus,
    build_book_consensus_for_field,
)
import config


class TestGetBlendWeights:
    def test_win_standard(self):
        w = get_blend_weights("win")
        assert w == config.BLEND_WEIGHTS["win"]
        assert abs(w["dg"] + w["books"] - 1.0) < 1e-9

    def test_t10_uses_placement(self):
        w = get_blend_weights("t10")
        assert w == config.BLEND_WEIGHTS["placement"]

    def test_t20_uses_placement(self):
        w = get_blend_weights("t20")
        assert w == config.BLEND_WEIGHTS["placement"]

    def test_make_cut(self):
        w = get_blend_weights("make_cut")
        assert w == config.BLEND_WEIGHTS["make_cut"]

    def test_tournament_matchup(self):
        w = get_blend_weights("tournament_matchup")
        assert w == config.BLEND_WEIGHTS["matchup"]

    def test_round_matchup(self):
        w = get_blend_weights("round_matchup")
        assert w == config.BLEND_WEIGHTS["matchup"]

    def test_3_ball(self):
        w = get_blend_weights("3_ball")
        assert w == config.BLEND_WEIGHTS["three_ball"]

    def test_unknown_defaults_to_placement(self):
        w = get_blend_weights("mystery_market")
        assert w == config.BLEND_WEIGHTS["placement"]

    def test_signature_win(self):
        w = get_blend_weights("win", is_signature=True)
        assert w == config.BLEND_WEIGHTS["signature_win"]
        assert w["books"] > config.BLEND_WEIGHTS["win"]["books"], \
            "Signature events should weight books more heavily"

    def test_signature_placement(self):
        w = get_blend_weights("t10", is_signature=True)
        assert w == config.BLEND_WEIGHTS["signature_placement"]

    def test_signature_make_cut_not_overridden(self):
        """Make-cut doesn't have a signature override — uses standard."""
        w = get_blend_weights("make_cut", is_signature=True)
        assert w == config.BLEND_WEIGHTS["make_cut"]

    def test_deep_field_override(self):
        w = get_blend_weights("win", player_field_rank=70)
        assert w == config.BLEND_WEIGHTS["deep_field"]
        assert w["dg"] == 1.0

    def test_deep_field_at_threshold(self):
        w = get_blend_weights("t20", player_field_rank=config.DEEP_FIELD_RANK_THRESHOLD)
        assert w == config.BLEND_WEIGHTS["deep_field"]

    def test_not_deep_field_below_threshold(self):
        w = get_blend_weights("win", player_field_rank=60)
        assert w == config.BLEND_WEIGHTS["win"]

    def test_deep_field_overrides_signature(self):
        """Deep field should take priority over signature."""
        w = get_blend_weights("win", is_signature=True, player_field_rank=70)
        assert w == config.BLEND_WEIGHTS["deep_field"]


class TestBlendProbabilities:
    def test_both_inputs(self):
        result = blend_probabilities(0.10, 0.08, "win")
        w = config.BLEND_WEIGHTS["win"]
        expected = w["dg"] * 0.10 + w["books"] * 0.08
        assert abs(result - expected) < 1e-9

    def test_dg_only(self):
        result = blend_probabilities(0.10, None, "win")
        assert result == 0.10

    def test_book_only(self):
        result = blend_probabilities(None, 0.08, "win")
        assert result == 0.08

    def test_both_none(self):
        result = blend_probabilities(None, None, "win")
        assert result is None

    def test_matchup_blend(self):
        """Matchup blend should now be 10% DG / 90% books."""
        result = blend_probabilities(0.60, 0.50, "tournament_matchup")
        w = config.BLEND_WEIGHTS["matchup"]
        expected = w["dg"] * 0.60 + w["books"] * 0.50
        assert abs(result - expected) < 1e-9

    def test_deep_field_ignores_books(self):
        result = blend_probabilities(0.10, 0.08, "win", player_field_rank=70)
        # Deep field = 100% DG, so books ignored
        assert abs(result - 0.10) < 1e-9

    def test_signature_shifts_toward_books(self):
        standard = blend_probabilities(0.10, 0.08, "win")
        signature = blend_probabilities(0.10, 0.08, "win", is_signature=True)
        # Signature weights books more, books prob is lower, so result should be lower
        assert signature < standard


class TestBuildBookConsensus:
    def test_equal_weight_placement(self):
        probs = {"betonline": 0.30, "draftkings": 0.32, "fanduel": 0.28}
        result = build_book_consensus(probs, "t10")
        expected = (0.30 + 0.32 + 0.28) / 3
        assert abs(result - expected) < 1e-9

    def test_sharp_weighted_win(self):
        probs = {"pinnacle": 0.04, "draftkings": 0.05}
        result = build_book_consensus(probs, "win")
        # pinnacle weight=2, draftkings weight=1
        expected = (2 * 0.04 + 1 * 0.05) / 3
        assert abs(result - expected) < 1e-9

    def test_make_cut_uses_win_weights(self):
        probs = {"pinnacle": 0.60, "fanduel": 0.65}
        result = build_book_consensus(probs, "make_cut")
        # pinnacle weight=2, fanduel weight=1
        expected = (2 * 0.60 + 1 * 0.65) / 3
        assert abs(result - expected) < 1e-9

    def test_skips_none_values(self):
        probs = {"betonline": 0.30, "draftkings": None, "fanduel": 0.28}
        result = build_book_consensus(probs, "t20")
        expected = (0.30 + 0.28) / 2
        assert abs(result - expected) < 1e-9

    def test_skips_zero_values(self):
        probs = {"betonline": 0.30, "fanduel": 0.0}
        result = build_book_consensus(probs, "t10")
        assert abs(result - 0.30) < 1e-9

    def test_all_none(self):
        result = build_book_consensus({"pinnacle": None, "bovada": None}, "win")
        assert result is None

    def test_empty_dict(self):
        result = build_book_consensus({}, "win")
        assert result is None

    def test_unknown_book_gets_weight_1(self):
        probs = {"pinnacle": 0.04, "some_new_book": 0.05}
        result = build_book_consensus(probs, "win")
        # pinnacle weight=2, unknown weight=1
        expected = (2 * 0.04 + 1 * 0.05) / 3
        assert abs(result - expected) < 1e-9


class TestBuildBookConsensusForField:
    def test_multiple_players(self):
        field = {
            "Player A": {"pinnacle": 0.04, "draftkings": 0.05},
            "Player B": {"pinnacle": 0.02, "draftkings": 0.03},
        }
        result = build_book_consensus_for_field(field, "win")
        assert "Player A" in result
        assert "Player B" in result
        assert result["Player A"] > result["Player B"]

    def test_player_with_no_valid_books(self):
        field = {
            "Player A": {"pinnacle": None},
        }
        result = build_book_consensus_for_field(field, "win")
        assert result["Player A"] is None
