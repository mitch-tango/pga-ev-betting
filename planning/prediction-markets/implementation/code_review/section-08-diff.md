diff --git a/planning/prediction-markets/implementation/deep_implement_config.json b/planning/prediction-markets/implementation/deep_implement_config.json
index de158ff..a347be5 100644
--- a/planning/prediction-markets/implementation/deep_implement_config.json
+++ b/planning/prediction-markets/implementation/deep_implement_config.json
@@ -43,6 +43,10 @@
     "section-06-polymarket-pull": {
       "status": "complete",
       "commit_hash": "413fd23"
+    },
+    "section-07-prophetx-client": {
+      "status": "complete",
+      "commit_hash": "ad5030f"
     }
   },
   "pre_commit": {
diff --git a/src/pipeline/prophetx_matching.py b/src/pipeline/prophetx_matching.py
new file mode 100644
index 0000000..1e44dd9
--- /dev/null
+++ b/src/pipeline/prophetx_matching.py
@@ -0,0 +1,232 @@
+"""ProphetX tournament matching, market classification, and player extraction.
+
+Matches ProphetX prediction market events to DataGolf tournaments,
+classifies markets by type, and extracts player names from ProphetX
+market data. Handles ProphetX's uncertain field names with flexible
+field detection.
+"""
+
+from __future__ import annotations
+
+import logging
+import re
+import unicodedata
+from datetime import date, datetime
+from difflib import SequenceMatcher
+
+from src.normalize.players import resolve_player
+
+logger = logging.getLogger(__name__)
+
+# Explicit exclusions for non-PGA tours
+_NON_PGA_EXCLUSIONS = ["liv", "dpwt", "dp world", "lpga", "korn ferry"]
+
+# Strip common prefixes/suffixes before fuzzy comparison
+_TITLE_PREFIX_PATTERN = re.compile(r"^pga\s+tour:\s*", re.IGNORECASE)
+_TITLE_SUFFIX_PATTERN = re.compile(r"\s+(?:winner|top\s+\d+)\s*$", re.IGNORECASE)
+
+# Player name field candidates (ordered by likelihood)
+_NAME_FIELDS = ("competitor_name", "participant", "player", "name", "playerName")
+
+# Competitors list field candidates
+_COMPETITORS_FIELDS = ("competitors", "participants", "selections")
+
+# Date field candidates for start
+_START_DATE_FIELDS = ("start_date", "startDate", "event_date", "start")
+# Date field candidates for end
+_END_DATE_FIELDS = ("end_date", "endDate", "event_end_date", "end")
+# Title field candidates
+_TITLE_FIELDS = ("name", "title", "event_name", "eventName")
+
+
+def _get_field(d: dict, *field_names: str, default=None):
+    """Try each field name, return first non-None value."""
+    for name in field_names:
+        val = d.get(name)
+        if val is not None:
+            return val
+    return default
+
+
+def _parse_date(date_str: str) -> date:
+    """Parse a date string into a date object."""
+    if "T" in date_str:
+        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
+    return date.fromisoformat(date_str)
+
+
+def _is_pga_event(title: str) -> bool:
+    """Check if event is acceptable (not from an excluded tour)."""
+    title_lower = title.lower()
+    return not any(exclusion in title_lower for exclusion in _NON_PGA_EXCLUSIONS)
+
+
+def _clean_name(name: str) -> str:
+    """Clean and NFC-normalize a player name."""
+    name = name.strip().rstrip("?").strip()
+    name = unicodedata.normalize("NFC", name)
+    return name
+
+
+def _extract_name_from_entry(entry: dict) -> str | None:
+    """Extract player name from a competitor/participant dict."""
+    name = _get_field(entry, *_NAME_FIELDS)
+    if name and isinstance(name, str):
+        return _clean_name(name)
+    return None
+
+
+def match_tournament(
+    events: list[dict],
+    tournament_name: str,
+    tournament_start: str,
+    tournament_end: str,
+) -> dict | None:
+    """Find the ProphetX event matching the current DG tournament.
+
+    Handles multiple field name variants for dates and titles.
+    Uses date range overlap + fuzzy name matching.
+
+    Returns full event dict, or None if no match.
+    """
+    start_date = _parse_date(tournament_start)
+    end_date = _parse_date(tournament_end)
+    tourney_lower = tournament_name.lower().strip()
+
+    def _name_score(event: dict) -> float:
+        title = _get_field(event, *_TITLE_FIELDS, default="")
+        title_lower = title.lower()
+        if tourney_lower in title_lower:
+            return 1.0
+        cleaned = _TITLE_PREFIX_PATTERN.sub("", title_lower)
+        cleaned = _TITLE_SUFFIX_PATTERN.sub("", cleaned).strip()
+        return SequenceMatcher(None, tourney_lower, cleaned).ratio()
+
+    # Pass 1: date range overlap — prefer best name match
+    date_candidates = []
+    for event in events:
+        title = _get_field(event, *_TITLE_FIELDS, default="")
+        if not _is_pga_event(title):
+            continue
+
+        event_start_str = _get_field(event, *_START_DATE_FIELDS)
+        event_end_str = _get_field(event, *_END_DATE_FIELDS)
+        if not event_start_str or not event_end_str:
+            continue
+
+        try:
+            event_start = _parse_date(str(event_start_str))
+            event_end = _parse_date(str(event_end_str))
+        except (ValueError, TypeError):
+            continue
+
+        if event_start <= end_date and event_end >= start_date:
+            score = _name_score(event)
+            date_candidates.append((score, event))
+
+    if date_candidates:
+        date_candidates.sort(key=lambda x: x[0], reverse=True)
+        return date_candidates[0][1]
+
+    # Pass 2: fuzzy name fallback
+    best_match = None
+    best_score = 0.0
+
+    for event in events:
+        title = _get_field(event, *_TITLE_FIELDS, default="")
+        if not _is_pga_event(title):
+            continue
+
+        score = _name_score(event)
+        if score > best_score:
+            best_score = score
+            best_match = event
+
+    if best_match and best_score >= 0.85:
+        return best_match
+
+    return None
+
+
+def classify_markets(markets: list[dict]) -> dict[str, list[dict]]:
+    """Classify ProphetX markets by type.
+
+    Returns sparse dict: {"win": [...], "matchup": [...], "t10": [...], etc.}
+    """
+    result: dict[str, list[dict]] = {}
+
+    for market in markets:
+        market_type = str(market.get("market_type", "")).lower()
+        sub_type = str(market.get("sub_type", "")).lower()
+        name = str(market.get("name", "")).lower()
+        competitors = _get_field(market, *_COMPETITORS_FIELDS, default=[])
+        num_competitors = len(competitors) if isinstance(competitors, list) else 0
+
+        classified = None
+
+        # Check for top 10/20 first (more specific)
+        if "top 10" in name or "top-10" in name or "top 10" in sub_type or "top-10" in sub_type:
+            classified = "t10"
+        elif "top 20" in name or "top-20" in name or "top 20" in sub_type or "top-20" in sub_type:
+            classified = "t20"
+        elif "cut" in name:
+            classified = "make_cut"
+        elif market_type == "moneyline" and "outright" in sub_type:
+            classified = "win"
+        elif market_type == "moneyline" and num_competitors == 2:
+            classified = "matchup"
+        elif "matchup" in sub_type and num_competitors == 2:
+            classified = "matchup"
+
+        if classified:
+            result.setdefault(classified, []).append(market)
+        else:
+            logger.debug("ProphetX: unrecognized market type=%s sub=%s name='%s'",
+                         market_type, sub_type, name)
+
+    return result
+
+
+def extract_player_name_outright(market: dict) -> str | None:
+    """Extract player name from an outright market.
+
+    Tries competitor data first, then direct fields on the market.
+    """
+    competitors = _get_field(market, *_COMPETITORS_FIELDS, default=[])
+    if isinstance(competitors, list) and competitors:
+        name = _extract_name_from_entry(competitors[0])
+        if name:
+            return name
+
+    logger.warning("ProphetX: could not extract player name from market: %s", market)
+    return None
+
+
+def extract_player_names_matchup(market: dict) -> tuple[str, str] | None:
+    """Extract both player names from a H2H matchup market.
+
+    Requires exactly 2 competitors. Returns (player_a, player_b) or None.
+    """
+    competitors = _get_field(market, *_COMPETITORS_FIELDS, default=[])
+    if not isinstance(competitors, list) or len(competitors) != 2:
+        return None
+
+    name_a = _extract_name_from_entry(competitors[0])
+    name_b = _extract_name_from_entry(competitors[1])
+
+    if name_a and name_b:
+        return (name_a, name_b)
+
+    logger.warning("ProphetX: could not extract matchup names from: %s", market)
+    return None
+
+
+def resolve_prophetx_player(
+    name: str,
+    auto_create: bool = False,
+) -> dict | None:
+    """Resolve a ProphetX player name to a canonical DG player record.
+
+    Delegates to resolve_player() with source="prophetx".
+    """
+    return resolve_player(name, source="prophetx", auto_create=auto_create)
diff --git a/tests/test_prophetx_matching.py b/tests/test_prophetx_matching.py
new file mode 100644
index 0000000..5665cc8
--- /dev/null
+++ b/tests/test_prophetx_matching.py
@@ -0,0 +1,206 @@
+"""Tests for ProphetX tournament matching, market classification, and player extraction."""
+
+from __future__ import annotations
+
+import unicodedata
+from unittest.mock import patch
+
+import pytest
+
+from src.pipeline.prophetx_matching import (
+    classify_markets,
+    extract_player_name_outright,
+    extract_player_names_matchup,
+    match_tournament,
+    resolve_prophetx_player,
+)
+
+
+# ── Helpers ─────────────────────────────────────────────────────────
+
+def _make_event(
+    name: str = "PGA Tour: The Masters",
+    start_date: str = "2026-04-09T00:00:00Z",
+    end_date: str = "2026-04-13T00:00:00Z",
+    event_id: str = "evt_123",
+) -> dict:
+    return {
+        "name": name,
+        "start_date": start_date,
+        "end_date": end_date,
+        "id": event_id,
+    }
+
+
+def _make_market(
+    market_type: str = "moneyline",
+    sub_type: str = "outrights",
+    name: str = "Masters Winner",
+    competitors: list | None = None,
+) -> dict:
+    return {
+        "market_type": market_type,
+        "sub_type": sub_type,
+        "name": name,
+        "competitors": competitors or [{"competitor_name": "Scottie Scheffler"}],
+    }
+
+
+# ── TestTournamentMatching ──────────────────────────────────────────
+
+class TestTournamentMatching:
+
+    def test_matches_by_date_range_overlap(self):
+        event = _make_event(start_date="2026-04-09T00:00:00Z", end_date="2026-04-13T00:00:00Z")
+        result = match_tournament([event], "The Masters", "2026-04-09", "2026-04-13")
+        assert result is not None
+        assert result["id"] == "evt_123"
+
+    def test_rejects_outside_date_range(self):
+        event = _make_event(
+            name="PGA Tour: Players Championship",
+            start_date="2026-03-10T00:00:00Z",
+            end_date="2026-03-14T00:00:00Z",
+        )
+        result = match_tournament([event], "The Masters", "2026-04-09", "2026-04-13")
+        assert result is None
+
+    def test_fuzzy_name_match(self):
+        event = _make_event(
+            name="PGA Tour: The Masters Tournament",
+            start_date="2026-04-08T00:00:00Z",
+            end_date="2026-04-08T00:00:00Z",  # No date overlap
+        )
+        result = match_tournament([event], "The Masters", "2026-04-09", "2026-04-13")
+        assert result is not None
+
+    def test_tries_multiple_date_fields(self):
+        """ProphetX may use startDate instead of start_date."""
+        event = {
+            "name": "PGA Tour: The Masters",
+            "startDate": "2026-04-09T00:00:00Z",
+            "endDate": "2026-04-13T00:00:00Z",
+            "id": "evt_alt",
+        }
+        result = match_tournament([event], "The Masters", "2026-04-09", "2026-04-13")
+        assert result is not None
+
+    def test_tries_multiple_title_fields(self):
+        """ProphetX may use 'title' instead of 'name'."""
+        event = {
+            "title": "PGA Tour: The Masters",
+            "start_date": "2026-04-09T00:00:00Z",
+            "end_date": "2026-04-13T00:00:00Z",
+            "id": "evt_title",
+        }
+        result = match_tournament([event], "The Masters", "2026-04-09", "2026-04-13")
+        assert result is not None
+
+    def test_excludes_non_pga_tours(self):
+        non_pga = [
+            _make_event(name="LIV Golf Portland"),
+            _make_event(name="DPWT BMW Championship"),
+            _make_event(name="LPGA Chevron Championship"),
+            _make_event(name="Korn Ferry Tour Boise Open"),
+        ]
+        for event in non_pga:
+            result = match_tournament([event], "The Masters", "2026-04-09", "2026-04-13")
+            assert result is None, f"Should exclude: {event['name']}"
+
+
+# ── TestClassifyMarkets ─────────────────────────────────────────────
+
+class TestClassifyMarkets:
+
+    def test_identifies_outright_winner(self):
+        market = _make_market(market_type="moneyline", sub_type="outrights", name="Masters Winner")
+        result = classify_markets([market])
+        assert "win" in result
+        assert len(result["win"]) == 1
+
+    def test_identifies_h2h_matchup(self):
+        market = _make_market(
+            market_type="moneyline",
+            sub_type="matchup",
+            name="Scheffler vs McIlroy",
+            competitors=[
+                {"competitor_name": "Scottie Scheffler"},
+                {"competitor_name": "Rory McIlroy"},
+            ],
+        )
+        result = classify_markets([market])
+        assert "matchup" in result
+
+    def test_identifies_make_cut(self):
+        market = _make_market(name="Will Scottie Scheffler make the cut?", market_type="prop", sub_type="")
+        result = classify_markets([market])
+        assert "make_cut" in result
+
+    def test_discovers_t10_t20(self):
+        t10 = _make_market(name="Masters Top 10", market_type="moneyline", sub_type="top 10")
+        t20 = _make_market(name="Masters Top 20", market_type="moneyline", sub_type="top 20")
+        result = classify_markets([t10, t20])
+        assert "t10" in result
+        assert "t20" in result
+
+    def test_returns_sparse_dict(self):
+        """Only found types should be in result."""
+        market = _make_market(market_type="moneyline", sub_type="outrights")
+        result = classify_markets([market])
+        assert "win" in result
+        assert "matchup" not in result
+        assert "make_cut" not in result
+
+
+# ── TestPlayerNameExtraction ────────────────────────────────────────
+
+class TestPlayerNameExtraction:
+
+    def test_extracts_from_competitor_name(self):
+        market = _make_market(competitors=[{"competitor_name": "Scottie Scheffler"}])
+        name = extract_player_name_outright(market)
+        assert name == "Scottie Scheffler"
+
+    def test_tries_multiple_field_names(self):
+        """Should find name in 'participant' or 'player' fields."""
+        market = _make_market(competitors=[{"participant": "Rory McIlroy"}])
+        name = extract_player_name_outright(market)
+        assert name == "Rory McIlroy"
+
+    def test_returns_none_when_no_name(self):
+        market = _make_market(competitors=[{"unknown_field": "???"}])
+        name = extract_player_name_outright(market)
+        assert name is None
+
+    def test_extracts_both_matchup_names(self):
+        market = _make_market(competitors=[
+            {"competitor_name": "Scottie Scheffler"},
+            {"competitor_name": "Rory McIlroy"},
+        ])
+        result = extract_player_names_matchup(market)
+        assert result == ("Scottie Scheffler", "Rory McIlroy")
+
+    def test_nfc_normalized(self):
+        market = _make_market(competitors=[{"competitor_name": "Ludvig A\u030aberg"}])
+        name = extract_player_name_outright(market)
+        assert name is not None
+        assert name == unicodedata.normalize("NFC", name)
+
+    def test_matchup_requires_two_competitors(self):
+        market = _make_market(competitors=[{"competitor_name": "Scottie Scheffler"}])
+        result = extract_player_names_matchup(market)
+        assert result is None
+
+
+# ── TestPlayerNameResolution ────────────────────────────────────────
+
+class TestPlayerNameResolution:
+
+    @patch("src.pipeline.prophetx_matching.resolve_player")
+    def test_delegates_to_resolve_player(self, mock_resolve):
+        mock_resolve.return_value = {"id": 1, "canonical_name": "Scottie Scheffler"}
+        result = resolve_prophetx_player("Scottie Scheffler", auto_create=True)
+        mock_resolve.assert_called_once_with(
+            "Scottie Scheffler", source="prophetx", auto_create=True,
+        )
+        assert result["canonical_name"] == "Scottie Scheffler"
