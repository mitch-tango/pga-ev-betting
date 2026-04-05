# Kalshi Integration — Complete Specification

## Overview

Integrate the Kalshi prediction market as a fully bettable book in the PGA +EV betting system. Kalshi offers binary contracts on PGA golf outcomes (winner, top 10, top 20, head-to-head matchups) where prices directly represent implied probabilities. The user has funds on Kalshi and wants it treated as a first-class sportsbook alongside the existing DataGolf-sourced books (pinnacle, draftkings, fanduel, bovada, betonline, betcris).

## System Context

The PGA +EV betting system:
- Pulls odds from DataGolf API, which aggregates sportsbook lines
- De-vigs book odds via power method (win) or independent method (placement)
- Builds weighted book consensus using BOOK_WEIGHTS in config.py
- Blends book consensus with DataGolf model probabilities (BLEND_WEIGHTS)
- Calculates edges and sizes bets via quarter-Kelly criterion
- Displays candidates via CLI and Discord bot (/scan, /place, /status, /live, /player)
- Stores everything in Supabase (candidate_bets, bets, odds_snapshots, book_rules tables)

## Kalshi API

- **Base URL:** `https://api.elections.kalshi.com/trade-api/v2`
- **Authentication:** Not required for market data reads (public endpoints)
- **Rate limit:** 20 req/sec (basic tier)
- **Python SDK:** `kalshi-py` on PyPI

### Golf Series Tickers

| Series Ticker | Market Type | System Market | In Consensus? |
|---|---|---|---|
| `KXPGATOUR` | Tournament Winner | `win` | Yes (sharp, 2x weight) |
| `KXPGATOP10` | Top 10 Finish | `t10` | Yes (1x weight) |
| `KXPGATOP20` | Top 20 Finish | `t20` | Yes (1x weight) |
| `KXPGAH2H` | Head-to-Head | `tournament_matchup` | No (bettable outlet only, 100% DG model) |

### Endpoints

- `GET /events?series_ticker={ticker}&status=open` — discover tournament events
- `GET /markets?event_ticker={event_ticker}` — all player contracts within an event
- `GET /markets/{ticker}` — single market with current prices
- `GET /markets/{ticker}/orderbook` — full orderbook

### Price Format

- Dollar strings: `"0.06"` = 6% implied probability
- Binary YES/NO contracts, $1 settlement
- Key fields: `yes_bid_dollars`, `yes_ask_dollars`, `no_bid_dollars`, `no_ask_dollars`
- **Use ask price** as implied probability (conservative; represents cost to buy)
- Already vig-free — no devigging needed

## Requirements

### R1. Kalshi API Client

New `KalshiClient` class in `src/api/kalshi.py` following the `DataGolfClient` pattern:
- Rate limiting (respect 20 req/sec)
- Retries with exponential backoff (3 attempts)
- Response caching to `data/raw/`
- Methods: fetch events by series ticker, fetch markets by event, fetch orderbook
- Graceful degradation: if API is down or no golf events, log warning and return empty data

### R2. Tournament Matching

Match Kalshi events to the current DataGolf tournament automatically:
- Pull all open events for golf series tickers
- Match by tournament date range to the current DG tournament week
- No manual mapping required; date-based matching is the primary strategy

### R3. Player Name Matching

- Kalshi player names in contract titles must be normalized to DataGolf canonical names
- Leverage existing name-matching infrastructure in `src/parsers/`
- Handle edge cases (nicknames, suffixes like Jr./III, international name variants)

### R4. Liquidity Threshold

- **Minimum 100 contracts open interest** per player contract
- Below this threshold, exclude the player's Kalshi price from consensus and edge calculation
- Configurable in config.py for future tuning

### R5. Pipeline Integration

New `src/pipeline/pull_kalshi.py` module:
- Fetch and cache Kalshi odds for all available golf markets
- Integrate into `scripts/run_pretournament.py` and `scripts/run_preround.py`
- Same polling cadence as DataGolf — only during pipeline runs, no independent polling
- Pipeline continues if Kalshi data is unavailable

### R6. Book Consensus Integration

- Add `"kalshi"` to `BOOK_WEIGHTS` in `config.py`:
  - **Win/Make-Cut markets:** 2x weight (sharp) — prediction markets are efficient
  - **Placement markets (T10/T20):** 1x weight (consistent with other placement books)
- Kalshi probabilities bypass devigging (already vig-free ask prices)
- Feed into `build_book_consensus()` in `src/core/blend.py`

### R7. Edge Calculation

- Kalshi participates as a bettable book in `src/core/edge.py`
- Can be recommended as "Best Book" when it offers the highest edge
- For H2H matchups: Kalshi is a bettable outlet only — matchup probabilities remain 100% DG model
- Edge = blended_prob - kalshi_ask_implied_prob

### R8. Settlement Rules

- Add Kalshi to `book_rules` table in `schema.sql`
- Simple settlement: $1 win / $0 lose
- Withdrawals: void (refund)
- No dead heats, no pushes
- Pattern: `('kalshi', '{market}', 'void', 'void', NULL)` for all markets

### R9. Config Updates

- `KALSHI_BASE_URL` — API base URL
- `KALSHI_SERIES_TICKERS` — mapping of market types to series tickers
- `KALSHI_MIN_OPEN_INTEREST` — 100 (liquidity threshold)
- `KALSHI_RATE_LIMIT` — 20 req/sec
- Add kalshi to `BOOK_WEIGHTS` dicts
- Add kalshi settlement rules to schema

### R10. Display / Discord Bot

- Kalshi appears in all relevant bot commands:
  - `/scan` — as a possible "Best Book" recommendation
  - `/place` — log bets placed on Kalshi
  - `/status` — by-book ROI breakdown
- No special display treatment — it's just another book column
- CLI odds screen also shows Kalshi

### R11. Graceful Degradation

- If Kalshi API is unreachable: log warning, proceed without Kalshi data
- If no golf events found: log info, proceed without Kalshi data
- If a player has no Kalshi contract: excluded from Kalshi consensus (other books still apply)
- If liquidity below threshold: treat as no data for that player

### R12. Future Polymarket Integration (TODO)

- Add code comments/TODOs in relevant integration points for future Polymarket support
- No stub modules or class skeletons
- Key notes for future: outrights and top-N only (no matchups), keyword-based discovery, public API
