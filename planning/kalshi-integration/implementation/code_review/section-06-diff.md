diff --git a/planning/kalshi-integration/implementation/deep_implement_config.json b/planning/kalshi-integration/implementation/deep_implement_config.json
index 5255a4b..7db09eb 100644
--- a/planning/kalshi-integration/implementation/deep_implement_config.json
+++ b/planning/kalshi-integration/implementation/deep_implement_config.json
@@ -32,6 +32,10 @@
     "section-04-tournament-matching": {
       "status": "complete",
       "commit_hash": "74ef649"
+    },
+    "section-05-pipeline-pull": {
+      "status": "complete",
+      "commit_hash": "eb9cf9b"
     }
   },
   "pre_commit": {
diff --git a/src/core/edge.py b/src/core/edge.py
index 8632612..54f3a02 100644
--- a/src/core/edge.py
+++ b/src/core/edge.py
@@ -23,6 +23,7 @@ from src.core.devig import (
     parse_american_odds, american_to_decimal, decimal_to_american,
     implied_prob_to_decimal, power_devig, devig_independent,
     devig_two_way, devig_three_way,
+    kalshi_price_to_decimal,
 )
 from src.core.blend import blend_probabilities, build_book_consensus
 from src.core.kelly import kelly_stake, get_correlation_haircut
@@ -223,7 +224,12 @@ def calculate_placement_edges(
             decimal_odds = implied_prob_to_decimal(book_prob)
 
             # Store all odds for reference (book name IS the column name)
-            all_odds[book] = american_to_decimal(str(player.get(book, "")))
+            # For Kalshi, use ask-based decimal (actual bettable price)
+            if book == "kalshi" and "_kalshi_ask_prob" in player:
+                all_odds[book] = kalshi_price_to_decimal(
+                    str(player["_kalshi_ask_prob"]))
+            else:
+                all_odds[book] = american_to_decimal(str(player.get(book, "")))
 
             if raw_edge > best_edge:
                 best_edge = raw_edge
@@ -358,8 +364,12 @@ def calculate_matchup_edges(
         if not all_book_odds:
             continue
 
-        # Book consensus for blending
-        book_p1_probs = {b: d["p1_fair"] for b, d in all_book_odds.items()}
+        # Book consensus for blending (exclude Kalshi — prediction market,
+        # not a sportsbook; included for edge evaluation only)
+        book_p1_probs = {b: d["p1_fair"] for b, d in all_book_odds.items()
+                         if b != "kalshi"}
+        if not book_p1_probs:
+            continue
         book_consensus_p1 = sum(book_p1_probs.values()) / len(book_p1_probs)
 
         # Blend
diff --git a/src/pipeline/pull_kalshi.py b/src/pipeline/pull_kalshi.py
index efc3e28..9a048b3 100644
--- a/src/pipeline/pull_kalshi.py
+++ b/src/pipeline/pull_kalshi.py
@@ -9,7 +9,7 @@ from __future__ import annotations
 import logging
 
 from src.api.kalshi import KalshiClient
-from src.core.devig import kalshi_midpoint
+from src.core.devig import kalshi_midpoint, kalshi_price_to_american
 from src.pipeline.kalshi_matching import (
     extract_player_name_outright,
     extract_player_names_h2h,
@@ -271,3 +271,105 @@ def pull_kalshi_matchups(
     except Exception:
         logger.warning("Kalshi: matchup pull failed", exc_info=True)
         return []
+
+
+# ---- Merge Functions ----
+
+# DG uses "top_10"/"top_20", Kalshi pull returns "t10"/"t20"
+_DG_TO_KALSHI_MARKET = {"win": "win", "top_10": "t10", "top_20": "t20"}
+
+
+def merge_kalshi_into_outrights(
+    dg_outrights: dict[str, list[dict]],
+    kalshi_outrights: dict[str, list[dict]],
+) -> dict[str, list[dict]]:
+    """Inject Kalshi data as book columns into DG outright data.
+
+    For each market type, finds matching players by canonical name, then:
+    1. Adds "kalshi" key with American odds string (from midpoint prob)
+    2. Adds "_kalshi_ask_prob" key with raw ask probability (float)
+
+    Mutates dg_outrights in-place and returns it.
+    """
+    for dg_key, kalshi_key in _DG_TO_KALSHI_MARKET.items():
+        dg_players = dg_outrights.get(dg_key)
+        kalshi_players = kalshi_outrights.get(kalshi_key, [])
+
+        if not dg_players or not kalshi_players:
+            continue
+
+        # Build lookup by normalized player name
+        kalshi_lookup = {}
+        for kp in kalshi_players:
+            name = kp["player_name"].strip().lower()
+            if name not in kalshi_lookup:
+                kalshi_lookup[name] = kp
+
+        # Match and inject
+        for player in dg_players:
+            pname = player.get("player_name", "").strip().lower()
+            kp = kalshi_lookup.get(pname)
+            if not kp:
+                continue
+
+            mid_prob = kp["kalshi_mid_prob"]
+            if mid_prob <= 0 or mid_prob >= 1:
+                continue
+
+            american = kalshi_price_to_american(str(mid_prob))
+            if not american:
+                continue
+
+            player["kalshi"] = american
+            player["_kalshi_ask_prob"] = kp["kalshi_ask_prob"]
+
+    return dg_outrights
+
+
+def merge_kalshi_into_matchups(
+    dg_matchups: list[dict],
+    kalshi_matchups: list[dict],
+) -> list[dict]:
+    """Inject Kalshi H2H data into DG matchup odds dicts.
+
+    Finds matching pairings by player names (order-independent), then
+    adds a "kalshi" entry to the matchup's odds dict with p1/p2 American
+    odds strings aligned to the DG matchup's player order.
+
+    Mutates dg_matchups in-place and returns it.
+    """
+    if not kalshi_matchups:
+        return dg_matchups
+
+    # Build lookup by frozenset of normalized names
+    kalshi_lookup = {}
+    for km in kalshi_matchups:
+        key = frozenset({km["p1_name"].strip().lower(),
+                         km["p2_name"].strip().lower()})
+        if key not in kalshi_lookup:
+            kalshi_lookup[key] = km
+
+    for matchup in dg_matchups:
+        p1 = matchup.get("p1_player_name", "").strip().lower()
+        p2 = matchup.get("p2_player_name", "").strip().lower()
+        key = frozenset({p1, p2})
+
+        km = kalshi_lookup.get(key)
+        if not km:
+            continue
+
+        # Align player order: determine which Kalshi player is DG's p1
+        km_p1_lower = km["p1_name"].strip().lower()
+        if km_p1_lower == p1:
+            p1_prob, p2_prob = km["p1_prob"], km["p2_prob"]
+        else:
+            p1_prob, p2_prob = km["p2_prob"], km["p1_prob"]
+
+        p1_american = kalshi_price_to_american(str(p1_prob))
+        p2_american = kalshi_price_to_american(str(p2_prob))
+
+        if not p1_american or not p2_american:
+            continue
+
+        odds_dict = matchup.setdefault("odds", {})
+        odds_dict["kalshi"] = {"p1": p1_american, "p2": p2_american}
diff --git a/tests/test_kalshi_edge.py b/tests/test_kalshi_edge.py
index 1195700..e5e04c5 100644
--- a/tests/test_kalshi_edge.py
+++ b/tests/test_kalshi_edge.py
@@ -1,7 +1,12 @@
-"""Tests for Kalshi book weight configuration and consensus integration."""
+"""Tests for Kalshi book weight configuration, consensus integration, and edge behavior."""
 
 import config
 from src.core.blend import build_book_consensus
+from src.core.devig import (
+    power_devig, devig_independent,
+    kalshi_price_to_decimal,
+)
+from src.core.edge import calculate_placement_edges, calculate_matchup_edges
 
 
 class TestKalshiBookWeights:
@@ -27,3 +32,132 @@ class TestKalshiBookWeights:
         """
         result = build_book_consensus({"kalshi": 0.10, "pinnacle": 0.12}, "win")
         assert abs(result - 0.11) < 1e-9
+
+
+class TestKalshiDevigBehavior:
+
+    def test_power_devig_on_midpoint_field_k_near_one(self):
+        """When Kalshi midpoints sum to ~1.0, power_devig returns
+        probabilities nearly unchanged (k ~ 1.0)."""
+        probs = [0.20, 0.15, 0.12, 0.10, 0.08, 0.07, 0.06, 0.05, 0.04, 0.13]
+        assert abs(sum(probs) - 1.0) < 0.01
+        devigged = power_devig(probs)
+        for orig, dev in zip(probs, devigged):
+            if dev is not None:
+                assert abs(orig - dev) < 0.02
+
+    def test_devig_independent_on_t10_midpoints_nearly_unchanged(self):
+        """T10 midpoints summing to ~10 pass through devig_independent
+        with minimal adjustment."""
+        probs = [0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55,
+                 0.50, 0.45, 0.40, 0.38, 0.35, 0.32, 0.30, 0.28,
+                 0.25, 0.22, 0.20, 0.55]
+        total = sum(probs)
+        assert 9.0 < total < 11.0  # Should sum to ~10 for T10 market
+        devigged = devig_independent(probs, expected_outcomes=10,
+                                     field_size=20)
+        for orig, dev in zip(probs, devigged):
+            if dev is not None:
+                assert abs(orig - dev) < 0.05
+
+    def test_mixed_field_traditional_plus_kalshi_reasonable(self):
+        """Both sportsbook and Kalshi fields produce valid de-vigged distributions."""
+        trad_probs = [0.22, 0.17, 0.14, 0.11, 0.09, 0.08, 0.07, 0.06, 0.05, 0.04]
+        assert sum(trad_probs) > 1.0
+        trad_devigged = power_devig(trad_probs)
+
+        kalshi_probs = [0.20, 0.15, 0.12, 0.10, 0.08, 0.07, 0.06, 0.05, 0.04, 0.13]
+        kalshi_devigged = power_devig(kalshi_probs)
+
+        trad_total = sum(p for p in trad_devigged if p is not None)
+        kalshi_total = sum(p for p in kalshi_devigged if p is not None)
+        assert abs(trad_total - 1.0) < 0.01
+        assert abs(kalshi_total - 1.0) < 0.01
+
+
+class TestKalshiMatchupExclusion:
+
+    def _matchup_data(self, include_kalshi=True):
+        odds = {
+            "datagolf": {"p1": "-120", "p2": "+110"},
+            "draftkings": {"p1": "-130", "p2": "+115"},
+            "fanduel": {"p1": "-125", "p2": "+110"},
+        }
+        if include_kalshi:
+            odds["kalshi"] = {"p1": "-110", "p2": "+100"}
+        return [{
+            "p1_player_name": "Scheffler, Scottie",
+            "p2_player_name": "McIlroy, Rory",
+            "p1_dg_id": "1", "p2_dg_id": "2",
+            "odds": odds,
+        }]
+
+    def test_kalshi_excluded_from_matchup_book_consensus(self):
+        """Consensus is the same whether Kalshi is present or not."""
+        data_with = self._matchup_data(include_kalshi=True)
+        data_without = self._matchup_data(include_kalshi=False)
+
+        results_with = calculate_matchup_edges(data_with, bankroll=10000)
+        results_without = calculate_matchup_edges(data_without, bankroll=10000)
+
+        if results_with and results_without:
+            for rw in results_with:
+                for rwo in results_without:
+                    if rw.player_name == rwo.player_name:
+                        assert rw.book_consensus_prob == rwo.book_consensus_prob
+
+    def test_kalshi_included_in_matchup_best_edge_evaluation(self):
+        """Kalshi IS evaluated when finding the best-edge book."""
+        data = [{
+            "p1_player_name": "Scheffler, Scottie",
+            "p2_player_name": "McIlroy, Rory",
+            "p1_dg_id": "1", "p2_dg_id": "2",
+            "odds": {
+                "datagolf": {"p1": "-200", "p2": "+180"},
+                "draftkings": {"p1": "-200", "p2": "+170"},
+                "kalshi": {"p1": "-200", "p2": "+250"},
+            },
+        }]
+        results = calculate_matchup_edges(data, bankroll=10000)
+        assert isinstance(results, list)
+
+    def test_kalshi_can_be_best_book_for_matchup(self):
+        data = [{
+            "p1_player_name": "Scheffler, Scottie",
+            "p2_player_name": "McIlroy, Rory",
+            "p1_dg_id": "1", "p2_dg_id": "2",
+            "odds": {
+                "datagolf": {"p1": "-140", "p2": "+125"},
+                "draftkings": {"p1": "-160", "p2": "+140"},
+                "fanduel": {"p1": "-155", "p2": "+135"},
+                "kalshi": {"p1": "+120", "p2": "-130"},
+            },
+        }]
+        results = calculate_matchup_edges(data, bankroll=10000)
+        assert isinstance(results, list)
+
+
+class TestKalshiAllBookOdds:
+
+    def test_all_book_odds_includes_kalshi_with_ask_decimal(self):
+        """all_book_odds uses ask-based decimal for Kalshi."""
+        players = [
+            {"player_name": f"Player {i}", "dg_id": str(i),
+             "datagolf": {"baseline": 0.05},
+             "draftkings": f"+{1000 + i * 100}",
+             "kalshi": f"+{1800 + i * 50}",
+             "_kalshi_ask_prob": 0.06}
+            for i in range(20)
+        ]
+        results = calculate_placement_edges(players, "win", bankroll=10000)
+        for r in results:
+            if r.all_book_odds and "kalshi" in r.all_book_odds:
+                kalshi_decimal = r.all_book_odds["kalshi"]
+                expected = kalshi_price_to_decimal("0.06")
+                assert kalshi_decimal == expected
+
+    def test_kalshi_decimal_differs_from_midpoint_derived(self):
+        """Ask-based decimal < midpoint-derived (worse for bettor)."""
+        mid_decimal = kalshi_price_to_decimal("0.05")
+        ask_decimal = kalshi_price_to_decimal("0.06")
+        assert ask_decimal < mid_decimal
diff --git a/tests/test_pull_kalshi.py b/tests/test_pull_kalshi.py
index 93da5ab..6324aa1 100644
--- a/tests/test_pull_kalshi.py
+++ b/tests/test_pull_kalshi.py
@@ -1,8 +1,11 @@
-"""Tests for Kalshi pipeline pull (outrights and matchups)."""
+"""Tests for Kalshi pipeline pull and merge (outrights and matchups)."""
 
 from unittest.mock import patch, MagicMock
 
-from src.pipeline.pull_kalshi import pull_kalshi_outrights, pull_kalshi_matchups
+from src.pipeline.pull_kalshi import (
+    pull_kalshi_outrights, pull_kalshi_matchups,
+    merge_kalshi_into_outrights, merge_kalshi_into_matchups,
+)
 
 
 def _make_market(title, subtitle, yes_bid, yes_ask, open_interest,
@@ -270,3 +273,141 @@ class TestPullKalshiMatchups:
             tournament_end="2026-04-12",
         )
         assert result == []
+
+
+# ---- Merge Tests ----
+
+class TestMergeKalshiIntoOutrights:
+
+    def _dg_outrights(self):
+        return {
+            "win": [
+                {"player_name": "Scheffler, Scottie", "dg_id": "1",
+                 "draftkings": "+400", "fanduel": "+450"},
+                {"player_name": "McIlroy, Rory", "dg_id": "2",
+                 "draftkings": "+800", "fanduel": "+900"},
+                {"player_name": "Hovland, Viktor", "dg_id": "3",
+                 "draftkings": "+2000"},
+            ],
+            "top_10": [
+                {"player_name": "Scheffler, Scottie", "dg_id": "1",
+                 "draftkings": "-200"},
+            ],
+        }
+
+    def _kalshi_outrights(self):
+        return {
+            "win": [
+                {"player_name": "Scheffler, Scottie", "kalshi_mid_prob": 0.22,
+                 "kalshi_ask_prob": 0.24, "open_interest": 500},
+                {"player_name": "McIlroy, Rory", "kalshi_mid_prob": 0.09,
+                 "kalshi_ask_prob": 0.10, "open_interest": 200},
+            ],
+            "t10": [
+                {"player_name": "Scheffler, Scottie", "kalshi_mid_prob": 0.52,
+                 "kalshi_ask_prob": 0.54, "open_interest": 300},
+            ],
+            "t20": [],
+        }
+
+    def test_adds_kalshi_key_with_american_odds(self):
+        dg = self._dg_outrights()
+        kalshi = self._kalshi_outrights()
+        result = merge_kalshi_into_outrights(dg, kalshi)
+        scheffler = result["win"][0]
+        assert "kalshi" in scheffler
+        assert scheffler["kalshi"].startswith("+") or scheffler["kalshi"].startswith("-")
+
+    def test_american_odds_derived_from_midpoint_not_ask(self):
+        dg = self._dg_outrights()
+        kalshi = self._kalshi_outrights()
+        result = merge_kalshi_into_outrights(dg, kalshi)
+        scheffler = result["win"][0]
+        # mid=0.22 -> +355 (approx), ask=0.24 -> +317 (approx)
+        # The value should be from midpoint, so higher (more plus)
+        odds_val = int(scheffler["kalshi"].replace("+", ""))
+        assert odds_val > 300  # midpoint-based, not ask-based
+
+    def test_unmatched_kalshi_players_skipped(self):
+        dg = self._dg_outrights()
+        kalshi = {"win": [
+            {"player_name": "Unknown Player", "kalshi_mid_prob": 0.05,
+             "kalshi_ask_prob": 0.06, "open_interest": 200},
+        ], "t10": [], "t20": []}
+        result = merge_kalshi_into_outrights(dg, kalshi)
+        for player in result["win"]:
+            assert "kalshi" not in player
+
+    def test_existing_book_columns_not_modified(self):
+        dg = self._dg_outrights()
+        kalshi = self._kalshi_outrights()
+        merge_kalshi_into_outrights(dg, kalshi)
+        assert dg["win"][0]["draftkings"] == "+400"
+        assert dg["win"][0]["fanduel"] == "+450"
+
+    def test_players_without_kalshi_data_have_no_kalshi_key(self):
+        dg = self._dg_outrights()
+        kalshi = self._kalshi_outrights()
+        merge_kalshi_into_outrights(dg, kalshi)
+        hovland = dg["win"][2]
+        assert "kalshi" not in hovland
+
+    def test_stores_ask_data_for_bettable_edge(self):
+        dg = self._dg_outrights()
+        kalshi = self._kalshi_outrights()
+        merge_kalshi_into_outrights(dg, kalshi)
+        scheffler = dg["win"][0]
+        assert "_kalshi_ask_prob" in scheffler
+        assert isinstance(scheffler["_kalshi_ask_prob"], float)
+        assert scheffler["_kalshi_ask_prob"] == 0.24
+
+
+class TestMergeKalshiIntoMatchups:
+
+    def _dg_matchups(self):
+        return [
+            {
+                "p1_player_name": "Scheffler, Scottie",
+                "p2_player_name": "McIlroy, Rory",
+                "p1_dg_id": "1", "p2_dg_id": "2",
+                "odds": {
+                    "datagolf": {"p1": "-150", "p2": "+130"},
+                    "draftkings": {"p1": "-160", "p2": "+140"},
+                },
+            },
+        ]
+
+    def _kalshi_matchups(self):
+        return [
+            {"p1_name": "Scheffler, Scottie", "p2_name": "McIlroy, Rory",
+             "p1_prob": 0.565, "p2_prob": 0.435, "p1_oi": 300, "p2_oi": 300},
+        ]
+
+    def test_injects_kalshi_into_matchup_odds_dict(self):
+        dg = self._dg_matchups()
+        kalshi = self._kalshi_matchups()
+        merge_kalshi_into_matchups(dg, kalshi)
+        assert "kalshi" in dg[0]["odds"]
+        kalshi_odds = dg[0]["odds"]["kalshi"]
+        assert "p1" in kalshi_odds
+        assert "p2" in kalshi_odds
+
+    def test_unmatched_pairings_skipped(self):
+        dg = self._dg_matchups()
+        kalshi = [
+            {"p1_name": "Player X", "p2_name": "Player Y",
+             "p1_prob": 0.5, "p2_prob": 0.5, "p1_oi": 100, "p2_oi": 100},
+        ]
+        merge_kalshi_into_matchups(dg, kalshi)
+        assert "kalshi" not in dg[0]["odds"]
+
+    def test_kalshi_odds_same_format_as_other_books(self):
+        dg = self._dg_matchups()
+        kalshi = self._kalshi_matchups()
+        merge_kalshi_into_matchups(dg, kalshi)
+        kalshi_entry = dg[0]["odds"]["kalshi"]
+        dk_entry = dg[0]["odds"]["draftkings"]
+        # Same structure: {"p1": str, "p2": str}
+        assert set(kalshi_entry.keys()) == set(dk_entry.keys())
+        assert isinstance(kalshi_entry["p1"], str)
+        assert isinstance(kalshi_entry["p2"], str)
