# Section 06: Polymarket Odds Pull & Merge

## Overview

This section implements `src/pipeline/pull_polymarket.py`, which pulls outright odds (win, top-10, top-20) from Polymarket and merges them into the DG data structure. Follows the same pattern as `src/pipeline/pull_kalshi.py`. Polymarket does NOT offer H2H matchups for golf.

## Dependencies

- **section-01-config**: `POLYMARKET_FEE_RATE`, `POLYMARKET_MIN_VOLUME`, `POLYMARKET_MAX_SPREAD_ABS`, `POLYMARKET_MAX_SPREAD_REL`, `POLYMARKET_MARKET_TYPES`
- **section-02-devig-refactor**: `binary_price_to_american()`, `binary_midpoint()`
- **section-04-polymarket-client**: `PolymarketClient` class
- **section-05-polymarket-matching**: `match_all_market_types()`, `extract_player_name()`, `resolve_polymarket_player()`

## File to Create

`src/pipeline/pull_polymarket.py`

## Tests First

Create `tests/test_pull_polymarket.py`. All tests mock `PolymarketClient`, matching functions, and name resolution.

### Test Stubs

```python
"""Tests for Polymarket pipeline pull and merge (outrights only)."""

def _make_polymarket_market(question, slug, outcomes, clob_token_ids,
                            outcome_prices, volume, market_type="winner"):
    """Helper to build a Polymarket market dict."""
    return {
        "question": question,
        "slug": slug,
        "outcomes": outcomes,
        "clobTokenIds": clob_token_ids,
        "outcomePrices": outcome_prices,
        "volume": volume,
        "marketType": market_type,
    }

# ---- pull_polymarket_outrights ----
# Test: returns {"win": [...], "t10": [...], "t20": [...]}
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

# ---- merge_polymarket_into_outrights ----
# Test: merge adds "polymarket" American odds key to matched DG players
# Test: merge adds "_polymarket_ask_prob" with fee-adjusted float
# Test: merge skips DG players not found in Polymarket data
# Test: merge handles case-insensitive name matching
# Test: merge uses binary_price_to_american() for odds conversion
# Test: existing book columns (draftkings, fanduel, kalshi) not modified by merge

# ---- No matchup pull ----
# Test: confirm no pull_polymarket_matchups function exists
```

## Implementation Details

### `pull_polymarket_outrights(tournament_name, tournament_start, tournament_end, tournament_slug=None)`

Returns `{"win": [...], "t10": [...], "t20": [...]}`.

**Flow:**

1. Create `PolymarketClient()`
2. Call `match_all_market_types(client, tournament_name, start, end)` → `{"win": event, "t10": event, ...}`
3. For each matched event and its nested `markets[]`:
   a. **Identify YES token**: Use `outcomes` array to find the "Yes" label index, then use `clobTokenIds[that_index]`. Do NOT assume index 0. Log warning and skip market if YES token cannot be identified.
   b. Batch call `client.get_books(token_ids)` (internally chunked into batches of 50)
   c. For each market/player:
      - Extract best bid (highest bid price) and best ask (lowest ask price)
      - **Empty orderbook handling**: if no bids → bid=0; if no asks → ask=1.0; if BOTH empty → skip player
      - Compute midpoint: `(bid + ask) / 2`
      - **Relative spread filter**: `spread <= max(POLYMARKET_MAX_SPREAD_ABS, POLYMARKET_MAX_SPREAD_REL * midpoint)`
      - **Volume filter**: skip if `volume < POLYMARKET_MIN_VOLUME`
      - Extract player name via `extract_player_name(market)`
      - Resolve to DG canonical name via `resolve_polymarket_player()`
      - **Fee-adjusted ask**: `adjusted_ask = ask + POLYMARKET_FEE_RATE`
      - Append: `{"player_name": canonical_name, "polymarket_mid_prob": mid, "polymarket_ask_prob": adjusted_ask, "volume": volume}`
4. Cache raw responses
5. Return results dict

**Error handling**: try/except per market type. On failure, log warning and continue with empty list.

### `merge_polymarket_into_outrights(dg_outrights, polymarket_outrights)`

Same pattern as `merge_kalshi_into_outrights()`.

**DG key mapping**: `{"win": "win", "top_10": "t10", "top_20": "t20"}`

**Merge logic**:
1. Build lookup from Polymarket data by lowercase player name
2. For each DG player, find matching Polymarket entry
3. Add `"polymarket"` key with American odds string (from midpoint via `binary_price_to_american()`)
4. Add `"_polymarket_ask_prob"` key with fee-adjusted ask float
5. Mutate `dg_outrights` in place, return it

The `_polymarket_ask_prob` already includes the fee adjustment, so edge.py uses it directly.

### No matchup pull

Polymarket does not offer H2H golf matchups. Do not create a `pull_polymarket_matchups` function.

### Module Structure

```python
"""Polymarket prediction market odds pull. Win, T10, T20 outrights only."""
from __future__ import annotations
import logging
from src.api.polymarket import PolymarketClient
from src.core.devig import binary_price_to_american
from src.pipeline.polymarket_matching import (
    match_all_market_types, extract_player_name, resolve_polymarket_player,
)
import config

logger = logging.getLogger(__name__)
_DG_TO_POLYMARKET_MARKET = {"win": "win", "top_10": "t10", "top_20": "t20"}
```

Key helpers: `_identify_yes_token(market)`, `_best_bid(orderbook)`, `_best_ask(orderbook)`.

### Key Differences from Kalshi Pull

| Aspect | Kalshi | Polymarket |
|--------|--------|------------|
| Price source | `yes_bid`/`yes_ask` fields | Orderbook via `get_books()` |
| Token ID | N/A (single contract) | YES token from `outcomes` array |
| Spread filter | Absolute | Relative |
| Volume/OI field | `open_interest` | `volume` |
| Fee adjustment | None | `ask + POLYMARKET_FEE_RATE` |
| Matchups | Supported | Not supported |

## Deviations from Original Plan

1. **One-sided orderbooks skipped**: Plan said "if no bids → bid=0; if no asks → ask=1.0". Implementation skips markets with only one side, since the resulting midpoints are not market-informed and would mislead edge calculations.
2. **Fee-adjusted ask clamped**: `min(1.0, ask + fee)` prevents invalid probabilities >1.0.
3. **Spread filter always applied**: No bypass for one-sided books (moot since they're skipped).

## Files Created/Modified

- `src/pipeline/pull_polymarket.py` (created)
- `tests/test_pull_polymarket.py` (created)

## Verification Checklist

1. YES token identified by outcome label, not index
2. One-sided orderbooks skipped (require both bids and asks)
3. Relative spread filter applied
4. Fee rate added to ask prob, clamped to ≤1.0
5. Merge adds both `"polymarket"` and `"_polymarket_ask_prob"` keys
6. No `pull_polymarket_matchups` function exists
7. 18 tests passing: `uv run pytest tests/test_pull_polymarket.py`
