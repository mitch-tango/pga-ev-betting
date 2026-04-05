# Research: Polymarket & ProphetX Integration

## Part 1: Existing Codebase Patterns (Kalshi Integration)

### API Client Pattern (`src/api/kalshi.py`)

**Class structure**: `KalshiClient` with constructor pulling config via `getattr(config, ...)` with defaults. Testable via DI of `base_url` and `cache_dir`.

**Core methods**:
- `_api_call(endpoint, params)` → `{"status": "ok"|"error", "data": ...}` envelope. Retry on 429 (exponential backoff from 5s), 5xx (3s backoff), timeout (3s). Rate limit: 100ms sleep after each 200. Max 3 retries.
- `_paginated_call(endpoint, params, collection_key)` → accumulates results across cursor-based pages (200/page, max 50 pages). Partial failure returns accumulated results.
- `_cache_response(data, label, tournament_slug)` → saves to `data/raw/{slug}/{YYYY-MM-DD_HHMM}/{label}.json`
- Public: `get_golf_events(series_ticker)`, `get_event_markets(event_ticker)`, `get_market(ticker)`, `get_orderbook(ticker)`

### Tournament Matching (`src/pipeline/kalshi_matching.py`)

**Two-pass strategy**:
1. Date-based: event expiration within `[start, end + 1 day]`
2. Fuzzy name: SequenceMatcher ≥0.7 threshold after stripping PGA prefixes/suffixes

**Safety**: `_is_pga_event()` checks title for PGA indicators to reject LIV/European Tour.

**Multi-series**: `match_all_series()` iterates market types, returns sparse dict of matched tickers. Graceful per-series failure.

**Player name extraction**:
- Outrights: tries subtitle first (often just player name), then regex patterns (`Will {name} win...`, `{name} to win...`)
- H2H: regex for `{name} vs. {name}` and `Will {name} beat {name}...`
- `_clean_name()`: strip, remove trailing `?`, NFC normalize unicode

**Name resolution**: `resolve_kalshi_player()` → delegates to `resolve_player(name, source="kalshi")` for canonical DG name lookup.

### Odds Pull & Merge (`src/pipeline/pull_kalshi.py`)

**`pull_kalshi_outrights()`** returns `{"win": [...], "t10": [...], "t20": [...]}` where each entry is `{player_name, kalshi_mid_prob, kalshi_ask_prob, open_interest}`.

Filtering chain: name extraction → price parsing → midpoint computation → OI ≥ 100 → spread ≤ $0.05 → player resolution.

**`pull_kalshi_matchups()`** returns `[{p1_name, p2_name, p1_prob, p2_prob, p1_oi, p2_oi}]`. P2 is complement of P1 (NO side).

**Price normalization**: `_normalize_price()` handles both 0.06 (decimal) and 6 (cents) formats.

**`merge_kalshi_into_outrights()`**: builds lookup by lowercase name, mutates DG data in-place. Adds `"kalshi"` (American odds from midpoint) and `"_kalshi_ask_prob"` (float for edge calc).

**`merge_kalshi_into_matchups()`**: order-independent matching via frozenset of names. Adds `odds["kalshi"] = {"p1": american, "p2": american}`.

### Edge Calculation Integration (`src/core/edge.py`)

- Kalshi detected as a book automatically (string odds starting with +/-)
- De-vigged alongside traditional books
- **Ask-based pricing**: for Kalshi, uses `_kalshi_ask_prob` for bettable decimal (actual cost to buy)
- **Dead-heat bypass**: `if book in config.KALSHI_NO_DEADHEAT_BOOKS` → skip DH adjustment
- **Matchup consensus**: Kalshi excluded from book consensus (prediction market), but included for best-edge selection

### Book Consensus (`src/core/blend.py`)

`build_book_consensus()` reads `BOOK_WEIGHTS[market_type]` dict. Unknown books default to weight 1. Market type routing: win → "win", make_cut → "make_cut", t5/t10/t20 → "placement".

### Config (`config.py`)

```
KALSHI_BASE_URL, KALSHI_RATE_LIMIT_DELAY (0.1s), KALSHI_MIN_OPEN_INTEREST (100),
KALSHI_MAX_SPREAD (0.05), KALSHI_SERIES_TICKERS (dict of market→ticker)
BOOK_WEIGHTS: win (kalshi:2), placement (kalshi:1), make_cut (no kalshi)
KALSHI_NO_DEADHEAT_BOOKS = {"kalshi"}
```

### Workflow Integration (`scripts/run_pretournament.py`)

