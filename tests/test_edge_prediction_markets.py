"""Tests for generalized edge calculation with multiple prediction markets.

Validates that edge.py:
1. Uses NO_DEADHEAT_BOOKS_BY_MARKET (not a flat set)
2. Generalizes ask-based pricing via _{book}_ask_prob pattern
3. Validates ask probability values
"""
from __future__ import annotations

import logging

import config
from src.core.edge import calculate_placement_edges
from src.core.devig import binary_price_to_decimal, american_to_decimal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Spread of longshot odds for filler — ensures the target (at favorable DG
# odds) has a large positive edge vs the book's de-vigged probabilities.
_FILLER_ODDS = [
    "+800", "+900", "+1000", "+1200", "+1400",
    "+1600", "+1800", "+2000", "+2500", "+3000",
    "+3500", "+4000", "+5000", "+6000",
]


def _make_field(target: dict, book_name: str | None = None) -> list[dict]:
    """Build a 15-player field where the target book has odds for ALL players.

    The target player gets favorable DG odds vs worse book odds so the
    edge exceeds the t10 threshold (6%).
    """
    filler = []
    for i in range(14):
        player = {
            "player_name": f"Filler {i + 2}",
            "dg_id": str(1000 + i),
            "datagolf": {"baseline_history_fit": _FILLER_ODDS[i]},
            "draftkings": _FILLER_ODDS[i],
        }
        if book_name:
            player[book_name] = _FILLER_ODDS[i]
        filler.append(player)
    return [target] + filler


# ---------------------------------------------------------------------------
# Dead-heat bypass
# ---------------------------------------------------------------------------

class TestDeadHeatBypass:
    """NO_DEADHEAT_BOOKS_BY_MARKET controls which books skip dead-heat
    reduction per market type. Books whose book_rules tie_rule is 'win'
    pay ties in full and must not be penalised by the DH haircut."""

    def test_config_has_no_deadheat_books_by_market(self):
        assert hasattr(config, "NO_DEADHEAT_BOOKS_BY_MARKET")
        for mkt in ("t5", "t10", "t20"):
            assert "kalshi" in config.NO_DEADHEAT_BOOKS_BY_MARKET[mkt]
            assert "polymarket" in config.NO_DEADHEAT_BOOKS_BY_MARKET[mkt]

    def test_polymarket_skips_deadheat(self):
        """Polymarket is in NO_DEADHEAT_BOOKS_BY_MARKET -> deadheat_adj == 0.0."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},  # DG bullish (~40%)
            "polymarket": "+600",  # Book sees ~14%
            "_polymarket_ask_prob": 0.15,
        }
        field = _make_field(target, book_name="polymarket")
        results = calculate_placement_edges(field, market_type="t10")
        poly_bets = [c for c in results if c.best_book == "polymarket"]
        assert len(poly_bets) > 0, "Expected at least one polymarket bet"
        assert poly_bets[0].deadheat_adj == 0.0

    def test_prophetx_skips_deadheat(self):
        """ProphetX is a binary-contract exchange (book_rules.tie_rule='win')
        so it should skip dead-heat reduction just like kalshi/polymarket."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "prophetx": "+600",
            "_prophetx_ask_prob": 0.15,
        }
        field = _make_field(target, book_name="prophetx")
        results = calculate_placement_edges(field, market_type="t10")
        px_bets = [c for c in results if c.best_book == "prophetx"]
        assert len(px_bets) > 0, "Expected at least one prophetx bet"
        assert px_bets[0].deadheat_adj == 0.0

    def test_betmgm_skips_deadheat_on_placement(self):
        """BetMGM pays ties in full on placement markets (book_rules
        t10 tie_rule='win', notes: 'pays ties in full on placement
        markets'). Dead-heat adj must be zero for BetMGM on T10/T20."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "betmgm": "+600",
        }
        field = _make_field(target, book_name="betmgm")
        results = calculate_placement_edges(field, market_type="t10")
        bmgm_bets = [c for c in results if c.best_book == "betmgm"]
        assert len(bmgm_bets) > 0, "Expected at least one betmgm bet"
        assert bmgm_bets[0].deadheat_adj == 0.0

    def test_pinnacle_skips_deadheat_on_placement(self):
        """Pinnacle pays ties in full on placement markets (book_rules
        t10 tie_rule='win')."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "pinnacle": "+600",
        }
        field = _make_field(target, book_name="pinnacle")
        results = calculate_placement_edges(field, market_type="t10")
        pin_bets = [c for c in results if c.best_book == "pinnacle"]
        assert len(pin_bets) > 0, "Expected at least one pinnacle bet"
        assert pin_bets[0].deadheat_adj == 0.0

    def test_draftkings_applies_deadheat(self):
        """DraftKings applies standard dead-heat on placement ties
        (book_rules t10 tie_rule='dead_heat'). This is the regression
        check that the exemption doesn't accidentally include books
        that do apply dead-heat."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "draftkings": "+600",
        }
        field = _make_field(target, book_name="draftkings")
        results = calculate_placement_edges(field, market_type="t10")
        dk_bets = [c for c in results if c.best_book == "draftkings"]
        assert len(dk_bets) > 0, "Expected at least one draftkings bet"
        assert dk_bets[0].deadheat_adj != 0.0

    def test_kalshi_still_skips_deadheat_regression(self):
        """Kalshi remains exempt (regression)."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "kalshi": "+600",
            "_kalshi_ask_prob": 0.15,
        }
        field = _make_field(target, book_name="kalshi")
        results = calculate_placement_edges(field, market_type="t10")
        kalshi_bets = [c for c in results if c.best_book == "kalshi"]
        assert len(kalshi_bets) > 0, "Expected at least one kalshi bet"
        assert kalshi_bets[0].deadheat_adj == 0.0


