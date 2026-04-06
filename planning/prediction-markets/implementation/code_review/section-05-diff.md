diff --git a/planning/prediction-markets/implementation/deep_implement_config.json b/planning/prediction-markets/implementation/deep_implement_config.json
index 309550b..0685ce0 100644
--- a/planning/prediction-markets/implementation/deep_implement_config.json
+++ b/planning/prediction-markets/implementation/deep_implement_config.json
@@ -31,6 +31,10 @@
     "section-03-edge-updates": {
       "status": "complete",
       "commit_hash": "e31f2b1"
+    },
+    "section-04-polymarket-client": {
+      "status": "complete",
+      "commit_hash": "113bdbe"
     }
   },
   "pre_commit": {
diff --git a/src/pipeline/polymarket_matching.py b/src/pipeline/polymarket_matching.py
new file mode 100644
index 0000000..7d1b78a
--- /dev/null
+++ b/src/pipeline/polymarket_matching.py
@@ -0,0 +1,226 @@
+"""Polymarket tournament matching and player name extraction.
+
+Matches Polymarket prediction market events to DataGolf tournaments by
+UTC date range overlap and fuzzy name, and extracts/resolves player names
+from Polymarket market data (slug-based and regex-based).
+
+Follows the same architectural pattern as kalshi_matching.py but adapts
+for Polymarket-specific data structures.
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
+import config
+from src.normalize.players import resolve_player
+
+logger = logging.getLogger(__name__)
+
+# PGA safety check — event title must contain one of these
+_PGA_INDICATORS = [
+    "pga", "masters", "u.s. open", "us open", "open championship",
+    "pga championship",
+]
+
+# Explicit exclusions for non-PGA tours
+_NON_PGA_EXCLUSIONS = ["liv", "dpwt", "lpga", "korn ferry"]
+
+# Strip common prefixes/suffixes before fuzzy comparison
+_TITLE_STRIP_PATTERNS = re.compile(
+    r"^(?:pga\s+tour:\s*)|(?:\s+winner\s*$)|(?:\s+top\s+\d+\s*$)",
+    re.IGNORECASE,
+)
+
+# Question-based player extraction patterns
+_QUESTION_PATTERNS = [
+    re.compile(r"^Will\s+(.+?)\s+(?:win|finish)\b", re.IGNORECASE),
+    re.compile(r"^(.+?)\s+to\s+(?:win|finish)\b", re.IGNORECASE),
+]
+
+
+def _parse_date(date_str: str) -> date:
+    """Parse a date string into a date object.
+
+    Handles both "2026-04-10T00:00:00Z" and "2026-04-10" formats.
+    """
+    if "T" in date_str:
+        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
+    return date.fromisoformat(date_str)
+
+
+def _is_pga_event(title: str) -> bool:
+    """Check if event title indicates a PGA Tour event.
+
+    Returns False for non-PGA tours (LIV, DPWT, LPGA, Korn Ferry).
+    """
+    title_lower = title.lower()
+
+    # Reject non-PGA tours first
+    for exclusion in _NON_PGA_EXCLUSIONS:
+        if exclusion in title_lower:
+            return False
+
+    return any(indicator in title_lower for indicator in _PGA_INDICATORS)
+
+
+def _clean_name(name: str) -> str:
+    """Clean and NFC-normalize a player name."""
+    name = name.strip().rstrip("?").strip()
+    name = unicodedata.normalize("NFC", name)
+    return name
+
+
+def match_tournament(
+    events: list[dict],
+    tournament_name: str,
+    tournament_start: str,
+    tournament_end: str,
+) -> dict | None:
+    """Find the Polymarket event matching the current DG tournament.
+
+    Matching strategy:
+    1. Date-based: UTC date range overlap (event_start <= tourn_end AND event_end >= tourn_start)
+    2. Fuzzy name fallback: token-based similarity ≥ 0.85
+    3. Safety check: reject non-PGA events
+
+    Returns full event dict (with nested markets[]), or None if no match.
+    """
+    start_date = _parse_date(tournament_start)
+    end_date = _parse_date(tournament_end)
+
+    tourney_lower = tournament_name.lower().strip()
+
+    # Pass 1: date range overlap
+    for event in events:
+        if not _is_pga_event(event.get("title", "")):
+            continue
+
+        event_start_str = event.get("startDate", "")
+        event_end_str = event.get("endDate", "")
+        if not event_start_str or not event_end_str:
+            continue
+
+        try:
+            event_start = _parse_date(event_start_str)
+            event_end = _parse_date(event_end_str)
+        except (ValueError, TypeError):
+            continue
+
+        # Two ranges overlap when start_a <= end_b AND end_a >= start_b
+        if event_start <= end_date and event_end >= start_date:
+            return event
+
+    # Pass 2: fuzzy name fallback (only PGA events)
+    best_match = None
+    best_score = 0.0
+
+    for event in events:
+        if not _is_pga_event(event.get("title", "")):
+            continue
+
+        title_lower = event.get("title", "").lower()
+
+        # Substring check
+        if tourney_lower in title_lower:
+            return event
+
+        # Strip common prefixes/suffixes before fuzzy comparison
+        cleaned_title = _TITLE_STRIP_PATTERNS.sub("", title_lower).strip()
+        score = SequenceMatcher(None, tourney_lower, cleaned_title).ratio()
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
+def match_all_market_types(
+    client,
+    tournament_name: str,
+    tournament_start: str,
+    tournament_end: str,
+) -> dict[str, dict]:
+    """Match all Polymarket market types to the current tournament.
+
+    Iterates config.POLYMARKET_MARKET_TYPES. For each type, fetches events
+    and attempts tournament matching.
+
+    Returns {"win": event_dict, "t10": event_dict, ...} with only matched entries.
+    """
+    matched = {}
+    for market_type, filter_value in config.POLYMARKET_MARKET_TYPES.items():
+        try:
+            events = client.get_golf_events(market_type_filter=filter_value)
+        except Exception:
+            logger.warning("Failed to fetch Polymarket events for %s", market_type)
+            continue
+
+        event = match_tournament(events, tournament_name, tournament_start, tournament_end)
+        if event:
+            matched[market_type] = event
+        else:
+            logger.info("No Polymarket match for %s (%s)", market_type, filter_value)
+
+    return matched
+
+
+def extract_player_name(market: dict, event_slug: str = "") -> str | None:
+    """Extract player name from a Polymarket market dict.
+
+    Priority order:
+    1. groupItemTitle (most reliable when present)
+    2. Slug-based: strip event prefix from market slug, convert hyphens to spaces
+    3. Question regex: "Will X win..." patterns
+
+    Returns cleaned, NFC-normalized name or None.
+    """
+    # 1. groupItemTitle — often just the player name
+    group_title = market.get("groupItemTitle", "").strip()
+    if group_title and not any(
+        kw in group_title.lower() for kw in ["win", "finish", "top", "yes", "no"]
+    ):
+        return _clean_name(group_title)
+
+    # 2. Slug-based extraction
+    market_slug = market.get("slug", "")
+    if market_slug and event_slug:
+        # Strip the event slug prefix
+        if market_slug.startswith(event_slug):
+            player_part = market_slug[len(event_slug):].lstrip("-")
+        else:
+            # Try removing common event prefix patterns
+            player_part = market_slug
+        if player_part:
+            name = player_part.replace("-", " ").strip()
+            if name and len(name) > 1:
+                name = name.title()
+                return _clean_name(name)
+
+    # 3. Question regex
+    question = market.get("question", "")
+    for pattern in _QUESTION_PATTERNS:
+        m = pattern.match(question)
+        if m:
+            return _clean_name(m.group(1))
+
+    logger.warning("Could not extract player name from Polymarket market: %s", market.get("slug", ""))
+    return None
+
+
+def resolve_polymarket_player(
+    name: str,
+    auto_create: bool = False,
+) -> dict | None:
+    """Resolve a Polymarket player name to a canonical DG player record.
+
+    Delegates to resolve_player() with source="polymarket".
+    """
+    return resolve_player(name, source="polymarket", auto_create=auto_create)
diff --git a/tests/test_polymarket_matching.py b/tests/test_polymarket_matching.py
new file mode 100644
index 0000000..0ef6f44
--- /dev/null
+++ b/tests/test_polymarket_matching.py
@@ -0,0 +1,258 @@
+"""Tests for Polymarket tournament matching and player name extraction."""
+
+from __future__ import annotations
+
+from unittest.mock import MagicMock, patch
+
+import pytest
+
+from src.pipeline.polymarket_matching import (
+    extract_player_name,
+    match_all_market_types,
+    match_tournament,
+    resolve_polymarket_player,
+)
+
+
+# ── Fixtures / helpers ──────────────────────────────────────────────
+
+def _make_event(
+    title: str = "PGA Tour: The Masters Winner",
+    start_date: str = "2026-04-09T00:00:00Z",
+    end_date: str = "2026-04-13T00:00:00Z",
+    slug: str = "pga-tour-the-masters-winner",
+    markets: list | None = None,
+) -> dict:
+    return {
+        "title": title,
+        "startDate": start_date,
+        "endDate": end_date,
+        "slug": slug,
+        "markets": markets or [],
+    }
+
+
+def _make_market(
+    slug: str = "pga-tour-the-masters-winner-scottie-scheffler",
+    question: str = "Will Scottie Scheffler win the Masters?",
+    outcome: str = "Yes",
+    tokens: list | None = None,
+) -> dict:
+    return {
+        "slug": slug,
+        "question": question,
+        "outcome": outcome,
+        "groupItemTitle": "Scottie Scheffler",
+        "tokens": tokens or [{"token_id": "0x123", "outcome": "Yes"}],
+    }
+
+
+# ── TestTournamentMatching ──────────────────────────────────────────
+
+class TestTournamentMatching:
+    """match_tournament: date range overlap + fuzzy name + PGA check."""
+
+    def test_match_by_date_range_overlap(self):
+        """Event overlapping tournament dates should match."""
+        event = _make_event(
+            start_date="2026-04-09T00:00:00Z",
+            end_date="2026-04-13T00:00:00Z",
+        )
+        result = match_tournament(
+            [event], "The Masters", "2026-04-09", "2026-04-13",
+        )
+        assert result is not None
+        assert result["slug"] == event["slug"]
+
+    def test_reject_outside_date_range(self):
+        """Event fully outside tournament dates should not match."""
+        event = _make_event(
+            title="PGA Tour: Players Championship Winner",
+            start_date="2026-03-10T00:00:00Z",
+            end_date="2026-03-14T00:00:00Z",
+            slug="pga-tour-players-championship-winner",
+        )
+        result = match_tournament(
+            [event], "The Masters", "2026-04-09", "2026-04-13",
+        )
+        assert result is None
+
+    def test_match_by_fuzzy_name(self):
+        """Fuzzy name match ≥0.85 should match even with date mismatch."""
+        # Dates don't overlap, but name is close enough
+        event = _make_event(
+            title="PGA Tour: The Masters Winner",
+            start_date="2026-04-08T00:00:00Z",
+            end_date="2026-04-08T00:00:00Z",  # ends before tournament
+        )
+        # Use a tournament name very similar to the event title
+        result = match_tournament(
+            [event], "The Masters", "2026-04-09", "2026-04-13",
+        )
+        # Should still match via fuzzy name
+        assert result is not None
+
+    def test_reject_similar_but_wrong_event(self):
+        """'US Open' vs 'US Women's Open' should not match (below 0.85)."""
+        event = _make_event(
+            title="PGA Tour: US Women's Open Winner",
+            start_date="2026-06-01T00:00:00Z",
+            end_date="2026-06-05T00:00:00Z",
+        )
+        result = match_tournament(
+            [event], "US Open", "2026-06-12", "2026-06-15",
+        )
+        assert result is None
+
+    def test_exclude_non_pga_tours(self):
+        """LIV, DPWT, LPGA, Korn Ferry events should be excluded."""
+        non_pga = [
+            _make_event(title="LIV Golf: Portland Winner", start_date="2026-04-09T00:00:00Z", end_date="2026-04-13T00:00:00Z"),
+            _make_event(title="DPWT: BMW Championship Winner", start_date="2026-04-09T00:00:00Z", end_date="2026-04-13T00:00:00Z"),
+            _make_event(title="LPGA: Chevron Championship Winner", start_date="2026-04-09T00:00:00Z", end_date="2026-04-13T00:00:00Z"),
+            _make_event(title="Korn Ferry Tour: Boise Open Winner", start_date="2026-04-09T00:00:00Z", end_date="2026-04-13T00:00:00Z"),
+        ]
+        for event in non_pga:
+            result = match_tournament(
+                [event], "The Masters", "2026-04-09", "2026-04-13",
+            )
+            assert result is None, f"Should exclude: {event['title']}"
+
+    def test_handles_date_only_format(self):
+        """Events with date-only strings (no T/Z) should parse fine."""
+        event = _make_event(
+            start_date="2026-04-09",
+            end_date="2026-04-13",
+        )
+        result = match_tournament(
+            [event], "The Masters", "2026-04-09", "2026-04-13",
+        )
+        assert result is not None
+
+
+# ── TestMatchAllMarketTypes ─────────────────────────────────────────
+
+class TestMatchAllMarketTypes:
+
+    def test_returns_matched_events_for_all_types(self):
+        """Should return matched events keyed by market type."""
+        win_event = _make_event(title="PGA Tour: The Masters Winner")
+        t10_event = _make_event(title="PGA Tour: The Masters Top 10")
+        t20_event = _make_event(title="PGA Tour: The Masters Top 20")
+
+        client = MagicMock()
+        client.get_golf_events.side_effect = lambda market_type_filter=None: {
+            "winner": [win_event],
+            "top-10": [t10_event],
+            "top-20": [t20_event],
+        }.get(market_type_filter, [])
+
+        result = match_all_market_types(
+            client, "The Masters", "2026-04-09", "2026-04-13",
+        )
+        assert "win" in result
+        assert "t10" in result
+        assert "t20" in result
+
+    def test_sparse_dict_when_some_types_missing(self):
+        """Missing types should just be absent from result dict."""
+        win_event = _make_event(title="PGA Tour: The Masters Winner")
+
+        client = MagicMock()
+        client.get_golf_events.side_effect = lambda market_type_filter=None: {
+            "winner": [win_event],
+        }.get(market_type_filter, [])
+
+        result = match_all_market_types(
+            client, "The Masters", "2026-04-09", "2026-04-13",
+        )
+        assert "win" in result
+        assert "t10" not in result
+        assert "t20" not in result
+
+    def test_handles_complete_miss(self):
+        """No golf events → empty dict."""
+        client = MagicMock()
+        client.get_golf_events.return_value = []
+
+        result = match_all_market_types(
+            client, "The Masters", "2026-04-09", "2026-04-13",
+        )
+        assert result == {}
+
+
+# ── TestPlayerNameExtraction ────────────────────────────────────────
+
+class TestPlayerNameExtraction:
+
+    def test_extracts_from_slug(self):
+        """'pga-tour-the-masters-winner-scottie-scheffler' → 'Scottie Scheffler'."""
+        market = _make_market(
+            slug="pga-tour-the-masters-winner-scottie-scheffler",
+        )
+        name = extract_player_name(market, event_slug="pga-tour-the-masters-winner")
+        assert name == "Scottie Scheffler"
+
+    def test_extracts_from_question_regex(self):
+        """Falls back to question regex when slug doesn't help."""
+        market = _make_market(
+            slug="",
+            question="Will Rory McIlroy win the Masters?",
+        )
+        market["groupItemTitle"] = ""  # Clear so we test question path
+        name = extract_player_name(market, event_slug="")
+        assert name == "Rory McIlroy"
+
+    def test_handles_special_characters(self):
+        """McIlroy, DeChambeau should preserve casing from slug."""
+        market = _make_market(
+            slug="pga-tour-masters-rory-mcilroy",
+        )
+        market["groupItemTitle"] = ""  # Clear so we test slug path
+        name = extract_player_name(market, event_slug="pga-tour-masters")
+        assert name is not None
+        assert "mcilroy" in name.lower()
+
+    def test_applies_nfc_normalization(self):
+        """Unicode combining chars should be NFC normalized."""
+        # Å can be either single char or A + combining ring
+        market = _make_market(
+            slug="pga-tour-masters-ludvig-a\u030aberg",
+            question="Will Ludvig Åberg win?",
+        )
+        name = extract_player_name(market, event_slug="pga-tour-masters")
+        assert name is not None
+        # NFC form: the combining sequence should be normalized
+        import unicodedata
+        assert name == unicodedata.normalize("NFC", name)
+
+    def test_returns_none_on_unparseable(self):
+        """Totally unparseable market should return None."""
+        market = {"slug": "", "question": "", "outcome": "Yes"}
+        name = extract_player_name(market, event_slug="")
+        assert name is None
+
+    def test_extracts_from_group_item_title(self):
+        """groupItemTitle is a reliable fallback."""
+        market = _make_market(
+            slug="some-generic-slug",
+            question="Some weird question format",
+        )
+        market["groupItemTitle"] = "Scottie Scheffler"
+        name = extract_player_name(market, event_slug="some-event")
+        assert name == "Scottie Scheffler"
+
+
+# ── TestPlayerNameResolution ────────────────────────────────────────
+
+class TestPlayerNameResolution:
+
+    @patch("src.pipeline.polymarket_matching.resolve_player")
+    def test_delegates_to_resolve_player(self, mock_resolve):
+        """Should call resolve_player with source='polymarket'."""
+        mock_resolve.return_value = {"id": 1, "canonical_name": "Scottie Scheffler"}
+        result = resolve_polymarket_player("Scottie Scheffler", auto_create=True)
+        mock_resolve.assert_called_once_with(
+            "Scottie Scheffler", source="polymarket", auto_create=True,
+        )
+        assert result["canonical_name"] == "Scottie Scheffler"
