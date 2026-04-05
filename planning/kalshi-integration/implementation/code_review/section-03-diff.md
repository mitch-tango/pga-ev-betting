diff --git a/config.py b/config.py
index 7818d51..00bd366 100644
--- a/config.py
+++ b/config.py
@@ -18,6 +18,20 @@ RATE_LIMIT_DELAY = 1.5  # seconds between API calls
 API_TIMEOUT = 30  # seconds
 API_MAX_RETRIES = 3
 
+# --- Kalshi ---
+KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
+KALSHI_RATE_LIMIT_DELAY = 0.1  # 100ms between calls (conservative vs 20/sec limit)
+KALSHI_MIN_OPEN_INTEREST = 100  # Minimum OI to include in consensus
+KALSHI_MAX_SPREAD = 0.05  # Max bid-ask spread ($0.05) — wider = illiquid
+KALSHI_SERIES_TICKERS = {
+    "win": "KXPGATOUR",
+    "t10": "KXPGATOP10",
+    "t20": "KXPGATOP20",
+    "tournament_matchup": "KXPGAH2H",
+}
+# TODO: Polymarket — add POLYMARKET_BASE_URL, POLYMARKET_CLOB_URL, book weights here
+# Polymarket covers outrights + top-N but NOT matchups. Gamma API for discovery, CLOB for prices.
+
 # --- Supabase ---
 SUPABASE_URL = os.getenv("SUPABASE_URL")
 SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
@@ -46,13 +60,16 @@ BOOK_WEIGHTS = {
     "win": {
         "pinnacle": 2, "betcris": 2, "betonline": 2,
         "draftkings": 1, "fanduel": 1, "bovada": 1, "start": 1,
+        "kalshi": 2,  # Sharp — prediction markets are efficient
     },
     "placement": {
         "betonline": 1, "draftkings": 1, "fanduel": 1, "bovada": 1, "start": 1,
+        "kalshi": 1,  # Equal weight for placement
     },
     "make_cut": {
         "pinnacle": 2, "betcris": 2, "betonline": 2,
         "draftkings": 1, "fanduel": 1, "bovada": 1, "start": 1,
+        # No kalshi — they don't offer make_cut
     },
     # Matchups: equal-weighted average in edge.py (no weight dict needed),
     # but listed here for reference when Start outrights are added.
diff --git a/planning/kalshi-integration/implementation/deep_implement_config.json b/planning/kalshi-integration/implementation/deep_implement_config.json
index ab4fb4d..db21d50 100644
--- a/planning/kalshi-integration/implementation/deep_implement_config.json
+++ b/planning/kalshi-integration/implementation/deep_implement_config.json
@@ -20,6 +20,10 @@
     "section-01-odds-conversion": {
       "status": "complete",
       "commit_hash": "a3bc514"
+    },
+    "section-02-kalshi-client": {
+      "status": "complete",
+      "commit_hash": "35b944e"
     }
   },
   "pre_commit": {
diff --git a/schema.sql b/schema.sql
index 6a77063..e4d4187 100644
--- a/schema.sql
+++ b/schema.sql
@@ -13,6 +13,8 @@ CREATE TABLE IF NOT EXISTS players (
 );
 
 -- Player aliases (cross-book name mapping)
+-- Valid sources: 'datagolf', 'start', 'kalshi'
+-- TODO: Add 'polymarket' when Polymarket integration is built
 CREATE TABLE IF NOT EXISTS player_aliases (
     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
     player_id UUID REFERENCES players(id) NOT NULL,
@@ -58,6 +60,18 @@ INSERT INTO book_rules (book, market_type, tie_rule, wd_rule, dead_heat_method,
     ('bovada', '3_ball', 'dead_heat', 'void', 'standard', NULL)
 ON CONFLICT (book, market_type) DO NOTHING;
 
+-- Kalshi settlement rules
+-- Binary contracts: $1 payout on YES, $0 on NO. No dead-heat reduction on placement.
+INSERT INTO book_rules (book, market_type, tie_rule, wd_rule, dead_heat_method, notes) VALUES
+    ('kalshi', 'win', 'void', 'void', NULL, 'Binary contract: $1 win / $0 lose. WD = voided contract.'),
+    ('kalshi', 't10', 'win', 'void', NULL, 'Binary: settles YES ($1) if official finish T10 or better, including ties. No dead-heat reduction.'),
+    ('kalshi', 't20', 'win', 'void', NULL, 'Binary: settles YES ($1) if official finish T20 or better, including ties. No dead-heat reduction.'),
+    ('kalshi', 'tournament_matchup', 'void', 'void', NULL, 'Binary H2H: voided if tie or WD.')
+ON CONFLICT (book, market_type) DO NOTHING;
+
+-- TODO: Polymarket settlement rules — similar binary contract structure to Kalshi.
+-- Covers outrights and top-N, but NOT matchups. Requires keyword-based event discovery.
+
 -- Tournaments
 CREATE TABLE IF NOT EXISTS tournaments (
     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
diff --git a/tests/test_kalshi_edge.py b/tests/test_kalshi_edge.py
new file mode 100644
index 0000000..1195700
--- /dev/null
+++ b/tests/test_kalshi_edge.py
@@ -0,0 +1,29 @@
+"""Tests for Kalshi book weight configuration and consensus integration."""
+
+import config
+from src.core.blend import build_book_consensus
+
+
+class TestKalshiBookWeights:
+    """Verify kalshi appears in BOOK_WEIGHTS with correct weight per market type."""
+
+    def test_kalshi_weight_2_in_win_market(self):
+        """kalshi has weight 2 in win market (sharp — prediction markets are efficient)."""
+        assert config.BOOK_WEIGHTS["win"]["kalshi"] == 2
+
+    def test_kalshi_weight_1_in_placement_market(self):
+        """kalshi has weight 1 in placement market (t10, t20)."""
+        assert config.BOOK_WEIGHTS["placement"]["kalshi"] == 1
+
+    def test_kalshi_absent_from_make_cut_weights(self):
+        """kalshi is not present in make_cut weights — Kalshi does not offer make_cut."""
+        assert "kalshi" not in config.BOOK_WEIGHTS["make_cut"]
+
+    def test_build_book_consensus_includes_kalshi(self):
+        """build_book_consensus picks up kalshi with correct weight when present.
+
+        Both pinnacle and kalshi have weight 2 for win market.
+        Weighted average of 0.12 and 0.10 with equal weights = 0.11.
+        """
+        result = build_book_consensus({"kalshi": 0.10, "pinnacle": 0.12}, "win")
+        assert abs(result - 0.11) < 1e-9