# ---------------------------------------------------------------------------
# Generalized ask-based pricing
# ---------------------------------------------------------------------------

class TestAskBasedPricing:
    """_{book}_ask_prob keys drive bettable decimal for any book."""

    def test_polymarket_ask_prob_used(self):
        """best_odds_decimal should use binary_price_to_decimal(_polymarket_ask_prob)."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "polymarket": "+600",
            "_polymarket_ask_prob": 0.15,
        }
        field = _make_field(target, book_name="polymarket")
        results = calculate_placement_edges(field, market_type="t10")
        poly_bets = [c for c in results if c.best_book == "polymarket"]
        assert len(poly_bets) > 0, "Expected at least one polymarket bet"
        expected = binary_price_to_decimal("0.15")
        assert poly_bets[0].best_odds_decimal == round(expected, 4)

    def test_prophetx_ask_prob_used(self):
        """best_odds_decimal should use binary_price_to_decimal(_prophetx_ask_prob)."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "prophetx": "+600",
            "_prophetx_ask_prob": 0.15,
        }
        field = _make_field(target, book_name="prophetx")
        results = calculate_placement_edges(field, market_type="t10")
        px_bets = [c for c in results if c.best_book == "prophetx"]
        assert len(px_bets) > 0, "Expected at least one prophetx bet"
        expected = binary_price_to_decimal("0.15")
        assert px_bets[0].best_odds_decimal == round(expected, 4)

    def test_kalshi_ask_prob_regression(self):
        """Kalshi ask prob still works with generic pattern."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "kalshi": "+1900",
            "_kalshi_ask_prob": 0.06,
        }
        field = _make_field(target, book_name="kalshi")
        results = calculate_placement_edges(field, market_type="t10")
        kalshi_bets = [c for c in results if c.best_book == "kalshi"]
        assert len(kalshi_bets) > 0, "Expected at least one kalshi bet"
        expected = binary_price_to_decimal("0.06")
        assert kalshi_bets[0].best_odds_decimal == round(expected, 4)

    def test_traditional_book_no_ask_key(self):
        """Books without _{book}_ask_prob use standard american_to_decimal."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "draftkings": "+600",
        }
        field = _make_field(target)
        results = calculate_placement_edges(field, market_type="t10")
        dk_bets = [c for c in results if c.best_book == "draftkings"]
        assert len(dk_bets) > 0, "Expected at least one draftkings bet"
        expected = american_to_decimal("+600")
        assert dk_bets[0].all_book_odds.get("draftkings") == expected

    def test_invalid_ask_prob_too_high(self, caplog):
        """ask_prob > 1 falls back to standard pricing, does not crash."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "polymarket": "+600",
            "_polymarket_ask_prob": 1.5,
        }
        field = _make_field(target, book_name="polymarket")
        with caplog.at_level(logging.WARNING):
            results = calculate_placement_edges(field, market_type="t10")
        assert isinstance(results, list)
        assert any("Invalid _polymarket_ask_prob" in r.message for r in caplog.records)

    def test_invalid_ask_prob_not_numeric(self, caplog):
        """Non-numeric ask_prob falls back to standard pricing."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "polymarket": "+600",
            "_polymarket_ask_prob": "not_a_number",
        }
        field = _make_field(target, book_name="polymarket")
        with caplog.at_level(logging.WARNING):
            results = calculate_placement_edges(field, market_type="t10")
        assert isinstance(results, list)
        assert any("Invalid _polymarket_ask_prob" in r.message for r in caplog.records)

    def test_fee_already_reflected_in_ask_prob(self):
        """Fee-adjusted ask prob used directly — no further deduction."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "polymarket": "+600",
            "_polymarket_ask_prob": 0.152,  # 0.15 ask + 0.002 fee
        }
        field = _make_field(target, book_name="polymarket")
        results = calculate_placement_edges(field, market_type="t10")
        poly_bets = [c for c in results if c.best_book == "polymarket"]
        assert len(poly_bets) > 0, "Expected polymarket bet"
        expected = binary_price_to_decimal("0.152")
        assert poly_bets[0].best_odds_decimal == round(expected, 4)


# ---------------------------------------------------------------------------
# Consensus / multi-market
# ---------------------------------------------------------------------------

class TestMultiMarketConsensus:
    """Verify BOOK_WEIGHTS includes prediction markets and pipeline doesn't crash."""

    def test_book_weights_include_prediction_markets(self):
        assert "polymarket" in config.BOOK_WEIGHTS["win"]
        assert "prophetx" in config.BOOK_WEIGHTS["win"]

    def test_no_crash_with_zero_prediction_markets(self):
        """DG-only field (no prediction market odds) runs without error."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "draftkings": "+600",
        }
        field = _make_field(target)
        results = calculate_placement_edges(field, market_type="t10")
        assert isinstance(results, list)

    def test_no_crash_with_all_three_markets(self):
        """Field with kalshi + polymarket + prophetx runs without error."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "draftkings": "+500",
            "kalshi": "+600",
            "_kalshi_ask_prob": 0.15,
            "polymarket": "+600",
            "_polymarket_ask_prob": 0.152,
            "prophetx": "+550",
            "_prophetx_ask_prob": 0.16,
        }
        filler = []
        for i in range(14):
            filler.append({
                "player_name": f"Filler {i + 2}",
                "dg_id": str(1000 + i),
                "datagolf": {"baseline_history_fit": _FILLER_ODDS[i]},
                "draftkings": _FILLER_ODDS[i],
                "kalshi": _FILLER_ODDS[i],
                "polymarket": _FILLER_ODDS[i],
                "prophetx": _FILLER_ODDS[i],
            })
        field = [target] + filler
        results = calculate_placement_edges(field, market_type="t10")
        assert isinstance(results, list)

    def test_no_crash_with_partial_markets(self):
        """Only polymarket present (no kalshi/prophetx) still works."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "polymarket": "+600",
            "_polymarket_ask_prob": 0.15,
        }
        field = _make_field(target, book_name="polymarket")
        results = calculate_placement_edges(field, market_type="t10")
        assert isinstance(results, list)
