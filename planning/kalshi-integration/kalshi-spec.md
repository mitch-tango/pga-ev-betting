# Kalshi Prediction Market Integration

## Overview

Integrate the Kalshi prediction market API into the PGA +EV betting system as a new odds source alongside the existing DataGolf-sourced sportsbook odds (pinnacle, draftkings, fanduel, bovada, betonline, betcris).

Kalshi offers binary contracts on PGA golf outcomes where prices directly represent implied probabilities. These should be incorporated into the book consensus and edge calculation pipeline as an additional "book."

## Kalshi API Details

- **Base URL:** `https://api.elections.kalshi.com/trade-api/v2`
- **Auth:** Market data endpoints are PUBLIC (no auth needed for reads)
- **Rate limit:** 20 req/sec (basic tier)
- **Python SDK:** `kalshi-py` on PyPI

### Golf Market Series Tickers

| Series Ticker | Market Type | Maps To |
|---|---|---|
| `KXPGATOUR` | Tournament Winner | `win` |
| `KXPGATOP10` | Top 10 Finish | `t10` |
| `KXPGATOP20` | Top 20 Finish | `t20` |
| `KXPGAH2H` | Head-to-Head Matchups | `tournament_matchup` |

### Key Endpoints

- `GET /events?series_ticker=KXPGATOUR&status=open` -- find tournament events
- `GET /markets?event_ticker={ticker}` -- get all player contracts within an event
- `GET /markets/{ticker}` -- single market with current prices
- `GET /markets/{ticker}/orderbook` -- full orderbook (bids/asks)

### Price Format

- Prices are dollar strings (e.g., `"0.06"` = 6% implied probability)
- Binary contracts (YES/NO) worth $1 at settlement
- Already vig-free (no devigging needed) -- just bid-ask spread
- For edge calculation: use `yes_ask` price as implied probability (cost to buy)

## Integration Requirements

### 1. Kalshi API Client (`src/api/kalshi.py`)

New client class following the existing `DataGolfClient` pattern:
- Rate limiting (1.5s between calls or respect 20/sec limit)
- Retries with backoff
- Response caching to `data/raw/`
- Methods to fetch events, markets, and orderbooks by series ticker

### 2. Player Name Matching

Kalshi uses player names in contract titles that need to match DataGolf canonical names. There is existing name-matching infrastructure in `src/parsers/` that should be leveraged.

### 3. Pipeline Module (`src/pipeline/pull_kalshi.py`)

New pipeline module to:
- Discover the current tournament's Kalshi event by series ticker
- Pull all player contracts and prices for win, t10, t20 markets
- Pull H2H matchup contracts
- Normalize player names to DG canonical format
- Cache raw responses

### 4. Book Consensus Integration

- Add `"kalshi"` to `BOOK_WEIGHTS` in `config.py`
- Weight as sharp book (2x) -- prediction markets tend to be efficient
- Kalshi probabilities can bypass devigging (already vig-free)
- Inject into `build_book_consensus()` in `src/core/blend.py`

### 5. Edge Calculation

- Kalshi should participate as a bettable book in `src/core/edge.py`
- Edge = blended_prob - kalshi_implied_prob
- For H2H matchups: map Kalshi H2H contracts to existing matchup pipeline

### 6. Config & Schema Updates

- Add `KALSHI_SERIES_TICKERS` mapping in `config.py`
- Add kalshi to `BOOK_WEIGHTS` for win, t10, t20, tournament_matchup
- Add settlement rules for kalshi in `schema.sql`

### 7. Display

- Kalshi appears as another book column in CLI odds screen and Discord `/scan` embed
- No special display treatment needed

### 8. Workflow Integration

- Add Kalshi pulls to `scripts/run_pretournament.py` and `scripts/run_preround.py`
- Kalshi data should be pulled alongside (not instead of) DataGolf data

## Future: Polymarket Integration (TODO)

Add placeholder/TODO for future Polymarket integration:
- Outrights and top-N finishes only (NO matchups)
- Public API, no auth for reads
- Discovery is harder (no golf tag, requires keyword search)
- Gamma API (`https://gamma-api.polymarket.com`) for market discovery
- CLOB API (`https://clob.polymarket.com`) for prices
- Python SDK: `py-clob-client`
