"""Tests for Kalshi book weight configuration and consensus integration."""

import config
from src.core.blend import build_book_consensus


class TestKalshiBookWeights:
    """Verify kalshi appears in BOOK_WEIGHTS with correct weight per market type."""

    def test_kalshi_weight_2_in_win_market(self):
        """kalshi has weight 2 in win market (sharp — prediction markets are efficient)."""
        assert config.BOOK_WEIGHTS["win"]["kalshi"] == 2

    def test_kalshi_weight_1_in_placement_market(self):
        """kalshi has weight 1 in placement market (t10, t20)."""
        assert config.BOOK_WEIGHTS["placement"]["kalshi"] == 1

    def test_kalshi_absent_from_make_cut_weights(self):
        """kalshi is not present in make_cut weights — Kalshi does not offer make_cut."""
        assert "kalshi" not in config.BOOK_WEIGHTS["make_cut"]

    def test_build_book_consensus_includes_kalshi(self):
        """build_book_consensus picks up kalshi with correct weight when present.

        Both pinnacle and kalshi have weight 2 for win market.
        Weighted average of 0.12 and 0.10 with equal weights = 0.11.
        """
        result = build_book_consensus({"kalshi": 0.10, "pinnacle": 0.12}, "win")
        assert abs(result - 0.11) < 1e-9
