# Implementation Plan: Polymarket & ProphetX Integration

## Overview

This plan adds two prediction markets — Polymarket and ProphetX — to the PGA EV betting pipeline. Both follow the established Kalshi integration pattern: config → API client → tournament matching → player extraction → odds pull → merge → edge calculation. The pipeline currently supports DG-aggregated sportsbooks plus Kalshi; after this work it will support up to 3 prediction markets, each independently enabled/disabled via graceful degradation.

## System Context

The PGA EV betting system detects +EV opportunities by comparing a DataGolf (DG) model probability with a consensus of sportsbook/prediction market odds. The pipeline:

1. Pulls DG model predictions + sportsbook odds from the DG API
2. Pulls prediction market odds (currently Kalshi only)
3. Merges prediction market data into DG data as additional "book" columns
4. De-vigs each book's field, builds weighted consensus, blends with DG model
5. Identifies edges and sizes bets via quarter-Kelly

Adding more independent price sources improves consensus accuracy and increases the chance of finding exploitable mispricing.

---

## Section 1: Configuration & Constants

### What to build
Add Polymarket and ProphetX constants to `config.py`, following the existing Kalshi pattern.

### Polymarket config
- `POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"` — event discovery
- `POLYMARKET_CLOB_URL = "https://clob.polymarket.com"` — pricing/orderbook
- `POLYMARKET_RATE_LIMIT_DELAY = 0.1` — 100ms between calls (conservative vs 1,500 req/10s)
- `POLYMARKET_MIN_VOLUME = 100` — minimum market volume (renamed from "open interest" since Polymarket reports volume not OI)
- `POLYMARKET_MAX_SPREAD_ABS = 0.10` — absolute spread ceiling
- `POLYMARKET_MAX_SPREAD_REL = 0.15` — relative spread factor; effective filter is `spread <= max(POLYMARKET_MAX_SPREAD_ABS, POLYMARKET_MAX_SPREAD_REL * midpoint)` — prevents filtering out illiquid longshots while still catching wide spreads on favorites
- `POLYMARKET_FEE_RATE = 0.002` — taker fee applied when computing bettable price (Polymarket recently introduced fees that erode edge)
- `POLYMARKET_GOLF_TAG_ID` — discovered at runtime via `/sports` endpoint, but provide a fallback env var `os.getenv("POLYMARKET_GOLF_TAG_ID")` for caching the discovered value
- `POLYMARKET_MARKET_TYPES = {"win": "winner", "t10": "top-10", "t20": "top-20"}` — maps internal keys to Polymarket's `sports_market_types` filter values

### ProphetX config
- `PROPHETX_BASE_URL = "https://cash.api.prophetx.co"` 
- `PROPHETX_EMAIL = os.getenv("PROPHETX_EMAIL")` — login credential
- `PROPHETX_PASSWORD = os.getenv("PROPHETX_PASSWORD")` — login credential
- `PROPHETX_RATE_LIMIT_DELAY = 0.1` — conservative (rate limits undocumented)
- `PROPHETX_MIN_OPEN_INTEREST = 100` — same threshold
- `PROPHETX_MAX_SPREAD = 0.05` — same threshold

### Book weights updates
Add both to `BOOK_WEIGHTS` at weight 1 (conservative until validated):
```python
"win": {..., "polymarket": 1, "prophetx": 1},
"placement": {..., "polymarket": 1, "prophetx": 1},
"make_cut": {..., "prophetx": 1},  # Polymarket doesn't offer make_cut
```

### Dead-heat config
Rename `KALSHI_NO_DEADHEAT_BOOKS` → `NO_DEADHEAT_BOOKS` and add Polymarket:
```python
NO_DEADHEAT_BOOKS = {"kalshi", "polymarket"}
```
ProphetX is NOT added — it uses traditional odds format where dead-heat rules apply. If ProphetX turns out to use binary contracts, add it later.

Update all references to `KALSHI_NO_DEADHEAT_BOOKS` in `edge.py` to use the new name.

