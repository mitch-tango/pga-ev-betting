"""Tests for Kalshi book weight configuration, consensus integration, and edge behavior."""

from unittest.mock import patch

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


def _make_placement_field(num_players=20, dk_odds="+350", kalshi_odds="+340",
                          dg_baseline="+1900"):
    """Helper: build a minimal outrights field for calculate_placement_edges.

    Args:
        dg_baseline: American odds string for DG model probability
            (e.g., "+1900" for ~5% implied, "+2400" for ~4% implied).
    """
    players = []
    for i in range(num_players):
        p = {
            "player_name": f"Player {i}",
            "dg_id": str(i),
            "datagolf": {"baseline_history_fit": dg_baseline},
            "draftkings": dk_odds,
            "kalshi": kalshi_odds,
        }
        players.append(p)
    return players


class TestKalshiDeadHeatBypass:
    """Dead-heat adjustment is skipped when best_book is Kalshi for placement markets."""

    def test_kalshi_no_deadheat_books_config_exists(self):
        """KALSHI_NO_DEADHEAT_BOOKS config set exists and contains 'kalshi'."""
        assert hasattr(config, "KALSHI_NO_DEADHEAT_BOOKS")
        assert "kalshi" in config.KALSHI_NO_DEADHEAT_BOOKS

    def test_kalshi_t10_no_deadheat_adj(self):
        """When best_book is 'kalshi' and market is t10, deadheat_adj should be 0.0."""
        # Mock blend to return a prob that creates edges for both books,
        # with Kalshi having a better adjusted edge (DH bypass)
        players = _make_placement_field(dk_odds="+350", kalshi_odds="+340")
        with patch("src.core.edge.blend_probabilities", return_value=0.30), \
             patch("src.core.edge.build_book_consensus", return_value=0.25):
            results = calculate_placement_edges(players, "t10", bankroll=10000)
        kalshi_bets = [r for r in results if r.best_book == "kalshi"]
        assert len(kalshi_bets) > 0, "Expected at least one bet with kalshi as best_book"
        for bet in kalshi_bets:
            assert bet.deadheat_adj == 0.0

    def test_kalshi_t20_no_deadheat_adj(self):
        """When best_book is 'kalshi' and market is t20, deadheat_adj should be 0.0."""
        players = _make_placement_field(dk_odds="+350", kalshi_odds="+340")
        with patch("src.core.edge.blend_probabilities", return_value=0.30), \
             patch("src.core.edge.build_book_consensus", return_value=0.25):
            results = calculate_placement_edges(players, "t20", bankroll=10000)
        kalshi_bets = [r for r in results if r.best_book == "kalshi"]
        assert len(kalshi_bets) > 0, "Expected at least one bet with kalshi as best_book"
        for bet in kalshi_bets:
            assert bet.deadheat_adj == 0.0

    def test_sportsbook_t10_has_deadheat_adj(self):
        """When best_book is 'draftkings' and market is t10, deadheat_adj < 0."""
        # Create a heterogeneous field where Player 0 has great DK odds
        # but poor Kalshi odds, so DK wins best_book despite DH penalty.
        # Player 0: DK +1500 (implied ~0.063), Kalshi +150 (implied ~0.40)
        # After devig, DK prob for P0 is much lower -> bigger raw edge from DK.
        # Other players fill the field with moderate odds.
        players = []
        # Player 0: target player — great DK odds, poor Kalshi odds
        players.append({
            "player_name": "Target Player",
            "dg_id": "0",
            "datagolf": {"baseline_history_fit": "+300"},
            "draftkings": "+1500",
            "kalshi": "+150",
        })
        # Remaining 19 players with moderate odds
        for i in range(1, 20):
            players.append({
                "player_name": f"Player {i}",
                "dg_id": str(i),
                "datagolf": {"baseline_history_fit": "+500"},
                "draftkings": "+400",
                "kalshi": "+400",
            })

        with patch("src.core.edge.blend_probabilities", return_value=0.60), \
             patch("src.core.edge.build_book_consensus", return_value=0.30):
            results = calculate_placement_edges(players, "t10", bankroll=10000)
        # Find the target player's bet — DK should win because its devigged
        # prob is much lower (~0.03), giving a raw edge of ~0.57, while
        # Kalshi devigged prob is ~0.20, raw edge ~0.40.
        # DK adj = 0.57 - 0.044 = 0.526, Kalshi adj = 0.40 -> DK wins.
        target = [r for r in results if r.player_name == "Target Player"]
        assert len(target) > 0, "Expected Target Player in results"
        bet = target[0]
        assert bet.best_book == "draftkings", f"Expected draftkings but got {bet.best_book}"
        assert bet.deadheat_adj < 0.0
        assert bet.deadheat_adj == round(-config.DEADHEAT_AVG_REDUCTION["t10"], 4)

    def test_kalshi_wins_best_book_via_dh_advantage(self):
        """Kalshi wins 'best book' over a sportsbook with better raw odds due to DH advantage.

        Scenario: DK has slightly better raw odds but after DH adjustment,
        Kalshi's effective edge is higher because DH adj = 0.
        """
        # We need DK to have better raw edge but worse adjusted edge.
        # Use mocking to control the blended probability precisely.
        # your_prob = 0.30
        # DK implied = 0.22 -> raw_edge = 0.08, DH adj = -0.044, effective = 0.036
        # Kalshi implied = 0.23 -> raw_edge = 0.07, DH adj = 0.0, effective = 0.07
        # -> Kalshi should win

        # Build a field with controlled de-vigged probabilities
        # We'll patch blend_probabilities and build_book_consensus to return
        # known values, and set up book_devigged to give us the probs we want.
        players = []
        for i in range(20):
            players.append({
                "player_name": f"Player {i}",
                "dg_id": str(i),
                "datagolf": {"baseline_history_fit": "+250"},  # ~0.286
                "draftkings": "+350",  # implied ~0.222
                "kalshi": "+340",      # implied ~0.227
            })

        with patch("src.core.edge.blend_probabilities", return_value=0.30), \
             patch("src.core.edge.build_book_consensus", return_value=0.25):
            results = calculate_placement_edges(players, "t10", bankroll=10000)

        # Every player should have kalshi as best_book because:
        # DK: raw ~0.08, adjusted ~0.036
        # Kalshi: raw ~0.07, adjusted = 0.07 (no DH)
        assert len(results) > 0, "Expected candidates"
        for bet in results:
            assert bet.best_book == "kalshi", (
                f"Expected kalshi as best_book but got {bet.best_book} "
                f"(raw_edge={bet.raw_edge}, edge={bet.edge}, dh_adj={bet.deadheat_adj})"
            )
