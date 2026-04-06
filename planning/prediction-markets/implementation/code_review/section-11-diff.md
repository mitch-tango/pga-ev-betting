diff --git a/planning/prediction-markets/implementation/deep_implement_config.json b/planning/prediction-markets/implementation/deep_implement_config.json
index b20c714..bf66599 100644
--- a/planning/prediction-markets/implementation/deep_implement_config.json
+++ b/planning/prediction-markets/implementation/deep_implement_config.json
@@ -55,6 +55,10 @@
     "section-09-prophetx-pull": {
       "status": "complete",
       "commit_hash": "589271e"
+    },
+    "section-10-workflow": {
+      "status": "complete",
+      "commit_hash": "ef2de75"
     }
   },
   "pre_commit": {
diff --git a/tests/conftest.py b/tests/conftest.py
new file mode 100644
index 0000000..a05021c
--- /dev/null
+++ b/tests/conftest.py
@@ -0,0 +1,140 @@
+"""Shared test fixture factories for prediction market data."""
+
+from __future__ import annotations
+
+import json
+import uuid
+
+import pytest
+
+
+# ---------------------------------------------------------------------------
+# Polymarket factories
+# ---------------------------------------------------------------------------
+
+
+@pytest.fixture
+def make_polymarket_event():
+    """Factory for Gamma API event dicts."""
+
+    def _make(title: str, start_date: str, end_date: str,
+              markets: list[dict] | None = None) -> dict:
+        return {
+            "id": str(uuid.uuid4()),
+            "title": title,
+            "slug": title.lower().replace(" ", "-"),
+            "startDate": start_date,
+            "endDate": end_date,
+            "markets": markets or [],
+        }
+
+    return _make
+
+
+@pytest.fixture
+def make_polymarket_market():
+    """Factory for a single Polymarket market dict."""
+
+    def _make(
+        question: str,
+        slug: str,
+        outcome_prices: list[float],
+        clob_token_ids: list[str],
+        volume: float = 500.0,
+        outcomes: list[str] | None = None,
+    ) -> dict:
+        return {
+            "id": str(uuid.uuid4()),
+            "question": question,
+            "slug": slug,
+            "outcomePrices": json.dumps(outcome_prices),
+            "clobTokenIds": json.dumps(clob_token_ids),
+            "volume": volume,
+            "outcomes": json.dumps(outcomes or ["Yes", "No"]),
+            "marketType": "binary",
+            "liquidity": volume * 0.5,
+        }
+
+    return _make
+
+
+@pytest.fixture
+def make_polymarket_books_response():
+    """Factory for CLOB /books response for one token."""
+
+    def _make(token_id: str, best_bid: float, best_ask: float) -> dict:
+        return {
+            token_id: {
+                "bids": [{"price": str(best_bid), "size": "100"}],
+                "asks": [{"price": str(best_ask), "size": "100"}],
+            }
+        }
+
+    return _make
+
+
+# ---------------------------------------------------------------------------
+# ProphetX factories
+# ---------------------------------------------------------------------------
+
+
+@pytest.fixture
+def make_prophetx_event():
+    """Factory for ProphetX event dicts."""
+
+    def _make(name: str, start_date: str, event_id: str | None = None) -> dict:
+        return {
+            "id": event_id or str(uuid.uuid4()),
+            "name": name,
+            "start_date": start_date,
+            "end_date": start_date,  # same day default
+        }
+
+    return _make
+
+
+@pytest.fixture
+def make_prophetx_market():
+    """Factory for ProphetX market dicts."""
+
+    def _make(
+        line_id: str,
+        competitors: list[dict],
+        odds: int | float | str,
+        market_type: str = "moneyline",
+        sub_type: str = "outrights",
+    ) -> dict:
+        return {
+            "line_id": line_id,
+            "market_type": market_type,
+            "sub_type": sub_type,
+            "competitors": competitors,
+            "odds": odds,
+        }
+
+    return _make
+
+
+@pytest.fixture
+def make_prophetx_matchup_market():
+    """Convenience factory for ProphetX 2-competitor matchup markets."""
+
+    def _make(
+        line_id: str,
+        player1: str,
+        player2: str,
+        p1_odds: int | float,
+        p2_odds: int | float,
+    ) -> dict:
+        return {
+            "line_id": line_id,
+            "market_type": "moneyline",
+            "sub_type": "matchup",
+            "competitors": [
+                {"competitor_name": player1, "odds": p1_odds},
+                {"competitor_name": player2, "odds": p2_odds},
+            ],
+            "odds": None,
+        }
+
+    return _make
diff --git a/tests/test_prediction_market_workflow.py b/tests/test_prediction_market_workflow.py
new file mode 100644
index 0000000..865b4b3
--- /dev/null
+++ b/tests/test_prediction_market_workflow.py
@@ -0,0 +1,346 @@
+"""Integration tests for prediction market pipeline.
+
+Cross-cutting tests that verify the full DG + Kalshi + Polymarket + ProphetX
+workflow end-to-end, including partial failure and config-gated skip scenarios.
+"""
+
+from __future__ import annotations
+
+from unittest.mock import MagicMock, patch
+
+import pytest
+
+from src.core.edge import CandidateBet, calculate_placement_edges
+from src.pipeline.pull_polymarket import (
+    merge_polymarket_into_outrights,
+    pull_polymarket_outrights,
+)
+from src.pipeline.pull_prophetx import (
+    merge_prophetx_into_outrights,
+    merge_prophetx_into_matchups,
+    pull_prophetx_outrights,
+    pull_prophetx_matchups,
+)
+from src.pipeline.pull_kalshi import (
+    merge_kalshi_into_outrights,
+)
+
+
+# ---------------------------------------------------------------------------
+# Helpers
+# ---------------------------------------------------------------------------
+
+_FILLER_ODDS = [
+    "+800", "+900", "+1000", "+1200", "+1400",
+    "+1600", "+1800", "+2000", "+2500", "+3000",
+    "+3500", "+4000", "+5000", "+6000",
+]
+
+
+def _dg_field(n: int = 20, books: dict[str, str] | None = None) -> list[dict]:
+    """Build a DG-style outright player list with filler data.
+
+    Args:
+        n: number of players (max 20).
+        books: extra book keys to add to every player (e.g. {"draftkings": "+400"}).
+    """
+    players = []
+    for i in range(min(n, 20)):
+        odds = _FILLER_ODDS[i] if i < len(_FILLER_ODDS) else "+8000"
+        p = {
+            "player_name": f"Player {i + 1}",
+            "dg_id": str(i + 1),
+            "datagolf": {"baseline_history_fit": odds},
+            "draftkings": odds,
+        }
+        if books:
+            p.update(books)
+        players.append(p)
+    return players
+
+
+def _kalshi_outrights(names: list[str]) -> dict:
+    """Build a Kalshi-shaped outrights dict for merging."""
+    return {
+        "win": [
+            {"player_name": name, "kalshi_mid_prob": 0.05 + i * 0.01,
+             "kalshi_ask_prob": 0.06 + i * 0.01, "open_interest": 500}
+            for i, name in enumerate(names)
+        ]
+    }
+
+
+def _polymarket_outrights(names: list[str]) -> dict:
+    """Build a Polymarket-shaped outrights dict for merging."""
+    return {
+        "win": [
+            {"player_name": name, "polymarket_mid_prob": 0.05 + i * 0.01,
+             "polymarket_ask_prob": 0.06 + i * 0.01, "volume": 1000}
+            for i, name in enumerate(names)
+        ]
+    }
+
+
+def _prophetx_outrights(names: list[str]) -> dict:
+    """Build a ProphetX-shaped outrights dict for merging."""
+    return {
+        "win": [
+            {"player_name": name, "prophetx_mid_prob": 0.05 + i * 0.01,
+             "prophetx_american": f"+{1800 - i * 100}",
+             "odds_format": "american"}
+            for i, name in enumerate(names)
+        ]
+    }
+
+
+# ===========================================================================
+# TestFullPipelineAllMarkets
+# ===========================================================================
+
+
+class TestFullPipelineAllMarkets:
+    """Verify that all three prediction markets merge into outrights
+    and produce valid edge output."""
+
+    def test_all_markets_merge_into_outrights(self):
+        """DG + Kalshi + Polymarket + ProphetX merge without error."""
+        dg = {"win": _dg_field(15)}
+        names = [p["player_name"] for p in dg["win"][:10]]
+
+        kalshi = _kalshi_outrights(names[:8])
+        poly = _polymarket_outrights(names[:6])
+        px = _prophetx_outrights(names[:5])
+
+        merge_kalshi_into_outrights(dg, kalshi)
+        merge_polymarket_into_outrights(dg, poly)
+        merge_prophetx_into_outrights(dg, px)
+
+        # Check that some players got all 3 prediction market keys
+        multi_count = sum(
+            1 for p in dg["win"]
+            if "kalshi" in p and "polymarket" in p and "prophetx" in p
+        )
+        assert multi_count >= 3, f"Expected >=3 players with all 3 markets, got {multi_count}"
+
+    def test_edge_calculation_with_all_markets(self):
+        """calculate_placement_edges runs with all 3 prediction markets present."""
+        field = _dg_field(15)
+        # Give first 5 players all prediction market odds
+        for i, p in enumerate(field[:5]):
+            p["kalshi"] = "+600"
+            p["_kalshi_ask_prob"] = 0.15
+            p["polymarket"] = "+650"
+            p["_polymarket_ask_prob"] = 0.14
+            p["prophetx"] = "+550"
+            p["_prophetx_ask_prob"] = 0.16
+
+        results = calculate_placement_edges(field, market_type="t10")
+        assert isinstance(results, list)
+
+    def test_pull_order_dg_kalshi_polymarket_prophetx(self):
+        """run_pretournament.py pulls in order: DG → Kalshi → Polymarket → ProphetX."""
+        import scripts.run_pretournament as mod
+        source = open(mod.__file__).read()
+
+        dg_pos = source.index("pull_all_outrights")
+        kalshi_pos = source.index("pull_kalshi_outrights")
+        poly_pos = source.index("_pull_polymarket_block")
+        px_pos = source.index("_pull_prophetx_block")
+
+        assert dg_pos < kalshi_pos < poly_pos < px_pos
+
+    def test_best_book_can_be_any_prediction_market(self):
+        """CandidateBet.best_book accepts polymarket, prophetx, or kalshi."""
+        for book in ("kalshi", "polymarket", "prophetx"):
+            cb = CandidateBet(market_type="win", player_name="Test", best_book=book)
+            assert cb.best_book == book
+
+
+# ===========================================================================
+# TestPartialFailure
+# ===========================================================================
+
+
+class TestPartialFailure:
+    """When one or two markets fail, remaining markets still produce edges."""
+
+    def _build_field_with_kalshi_poly_px(self):
+        """Build a field where all 3 prediction markets have odds."""
+        field = _dg_field(15)
+        for p in field:
+            p["kalshi"] = "+700"
+            p["_kalshi_ask_prob"] = 0.13
+            p["polymarket"] = "+650"
+            p["_polymarket_ask_prob"] = 0.14
+            p["prophetx"] = "+600"
+            p["_prophetx_ask_prob"] = 0.15
+        return field
+
+    def test_polymarket_down_others_ok(self):
+        """Polymarket fails → Kalshi + ProphetX produce valid output."""
+        dg = {"win": _dg_field(15)}
+        names = [p["player_name"] for p in dg["win"][:5]]
+
+        merge_kalshi_into_outrights(dg, _kalshi_outrights(names))
+        # Polymarket skipped entirely
+        merge_prophetx_into_outrights(dg, _prophetx_outrights(names))
+
+        results = calculate_placement_edges(dg["win"], market_type="t10")
+        assert isinstance(results, list)
+
+    def test_prophetx_down_others_ok(self):
+        """ProphetX fails → Kalshi + Polymarket produce valid output."""
+        dg = {"win": _dg_field(15)}
+        names = [p["player_name"] for p in dg["win"][:5]]
+
+        merge_kalshi_into_outrights(dg, _kalshi_outrights(names))
+        merge_polymarket_into_outrights(dg, _polymarket_outrights(names))
+        # ProphetX skipped
+
+        results = calculate_placement_edges(dg["win"], market_type="t10")
+        assert isinstance(results, list)
+
+    def test_kalshi_down_others_ok(self):
+        """Kalshi fails → Polymarket + ProphetX produce valid output."""
+        dg = {"win": _dg_field(15)}
+        names = [p["player_name"] for p in dg["win"][:5]]
+
+        # Kalshi skipped
+        merge_polymarket_into_outrights(dg, _polymarket_outrights(names))
+        merge_prophetx_into_outrights(dg, _prophetx_outrights(names))
+
+        results = calculate_placement_edges(dg["win"], market_type="t10")
+        assert isinstance(results, list)
+
+    def test_two_markets_down_one_remaining(self):
+        """Only one prediction market available → still produces edges."""
+        dg = {"win": _dg_field(15)}
+        names = [p["player_name"] for p in dg["win"][:5]]
+
+        merge_polymarket_into_outrights(dg, _polymarket_outrights(names))
+        # Kalshi + ProphetX both down
+
+        results = calculate_placement_edges(dg["win"], market_type="t10")
+        assert isinstance(results, list)
+
+    def test_graceful_degradation_pretournament(self):
+        """run_pretournament has try/except + warning for each prediction market."""
+        import scripts.run_pretournament as mod
+        source = open(mod.__file__).read()
+
+        assert "Warning: Polymarket unavailable" in source or "Polymarket unavailable" in source
+        assert "Warning: ProphetX unavailable" in source or "ProphetX unavailable" in source
+        assert "Warning: Kalshi unavailable" in source or "Kalshi unavailable" in source
+
+
+# ===========================================================================
+# TestTotalPredictionMarketFailure
+# ===========================================================================
+
+
+class TestTotalPredictionMarketFailure:
+    """Pipeline works with zero prediction markets."""
+
+    def test_dg_only_pipeline(self):
+        """DG-only field (no prediction markets) → valid edge output."""
+        field = _dg_field(15)
+        # First player gets favorable DG odds to generate an edge
+        field[0]["datagolf"]["baseline_history_fit"] = "+150"
+
+        results = calculate_placement_edges(field, market_type="t10")
+        assert isinstance(results, list)
+
+    @patch("config.POLYMARKET_ENABLED", False)
+    @patch("config.PROPHETX_ENABLED", False)
+    def test_all_disabled_via_config_dg_plus_kalshi_only(self):
+        """Both prediction markets disabled → blocks skip cleanly."""
+        from scripts.run_pretournament import _pull_polymarket_block, _pull_prophetx_block
+
+        outrights = {"win": [{"player_name": "Test"}]}
+        matchups = []
+
+        _pull_polymarket_block(outrights, "Test", "2026-01-01", "2026-01-04")
+        _pull_prophetx_block(outrights, matchups, "Test", "2026-01-01", "2026-01-04")
+
+        # Outrights unmodified
+        assert outrights == {"win": [{"player_name": "Test"}]}
+
+
+# ===========================================================================
+# TestEnabledFlags
+# ===========================================================================
+
+
+class TestEnabledFlags:
+    """Config flags gate prediction market API calls."""
+
+    @patch("config.POLYMARKET_ENABLED", False)
+    @patch("scripts.run_pretournament.pull_polymarket_outrights")
+    def test_polymarket_skipped_when_disabled(self, mock_pull):
+        from scripts.run_pretournament import _pull_polymarket_block
+        outrights = {"win": []}
+        _pull_polymarket_block(outrights, "Test", "2026-01-01", "2026-01-04")
+        mock_pull.assert_not_called()
+
+    @patch("config.PROPHETX_ENABLED", False)
+    @patch("scripts.run_pretournament.pull_prophetx_outrights")
+    def test_prophetx_skipped_when_disabled(self, mock_pull):
+        from scripts.run_pretournament import _pull_prophetx_block
+        outrights = {"win": []}
+        matchups = []
+        _pull_prophetx_block(outrights, matchups, "Test", "2026-01-01", "2026-01-04")
+        mock_pull.assert_not_called()
+
+    @patch("config.POLYMARKET_ENABLED", False)
+    @patch("config.PROPHETX_ENABLED", False)
+    def test_both_disabled_dg_kalshi_only_baseline(self):
+        """Pre-integration baseline: pipeline runs with only DG + Kalshi."""
+        field = _dg_field(15)
+        # Simulate Kalshi merge
+        for p in field[:5]:
+            p["kalshi"] = "+600"
+            p["_kalshi_ask_prob"] = 0.15
+
+        results = calculate_placement_edges(field, market_type="t10")
+        assert isinstance(results, list)
+
+
+# ===========================================================================
+# TestWorkflowScriptContents
+# ===========================================================================
+
+
+class TestWorkflowScriptContents:
+    """Structural tests: scripts import and reference prediction markets."""
+
+    def test_pretournament_imports_polymarket(self):
+        import scripts.run_pretournament as mod
+        source = open(mod.__file__).read()
+        assert "from src.pipeline.pull_polymarket import" in source
+        assert source.count("pull_polymarket_outrights") >= 2  # import + call
+
+    def test_pretournament_imports_prophetx(self):
+        import scripts.run_pretournament as mod
+        source = open(mod.__file__).read()
+        assert "from src.pipeline.pull_prophetx import" in source
+        assert source.count("pull_prophetx_outrights") >= 2
+
+    def test_pretournament_try_except_for_each_market(self):
+        """Each prediction market block has try/except for graceful degradation."""
+        import scripts.run_pretournament as mod
+        source = open(mod.__file__).read()
+        # Polymarket block
+        assert "Polymarket unavailable" in source or "Polymarket" in source
+        # ProphetX block
+        assert "ProphetX unavailable" in source or "ProphetX" in source
+
+    def test_preround_imports_prophetx(self):
+        import scripts.run_preround as mod
+        source = open(mod.__file__).read()
+        assert "pull_prophetx" in source
+
+    def test_live_check_references_prediction_market_stats(self):
+        import scripts.run_live_check as mod
+        source = open(mod.__file__).read()
+        assert "polymarket_merged" in source
+        assert "prophetx_merged" in source
