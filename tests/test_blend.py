"""Unit tests for src/core/blend.py"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.blend import (
    get_blend_weights,
    blend_probabilities,
    build_book_consensus,
    build_book_consensus_for_field,
    classify_tranche,
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

    def test_matchup_favorite_tranche(self):
        w = get_blend_weights("tournament_matchup", tranche="favorite")
        assert w == config.MATCHUP_TRANCHE_WEIGHTS["favorite"]
        assert w["dg"] == 0.60

    def test_matchup_mid_tranche(self):
        w = get_blend_weights("tournament_matchup", tranche="mid")
        assert w == config.MATCHUP_TRANCHE_WEIGHTS["mid"]
        assert w["dg"] == 0.30

    def test_matchup_longshot_tranche(self):
        w = get_blend_weights("round_matchup", tranche="longshot")
        assert w == config.MATCHUP_TRANCHE_WEIGHTS["longshot"]
        assert w["dg"] == 0.00

    def test_matchup_no_tranche_uses_global(self):
        w = get_blend_weights("tournament_matchup")
        assert w == config.BLEND_WEIGHTS["matchup"]

    def test_tranche_ignored_for_win(self):
        """Tranche should not affect win market (temporally unstable)."""
        w = get_blend_weights("win", tranche="favorite")
        assert w == config.BLEND_WEIGHTS["win"]

    def test_placement_favorite_tranche(self):
        w = get_blend_weights("t10", tranche="favorite")
        assert w == config.PLACEMENT_TRANCHE_WEIGHTS["favorite"]
        assert w["dg"] == 1.00

    def test_placement_mid_tranche(self):
        w = get_blend_weights("t20", tranche="mid")
        assert w == config.PLACEMENT_TRANCHE_WEIGHTS["mid"]
        assert w["dg"] == 0.45

    def test_placement_longshot_tranche(self):
        w = get_blend_weights("t10", tranche="longshot")
        assert w == config.PLACEMENT_TRANCHE_WEIGHTS["longshot"]
        assert w["dg"] == 0.45

    def test_placement_no_tranche_uses_global(self):
        w = get_blend_weights("t20")
        assert w == config.BLEND_WEIGHTS["placement"]

    def test_make_cut_uses_tranche(self):
        """Make-cut now uses tranche-specific weights (revalidated 2026-04-07)."""
        w = get_blend_weights("make_cut", tranche="favorite")
        assert w == config.MAKE_CUT_TRANCHE_WEIGHTS["favorite"]
        assert w["dg"] == 0.85

    def test_make_cut_mid_tranche(self):
        w = get_blend_weights("make_cut", tranche="mid")
        assert w == config.MAKE_CUT_TRANCHE_WEIGHTS["mid"]
        assert w["dg"] == 0.70

    def test_make_cut_no_tranche_uses_global(self):
        """Without tranche info, falls back to global 80% DG."""
        w = get_blend_weights("make_cut")
        assert w == config.BLEND_WEIGHTS["make_cut"]
        assert w["dg"] == 0.80

    def test_signature_overrides_tranche(self):
        """Signature event override should take priority over tranche."""
        w = get_blend_weights("t10", is_signature=True, tranche="longshot")
        assert w == config.BLEND_WEIGHTS["signature_placement"]


class TestClassifyTranche:
    def test_favorite(self):
        assert classify_tranche(0.08) == "favorite"

    def test_favorite_at_threshold(self):
        assert classify_tranche(0.05) == "favorite"

    def test_mid(self):
        assert classify_tranche(0.03) == "mid"

    def test_mid_at_threshold(self):
        assert classify_tranche(0.01) == "mid"

    def test_longshot(self):
        assert classify_tranche(0.005) == "longshot"

    def test_longshot_very_low(self):
        assert classify_tranche(0.001) == "longshot"


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

    def test_matchup_blend_no_tranche(self):
        """Matchup without tranche uses global 20/80 fallback."""
        result = blend_probabilities(0.60, 0.50, "tournament_matchup")
        w = config.BLEND_WEIGHTS["matchup"]
        expected = w["dg"] * 0.60 + w["books"] * 0.50
        assert abs(result - expected) < 1e-9

    def test_matchup_blend_favorite_tranche(self):
        """Favorite tranche uses 60% DG / 40% books."""
        result = blend_probabilities(0.60, 0.50, "tournament_matchup",
                                     tranche="favorite")
        w = config.MATCHUP_TRANCHE_WEIGHTS["favorite"]
        expected = w["dg"] * 0.60 + w["books"] * 0.50
        assert abs(result - expected) < 1e-9

    def test_matchup_blend_longshot_tranche(self):
        """Longshot tranche uses 0% DG / 100% books."""
        result = blend_probabilities(0.60, 0.50, "tournament_matchup",
                                     tranche="longshot")
        w = config.MATCHUP_TRANCHE_WEIGHTS["longshot"]
        expected = w["dg"] * 0.60 + w["books"] * 0.50
        assert abs(result - expected) < 1e-9
        # Longshot = 100% books, so result should equal book prob
        assert abs(result - 0.50) < 1e-9

    def test_placement_favorite_uses_100pct_dg(self):
        """T10 favorite tranche = 100% DG."""
        result = blend_probabilities(0.40, 0.30, "t10", tranche="favorite")
        assert abs(result - 0.40) < 1e-9  # 100% DG = DG prob

    def test_placement_longshot_blend(self):
        """T20 longshot tranche = 45% DG / 55% books."""
        result = blend_probabilities(0.10, 0.08, "t20", tranche="longshot")
        w = config.PLACEMENT_TRANCHE_WEIGHTS["longshot"]
        expected = w["dg"] * 0.10 + w["books"] * 0.08
        assert abs(result - expected) < 1e-9

    def test_make_cut_blend(self):
        """Make-cut uses 80% DG global weight."""
        result = blend_probabilities(0.70, 0.60, "make_cut")
        w = config.BLEND_WEIGHTS["make_cut"]
        expected = w["dg"] * 0.70 + w["books"] * 0.60
        assert abs(result - expected) < 1e-9
        assert w["dg"] == 0.80

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
