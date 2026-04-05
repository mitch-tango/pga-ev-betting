# Section 07 Code Review: Edge Dead-Heat Per-Book Adjustment

## Findings

### 1. TEST DATA USES NONSENSICAL DG PROBABILITIES (medium severity)
In `_make_placement_field()`, `dg_baseline` defaults to `0.05` and is set to `0.04` in tests. This value flows to `datagolf.baseline_history_fit`, which gets stringified to `"0.04"` at edge.py line 188. `parse_american_odds("0.04")` interprets this as American odds of +0.04, yielding ~0.9996 probability. Tests pass only because the absurdly high dg_prob creates massive edges for every book. The helper should use American odds strings like `"+1900"` instead of bare floats.

### 2. MISSING `_kalshi_ask_prob` IN TEST DATA (low severity)
Test fixtures omit the `_kalshi_ask_prob` field. The Kalshi ask-price branch never fires in tests. Dead-heat bypass still works, but Kelly sizing uses a different decimal than production.

### 3. MOCKED TEST DOES NOT VERIFY NUMERIC VALUES (low severity)
`test_kalshi_wins_best_book_via_dh_advantage` asserts Kalshi wins best_book but doesn't verify actual raw_edge/edge values match the worked example from the plan.

### 4. NO NEGATIVE EDGE GUARD FOR KALSHI (low severity)
If raw_edge is negative for Kalshi, it could "win" best_book before the `best_adjusted_edge <= 0` guard catches it. No actual bug, just slightly misleading semantics.

### 5. PLAN VERIFICATION ITEM 2 NOT COVERED (low severity/process)
Should confirm existing settlement tests pass. (Done: 290 passed, 0 failures in full suite.)

### 6. EXTRA TEST BEYOND PLAN SPEC (informational)
5th test `test_kalshi_no_deadheat_books_config_exists` added beyond plan's 4 tests. Harmless and useful.

## Summary
Core logic change in edge.py is correct and well-structured. Primary concern is issue #1 — test helper should use proper American odds strings for DG baseline probabilities.
