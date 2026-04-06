# Section 09 Code Review Interview

## Auto-fixes Applied

1. **_classify_odds_value logic cleanup** — Removed dead int branch; unified int/float check with bool exclusion
2. **Use binary_midpoint from devig** — Replaced hand-rolled `(bid + ask) / 2.0` with `binary_midpoint()` for validation
3. **OI/spread filter defaults** — Changed from defaulting to 0 (silently passing/failing) to skipping filter when field absent
4. **Added spread filter test** — test_filters_wide_spread verifies competitors with wide spreads are excluded

## User Decisions

5. **Caching raw vs processed** → Keep as-is (processed cache, matches Polymarket pattern)
6. **make_cut stretch goal** → Skip (only win/t10/t20)
7. **Return type consistency** → Keep sparse returns (`{}` on failure, only keys with data)

## Let Go

- #3 matchup merge ask_prob: not needed, matches Kalshi pattern
- #9-11 missing tests for caching/mixed formats/wrapper logic: low impact
- #13 return type inconsistency: acceptable, downstream handles both
- #14 missing mock: test works correctly with real implementation
