diff --git a/config.py b/config.py
index 7f5d29c..7aab8d2 100644
--- a/config.py
+++ b/config.py
@@ -11,6 +11,16 @@ from dotenv import load_dotenv
 
 load_dotenv()
 
+
+def env_flag(name: str, default: str = "0") -> bool:
+    """Parse an environment variable as a boolean flag.
+
+    Returns True for "1", "true", "yes" (case-insensitive).
+    Returns False for everything else including "0", "false", "no", "".
+    """
+    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")
+
+
 # --- DG API ---
 DG_API_KEY = os.getenv("DG_API_KEY")
 DG_BASE_URL = "https://feeds.datagolf.com"
@@ -29,8 +39,27 @@ KALSHI_SERIES_TICKERS = {
     "t20": "KXPGATOP20",
     "tournament_matchup": "KXPGAH2H",
 }
-# TODO: Polymarket — add POLYMARKET_BASE_URL, POLYMARKET_CLOB_URL, book weights here
-# Polymarket covers outrights + top-N but NOT matchups. Gamma API for discovery, CLOB for prices.
+
+# --- Polymarket ---
+POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"
+POLYMARKET_CLOB_URL = "https://clob.polymarket.com"
+POLYMARKET_RATE_LIMIT_DELAY = 0.1  # 100ms between calls (conservative vs 1,500 req/10s)
+POLYMARKET_MIN_VOLUME = 100  # Minimum market volume to include
+POLYMARKET_MAX_SPREAD_ABS = 0.10  # Absolute spread ceiling
+POLYMARKET_MAX_SPREAD_REL = 0.15  # Relative spread factor
+POLYMARKET_FEE_RATE = 0.002  # Taker fee applied to ask price for bettable cost
+POLYMARKET_GOLF_TAG_ID = os.getenv("POLYMARKET_GOLF_TAG_ID")
+POLYMARKET_MARKET_TYPES = {"win": "winner", "t10": "top-10", "t20": "top-20"}
+POLYMARKET_ENABLED = env_flag("POLYMARKET_ENABLED", "1")  # On by default (no auth needed)
+
+# --- ProphetX ---
+PROPHETX_BASE_URL = "https://cash.api.prophetx.co"
+PROPHETX_EMAIL = os.getenv("PROPHETX_EMAIL")
+PROPHETX_PASSWORD = os.getenv("PROPHETX_PASSWORD")
+PROPHETX_RATE_LIMIT_DELAY = 0.1  # Conservative (rate limits undocumented)
+PROPHETX_MIN_OPEN_INTEREST = 100  # Minimum OI threshold
+PROPHETX_MAX_SPREAD = 0.05  # Max bid-ask spread
+PROPHETX_ENABLED = bool(PROPHETX_EMAIL and PROPHETX_PASSWORD)  # Auto-enabled when credentials present
 
 # --- Supabase ---
 SUPABASE_URL = os.getenv("SUPABASE_URL")
@@ -76,15 +105,18 @@ BOOK_WEIGHTS = {
         "pinnacle": 2, "betcris": 2, "betonline": 2,
         "draftkings": 1, "fanduel": 1, "bovada": 1, "start": 1,
         "kalshi": 2,  # Sharp — prediction markets are efficient
+        "polymarket": 1, "prophetx": 1,
     },
     "placement": {
         "betonline": 1, "draftkings": 1, "fanduel": 1, "bovada": 1, "start": 1,
         "kalshi": 1,  # Equal weight for placement
+        "polymarket": 1, "prophetx": 1,
     },
     "make_cut": {
         "pinnacle": 2, "betcris": 2, "betonline": 2,
         "draftkings": 1, "fanduel": 1, "bovada": 1, "start": 1,
         # No kalshi — they don't offer make_cut
+        "prophetx": 1,  # Polymarket doesn't offer make_cut
     },
     # Matchups: equal-weighted average in edge.py (no weight dict needed),
     # but listed here for reference when Start outrights are added.
