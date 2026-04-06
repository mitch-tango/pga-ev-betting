diff --git a/src/core/devig.py b/src/core/devig.py
index 6dd3582..485c822 100644
--- a/src/core/devig.py
+++ b/src/core/devig.py
@@ -243,12 +243,12 @@ def devig_three_way(prob_a: float, prob_b: float, prob_c: float) -> tuple[float,
     return (result[0], result[1], result[2])
 
 
-# ---- Kalshi Odds Conversion ----
+# ---- Binary Contract Odds Conversion ----
 
-def kalshi_price_to_american(price_str: str) -> str:
-    """Convert a Kalshi dollar price string to American odds string.
+def binary_price_to_american(price_str: str) -> str:
+    """Convert a binary contract price string (0.00-1.00) to American odds string.
 
-    Kalshi contracts are priced 0.00-1.00 (cost to buy a YES contract
+    Binary contracts are priced 0.00-1.00 (cost to buy a YES contract
     paying $1). E.g., '0.06' -> '+1567'.
     """
     if not price_str or not isinstance(price_str, str):
@@ -269,8 +269,8 @@ def kalshi_price_to_american(price_str: str) -> str:
         return f"-{american}"
 
 
-def kalshi_price_to_decimal(price_str: str) -> float | None:
-    """Convert a Kalshi dollar price string to decimal odds.
+def binary_price_to_decimal(price_str: str) -> float | None:
+    """Convert a binary contract price string to decimal odds.
 
     E.g., '0.06' -> 16.667.
     """
@@ -285,8 +285,8 @@ def kalshi_price_to_decimal(price_str: str) -> float | None:
     return 1.0 / prob
 
 
-def kalshi_midpoint(bid_str: str, ask_str: str) -> float | None:
-    """Compute midpoint probability from Kalshi bid and ask prices.
+def binary_midpoint(bid_str: str, ask_str: str) -> float | None:
+    """Compute midpoint probability from binary contract bid and ask prices.
 
     E.g., ('0.04', '0.06') -> 0.05.
     """
@@ -302,3 +302,9 @@ def kalshi_midpoint(bid_str: str, ask_str: str) -> float | None:
     if bid < 0 or ask < 0 or bid > 1.0 or ask > 1.0:
         return None
     return (bid + ask) / 2.0
+
+
+# Backward-compatible aliases (used by existing Kalshi code and tests)
+kalshi_price_to_american = binary_price_to_american
+kalshi_price_to_decimal = binary_price_to_decimal
+kalshi_midpoint = binary_midpoint
diff --git a/tests/test_devig.py b/tests/test_devig.py
index 283e272..53aa6e0 100644
--- a/tests/test_devig.py
+++ b/tests/test_devig.py
@@ -17,6 +17,9 @@ from src.core.devig import (
     kalshi_price_to_american,
     kalshi_price_to_decimal,
     kalshi_midpoint,
+    binary_price_to_american,
+    binary_price_to_decimal,
+    binary_midpoint,
 )
 
 
@@ -338,3 +341,64 @@ class TestKalshiRoundTrip:
         american = kalshi_price_to_american('0.95')
         recovered = parse_american_odds(american)
         assert abs(recovered - 0.95) < 0.002
+
+
+# ---- Generic Binary Contract Name Tests ----
+
+class TestBinaryGenericNames:
+    """Verify generic names produce identical output to Kalshi-specific names."""
+
+    def test_price_to_american_equivalence(self):
+        for val in ("0.06", "0.30", "0.50", "0.55", "0.95"):
+            assert binary_price_to_american(val) == kalshi_price_to_american(val)
+
+    def test_price_to_decimal_equivalence(self):
+        for val in ("0.06", "0.30", "0.50", "0.55"):
+            assert binary_price_to_decimal(val) == kalshi_price_to_decimal(val)
+
+    def test_midpoint_equivalence(self):
+        assert binary_midpoint("0.04", "0.06") == kalshi_midpoint("0.04", "0.06")
+
+    def test_aliases_backward_compat(self):
+        assert kalshi_price_to_american("0.30") != ""
+        assert kalshi_price_to_decimal("0.30") is not None
+        assert kalshi_midpoint("0.04", "0.06") is not None
+
+    def test_binary_price_to_american_zero(self):
+        assert binary_price_to_american("0.0") == ""
+
+    def test_binary_price_to_american_one(self):
+        assert binary_price_to_american("1.0") == ""
+
+    def test_binary_price_to_american_half(self):
+        assert binary_price_to_american("0.5") == "+100"
+
+    def test_binary_price_to_american_string_input(self):
+        result = binary_price_to_american("0.30")
+        assert result.startswith("+") or result.startswith("-")
+
+    def test_binary_price_to_american_float_like_string(self):
+        assert binary_price_to_american("0.06") == kalshi_price_to_american("0.06")
+
+    def test_binary_price_to_decimal_none(self):
+        assert binary_price_to_decimal(None) is None
+
+    def test_binary_price_to_decimal_empty(self):
+        assert binary_price_to_decimal("") is None
+
+    def test_binary_midpoint_typical(self):
+        result = binary_midpoint("0.04", "0.06")
+        assert abs(result - 0.05) < 0.0001
+
+    def test_binary_midpoint_none(self):
+        assert binary_midpoint(None, "0.06") is None
+        assert binary_midpoint("0.04", None) is None
+
+    def test_identity_price_to_american(self):
+        assert binary_price_to_american is kalshi_price_to_american
+
+    def test_identity_price_to_decimal(self):
+        assert binary_price_to_decimal is kalshi_price_to_decimal
+
+    def test_identity_midpoint(self):
+        assert binary_midpoint is kalshi_midpoint
