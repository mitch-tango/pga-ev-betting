diff --git a/planning/prediction-markets/implementation/deep_implement_config.json b/planning/prediction-markets/implementation/deep_implement_config.json
index 20e106e..b20c714 100644
--- a/planning/prediction-markets/implementation/deep_implement_config.json
+++ b/planning/prediction-markets/implementation/deep_implement_config.json
@@ -51,6 +51,10 @@
     "section-08-prophetx-matching": {
       "status": "complete",
       "commit_hash": "cb1be84"
+    },
+    "section-09-prophetx-pull": {
+      "status": "complete",
+      "commit_hash": "589271e"
     }
   },
   "pre_commit": {
diff --git a/scripts/run_live_check.py b/scripts/run_live_check.py
index f0242d2..a614c71 100644
--- a/scripts/run_live_check.py
+++ b/scripts/run_live_check.py
@@ -62,6 +62,14 @@ def main():
         print("Kalshi: merged")
     elif stats.get("kalshi_error"):
         print(f"Kalshi: unavailable ({stats['kalshi_error'][:60]})")
+    if stats.get("polymarket_merged"):
+        print("Polymarket: merged")
+    elif stats.get("polymarket_error"):
+        print(f"Polymarket: unavailable ({stats['polymarket_error'][:60]})")
+    if stats.get("prophetx_merged"):
+        print("ProphetX: merged")
+    elif stats.get("prophetx_error"):
+        print(f"ProphetX: unavailable ({stats['prophetx_error'][:60]})")
     print(f"Bankroll: ${stats.get('bankroll', 0):,.2f}")
 
     # Show edge breakdown
diff --git a/scripts/run_preround.py b/scripts/run_preround.py
index 33b230d..0b8b730 100644
--- a/scripts/run_preround.py
+++ b/scripts/run_preround.py
@@ -22,6 +22,9 @@ from src.pipeline.pull_matchups import pull_round_matchups, pull_3balls
 from src.pipeline.pull_kalshi import (
     pull_kalshi_matchups, merge_kalshi_into_matchups,
 )
+from src.pipeline.pull_prophetx import (
+    pull_prophetx_matchups, merge_prophetx_into_matchups,
+)
 from src.parsers.start_matchups import parse_start_matchups_from_file
 from src.parsers.start_merger import merge_start_into_matchups
 from src.core.edge import calculate_matchup_edges, calculate_3ball_edges
@@ -168,6 +171,29 @@ def interactive_place_bets(candidates, tournament_id, bankroll):
     print(f"\nBankroll: ${new_balance:.2f}")
 
 
+def _pull_prophetx_matchup_block(matchups, tournament_name, today, end_date,
+                                 tournament_slug=None):
+    """Pull and merge ProphetX matchups. Graceful degradation on failure."""
+    if not config.PROPHETX_ENABLED:
+        print("\nProphetX: disabled (no credentials)")
+        return
+    if not tournament_name:
+        return
+    print("\nPulling ProphetX matchups...")
+    try:
+        prophetx_matchup_data = pull_prophetx_matchups(
+            tournament_name, today, end_date,
+            tournament_slug=tournament_slug,
+        )
+        if prophetx_matchup_data and matchups:
+            merge_prophetx_into_matchups(matchups, prophetx_matchup_data)
+            print(f"  ProphetX matchups: {len(prophetx_matchup_data)} merged")
+        else:
+            print("  ProphetX: no matchup data available")
+    except Exception as e:
+        print(f"  Warning: ProphetX unavailable ({e}), proceeding without")
+
+
 def main():
     parser = argparse.ArgumentParser(description="Pre-round matchup + 3-ball scan")
     parser.add_argument("--dry-run", action="store_true")
@@ -225,6 +251,15 @@ def main():
         for u in unmatched:
             print(f"    ? {u['p1_name']} vs {u['p2_name']}")
 
+    # Date range and tournament name for prediction market matching
+    today = datetime.now().strftime("%Y-%m-%d")
+    end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")  # Thu-Sun
+    tournament_name_for_kalshi = ""
+    if tournament_id:
+        t = db.get_tournament_by_id(tournament_id)
+        if t:
+            tournament_name_for_kalshi = t.get("tournament_name", "")
+
     # Kalshi tournament matchups: enabled when live DG model is available.
     # Kalshi tournament-long prices reflect in-tournament performance.
     # We pull DG live predictions to avoid comparing stale DG vs live Kalshi.
@@ -235,14 +270,6 @@ def main():
         print(f"  DG live model: {len(live_data)} players — Kalshi comparison enabled")
     if kalshi_enabled:
         try:
-            today = datetime.now().strftime("%Y-%m-%d")
-            # PGA tournaments run Thu-Sun (4 days)
-            end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
-            tournament_name_for_kalshi = ""
-            if tournament_id:
-                t = db.get_tournament_by_id(tournament_id)
-                if t:
-                    tournament_name_for_kalshi = t.get("tournament_name", "")
             if tournament_name_for_kalshi:
                 kalshi_matchup_data = pull_kalshi_matchups(
                     tournament_name_for_kalshi, today, end_date,
@@ -256,9 +283,11 @@ def main():
     else:
         print("  Skipping Kalshi tournament markets (no live DG data available)")
 
-    # TODO: Polymarket integration — pull_polymarket_outrights() would follow
-    # the same pattern here. Polymarket covers win/T10/T20 but NOT matchups.
-    # Requires keyword-based event discovery (no golf-specific ticker).
+    # Polymarket: skip in preround (outrights only, not relevant for round analysis)
+
+    # ProphetX matchups
+    _pull_prophetx_matchup_block(round_matchups, tournament_name_for_kalshi, today, end_date,
+                                 tournament_slug=args.tournament)
 
     # Pull 3-balls
     print("Pulling 3-ball odds...")
diff --git a/scripts/run_pretournament.py b/scripts/run_pretournament.py
index 2e174d3..58fd0d8 100644
--- a/scripts/run_pretournament.py
+++ b/scripts/run_pretournament.py
@@ -31,6 +31,14 @@ from src.pipeline.pull_kalshi import (
     pull_kalshi_outrights, pull_kalshi_matchups,
     merge_kalshi_into_outrights, merge_kalshi_into_matchups,
 )
+from src.pipeline.pull_polymarket import (
+    pull_polymarket_outrights,
+    merge_polymarket_into_outrights,
+)
+from src.pipeline.pull_prophetx import (
+    pull_prophetx_outrights, pull_prophetx_matchups,
+    merge_prophetx_into_outrights, merge_prophetx_into_matchups,
+)
 from src.parsers.start_matchups import parse_start_matchups_from_file
 from src.parsers.start_merger import merge_start_into_matchups
 from src.core.edge import calculate_placement_edges, calculate_matchup_edges
@@ -206,6 +214,58 @@ def interactive_place_bets(candidates, tournament_id, bankroll):
     print(f"Bets placed this session: {len(placed_bets)}")
 
 
+def _pull_polymarket_block(outrights, tournament_name, today, end_date,
+                           tournament_slug=None):
+    """Pull and merge Polymarket outrights. Graceful degradation on failure."""
+    if not config.POLYMARKET_ENABLED:
+        print("\nPolymarket: disabled")
+        return
+    print("\nPulling Polymarket odds...")
+    try:
+        polymarket_outrights = pull_polymarket_outrights(
+            tournament_name, today, end_date,
+            tournament_slug=tournament_slug,
+        )
+        if any(len(v) > 0 for v in polymarket_outrights.values()):
+            merge_polymarket_into_outrights(outrights, polymarket_outrights)
+            for mkt, players in polymarket_outrights.items():
+                if players:
+                    print(f"  Polymarket {mkt}: {len(players)} players merged")
+        else:
+            print("  Polymarket: no outright data available")
+    except Exception as e:
+        print(f"  Warning: Polymarket unavailable ({e}), proceeding without")
+
+
+def _pull_prophetx_block(outrights, matchups, tournament_name, today, end_date,
+                         tournament_slug=None):
+    """Pull and merge ProphetX outrights + matchups. Graceful degradation."""
+    if not config.PROPHETX_ENABLED:
+        print("\nProphetX: disabled (no credentials)")
+        return
+    print("\nPulling ProphetX odds...")
+    try:
+        prophetx_outrights = pull_prophetx_outrights(
+            tournament_name, today, end_date,
+            tournament_slug=tournament_slug,
+        )
+        if any(len(v) > 0 for v in prophetx_outrights.values()):
+            merge_prophetx_into_outrights(outrights, prophetx_outrights)
+            for mkt, players in prophetx_outrights.items():
+                if players:
+                    print(f"  ProphetX {mkt}: {len(players)} players merged")
+
+        prophetx_matchup_data = pull_prophetx_matchups(
+            tournament_name, today, end_date,
+            tournament_slug=tournament_slug,
+        )
+        if prophetx_matchup_data:
+            merge_prophetx_into_matchups(matchups, prophetx_matchup_data)
+            print(f"  ProphetX matchups: {len(prophetx_matchup_data)} merged")
+    except Exception as e:
+        print(f"  Warning: ProphetX unavailable ({e}), proceeding without")
+
+
 def main():
     parser = argparse.ArgumentParser(
         description="Pre-tournament +EV scan"
@@ -251,16 +311,17 @@ def main():
     matchups = pull_tournament_matchups(tournament_slug, tour)
     print(f"  Matchups: {len(matchups)}")
 
+    # Date range for prediction market matching
+    tournament_name_for_kalshi = outrights.get("_event_name", "")
+    today = datetime.now().strftime("%Y-%m-%d")
+    end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")  # Thu-Sun
+
     # Pull Kalshi odds (graceful degradation — never blocks DG pipeline)
     print("\nPulling Kalshi odds...")
     try:
-        tournament_name_for_kalshi = outrights.get("_event_name", "")
         if not tournament_name_for_kalshi:
             print("  Warning: tournament name unknown, skipping Kalshi")
             raise ValueError("No tournament name for Kalshi matching")
-        today = datetime.now().strftime("%Y-%m-%d")
-        # PGA tournaments run Thu-Sun (4 days)
-        end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
 
         kalshi_outrights = pull_kalshi_outrights(
             tournament_name_for_kalshi, today, end_date,
@@ -284,9 +345,13 @@ def main():
     except Exception as e:
         print(f"  Warning: Kalshi unavailable ({e}), proceeding with DG-only")
 
-    # TODO: Polymarket integration — pull_polymarket_outrights() would follow
-    # the same pattern here. Polymarket covers win/T10/T20 but NOT matchups.
-    # Requires keyword-based event discovery (no golf-specific ticker).
+    # Polymarket outrights
+    _pull_polymarket_block(outrights, tournament_name_for_kalshi, today, end_date,
+                           tournament_slug=tournament_slug)
+
+    # ProphetX outrights + matchups
+    _pull_prophetx_block(outrights, matchups, tournament_name_for_kalshi, today, end_date,
+                         tournament_slug=tournament_slug)
 
     # Merge Start odds if provided
     if args.start_file and matchups:
diff --git a/src/pipeline/pull_live_edges.py b/src/pipeline/pull_live_edges.py
index 3e86d09..1c3c530 100644
--- a/src/pipeline/pull_live_edges.py
+++ b/src/pipeline/pull_live_edges.py
@@ -24,6 +24,14 @@ from src.pipeline.pull_kalshi import (
     pull_kalshi_outrights, pull_kalshi_matchups,
     merge_kalshi_into_outrights, merge_kalshi_into_matchups,
 )
+from src.pipeline.pull_polymarket import (
+    pull_polymarket_outrights,
+    merge_polymarket_into_outrights,
+)
+from src.pipeline.pull_prophetx import (
+    pull_prophetx_outrights, pull_prophetx_matchups,
+    merge_prophetx_into_outrights, merge_prophetx_into_matchups,
+)
 from src.core.edge import calculate_placement_edges, calculate_matchup_edges, calculate_3ball_edges, CandidateBet
 from src.core.kelly import get_correlation_haircut
 from src.normalize.players import resolve_candidates
@@ -138,6 +146,47 @@ def _override_dg_with_live(outrights: dict[str, list[dict]], live_players: list[
     return total_matched
 
 
+def _pull_polymarket_block(outrights, stats, tournament_name, today, end_date,
+                           tournament_slug=None):
+    """Pull and merge Polymarket outrights into live data. Graceful degradation."""
+    if not config.POLYMARKET_ENABLED:
+        return
+    try:
+        polymarket_outrights = pull_polymarket_outrights(
+            tournament_name, today, end_date,
+            tournament_slug=tournament_slug,
+        )
+        if any(len(v) > 0 for v in polymarket_outrights.values()):
+            merge_polymarket_into_outrights(outrights, polymarket_outrights)
+            stats["polymarket_merged"] = True
+    except Exception as e:
+        stats["polymarket_error"] = str(e)
+
+
+def _pull_prophetx_block(outrights, matchups, stats, tournament_name, today, end_date,
+                         tournament_slug=None):
+    """Pull and merge ProphetX outrights + matchups into live data. Graceful degradation."""
+    if not config.PROPHETX_ENABLED:
+        return
+    try:
+        prophetx_outrights = pull_prophetx_outrights(
+            tournament_name, today, end_date,
+            tournament_slug=tournament_slug,
+        )
+        if any(len(v) > 0 for v in prophetx_outrights.values()):
+            merge_prophetx_into_outrights(outrights, prophetx_outrights)
+            stats["prophetx_merged"] = True
+
+        prophetx_matchup_data = pull_prophetx_matchups(
+            tournament_name, today, end_date,
+            tournament_slug=tournament_slug,
+        )
+        if prophetx_matchup_data and isinstance(matchups, list):
+            merge_prophetx_into_matchups(matchups, prophetx_matchup_data)
+    except Exception as e:
+        stats["prophetx_error"] = str(e)
+
+
 def pull_live_edges(
     tour: str = "pga",
     tournament_slug: str | None = None,
@@ -169,12 +218,13 @@ def pull_live_edges(
     matched = _override_dg_with_live(outrights, live_players)
     stats["matched"] = matched
 
+    # Date range for prediction market matching
+    today = datetime.now().strftime("%Y-%m-%d")
+    end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
+
     # Step 4: Pull and merge Kalshi odds (now safe — we have live DG data)
     if include_kalshi:
         try:
-            today = datetime.now().strftime("%Y-%m-%d")
-            end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
-
             kalshi_outrights = pull_kalshi_outrights(
                 tournament_name, today, end_date,
                 tournament_slug=tournament_slug,
@@ -185,6 +235,14 @@ def pull_live_edges(
         except Exception as e:
             stats["kalshi_error"] = str(e)
 
+    # Step 4b: Pull and merge Polymarket outrights
+    _pull_polymarket_block(outrights, stats, tournament_name, today, end_date,
+                           tournament_slug=tournament_slug)
+
+    # Step 4c: Pull and merge ProphetX outrights (matchups merged in step 7)
+    _pull_prophetx_block(outrights, [], stats, tournament_name, today, end_date,
+                         tournament_slug=tournament_slug)
+
     # Step 5: Get bankroll and existing bets
     bankroll = db.get_bankroll()
     existing_bets = db.get_open_bets_for_week()
@@ -227,8 +285,6 @@ def pull_live_edges(
             # Merge Kalshi matchups if available
             if include_kalshi:
                 try:
-                    today = datetime.now().strftime("%Y-%m-%d")
-                    end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
                     kalshi_matchup_data = pull_kalshi_matchups(
                         tournament_name, today, end_date,
                         tournament_slug=tournament_slug,
@@ -238,6 +294,18 @@ def pull_live_edges(
                 except Exception:
                     pass
 
+            # Merge ProphetX matchups
+            if config.PROPHETX_ENABLED:
+                try:
+                    prophetx_matchup_data = pull_prophetx_matchups(
+                        tournament_name, today, end_date,
+                        tournament_slug=tournament_slug,
+                    )
+                    if prophetx_matchup_data:
+                        merge_prophetx_into_matchups(round_matchups, prophetx_matchup_data)
+                except Exception:
+                    pass
+
             edges = calculate_matchup_edges(
                 round_matchups, bankroll=bankroll,
                 existing_bets=existing_bets + [
diff --git a/tests/test_workflow_integration.py b/tests/test_workflow_integration.py
new file mode 100644
index 0000000..edc6475
--- /dev/null
+++ b/tests/test_workflow_integration.py
@@ -0,0 +1,189 @@
+"""Tests for workflow integration with prediction markets (section 10).
+
+Tests that Polymarket and ProphetX blocks are properly gated by
+config flags, handle failures gracefully, and integrate into
+the existing DG + Kalshi pipeline.
+"""
+
+from __future__ import annotations
+
+from unittest.mock import MagicMock, patch
+
+import pytest
+
+
+# ── run_pretournament.py integration ─��──────────────────────────────
+
+
+class TestPretournamentPolymarket:
+    """Polymarket block in pretournament workflow."""
+
+    @patch("config.POLYMARKET_ENABLED", True)
+    @patch("scripts.run_pretournament.pull_polymarket_outrights")
+    @patch("scripts.run_pretournament.merge_polymarket_into_outrights")
+    def test_polymarket_runs_when_enabled(self, mock_merge, mock_pull):
+        mock_pull.return_value = {"win": [{"player_name": "Test", "polymarket_mid_prob": 0.2}]}
+
+        from scripts.run_pretournament import _pull_polymarket_block
+        outrights = {"win": [{"player_name": "Test"}]}
+        _pull_polymarket_block(outrights, "The Masters", "2026-04-09", "2026-04-12")
+
+        mock_pull.assert_called_once()
+        mock_merge.assert_called_once()
+
+    @patch("config.POLYMARKET_ENABLED", False)
+    @patch("scripts.run_pretournament.pull_polymarket_outrights")
+    def test_polymarket_skips_when_disabled(self, mock_pull):
+        from scripts.run_pretournament import _pull_polymarket_block
+        outrights = {"win": [{"player_name": "Test"}]}
+        _pull_polymarket_block(outrights, "The Masters", "2026-04-09", "2026-04-12")
+
+        mock_pull.assert_not_called()
+
+    @patch("config.POLYMARKET_ENABLED", True)
+    @patch("scripts.run_pretournament.pull_polymarket_outrights", side_effect=Exception("API down"))
+    def test_polymarket_failure_continues(self, mock_pull):
+        from scripts.run_pretournament import _pull_polymarket_block
+        outrights = {"win": [{"player_name": "Test"}]}
+        # Should not raise
+        _pull_polymarket_block(outrights, "The Masters", "2026-04-09", "2026-04-12")
+
+
+class TestPretournamentProphetX:
+    """ProphetX block in pretournament workflow."""
+
+    @patch("config.PROPHETX_ENABLED", True)
+    @patch("scripts.run_pretournament.pull_prophetx_outrights")
+    @patch("scripts.run_pretournament.pull_prophetx_matchups")
+    @patch("scripts.run_pretournament.merge_prophetx_into_outrights")
+    @patch("scripts.run_pretournament.merge_prophetx_into_matchups")
+    def test_prophetx_runs_when_enabled(
+        self, mock_merge_m, mock_merge_o, mock_pull_m, mock_pull_o,
+    ):
+        mock_pull_o.return_value = {"win": [{"player_name": "Test"}]}
+        mock_pull_m.return_value = [{"p1_name": "A", "p2_name": "B"}]
+
+        from scripts.run_pretournament import _pull_prophetx_block
+        outrights = {"win": [{"player_name": "Test"}]}
+        matchups = []
+        _pull_prophetx_block(outrights, matchups, "The Masters", "2026-04-09", "2026-04-12")
+
+        mock_pull_o.assert_called_once()
+        mock_pull_m.assert_called_once()
+
+    @patch("config.PROPHETX_ENABLED", False)
+    @patch("scripts.run_pretournament.pull_prophetx_outrights")
+    def test_prophetx_skips_when_disabled(self, mock_pull):
+        from scripts.run_pretournament import _pull_prophetx_block
+        outrights = {"win": []}
+        matchups = []
+        _pull_prophetx_block(outrights, matchups, "The Masters", "2026-04-09", "2026-04-12")
+
+        mock_pull.assert_not_called()
+
+    @patch("config.PROPHETX_ENABLED", True)
+    @patch("scripts.run_pretournament.pull_prophetx_outrights", side_effect=Exception("Auth fail"))
+    def test_prophetx_failure_continues(self, mock_pull):
+        from scripts.run_pretournament import _pull_prophetx_block
+        outrights = {"win": []}
+        matchups = []
+        # Should not raise
+        _pull_prophetx_block(outrights, matchups, "The Masters", "2026-04-09", "2026-04-12")
+
+
+# ── run_preround.py integration ─────────────────────────────────────
+
+
+class TestPreroundProphetX:
+    """ProphetX matchup block in preround workflow."""
+
+    @patch("config.PROPHETX_ENABLED", True)
+    @patch("scripts.run_preround.pull_prophetx_matchups")
+    @patch("scripts.run_preround.merge_prophetx_into_matchups")
+    def test_prophetx_matchups_merged(self, mock_merge, mock_pull):
+        mock_pull.return_value = [{"p1_name": "A", "p2_name": "B", "p1_prob": 0.55, "p2_prob": 0.45}]
+
+        from scripts.run_preround import _pull_prophetx_matchup_block
+        matchups = [{"p1_player_name": "A", "p2_player_name": "B", "odds": {}}]
+        _pull_prophetx_matchup_block(matchups, "The Masters", "2026-04-09", "2026-04-12")
+
+        mock_pull.assert_called_once()
+        mock_merge.assert_called_once()
+
+    @patch("config.PROPHETX_ENABLED", False)
+    @patch("scripts.run_preround.pull_prophetx_matchups")
+    def test_prophetx_skips_when_disabled(self, mock_pull):
+        from scripts.run_preround import _pull_prophetx_matchup_block
+        matchups = []
+        _pull_prophetx_matchup_block(matchups, "The Masters", "2026-04-09", "2026-04-12")
+
+        mock_pull.assert_not_called()
+
+
+# ── pull_live_edges.py integration ─���────────────────────────────────
+
+
+class TestLiveEdgesIntegration:
+    """Prediction market blocks in live edge pipeline."""
+
+    @patch("config.POLYMARKET_ENABLED", True)
+    @patch("src.pipeline.pull_live_edges.pull_polymarket_outrights")
+    @patch("src.pipeline.pull_live_edges.merge_polymarket_into_outrights")
+    def test_polymarket_merged_in_live(self, mock_merge, mock_pull):
+        mock_pull.return_value = {"win": [{"player_name": "Test"}]}
+
+        from src.pipeline.pull_live_edges import _pull_polymarket_block
+        outrights = {"win": []}
+        stats = {}
+        _pull_polymarket_block(outrights, stats, "Masters", "2026-04-09", "2026-04-12")
+
+        mock_pull.assert_called_once()
+        assert stats.get("polymarket_merged") is True
+
+    @patch("config.PROPHETX_ENABLED", True)
+    @patch("src.pipeline.pull_live_edges.pull_prophetx_outrights")
+    @patch("src.pipeline.pull_live_edges.pull_prophetx_matchups")
+    @patch("src.pipeline.pull_live_edges.merge_prophetx_into_outrights")
+    def test_prophetx_merged_in_live(self, mock_merge, mock_pull_m, mock_pull):
+        mock_pull.return_value = {"win": [{"player_name": "Test"}]}
+        mock_pull_m.return_value = []
+
+        from src.pipeline.pull_live_edges import _pull_prophetx_block
+        outrights = {"win": []}
+        matchups = []
+        stats = {}
+        _pull_prophetx_block(outrights, matchups, stats, "Masters", "2026-04-09", "2026-04-12")
+
+        mock_pull.assert_called_once()
+        assert stats.get("prophetx_merged") is True
+
+    @patch("config.POLYMARKET_ENABLED", True)
+    @patch("src.pipeline.pull_live_edges.pull_polymarket_outrights", side_effect=Exception("fail"))
+    def test_polymarket_failure_tracked_in_stats(self, mock_pull):
+        from src.pipeline.pull_live_edges import _pull_polymarket_block
+        outrights = {"win": []}
+        stats = {}
+        _pull_polymarket_block(outrights, stats, "Masters", "2026-04-09", "2026-04-12")
+
+        assert "polymarket_error" in stats
+
+
+# ── DG-only regression ─────────────────────────────────────��────────
+
+
+class TestDGOnlyRegression:
+    """Pipeline works with all prediction markets disabled/failing."""
+
+    @patch("config.POLYMARKET_ENABLED", False)
+    @patch("config.PROPHETX_ENABLED", False)
+    def test_pretournament_blocks_skip_cleanly(self):
+        from scripts.run_pretournament import _pull_polymarket_block, _pull_prophetx_block
+        outrights = {"win": [{"player_name": "Test"}]}
+        matchups = []
+
+        # Both should complete without error
+        _pull_polymarket_block(outrights, "Test", "2026-01-01", "2026-01-04")
+        _pull_prophetx_block(outrights, matchups, "Test", "2026-01-01", "2026-01-04")
+
+        # Outrights should be unmodified
+        assert outrights == {"win": [{"player_name": "Test"}]}