### Enabled flags
Add a helper `env_flag(name, default)` that parses env values correctly — `os.getenv(name, default).strip().lower() in ("1", "true", "yes")`. This avoids the Python gotcha where `bool("0")` is `True`.

- `POLYMARKET_ENABLED = env_flag("POLYMARKET_ENABLED", "1")` — on by default (no auth needed)
- `PROPHETX_ENABLED = bool(PROPHETX_EMAIL and PROPHETX_PASSWORD)` — auto-enabled when credentials present

---

## Section 2: Polymarket API Client

### What to build
`src/api/polymarket.py` — a `PolymarketClient` class following the Kalshi client pattern.

### Constructor
- Accepts optional `gamma_url`, `clob_url`, `cache_dir` for testability
- Reads config via `getattr(config, ...)` with defaults
- Stores `rate_limit_delay`, `timeout`, `max_retries`

### Core methods

**`_api_call(base_url, endpoint, params)`** — same retry/rate-limit pattern as Kalshi:
- 200 → `{"status": "ok", "data": resp.json()}`
- 429 → exponential backoff (5s, 10s, 15s)
- 400 → immediate error return
- 5xx → backoff retry
- Timeout → 3s wait retry
- Returns error envelope after max_retries

Takes `base_url` parameter since Polymarket uses two different base URLs (Gamma vs CLOB).

**`_paginated_call(base_url, endpoint, params, collection_key)`** — offset-based pagination:
- Uses `limit=100` and incrementing `offset`
- Accumulates results until response returns fewer items than limit
- Max 50 pages safety limit
- Partial failure returns accumulated results

**`_cache_response(data, label, tournament_slug)`** — identical pattern to Kalshi, saves to `data/raw/{slug}/{timestamp}/polymarket_{label}.json`

### Public methods

**`get_golf_tag_id()`** — calls `GET /sports`, finds the golf sport entry, returns its tag_id. Caches result on the instance for the session. Falls back to `POLYMARKET_GOLF_TAG_ID` env var if API call fails.

**`get_golf_events(market_type_filter=None)`** — calls `GET /events` with golf tag_id, `active=true`, `closed=false`. If `market_type_filter` provided (e.g., "winner"), also passes it. Returns list of event dicts including nested `markets[]`.

**`get_event_markets(event_id)`** — calls `GET /events/{id}` and returns the `markets` array. Each market includes `question`, `outcomePrices`, `clobTokenIds`, `volume`, `liquidity`, `marketType`.

**`get_midpoints(token_ids)`** — calls `GET /midpoints` on CLOB API with batch of token_ids. Returns dict mapping token_id → midpoint price string.

**`get_books(token_ids)`** — calls `GET /books` on CLOB API with batches of token_ids. **Chunks into batches of 50 token_ids per request** to avoid 414 URI Too Long errors from Cloudflare when passing 150+ IDs via query parameters. Merges response dicts across chunks. Returns dict mapping token_id → `{bids: [...], asks: [...]}`.

### Design notes
- Batch CLOB endpoints are preferred over per-token calls for efficiency (one call per 50 players vs 100+ individual calls)
- The Gamma API returns `outcomePrices` inline with the market, which may be sufficient for initial pricing without hitting CLOB. But CLOB provides bid/ask spread data needed for filtering, so we'll use CLOB for final pricing.

---

## Section 3: Polymarket Tournament Matching & Player Extraction

### What to build
`src/pipeline/polymarket_matching.py` — tournament and player name matching.

### Tournament matching

**`match_tournament(events, tournament_name, tournament_start, tournament_end)`**

Similar two-pass strategy as Kalshi:
1. **Date-based**: parse all dates as UTC-aware datetimes. Use **date range overlap** matching (event range overlaps tournament range) instead of ±1 day point matching — this is more robust across timezone differences between Polymarket UTC timestamps and DG local dates.
2. **Fuzzy name**: strip "PGA Tour: " prefix, strip " Winner" / " Top 10" / " Top 20" suffix, then token-based similarity ≥ 0.85 (using RapidFuzz `token_set_ratio` if available, else SequenceMatcher). Higher threshold than Kalshi to prevent false matches like "US Open" vs "US Women's Open".

