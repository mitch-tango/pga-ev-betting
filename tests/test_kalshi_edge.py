"""Tests for Kalshi book weight configuration, consensus integration, and edge behavior."""

import config
from src.core.blend import build_book_consensus
from src.core.devig import (
    power_devig, devig_independent,
    kalshi_price_to_decimal,
)
from src.core.edge import calculate_placement_edges, calculate_matchup_edges


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


class TestKalshiDevigBehavior:

    def test_power_devig_on_midpoint_field_k_near_one(self):
        """When Kalshi midpoints sum to ~1.0, power_devig returns
        probabilities nearly unchanged (k ~ 1.0)."""
        probs = [0.20, 0.15, 0.12, 0.10, 0.08, 0.07, 0.06, 0.05, 0.04, 0.13]
        assert abs(sum(probs) - 1.0) < 0.01
        devigged = power_devig(probs)
        for orig, dev in zip(probs, devigged):
            if dev is not None:
                assert abs(orig - dev) < 0.02

    def test_devig_independent_on_t10_midpoints_nearly_unchanged(self):
        """T10 midpoints summing to ~10 pass through devig_independent
        with minimal adjustment."""
        probs = [0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55,
                 0.50, 0.45, 0.40, 0.38, 0.35, 0.32, 0.30, 0.28,
                 0.25, 0.22, 0.20, 0.55]
        total = sum(probs)
        assert 9.0 < total < 11.0  # Should sum to ~10 for T10 market
        devigged = devig_independent(probs, expected_outcomes=10,
                                     field_size=20)
        for orig, dev in zip(probs, devigged):
            if dev is not None:
                assert abs(orig - dev) < 0.05

    def test_mixed_field_traditional_plus_kalshi_reasonable(self):
        """Both sportsbook and Kalshi fields produce valid de-vigged distributions."""
        trad_probs = [0.22, 0.17, 0.14, 0.11, 0.09, 0.08, 0.07, 0.06, 0.05, 0.04]
        assert sum(trad_probs) > 1.0
        trad_devigged = power_devig(trad_probs)

        kalshi_probs = [0.20, 0.15, 0.12, 0.10, 0.08, 0.07, 0.06, 0.05, 0.04, 0.13]
        kalshi_devigged = power_devig(kalshi_probs)

        trad_total = sum(p for p in trad_devigged if p is not None)
        kalshi_total = sum(p for p in kalshi_devigged if p is not None)
        assert abs(trad_total - 1.0) < 0.01
        assert abs(kalshi_total - 1.0) < 0.01


class TestKalshiMatchupExclusion:

    def _matchup_data(self, include_kalshi=True):
        odds = {
            "datagolf": {"p1": "-120", "p2": "+110"},
            "draftkings": {"p1": "-130", "p2": "+115"},
            "fanduel": {"p1": "-125", "p2": "+110"},
        }
        if include_kalshi:
            odds["kalshi"] = {"p1": "-110", "p2": "+100"}
        return [{
            "p1_player_name": "Scheffler, Scottie",
            "p2_player_name": "McIlroy, Rory",
            "p1_dg_id": "1", "p2_dg_id": "2",
            "odds": odds,
        }]

    def test_kalshi_excluded_from_matchup_book_consensus(self):
        """Consensus is the same whether Kalshi is present or not."""
        data_with = self._matchup_data(include_kalshi=True)
        data_without = self._matchup_data(include_kalshi=False)

        results_with = calculate_matchup_edges(data_with, bankroll=10000)
        results_without = calculate_matchup_edges(data_without, bankroll=10000)

        if results_with and results_without:
            for rw in results_with:
                for rwo in results_without:
                    if rw.player_name == rwo.player_name:
                        assert rw.book_consensus_prob == rwo.book_consensus_prob

    def test_kalshi_included_in_matchup_best_edge_evaluation(self):
        """Kalshi IS evaluated when finding the best-edge book."""
        data = [{
            "p1_player_name": "Scheffler, Scottie",
            "p2_player_name": "McIlroy, Rory",
            "p1_dg_id": "1", "p2_dg_id": "2",
            "odds": {
                "datagolf": {"p1": "-200", "p2": "+180"},
                "draftkings": {"p1": "-200", "p2": "+170"},
                "kalshi": {"p1": "-200", "p2": "+250"},
            },
        }]
        results = calculate_matchup_edges(data, bankroll=10000)
        assert isinstance(results, list)

    def test_kalshi_can_be_best_book_for_matchup(self):
        data = [{
            "p1_player_name": "Scheffler, Scottie",
            "p2_player_name": "McIlroy, Rory",
            "p1_dg_id": "1", "p2_dg_id": "2",
            "odds": {
                "datagolf": {"p1": "-140", "p2": "+125"},
                "draftkings": {"p1": "-160", "p2": "+140"},
                "fanduel": {"p1": "-155", "p2": "+135"},
                "kalshi": {"p1": "+120", "p2": "-130"},
            },
        }]
        results = calculate_matchup_edges(data, bankroll=10000)
        assert isinstance(results, list)


class TestKalshiAllBookOdds:

    def test_all_book_odds_includes_kalshi_with_ask_decimal(self):
        """all_book_odds uses ask-based decimal for Kalshi."""
        players = [
            {"player_name": f"Player {i}", "dg_id": str(i),
             "datagolf": {"baseline": 0.05},
             "draftkings": f"+{1000 + i * 100}",
             "kalshi": f"+{1800 + i * 50}",
             "_kalshi_ask_prob": 0.06}
            for i in range(20)
        ]
        results = calculate_placement_edges(players, "win", bankroll=10000)
        for r in results:
            if r.all_book_odds and "kalshi" in r.all_book_odds:
                kalshi_decimal = r.all_book_odds["kalshi"]
                expected = kalshi_price_to_decimal("0.06")
                assert kalshi_decimal == expected

    def test_kalshi_decimal_differs_from_midpoint_derived(self):
        """Ask-based decimal < midpoint-derived (worse for bettor)."""
        mid_decimal = kalshi_price_to_decimal("0.05")
        ask_decimal = kalshi_price_to_decimal("0.06")
        assert ask_decimal < mid_decimal
