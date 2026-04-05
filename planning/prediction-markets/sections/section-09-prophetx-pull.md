# Section 09: ProphetX Odds Pull & Merge

## Overview

This section implements `src/pipeline/pull_prophetx.py`, which pulls ProphetX outright and matchup odds and merges them into the DG data structure. Key difference from Polymarket: ProphetX may return odds in either American or binary format, requiring format detection logic.

## Dependencies

- **section-01-config**: `PROPHETX_ENABLED`, `PROPHETX_MIN_OPEN_INTEREST`, `PROPHETX_MAX_SPREAD`
- **section-02-devig-refactor**: `binary_price_to_american()`, `binary_price_to_decimal()`, `parse_american_odds()`
- **section-07-prophetx-client**: `ProphetXClient`
- **section-08-prophetx-matching**: `match_tournament()`, `classify_markets()`, `extract_player_name_outright()`, `extract_player_names_matchup()`, `resolve_prophetx_player()`

## File to Create

`src/pipeline/pull_prophetx.py`

## Tests First

Create `tests/test_pull_prophetx.py`.

```python
# ---- pull_prophetx_outrights ----
# Test: returns {"win": [...], "t10": [...], "t20": [...]} format
# Test: detects American odds as int (400, -150) not just string ("+400")
# Test: detects American odds as string ("+400", "-150")
# Test: detects binary contract prices (0.55) and converts
# Test: handles mixed formats gracefully
# Test: filters by quality thresholds (OI, spread)
# Test: resolves to DG canonical names
# Test: returns empty dict when no tournament match
# Test: caches raw responses

# ---- pull_prophetx_matchups ----
# Test: returns [{p1_name, p2_name, p1_prob, p2_prob}] format
# Test: extracts both player names and odds per side
# Test: handles American odds for matchups

# ---- merge_prophetx_into_outrights ----
# Test: adds "prophetx" American odds string
# Test: adds "_prophetx_ask_prob" when binary format detected
# Test: no "_prophetx_ask_prob" when American format (American IS bettable price)
# Test: merge skips unmatched DG players
# Test: case-insensitive name matching

# ---- merge_prophetx_into_matchups ----
# Test: frozenset name matching (order-independent)
# Test: adds odds["prophetx"] = {"p1": ..., "p2": ...}
```

## Implementation Details

### Module Structure

Four public functions mirroring `pull_kalshi.py`:

1. `pull_prophetx_outrights()` — pull outrights (win, t10, t20)
2. `pull_prophetx_matchups()` — pull H2H matchups
3. `merge_prophetx_into_outrights()` — inject into DG outrights
4. `merge_prophetx_into_matchups()` — inject into DG matchups

### Odds Format Detection

Internal helper `_detect_odds_format(markets)`:
- If odds value is int/float with `abs(value) > 1` (e.g., `400`, `-150`) → **American**
- If odds value is string matching `r"^[+-]\d+"` (e.g., `"+400"`) → **American**
- If odds value is float in `(0, 1)` exclusive → **binary**
- Store detected format as `"american"` or `"binary"` flag

Must handle both `int` and `str` types — APIs frequently return American odds as integers.

### `pull_prophetx_outrights(tournament_name, start, end, tournament_slug=None)`

Returns `{"win": [...], "t10": [...], "t20": [...]}`.

Flow:
1. Create `ProphetXClient()` (lazy auth on first call)
2. `get_golf_events()` → `match_tournament()` → return empty if no match
3. `get_markets_for_events([event_id])` → `classify_markets()`
4. For each outright type:
   - Detect odds format
   - For each market/competitor:
     - Extract player name via `extract_player_name_outright()`
     - Read odds value
     - **American format**: store American string directly, compute implied prob via `parse_american_odds()`
     - **Binary format**: compute midpoint, convert to American via `binary_price_to_american()`, store ask prob
     - Filter by OI ≥ `PROPHETX_MIN_OPEN_INTEREST`, spread ≤ `PROPHETX_MAX_SPREAD`
     - Resolve name via `resolve_prophetx_player()`
     - Append player dict
5. Cache raw responses
6. Return results

### Player Dict Format

**American format** (no ask prob):
```python
{"player_name": "...", "prophetx_american": "+400", "prophetx_mid_prob": 0.20, "odds_format": "american"}
```

**Binary format** (with ask prob):
```python
{"player_name": "...", "prophetx_mid_prob": 0.22, "prophetx_ask_prob": 0.25, "odds_format": "binary"}
```

### `pull_prophetx_matchups(tournament_name, start, end, tournament_slug=None)`

Returns `[{p1_name, p2_name, p1_prob, p2_prob}]`.

Flow: extract "matchup" markets from classified data, extract both names, read odds per side, convert to probs, filter, resolve, append.

### `merge_prophetx_into_outrights(dg_outrights, prophetx_outrights)`

Same pattern as Kalshi merge with format-aware logic:

- Build case-insensitive lookup
- For each DG player, find matching ProphetX entry
- Add `"prophetx"` key with American odds string
- Add `"_prophetx_ask_prob"` **only when binary format** — American odds already represent bettable price, no separate ask prob needed
- This distinction is critical: edge.py checks for `_{book}_ask_prob` to determine pricing path

### `merge_prophetx_into_matchups(dg_matchups, prophetx_matchups)`

Frozenset-based order-independent matching. Align ProphetX player order to DG's p1/p2. Set `matchup["odds"]["prophetx"] = {"p1": american, "p2": american}`.

### Key Imports

```python
from src.api.prophetx import ProphetXClient
from src.core.devig import binary_price_to_american, binary_midpoint, parse_american_odds
from src.pipeline.prophetx_matching import (
    match_tournament, classify_markets,
    extract_player_name_outright, extract_player_names_matchup,
    resolve_prophetx_player,
)
import config
```

### Key Design Decisions

1. **Format-aware merge**: Unlike Kalshi/Polymarket (always binary), ProphetX `_ask_prob` is conditional on format. Edge.py handles this automatically via the generalized `_{book}_ask_prob` check.
2. **Graceful degradation**: All functions return empty results on failure, never raise.
3. **Make-cut stretch goal**: If classify_markets discovers make_cut, include under `"make_cut"` key.

## Implementation Notes

### Files Created
- `src/pipeline/pull_prophetx.py` — 4 public functions + format detection helpers
- `tests/test_pull_prophetx.py` — 23 tests

### Deviations from Plan
- **binary_midpoint**: Used `binary_midpoint()` from devig module (as specified in Key Imports) with string args, falling back to odds_val when bid/ask unavailable
- **make_cut stretch goal**: Skipped — only win/t10/t20 implemented
- **OI/spread filters**: Skip filter when field absent (rather than defaulting to 0) to avoid silently passing/filtering all competitors
- **_classify_odds_value**: Simplified to unified int/float branch with bool exclusion (avoids dead code from separate int check)
- **Caching**: Caches processed results (matches Polymarket pattern), not raw API responses
- **Return type**: Sparse returns (`{}` on empty) rather than always returning all three keys

## Verification Checklist

1. Format detection handles int, float, and string odds types ✓
2. `_prophetx_ask_prob` only set for binary format ✓
3. American format stored directly without binary conversion ✓
4. Matchup merge uses frozenset matching ✓
5. All exceptions caught, empty results returned ✓
6. `uv run pytest tests/test_pull_prophetx.py` — 23 passed ✓