**Difference from Kalshi**: Polymarket uses `startDate`/`endDate` fields (not `expected_expiration_time`). The date matching logic uses range overlap on different fields.

**PGA safety check**: reuse the same `_is_pga_event()` pattern — check title for PGA indicators. Explicitly exclude non-PGA tours (DPWT, LIV, LPGA, Korn Ferry) by checking for these keywords.

**`match_all_market_types(client, tournament_name, start, end)`** — iterates over `POLYMARKET_MARKET_TYPES`, calls `get_golf_events(market_type_filter=type)` for each, matches tournament. Returns `{"win": event_dict, "t10": event_dict, "t20": event_dict}` with only matched entries.

### Player name extraction

**`extract_player_name(market)`** — Polymarket market questions follow patterns like:
- "Will Scottie Scheffler win the 2026 Valero Texas Open?"
- "Scottie Scheffler" (may appear in market title or slug)

Strategy:
1. Try the `slug` field: strip event prefix, convert hyphens to spaces, title-case → candidate name
2. Try regex on `question`: `r"^Will\s+(.+?)\s+(?:win|finish)\b"`
3. Apply `_clean_name()` (strip, NFC normalize) — reuse from Kalshi matching or extract to shared utility

**`resolve_polymarket_player(name)`** — delegates to `resolve_player(name, source="polymarket")`.

### Design notes
- Polymarket events contain nested `markets[]` (one per player), so we get all players from a single event fetch rather than needing a separate "get markets for event" call
- The slug-based name extraction is more reliable than regex for Polymarket since slugs follow a consistent pattern

---

## Section 4: Polymarket Odds Pull & Merge

### What to build
`src/pipeline/pull_polymarket.py` — odds pull and merge into DG data.

### `pull_polymarket_outrights(tournament_name, start, end, tournament_slug=None)`

Returns `{"win": [...], "t10": [...], "t20": [...]}` — same format as Kalshi outrights.

