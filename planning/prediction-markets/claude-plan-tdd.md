# TDD Plan: Polymarket & ProphetX Integration

Mirrors `claude-plan.md` sections. Tests use pytest + unittest.mock, following existing Kalshi test patterns. Write tests BEFORE implementing each section.

---

## Section 1: Configuration & Constants

### Test stubs

```python
# Test: env_flag("VAR", "1") returns True for "1", "true", "yes", "True", "YES"
# Test: env_flag("VAR", "0") returns False for "0", "false", "no", "False", ""
# Test: bool("0") gotcha is avoided — env_flag("X", "0") returns False (not True)
# Test: POLYMARKET_ENABLED defaults to True when env var unset
# Test: POLYMARKET_ENABLED is False when env var set to "0"
# Test: PROPHETX_ENABLED is False when email/password not set
# Test: PROPHETX_ENABLED is True when both email and password are set
# Test: BOOK_WEIGHTS contains "polymarket" and "prophetx" for "win" and "placement"
# Test: BOOK_WEIGHTS "make_cut" contains "prophetx" but NOT "polymarket"
# Test: NO_DEADHEAT_BOOKS contains "kalshi" and "polymarket" but NOT "prophetx"
# Test: POLYMARKET_FEE_RATE is a positive float
# Test: POLYMARKET_MIN_VOLUME is a positive int
# Test: POLYMARKET_MAX_SPREAD_ABS and POLYMARKET_MAX_SPREAD_REL are positive floats
```

---

## Section 2: Polymarket API Client

### Test stubs

```python
# --- Constructor ---
# Test: PolymarketClient() reads config defaults
# Test: PolymarketClient(gamma_url=..., clob_url=...) uses overrides

# --- _api_call ---
# Test: _api_call returns ok envelope on 200 response
# Test: _api_call retries on 429 with exponential backoff
# Test: _api_call retries on 5xx with backoff
# Test: _api_call returns error envelope on 400 (no retry)
# Test: _api_call returns error envelope after max retries exhausted
# Test: _api_call uses correct base_url (gamma vs clob)
# Test: _api_call respects rate_limit_delay between calls

# --- _paginated_call ---
# Test: _paginated_call accumulates results across multiple pages
# Test: _paginated_call stops when response has fewer items than limit
# Test: _paginated_call stops at 50-page safety limit and logs warning
# Test: _paginated_call returns partial results on mid-pagination failure

# --- _cache_response ---
# Test: _cache_response writes JSON to data/raw/{slug}/{timestamp}/polymarket_{label}.json
# Test: _cache_response creates directories if needed

# --- get_golf_tag_id ---
# Test: get_golf_tag_id returns tag_id from /sports response
# Test: get_golf_tag_id caches result on instance (second call doesn't hit API)
# Test: get_golf_tag_id falls back to env var when API fails

# --- get_golf_events ---
# Test: get_golf_events passes golf tag_id and active/closed filters
# Test: get_golf_events passes market_type_filter when provided
# Test: get_golf_events returns list of event dicts with nested markets

# --- get_books ---
# Test: get_books returns bid/ask data for single token_id
# Test: get_books chunks requests into batches of 50 when >50 token_ids
# Test: get_books merges results across chunks correctly
# Test: get_books handles empty response for unknown token_ids
```

---

## Section 3: Polymarket Tournament Matching & Player Extraction

### Test stubs

```python
# --- match_tournament ---
# Test: match_tournament finds event by UTC date range overlap
# Test: match_tournament rejects event outside date range
# Test: match_tournament matches by fuzzy name (≥0.85 token similarity)
# Test: match_tournament rejects similar but wrong events ("US Open" vs "US Women's Open")
# Test: match_tournament excludes non-PGA tours (LIV, DPWT, LPGA, Korn Ferry)
# Test: match_tournament handles timezone differences (UTC event vs local tournament dates)

# --- match_all_market_types ---
# Test: match_all_market_types returns matched events for win, t10, t20
# Test: match_all_market_types returns sparse dict when some types have no events
# Test: match_all_market_types handles complete miss (no golf events)

# --- extract_player_name ---
# Test: extract_player_name extracts from slug ("scottie-scheffler" → "Scottie Scheffler")
# Test: extract_player_name extracts from question regex ("Will X win...")
# Test: extract_player_name handles names with special characters (McIlroy, Åberg, DeChambeau)
# Test: extract_player_name applies NFC unicode normalization
# Test: extract_player_name returns None on unparseable market

# --- resolve_polymarket_player ---
# Test: resolve_polymarket_player delegates to resolve_player with source="polymarket"
```

