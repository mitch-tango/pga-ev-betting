# Synthesized Spec: Polymarket & ProphetX Prediction Market Integration

## Goal

Add Polymarket and ProphetX as additional prediction market "books" in the PGA EV betting pipeline, alongside the existing Kalshi integration. This expands price signal coverage for edge detection — more independent price sources improve consensus accuracy and increase the chance of finding exploitable edges.

## Scope

### Polymarket
- **Markets**: Win, Top 10, Top 20 outrights (NOT matchups, NOT make_cut, NOT T5)
- **API**: Gamma API for event discovery (no auth), CLOB API for pricing (no auth for reads)
- **Event discovery**: Use golf tag_id from `/sports` endpoint, filter `/events` by tag + active status
- **Token flow**: event → market → clobTokenIds → CLOB pricing (batch midpoint/book endpoints)
- **Pagination**: limit/offset (not cursor-based like Kalshi)
- **Rate limits**: 4,000 req/10s (Gamma), 1,500 req/10s (CLOB market data), 500 req/10s (events, batch)
- **Pricing**: Binary contracts 0-1, same as Kalshi. Use midpoint for consensus, ask for bettable edge.
- **Dead-heat**: Binary contracts pay full on ties ("including ties" in resolution rules). Add to no-deadheat set.
- **Filtering**: Match Kalshi thresholds — OI >= 100, spread <= $0.05
- **Book weight**: Start at 1 for all market types (conservative until validated)

### ProphetX
- **Markets**: Discover dynamically — confirmed: outrights, H2H matchups, make_cut. Integrate whatever they offer.
- **API**: REST at `cash.api.prophetx.co`. Requires email/password auth → JWT token (1hr expiry, 30-day refresh).
- **Credentials**: User has credentials. Store as env vars following project pattern.
- **Odds format**: Unknown — may be American (traditional) or binary (prediction market). Client must detect/handle both.
- **Event discovery**: `get_sport_events` → `get_multiple_markets` with event IDs
- **Rate limits**: Not documented. Use conservative delay (match Kalshi's 100ms).
- **Dead-heat**: If American odds format, apply normal dead-heat rules (NOT in no-deadheat set). If binary contracts, add to no-deadheat set.
- **Book weight**: Start at 1 for all market types

## Architecture Decisions

### Client Architecture
Each market gets its own self-contained client class (no shared base class). Rationale:
- Matches existing Kalshi pattern
- APIs are sufficiently different (auth, pagination, endpoints) that a base class would be leaky
- Easier to test independently
- Each client has its own retry/rate-limit/cache logic

### Integration Pattern (replicate for both)
1. Config constants in `config.py`
2. API client in `src/api/{market}.py`
3. Tournament matching + player extraction in `src/pipeline/{market}_matching.py`
4. Odds pull + merge in `src/pipeline/pull_{market}.py`
5. Odds conversion helpers in `src/core/devig.py` (if needed beyond Kalshi's existing functions)
6. Workflow integration in `scripts/run_pretournament.py` and `scripts/run_preround.py`
7. Graceful degradation — try/except wrapping, never blocks DG pipeline

### What Changes vs. Stays the Same
- **Book consensus** (`blend.py`): No code changes — already reads `BOOK_WEIGHTS` dynamically. Just add weights.
- **Edge calculation** (`edge.py`): Minimal changes — add new books to `KALSHI_NO_DEADHEAT_BOOKS` (rename to `NO_DEADHEAT_BOOKS`). Ask-based pricing pattern already works for any prediction market.
- **Devig** (`devig.py`): Kalshi conversion functions work for any binary 0-1 pricing. May rename for generality.
- **Config**: Add new constants, book weights, dead-heat config for both markets.

## Constraints
- Graceful degradation is mandatory — pipeline must work with 0, 1, 2, or 3 prediction markets
- ProphetX API docs are incomplete — implementation may need adaptive discovery
- Golf liquidity on both platforms is thinner than traditional books — filter aggressively
- No new dependencies beyond `requests` (already in project)
