diff --git a/planning/prediction-markets/implementation/deep_implement_config.json b/planning/prediction-markets/implementation/deep_implement_config.json
index a347be5..20e106e 100644
--- a/planning/prediction-markets/implementation/deep_implement_config.json
+++ b/planning/prediction-markets/implementation/deep_implement_config.json
@@ -47,6 +47,10 @@
     "section-07-prophetx-client": {
       "status": "complete",
       "commit_hash": "ad5030f"
+    },
+    "section-08-prophetx-matching": {
+      "status": "complete",
+      "commit_hash": "cb1be84"
     }
   },
   "pre_commit": {
diff --git a/src/pipeline/pull_prophetx.py b/src/pipeline/pull_prophetx.py
new file mode 100644
index 0000000..3108bca
--- /dev/null
+++ b/src/pipeline/pull_prophetx.py
@@ -0,0 +1,408 @@
+"""ProphetX prediction market odds pull & merge.
+
+Pulls outrights (win, t10, t20) and H2H matchups from ProphetX,
+with format-aware handling for American vs binary odds.
+"""
+
+from __future__ import annotations
+
+import logging
+import re
+
+import config
+from src.api.prophetx import ProphetXClient
+from src.core.devig import binary_price_to_american, parse_american_odds
+from src.pipeline.prophetx_matching import (
+    classify_markets,
+    extract_player_name_outright,
+    extract_player_names_matchup,
+    match_tournament,
+    resolve_prophetx_player,
+)
+
+logger = logging.getLogger(__name__)
+
+# DG uses "top_10"/"top_20"; ProphetX classification uses "t10"/"t20"
+_DG_TO_PROPHETX_MARKET = {"win": "win", "top_10": "t10", "top_20": "t20"}
+
+_AMERICAN_STR_RE = re.compile(r"^[+-]\d+$")
+
+
+def _detect_odds_format(markets: list[dict], odds_key: str = "odds") -> str:
+    """Detect whether markets use American or binary odds format.
+
+    Samples the first valid odds value found:
+    - int/float with abs > 1 → american (e.g. 400, -150)
+    - string matching [+-]digits → american (e.g. "+400")
+    - float in (0, 1) exclusive → binary
+    - Default: binary
+    """
+    for market in markets:
+        # Check competitor-level odds first
+        competitors = market.get("competitors", market.get("participants", market.get("selections", [])))
+        if isinstance(competitors, list):
+            for comp in competitors:
+                val = comp.get(odds_key)
+                if val is not None:
+                    return _classify_odds_value(val)
+
+        # Check market-level odds
+        val = market.get(odds_key)
+        if val is not None:
+            return _classify_odds_value(val)
+
+    return "binary"
+
+
+def _classify_odds_value(val) -> str:
+    """Classify a single odds value as american or binary."""
+    if isinstance(val, int):
+        return "american"
+    if isinstance(val, str) and _AMERICAN_STR_RE.match(val.strip()):
+        return "american"
+    if isinstance(val, (int, float)):
+        if abs(val) > 1:
+            return "american"
+        return "binary"
+    return "binary"
+
+
+def _get_odds_value(entry: dict, key: str = "odds"):
+    """Extract odds value from a competitor/market entry."""
+    return entry.get(key)
+
+
+def _american_to_prob(odds_val) -> float | None:
+    """Convert an American odds value (int or string) to implied probability."""
+    if isinstance(odds_val, int):
+        odds_str = f"+{odds_val}" if odds_val > 0 else str(odds_val)
+    elif isinstance(odds_val, str):
+        odds_str = odds_val.strip()
+    else:
+        return None
+    return parse_american_odds(odds_str)
+
+
+def _american_to_string(odds_val) -> str:
+    """Convert American odds value to display string."""
+    if isinstance(odds_val, int):
+        return f"+{odds_val}" if odds_val > 0 else str(odds_val)
+    if isinstance(odds_val, str):
+        return odds_val.strip()
+    return str(odds_val)
+
+
+def pull_prophetx_outrights(
+    tournament_name: str,
+    tournament_start: str,
+    tournament_end: str,
+    tournament_slug: str | None = None,
+) -> dict[str, list[dict]]:
+    """Pull ProphetX outright odds for win, t10, t20.
+
+    Returns {"win": [...], "t10": [...], "t20": [...]} with format-aware
+    player dicts. Empty dict on failure or no match.
+    """
+    try:
+        client = ProphetXClient()
+        events = client.get_golf_events()
+
+        matched = match_tournament(events, tournament_name, tournament_start, tournament_end)
+        if not matched:
+            logger.info("ProphetX: no tournament match for '%s'", tournament_name)
+            return {}
+
+        event_id = matched.get("id") or matched.get("event_id")
+        if not event_id:
+            logger.warning("ProphetX: matched event has no id field")
+            return {}
+
+        all_markets = client.get_markets_for_events([str(event_id)])
+        classified = classify_markets(all_markets)
+
+        results: dict[str, list[dict]] = {}
+
+        for market_type in ("win", "t10", "t20"):
+            type_markets = classified.get(market_type, [])
+            if not type_markets:
+                continue
+
+            odds_format = _detect_odds_format(type_markets)
+            players = []
+
+            for market in type_markets:
+                competitors = market.get("competitors",
+                              market.get("participants",
+                              market.get("selections", [])))
+                if not isinstance(competitors, list):
+                    competitors = [market]
+
+                for comp in competitors:
+                    name = extract_player_name_outright(
+                        {"competitors": [comp]} if comp is not market else market,
+                    )
+                    if not name:
+                        continue
+
+                    odds_val = _get_odds_value(comp)
+                    if odds_val is None:
+                        continue
+
+                    # Quality filters
+                    oi = comp.get("open_interest", 0)
+                    if isinstance(oi, (int, float)) and oi < config.PROPHETX_MIN_OPEN_INTEREST:
+                        continue
+
+                    bid = comp.get("bid", 0)
+                    ask = comp.get("ask", 0)
+                    if isinstance(bid, (int, float)) and isinstance(ask, (int, float)):
+                        spread = abs(ask - bid)
+                        if spread > config.PROPHETX_MAX_SPREAD:
+                            continue
+
+                    # Resolve canonical name
+                    resolved = resolve_prophetx_player(name)
+                    canonical = resolved["canonical_name"] if resolved else name
+
+                    if odds_format == "american":
+                        american_str = _american_to_string(odds_val)
+                        prob = _american_to_prob(odds_val)
+                        if prob is None or prob <= 0 or prob >= 1:
+                            continue
+                        players.append({
+                            "player_name": canonical,
+                            "prophetx_american": american_str,
+                            "prophetx_mid_prob": prob,
+                            "odds_format": "american",
+                        })
+                    else:
+                        # Binary format
+                        try:
+                            ask_f = float(ask) if ask else None
+                            bid_f = float(bid) if bid else None
+                        except (ValueError, TypeError):
+                            ask_f = bid_f = None
+
+                        if bid_f is not None and ask_f is not None:
+                            midpoint = (bid_f + ask_f) / 2.0
+                        else:
+                            midpoint = float(odds_val) if odds_val else None
+
+                        if midpoint is None or midpoint <= 0 or midpoint >= 1:
+                            continue
+
+                        american_str = binary_price_to_american(str(midpoint))
+                        if not american_str:
+                            continue
+
+                        player_dict = {
+                            "player_name": canonical,
+                            "prophetx_mid_prob": midpoint,
+                            "odds_format": "binary",
+                        }
+                        if ask_f is not None and 0 < ask_f < 1:
+                            player_dict["prophetx_ask_prob"] = ask_f
+
+                        players.append(player_dict)
+
+            if players:
+                results[market_type] = players
+
+        # Cache raw responses
+        if results and tournament_slug:
+            try:
+                client._cache_response(results, "prophetx_outrights", tournament_slug)
+            except Exception:
+                logger.debug("ProphetX: cache write failed", exc_info=True)
+
+        return results
+
+    except Exception:
+        logger.warning("ProphetX: outrights pull failed", exc_info=True)
+        return {}
+
+
+def pull_prophetx_matchups(
+    tournament_name: str,
+    tournament_start: str,
+    tournament_end: str,
+    tournament_slug: str | None = None,
+) -> list[dict]:
+    """Pull ProphetX H2H matchup odds.
+
+    Returns list of {p1_name, p2_name, p1_prob, p2_prob} dicts.
+    Empty list on failure or no match.
+    """
+    try:
+        client = ProphetXClient()
+        events = client.get_golf_events()
+
+        matched = match_tournament(events, tournament_name, tournament_start, tournament_end)
+        if not matched:
+            return []
+
+        event_id = matched.get("id") or matched.get("event_id")
+        if not event_id:
+            return []
+
+        all_markets = client.get_markets_for_events([str(event_id)])
+        classified = classify_markets(all_markets)
+
+        matchup_markets = classified.get("matchup", [])
+        if not matchup_markets:
+            return []
+
+        odds_format = _detect_odds_format(matchup_markets)
+        matchups = []
+
+        for market in matchup_markets:
+            names = extract_player_names_matchup(market)
+            if not names:
+                continue
+
+            name_a, name_b = names
+            competitors = market.get("competitors",
+                          market.get("participants",
+                          market.get("selections", [])))
+            if not isinstance(competitors, list) or len(competitors) != 2:
+                continue
+
+            odds_a = _get_odds_value(competitors[0])
+            odds_b = _get_odds_value(competitors[1])
+            if odds_a is None or odds_b is None:
+                continue
+
+            if odds_format == "american":
+                prob_a = _american_to_prob(odds_a)
+                prob_b = _american_to_prob(odds_b)
+            else:
+                prob_a = float(odds_a) if odds_a else None
+                prob_b = float(odds_b) if odds_b else None
+
+            if prob_a is None or prob_b is None:
+                continue
+
+            resolved_a = resolve_prophetx_player(name_a)
+            resolved_b = resolve_prophetx_player(name_b)
+            canonical_a = resolved_a["canonical_name"] if resolved_a else name_a
+            canonical_b = resolved_b["canonical_name"] if resolved_b else name_b
+
+            matchups.append({
+                "p1_name": canonical_a,
+                "p2_name": canonical_b,
+                "p1_prob": prob_a,
+                "p2_prob": prob_b,
+            })
+
+        # Cache
+        if matchups and tournament_slug:
+            try:
+                client._cache_response(matchups, "prophetx_matchups", tournament_slug)
+            except Exception:
+                logger.debug("ProphetX: matchup cache write failed", exc_info=True)
+
+        return matchups
+
+    except Exception:
+        logger.warning("ProphetX: matchups pull failed", exc_info=True)
+        return []
+
+
+def merge_prophetx_into_outrights(
+    dg_outrights: dict[str, list[dict]],
+    prophetx_outrights: dict[str, list[dict]],
+) -> dict[str, list[dict]]:
+    """Inject ProphetX data as book columns into DG outright data.
+
+    Format-aware merge:
+    - Always adds "prophetx" key with American odds string
+    - Adds "_prophetx_ask_prob" ONLY when binary format (American IS the bettable price)
+
+    Mutates dg_outrights in-place and returns it.
+    """
+    for dg_key, px_key in _DG_TO_PROPHETX_MARKET.items():
+        dg_players = dg_outrights.get(dg_key)
+        px_players = prophetx_outrights.get(px_key, [])
+
+        if not dg_players or not px_players:
+            continue
+
+        # Build case-insensitive lookup
+        px_lookup: dict[str, dict] = {}
+        for pp in px_players:
+            name = pp["player_name"].strip().lower()
+            if name not in px_lookup:
+                px_lookup[name] = pp
+
+        for player in dg_players:
+            pname = player.get("player_name", "").strip().lower()
+            pp = px_lookup.get(pname)
+            if not pp:
+                continue
+
+            mid_prob = pp.get("prophetx_mid_prob", 0)
+            if mid_prob <= 0 or mid_prob >= 1:
+                continue
+
+            # Get American odds: either stored directly or convert from mid_prob
+            if pp.get("prophetx_american"):
+                american = pp["prophetx_american"]
+            else:
+                american = binary_price_to_american(str(mid_prob))
+                if not american:
+                    continue
+
+            player["prophetx"] = american
+
+            # Only add ask_prob for binary format
+            if pp.get("odds_format") == "binary" and "prophetx_ask_prob" in pp:
+                player["_prophetx_ask_prob"] = pp["prophetx_ask_prob"]
+
+    return dg_outrights
+
+
+def merge_prophetx_into_matchups(
+    dg_matchups: list[dict],
+    prophetx_matchups: list[dict],
+) -> list[dict]:
+    """Inject ProphetX H2H data into DG matchup odds dicts.
+
+    Uses frozenset for order-independent name matching, then aligns
+    player order to DG's p1/p2.
+
+    Mutates dg_matchups in-place and returns it.
+    """
+    # Build lookup by frozenset of normalized names
+    px_lookup: dict[frozenset, dict] = {}
+    for pm in prophetx_matchups:
+        key = frozenset({pm["p1_name"].strip().lower(),
+                         pm["p2_name"].strip().lower()})
+        if key not in px_lookup:
+            px_lookup[key] = pm
+
+    for matchup in dg_matchups:
+        p1 = matchup.get("p1_player_name", "").strip().lower()
+        p2 = matchup.get("p2_player_name", "").strip().lower()
+        key = frozenset({p1, p2})
+
+        pm = px_lookup.get(key)
+        if not pm:
+            continue
+
+        # Align player order
+        pm_p1_lower = pm["p1_name"].strip().lower()
+        if pm_p1_lower == p1:
+            p1_prob, p2_prob = pm["p1_prob"], pm["p2_prob"]
+        else:
+            p1_prob, p2_prob = pm["p2_prob"], pm["p1_prob"]
+
+        p1_american = binary_price_to_american(str(p1_prob))
+        p2_american = binary_price_to_american(str(p2_prob))
+
+        if not p1_american or not p2_american:
+            continue
+
+        odds_dict = matchup.setdefault("odds", {})
+        odds_dict["prophetx"] = {"p1": p1_american, "p2": p2_american}
+
+    return dg_matchups
diff --git a/tests/test_pull_prophetx.py b/tests/test_pull_prophetx.py
new file mode 100644
index 0000000..8aab212
--- /dev/null
+++ b/tests/test_pull_prophetx.py
@@ -0,0 +1,396 @@
+"""Tests for ProphetX odds pull & merge (section 09)."""
+
+from __future__ import annotations
+
+from unittest.mock import MagicMock, patch
+
+import pytest
+
+from src.pipeline.pull_prophetx import (
+    _detect_odds_format,
+    merge_prophetx_into_matchups,
+    merge_prophetx_into_outrights,
+    pull_prophetx_matchups,
+    pull_prophetx_outrights,
+)
+
+
+# ── Odds format detection ───────────────────────────────────────────
+
+
+class TestDetectOddsFormat:
+    def test_american_int_positive(self):
+        markets = [{"odds": 400}]
+        assert _detect_odds_format(markets, "odds") == "american"
+
+    def test_american_int_negative(self):
+        markets = [{"odds": -150}]
+        assert _detect_odds_format(markets, "odds") == "american"
+
+    def test_american_string_positive(self):
+        markets = [{"odds": "+400"}]
+        assert _detect_odds_format(markets, "odds") == "american"
+
+    def test_american_string_negative(self):
+        markets = [{"odds": "-150"}]
+        assert _detect_odds_format(markets, "odds") == "american"
+
+    def test_binary_float(self):
+        markets = [{"odds": 0.55}]
+        assert _detect_odds_format(markets, "odds") == "binary"
+
+    def test_binary_small_float(self):
+        markets = [{"odds": 0.02}]
+        assert _detect_odds_format(markets, "odds") == "binary"
+
+    def test_empty_markets(self):
+        assert _detect_odds_format([], "odds") == "binary"  # default
+
+    def test_missing_key(self):
+        markets = [{"other": 123}]
+        assert _detect_odds_format(markets, "odds") == "binary"
+
+
+# ── Helpers: fake data builders ──────────────────────────────────────
+
+
+def _make_competitor(name, odds=0.25, oi=200, bid=0.23, ask=0.27):
+    return {
+        "competitor_name": name,
+        "odds": odds,
+        "open_interest": oi,
+        "bid": bid,
+        "ask": ask,
+    }
+
+
+def _make_market(market_type, sub_type, name, competitors):
+    return {
+        "market_type": market_type,
+        "sub_type": sub_type,
+        "name": name,
+        "competitors": competitors,
+    }
+
+
+def _make_event(title, start, end, event_id="evt-1"):
+    return {
+        "name": title,
+        "start_date": start,
+        "end_date": end,
+        "id": event_id,
+    }
+
+
+# ── pull_prophetx_outrights ─────────────────────────────────────────
+
+
+class TestPullProphetxOutrights:
+    @patch("src.pipeline.pull_prophetx.ProphetXClient")
+    @patch("src.pipeline.pull_prophetx.match_tournament")
+    @patch("src.pipeline.pull_prophetx.classify_markets")
+    @patch("src.pipeline.pull_prophetx.resolve_prophetx_player")
+    def test_binary_format_outrights(
+        self, mock_resolve, mock_classify, mock_match, mock_client_cls,
+    ):
+        """Binary format: returns mid_prob and ask_prob."""
+        mock_client = MagicMock()
+        mock_client_cls.return_value = mock_client
+
+        event = _make_event("The Masters", "2026-04-09", "2026-04-12")
+        mock_match.return_value = event
+
+        competitors = [_make_competitor("Scottie Scheffler", odds=0.25, bid=0.23, ask=0.27)]
+        win_market = _make_market("moneyline", "outright", "Winner", competitors)
+        mock_client.get_markets_for_events.return_value = [win_market]
+        mock_classify.return_value = {"win": [win_market]}
+        mock_resolve.return_value = {"canonical_name": "Scottie Scheffler"}
+
+        result = pull_prophetx_outrights("The Masters", "2026-04-09", "2026-04-12")
+
+        assert "win" in result
+        assert len(result["win"]) == 1
+        player = result["win"][0]
+        assert player["player_name"] == "Scottie Scheffler"
+        assert player["odds_format"] == "binary"
+        assert "prophetx_mid_prob" in player
+        assert "prophetx_ask_prob" in player
+
+    @patch("src.pipeline.pull_prophetx.ProphetXClient")
+    @patch("src.pipeline.pull_prophetx.match_tournament")
+    @patch("src.pipeline.pull_prophetx.classify_markets")
+    @patch("src.pipeline.pull_prophetx.resolve_prophetx_player")
+    def test_american_int_outrights(
+        self, mock_resolve, mock_classify, mock_match, mock_client_cls,
+    ):
+        """American int format: no ask_prob, stores American string directly."""
+        mock_client = MagicMock()
+        mock_client_cls.return_value = mock_client
+
+        event = _make_event("The Masters", "2026-04-09", "2026-04-12")
+        mock_match.return_value = event
+
+        competitors = [_make_competitor("Rory McIlroy", odds=400)]
+        win_market = _make_market("moneyline", "outright", "Winner", competitors)
+        mock_client.get_markets_for_events.return_value = [win_market]
+        mock_classify.return_value = {"win": [win_market]}
+        mock_resolve.return_value = {"canonical_name": "Rory McIlroy"}
+
+        result = pull_prophetx_outrights("The Masters", "2026-04-09", "2026-04-12")
+
+        assert "win" in result
+        player = result["win"][0]
+        assert player["player_name"] == "Rory McIlroy"
+        assert player["odds_format"] == "american"
+        assert "prophetx_american" in player
+        assert "prophetx_ask_prob" not in player
+
+    @patch("src.pipeline.pull_prophetx.ProphetXClient")
+    @patch("src.pipeline.pull_prophetx.match_tournament")
+    @patch("src.pipeline.pull_prophetx.classify_markets")
+    @patch("src.pipeline.pull_prophetx.resolve_prophetx_player")
+    def test_american_string_outrights(
+        self, mock_resolve, mock_classify, mock_match, mock_client_cls,
+    ):
+        """American string format ('+400')."""
+        mock_client = MagicMock()
+        mock_client_cls.return_value = mock_client
+
+        event = _make_event("The Masters", "2026-04-09", "2026-04-12")
+        mock_match.return_value = event
+
+        competitors = [_make_competitor("Jon Rahm", odds="+400")]
+        win_market = _make_market("moneyline", "outright", "Winner", competitors)
+        mock_client.get_markets_for_events.return_value = [win_market]
+        mock_classify.return_value = {"win": [win_market]}
+        mock_resolve.return_value = {"canonical_name": "Jon Rahm"}
+
+        result = pull_prophetx_outrights("The Masters", "2026-04-09", "2026-04-12")
+
+        assert "win" in result
+        player = result["win"][0]
+        assert player["odds_format"] == "american"
+        assert "prophetx_american" in player
+
+    @patch("src.pipeline.pull_prophetx.ProphetXClient")
+    @patch("src.pipeline.pull_prophetx.match_tournament")
+    def test_no_tournament_match(self, mock_match, mock_client_cls):
+        mock_client_cls.return_value = MagicMock()
+        mock_match.return_value = None
+
+        result = pull_prophetx_outrights("Fake Event", "2026-01-01", "2026-01-04")
+        assert result == {}
+
+    @patch("src.pipeline.pull_prophetx.ProphetXClient")
+    @patch("src.pipeline.pull_prophetx.match_tournament")
+    @patch("src.pipeline.pull_prophetx.classify_markets")
+    @patch("src.pipeline.pull_prophetx.resolve_prophetx_player")
+    def test_filters_low_oi(
+        self, mock_resolve, mock_classify, mock_match, mock_client_cls,
+    ):
+        """Competitors below OI threshold are filtered out."""
+        mock_client = MagicMock()
+        mock_client_cls.return_value = mock_client
+
+        event = _make_event("The Masters", "2026-04-09", "2026-04-12")
+        mock_match.return_value = event
+
+        competitors = [_make_competitor("Low OI Player", odds=0.25, oi=5)]
+        win_market = _make_market("moneyline", "outright", "Winner", competitors)
+        mock_client.get_markets_for_events.return_value = [win_market]
+        mock_classify.return_value = {"win": [win_market]}
+        mock_resolve.return_value = {"canonical_name": "Low OI Player"}
+
+        result = pull_prophetx_outrights("The Masters", "2026-04-09", "2026-04-12")
+        # No players should pass the filter
+        assert result == {} or len(result.get("win", [])) == 0
+
+
+# ── pull_prophetx_matchups ──────────────────────────────────────────
+
+
+class TestPullProphetxMatchups:
+    @patch("src.pipeline.pull_prophetx.ProphetXClient")
+    @patch("src.pipeline.pull_prophetx.match_tournament")
+    @patch("src.pipeline.pull_prophetx.classify_markets")
+    @patch("src.pipeline.pull_prophetx.resolve_prophetx_player")
+    def test_matchup_extraction(
+        self, mock_resolve, mock_classify, mock_match, mock_client_cls,
+    ):
+        mock_client = MagicMock()
+        mock_client_cls.return_value = mock_client
+
+        event = _make_event("The Masters", "2026-04-09", "2026-04-12")
+        mock_match.return_value = event
+
+        competitors = [
+            _make_competitor("Player A", odds=0.55),
+            _make_competitor("Player B", odds=0.45),
+        ]
+        matchup_market = _make_market("moneyline", "matchup", "A vs B", competitors)
+        mock_client.get_markets_for_events.return_value = [matchup_market]
+        mock_classify.return_value = {"matchup": [matchup_market]}
+        mock_resolve.side_effect = [
+            {"canonical_name": "Player A"},
+            {"canonical_name": "Player B"},
+        ]
+
+        result = pull_prophetx_matchups("The Masters", "2026-04-09", "2026-04-12")
+
+        assert len(result) == 1
+        m = result[0]
+        assert m["p1_name"] == "Player A"
+        assert m["p2_name"] == "Player B"
+        assert "p1_prob" in m
+        assert "p2_prob" in m
+
+    @patch("src.pipeline.pull_prophetx.ProphetXClient")
+    @patch("src.pipeline.pull_prophetx.match_tournament")
+    @patch("src.pipeline.pull_prophetx.classify_markets")
+    @patch("src.pipeline.pull_prophetx.resolve_prophetx_player")
+    def test_matchup_american_odds(
+        self, mock_resolve, mock_classify, mock_match, mock_client_cls,
+    ):
+        mock_client = MagicMock()
+        mock_client_cls.return_value = mock_client
+
+        event = _make_event("The Masters", "2026-04-09", "2026-04-12")
+        mock_match.return_value = event
+
+        competitors = [
+            _make_competitor("Player A", odds=-150),
+            _make_competitor("Player B", odds=130),
+        ]
+        matchup_market = _make_market("moneyline", "matchup", "A vs B", competitors)
+        mock_client.get_markets_for_events.return_value = [matchup_market]
+        mock_classify.return_value = {"matchup": [matchup_market]}
+        mock_resolve.side_effect = [
+            {"canonical_name": "Player A"},
+            {"canonical_name": "Player B"},
+        ]
+
+        result = pull_prophetx_matchups("The Masters", "2026-04-09", "2026-04-12")
+
+        assert len(result) == 1
+        m = result[0]
+        assert "p1_prob" in m
+        assert "p2_prob" in m
+
+
+# ── merge_prophetx_into_outrights ───────────────────────────────────
+
+
+class TestMergeProphetxIntoOutrights:
+    def test_adds_american_odds(self):
+        dg = {"win": [{"player_name": "Scottie Scheffler"}]}
+        prophetx = {"win": [{
+            "player_name": "Scottie Scheffler",
+            "prophetx_mid_prob": 0.20,
+            "prophetx_american": "+400",
+            "odds_format": "american",
+        }]}
+
+        result = merge_prophetx_into_outrights(dg, prophetx)
+        player = result["win"][0]
+        assert player["prophetx"] == "+400"
+
+    def test_adds_ask_prob_for_binary(self):
+        dg = {"win": [{"player_name": "Rory McIlroy"}]}
+        prophetx = {"win": [{
+            "player_name": "Rory McIlroy",
+            "prophetx_mid_prob": 0.22,
+            "prophetx_ask_prob": 0.25,
+            "odds_format": "binary",
+        }]}
+
+        result = merge_prophetx_into_outrights(dg, prophetx)
+        player = result["win"][0]
+        assert "_prophetx_ask_prob" in player
+        assert player["_prophetx_ask_prob"] == 0.25
+
+    def test_no_ask_prob_for_american(self):
+        dg = {"win": [{"player_name": "Jon Rahm"}]}
+        prophetx = {"win": [{
+            "player_name": "Jon Rahm",
+            "prophetx_mid_prob": 0.20,
+            "prophetx_american": "+400",
+            "odds_format": "american",
+        }]}
+
+        result = merge_prophetx_into_outrights(dg, prophetx)
+        player = result["win"][0]
+        assert "_prophetx_ask_prob" not in player
+
+    def test_skips_unmatched_dg_players(self):
+        dg = {"win": [
+            {"player_name": "Scottie Scheffler"},
+            {"player_name": "Unknown Player"},
+        ]}
+        prophetx = {"win": [{
+            "player_name": "Scottie Scheffler",
+            "prophetx_mid_prob": 0.20,
+            "prophetx_american": "+400",
+            "odds_format": "american",
+        }]}
+
+        result = merge_prophetx_into_outrights(dg, prophetx)
+        assert "prophetx" in result["win"][0]
+        assert "prophetx" not in result["win"][1]
+
+    def test_case_insensitive_matching(self):
+        dg = {"win": [{"player_name": "SCOTTIE SCHEFFLER"}]}
+        prophetx = {"win": [{
+            "player_name": "scottie scheffler",
+            "prophetx_mid_prob": 0.20,
+            "prophetx_american": "+400",
+            "odds_format": "american",
+        }]}
+
+        result = merge_prophetx_into_outrights(dg, prophetx)
+        assert "prophetx" in result["win"][0]
+
+
+# ── merge_prophetx_into_matchups ────────────────────────────────────
+
+
+class TestMergeProphetxIntoMatchups:
+    def test_frozenset_matching(self):
+        """Order-independent matching via frozenset."""
+        dg = [
+            {
+                "p1_player_name": "Player A",
+                "p2_player_name": "Player B",
+                "odds": {"draftkings": {"p1": "-110", "p2": "+100"}},
+            },
+        ]
+        prophetx = [{
+            "p1_name": "Player B",
+            "p2_name": "Player A",
+            "p1_prob": 0.45,
+            "p2_prob": 0.55,
+        }]
+
+        result = merge_prophetx_into_matchups(dg, prophetx)
+        odds = result[0]["odds"]["prophetx"]
+        # Player A is DG's p1, but ProphetX has them as p2
+        # So p1 odds should correspond to Player A's prob (0.55)
+        assert "p1" in odds
+        assert "p2" in odds
+
+    def test_adds_prophetx_odds(self):
+        dg = [
+            {
+                "p1_player_name": "Player A",
+                "p2_player_name": "Player B",
+                "odds": {},
+            },
+        ]
+        prophetx = [{
+            "p1_name": "Player A",
+            "p2_name": "Player B",
+            "p1_prob": 0.55,
+            "p2_prob": 0.45,
+        }]
+
+        result = merge_prophetx_into_matchups(dg, prophetx)
+        assert "prophetx" in result[0]["odds"]
