"""Tests for exchange_only mode in edge.py and EXCHANGE_BOOKS config."""

import config
from src.core.edge import calculate_placement_edges


# Spread of longshot odds for filler
_FILLER_ODDS = [
    "+800", "+900", "+1000", "+1200", "+1400",
    "+1600", "+1800", "+2000", "+2500", "+3000",
    "+3500", "+4000", "+5000", "+6000",
]


def _make_field(target: dict, book_names: list[str] | None = None) -> list[dict]:
    """Build a 15-player field with odds on the given books."""
    book_names = book_names or []
    filler = []
    for i in range(14):
        player = {
            "player_name": f"Filler {i + 2}",
            "dg_id": str(1000 + i),
            "datagolf": {"baseline_history_fit": _FILLER_ODDS[i]},
        }
        for bk in book_names:
            player[bk] = _FILLER_ODDS[i]
        filler.append(player)
    return [target] + filler


class TestExchangeBooksConfig:
    """EXCHANGE_BOOKS constant exists and has expected members."""

    def test_exchange_books_exists(self):
        assert hasattr(config, "EXCHANGE_BOOKS")

    def test_contains_kalshi(self):
        assert "kalshi" in config.EXCHANGE_BOOKS

    def test_contains_polymarket(self):
        assert "polymarket" in config.EXCHANGE_BOOKS

    def test_contains_prophetx(self):
        assert "prophetx" in config.EXCHANGE_BOOKS

    def test_does_not_contain_sportsbooks(self):
        for book in ["draftkings", "fanduel", "betmgm", "caesars"]:
            assert book not in config.EXCHANGE_BOOKS


class TestExchangeOnlyMode:
    """exchange_only=True restricts edge calculation to exchange books."""

    def test_sportsbook_excluded_in_exchange_only(self):
        """DraftKings edge should NOT appear when exchange_only=True."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "draftkings": "+600",
        }
        field = _make_field(target, book_names=["draftkings"])
        results = calculate_placement_edges(
            field, market_type="t10", exchange_only=True)
        dk_bets = [c for c in results if c.best_book == "draftkings"]
        assert len(dk_bets) == 0, "DraftKings should be excluded in exchange_only mode"

    def test_exchange_included_in_exchange_only(self):
        """Kalshi edge should still appear when exchange_only=True."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "kalshi": "+600",
            "_kalshi_ask_prob": 0.15,
        }
        field = _make_field(target, book_names=["kalshi"])
        results = calculate_placement_edges(
            field, market_type="t10", exchange_only=True)
        kalshi_bets = [c for c in results if c.best_book == "kalshi"]
        assert len(kalshi_bets) > 0, "Kalshi should be included in exchange_only mode"

    def test_sportsbook_included_without_exchange_only(self):
        """DraftKings edge should appear when exchange_only=False (default)."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "draftkings": "+600",
        }
        field = _make_field(target, book_names=["draftkings"])
        results = calculate_placement_edges(
            field, market_type="t10", exchange_only=False)
        dk_bets = [c for c in results if c.best_book == "draftkings"]
        assert len(dk_bets) > 0, "DraftKings should be included when exchange_only is False"

    def test_mixed_books_exchange_only_filters_correctly(self):
        """With both DK and Polymarket, only Polymarket should produce edges."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "draftkings": "+600",
            "polymarket": "+600",
            "_polymarket_ask_prob": 0.15,
        }
        field = _make_field(target, book_names=["draftkings", "polymarket"])
        results = calculate_placement_edges(
            field, market_type="t10", exchange_only=True)
        books = {c.best_book for c in results}
        assert "draftkings" not in books, "DraftKings should be filtered out"
        # Polymarket may or may not produce an edge depending on de-vig,
        # but DraftKings must not be present

    def test_exchange_only_default_is_false(self):
        """Default behavior (no exchange_only) should include sportsbooks."""
        target = {
            "player_name": "Scottie Scheffler",
            "dg_id": "18417",
            "datagolf": {"baseline_history_fit": "+150"},
            "draftkings": "+600",
        }
        field = _make_field(target, book_names=["draftkings"])
        results = calculate_placement_edges(field, market_type="t10")
        dk_bets = [c for c in results if c.best_book == "draftkings"]
        assert len(dk_bets) > 0, "DraftKings should be included by default"
