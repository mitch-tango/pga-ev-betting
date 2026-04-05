# Section 05 Code Review Interview

## User Decision

### #2 — Function signature (explicit params vs slug-only)
**Decision:** Keep current explicit signature (tournament_name, tournament_start, tournament_end). User deferred — chose explicit since caller will have the info.

## Auto-fixes Applied

- **#1 (zero price guard):** `_normalize_price` now returns None for 0/None values; callers guard with `if bid is None or ask is None: continue`
- **#3 (boundary 1.0):** Added `_detect_cent_format` helper (available for future batch detection); `_normalize_price` rejects <= 0
- **#5 (partial results):** Moved per-market_key logic into its own try/except so a failure in t10 doesn't wipe valid win data
- **#6 (int cast):** Wrapped `int(mkt.get("open_interest", 0))` in try/except
- **#11 (rename):** `empty` → `results`

## Let Go

- **#4:** float-to-string round-trip is correct per `kalshi_midpoint` signature
- **#7:** H2H complement derivation is correct for Kalshi binary contracts
- **#8, #9, #10:** Minor test coverage nitpicks, not blocking