Entire Kalshi block in try/except. Pull → merge → print counts. If fail, `Warning: Kalshi unavailable, proceeding with DG-only`. TODO comments at lines 287-289 for Polymarket.

### Data Structures

**Outright record** (post-merge): `{player_name, dg_id, datagolf: {...}, draftkings: "+400", kalshi: "+355", _kalshi_ask_prob: 0.24}`

**Matchup record** (post-merge): `{p1_player_name, p2_player_name, odds: {datagolf: {p1, p2}, kalshi: {p1, p2}}}`

### Testing Patterns

Framework: pytest + unittest.mock. Files: `test_kalshi_client.py`, `test_kalshi_matching.py`, `test_pull_kalshi.py`, `test_kalshi_edge.py`, `test_kalshi_workflow.py`, `test_kalshi_degradation.py`.

Helpers: `_make_market()` factory for test data. Mock setup: `@patch("src.pipeline.pull_kalshi.KalshiClient")` → configure mock return values. Integration tests inspect source code for import/call ordering.

---

## Part 2: Polymarket API Details

### Architecture
- **Gamma API** (`gamma-api.polymarket.com`): Event/market discovery. No auth required.
- **CLOB API** (`clob.polymarket.com`): Pricing, orderbook. No auth for reads.

### Event Discovery

**Key endpoints**:
- `GET /events?tag_id={golf_tag}&active=true&closed=false&limit=100` — discover golf events
- `GET /markets?sports_market_types=winner&tag_id={golf_tag}` — filter by market type
- `GET /sports` — get golf tag ID and series info
- `GET /sports/market-types` — valid type strings (winner, top-5, top-10, top-20)

**Pagination**: limit/offset (not cursor). `?limit=50&offset=0`, `?limit=50&offset=50`, etc.

### Token ID Flow
```
/sports → tag_id → /events?tag_id=X → event.markets[] → market.clobTokenIds → [YES_token, NO_token]
```

Each player in a multi-outcome event (e.g., tournament winner) gets their own Market with its own `clobTokenIds` pair.

### Pricing Endpoints (CLOB)

| Endpoint | Returns |
|----------|---------|
| `GET /price?token_id=X&side=BUY` | Best ask price |
| `GET /midpoint?token_id=X` | Mid price |
| `GET /spread?token_id=X` | Bid-ask spread |
| `GET /book?token_id=X` | Full orderbook (bids[], asks[]) |
| `GET /books` | Batch orderbook |
| `GET /midpoints` | Batch midpoints |
| `GET /prices` | Batch prices |

**Batch methods** accept arrays of token_ids for efficient multi-player queries.

### Event Response Structure
```json
{
  "id": 12345,
  "slug": "2026-valero-texas-open-winner",
  "title": "PGA Tour: Valero Texas Open Winner",
  "startDate": "2026-04-02T...",
  "endDate": "2026-04-05T...",
  "active": true,
  "liquidity": 50000,
  "volume": 169500,
  "markets": [...]
}
```

### Market Response Structure
```json
{
  "id": 67890,
  "question": "Will Scottie Scheffler win the 2026 Valero Texas Open?",
  "slug": "2026-valero-texas-open-winner-scottie-scheffler",
  "outcomes": ["Yes", "No"],
  "outcomePrices": ["0.15", "0.85"],
  "clobTokenIds": ["token_yes", "token_no"],
  "volume": 5000,
  "liquidity": 3000,
  "marketType": "winner",
  "active": true
}
```

### Rate Limits
- General: 4,000 req/10s (Gamma), 9,000 req/10s (CLOB)
- Events endpoint: 500 req/10s
- Market data (book/price/midpoint): 1,500 req/10s
- Batch endpoints: 500 req/10s

### Golf Market Coverage (Confirmed Active)

109 active golf markets. Confirmed types:
- **Tournament Winner** — multi-outcome, 100+ players
- **Top 5** — per-player binary
- **Top 10** — per-player binary
- **Top 20** — per-player binary, "including ties" (full payout)
- **Novelty/Props** — e.g., "Will Tiger play in Masters?"

**Not offered**: Head-to-head matchups, make/miss cut, round-by-round, FRL.

**Liquidity**: Golf markets have relatively thin liquidity vs political markets. Individual contracts: $0-$46 per contract typical. Top players have better depth.

**Resolution**: "including ties" means **full payout on ties** — no dead-heat reduction. Same as Kalshi.

