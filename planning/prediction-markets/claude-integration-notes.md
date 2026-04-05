# External Review Integration Notes

## Reviews Received
- **Gemini (gemini-3-pro-preview)**: 6 critical items, 3 betting/financial items, 2 security items, 4 architectural items
- **OpenAI (gpt-5.2)**: 6 high-risk footguns, 6 missing considerations, 2 security items, 2 performance items, 2 architectural items

## Changes Integrating

### 1. Fix boolean env var parsing (Both reviewers)
**Why**: `bool("0")` is `True` in Python — env flags can never be disabled.
**Action**: Replace `bool(os.getenv(...))` with proper flag parser in Section 1.

### 2. Chunk Polymarket CLOB token_id batches (Gemini)
**Why**: 150+ token IDs in a GET query string risks 414 URI Too Long from Cloudflare.
**Action**: Add chunking (batches of 50) to `get_books()` in Section 2.

### 3. Handle empty orderbooks — missing bids/asks (Both reviewers)
**Why**: Longshot golfers often have one-sided books. `bids[0]` or `asks[0]` will IndexError.
**Action**: Add defensive handling in Section 4 — skip players with no two-sided market.

### 4. Explicit YES token identification (OpenAI)
**Why**: Assuming `clobTokenIds[0]` is YES is fragile. Ordering may vary.
**Action**: Use `outcomes` array or outcome metadata to identify YES token in Section 4.

### 5. Use relative spread filter instead of absolute (OpenAI)
**Why**: 0.05 absolute spread is nonsensical for 0.01 longshots but fine for 0.70 favorites.
**Action**: Change filter to `spread <= max(0.02, 0.15 * midpoint)` in Sections 1 and 4.

### 6. ProphetX credential security — don't cache auth responses (Both reviewers)
**Why**: Caching raw responses could leak tokens/passwords to disk.
**Action**: Exclude auth endpoints from `_cache_response()` in Section 5. Redact tokens in logs.

### 7. Read token expiry from API response (Gemini)
**Why**: Hardcoded 55-minute expiry breaks if ProphetX changes session lifespan.
**Action**: Read `expires_in` from auth payload, fall back to 55 min in Section 5.

### 8. Handle int/float American odds (Gemini)
**Why**: APIs may return `400` (int) not `"+400"` (string).
**Action**: Ensure odds parser handles numeric types in Section 7.

### 9. Improve fuzzy match robustness (OpenAI)
**Why**: SequenceMatcher ≥ 0.7 is too permissive — "US Open" matches "US Women's Open".
**Action**: Raise threshold to 0.85 with token-based matching, plus explicit non-PGA tour exclusion in Sections 3 and 6.

### 10. Polymarket fee rate in config (Gemini)
**Why**: Taker fees erode edge — bettable price should account for execution cost.
**Action**: Add `POLYMARKET_FEE_RATE` constant in Section 1, apply in edge calculation in Section 8.

### 11. Rename volume proxy config constant (OpenAI)
**Why**: `MIN_OPEN_INTEREST` checking `volume` is confusing. Name should match usage.
**Action**: Rename to `POLYMARKET_MIN_VOLUME` in Section 1.

### 12. Add User-Agent header for ProphetX (Gemini)
**Why**: Undocumented APIs often sit behind anti-bot protections.
**Action**: Add standard User-Agent to ProphetX session headers in Section 5.

### 13. Normalize dates to UTC for matching (OpenAI)
**Why**: Timezone mismatch between Polymarket UTC dates and DG local dates can cause false matches.
**Action**: Parse all dates as UTC-aware, use date range overlap instead of ±1 day in Sections 3 and 6.

## NOT Integrating

### Provider interface / base class abstraction (OpenAI)
**Why not**: The spec explicitly raised this as an open question. Three independent clients following the same pattern is fine — a premature abstraction adds complexity without proven benefit. Can refactor later if a fourth market is added.

### Parallel workflow execution (OpenAI)
**Why not**: Sequential pulls are simple and reliable. Total pull time is <30s. Not worth threading complexity for this.

### Cache retention policy (OpenAI)
**Why not**: Nice to have but out of scope. Disk usage is manageable for tournament-level data. Can add later.

### Property-based tests for odds conversions (OpenAI)
**Why not**: Standard unit tests with known values are sufficient. The conversion functions are simple arithmetic.

### Contract tests with real credentials (OpenAI)
**Why not**: Good practice but out of scope for this integration. The mock-based tests + manual verification during initial setup are sufficient.

### Schema adapter / normalized market model (OpenAI)
**Why not**: Adds a layer of abstraction we don't need yet. Each client already normalizes to the same output format in its pull function.

### Polymarket golf tag ID multi-keyword search (Gemini)
**Why not**: The current approach (runtime discovery + env var fallback) is sufficient. Tag IDs are stable enough; if they change, the env var override handles it.

### Shared token bucket rate limiter (OpenAI)
**Why not**: Per-client fixed delay is simple and works within rate limits. Token bucket adds complexity for minimal benefit at our request volume.
