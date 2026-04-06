diff --git a/planning/prediction-markets/implementation/deep_implement_config.json b/planning/prediction-markets/implementation/deep_implement_config.json
index 0685ce0..785b89c 100644
--- a/planning/prediction-markets/implementation/deep_implement_config.json
+++ b/planning/prediction-markets/implementation/deep_implement_config.json
@@ -35,6 +35,10 @@
     "section-04-polymarket-client": {
       "status": "complete",
       "commit_hash": "113bdbe"
+    },
+    "section-05-polymarket-matching": {
+      "status": "complete",
+      "commit_hash": "66c63b2"
     }
   },
   "pre_commit": {
diff --git a/src/pipeline/pull_polymarket.py b/src/pipeline/pull_polymarket.py
new file mode 100644
index 0000000..f797383
--- /dev/null
+++ b/src/pipeline/pull_polymarket.py
@@ -0,0 +1,217 @@
+"""Polymarket prediction market odds pull. Win, T10, T20 outrights only."""
+
+from __future__ import annotations
+
+import json
+import logging
+
+import config
+from src.api.polymarket import PolymarketClient
+from src.core.devig import binary_price_to_american
+from src.pipeline.polymarket_matching import (
+    extract_player_name,
+    match_all_market_types,
+    resolve_polymarket_player,
+)
+
+logger = logging.getLogger(__name__)
+
+# DG uses "top_10"/"top_20", our pull returns "t10"/"t20"
+_DG_TO_POLYMARKET_MARKET = {"win": "win", "top_10": "t10", "top_20": "t20"}
+
+
+def _identify_yes_token(market: dict) -> str | None:
+    """Find the YES token ID from the market's outcomes array.
+
+    Returns the clobTokenId corresponding to the "Yes" outcome,
+    or None if not found.
+    """
+    outcomes_raw = market.get("outcomes", "[]")
+    token_ids_raw = market.get("clobTokenIds", "[]")
+
+    try:
+        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
+        token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
+    except (json.JSONDecodeError, TypeError):
+        return None
+
+    for i, outcome in enumerate(outcomes):
+        if isinstance(outcome, str) and outcome.lower() == "yes":
+            if i < len(token_ids):
+                return token_ids[i]
+    return None
+
+
+def _best_bid(orderbook: dict) -> float:
+    """Extract the highest bid price. Returns 0.0 if no bids."""
+    bids = orderbook.get("bids", [])
+    if not bids:
+        return 0.0
+    return max(float(b["price"]) for b in bids)
+
+
+def _best_ask(orderbook: dict) -> float:
+    """Extract the lowest ask price. Returns 1.0 if no asks."""
+    asks = orderbook.get("asks", [])
+    if not asks:
+        return 1.0
+    return min(float(a["price"]) for a in asks)
+
+
+def pull_polymarket_outrights(
+    tournament_name: str,
+    tournament_start: str,
+    tournament_end: str,
+    tournament_slug: str | None = None,
+) -> dict[str, list[dict]]:
+    """Pull Polymarket outright odds for win, t10, t20.
+
+    Returns {"win": [...], "t10": [...], "t20": [...]} with only
+    market types that had matched events.
+    """
+    client = PolymarketClient()
+    matched_events = match_all_market_types(
+        client, tournament_name, tournament_start, tournament_end,
+    )
+
+    if not matched_events:
+        return {}
+
+    results = {}
+
+    for market_type, event in matched_events.items():
+        try:
+            markets = event.get("markets", [])
+            if not markets:
+                continue
+
+            # Collect YES token IDs for batch book fetch
+            token_map = {}  # token_id → market
+            for market in markets:
+                yes_token = _identify_yes_token(market)
+                if yes_token:
+                    token_map[yes_token] = market
+                else:
+                    logger.warning(
+                        "Polymarket: no YES token for market '%s'",
+                        market.get("slug", "unknown"),
+                    )
+
+            if not token_map:
+                continue
+
+            # Batch fetch orderbooks
+            books = client.get_books(list(token_map.keys()))
+
+            players = []
+            event_slug = event.get("slug", "")
+
+            for token_id, market in token_map.items():
+                orderbook = books.get(token_id, {})
+
+                has_bids = bool(orderbook.get("bids"))
+                has_asks = bool(orderbook.get("asks"))
+
+                # Skip if both sides empty
+                if not has_bids and not has_asks:
+                    continue
+
+                bid = _best_bid(orderbook)
+                ask = _best_ask(orderbook)
+                midpoint = (bid + ask) / 2.0
+
+                # Relative spread filter (only when both sides present)
+                if has_bids and has_asks:
+                    spread = ask - bid
+                    max_allowed = max(
+                        config.POLYMARKET_MAX_SPREAD_ABS,
+                        config.POLYMARKET_MAX_SPREAD_REL * midpoint,
+                    )
+                    if spread > max_allowed:
+                        continue
+
+                # Volume filter
+                volume = float(market.get("volume", 0))
+                if volume < config.POLYMARKET_MIN_VOLUME:
+                    continue
+
+                # Extract and resolve player name
+                name = extract_player_name(market, event_slug=event_slug)
+                if not name:
+                    continue
+
+                resolved = resolve_polymarket_player(name)
+                canonical = resolved["canonical_name"] if resolved else name
+
+                # Fee-adjusted ask
+                adjusted_ask = ask + config.POLYMARKET_FEE_RATE
+
+                players.append({
+                    "player_name": canonical,
+                    "polymarket_mid_prob": midpoint,
+                    "polymarket_ask_prob": adjusted_ask,
+                    "volume": volume,
+                })
+
+            if players:
+                results[market_type] = players
+
+        except Exception:
+            logger.warning("Polymarket: pull failed for %s", market_type, exc_info=True)
+            continue
+
+    # Cache raw responses
+    if results and tournament_slug:
+        try:
+            client._cache_response(results, "polymarket_outrights", tournament_slug)
+        except Exception:
+            logger.debug("Polymarket: cache write failed", exc_info=True)
+
+    return results
+
+
+def merge_polymarket_into_outrights(
+    dg_outrights: dict[str, list[dict]],
+    polymarket_outrights: dict[str, list[dict]],
+) -> dict[str, list[dict]]:
+    """Inject Polymarket data as book columns into DG outright data.
+
+    For each market type, finds matching players by canonical name, then:
+    1. Adds "polymarket" key with American odds string (from midpoint prob)
+    2. Adds "_polymarket_ask_prob" key with fee-adjusted ask probability (float)
+
+    Mutates dg_outrights in-place and returns it.
+    """
+    for dg_key, poly_key in _DG_TO_POLYMARKET_MARKET.items():
+        dg_players = dg_outrights.get(dg_key)
+        poly_players = polymarket_outrights.get(poly_key, [])
+
+        if not dg_players or not poly_players:
+            continue
+
+        # Build lookup by normalized player name
+        poly_lookup = {}
+        for pp in poly_players:
+            name = pp["player_name"].strip().lower()
+            if name not in poly_lookup:
+                poly_lookup[name] = pp
+
+        # Match and inject
+        for player in dg_players:
+            pname = player.get("player_name", "").strip().lower()
+            pp = poly_lookup.get(pname)
+            if not pp:
+                continue
+
+            mid_prob = pp["polymarket_mid_prob"]
+            if mid_prob <= 0 or mid_prob >= 1:
+                continue
+
+            american = binary_price_to_american(str(mid_prob))
+            if not american:
+                continue
+
+            player["polymarket"] = american
+            player["_polymarket_ask_prob"] = pp["polymarket_ask_prob"]
+
+    return dg_outrights
diff --git a/tests/test_pull_polymarket.py b/tests/test_pull_polymarket.py
new file mode 100644
index 0000000..e55e30e
--- /dev/null
+++ b/tests/test_pull_polymarket.py
@@ -0,0 +1,344 @@
+"""Tests for Polymarket pipeline pull and merge (outrights only)."""
+
+from __future__ import annotations
+
+from unittest.mock import MagicMock, patch
+
+import pytest
+
+from src.pipeline.pull_polymarket import (
+    merge_polymarket_into_outrights,
+    pull_polymarket_outrights,
+)
+
+
+# ── Helpers ─────────────────────────────────────────────────────────
+
+def _make_polymarket_market(
+    question: str = "Will Scottie Scheffler win the Masters?",
+    slug: str = "pga-tour-masters-scottie-scheffler",
+    outcomes: str = '["Yes","No"]',
+    clob_token_ids: str = '["0xYES","0xNO"]',
+    outcome_prices: str = '["0.30","0.70"]',
+    volume: float = 5000.0,
+    group_item_title: str = "Scottie Scheffler",
+) -> dict:
+    return {
+        "question": question,
+        "slug": slug,
+        "outcomes": outcomes,
+        "clobTokenIds": clob_token_ids,
+        "outcomePrices": outcome_prices,
+        "volume": volume,
+        "groupItemTitle": group_item_title,
+    }
+
+
+def _make_event_with_markets(markets: list[dict]) -> dict:
+    return {
+        "title": "PGA Tour: The Masters Winner",
+        "startDate": "2026-04-09T00:00:00Z",
+        "endDate": "2026-04-13T00:00:00Z",
+        "slug": "pga-tour-masters",
+        "markets": markets,
+    }
+
+
+def _make_orderbook(best_bid: float = 0.28, best_ask: float = 0.32) -> dict:
+    """Build a simple orderbook with one bid and one ask."""
+    bids = [{"price": str(best_bid), "size": "100"}] if best_bid > 0 else []
+    asks = [{"price": str(best_ask), "size": "100"}] if best_ask < 1.0 else []
+    return {"bids": bids, "asks": asks}
+
+
+# ── TestPullPolymarketOutrights ─────────────────────────────────────
+
+class TestPullPolymarketOutrights:
+
+    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
+    @patch("src.pipeline.pull_polymarket.extract_player_name")
+    @patch("src.pipeline.pull_polymarket.match_all_market_types")
+    @patch("src.pipeline.pull_polymarket.PolymarketClient")
+    def test_returns_market_type_dict(self, MockClient, mock_match, mock_extract, mock_resolve):
+        """Should return dict with win, t10, t20 keys."""
+        market = _make_polymarket_market()
+        event = _make_event_with_markets([market])
+        mock_match.return_value = {"win": event}
+
+        client = MockClient.return_value
+        client.get_books.return_value = {"0xYES": _make_orderbook(0.28, 0.32)}
+
+        mock_extract.return_value = "Scottie Scheffler"
+        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}
+
+        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
+        assert "win" in result
+        assert len(result["win"]) == 1
+
+    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
+    @patch("src.pipeline.pull_polymarket.extract_player_name")
+    @patch("src.pipeline.pull_polymarket.match_all_market_types")
+    @patch("src.pipeline.pull_polymarket.PolymarketClient")
+    def test_player_entry_fields(self, MockClient, mock_match, mock_extract, mock_resolve):
+        """Each entry should have player_name, polymarket_mid_prob, polymarket_ask_prob, volume."""
+        market = _make_polymarket_market(volume=5000.0)
+        event = _make_event_with_markets([market])
+        mock_match.return_value = {"win": event}
+
+        client = MockClient.return_value
+        client.get_books.return_value = {"0xYES": _make_orderbook(0.28, 0.32)}
+
+        mock_extract.return_value = "Scottie Scheffler"
+        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}
+
+        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
+        entry = result["win"][0]
+        assert "player_name" in entry
+        assert "polymarket_mid_prob" in entry
+        assert "polymarket_ask_prob" in entry
+        assert "volume" in entry
+        assert entry["player_name"] == "Scottie Scheffler"
+
+    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
+    @patch("src.pipeline.pull_polymarket.extract_player_name")
+    @patch("src.pipeline.pull_polymarket.match_all_market_types")
+    @patch("src.pipeline.pull_polymarket.PolymarketClient")
+    def test_yes_token_identified_by_outcome_label(self, MockClient, mock_match, mock_extract, mock_resolve):
+        """YES token found via outcomes array, not assumed index 0."""
+        # Swap order: No first, Yes second
+        market = _make_polymarket_market(
+            outcomes='["No","Yes"]',
+            clob_token_ids='["0xNO","0xYES"]',
+            outcome_prices='["0.70","0.30"]',
+        )
+        event = _make_event_with_markets([market])
+        mock_match.return_value = {"win": event}
+
+        client = MockClient.return_value
+        # Only provide book for 0xYES
+        client.get_books.return_value = {"0xYES": _make_orderbook(0.28, 0.32)}
+
+        mock_extract.return_value = "Scottie Scheffler"
+        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}
+
+        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
+        assert len(result["win"]) == 1
+
+    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
+    @patch("src.pipeline.pull_polymarket.extract_player_name")
+    @patch("src.pipeline.pull_polymarket.match_all_market_types")
+    @patch("src.pipeline.pull_polymarket.PolymarketClient")
+    def test_skips_when_yes_token_not_found(self, MockClient, mock_match, mock_extract, mock_resolve):
+        """Market with no 'Yes' outcome should be skipped."""
+        market = _make_polymarket_market(
+            outcomes='["Up","Down"]',
+            clob_token_ids='["0xUP","0xDOWN"]',
+        )
+        event = _make_event_with_markets([market])
+        mock_match.return_value = {"win": event}
+
+        client = MockClient.return_value
+        client.get_books.return_value = {}
+
+        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
+        assert result.get("win", []) == []
+
+    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
+    @patch("src.pipeline.pull_polymarket.extract_player_name")
+    @patch("src.pipeline.pull_polymarket.match_all_market_types")
+    @patch("src.pipeline.pull_polymarket.PolymarketClient")
+    def test_empty_bids_uses_zero(self, MockClient, mock_match, mock_extract, mock_resolve):
+        """No bids → bid=0, still produces result with ask."""
+        market = _make_polymarket_market()
+        event = _make_event_with_markets([market])
+        mock_match.return_value = {"win": event}
+
+        client = MockClient.return_value
+        # Empty bids, ask at 0.32
+        client.get_books.return_value = {"0xYES": {"bids": [], "asks": [{"price": "0.32", "size": "100"}]}}
+
+        mock_extract.return_value = "Scottie Scheffler"
+        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}
+
+        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
+        entry = result["win"][0]
+        # mid = (0 + 0.32) / 2 = 0.16
+        assert entry["polymarket_mid_prob"] == pytest.approx(0.16)
+
+    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
+    @patch("src.pipeline.pull_polymarket.extract_player_name")
+    @patch("src.pipeline.pull_polymarket.match_all_market_types")
+    @patch("src.pipeline.pull_polymarket.PolymarketClient")
+    def test_empty_asks_uses_one(self, MockClient, mock_match, mock_extract, mock_resolve):
+        """No asks → ask=1.0, still produces result with bid."""
+        market = _make_polymarket_market()
+        event = _make_event_with_markets([market])
+        mock_match.return_value = {"win": event}
+
+        client = MockClient.return_value
+        client.get_books.return_value = {"0xYES": {"bids": [{"price": "0.28", "size": "100"}], "asks": []}}
+
+        mock_extract.return_value = "Scottie Scheffler"
+        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}
+
+        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
+        entry = result["win"][0]
+        # mid = (0.28 + 1.0) / 2 = 0.64
+        assert entry["polymarket_mid_prob"] == pytest.approx(0.64)
+
+    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
+    @patch("src.pipeline.pull_polymarket.extract_player_name")
+    @patch("src.pipeline.pull_polymarket.match_all_market_types")
+    @patch("src.pipeline.pull_polymarket.PolymarketClient")
+    def test_skips_both_sides_empty(self, MockClient, mock_match, mock_extract, mock_resolve):
+        """Both bids and asks empty → skip player."""
+        market = _make_polymarket_market()
+        event = _make_event_with_markets([market])
+        mock_match.return_value = {"win": event}
+
+        client = MockClient.return_value
+        client.get_books.return_value = {"0xYES": {"bids": [], "asks": []}}
+
+        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
+        assert result.get("win", []) == []
+
+    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
+    @patch("src.pipeline.pull_polymarket.extract_player_name")
+    @patch("src.pipeline.pull_polymarket.match_all_market_types")
+    @patch("src.pipeline.pull_polymarket.PolymarketClient")
+    def test_relative_spread_filter(self, MockClient, mock_match, mock_extract, mock_resolve):
+        """spread > max(abs_max, rel_factor * mid) → skip."""
+        market = _make_polymarket_market()
+        event = _make_event_with_markets([market])
+        mock_match.return_value = {"win": event}
+
+        client = MockClient.return_value
+        # Wide spread: bid=0.10, ask=0.50 → spread=0.40, mid=0.30
+        # max(0.10, 0.15*0.30) = max(0.10, 0.045) = 0.10
+        # 0.40 > 0.10 → filtered
+        client.get_books.return_value = {"0xYES": _make_orderbook(0.10, 0.50)}
+
+        mock_extract.return_value = "Scottie Scheffler"
+        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}
+
+        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
+        assert result.get("win", []) == []
+
+    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
+    @patch("src.pipeline.pull_polymarket.extract_player_name")
+    @patch("src.pipeline.pull_polymarket.match_all_market_types")
+    @patch("src.pipeline.pull_polymarket.PolymarketClient")
+    def test_volume_filter(self, MockClient, mock_match, mock_extract, mock_resolve):
+        """Markets below MIN_VOLUME should be skipped."""
+        market = _make_polymarket_market(volume=50.0)  # Below 100
+        event = _make_event_with_markets([market])
+        mock_match.return_value = {"win": event}
+
+        client = MockClient.return_value
+        client.get_books.return_value = {"0xYES": _make_orderbook(0.28, 0.32)}
+
+        mock_extract.return_value = "Scottie Scheffler"
+        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}
+
+        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
+        assert result.get("win", []) == []
+
+    @patch("src.pipeline.pull_polymarket.resolve_polymarket_player")
+    @patch("src.pipeline.pull_polymarket.extract_player_name")
+    @patch("src.pipeline.pull_polymarket.match_all_market_types")
+    @patch("src.pipeline.pull_polymarket.PolymarketClient")
+    def test_fee_adjusted_ask(self, MockClient, mock_match, mock_extract, mock_resolve):
+        """polymarket_ask_prob = ask + POLYMARKET_FEE_RATE."""
+        market = _make_polymarket_market()
+        event = _make_event_with_markets([market])
+        mock_match.return_value = {"win": event}
+
+        client = MockClient.return_value
+        client.get_books.return_value = {"0xYES": _make_orderbook(0.28, 0.32)}
+
+        mock_extract.return_value = "Scottie Scheffler"
+        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}
+
+        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
+        entry = result["win"][0]
+        # ask=0.32, fee=0.002 → adjusted=0.322
+        assert entry["polymarket_ask_prob"] == pytest.approx(0.322)
+
+    @patch("src.pipeline.pull_polymarket.match_all_market_types")
+    @patch("src.pipeline.pull_polymarket.PolymarketClient")
+    def test_returns_empty_on_no_match(self, MockClient, mock_match):
+        """No tournament match → empty dict."""
+        mock_match.return_value = {}
+
+        result = pull_polymarket_outrights("The Masters", "2026-04-09", "2026-04-13")
+        assert result == {}
+
+
+# ── TestMergePolymarketIntoOutrights ────────────────────────────────
+
+class TestMergePolymarketIntoOutrights:
+
+    def test_adds_polymarket_odds_key(self):
+        """Merge adds 'polymarket' American odds key."""
+        dg = {"win": [{"player_name": "Scottie Scheffler"}]}
+        poly = {"win": [{"player_name": "Scottie Scheffler", "polymarket_mid_prob": 0.30, "polymarket_ask_prob": 0.322, "volume": 5000}]}
+
+        result = merge_polymarket_into_outrights(dg, poly)
+        assert "polymarket" in result["win"][0]
+
+    def test_adds_ask_prob_key(self):
+        """Merge adds '_polymarket_ask_prob' float."""
+        dg = {"win": [{"player_name": "Scottie Scheffler"}]}
+        poly = {"win": [{"player_name": "Scottie Scheffler", "polymarket_mid_prob": 0.30, "polymarket_ask_prob": 0.322, "volume": 5000}]}
+
+        result = merge_polymarket_into_outrights(dg, poly)
+        assert result["win"][0]["_polymarket_ask_prob"] == pytest.approx(0.322)
+
+    def test_skips_unmatched_dg_players(self):
+        """DG players not in Polymarket should be unchanged."""
+        dg = {"win": [
+            {"player_name": "Scottie Scheffler"},
+            {"player_name": "Jon Rahm"},
+        ]}
+        poly = {"win": [{"player_name": "Scottie Scheffler", "polymarket_mid_prob": 0.30, "polymarket_ask_prob": 0.322, "volume": 5000}]}
+
+        result = merge_polymarket_into_outrights(dg, poly)
+        assert "polymarket" in result["win"][0]
+        assert "polymarket" not in result["win"][1]
+
+    def test_case_insensitive_matching(self):
+        """Name matching should be case-insensitive."""
+        dg = {"win": [{"player_name": "scottie scheffler"}]}
+        poly = {"win": [{"player_name": "Scottie Scheffler", "polymarket_mid_prob": 0.30, "polymarket_ask_prob": 0.322, "volume": 5000}]}
+
+        result = merge_polymarket_into_outrights(dg, poly)
+        assert "polymarket" in result["win"][0]
+
+    def test_uses_binary_price_to_american(self):
+        """Odds should be converted via binary_price_to_american."""
+        dg = {"win": [{"player_name": "Scottie Scheffler"}]}
+        poly = {"win": [{"player_name": "Scottie Scheffler", "polymarket_mid_prob": 0.30, "polymarket_ask_prob": 0.322, "volume": 5000}]}
+
+        result = merge_polymarket_into_outrights(dg, poly)
+        odds = result["win"][0]["polymarket"]
+        # 0.30 prob → +233 (approx)
+        assert odds.startswith("+")
+
+    def test_existing_books_not_modified(self):
+        """Existing book columns should be untouched."""
+        dg = {"win": [{"player_name": "Scottie Scheffler", "draftkings": "+300", "fanduel": "+280"}]}
+        poly = {"win": [{"player_name": "Scottie Scheffler", "polymarket_mid_prob": 0.30, "polymarket_ask_prob": 0.322, "volume": 5000}]}
+
+        result = merge_polymarket_into_outrights(dg, poly)
+        assert result["win"][0]["draftkings"] == "+300"
+        assert result["win"][0]["fanduel"] == "+280"
+
+
+# ── TestNoMatchupPull ───────────────────────────────────────────────
+
+class TestNoMatchupPull:
+
+    def test_no_matchup_function(self):
+        """pull_polymarket_matchups should not exist."""
+        import src.pipeline.pull_polymarket as mod
+        assert not hasattr(mod, "pull_polymarket_matchups")