---

## Section 4: Polymarket Odds Pull & Merge

### Test stubs

```python
# --- pull_polymarket_outrights ---
# Test: pull_polymarket_outrights returns {"win": [...], "t10": [...], "t20": [...]}
# Test: each player entry has player_name, polymarket_mid_prob, polymarket_ask_prob, volume
# Test: YES token identified via outcomes array, not assumed as index 0
# Test: skips market when YES token cannot be identified (logs warning)
# Test: handles empty bids (bid=0) and empty asks (ask=1.0)
# Test: skips player when both bids and asks are empty
# Test: applies relative spread filter: spread <= max(abs_max, rel_factor * mid)
# Test: filters out markets below MIN_VOLUME
# Test: applies POLYMARKET_FEE_RATE to ask probability (adjusted_ask = ask + fee)
# Test: returns empty dict when no tournament match found
# Test: caches raw responses

# --- merge_polymarket_into_outrights ---
# Test: merge adds "polymarket" American odds key to matched DG players
# Test: merge adds "_polymarket_ask_prob" with fee-adjusted float
# Test: merge skips DG players not found in Polymarket data
# Test: merge handles case-insensitive name matching
# Test: merge uses binary_price_to_american() for odds conversion
# Test: merge doesn't modify Polymarket players not in DG data

# --- No matchup pull ---
# Test: confirm no pull_polymarket_matchups function exists (Polymarket has no golf H2H)
```

---

## Section 5: ProphetX API Client

### Test stubs

```python
# --- Constructor ---
# Test: ProphetXClient reads email/password from config
# Test: ProphetXClient sets User-Agent header on session

# --- Authentication ---
# Test: _authenticate sends email/password to /auth/login
# Test: _authenticate stores access_token and refresh_token
# Test: _authenticate reads expires_in from response and sets token_expiry
# Test: _authenticate falls back to 55-minute expiry when expires_in absent
# Test: _authenticate returns error envelope on login failure
# Test: _refresh_auth sends refresh_token to /extend-session
# Test: _refresh_auth falls back to full _authenticate on refresh failure
# Test: _ensure_auth calls _authenticate on first request (lazy init)
# Test: _ensure_auth calls _refresh_auth when token expired
# Test: _ensure_auth no-ops when token still valid

# --- _api_call ---
# Test: _api_call adds Authorization header
# Test: _api_call calls _ensure_auth before request
# Test: _api_call re-authenticates on 401, then retries
# Test: _api_call same retry/backoff pattern as Polymarket (429, 5xx, timeout)

# --- _cache_response ---
# Test: _cache_response writes to prophetx_{label}.json
# Test: _cache_response SKIPS endpoints containing "/auth/" (security)
# Test: _cache_response does not write tokens or credentials to disk

# --- Public methods ---
# Test: get_golf_events returns list of golf event dicts
# Test: get_markets_for_events returns market dicts with odds and competitor info
```

---

## Section 6: ProphetX Tournament Matching & Player Extraction

### Test stubs

```python
# --- match_tournament ---
# Test: match_tournament uses UTC date range overlap
# Test: match_tournament uses token-based fuzzy match ≥0.85
# Test: match_tournament tries multiple date field names (start_date, startDate, etc.)
# Test: match_tournament tries multiple title field names (name, title, event_name, etc.)
# Test: match_tournament excludes non-PGA tours

# --- classify_markets ---
# Test: classify_markets identifies outright winner from moneyline + sub_type
# Test: classify_markets identifies H2H matchup from moneyline with 2 competitors
# Test: classify_markets identifies make_cut from "cut" keyword
# Test: classify_markets discovers t10/t20 from market names if present
# Test: classify_markets returns sparse dict with only found types

# --- extract_player_name_outright ---
# Test: extract from competitor_name field
# Test: tries multiple field names (competitor_name, participant, player)
# Test: logs warning when no name field found

# --- extract_player_names_matchup ---
# Test: extracts both player names from H2H market
# Test: handles markets with exactly 2 competitors
```

---

## Section 7: ProphetX Odds Pull & Merge

### Test stubs

