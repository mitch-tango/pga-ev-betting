diff --git a/planning/kalshi-integration/implementation/deep_implement_config.json b/planning/kalshi-integration/implementation/deep_implement_config.json
index 9faab86..5255a4b 100644
--- a/planning/kalshi-integration/implementation/deep_implement_config.json
+++ b/planning/kalshi-integration/implementation/deep_implement_config.json
@@ -28,6 +28,10 @@
     "section-03-config-schema": {
       "status": "complete",
       "commit_hash": "ac02814"
+    },
+    "section-04-tournament-matching": {
+      "status": "complete",
+      "commit_hash": "74ef649"
     }
   },
   "pre_commit": {
diff --git a/src/pipeline/pull_kalshi.py b/src/pipeline/pull_kalshi.py
new file mode 100644
index 0000000..4cb65f7
--- /dev/null
+++ b/src/pipeline/pull_kalshi.py
@@ -0,0 +1,239 @@
+"""
+Kalshi prediction market odds pull.
+
+Pulls win, T10, T20 outright odds and H2H matchup odds from Kalshi.
+Used by run_pretournament.py alongside DG API pulls.
+"""
+from __future__ import annotations
+
+import logging
+
+from src.api.kalshi import KalshiClient
+from src.core.devig import kalshi_midpoint
+from src.pipeline.kalshi_matching import (
+    extract_player_name_outright,
+    extract_player_names_h2h,
+    match_tournament,
+    resolve_kalshi_player,
+)
+import config
+
+# Future: Polymarket would follow a similar pattern here.
+# Polymarket covers outrights and top-N but NOT matchups,
+# and requires keyword-based event discovery via the Gamma API.
+
+logger = logging.getLogger(__name__)
+
+# Outright market types to pull (skip tournament_matchup — handled by pull_kalshi_matchups)
+_OUTRIGHT_KEYS = ("win", "t10", "t20")
+
+
+def _normalize_price(value) -> float:
+    """Normalize a Kalshi price to 0-1 range.
+
+    Kalshi may return prices as floats (0.06) or integer cents (6).
+    """
+    v = float(value)
+    if v > 1.0:
+        v /= 100.0
+    return v
+
+
+def pull_kalshi_outrights(
+    tournament_name: str,
+    tournament_start: str,
+    tournament_end: str,
+    tournament_slug: str | None = None,
+) -> dict[str, list[dict]]:
+    """Pull Kalshi outright odds for win, t10, t20 markets.
+
+    Args:
+        tournament_name: DG tournament name for matching.
+        tournament_start: ISO date string for tournament start.
+        tournament_end: ISO date string for tournament end.
+        tournament_slug: Optional slug for cache labeling.
+
+    Returns:
+        {"win": [...], "t10": [...], "t20": [...]} with player dicts.
+        Each dict has: player_name, kalshi_mid_prob, kalshi_ask_prob, open_interest.
+        Returns empty lists on any failure.
+    """
+    empty = {k: [] for k in _OUTRIGHT_KEYS}
+
+    try:
+        client = KalshiClient()
+
+        for market_key in _OUTRIGHT_KEYS:
+            series_ticker = config.KALSHI_SERIES_TICKERS.get(market_key)
+            if not series_ticker:
+                continue
+
+            # Find the current tournament event
+            events = client.get_golf_events(series_ticker)
+            event_ticker = match_tournament(
+                events, tournament_name, tournament_start, tournament_end,
+            )
+            if not event_ticker:
+                logger.info("Kalshi: no %s event matched for %s", market_key, tournament_name)
+                continue
+
+            # Fetch all markets (player contracts) for the event
+            markets = client.get_event_markets(event_ticker)
+
+            # Cache raw response
+            client._cache_response(
+                markets, f"kalshi_{market_key}",
+                tournament_slug=tournament_slug,
+            )
+
+            # Process each contract
+            players = []
+            for mkt in markets:
+                # Extract player name
+                raw_name = extract_player_name_outright(mkt)
+                if not raw_name:
+                    continue
+
+                # Read and normalize prices
+                try:
+                    bid = _normalize_price(mkt.get("yes_bid", 0))
+                    ask = _normalize_price(mkt.get("yes_ask", 0))
+                except (ValueError, TypeError):
+                    logger.warning("Kalshi: invalid price data for %s", raw_name)
+                    continue
+
+                # Compute midpoint
+                mid = kalshi_midpoint(str(bid), str(ask))
+                if mid is None:
+                    continue
+
+                # Read open interest
+                oi = int(mkt.get("open_interest", 0))
+
+                # Filter: OI threshold
+                if oi < config.KALSHI_MIN_OPEN_INTEREST:
+                    continue
+
+                # Filter: spread threshold
+                if (ask - bid) > config.KALSHI_MAX_SPREAD:
+                    continue
+
+                # Resolve player name to DG canonical
+                resolved = resolve_kalshi_player(raw_name)
+                if not resolved:
+                    logger.warning("Kalshi: could not resolve player '%s'", raw_name)
+                    continue
+
+                players.append({
+                    "player_name": resolved["canonical_name"],
+                    "kalshi_mid_prob": mid,
+                    "kalshi_ask_prob": ask,
+                    "open_interest": oi,
+                })
+
+            empty[market_key] = players
+
+        return empty
+
+    except Exception:
+        logger.warning("Kalshi: outright pull failed", exc_info=True)
+        return {k: [] for k in _OUTRIGHT_KEYS}
+
+
+def pull_kalshi_matchups(
+    tournament_name: str,
+    tournament_start: str,
+    tournament_end: str,
+    tournament_slug: str | None = None,
+) -> list[dict]:
+    """Pull Kalshi H2H matchup odds.
+
+    Args:
+        tournament_name: DG tournament name for matching.
+        tournament_start: ISO date string for tournament start.
+        tournament_end: ISO date string for tournament end.
+        tournament_slug: Optional slug for cache labeling.
+
+    Returns:
+        List of matchup dicts with p1_name, p2_name, p1_prob, p2_prob, p1_oi, p2_oi.
+        Empty list on any failure.
+    """
+    try:
+        client = KalshiClient()
+
+        series_ticker = config.KALSHI_SERIES_TICKERS.get("tournament_matchup")
+        if not series_ticker:
+            return []
+
+        events = client.get_golf_events(series_ticker)
+        event_ticker = match_tournament(
+            events, tournament_name, tournament_start, tournament_end,
+        )
+        if not event_ticker:
+            logger.info("Kalshi: no H2H event matched for %s", tournament_name)
+            return []
+
+        markets = client.get_event_markets(event_ticker)
+
+        # Cache raw response
+        client._cache_response(
+            markets, "kalshi_h2h", tournament_slug=tournament_slug,
+        )
+
+        results = []
+        for mkt in markets:
+            # Extract both player names from H2H title
+            names = extract_player_names_h2h(mkt)
+            if not names:
+                continue
+            p1_raw, p2_raw = names
+
+            # Read and normalize prices
+            try:
+                p1_bid = _normalize_price(mkt.get("yes_bid", 0))
+                p1_ask = _normalize_price(mkt.get("yes_ask", 0))
+            except (ValueError, TypeError):
+                continue
+
+            # P2 is the complement (NO side)
+            p2_bid = 1.0 - p1_ask
+            p2_ask = 1.0 - p1_bid
+
+            # Open interest (same for both sides of a binary contract)
+            oi = int(mkt.get("open_interest", 0))
+
+            # Filter: OI threshold
+            if oi < config.KALSHI_MIN_OPEN_INTEREST:
+                continue
+
+            # Filter: spread threshold (YES side spread)
+            if (p1_ask - p1_bid) > config.KALSHI_MAX_SPREAD:
+                continue
+
+            # Compute midpoints
+            p1_mid = kalshi_midpoint(str(p1_bid), str(p1_ask))
+            p2_mid = kalshi_midpoint(str(p2_bid), str(p2_ask))
+            if p1_mid is None or p2_mid is None:
+                continue
+
+            # Resolve player names
+            p1_resolved = resolve_kalshi_player(p1_raw)
+            p2_resolved = resolve_kalshi_player(p2_raw)
+            if not p1_resolved or not p2_resolved:
+                logger.warning("Kalshi: could not resolve H2H players '%s' vs '%s'", p1_raw, p2_raw)
+                continue
+
+            results.append({
+                "p1_name": p1_resolved["canonical_name"],
+                "p2_name": p2_resolved["canonical_name"],
+                "p1_prob": p1_mid,
+                "p2_prob": p2_mid,
+                "p1_oi": oi,
+                "p2_oi": oi,
+            })
+
+        return results
+
+    except Exception:
+        logger.warning("Kalshi: matchup pull failed", exc_info=True)
+        return []
diff --git a/tests/test_pull_kalshi.py b/tests/test_pull_kalshi.py
new file mode 100644
index 0000000..93da5ab
--- /dev/null
+++ b/tests/test_pull_kalshi.py
@@ -0,0 +1,272 @@
+"""Tests for Kalshi pipeline pull (outrights and matchups)."""
+
+from unittest.mock import patch, MagicMock
+
+from src.pipeline.pull_kalshi import pull_kalshi_outrights, pull_kalshi_matchups
+
+
+def _make_market(title, subtitle, yes_bid, yes_ask, open_interest,
+                 ticker="MKT-001"):
+    """Helper to build a Kalshi market dict."""
+    return {
+        "ticker": ticker,
+        "title": title,
+        "subtitle": subtitle,
+        "yes_bid": yes_bid,
+        "yes_ask": yes_ask,
+        "open_interest": open_interest,
+    }
+
+
+# ---- Outright fixtures ----
+
+_VALID_WIN_MARKETS = [
+    _make_market("Will Scottie Scheffler win?", "Scottie Scheffler",
+                 0.20, 0.24, 500, "MKT-W1"),
+    _make_market("Will Rory McIlroy win?", "Rory McIlroy",
+                 0.08, 0.10, 200, "MKT-W2"),
+]
+
+_VALID_T10_MARKETS = [
+    _make_market("Will Scottie Scheffler finish Top 10?", "Scottie Scheffler",
+                 0.50, 0.54, 300, "MKT-T1"),
+]
+
+
+@patch("src.pipeline.pull_kalshi.resolve_kalshi_player")
+@patch("src.pipeline.pull_kalshi.match_tournament")
+@patch("src.pipeline.pull_kalshi.KalshiClient")
+class TestPullKalshiOutrights:
+
+    def _setup_client(self, mock_cls, event_markets_by_ticker=None):
+        """Wire up mock client with events and markets."""
+        client = MagicMock()
+        mock_cls.return_value = client
+        # Each series ticker returns one event
+        client.get_golf_events.return_value = [
+            {"event_ticker": "EVT-WIN", "title": "PGA Tour: Masters Winner"},
+        ]
+        if event_markets_by_ticker:
+            client.get_event_markets.side_effect = (
+                lambda t: event_markets_by_ticker.get(t, [])
+            )
+        else:
+            client.get_event_markets.return_value = []
+        return client
+
+    def test_returns_dict_with_correct_keys(self, mock_cls, mock_match, mock_resolve):
+        self._setup_client(mock_cls)
+        mock_match.return_value = "EVT-WIN"
+        mock_resolve.return_value = {"canonical_name": "Scheffler, Scottie"}
+
+        result = pull_kalshi_outrights(
+            tournament_name="Masters", tournament_start="2026-04-09",
+            tournament_end="2026-04-12",
+        )
+        assert set(result.keys()) == {"win", "t10", "t20"}
+
+    def test_each_entry_has_required_fields(self, mock_cls, mock_match, mock_resolve):
+        client = self._setup_client(mock_cls)
+        client.get_event_markets.return_value = _VALID_WIN_MARKETS
+        mock_match.return_value = "EVT-WIN"
+        mock_resolve.return_value = {"canonical_name": "Scheffler, Scottie"}
+
+        result = pull_kalshi_outrights(
+            tournament_name="Masters", tournament_start="2026-04-09",
+            tournament_end="2026-04-12",
+        )
+        for entry in result["win"]:
+            assert "player_name" in entry
+            assert "kalshi_mid_prob" in entry
+            assert "kalshi_ask_prob" in entry
+            assert "open_interest" in entry
+            assert isinstance(entry["kalshi_mid_prob"], float)
+            assert isinstance(entry["open_interest"], int)
+
+    def test_filters_out_players_below_oi_threshold(self, mock_cls, mock_match, mock_resolve):
+        client = self._setup_client(mock_cls)
+        client.get_event_markets.return_value = [
+            _make_market("Win?", "Low OI Player", 0.10, 0.12, 50),   # below 100
+            _make_market("Win?", "High OI Player", 0.10, 0.12, 200),  # above 100
+        ]
+        mock_match.return_value = "EVT-WIN"
+        mock_resolve.return_value = {"canonical_name": "High OI Player"}
+
+        result = pull_kalshi_outrights(
+            tournament_name="Masters", tournament_start="2026-04-09",
+            tournament_end="2026-04-12",
+        )
+        assert len(result["win"]) == 1
+        assert result["win"][0]["open_interest"] == 200
+
+    def test_filters_out_players_with_wide_spread(self, mock_cls, mock_match, mock_resolve):
+        client = self._setup_client(mock_cls)
+        client.get_event_markets.return_value = [
+            _make_market("Win?", "Wide Spread", 0.10, 0.20, 200),  # spread=0.10
+            _make_market("Win?", "Tight Spread", 0.10, 0.14, 200),  # spread=0.04
+        ]
+        mock_match.return_value = "EVT-WIN"
+        mock_resolve.return_value = {"canonical_name": "Tight Spread"}
+
+        result = pull_kalshi_outrights(
+            tournament_name="Masters", tournament_start="2026-04-09",
+            tournament_end="2026-04-12",
+        )
+        assert len(result["win"]) == 1
+
+    def test_normalizes_integer_prices_to_0_1(self, mock_cls, mock_match, mock_resolve):
+        """Prices like 6 (instead of 0.06) should be divided by 100."""
+        client = self._setup_client(mock_cls)
+        client.get_event_markets.return_value = [
+            _make_market("Win?", "Player A", 6, 8, 200),  # integer cents
+        ]
+        mock_match.return_value = "EVT-WIN"
+        mock_resolve.return_value = {"canonical_name": "Player A"}
+
+        result = pull_kalshi_outrights(
+            tournament_name="Masters", tournament_start="2026-04-09",
+            tournament_end="2026-04-12",
+        )
+        assert len(result["win"]) == 1
+        entry = result["win"][0]
+        assert 0 < entry["kalshi_mid_prob"] < 1
+        assert 0 < entry["kalshi_ask_prob"] < 1
+
+    def test_returns_empty_on_api_failure(self, mock_cls, mock_match, mock_resolve):
+        client = self._setup_client(mock_cls)
+        client.get_golf_events.side_effect = Exception("Connection refused")
+
+        result = pull_kalshi_outrights(
+            tournament_name="Masters", tournament_start="2026-04-09",
+            tournament_end="2026-04-12",
+        )
+        assert result == {"win": [], "t10": [], "t20": []}
+
+    def test_returns_empty_when_no_golf_events(self, mock_cls, mock_match, mock_resolve):
+        client = self._setup_client(mock_cls)
+        client.get_golf_events.return_value = []
+        mock_match.return_value = None
+
+        result = pull_kalshi_outrights(
+            tournament_name="Masters", tournament_start="2026-04-09",
+            tournament_end="2026-04-12",
+        )
+        assert result == {"win": [], "t10": [], "t20": []}
+
+    def test_caches_raw_response(self, mock_cls, mock_match, mock_resolve):
+        client = self._setup_client(mock_cls)
+        client.get_event_markets.return_value = _VALID_WIN_MARKETS
+        mock_match.return_value = "EVT-WIN"
+        mock_resolve.return_value = {"canonical_name": "Scheffler, Scottie"}
+
+        pull_kalshi_outrights(
+            tournament_name="Masters", tournament_start="2026-04-09",
+            tournament_end="2026-04-12",
+        )
+        assert client._cache_response.called
+
+
+# ---- Matchup fixtures ----
+
+_VALID_H2H_MARKETS = [
+    {
+        "ticker": "MKT-H2H-1A",
+        "title": "Scottie Scheffler vs. Rory McIlroy",
+        "subtitle": "",
+        "yes_bid": 0.55,
+        "yes_ask": 0.58,
+        "open_interest": 300,
+    },
+]
+
+
+@patch("src.pipeline.pull_kalshi.resolve_kalshi_player")
+@patch("src.pipeline.pull_kalshi.match_tournament")
+@patch("src.pipeline.pull_kalshi.KalshiClient")
+class TestPullKalshiMatchups:
+
+    def _setup_client(self, mock_cls):
+        client = MagicMock()
+        mock_cls.return_value = client
+        client.get_golf_events.return_value = [
+            {"event_ticker": "EVT-H2H", "title": "PGA Tour: H2H"},
+        ]
+        return client
+
+    def test_returns_list_of_matchup_dicts(self, mock_cls, mock_match, mock_resolve):
+        client = self._setup_client(mock_cls)
+        client.get_event_markets.return_value = _VALID_H2H_MARKETS
+        mock_match.return_value = "EVT-H2H"
+        mock_resolve.side_effect = [
+            {"canonical_name": "Scheffler, Scottie"},
+            {"canonical_name": "McIlroy, Rory"},
+        ]
+
+        result = pull_kalshi_matchups(
+            tournament_name="Masters", tournament_start="2026-04-09",
+            tournament_end="2026-04-12",
+        )
+        assert isinstance(result, list)
+        assert len(result) == 1
+        m = result[0]
+        assert "p1_name" in m
+        assert "p2_name" in m
+        assert "p1_prob" in m
+        assert "p2_prob" in m
+        assert "p1_oi" in m
+        assert "p2_oi" in m
+
+    def test_filters_by_oi_threshold(self, mock_cls, mock_match, mock_resolve):
+        client = self._setup_client(mock_cls)
+        client.get_event_markets.return_value = [
+            {
+                "ticker": "MKT-H2H-LOW",
+                "title": "Low OI A vs. Low OI B",
+                "subtitle": "",
+                "yes_bid": 0.50,
+                "yes_ask": 0.53,
+                "open_interest": 30,  # below threshold
+            },
+        ]
+        mock_match.return_value = "EVT-H2H"
+        mock_resolve.side_effect = [
+            {"canonical_name": "Low OI A"},
+            {"canonical_name": "Low OI B"},
+        ]
+
+        result = pull_kalshi_matchups(
+            tournament_name="Masters", tournament_start="2026-04-09",
+            tournament_end="2026-04-12",
+        )
+        assert result == []
+
+    def test_filters_by_spread_threshold(self, mock_cls, mock_match, mock_resolve):
+        client = self._setup_client(mock_cls)
+        client.get_event_markets.return_value = [
+            {
+                "ticker": "MKT-H2H-WIDE",
+                "title": "Wide A vs. Wide B",
+                "subtitle": "",
+                "yes_bid": 0.40,
+                "yes_ask": 0.60,  # spread = 0.20
+                "open_interest": 500,
+            },
+        ]
+        mock_match.return_value = "EVT-H2H"
+
+        result = pull_kalshi_matchups(
+            tournament_name="Masters", tournament_start="2026-04-09",
+            tournament_end="2026-04-12",
+        )
+        assert result == []
+
+    def test_returns_empty_list_when_no_h2h_events(self, mock_cls, mock_match, mock_resolve):
+        client = self._setup_client(mock_cls)
+        client.get_golf_events.return_value = []
+        mock_match.return_value = None
+
+        result = pull_kalshi_matchups(
+            tournament_name="Masters", tournament_start="2026-04-09",
+            tournament_end="2026-04-12",
+        )
+        assert result == []
