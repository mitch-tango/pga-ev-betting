# Research Findings

## Codebase Analysis

### Current Architecture
- **Odds Source**: DataGolf API (`src/api/datagolf.py`) — aggregates sportsbook lines from pinnacle, draftkings, fanduel, bovada, betonline, betcris
- **API Client Pattern**: `DataGolfClient` class with 1.5s rate limiting, 3 retries, response caching to `data/raw/`
- **Pipeline**: Separate modules per data type (`pull_outrights.py`, `pull_matchups.py`, `pull_closing.py`, `pull_live.py`, `pull_results.py`)
- **Orchestration**: `scripts/run_pretournament.py` (weekly) and `scripts/run_preround.py` (daily)

### Book Consensus Flow
1. `src/core/devig.py` — parses American odds, converts to decimal, removes vig via power method (win) or independent method (placement)
2. `src/core/blend.py` — `build_book_consensus()` applies `BOOK_WEIGHTS` to create weighted average per player
3. `src/core/edge.py` — calculates edges, finds best book, sizes via Kelly

### Book Weighting (config.py)
- **Win/MC**: Sharp books (pinnacle, betcris, betonline) get 2x; Retail (DK, FD, bovada) get 1x
- **Placement (T10/T20)**: All books equal weight (1x)
- **Matchups**: 100% DataGolf model (no book weighting currently)

### Blend Weights (DG vs Books)
- Win: 35% DG / 65% books
- Placement: 55% DG / 45% books
- Make Cut: 35% DG / 65% books
- Matchup: 20% DG / 80% books (100% DG if no book data)
- 3-Ball: 100% DG

### Name Matching
- Existing infrastructure in `src/parsers/` (untracked, new files)
- System normalizes player names to DG canonical format

### Database (Supabase)
- `candidate_bets` table stores `all_book_odds` as JSONB
- `bets` table stores single `book` column
- `book_rules` table defines settlement rules per book/market
- `odds_snapshots` for closing line capture

### Testing
- Tests in `tests/` directory (test_auto_settlement.py, test_blend.py, test_name_matching.py — all untracked/new)

---

## Kalshi API Research

### Golf Market Series Tickers
| Series Ticker | Market Type | Maps To System Market |
|---|---|---|
| `KXPGATOUR` | Tournament Winner | `win` |
| `KXPGATOP10` | Top 10 Finish | `t10` |
| `KXPGATOP20` | Top 20 Finish | `t20` |
| `KXPGAH2H` | Head-to-Head Matchups | `tournament_matchup` |

### API Details
- **Base URL**: `https://api.elections.kalshi.com/trade-api/v2`
- **Auth**: Market data endpoints are PUBLIC (no auth for reads)
- **Rate limit**: 20 req/sec (basic tier), 30/sec (advanced)

### Key Endpoints
- `GET /events?series_ticker=KXPGATOUR&status=open` — find tournament events
- `GET /markets?event_ticker={ticker}` — get all player contracts
- `GET /markets/{ticker}` — single market with prices
- `GET /markets/{ticker}/orderbook` — full orderbook

### Price Format
- Dollar strings: `"0.06"` = 6% implied probability = +1567 American
- Binary YES/NO contracts worth $1 at settlement
- Key fields: `yes_bid_dollars`, `yes_ask_dollars`, `no_bid_dollars`, `no_ask_dollars`
- Subpenny pricing supported ($0.001 tick on some markets)
- Already vig-free — just bid-ask spread

### SDK & Tooling
- Python SDK: `kalshi-py` on PyPI
- WebSocket available for real-time streaming
- OpenAPI spec at `https://docs.kalshi.com/openapi.yaml`

### Integration Considerations
- Kalshi prices map directly to implied probability (no devig needed)
- For edge calculation: use `yes_ask` as implied prob (cost to buy YES)
- H2H matchups exist (`KXPGAH2H`) — maps to existing matchup pipeline
- No make_cut or 3-ball markets on Kalshi
- Player names appear in contract titles — need normalization to DG canonical names

---

## Future: Polymarket (TODO)
- Outrights and top-N only (NO matchups)
- No golf-specific tag — requires keyword search for discovery
- Public API, no auth for reads
- Gamma API for discovery + CLOB API for prices
- Python SDK: `py-clob-client`
