diff --git a/config.py b/config.py
index 7aab8d2..da58b00 100644
--- a/config.py
+++ b/config.py
@@ -164,7 +164,6 @@ DEADHEAT_AVG_REDUCTION = {
 
 # Books exempt from dead-heat adjustment (binary contract payout, no DH reduction)
 NO_DEADHEAT_BOOKS = {"kalshi", "polymarket"}
-KALSHI_NO_DEADHEAT_BOOKS = NO_DEADHEAT_BOOKS  # Deprecated alias — removed in section 03
 
 # --- Signature Event ---
 SIGNATURE_PURSE_THRESHOLD = 20_000_000
diff --git a/planning/prediction-markets/implementation/deep_implement_config.json b/planning/prediction-markets/implementation/deep_implement_config.json
index 56395c6..c71d736 100644
--- a/planning/prediction-markets/implementation/deep_implement_config.json
+++ b/planning/prediction-markets/implementation/deep_implement_config.json
@@ -23,6 +23,10 @@
     "section-01-config": {
       "status": "complete",
       "commit_hash": "d9221b9"
+    },
+    "section-02-devig-refactor": {
+      "status": "complete",
+      "commit_hash": "ae995e0"
     }
   },
   "pre_commit": {
diff --git a/src/core/edge.py b/src/core/edge.py
index f977aad..a1eed82 100644
--- a/src/core/edge.py
+++ b/src/core/edge.py
@@ -19,12 +19,16 @@ ready for insertion into the candidate_bets Supabase table.
 from dataclasses import dataclass, asdict
 from typing import Any
 
+import logging
+
 from src.core.devig import (
     parse_american_odds, american_to_decimal, decimal_to_american,
     implied_prob_to_decimal, power_devig, devig_independent,
     devig_two_way, devig_three_way,
-    kalshi_price_to_decimal,
+    binary_price_to_decimal,
 )
+
+logger = logging.getLogger(__name__)
 from src.core.blend import blend_probabilities, build_book_consensus
 from src.core.kelly import kelly_stake, get_correlation_haircut
 from src.core.settlement import adjust_edge_for_deadheat
@@ -224,19 +228,28 @@ def calculate_placement_edges(
 
             raw_edge = your_prob - book_prob
 
-            # For Kalshi, use ask-based decimal (actual bettable price)
-            # for both Kelly sizing and all_book_odds display
-            if book == "kalshi" and "_kalshi_ask_prob" in player:
-                bettable_decimal = kalshi_price_to_decimal(
-                    str(player["_kalshi_ask_prob"]))
-                all_odds[book] = bettable_decimal
+            # For prediction markets with ask-based pricing, use the
+            # _{book}_ask_prob value for bettable decimal (actual cost).
+            # This covers kalshi, polymarket, prophetx, and any future market.
+            ask_key = f"_{book}_ask_prob"
+            if ask_key in player:
+                ask_val = player[ask_key]
+                if isinstance(ask_val, (int, float)) and 0 < float(ask_val) < 1:
+                    bettable_decimal = binary_price_to_decimal(str(ask_val))
+                    all_odds[book] = bettable_decimal
+                else:
+                    logger.warning(
+                        "Invalid %s value %r for %s, using standard pricing",
+                        ask_key, ask_val, player.get("player_name", "unknown"))
+                    bettable_decimal = implied_prob_to_decimal(book_prob)
+                    all_odds[book] = american_to_decimal(str(player.get(book, "")))
             else:
                 bettable_decimal = implied_prob_to_decimal(book_prob)
                 all_odds[book] = american_to_decimal(str(player.get(book, "")))
 
-            # Per-book dead-heat adjustment: Kalshi binary contracts
+            # Per-book dead-heat adjustment: binary contract markets
             # pay full value on ties, so no DH reduction needed
-            if book in config.KALSHI_NO_DEADHEAT_BOOKS:
+            if book in config.NO_DEADHEAT_BOOKS:
                 adj_edge = raw_edge
                 dh_adj = 0.0
             else:
diff --git a/tests/test_config_prediction_markets.py b/tests/test_config_prediction_markets.py
index 636dde2..7205189 100644
--- a/tests/test_config_prediction_markets.py
+++ b/tests/test_config_prediction_markets.py
@@ -123,10 +123,10 @@ class TestNoDeadheatBooks:
         import config
         assert "prophetx" not in config.NO_DEADHEAT_BOOKS
 
-    def test_deprecated_alias_still_works(self):
-        """Backward compat: KALSHI_NO_DEADHEAT_BOOKS still exists."""
+    def test_deprecated_alias_removed(self):
+        """KALSHI_NO_DEADHEAT_BOOKS alias was removed in section 03."""
         import config
-        assert config.KALSHI_NO_DEADHEAT_BOOKS is config.NO_DEADHEAT_BOOKS
+        assert not hasattr(config, "KALSHI_NO_DEADHEAT_BOOKS")
 
 
 class TestPolymarketConstants:
diff --git a/tests/test_edge_prediction_markets.py b/tests/test_edge_prediction_markets.py
new file mode 100644
index 0000000..5c9adef
--- /dev/null
+++ b/tests/test_edge_prediction_markets.py
@@ -0,0 +1,285 @@
+"""Tests for generalized edge calculation with multiple prediction markets.
+
+Validates that edge.py:
+1. Uses NO_DEADHEAT_BOOKS (not KALSHI_NO_DEADHEAT_BOOKS)
+2. Generalizes ask-based pricing via _{book}_ask_prob pattern
+3. Validates ask probability values
+"""
+
+import logging
+
+import config
+from src.core.edge import calculate_placement_edges
+from src.core.devig import binary_price_to_decimal, american_to_decimal
+
+
+# ---------------------------------------------------------------------------
+# Helpers
+# ---------------------------------------------------------------------------
+
+# Spread of longshot odds for filler — ensures the target (at favorable DG
+# odds) has a large positive edge vs the book's de-vigged probabilities.
+_FILLER_ODDS = [
+    "+800", "+900", "+1000", "+1200", "+1400",
+    "+1600", "+1800", "+2000", "+2500", "+3000",
+    "+3500", "+4000", "+5000", "+6000",
+]
+
+
+def _make_field(target: dict, book_name: str | None = None) -> list[dict]:
+    """Build a 15-player field where the target book has odds for ALL players.
+
+    The target player gets favorable DG odds vs worse book odds so the
+    edge exceeds the t10 threshold (6%).
+    """
+    filler = []
+    for i in range(14):
+        player = {
+            "player_name": f"Filler {i + 2}",
+            "dg_id": str(1000 + i),
+            "datagolf": {"baseline_history_fit": _FILLER_ODDS[i]},
+            "draftkings": _FILLER_ODDS[i],
+        }
+        if book_name:
+            player[book_name] = _FILLER_ODDS[i]
+        filler.append(player)
+    return [target] + filler
+
+
+# ---------------------------------------------------------------------------
+# Dead-heat bypass
+# ---------------------------------------------------------------------------
+
+class TestDeadHeatBypass:
+    """NO_DEADHEAT_BOOKS controls which books skip dead-heat reduction."""
+
+    def test_config_has_no_deadheat_books(self):
+        assert hasattr(config, "NO_DEADHEAT_BOOKS")
+        assert "kalshi" in config.NO_DEADHEAT_BOOKS
+        assert "polymarket" in config.NO_DEADHEAT_BOOKS
+
+    def test_polymarket_skips_deadheat(self):
+        """Polymarket is in NO_DEADHEAT_BOOKS -> deadheat_adj == 0.0."""
+        target = {
+            "player_name": "Scottie Scheffler",
+            "dg_id": "18417",
+            "datagolf": {"baseline_history_fit": "+150"},  # DG bullish (~40%)
+            "polymarket": "+600",  # Book sees ~14%
+            "_polymarket_ask_prob": 0.15,
+        }
+        field = _make_field(target, book_name="polymarket")
+        results = calculate_placement_edges(field, market_type="t10")
+        poly_bets = [c for c in results if c.best_book == "polymarket"]
+        assert len(poly_bets) > 0, "Expected at least one polymarket bet"
+        assert poly_bets[0].deadheat_adj == 0.0
+
+    def test_prophetx_applies_deadheat(self):
+        """ProphetX is NOT in NO_DEADHEAT_BOOKS -> deadheat_adj != 0."""
+        target = {
+            "player_name": "Scottie Scheffler",
+            "dg_id": "18417",
+            "datagolf": {"baseline_history_fit": "+150"},
+            "prophetx": "+600",
+            "_prophetx_ask_prob": 0.15,
+        }
+        field = _make_field(target, book_name="prophetx")
+        results = calculate_placement_edges(field, market_type="t10")
+        px_bets = [c for c in results if c.best_book == "prophetx"]
+        assert len(px_bets) > 0, "Expected at least one prophetx bet"
+        assert px_bets[0].deadheat_adj != 0.0
+
+    def test_kalshi_still_skips_deadheat_regression(self):
+        """Kalshi remains in NO_DEADHEAT_BOOKS (regression)."""
+        target = {
+            "player_name": "Scottie Scheffler",
+            "dg_id": "18417",
+            "datagolf": {"baseline_history_fit": "+150"},
+            "kalshi": "+600",
+            "_kalshi_ask_prob": 0.15,
+        }
+        field = _make_field(target, book_name="kalshi")
+        results = calculate_placement_edges(field, market_type="t10")
+        kalshi_bets = [c for c in results if c.best_book == "kalshi"]
+        assert len(kalshi_bets) > 0, "Expected at least one kalshi bet"
+        assert kalshi_bets[0].deadheat_adj == 0.0
+
+
+# ---------------------------------------------------------------------------
+# Generalized ask-based pricing
+# ---------------------------------------------------------------------------
+
+class TestAskBasedPricing:
+    """_{book}_ask_prob keys drive bettable decimal for any book."""
+
+    def test_polymarket_ask_prob_used(self):
+        """best_odds_decimal should use binary_price_to_decimal(_polymarket_ask_prob)."""
+        target = {
+            "player_name": "Scottie Scheffler",
+            "dg_id": "18417",
+            "datagolf": {"baseline_history_fit": "+150"},
+            "polymarket": "+600",
+            "_polymarket_ask_prob": 0.15,
+        }
+        field = _make_field(target, book_name="polymarket")
+        results = calculate_placement_edges(field, market_type="t10")
+        poly_bets = [c for c in results if c.best_book == "polymarket"]
+        assert len(poly_bets) > 0, "Expected at least one polymarket bet"
+        expected = binary_price_to_decimal("0.15")
+        assert poly_bets[0].best_odds_decimal == round(expected, 4)
+
+    def test_prophetx_ask_prob_used(self):
+        """best_odds_decimal should use binary_price_to_decimal(_prophetx_ask_prob)."""
+        target = {
+            "player_name": "Scottie Scheffler",
+            "dg_id": "18417",
+            "datagolf": {"baseline_history_fit": "+150"},
+            "prophetx": "+600",
+            "_prophetx_ask_prob": 0.15,
+        }
+        field = _make_field(target, book_name="prophetx")
+        results = calculate_placement_edges(field, market_type="t10")
+        px_bets = [c for c in results if c.best_book == "prophetx"]
+        assert len(px_bets) > 0, "Expected at least one prophetx bet"
+        expected = binary_price_to_decimal("0.15")
+        assert px_bets[0].best_odds_decimal == round(expected, 4)
+
+    def test_kalshi_ask_prob_regression(self):
+        """Kalshi ask prob still works with generic pattern."""
+        target = {
+            "player_name": "Scottie Scheffler",
+            "dg_id": "18417",
+            "datagolf": {"baseline_history_fit": "+150"},
+            "kalshi": "+1900",
+            "_kalshi_ask_prob": 0.06,
+        }
+        field = _make_field(target, book_name="kalshi")
+        results = calculate_placement_edges(field, market_type="t10")
+        kalshi_bets = [c for c in results if c.best_book == "kalshi"]
+        assert len(kalshi_bets) > 0, "Expected at least one kalshi bet"
+        expected = binary_price_to_decimal("0.06")
+        assert kalshi_bets[0].best_odds_decimal == round(expected, 4)
+
+    def test_traditional_book_no_ask_key(self):
+        """Books without _{book}_ask_prob use standard american_to_decimal."""
+        target = {
+            "player_name": "Scottie Scheffler",
+            "dg_id": "18417",
+            "datagolf": {"baseline_history_fit": "+150"},
+            "draftkings": "+600",
+        }
+        field = _make_field(target)
+        results = calculate_placement_edges(field, market_type="t10")
+        dk_bets = [c for c in results if c.best_book == "draftkings"]
+        assert len(dk_bets) > 0, "Expected at least one draftkings bet"
+        expected = american_to_decimal("+600")
+        assert dk_bets[0].all_book_odds.get("draftkings") == expected
+
+    def test_invalid_ask_prob_too_high(self, caplog):
+        """ask_prob > 1 falls back to standard pricing, does not crash."""
+        target = {
+            "player_name": "Scottie Scheffler",
+            "dg_id": "18417",
+            "datagolf": {"baseline_history_fit": "+150"},
+            "polymarket": "+600",
+            "_polymarket_ask_prob": 1.5,
+        }
+        field = _make_field(target, book_name="polymarket")
+        with caplog.at_level(logging.WARNING):
+            results = calculate_placement_edges(field, market_type="t10")
+        assert isinstance(results, list)
+
+    def test_invalid_ask_prob_not_numeric(self, caplog):
+        """Non-numeric ask_prob falls back to standard pricing."""
+        target = {
+            "player_name": "Scottie Scheffler",
+            "dg_id": "18417",
+            "datagolf": {"baseline_history_fit": "+150"},
+            "polymarket": "+600",
+            "_polymarket_ask_prob": "not_a_number",
+        }
+        field = _make_field(target, book_name="polymarket")
+        with caplog.at_level(logging.WARNING):
+            results = calculate_placement_edges(field, market_type="t10")
+        assert isinstance(results, list)
+
+    def test_fee_already_reflected_in_ask_prob(self):
+        """Fee-adjusted ask prob used directly — no further deduction."""
+        target = {
+            "player_name": "Scottie Scheffler",
+            "dg_id": "18417",
+            "datagolf": {"baseline_history_fit": "+150"},
+            "polymarket": "+600",
+            "_polymarket_ask_prob": 0.152,  # 0.15 ask + 0.002 fee
+        }
+        field = _make_field(target, book_name="polymarket")
+        results = calculate_placement_edges(field, market_type="t10")
+        poly_bets = [c for c in results if c.best_book == "polymarket"]
+        assert len(poly_bets) > 0, "Expected polymarket bet"
+        expected = binary_price_to_decimal("0.152")
+        assert poly_bets[0].best_odds_decimal == round(expected, 4)
+
+
+# ---------------------------------------------------------------------------
+# Consensus / multi-market
+# ---------------------------------------------------------------------------
+
+class TestMultiMarketConsensus:
+    """Verify BOOK_WEIGHTS includes prediction markets and pipeline doesn't crash."""
+
+    def test_book_weights_include_prediction_markets(self):
+        assert "polymarket" in config.BOOK_WEIGHTS["win"]
+        assert "prophetx" in config.BOOK_WEIGHTS["win"]
+
+    def test_no_crash_with_zero_prediction_markets(self):
+        """DG-only field (no prediction market odds) runs without error."""
+        target = {
+            "player_name": "Scottie Scheffler",
+            "dg_id": "18417",
+            "datagolf": {"baseline_history_fit": "+150"},
+            "draftkings": "+600",
+        }
+        field = _make_field(target)
+        results = calculate_placement_edges(field, market_type="t10")
+        assert isinstance(results, list)
+
+    def test_no_crash_with_all_three_markets(self):
+        """Field with kalshi + polymarket + prophetx runs without error."""
+        target = {
+            "player_name": "Scottie Scheffler",
+            "dg_id": "18417",
+            "datagolf": {"baseline_history_fit": "+150"},
+            "draftkings": "+500",
+            "kalshi": "+600",
+            "_kalshi_ask_prob": 0.15,
+            "polymarket": "+600",
+            "_polymarket_ask_prob": 0.152,
+            "prophetx": "+550",
+            "_prophetx_ask_prob": 0.16,
+        }
+        filler = []
+        for i in range(14):
+            filler.append({
+                "player_name": f"Filler {i + 2}",
+                "dg_id": str(1000 + i),
+                "datagolf": {"baseline_history_fit": _FILLER_ODDS[i]},
+                "draftkings": _FILLER_ODDS[i],
+                "kalshi": _FILLER_ODDS[i],
+                "polymarket": _FILLER_ODDS[i],
+                "prophetx": _FILLER_ODDS[i],
+            })
+        field = [target] + filler
+        results = calculate_placement_edges(field, market_type="t10")
+        assert isinstance(results, list)
+
+    def test_no_crash_with_partial_markets(self):
+        """Only polymarket present (no kalshi/prophetx) still works."""
+        target = {
+            "player_name": "Scottie Scheffler",
+            "dg_id": "18417",
+            "datagolf": {"baseline_history_fit": "+150"},
+            "polymarket": "+600",
+            "_polymarket_ask_prob": 0.15,
+        }
+        field = _make_field(target, book_name="polymarket")
+        results = calculate_placement_edges(field, market_type="t10")
+        assert isinstance(results, list)
diff --git a/tests/test_kalshi_edge.py b/tests/test_kalshi_edge.py
index ad9c2c3..a4f6e90 100644
--- a/tests/test_kalshi_edge.py
+++ b/tests/test_kalshi_edge.py
@@ -190,9 +190,9 @@ class TestKalshiDeadHeatBypass:
     """Dead-heat adjustment is skipped when best_book is Kalshi for placement markets."""
 
     def test_kalshi_no_deadheat_books_config_exists(self):
-        """KALSHI_NO_DEADHEAT_BOOKS config set exists and contains 'kalshi'."""
-        assert hasattr(config, "KALSHI_NO_DEADHEAT_BOOKS")
-        assert "kalshi" in config.KALSHI_NO_DEADHEAT_BOOKS
+        """NO_DEADHEAT_BOOKS config set exists and contains 'kalshi'."""
+        assert hasattr(config, "NO_DEADHEAT_BOOKS")
+        assert "kalshi" in config.NO_DEADHEAT_BOOKS
 
     def test_kalshi_t10_no_deadheat_adj(self):
         """When best_book is 'kalshi' and market is t10, deadheat_adj should be 0.0."""
