# Code Review: Section 01 - Odds Conversion Utilities

The implementation is a faithful translation of the plan with all three functions and all specified test cases present. That said, there are several issues worth calling out:

1. **Missing validation in `kalshi_midpoint` for bid/ask exceeding 1.0**: The function guards against negative values but does not guard against values >= 1.0 or unreasonable inputs like bid=5.0. The plan says 'bid and ask are both in [0, 1]' -- the implementation trusts that without enforcing it. If a malformed API response sends a price of 2.5, the midpoint will happily return 1.25+, which is not a valid probability. This could silently corrupt downstream edge calculations.

2. **Missing validation that bid <= ask in `kalshi_midpoint`**: A crossed market (bid > ask) is a data quality signal that something is wrong. The function will silently compute a midpoint from nonsensical inputs. At minimum this should log a warning; arguably it should return None.

3. **Floating-point equality check on `prob == 0.5`**: Comparing floats with `==` is fragile. For this specific case it works because '0.50' parses to exactly 0.5 in IEEE 754, but this is a latent bug if the function is ever called with a computed probability rather than a parsed string. A tolerance check like `abs(prob - 0.5) < 1e-9` would be more defensive.

4. **No test for the round-trip property mentioned in the plan**: The plan explicitly states 'the key constraint is that the round-trip `parse_american_odds(kalshi_price_to_american(p))` should recover the original probability to within rounding tolerance.' No test verifies this property. This is the most important correctness invariant for integration with the edge calculator and it is completely untested.

5. **`kalshi_price_to_decimal` does not reject '0' (no decimal point)**: The input `'0'` would parse to 0.0 and correctly return None via the `prob <= 0` guard, so this is fine. However, `'1'` would parse to 1.0 and return None, which is correct. No issue here on reflection, but the test suite does not cover plain integer strings like '0' or '1' -- only '0.0' and '1.0'.

6. **No test for numeric (non-string) input to `kalshi_price_to_decimal` and `kalshi_price_to_american`**: The plan says 'not a string -> return empty/None'. The tests cover `None` but not passing an actual float like `0.06` or an int like `0`. If someone calls `kalshi_price_to_american(0.06)` they get `''` silently, which could mask bugs at integration time. This should at minimum be tested to document the behavior.

7. **Minor: missing empty-string test for `kalshi_price_to_decimal`**: The plan lists empty string as a case but the test class does not include `test_empty_string`. It would pass due to the `not price_str` guard, but it is an omission from the spec.

Overall severity: LOW to MEDIUM. The core math is correct, the edge cases are mostly handled, and the tests cover the specified cases. The biggest gap is the missing round-trip test, which is the primary integration contract. The midpoint validation gaps could cause silent data corruption if upstream data is malformed.
