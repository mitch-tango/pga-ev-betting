# Section 08: ProphetX Tournament Matching & Player Extraction

## Overview

This section implements `src/pipeline/prophetx_matching.py`, which handles matching ProphetX prediction market events to DataGolf tournaments and extracting player names from ProphetX market data. It follows the same pattern as `src/pipeline/kalshi_matching.py` but adapts to ProphetX's uncertain field names and includes market type classification logic.

## Dependencies

- **Section 01 (config):** ProphetX config constants
- **Section 07 (prophetx-client):** `ProphetXClient` with `get_golf_events()` and `get_markets_for_events()`
- **Existing:** `src/normalize/players.py` provides `resolve_player(name, source=...)`

## File to Create

`src/pipeline/prophetx_matching.py`

## Tests First

Create `tests/test_prophetx_matching.py`.

```python
"""Tests for ProphetX tournament matching, market classification, and player extraction."""

class TestTournamentMatching:
    # Test: matches by UTC date range overlap
    # Test: rejects event outside date range
    # Test: fuzzy name match >= 0.85 finds correct event
    # Test: tries multiple date field names (start_date, startDate, event_date)
    # Test: tries multiple title field names (name, title, event_name)
    # Test: excludes non-PGA tours (LIV, DPWT, LPGA, Korn Ferry)

class TestClassifyMarkets:
    # Test: identifies outright winner from moneyline + sub_type "outrights"
    # Test: identifies H2H matchup from moneyline with 2 competitors
    # Test: identifies make_cut from "cut" keyword in name
    # Test: discovers t10/t20 from "top 10"/"top 20" in market names
    # Test: returns sparse dict with only found types

class TestPlayerNameExtraction:
    # Test: extracts from competitor_name field
    # Test: tries multiple field names (competitor_name, participant, player)
    # Test: logs warning when no name field found, returns None
    # Test: extracts both names from H2H matchup with 2 competitors
    # Test: handles international characters (NFC normalized)
    # Test: matchup requires exactly 2 competitors

class TestPlayerNameResolution:
    # Test: resolve_prophetx_player delegates to resolve_player with source="prophetx"
```

## Implementation Details

### Module: `src/pipeline/prophetx_matching.py`

Five public functions:

1. `match_tournament(events, tournament_name, tournament_start, tournament_end) -> dict | None`
2. `classify_markets(markets) -> dict[str, list[dict]]`
3. `extract_player_name_outright(market) -> str | None`
4. `extract_player_names_matchup(market) -> tuple[str, str] | None`
5. `resolve_prophetx_player(name, auto_create=False) -> dict | None`

### Tournament Matching

**Two-pass strategy:**

Pass 1 — Date-based with range overlap:
- Try multiple date field names: `start_date`, `startDate`, `event_date`, `start` (and similarly for end dates)
- Parse all as UTC-aware datetimes, compare as dates
- Overlap formula: `event_start <= tournament_end AND event_end >= tournament_start`
- Skip events failing `_is_pga_event()` check

Pass 2 — Fuzzy name matching:
- Try multiple title fields: `name`, `title`, `event_name`, `eventName`
- Strip prefixes/suffixes before comparison
- Token-based similarity ≥ 0.85 (RapidFuzz if available, else SequenceMatcher)

**Non-PGA exclusion**: Reject events containing "liv", "dpwt", "dp world", "lpga", "korn ferry".

**Helper `_get_field(d, *field_names, default=None)`**: Try each field name, return first non-None.

### Market Type Classification

`classify_markets(markets)` groups markets by type. Returns sparse dict.

Classification rules:
- `moneyline` + `sub_type` containing `"outright"` → `"win"`
- `moneyline` with exactly 2 competitors → `"matchup"`
- Market name contains `"cut"` → `"make_cut"`
- Market name contains `"top 10"` or `"top-10"` → `"t10"`
- Market name contains `"top 20"` or `"top-20"` → `"t20"`
- Unrecognized types logged and skipped

### Player Name Extraction

**`extract_player_name_outright(market)`**:
1. Look for competitor data in: `competitor_name`, `participant`, `player`, `name` (within competitors array or directly on market)
2. If market has `competitors` list, extract from first entry
3. Apply `_clean_name()` — strip, NFC normalize
4. Return `None` with warning if no name found

**`extract_player_names_matchup(market)`**:
1. Access competitors list (try `competitors`, `participants`, `selections`)
2. Verify exactly 2 entries; return `None` if not
3. Extract names from each entry
4. Return `(player_a, player_b)` tuple

### resolve_prophetx_player

Thin wrapper: `resolve_player(name, source="prophetx", auto_create=auto_create)`.

### Shared Utilities

`_clean_name()` and `_is_pga_event()` duplicated from `kalshi_matching.py`. `_get_field()` is new for ProphetX's uncertain schema.

### Key Design Decisions

1. **Flexible field detection**: Every field access tries multiple names, handles uncertain API schema
2. **Higher fuzzy threshold (0.85)**: Prevents false matches with less-documented data
3. **Range overlap**: More robust than point matching for uncertain date formats
4. **Dynamic classification**: Markets classified after retrieval (unlike Kalshi's pre-classified series tickers)
5. **Returns event dict**: Not ticker string — downstream code needs event ID

## Deviations from Original Plan

1. **Player name extraction excludes market 'name' field from fallback**: Direct market field fallback skips the 'name' field (which is the market title) to avoid extracting market names as player names.

## Files Created/Modified

- `src/pipeline/prophetx_matching.py` (created)
- `tests/test_prophetx_matching.py` (created)

## Verification Checklist

1. Tournament matching uses date range overlap with multiple field name attempts
2. Fuzzy threshold is 0.85
3. Non-PGA tours excluded (exclusion-only, same as Polymarket)
4. Market classifier handles outright, matchup, make_cut, t10, t20
5. Player extraction tries competitors array then direct market fields
6. 18 tests passing: `uv run pytest tests/test_prophetx_matching.py`