Sources: [Gamma API Docs](https://docs.polymarket.com/developers/gamma-markets-api/overview), [CLOB Docs](https://docs.polymarket.com/developers/CLOB/introduction), [Rate Limits](https://docs.polymarket.com/api-reference/rate-limits), [Sports API](https://docs.polymarket.com/api-reference/sports/get-sports-metadata-information)

---

## Part 3: ProphetX API Details

### Architecture
- **Affiliate API** — market data access (read-oriented), Swagger at `partner-docs.prophetx.co`
- **Market Maker API** — core trading
- Auth required for all endpoints

### Authentication
1. `POST /api/v1/auth/login` with email/password → `{accessToken, refreshToken}`
2. Access token: 1-hour expiry. Refresh token: 30-day validity.
3. `POST /api/v1/auth/extend-session` with Bearer refreshToken
4. All requests: `Authorization: Bearer {accessToken}`

### Key Endpoints

| Endpoint | Purpose |
|----------|---------|
| `get_sport_events` | List events for a tournament |
| `get_multiple_markets` | Get markets for event IDs |
| Market listing (v1/v2/v3) | Multiple versions of market listing |

### Market Structure
- `line_id` — critical identifier for pricing/trading
- Market types: `moneyline`, `spread`, `total`
- SportEvent sub_type: `"outrights"` for tournament winners
- Winning status includes `draw` and `push`

### Golf Coverage (Confirmed)
- **Head-to-Head Matchups** — confirmed (e.g., "Kevin Yu vs Thorbjorn Olesen")
- **Make Cut** — referenced in reviews
- **Outrights** — supported via sub_type enum
- **Traditional odds format** (American) — not binary contracts

**Not confirmed**: Top-5, Top-10, Top-20 positional finish markets.

### Key Limitations
- Documentation is self-admittedly "limited and incomplete"
- Swagger spec loads from external `doc.json` (harder to scrape)
- May require business/affiliate relationship for API access
- Geocomply integration required for US access
- Rate limits not documented

Sources: [ProphetX Docs](https://docs.prophetx.co/), [Affiliate Swagger](https://partner-docs.prophetx.co/swagger/affiliate/index.html), [ProphetX Enums](https://medium.com/@ProphetXServiceAPI/prophetx-service-api-meaning-of-enums-6060fbc2398b)

---

## Part 4: Odds Conversion & Dead-Heat Analysis

### Binary Contract → American Odds
- `p < 0.50`: American = `+{round((1-p)/p * 100)}`
- `p > 0.50`: American = `-{round(p/(1-p) * 100)}`
- `p = 0.50`: `+100`

### Midpoint Best Practices
- Tight spread (≤$0.10): midpoint is reliable fair value
- Wide spread (>$0.10): prefer last trade price or volume-weighted average
- For edge detection: real edge = |model_prob - midpoint| - (spread/2)

### Dead-Heat: Both Polymarket and ProphetX
- **Polymarket**: Confirmed "including ties" → full $1.00 payout on ties. No dead-heat reduction. Same as Kalshi.
- **ProphetX**: Uses traditional American odds format. Dead-heat rules likely follow sportsbook convention for positional finishes. For H2H matchups, `draw`/`push` status returns stake.

### Structural Implication
Prediction market Top-N prices should be higher than equivalent sportsbook odds (after DH adjustment) because they pay full on ties. This is already modeled in the Kalshi integration via `KALSHI_NO_DEADHEAT_BOOKS`.

---

## Part 5: Integration Recommendations

### Polymarket
- **Markets**: win, t5, t10, t20 (NOT matchups, NOT make_cut)
- **Pricing**: Use CLOB batch midpoint endpoint for efficiency
- **Filtering**: Filter by volume/liquidity (golf markets can be thin)
- **Event discovery**: Use Gamma `/events` with golf tag_id + `/sports` for tag discovery
- **Player extraction**: Parse `question` field ("Will {name} win...?") or `slug` field
- **Dead-heat**: Add to `KALSHI_NO_DEADHEAT_BOOKS` set (binary contracts, full payout on ties)
- **Book weight**: Start at weight 1 for all markets (liquidity is thinner than Kalshi)

### ProphetX
- **Markets**: H2H matchups, make_cut, outrights (NOT confirmed for t5/t10/t20)
- **Pricing**: Traditional American odds from API (no binary conversion needed)
- **Auth**: Requires email/password login → JWT token management
- **Event discovery**: `get_sport_events` → `get_multiple_markets`
- **Player extraction**: Extract from competitor info in market response
- **Dead-heat**: ProphetX uses traditional odds → apply normal dead-heat rules (do NOT add to no-deadheat set)
- **Book weight**: Start at weight 1 (liquidity unknown, API docs incomplete)
- **Caution**: API access may require affiliate/partner relationship. Verify before building full integration.
