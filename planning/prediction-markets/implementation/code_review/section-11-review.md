# Code Review: Section 11 — Testing Infrastructure & Integration Tests

## High Severity

**1. Fixture factories in conftest.py are never used by any test**
The `tests/conftest.py` defines six fixture factories, but `test_prediction_market_workflow.py` uses local helpers instead. Dead code on arrival.

**2. Tests never verify actual merged data shape — only `isinstance(results, list)`**
Every `calculate_placement_edges` call is followed by `assert isinstance(results, list)`. This passes even if the function returns `[]`. Plan's Key Verification Points #1 and #3 are unverified.

## Medium Severity

**3. `test_all_markets_merge_into_outrights` checks for literal keys `"kalshi"`, `"polymarket"`, `"prophetx"` — works correctly**
The merge functions DO inject top-level keys named exactly `"kalshi"`, `"polymarket"`, `"prophetx"` (American odds strings). Verified in source. This finding is actually fine.

**4. `test_best_book_can_be_any_prediction_market` only verifies dataclass construction**
Does not test that `calculate_placement_edges` actually selects a prediction market as `best_book`.

**5-6. Overly permissive fallback assertions in graceful degradation tests**
The `or "Polymarket" in source` fallback makes specific string checks meaningless.

## Low Severity

**7. Missing plan requirements**: Dead-heat correctness tests, config enforcement patch targets
**8. File handle leak**: `open(mod.__file__).read()` without closing
**9. Unused conftest fixtures should either be used or demonstrate utility for other test files**