```python
# --- pull_prophetx_outrights ---
# Test: returns {"win": [...], "t10": [...], "t20": [...]} format
# Test: detects American odds as int (400, -150) not just string ("+400")
# Test: detects American odds as string ("+400", "-150")
# Test: detects binary contract prices (0.55) and converts
# Test: handles mixed formats gracefully
# Test: filters by quality thresholds
# Test: resolves to DG canonical names

# --- pull_prophetx_matchups ---
# Test: returns [{p1_name, p2_name, p1_prob, p2_prob}] format
# Test: extracts both player names and odds per side
# Test: handles American odds for matchups

# --- merge_prophetx_into_outrights ---
# Test: adds "prophetx" American odds string
# Test: adds "_prophetx_ask_prob" when binary format detected
# Test: no "_prophetx_ask_prob" when American format (American IS the bettable price)

# --- merge_prophetx_into_matchups ---
# Test: frozenset name matching (order-independent)
# Test: adds odds["prophetx"] = {"p1": ..., "p2": ...}
```

---

## Section 8: Edge Calculation Updates

### Test stubs

```python
# --- Dead-heat bypass ---
# Test: NO_DEADHEAT_BOOKS used instead of KALSHI_NO_DEADHEAT_BOOKS
# Test: Polymarket edges skip dead-heat reduction
# Test: ProphetX edges apply dead-heat reduction (not in NO_DEADHEAT_BOOKS)
# Test: Kalshi edges still skip dead-heat reduction (regression)

# --- Generalized ask-based pricing ---
# Test: edge calc uses _polymarket_ask_prob for bettable decimal
# Test: edge calc uses _prophetx_ask_prob for bettable decimal (when binary)
# Test: edge calc uses _kalshi_ask_prob for bettable decimal (regression)
# Test: edge calc skips ask-based pricing when ask key not present (traditional book)
# Test: edge calc validates ask prob is numeric and in (0, 1), warns on invalid
# Test: Polymarket fee rate already reflected in stored _polymarket_ask_prob

# --- Consensus ---
# Test: blend.py picks up polymarket and prophetx from BOOK_WEIGHTS automatically
# Test: consensus calculation works with 0, 1, 2, or 3 prediction markets present
```

---

## Section 9: Workflow Integration

### Test stubs

```python
# --- run_pretournament.py ---
# Test: Polymarket block runs when POLYMARKET_ENABLED=True
# Test: Polymarket block skips when POLYMARKET_ENABLED=False
# Test: Polymarket failure prints warning and continues (graceful degradation)
# Test: ProphetX block runs when PROPHETX_ENABLED=True
# Test: ProphetX block skips when PROPHETX_ENABLED=False
# Test: ProphetX failure prints warning and continues
# Test: Pipeline works with all prediction markets failing (DG-only)

# --- run_preround.py ---
# Test: same enabled/disabled/failure patterns as pretournament

# --- run_live_check.py ---
# Test: live check includes prediction market edges when available

# --- Integration ---
# Test: full pipeline with all 3 prediction markets returns valid edges
# Test: full pipeline with only DG + Kalshi returns valid edges (regression)
# Test: pull order: DG → Kalshi → Polymarket → ProphetX → edge calc
```

---

## Section 10: Odds Conversion Refactoring

### Test stubs

```python
# Test: binary_price_to_american() produces same output as old kalshi_price_to_american()
# Test: binary_price_to_decimal() produces same output as old kalshi_price_to_decimal()
# Test: binary_midpoint() produces same output as old kalshi_midpoint()
# Test: old names still work as aliases (kalshi_price_to_american still callable)
# Test: binary_price_to_american handles edge cases: 0.0, 0.5, 1.0
# Test: binary_price_to_american handles string and float inputs
```

---

## Section 11: Testing Infrastructure

### Test stubs

```python
# --- Test helpers ---
# Test: _make_polymarket_event() creates valid event fixture with nested markets
# Test: _make_polymarket_market() creates market with configurable prices/tokens/volume
# Test: _make_prophetx_event() creates valid event fixture
# Test: _make_prophetx_market() creates market with configurable odds/competitors

# --- Integration test ---
# Test: test_prediction_market_workflow verifies all 3 markets integrate end-to-end
# Test: partial failure (1 market down) still produces valid output
# Test: total failure (all prediction markets down) produces DG-only output
```
