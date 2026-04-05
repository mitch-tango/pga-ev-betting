diff --git a/planning/kalshi-integration/implementation/deep_implement_config.json b/planning/kalshi-integration/implementation/deep_implement_config.json
index df3136b..65a6179 100644
--- a/planning/kalshi-integration/implementation/deep_implement_config.json
+++ b/planning/kalshi-integration/implementation/deep_implement_config.json
@@ -25,5 +25,5 @@
     "may_modify_files": false,
     "detected_formatters": []
   },
-  "created_at": "2026-04-05T12:16:56.078742+00:00"
+  "created_at": "2026-04-05T12:19:32.595490+00:00"
 }
\ No newline at end of file
diff --git a/src/core/devig.py b/src/core/devig.py
index 21e6770..747c6cc 100644
--- a/src/core/devig.py
+++ b/src/core/devig.py
@@ -241,3 +241,64 @@ def devig_three_way(prob_a: float, prob_b: float, prob_c: float) -> tuple[float,
 
     result = power_devig([prob_a, prob_b, prob_c])
     return (result[0], result[1], result[2])
+
+
+# ---- Kalshi Odds Conversion ----
+
+def kalshi_price_to_american(price_str: str) -> str:
+    """Convert a Kalshi dollar price string to American odds string.
+
+    Kalshi contracts are priced 0.00-1.00 (cost to buy a YES contract
+    paying $1). E.g., '0.06' -> '+1567'.
+    """
+    if not price_str or not isinstance(price_str, str):
+        return ""
+    try:
+        prob = float(price_str)
+    except (ValueError, TypeError):
+        return ""
+    if prob <= 0 or prob >= 1:
+        return ""
+    if prob == 0.5:
+        return "+100"
+    if prob < 0.5:
+        american = round((1 - prob) / prob * 100)
+        return f"+{american}"
+    else:
+        american = round(prob / (1 - prob) * 100)
+        return f"-{american}"
+
+
+def kalshi_price_to_decimal(price_str: str) -> float | None:
+    """Convert a Kalshi dollar price string to decimal odds.
+
+    E.g., '0.06' -> 16.667.
+    """
+    if not price_str or not isinstance(price_str, str):
+        return None
+    try:
+        prob = float(price_str)
+    except (ValueError, TypeError):
+        return None
+    if prob <= 0 or prob >= 1.0:
+        return None
+    return 1.0 / prob
+
+
+def kalshi_midpoint(bid_str: str, ask_str: str) -> float | None:
+    """Compute midpoint probability from Kalshi bid and ask prices.
+
+    E.g., ('0.04', '0.06') -> 0.05.
+    """
+    if not bid_str or not isinstance(bid_str, str):
+        return None
+    if not ask_str or not isinstance(ask_str, str):
+        return None
+    try:
+        bid = float(bid_str)
+        ask = float(ask_str)
+    except (ValueError, TypeError):
+        return None
+    if bid < 0 or ask < 0:
+        return None
+    return (bid + ask) / 2.0
diff --git a/tests/test_devig.py b/tests/test_devig.py
index c74a90c..1340d5f 100644
--- a/tests/test_devig.py
+++ b/tests/test_devig.py
@@ -14,6 +14,9 @@ from src.core.devig import (
     devig_independent,
     devig_two_way,
     devig_three_way,
+    kalshi_price_to_american,
+    kalshi_price_to_decimal,
+    kalshi_midpoint,
 )
 
 
@@ -214,3 +217,88 @@ class TestDevigThreeWay:
     def test_preserves_none(self):
         a, b, c = devig_three_way(0.40, None, 0.30)
         assert b is None
+
+
+# ---- Kalshi Odds Conversion Tests ----
+
+class TestKalshiPriceToAmerican:
+    def test_longshot(self):
+        # (1 - 0.06) / 0.06 * 100 = 1566.67, rounds to 1567
+        assert kalshi_price_to_american('0.06') == '+1567'
+
+    def test_favorite(self):
+        # 0.55 / 0.45 * 100 = 122.22, rounds to 122
+        assert kalshi_price_to_american('0.55') == '-122'
+
+    def test_even_money(self):
+        assert kalshi_price_to_american('0.50') == '+100'
+
+    def test_extreme_longshot(self):
+        assert kalshi_price_to_american('0.01') == '+9900'
+
+    def test_heavy_favorite(self):
+        assert kalshi_price_to_american('0.95') == '-1900'
+
+    def test_result_format(self):
+        result = kalshi_price_to_american('0.30')
+        assert result.startswith('+') or result.startswith('-')
+        # Should be integer string (no decimals)
+        sign = result[0]
+        assert result[1:].isdigit()
+
+    def test_none_input(self):
+        assert kalshi_price_to_american(None) == ''
+
+    def test_empty_string(self):
+        assert kalshi_price_to_american('') == ''
+
+    def test_invalid_range(self):
+        assert kalshi_price_to_american('0.0') == ''
+        assert kalshi_price_to_american('1.0') == ''
+        assert kalshi_price_to_american('-0.5') == ''
+        assert kalshi_price_to_american('1.5') == ''
+
+
+class TestKalshiPriceToDecimal:
+    def test_longshot(self):
+        result = kalshi_price_to_decimal('0.06')
+        assert abs(result - 16.667) < 0.01
+
+    def test_slight_favorite(self):
+        result = kalshi_price_to_decimal('0.55')
+        assert abs(result - 1.818) < 0.01
+
+    def test_even_money(self):
+        result = kalshi_price_to_decimal('0.50')
+        assert result == 2.0
+
+    def test_zero_price(self):
+        assert kalshi_price_to_decimal('0.0') is None
+
+    def test_one_price(self):
+        assert kalshi_price_to_decimal('1.0') is None
+
+    def test_non_numeric(self):
+        assert kalshi_price_to_decimal('abc') is None
+
+    def test_none_input(self):
+        assert kalshi_price_to_decimal(None) is None
+
+
+class TestKalshiMidpoint:
+    def test_basic(self):
+        result = kalshi_midpoint('0.04', '0.06')
+        assert abs(result - 0.05) < 0.0001
+
+    def test_tight_spread(self):
+        result = kalshi_midpoint('0.50', '0.52')
+        assert abs(result - 0.51) < 0.0001
+
+    def test_none_bid(self):
+        assert kalshi_midpoint(None, '0.06') is None
+
+    def test_none_ask(self):
+        assert kalshi_midpoint('0.04', None) is None
+
+    def test_both_empty(self):
+        assert kalshi_midpoint('', '') is None
