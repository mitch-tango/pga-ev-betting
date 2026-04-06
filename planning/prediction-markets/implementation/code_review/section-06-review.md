# Code Review: Section 06 - Polymarket Odds Pull & Merge

1. **MISSING TEST: Cache raw responses** — No test covers caching behavior.
2. **PRIVATE METHOD COUPLING** — Calls `client._cache_response()`, a private method.
3. **CACHING ONLY TRIGGERS WITH tournament_slug** — Defaults to None, so caching silently skipped in most calls.
4. **FEE-ADJUSTED ASK CAN EXCEED 1.0** — If ask=1.0 (empty asks default), adjusted becomes 1.002.
5. **SPREAD FILTER BYPASSED ON ONE-SIDED BOOKS** — Deliberate but undocumented; one-sided markets with bid=0 produce low-quality midpoints.
6. **MIDPOINT QUALITY ON ONE-SIDED BOOKS** — Midpoints from one-sided books are not market-informed estimates.
7. **DUPLICATE PLAYER HANDLING** — No deduplication; first match used in merge.
8. **TEST HARDCODES CONFIG VALUES** — Tests assume specific config values.
