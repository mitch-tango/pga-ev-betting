diff --git a/config.py b/config.py
index 00bd366..d0bda86 100644
--- a/config.py
+++ b/config.py
@@ -115,6 +115,9 @@ DEADHEAT_AVG_REDUCTION = {
     "t20": 0.038,   # ~3.8%
 }
 
+# Books exempt from dead-heat adjustment (binary contract payout, no DH reduction)
+KALSHI_NO_DEADHEAT_BOOKS = {"kalshi"}
+
 # --- Signature Event ---
 SIGNATURE_PURSE_THRESHOLD = 20_000_000
 
diff --git a/planning/kalshi-integration/implementation/deep_implement_config.json b/planning/kalshi-integration/implementation/deep_implement_config.json
index 7db09eb..101da93 100644
--- a/planning/kalshi-integration/implementation/deep_implement_config.json
+++ b/planning/kalshi-integration/implementation/deep_implement_config.json
@@ -36,6 +36,10 @@
     "section-05-pipeline-pull": {
       "status": "complete",
       "commit_hash": "eb9cf9b"
+    },
+    "section-06-pipeline-merge": {
+      "status": "complete",
+      "commit_hash": "b7aeda5"
     }
   },
   "pre_commit": {
diff --git a/src/core/edge.py b/src/core/edge.py
index 01dc4c0..f977aad 100644
--- a/src/core/edge.py
+++ b/src/core/edge.py
@@ -206,11 +206,13 @@ def calculate_placement_edges(
         if your_prob is None or your_prob <= 0:
             continue
 
-        # Find the best book (highest edge = your_prob - book_implied_prob)
-        best_edge = -1
+        # Find the best book by adjusted edge (per-book dead-heat adjustment)
+        best_adjusted_edge = -1
         best_book = ""
         best_book_prob = 0
         best_decimal = 0
+        best_raw_edge = 0
+        best_dh_adj = 0.0
         all_odds = {}
 
         for book, devigged_list in book_devigged.items():
@@ -232,21 +234,27 @@ def calculate_placement_edges(
                 bettable_decimal = implied_prob_to_decimal(book_prob)
                 all_odds[book] = american_to_decimal(str(player.get(book, "")))
 
-            if raw_edge > best_edge:
-                best_edge = raw_edge
+            # Per-book dead-heat adjustment: Kalshi binary contracts
+            # pay full value on ties, so no DH reduction needed
+            if book in config.KALSHI_NO_DEADHEAT_BOOKS:
+                adj_edge = raw_edge
+                dh_adj = 0.0
+            else:
+                adj_edge, dh_adj = adjust_edge_for_deadheat(
+                    raw_edge, market_type, bettable_decimal)
+
+            if adj_edge > best_adjusted_edge:
+                best_adjusted_edge = adj_edge
                 best_book = book
                 best_book_prob = book_prob
                 best_decimal = bettable_decimal
+                best_raw_edge = raw_edge
+                best_dh_adj = dh_adj
 
-        if best_edge <= 0 or best_decimal is None:
+        if best_adjusted_edge <= 0 or best_decimal is None:
             continue
 
-        # Dead-heat adjustment
-        adjusted_edge, dh_adj = adjust_edge_for_deadheat(
-            best_edge, market_type, best_decimal
-        )
-
-        if adjusted_edge < min_edge:
+        if best_adjusted_edge < min_edge:
             continue
 
         # Correlation haircut
@@ -254,7 +262,7 @@ def calculate_placement_edges(
 
         # Kelly sizing
         stake = kelly_stake(
-            adjusted_edge, best_decimal, bankroll,
+            best_adjusted_edge, best_decimal, bankroll,
             correlation_haircut=haircut,
         )
 
@@ -272,10 +280,10 @@ def calculate_placement_edges(
             best_odds_decimal=round(best_decimal, 4),
             best_odds_american=decimal_to_american(best_decimal),
             best_implied_prob=round(best_book_prob, 4),
-            raw_edge=round(best_edge, 4),
-            deadheat_adj=round(dh_adj, 4),
-            edge=round(adjusted_edge, 4),
-            kelly_fraction=round(adjusted_edge / (best_decimal - 1), 4)
+            raw_edge=round(best_raw_edge, 4),
+            deadheat_adj=round(best_dh_adj, 4),
+            edge=round(best_adjusted_edge, 4),
+            kelly_fraction=round(best_adjusted_edge / (best_decimal - 1), 4)
                 if best_decimal > 1 else None,
             correlation_haircut=haircut,
             suggested_stake=stake,
diff --git a/tests/test_kalshi_edge.py b/tests/test_kalshi_edge.py
index e5e04c5..4f86e7d 100644
--- a/tests/test_kalshi_edge.py
+++ b/tests/test_kalshi_edge.py
@@ -1,5 +1,7 @@
 """Tests for Kalshi book weight configuration, consensus integration, and edge behavior."""
 
+from unittest.mock import patch
+
 import config
 from src.core.blend import build_book_consensus
 from src.core.devig import (
@@ -161,3 +163,106 @@ class TestKalshiAllBookOdds:
         mid_decimal = kalshi_price_to_decimal("0.05")
         ask_decimal = kalshi_price_to_decimal("0.06")
         assert ask_decimal < mid_decimal
+
+
+def _make_placement_field(num_players=20, dk_odds="+350", kalshi_odds="+340",
+                          dg_baseline=0.05):
+    """Helper: build a minimal outrights field for calculate_placement_edges."""
+    players = []
+    for i in range(num_players):
+        p = {
+            "player_name": f"Player {i}",
+            "dg_id": str(i),
+            "datagolf": {"baseline_history_fit": dg_baseline},
+            "draftkings": dk_odds,
+            "kalshi": kalshi_odds,
+        }
+        players.append(p)
+    return players
+
+
+class TestKalshiDeadHeatBypass:
+    """Dead-heat adjustment is skipped when best_book is Kalshi for placement markets."""
+
+    def test_kalshi_no_deadheat_books_config_exists(self):
+        """KALSHI_NO_DEADHEAT_BOOKS config set exists and contains 'kalshi'."""
+        assert hasattr(config, "KALSHI_NO_DEADHEAT_BOOKS")
+        assert "kalshi" in config.KALSHI_NO_DEADHEAT_BOOKS
+
+    def test_kalshi_t10_no_deadheat_adj(self):
+        """When best_book is 'kalshi' and market is t10, deadheat_adj should be 0.0."""
+        # Build field where Kalshi has the best raw edge so it wins best_book
+        players = _make_placement_field(
+            dk_odds="+500", kalshi_odds="+450", dg_baseline=0.04,
+        )
+        results = calculate_placement_edges(players, "t10", bankroll=10000)
+        kalshi_bets = [r for r in results if r.best_book == "kalshi"]
+        assert len(kalshi_bets) > 0, "Expected at least one bet with kalshi as best_book"
+        for bet in kalshi_bets:
+            assert bet.deadheat_adj == 0.0
+
+    def test_kalshi_t20_no_deadheat_adj(self):
+        """When best_book is 'kalshi' and market is t20, deadheat_adj should be 0.0."""
+        players = _make_placement_field(
+            dk_odds="+500", kalshi_odds="+450", dg_baseline=0.04,
+        )
+        results = calculate_placement_edges(players, "t20", bankroll=10000)
+        kalshi_bets = [r for r in results if r.best_book == "kalshi"]
+        assert len(kalshi_bets) > 0, "Expected at least one bet with kalshi as best_book"
+        for bet in kalshi_bets:
+            assert bet.deadheat_adj == 0.0
+
+    def test_sportsbook_t10_has_deadheat_adj(self):
+        """When best_book is 'draftkings' and market is t10, deadheat_adj < 0."""
+        # DK must have such a large raw edge advantage that it still wins
+        # after the DH penalty (~4.4%). DK at +800 (implied ~0.11) vs
+        # Kalshi at +300 (implied ~0.25) — DK raw edge is ~0.14 higher.
+        players = _make_placement_field(
+            dk_odds="+800", kalshi_odds="+300", dg_baseline=0.04,
+        )
+        results = calculate_placement_edges(players, "t10", bankroll=10000)
+        dk_bets = [r for r in results if r.best_book == "draftkings"]
+        assert len(dk_bets) > 0, "Expected at least one bet with draftkings as best_book"
+        for bet in dk_bets:
+            assert bet.deadheat_adj < 0.0
+            assert bet.deadheat_adj == round(-config.DEADHEAT_AVG_REDUCTION["t10"], 4)
+
+    def test_kalshi_wins_best_book_via_dh_advantage(self):
+        """Kalshi wins 'best book' over a sportsbook with better raw odds due to DH advantage.
+
+        Scenario: DK has slightly better raw odds but after DH adjustment,
+        Kalshi's effective edge is higher because DH adj = 0.
+        """
+        # We need DK to have better raw edge but worse adjusted edge.
+        # Use mocking to control the blended probability precisely.
+        # your_prob = 0.30
+        # DK implied = 0.22 -> raw_edge = 0.08, DH adj = -0.044, effective = 0.036
+        # Kalshi implied = 0.23 -> raw_edge = 0.07, DH adj = 0.0, effective = 0.07
+        # -> Kalshi should win
+
+        # Build a field with controlled de-vigged probabilities
+        # We'll patch blend_probabilities and build_book_consensus to return
+        # known values, and set up book_devigged to give us the probs we want.
+        players = []
+        for i in range(20):
+            players.append({
+                "player_name": f"Player {i}",
+                "dg_id": str(i),
+                "datagolf": {"baseline_history_fit": "+250"},  # ~0.286
+                "draftkings": "+350",  # implied ~0.222
+                "kalshi": "+340",      # implied ~0.227
+            })
+
+        with patch("src.core.edge.blend_probabilities", return_value=0.30), \
+             patch("src.core.edge.build_book_consensus", return_value=0.25):
+            results = calculate_placement_edges(players, "t10", bankroll=10000)
+
+        # Every player should have kalshi as best_book because:
+        # DK: raw ~0.08, adjusted ~0.036
+        # Kalshi: raw ~0.07, adjusted = 0.07 (no DH)
+        assert len(results) > 0, "Expected candidates"
+        for bet in results:
+            assert bet.best_book == "kalshi", (
+                f"Expected kalshi as best_book but got {bet.best_book} "
+                f"(raw_edge={bet.raw_edge}, edge={bet.edge}, dh_adj={bet.deadheat_adj})"
+            )
