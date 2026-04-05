# Prediction Market Integration: Polymarket & ProphetX

## Overview

Integrate Polymarket and ProphetX prediction market APIs into the PGA EV betting system as additional "books" for edge detection, following the existing Kalshi integration pattern.

## Background

The system currently pulls odds from DG-aggregated sportsbooks and Kalshi (prediction market). Adding Polymarket and ProphetX increases market coverage and improves edge detection by providing more price signals — particularly valuable when prediction markets disagree with traditional books.

## Markets to Integrate

### Polymarket
- **API**: Gamma API (event discovery) + CLOB API (prices/orderbook)
- **Base URLs**: `gamma-api.polymarket.com`, `clob.polymarket.com`
- **Auth**: No authentication required for public read endpoints
- **Golf coverage**: Win, Top 10, Top 20 outrights — does NOT offer matchups
- **Rate limits**: 4,000 req/10s general, 500/10s events, 1,500/10s market data
- **Price format**: Decimal 0-1 (same as Kalshi)

### ProphetX
- **API**: REST API with affiliate/partner endpoints
- **Base URL**: `cash.api.prophetx.co`
- **Auth**: API key required
- **Golf coverage**: PGA tournaments supported; specific market types TBD via research
- **Rate limits**: Not publicly documented
- **Docs**: Swagger at `partner-docs.prophetx.co`

## Requirements

### Functional
1. Pull outrights (win, T10, T20) from Polymarket for current PGA tournaments
2. Pull available golf markets from ProphetX for current PGA tournaments
3. Merge both into the existing DG outrights/matchups data structure as additional book columns
4. Include both in book consensus and edge calculation
5. Treat as prediction markets: binary contracts with no dead-heat reduction
6. Configurable book weights per market type (win, placement, make_cut)
7. Configurable quality filters (min open interest, max spread) per market

### Non-Functional
8. Graceful degradation — if either market is unavailable, the DG pipeline continues unaffected
9. Rate limiting with retry/backoff matching the Kalshi client pattern
10. Response caching to `data/raw/{tournament_slug}/{timestamp}/`
11. Comprehensive test coverage following existing test patterns

## Integration Pattern (from Kalshi)

Each market follows the same 8-step pattern:
1. **Config constants** — API URLs, rate limits, filters, series tickers, book weights
2. **API client** — HTTP wrapper with retry/rate-limit, pagination, caching
3. **Tournament matching** — Map platform events to DG tournaments (date + fuzzy name)
4. **Player name extraction** — Parse player names from contract/market titles
5. **Name resolution** — Map raw names to DG canonical player names
6. **Odds pull** — Fetch markets, filter by quality, compute mid/ask probabilities
7. **Odds merge** — Inject as new book columns into existing DG data structures
8. **Workflow integration** — Add to run_pretournament.py and run_preround.py with try/except

## Key Files to Modify or Create

### New files (per market)
- `src/api/polymarket.py` / `src/api/prophetx.py` — API clients
- `src/pipeline/polymarket_matching.py` / `src/pipeline/prophetx_matching.py` — Tournament + player matching
- `src/pipeline/pull_polymarket.py` / `src/pipeline/pull_prophetx.py` — Odds pull + merge
- `tests/test_polymarket_*.py` / `tests/test_prophetx_*.py` — Tests

### Existing files to modify
- `config.py` — Add constants, book weights, dead-heat bypass sets
- `src/core/devig.py` — Odds conversion helpers if needed
- `src/core/blend.py` — Book consensus already reads from BOOK_WEIGHTS (should work automatically)
- `src/core/edge.py` — Dead-heat bypass set already configurable (should work automatically)
- `scripts/run_pretournament.py` — Add pull+merge calls (TODO placeholders exist)
- `scripts/run_preround.py` — Same
- `scripts/run_live_check.py` — Add live edge support if applicable

## Open Questions
- What specific ProphetX golf markets are available? (needs API exploration)
- Does ProphetX use binary contract pricing like Kalshi/Polymarket, or traditional odds?
- Should both markets share a common base class or remain independent clients?
- What book weights should Polymarket and ProphetX receive relative to Kalshi?