@@ -131,7 +163,8 @@ DEADHEAT_AVG_REDUCTION = {
 }
 
 # Books exempt from dead-heat adjustment (binary contract payout, no DH reduction)
-KALSHI_NO_DEADHEAT_BOOKS = {"kalshi"}
+NO_DEADHEAT_BOOKS = {"kalshi", "polymarket"}
+KALSHI_NO_DEADHEAT_BOOKS = NO_DEADHEAT_BOOKS  # Deprecated alias — removed in section 03
 
 # --- Signature Event ---
 SIGNATURE_PURSE_THRESHOLD = 20_000_000
diff --git a/planning/prediction-markets/implementation/deep_implement_config.json b/planning/prediction-markets/implementation/deep_implement_config.json
index 073ec8f..ba38db1 100644
--- a/planning/prediction-markets/implementation/deep_implement_config.json
+++ b/planning/prediction-markets/implementation/deep_implement_config.json
@@ -28,5 +28,5 @@
     "may_modify_files": false,
     "detected_formatters": []
   },
-  "created_at": "2026-04-05T18:13:13.271156+00:00"
+  "created_at": "2026-04-05T18:15:22.744666+00:00"
 }
\ No newline at end of file
diff --git a/tests/test_config_prediction_markets.py b/tests/test_config_prediction_markets.py
new file mode 100644
index 0000000..f498899
--- /dev/null
+++ b/tests/test_config_prediction_markets.py
@@ -0,0 +1,171 @@
+"""Tests for Polymarket & ProphetX configuration constants."""
+
+import importlib
+import os
+from unittest.mock import patch
+
+
+class TestEnvFlag:
+    """env_flag helper correctly parses boolean env vars."""
+
+    def test_true_values(self):
+        import config
+        for val in ("1", "true", "yes", "True", "YES", "TRUE"):
+            assert config.env_flag("X", val) is True, f"Expected True for {val!r}"
+
+    def test_false_values(self):
+        import config
+        for val in ("0", "false", "no", "False", "", "NO"):
+            assert config.env_flag("X", val) is False, f"Expected False for {val!r}"
+
+    def test_bool_zero_gotcha_avoided(self):
+        """bool('0') is True in Python, but env_flag('X', '0') must be False."""
+        import config
+        assert config.env_flag("X", "0") is False
+
+
+class TestPolymarketEnabled:
+    """POLYMARKET_ENABLED flag respects env var."""
+
+    def test_default_enabled(self):
+        with patch.dict(os.environ, {}, clear=False):
+            os.environ.pop("POLYMARKET_ENABLED", None)
+            import config
+            importlib.reload(config)
+            assert config.POLYMARKET_ENABLED is True
+
+    def test_disabled_by_env(self):
+        with patch.dict(os.environ, {"POLYMARKET_ENABLED": "0"}):
+            import config
+            importlib.reload(config)
+            assert config.POLYMARKET_ENABLED is False
+
+
+class TestProphetxEnabled:
+    """PROPHETX_ENABLED auto-detects credentials."""
+
+    def test_disabled_without_credentials(self):
+        env = {k: v for k, v in os.environ.items()
+               if k not in ("PROPHETX_EMAIL", "PROPHETX_PASSWORD")}
+        with patch.dict(os.environ, env, clear=True):
+            import config
+            importlib.reload(config)
+            assert config.PROPHETX_ENABLED is False
+
+    def test_enabled_with_credentials(self):
+        with patch.dict(os.environ, {
+            "PROPHETX_EMAIL": "test@example.com",
+            "PROPHETX_PASSWORD": "secret",
+        }):
+            import config
+            importlib.reload(config)
+            assert config.PROPHETX_ENABLED is True
+
+
+class TestBookWeights:
+    """BOOK_WEIGHTS includes prediction market entries."""
+
+    def test_polymarket_in_win(self):
+        import config
+        assert "polymarket" in config.BOOK_WEIGHTS["win"]
+
+    def test_polymarket_in_placement(self):
+        import config
+        assert "polymarket" in config.BOOK_WEIGHTS["placement"]
+
+    def test_polymarket_not_in_make_cut(self):
+        import config
+        assert "polymarket" not in config.BOOK_WEIGHTS["make_cut"]
+
+    def test_prophetx_in_win(self):
+        import config
+        assert "prophetx" in config.BOOK_WEIGHTS["win"]
+
+    def test_prophetx_in_placement(self):
+        import config
+        assert "prophetx" in config.BOOK_WEIGHTS["placement"]
+
+    def test_prophetx_in_make_cut(self):
+        import config
+        assert "prophetx" in config.BOOK_WEIGHTS["make_cut"]
+
+
+class TestNoDeadheatBooks:
+    """NO_DEADHEAT_BOOKS set contains correct entries."""
+
+    def test_contains_kalshi(self):
+        import config
+        assert "kalshi" in config.NO_DEADHEAT_BOOKS
+
+    def test_contains_polymarket(self):
+        import config
+        assert "polymarket" in config.NO_DEADHEAT_BOOKS
+
+    def test_prophetx_not_included(self):
+        import config
+        assert "prophetx" not in config.NO_DEADHEAT_BOOKS
+
+    def test_deprecated_alias_still_works(self):
+        """Backward compat: KALSHI_NO_DEADHEAT_BOOKS still exists."""
+        import config
+        assert config.KALSHI_NO_DEADHEAT_BOOKS is config.NO_DEADHEAT_BOOKS
+
+
+class TestPolymarketConstants:
+    """Polymarket URL, rate limit, volume, spread, and fee constants."""
+
+    def test_gamma_url(self):
+        import config
+        assert config.POLYMARKET_GAMMA_URL == "https://gamma-api.polymarket.com"
+
+    def test_clob_url(self):
+        import config
+        assert config.POLYMARKET_CLOB_URL == "https://clob.polymarket.com"
+
+    def test_fee_rate_positive_float(self):
+        import config
+        assert isinstance(config.POLYMARKET_FEE_RATE, float)
+        assert config.POLYMARKET_FEE_RATE > 0
+
+    def test_min_volume_positive_int(self):
+        import config
+        assert isinstance(config.POLYMARKET_MIN_VOLUME, int)
+        assert config.POLYMARKET_MIN_VOLUME > 0
+
+    def test_max_spread_abs_positive(self):
+        import config
+        assert isinstance(config.POLYMARKET_MAX_SPREAD_ABS, float)
+        assert config.POLYMARKET_MAX_SPREAD_ABS > 0
+
+    def test_max_spread_rel_positive(self):
+        import config
+        assert isinstance(config.POLYMARKET_MAX_SPREAD_REL, float)
+        assert config.POLYMARKET_MAX_SPREAD_REL > 0
+
+    def test_market_types_dict(self):
+        import config
+        assert "win" in config.POLYMARKET_MARKET_TYPES
+        assert "t10" in config.POLYMARKET_MARKET_TYPES
+        assert "t20" in config.POLYMARKET_MARKET_TYPES
+
+
+class TestProphetxConstants:
+    """ProphetX URL, credential, rate limit, OI, and spread constants."""
+
+    def test_base_url(self):
+        import config
+        assert config.PROPHETX_BASE_URL == "https://cash.api.prophetx.co"
+
+    def test_rate_limit_delay(self):
+        import config
+        assert config.PROPHETX_RATE_LIMIT_DELAY == 0.1
+
+    def test_min_open_interest(self):
+        import config
+        assert isinstance(config.PROPHETX_MIN_OPEN_INTEREST, int)
+        assert config.PROPHETX_MIN_OPEN_INTEREST > 0
+
+    def test_max_spread(self):
+        import config
+        assert isinstance(config.PROPHETX_MAX_SPREAD, float)
+        assert config.PROPHETX_MAX_SPREAD > 0
