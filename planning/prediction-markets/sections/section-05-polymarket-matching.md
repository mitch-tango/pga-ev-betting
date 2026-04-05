# Section 05: Polymarket Tournament Matching & Player Extraction

## Overview

This section implements `src/pipeline/polymarket_matching.py`, which matches Polymarket prediction market events to DataGolf (DG) tournaments and extracts player names from Polymarket market data. It follows the same architectural pattern as the existing Kalshi matching module (`src/pipeline/kalshi_matching.py`) but adapts for Polymarket-specific data structures: date range overlap instead of single-point expiration matching, slug-based name extraction, and a higher fuzzy match threshold (0.85 vs Kalshi's 0.70).

## Dependencies

- **Section 01 (config)**: `POLYMARKET_MARKET_TYPES` mapping
- **Section 04 (polymarket client)**: `PolymarketClient` with `get_golf_events(market_type_filter=...)`
- **Existing code**: `src/normalize/players.py` provides `resolve_player(name, source=...)`

## File to Create

`src/pipeline/polymarket_matching.py`

## Tests First

Create `tests/test_polymarket_matching.py`. All API interactions mocked; these are pure matching/extraction logic tests.

### Test stubs

```python
"""Tests for Polymarket tournament matching and player name extraction."""

class TestTournamentMatching:
    # Test: match_tournament finds event by UTC date range overlap
    # Test: match_tournament rejects event outside date range
    # Test: match_tournament matches by fuzzy name (≥0.85 token similarity)
    # Test: match_tournament rejects similar but wrong events ("US Open" vs "US Women's Open")
    # Test: match_tournament excludes non-PGA tours (LIV, DPWT, LPGA, Korn Ferry)
    # Test: match_tournament handles timezone differences (UTC vs local dates)

class TestMatchAllMarketTypes:
    # Test: returns matched events for win, t10, t20
    # Test: returns sparse dict when some types have no events
    # Test: handles complete miss (no golf events) → empty dict

class TestPlayerNameExtraction:
    # Test: extracts from slug ("scottie-scheffler" → "Scottie Scheffler")
    # Test: extracts from question regex ("Will X win...")
    # Test: handles special characters (McIlroy, Åberg, DeChambeau)
    # Test: applies NFC unicode normalization
    # Test: returns None on unparseable market

class TestPlayerNameResolution:
    # Test: resolve_polymarket_player delegates to resolve_player with source="polymarket"
```

## Implementation Details

### Module structure

Public functions:
1. **`match_tournament(events, tournament_name, tournament_start, tournament_end)`** — returns matched event dict
2. **`match_all_market_types(client, tournament_name, start, end)`** — iterates market types, returns dict of matched events
3. **`extract_player_name(market)`** — extracts player name from a Polymarket market dict
4. **`resolve_polymarket_player(name, auto_create=False)`** — delegates to `resolve_player`

Internal helpers: `_is_pga_event()`, `_clean_name()`, title-strip patterns.

### Tournament Matching

**Pass 1 — Date range overlap**: Parse `startDate`/`endDate` as UTC-aware datetimes. Two ranges overlap when `event_start <= tournament_end` AND `event_end >= tournament_start`. Convert to dates for comparison to avoid timezone edge cases.

**Pass 2 — Fuzzy name fallback**: Strip common prefixes/suffixes:
- Strip `"PGA Tour: "` prefix
- Strip `" Winner"`, `" Top 10"`, `" Top 20"` suffixes

Compute token-based similarity. Use `rapidfuzz.fuzz.token_set_ratio` if available, else fall back to `difflib.SequenceMatcher`. Threshold: **0.85** (higher than Kalshi's 0.70).

**PGA safety check**: Check for PGA indicators ("pga", "masters", "u.s. open", etc.). Explicitly **exclude** events containing "LIV", "DPWT", "LPGA", or "Korn Ferry" (case-insensitive).

**Return value**: Full event dict (contains nested `markets[]` needed downstream), not a ticker string like Kalshi.

### match_all_market_types

Iterates `config.POLYMARKET_MARKET_TYPES`. For each type: call `client.get_golf_events(market_type_filter=filter_value)` → `match_tournament()`. Returns sparse dict. Try/except per type so one failure doesn't block others.

### Player Name Extraction

Priority order:
1. **Slug-based** (most reliable): Strip event prefix from slug, convert hyphens to spaces, title-case
2. **Question regex**: `r"^Will\s+(.+?)\s+(?:win|finish)\b"` and similar patterns
3. **Clean and normalize**: Strip, remove trailing `?`, NFC normalize

Returns `None` with warning log if no name extracted.

### resolve_polymarket_player

Thin wrapper: `resolve_player(name, source="polymarket", auto_create=auto_create)`.

### Design Notes

- Polymarket events contain nested `markets[]` (one per player), so all player data comes from a single event fetch
- Slug-based extraction is more reliable than regex for Polymarket
- The 0.85 threshold prevents false positives on similar tournament names
- All date parsing handles both `"2026-04-10T00:00:00Z"` and `"2026-04-10"` formats

### Reference Pattern

Follow `src/pipeline/kalshi_matching.py` structure: module-level compiled regex patterns, `_is_pga_event()` helper, `_clean_name()` helper, logging via `logging.getLogger(__name__)`, type hints, docstrings.

## Verification Checklist

1. Tournament matching uses UTC date range overlap (not ±1 day point matching)
2. Fuzzy threshold is 0.85 (not 0.70)
3. Non-PGA tours explicitly excluded
4. Player name extraction handles slug and regex paths
5. Unicode normalization applied
6. `uv run pytest tests/test_polymarket_matching.py` passes
