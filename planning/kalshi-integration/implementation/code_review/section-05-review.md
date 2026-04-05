# Section 05 Code Review

## HIGH

### 1. Data corruption via missing price defaults
Lines 99-100, 193-194: `mkt.get('yes_bid', 0)` defaults to `0`. `_normalize_price(0)` returns `0.0`, then `kalshi_midpoint("0.0", "0.0")` returns `0.0` — valid float, corrupts consensus. Fix: reject zero prices.

### 2. Function signature deviation from plan
Both functions require `tournament_name`, `tournament_start`, `tournament_end` as positional args instead of plan's `tournament_slug: str | None`. Section-06 may expect different signature.

### 3. `_normalize_price` boundary at 1.0
Integer `1` (meaning $0.01) passes through as `1.0` (100% probability). Silent corruption.

## MEDIUM

### 4. `kalshi_midpoint` float-to-string round-trip
`kalshi_midpoint(str(bid), str(ask))` converts floats to strings then back. Fragile.

### 5. Outer exception handler discards partial results
If 'win' succeeds but 't10' throws, all results wiped. Each market_key should have own try/except.

### 6. `int()` cast on open_interest outside try/except
Non-numeric value crashes entire function.

### 7. H2H: complement derivation vs grouping
P2 derived as complement rather than pairing contracts. May be correct for Kalshi's actual API but deviates from plan.

## LOW

### 8. Cache test only checks boolean
Should verify called once per series ticker.

### 9. No test for unexpected response format

### 10. `_VALID_T10_MARKETS` defined but unused

### 11. Variable name `empty` is misleading