Flow:
1. Create `PolymarketClient()`
2. Call `match_all_market_types()` to find events for each market type
3. For each matched event:
   a. Get markets (from the event's nested `markets[]`)
   b. Identify YES token IDs from each market — use the `outcomes` array or outcome metadata to find the affirmative token rather than assuming `clobTokenIds[0]` is always YES. Log a warning and skip the market if YES token cannot be confidently identified.
   c. Batch call `get_books(token_ids)` (chunked into batches of 50) to get bid/ask for all players
   d. For each market/player:
      - Extract player name via `extract_player_name()`
      - Parse bid (best bid price) and ask (best ask price) from orderbook. **Handle empty sides**: if no bids, set bid=0; if no asks, set ask=1.0. Skip the player entirely if both sides are empty (no two-sided market).
      - Compute midpoint: `(bid + ask) / 2`
      - Filter: relative spread check `spread <= max(MAX_SPREAD_ABS, MAX_SPREAD_REL * midpoint)`, volume ≥ `POLYMARKET_MIN_VOLUME`
      - Resolve to DG canonical name
      - Append `{player_name, polymarket_mid_prob, polymarket_ask_prob, volume}`
4. Cache raw responses
5. Return results dict

**Filtering**: Relative spread filter (see config), then volume ≥ `POLYMARKET_MIN_VOLUME`.

**Fee adjustment**: When computing bettable price, apply `POLYMARKET_FEE_RATE` — the ask probability used for edge calculation should be adjusted upward by the fee rate to reflect actual execution cost: `adjusted_ask = ask + POLYMARKET_FEE_RATE`.

### `merge_polymarket_into_outrights(dg_outrights, polymarket_outrights)`

Same pattern as `merge_kalshi_into_outrights()`:
1. Build lookup by lowercase canonical name
2. For each DG player, find match in Polymarket data
3. Add `"polymarket"` key with American odds string (from midpoint, using existing `kalshi_price_to_american()` — works for any 0-1 price)
4. Add `"_polymarket_ask_prob"` key with float ask probability

The existing `kalshi_price_to_american()` and `kalshi_price_to_decimal()` in `devig.py` work for any binary contract price. Consider renaming them to `binary_price_to_american()` / `binary_price_to_decimal()` for clarity, with the old names kept as aliases to avoid breaking existing code.

### No matchup pull
Polymarket does not offer H2H matchups for golf, so there is no `pull_polymarket_matchups()` function.

---

## Section 5: ProphetX API Client

### What to build
`src/api/prophetx.py` — a `ProphetXClient` class.

### Constructor
- Accepts optional `base_url`, `cache_dir` for testability
- Reads `PROPHETX_EMAIL`, `PROPHETX_PASSWORD`, `PROPHETX_BASE_URL` from config
- Stores `access_token = None`, `refresh_token = None`, `token_expiry = None`
- Sets a standard browser User-Agent header on the session to avoid anti-bot protections on undocumented APIs

### Authentication

**`_authenticate()`** — called lazily on first API request or when token expires:
1. `POST /api/v1/auth/login` with `{"email": email, "password": password}`
2. Store `access_token`, `refresh_token`. Read `expires_in` from auth response if present and set `token_expiry = now + expires_in - 5min buffer`; fall back to `now + 55 minutes` if field is absent.
3. If login fails, return error envelope
4. **Never cache auth responses** — exclude `/auth/` endpoints from `_cache_response()` to prevent leaking tokens/credentials to disk

**`_refresh_auth()`** — called when `token_expiry` is past:
1. `POST /api/v1/auth/extend-session` with Bearer refresh_token
2. Update `access_token` and `token_expiry` (same `expires_in` logic)
3. If refresh fails (30-day expiry), fall back to full `_authenticate()`

**`_ensure_auth()`** — checks token validity, refreshes or re-authenticates as needed. Called at the start of every `_api_call()`.

### Core methods

**`_api_call(endpoint, params=None, method="GET")`** — same retry/rate-limit pattern as Kalshi:
- Calls `_ensure_auth()` first
- Adds `Authorization: Bearer {access_token}` header
- Same 429/5xx/timeout handling
- 401 → re-authenticate once, then retry

**`_cache_response(data, label, tournament_slug)`** — saves to `data/raw/{slug}/{timestamp}/prophetx_{label}.json`

### Public methods

**`get_golf_events()`** — calls the sport events endpoint filtered for golf/PGA. Returns list of event dicts with event IDs.

**`get_markets_for_events(event_ids)`** — calls `get_multiple_markets` with event ID list. Returns list of market dicts containing `line_id`, odds, competitor info, market type.

### Security notes
- **Never cache auth responses**: `_cache_response()` must skip any endpoint containing `/auth/`. This prevents tokens, refresh tokens, and credentials from being written to `data/raw/`.
- **Redact sensitive headers in logs**: If logging request/response details, strip `Authorization` headers and any `access_token`/`refresh_token` values.

### Design notes
- ProphetX API documentation is incomplete. The client should be defensive: log and skip unknown response fields, handle unexpected formats.
- The `get_golf_events()` and `get_markets_for_events()` method signatures may need adjustment once we see actual API responses. Build the client with exploratory logging initially.
- ProphetX may return American odds directly (not binary prices). The client should detect the format: if odds values are integers/floats like `400`/`-150` OR strings like `"+400"`/`"-150"`, they're American; if they're decimal 0-1, they're binary contract prices. **Handle both numeric and string types** — APIs frequently return American odds as `int` not `str`. Store a flag on the client instance after first successful response.

---

## Section 6: ProphetX Tournament Matching & Player Extraction

### What to build
`src/pipeline/prophetx_matching.py` — tournament and player name matching.

### Tournament matching

**`match_tournament(events, tournament_name, tournament_start, tournament_end)`**

Same two-pass strategy:
1. **Date-based**: parse dates as UTC-aware, use date range overlap matching (same as Polymarket improvement)
2. **Fuzzy name**: token-based similarity ≥ 0.85 with explicit non-PGA tour exclusion (DPWT, LIV, LPGA, Korn Ferry)

ProphetX event structure may differ from Kalshi/Polymarket. The matcher should look for common date fields (`start_date`, `startDate`, `event_date`, etc.) and title fields (`name`, `title`, `event_name`, etc.) — be flexible about field names given incomplete docs.

### Market type detection

**`classify_markets(markets)`** — ProphetX markets have a `market_type` enum of `moneyline`, `spread`, `total`. For golf:
- `moneyline` with `sub_type: "outrights"` → tournament winner
- `moneyline` with two competitors → H2H matchup
- Markets mentioning "make cut" or "cut" → make_cut

The classifier should also check for `top-10`, `top-20` patterns in market names/descriptions in case ProphetX offers them (not confirmed, but we should discover dynamically per interview answer).

Returns `{"win": [...], "matchup": [...], "make_cut": [...], "t10": [...], "t20": [...]}` — sparse dict with only discovered types.

### Player name extraction

**`extract_player_name_outright(market)`** — extract from competitor info or market title. ProphetX markets likely include competitor names directly (not embedded in question text like Polymarket). Look for fields like `competitor_name`, `participant`, `player`, etc.

**`extract_player_names_matchup(market)`** — extract both player names from H2H market. Look for two competitor entries in the market data.

**`resolve_prophetx_player(name)`** — delegates to `resolve_player(name, source="prophetx")`.

### Design notes
- ProphetX field names are uncertain. The matching/extraction code should try multiple possible field names and log warnings when expected fields are missing.
- Initial implementation may need iteration once we see real API responses.

---

## Section 7: ProphetX Odds Pull & Merge

### What to build
`src/pipeline/pull_prophetx.py` — odds pull and merge.

### `pull_prophetx_outrights(tournament_name, start, end, tournament_slug=None)`

Returns same format as Kalshi: `{"win": [...], "t10": [...], "t20": [...]}`.

Flow:
1. Create `ProphetXClient()` (triggers lazy auth)
2. Call `get_golf_events()` → match tournament → `get_markets_for_events()`
3. Classify markets by type
4. For outright markets:
   a. Extract player name from each market's competitor data
   b. Read odds — detect format (American vs binary):
      - If American string ("+400"): store directly, compute implied prob via existing `parse_american_odds()`
      - If binary (0.55): compute American via `kalshi_price_to_american()`, store ask prob
   c. Filter by quality thresholds
   d. Resolve to DG canonical name
   e. Append player dict
5. Cache raw responses
6. Return results

### `pull_prophetx_matchups(tournament_name, start, end, tournament_slug=None)`

Returns same format as Kalshi matchups: `[{p1_name, p2_name, p1_prob, p2_prob}]`.

Flow:
1. From classified markets, extract H2H matchups
2. For each matchup:
   a. Extract both player names
   b. Read odds for each side
   c. Convert to probabilities (from American or binary)
   d. Filter by quality
   e. Resolve names
   f. Append matchup dict

### `merge_prophetx_into_outrights(dg_outrights, prophetx_outrights)`

Same merge pattern as Kalshi. Adds `"prophetx"` American odds string and `"_prophetx_ask_prob"` (if binary format) or just `"prophetx"` (if American format — no separate ask prob needed since American odds already represent the bettable price).

### `merge_prophetx_into_matchups(dg_matchups, prophetx_matchups)`

Same as Kalshi matchup merge — frozenset name matching, order alignment, adds `odds["prophetx"] = {"p1": ..., "p2": ...}`.

### Make-cut support

If ProphetX offers make_cut markets, the pull function should also return them. Make_cut merges into the existing DG make_cut data following the same pattern. This is a stretch goal — implement if the API response reveals make_cut markets.

---

## Section 8: Edge Calculation Updates

### What to change
Minimal changes to `src/core/edge.py` — the existing architecture handles new books automatically, but two things need updating.

### Rename dead-heat config
In `config.py`: `KALSHI_NO_DEADHEAT_BOOKS` → `NO_DEADHEAT_BOOKS`, add `"polymarket"`.

In `edge.py`: update the reference from `config.KALSHI_NO_DEADHEAT_BOOKS` to `config.NO_DEADHEAT_BOOKS`. This is the only code change needed in edge.py — the rest of the logic (de-vig, consensus, best-book selection, ask-based pricing) already handles arbitrary book names.

### Ask-based pricing for new prediction markets

The existing edge.py code checks `if book == "kalshi" and "_kalshi_ask_prob" in player:` for ask-based decimal computation. Generalize this to check for any `"_{book}_ask_prob"` key:

```python
ask_key = f"_{book}_ask_prob"
if ask_key in player:
    bettable_decimal = binary_price_to_decimal(str(player[ask_key]))
```

This handles Kalshi, Polymarket, and any future binary-contract prediction market without per-book conditionals.

Ensure `player[ask_key]` is validated as numeric and within (0, 1) before computing — skip with warning if invalid.

### Polymarket fee adjustment
When computing bettable decimal for Polymarket specifically, the ask probability should be adjusted by `POLYMARKET_FEE_RATE` to reflect actual execution cost. This can be handled in the merge step (storing adjusted ask prob) or in edge.py (applying fee at bettable decimal computation). Prefer adjusting in the merge step so the stored `_polymarket_ask_prob` already reflects the true cost.

### No changes needed
- `blend.py`: Already reads `BOOK_WEIGHTS` dynamically — adding weight entries in config is sufficient
- `devig.py`: Existing Kalshi conversion functions work for any binary 0-1 price. Optionally rename for clarity.

---

## Section 9: Workflow Integration

### What to change
Update `scripts/run_pretournament.py` and `scripts/run_preround.py` to pull and merge both new markets.

### Pattern
Each market gets its own try/except block, following the existing Kalshi pattern:

```
# Pull DG (existing)
# Pull Kalshi (existing)
# Pull Polymarket (new)
# Pull ProphetX (new)
# Calculate edges (existing — now sees more book columns)
```

### Polymarket block (in both scripts)
1. Check `config.POLYMARKET_ENABLED`
2. Try: pull outrights → merge into DG outrights → print counts
3. Except: `Warning: Polymarket unavailable ({e}), proceeding without`

### ProphetX block (in both scripts)
1. Check `config.PROPHETX_ENABLED`
2. Try: pull outrights → merge into DG outrights → print counts
3. Try: pull matchups → merge into DG matchups → print counts
4. Except: `Warning: ProphetX unavailable ({e}), proceeding without`

### Live monitoring
Update `scripts/run_live_check.py` to also pull from Polymarket/ProphetX during live rounds, if applicable. Same graceful degradation pattern.

### Order of operations
Pull all prediction markets after DG but before edge calculation. The order between prediction markets doesn't matter since each merges independently into the DG data structure.

---

## Section 10: Odds Conversion Refactoring

### What to change
Rename Kalshi-specific functions in `src/core/devig.py` to generic prediction market names.

### Renames
- `kalshi_price_to_american()` → `binary_price_to_american()` (keep old name as alias)
- `kalshi_price_to_decimal()` → `binary_price_to_decimal()` (keep old name as alias)
- `kalshi_midpoint()` → `binary_midpoint()` (keep old name as alias)

### Why aliases
The Kalshi pull code, tests, and edge calculation code all reference the old names. Keeping aliases avoids a massive rename across the codebase while making new code use the clearer names.

### ProphetX odds detection
If ProphetX returns binary prices, use the same conversion functions. If American, use existing `parse_american_odds()` and `american_to_decimal()` already in devig.py. The ProphetX client should detect and flag the format.

---

## Section 11: Testing

### Test structure
Follow existing patterns from `test_kalshi_*.py`:

**Polymarket tests:**
- `tests/test_polymarket_client.py` — API client unit tests (mock HTTP)
- `tests/test_polymarket_matching.py` — tournament matching, player extraction
- `tests/test_pull_polymarket.py` — pull flow, merge functions
- `tests/test_polymarket_edge.py` — edge calc with Polymarket as a book

**ProphetX tests:**
- `tests/test_prophetx_client.py` — API client unit tests (mock HTTP), auth flow
- `tests/test_prophetx_matching.py` — tournament matching, market classification, player extraction
- `tests/test_pull_prophetx.py` — pull flow, merge functions
- `tests/test_prophetx_edge.py` — edge calc with ProphetX as a book

**Integration tests:**
- `tests/test_prediction_market_workflow.py` — verify all 3 markets integrate in the workflow scripts

### Test helpers
Create reusable market data factories:
- `_make_polymarket_event(title, start, end, markets)` 
- `_make_polymarket_market(question, slug, outcome_prices, clob_tokens, volume)`
- `_make_prophetx_event(name, date, event_id)`
- `_make_prophetx_market(line_id, competitors, odds, market_type)`

### Mock patterns
- Polymarket: `@patch("src.pipeline.pull_polymarket.PolymarketClient")` — mock client methods
- ProphetX: `@patch("src.pipeline.pull_prophetx.ProphetXClient")` — mock client methods + auth
- Edge tests: build DG outright data with merged prediction market columns, verify edge calc handles them correctly

### Key test scenarios
1. **Happy path**: all markets return data, merge correctly, edges found
2. **Partial failure**: one market unavailable, others succeed
3. **Total failure**: all prediction markets down, DG-only pipeline works
4. **Empty results**: market returns no golf events or no player data
5. **Name resolution**: player names from different sources resolve to same canonical name
6. **Dead-heat bypass**: Polymarket edges skip DH reduction, ProphetX applies it
7. **Ask-based pricing**: verify bettable decimal uses ask (not mid) for both Polymarket and ProphetX (if binary)
8. **Auth flow** (ProphetX): token refresh, re-auth on 401, expired credentials

---

## File Summary

### New files
| File | Purpose |
|------|---------|
| `src/api/polymarket.py` | Polymarket API client |
| `src/api/prophetx.py` | ProphetX API client |
| `src/pipeline/polymarket_matching.py` | Polymarket tournament/player matching |
| `src/pipeline/prophetx_matching.py` | ProphetX tournament/player matching |
| `src/pipeline/pull_polymarket.py` | Polymarket odds pull & merge |
| `src/pipeline/pull_prophetx.py` | ProphetX odds pull & merge |
| `tests/test_polymarket_client.py` | Polymarket client tests |
| `tests/test_polymarket_matching.py` | Polymarket matching tests |
| `tests/test_pull_polymarket.py` | Polymarket pull/merge tests |
| `tests/test_polymarket_edge.py` | Polymarket edge calc tests |
| `tests/test_prophetx_client.py` | ProphetX client tests |
| `tests/test_prophetx_matching.py` | ProphetX matching tests |
| `tests/test_pull_prophetx.py` | ProphetX pull/merge tests |
| `tests/test_prophetx_edge.py` | ProphetX edge calc tests |
| `tests/test_prediction_market_workflow.py` | Integration workflow tests |

### Modified files
| File | Changes |
|------|---------|
| `config.py` | Add Polymarket/ProphetX constants, book weights, rename dead-heat set |
| `src/core/devig.py` | Rename Kalshi functions → generic, add aliases |
| `src/core/edge.py` | Generalize ask-based pricing check, update dead-heat config ref |
| `scripts/run_pretournament.py` | Add Polymarket/ProphetX pull+merge blocks |
| `scripts/run_preround.py` | Same |
| `scripts/run_live_check.py` | Same (if applicable for live monitoring) |

---

## Implementation Order

1. **Config** (Section 1) — foundation for everything
2. **Devig refactoring** (Section 10) — rename before new code references it
3. **Edge calc updates** (Section 8) — generalize dead-heat and ask-pricing
4. **Polymarket client** (Section 2) — no auth, simpler to test
5. **Polymarket matching** (Section 3) — tournament + player extraction
6. **Polymarket pull/merge** (Section 4) — wire up the pipeline
7. **ProphetX client** (Section 5) — auth adds complexity
8. **ProphetX matching** (Section 6) — adaptive market discovery
9. **ProphetX pull/merge** (Section 7) — wire up
10. **Workflow integration** (Section 9) — connect to scripts
11. **Testing** (Section 11) — tests throughout, integration tests last

Each section should be independently testable. The pipeline should work after each section is complete (graceful degradation means partially-integrated markets don't break anything).
