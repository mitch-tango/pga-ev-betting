# Section 09 Code Review

## HIGH SEVERITY

### 1. Dead code branch in _classify_odds_value
`isinstance(val, int)` at line 59 returns 'american' immediately, so the `isinstance(val, (int, float))` check at line 63 never matches an int — only floats. Misleading logic.

### 2. Matchup merge always calls binary_price_to_american
In `merge_prophetx_into_matchups`, `binary_price_to_american(str(p1_prob))` is always called regardless of format. Currently coincidentally correct (probs come from _american_to_prob), but fragile.

### 3. Matchup merge has no format-conditional _prophetx_ask_prob
Not discussed in plan for matchups, and Kalshi doesn't do it either — likely by design.

## MEDIUM SEVERITY

### 4. Missing binary_midpoint import — plan specifies it, implementation hand-rolls midpoint
Plan says to import `binary_midpoint` from devig. Implementation computes `(bid_f + ask_f) / 2.0` inline.

### 5. Caching processed results instead of raw API responses
Plan says "cache raw responses" but code caches the processed/filtered output.

### 6. OI filter default of 0 silently passes when field missing
If API doesn't return `open_interest`, default 0 either passes everything or filters everything depending on threshold.

### 7. Spread filter defaults to 0 when bid/ask missing
Missing bid/ask defaults to 0, spread = 0, always passes filter.

## LOW SEVERITY

### 8. No test for spread filtering
### 9. No test for caching behavior
### 10. No test for mixed formats
### 11. No test for extract_player_name_outright wrapper logic
### 12. make_cut stretch goal not implemented
### 13. Return type inconsistency with sibling modules
### 14. No extract_player_names_matchup mock in matchup tests
