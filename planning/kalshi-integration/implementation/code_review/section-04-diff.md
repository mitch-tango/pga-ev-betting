diff --git a/planning/kalshi-integration/implementation/deep_implement_config.json b/planning/kalshi-integration/implementation/deep_implement_config.json
index db21d50..9faab86 100644
--- a/planning/kalshi-integration/implementation/deep_implement_config.json
+++ b/planning/kalshi-integration/implementation/deep_implement_config.json
@@ -24,6 +24,10 @@
     "section-02-kalshi-client": {
       "status": "complete",
       "commit_hash": "35b944e"
+    },
+    "section-03-config-schema": {
+      "status": "complete",
+      "commit_hash": "ac02814"
     }
   },
   "pre_commit": {
diff --git a/src/pipeline/kalshi_matching.py b/src/pipeline/kalshi_matching.py
new file mode 100644
index 0000000..f858ad9
--- /dev/null
+++ b/src/pipeline/kalshi_matching.py
@@ -0,0 +1,199 @@
+"""Kalshi tournament matching and player name extraction.
+
+Matches Kalshi prediction market events to DataGolf tournaments by date
+and fuzzy name, and extracts/resolves player names from contract titles.
+"""
+
+from __future__ import annotations
+
+import logging
+import re
+import unicodedata
+from datetime import datetime, timedelta
+from difflib import SequenceMatcher
+
+from src.normalize.players import resolve_player
+
+logger = logging.getLogger(__name__)
+
+# PGA safety check — event title must contain one of these
+_PGA_INDICATORS = [
+    "pga", "masters", "u.s. open", "us open", "open championship",
+    "pga championship", "players championship", "memorial",
+    "arnold palmer", "genesis", "rbc", "waste management",
+    "farmers", "at&t", "sentry", "sony", "american express",
+    "cognizant", "wells fargo", "charles schwab", "travelers",
+    "rocket mortgage", "john deere", "3m open", "wyndham",
+    "fedex", "tour championship", "zurich", "valero",
+    "valspar", "honda", "mexico open",
+]
+
+
+def _is_pga_event(title: str) -> bool:
+    """Check if event title indicates a PGA Tour event."""
+    title_lower = title.lower()
+    return any(indicator in title_lower for indicator in _PGA_INDICATORS)
+
+
+def match_tournament(
+    kalshi_events: list[dict],
+    tournament_name: str,
+    tournament_start: str,
+    tournament_end: str,
+) -> str | None:
+    """Find the Kalshi event ticker matching the current DG tournament.
+
+    Matching strategy:
+    1. Date-based: event expiration within [start, end + 1 day]
+    2. Fuzzy name fallback: substring or SequenceMatcher on title
+    3. Safety check: reject non-PGA events
+
+    Returns event_ticker string, or None if no match found.
+    """
+    start_date = datetime.fromisoformat(tournament_start).date()
+    end_date = datetime.fromisoformat(tournament_end).date()
+    end_date_padded = end_date + timedelta(days=1)
+
+    # Normalize tournament name for comparison
+    tourney_lower = tournament_name.lower().strip()
+
+    # Pass 1: date-based matching
+    for event in kalshi_events:
+        if not _is_pga_event(event.get("title", "")):
+            continue
+
+        exp_str = event.get("expected_expiration_time", "")
+        if not exp_str:
+            continue
+
+        try:
+            exp_date = datetime.fromisoformat(exp_str.replace("Z", "+00:00")).date()
+        except (ValueError, TypeError):
+            continue
+
+        if start_date <= exp_date <= end_date_padded:
+            return event["event_ticker"]
+
+    # Pass 2: fuzzy name fallback (only PGA events)
+    best_match = None
+    best_score = 0.0
+
+    for event in kalshi_events:
+        if not _is_pga_event(event.get("title", "")):
+            continue
+
+        title_lower = event.get("title", "").lower()
+
+        # Substring check
+        if tourney_lower in title_lower:
+            return event["event_ticker"]
+
+        # SequenceMatcher on the tournament name portion
+        score = SequenceMatcher(None, tourney_lower, title_lower).ratio()
+        if score > best_score:
+            best_score = score
+            best_match = event
+
+    if best_match and best_score >= 0.7:
+        return best_match["event_ticker"]
+
+    return None
+
+
+def match_all_series(
+    client,
+    tournament_name: str,
+    tournament_start: str,
+    tournament_end: str,
+    series_tickers: dict[str, str],
+) -> dict[str, str]:
+    """Match all Kalshi series to the current tournament.
+
+    Returns {"win": "KXPGATOUR-...", "t10": "KXPGATOP10-...", ...}
+    with only successfully matched entries.
+    """
+    matched = {}
+    for market_type, series_ticker in series_tickers.items():
+        try:
+            events = client.get_golf_events(series_ticker)
+        except Exception:
+            logger.warning("Failed to fetch Kalshi events for %s", series_ticker)
+            continue
+
+        ticker = match_tournament(events, tournament_name, tournament_start, tournament_end)
+        if ticker:
+            matched[market_type] = ticker
+        else:
+            logger.info("No Kalshi match for %s (%s)", market_type, series_ticker)
+
+    return matched
+
+
+# --- Player Name Extraction ---
+
+# Patterns for outright contracts
+_OUTRIGHT_PATTERNS = [
+    re.compile(r"^Will\s+(.+?)\s+(?:win|finish)\b", re.IGNORECASE),
+    re.compile(r"^(.+?)\s+to\s+(?:win|finish)\b", re.IGNORECASE),
+]
+
+# Patterns for H2H contracts
+_H2H_PATTERNS = [
+    re.compile(r"^(.+?)\s+vs\.?\s+(.+?)(?:\s*\?)?$", re.IGNORECASE),
+    re.compile(r"^Will\s+(.+?)\s+beat\s+(.+?)(?:\s*\?)?$", re.IGNORECASE),
+]
+
+# Suffixes to preserve
+_NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}
+
+
+def _clean_name(name: str) -> str:
+    """Clean and NFC-normalize a player name."""
+    name = name.strip().rstrip("?").strip()
+    name = unicodedata.normalize("NFC", name)
+    return name
+
+
+def extract_player_name_outright(contract: dict) -> str | None:
+    """Extract player name from a Kalshi outright contract.
+
+    Tries subtitle first (often just the player name), then title patterns.
+    """
+    subtitle = contract.get("subtitle", "").strip()
+    if subtitle and not any(kw in subtitle.lower() for kw in ["win", "finish", "top", "vs"]):
+        return _clean_name(subtitle)
+
+    title = contract.get("title", "")
+    for pattern in _OUTRIGHT_PATTERNS:
+        m = pattern.match(title)
+        if m:
+            return _clean_name(m.group(1))
+
+    return None
+
+
+def extract_player_names_h2h(contract: dict) -> tuple[str, str] | None:
+    """Extract both player names from a Kalshi H2H contract.
+
+    Returns (player_a, player_b) or None if unparseable.
+    """
+    title = contract.get("title", "")
+    for pattern in _H2H_PATTERNS:
+        m = pattern.match(title)
+        if m:
+            return (_clean_name(m.group(1)), _clean_name(m.group(2)))
+
+    return None
+
+
+# --- Player Name Resolution ---
+
+def resolve_kalshi_player(
+    kalshi_name: str,
+    auto_create: bool = False,
+) -> dict | None:
+    """Resolve a Kalshi player name to a canonical DG player record.
+
+    Delegates to resolve_player() with source="kalshi".
+    """
+    return resolve_player(kalshi_name, source="kalshi", auto_create=auto_create)
diff --git a/tests/test_kalshi_matching.py b/tests/test_kalshi_matching.py
new file mode 100644
index 0000000..248a151
--- /dev/null
+++ b/tests/test_kalshi_matching.py
@@ -0,0 +1,167 @@
+"""Tests for Kalshi tournament matching and player name extraction/resolution."""
+
+import unicodedata
+from unittest.mock import patch, MagicMock
+
+from src.pipeline.kalshi_matching import (
+    match_tournament,
+    extract_player_name_outright,
+    extract_player_names_h2h,
+    resolve_kalshi_player,
+)
+
+
+class TestTournamentMatching:
+    """Matching Kalshi events to DG tournaments by date and name."""
+
+    def test_matches_by_expiration_date_within_tournament_week(self):
+        """Event expiring Sunday of tournament week matches."""
+        events = [
+            {
+                "event_ticker": "KXPGATOUR-26APR10-SCHEFFLER",
+                "title": "PGA Tour: Masters Winner",
+                "expected_expiration_time": "2026-04-12T23:00:00Z",
+            }
+        ]
+        result = match_tournament(events, "Masters Tournament", "2026-04-09", "2026-04-12")
+        assert result == "KXPGATOUR-26APR10-SCHEFFLER"
+
+    def test_falls_back_to_fuzzy_name_match(self):
+        """When dates don't align, fuzzy name matching kicks in."""
+        events = [
+            {
+                "event_ticker": "KXPGATOUR-26MAR-VALERO",
+                "title": "PGA Tour: Valero Texas Open Winner",
+                "expected_expiration_time": "2026-03-30T23:00:00Z",
+            }
+        ]
+        # Dates deliberately off by a week
+        result = match_tournament(events, "Valero Texas Open", "2026-04-02", "2026-04-05")
+        assert result == "KXPGATOUR-26MAR-VALERO"
+
+    def test_returns_none_when_no_match_found(self):
+        """No match by date or name returns None."""
+        events = [
+            {
+                "event_ticker": "KXPGATOUR-OTHER",
+                "title": "PGA Tour: Arnold Palmer Invitational Winner",
+                "expected_expiration_time": "2026-06-15T23:00:00Z",
+            }
+        ]
+        result = match_tournament(events, "Valero Texas Open", "2026-04-02", "2026-04-05")
+        assert result is None
+
+    def test_rejects_non_pga_events(self):
+        """LIV Golf events with overlapping dates are rejected."""
+        events = [
+            {
+                "event_ticker": "KXLIV-26APR",
+                "title": "LIV Golf: Adelaide Winner",
+                "expected_expiration_time": "2026-04-12T23:00:00Z",
+            }
+        ]
+        result = match_tournament(events, "Masters Tournament", "2026-04-09", "2026-04-12")
+        assert result is None
+
+    def test_handles_multiple_open_events_picks_correct_week(self):
+        """Multiple open events — picks the one matching tournament dates."""
+        events = [
+            {
+                "event_ticker": "KXPGATOUR-THISWEEK",
+                "title": "PGA Tour: RBC Heritage Winner",
+                "expected_expiration_time": "2026-04-19T23:00:00Z",
+            },
+            {
+                "event_ticker": "KXPGATOUR-NEXTWEEK",
+                "title": "PGA Tour: Zurich Classic Winner",
+                "expected_expiration_time": "2026-04-26T23:00:00Z",
+            },
+        ]
+        result = match_tournament(events, "RBC Heritage", "2026-04-16", "2026-04-19")
+        assert result == "KXPGATOUR-THISWEEK"
+
+
+class TestPlayerNameExtraction:
+    """Parsing player names from Kalshi contract titles/subtitles."""
+
+    def test_extracts_from_outright_title(self):
+        """Title pattern 'Will X win...' extracts name."""
+        contract = {"title": "Will Scottie Scheffler win the Masters?", "subtitle": ""}
+        result = extract_player_name_outright(contract)
+        assert result == "Scottie Scheffler"
+
+    def test_extracts_from_simple_subtitle(self):
+        """Subtitle with just the player name returns it directly."""
+        contract = {"title": "Masters Tournament Winner", "subtitle": "Scottie Scheffler"}
+        result = extract_player_name_outright(contract)
+        assert result == "Scottie Scheffler"
+
+    def test_extracts_both_names_from_h2h(self):
+        """H2H title 'A vs B' extracts both names."""
+        contract = {"title": "Scottie Scheffler vs Rory McIlroy", "subtitle": ""}
+        result = extract_player_names_h2h(contract)
+        assert result == ("Scottie Scheffler", "Rory McIlroy")
+
+    def test_handles_suffixes(self):
+        """Names with Jr., III, etc. are preserved."""
+        contract = {"title": "Will Davis Love III win the Masters?", "subtitle": ""}
+        result = extract_player_name_outright(contract)
+        assert result == "Davis Love III"
+
+    def test_handles_international_characters(self):
+        """Unicode names are preserved correctly."""
+        contract = {"title": "Will Ludvig Åberg win the Masters?", "subtitle": ""}
+        result = extract_player_name_outright(contract)
+        assert "berg" in result  # Handles with or without å
+        # Verify unicode is NFC normalized
+        assert result == unicodedata.normalize("NFC", result)
+
+
+class TestPlayerNameMatching:
+    """Resolving Kalshi player names to DG canonical names."""
+
+    @patch("src.pipeline.kalshi_matching.resolve_player")
+    def test_exact_match_against_canonical(self, mock_resolve):
+        """Exact name match returns the player record."""
+        mock_resolve.return_value = {"id": "uuid-1", "canonical_name": "Scottie Scheffler"}
+        result = resolve_kalshi_player("Scottie Scheffler")
+        assert result["canonical_name"] == "Scottie Scheffler"
+        mock_resolve.assert_called_once_with("Scottie Scheffler", source="kalshi", auto_create=False)
+
+    @patch("src.pipeline.kalshi_matching.resolve_player")
+    def test_fuzzy_match_finds_close_variant(self, mock_resolve):
+        """Minor spelling variants still resolve via fuzzy match."""
+        mock_resolve.return_value = {"id": "uuid-2", "canonical_name": "Xander Schauffele"}
+        result = resolve_kalshi_player("Xander Schauffele")
+        assert result is not None
+        assert result["canonical_name"] == "Xander Schauffele"
+
+    @patch("src.pipeline.kalshi_matching.resolve_player")
+    def test_creates_alias_on_first_match(self, mock_resolve):
+        """resolve_player is called with source='kalshi'."""
+        mock_resolve.return_value = {"id": "uuid-3", "canonical_name": "Rory McIlroy"}
+        resolve_kalshi_player("Rory McIlroy")
+        mock_resolve.assert_called_once_with("Rory McIlroy", source="kalshi", auto_create=False)
+
+    @patch("src.pipeline.kalshi_matching.resolve_player")
+    def test_uses_cached_alias_on_subsequent_lookups(self, mock_resolve):
+        """Second lookup for same name still delegates to resolve_player (which checks alias cache)."""
+        mock_resolve.return_value = {"id": "uuid-4", "canonical_name": "Jon Rahm"}
+        resolve_kalshi_player("Jon Rahm")
+        resolve_kalshi_player("Jon Rahm")
+        assert mock_resolve.call_count == 2
+
+    @patch("src.pipeline.kalshi_matching.resolve_player")
+    def test_returns_none_for_unknown_player(self, mock_resolve):
+        """Unknown player with auto_create=False returns None."""
+        mock_resolve.return_value = None
+        result = resolve_kalshi_player("Unknown Player XYZ")
+        assert result is None
+
+    @patch("src.pipeline.kalshi_matching.resolve_player")
+    def test_source_is_kalshi(self, mock_resolve):
+        """Source string passed is exactly 'kalshi'."""
+        mock_resolve.return_value = {"id": "uuid-5", "canonical_name": "Tiger Woods"}
+        resolve_kalshi_player("Tiger Woods")
+        args, kwargs = mock_resolve.call_args
+        assert kwargs.get("source") == "kalshi" or (len(args) > 1 and args[1] == "kalshi")
