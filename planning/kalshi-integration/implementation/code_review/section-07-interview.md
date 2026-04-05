# Section 07 Code Review Interview

## Triage

| # | Issue | Severity | Action |
|---|-------|----------|--------|
| 1 | Test helper uses bare float for DG baseline | Medium | **Auto-fix** |
| 2 | Missing `_kalshi_ask_prob` in test data | Low | Let go |
| 3 | Mocked test doesn't verify numeric values | Low | Let go |
| 4 | Negative edge guard semantics | Low | Let go |
| 5 | Settlement test regression check | Low/process | Already done (290 pass) |
| 6 | Extra test beyond plan | Info | Let go |

## Auto-fixes Applied

### Fix 1: Test helper DG baseline format
Changed `_make_placement_field` default `dg_baseline` from `0.05` (float) to `"+1900"` (American odds string). Updated all test calls to use proper American odds. Refactored t10/t20/sportsbook tests to use `patch()` for controlled blended probabilities, matching the pattern already used by `test_kalshi_wins_best_book_via_dh_advantage`. Created heterogeneous field data for `test_sportsbook_t10_has_deadheat_adj` where one player has genuinely different odds across books.

## Items Let Go
- #2: Tests correctly target the DH bypass logic; ask-price path is orthogonal.
- #3: Asserting Kalshi wins best_book is the critical behavioral assertion. The de-vigged probs from `devig_independent` on homogeneous fields are deterministic, so the structural reasoning holds.
- #4: The `best_adjusted_edge <= 0` guard at line 254 catches this case. No semantic issue in practice.
- #6: Extra config existence test is a useful sanity check.
