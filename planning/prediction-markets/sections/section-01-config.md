# Section 01: Configuration & Constants

## Overview

This section adds Polymarket and ProphetX configuration constants to `config.py`, following the established Kalshi integration pattern. It is the foundation for all subsequent sections -- every other section depends on these constants being in place.

**No dependencies.** This section can be implemented first.

**Blocks:** All other sections (02 through 11).

## Files to Modify

- `config.py` -- add new constants, update existing structures
- `tests/test_config_prediction_markets.py` -- new test file

## Tests (Write First)

Create `tests/test_config_prediction_markets.py`. These tests validate the new configuration constants before any implementation code is written.

```python
"""Tests for Polymarket & ProphetX configuration constants."""

from unittest.mock import patch
import os

# --- env_flag helper ---
# Test: env_flag("VAR", "1") returns True for "1", "true", "yes", "True", "YES"
# Test: env_flag("VAR", "0") returns False for "0", "false", "no", "False", ""
# Test: bool("0") gotcha is avoided — env_flag("X", "0") returns False (not True)

# --- POLYMARKET_ENABLED ---
# Test: POLYMARKET_ENABLED defaults to True when env var unset
# Test: POLYMARKET_ENABLED is False when env var set to "0"

# --- PROPHETX_ENABLED ---
# Test: PROPHETX_ENABLED is False when email/password not set
# Test: PROPHETX_ENABLED is True when both email and password are set

# --- BOOK_WEIGHTS ---
# Test: BOOK_WEIGHTS contains "polymarket" and "prophetx" for "win" and "placement"
# Test: BOOK_WEIGHTS "make_cut" contains "prophetx" but NOT "polymarket"

# --- NO_DEADHEAT_BOOKS ---
# Test: NO_DEADHEAT_BOOKS contains "kalshi" and "polymarket" but NOT "prophetx"

# --- Polymarket constants ---
# Test: POLYMARKET_FEE_RATE is a positive float
# Test: POLYMARKET_MIN_VOLUME is a positive int
# Test: POLYMARKET_MAX_SPREAD_ABS and POLYMARKET_MAX_SPREAD_REL are positive floats
```

### Testing approach for env-dependent config

The `env_flag` helper and `POLYMARKET_ENABLED`/`PROPHETX_ENABLED` flags depend on environment variables at import time. Tests need to reload the config module with patched environment variables using `importlib.reload(config)` inside `unittest.mock.patch.dict(os.environ, ...)` blocks.

Example approach for testing `env_flag`:

- Import `env_flag` directly from config (it should be a standalone function, not just used at module scope)
- Call it with various inputs to verify correct boolean parsing
- For the module-level flags (`POLYMARKET_ENABLED`, `PROPHETX_ENABLED`), use `importlib.reload` with patched env vars

## Implementation Details

### 1. Add `env_flag` helper function

Add this near the top of `config.py`, after the imports. This utility avoids the Python gotcha where `bool("0")` evaluates to `True`.

```python
def env_flag(name: str, default: str = "0") -> bool:
    """Parse an environment variable as a boolean flag.
    
    Returns True for "1", "true", "yes" (case-insensitive).
    Returns False for everything else including "0", "false", "no", "".
    """
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")
```

### 2. Add Polymarket constants

Add a new `# --- Polymarket ---` section after the existing Kalshi section. Remove the existing TODO comment about Polymarket on line 33.

Constants to add:

| Constant | Value | Purpose |
|----------|-------|---------|
| `POLYMARKET_GAMMA_URL` | `"https://gamma-api.polymarket.com"` | Event discovery API |
| `POLYMARKET_CLOB_URL` | `"https://clob.polymarket.com"` | Pricing/orderbook API |
| `POLYMARKET_RATE_LIMIT_DELAY` | `0.1` | 100ms between calls (conservative vs 1,500 req/10s) |
| `POLYMARKET_MIN_VOLUME` | `100` | Minimum market volume to include |
| `POLYMARKET_MAX_SPREAD_ABS` | `0.10` | Absolute spread ceiling |
| `POLYMARKET_MAX_SPREAD_REL` | `0.15` | Relative spread factor |
| `POLYMARKET_FEE_RATE` | `0.002` | Taker fee applied to ask price for bettable cost |
| `POLYMARKET_GOLF_TAG_ID` | `os.getenv("POLYMARKET_GOLF_TAG_ID")` | Fallback env var for caching discovered tag ID |
| `POLYMARKET_MARKET_TYPES` | `{"win": "winner", "t10": "top-10", "t20": "top-20"}` | Maps internal keys to Polymarket filter values |
| `POLYMARKET_ENABLED` | `env_flag("POLYMARKET_ENABLED", "1")` | On by default (no auth needed) |

The spread filter logic (used later in section 06) is: `spread <= max(POLYMARKET_MAX_SPREAD_ABS, POLYMARKET_MAX_SPREAD_REL * midpoint)`. This prevents filtering out illiquid longshots while still catching wide spreads on favorites. The config just stores the two thresholds; the filter logic lives in the pull module.

### 3. Add ProphetX constants

Add a `# --- ProphetX ---` section after Polymarket.

| Constant | Value | Purpose |
|----------|-------|---------|
| `PROPHETX_BASE_URL` | `"https://cash.api.prophetx.co"` | API base URL |
| `PROPHETX_EMAIL` | `os.getenv("PROPHETX_EMAIL")` | Login credential |
| `PROPHETX_PASSWORD` | `os.getenv("PROPHETX_PASSWORD")` | Login credential |
| `PROPHETX_RATE_LIMIT_DELAY` | `0.1` | Conservative (rate limits undocumented) |
| `PROPHETX_MIN_OPEN_INTEREST` | `100` | Minimum OI threshold |
| `PROPHETX_MAX_SPREAD` | `0.05` | Max bid-ask spread |
| `PROPHETX_ENABLED` | `bool(PROPHETX_EMAIL and PROPHETX_PASSWORD)` | Auto-enabled when credentials present |

### 4. Update BOOK_WEIGHTS

Add `"polymarket"` and `"prophetx"` entries to the existing `BOOK_WEIGHTS` dict. Both start at weight 1 (conservative until validated with real data):

- **`"win"`**: add `"polymarket": 1, "prophetx": 1`
- **`"placement"`**: add `"polymarket": 1, "prophetx": 1`
- **`"make_cut"`**: add `"prophetx": 1` only. Polymarket does NOT offer make_cut markets, so it must not appear in this dict.

### 5. Rename dead-heat set

Rename the existing constant on line 134 from `KALSHI_NO_DEADHEAT_BOOKS` to `NO_DEADHEAT_BOOKS` and add Polymarket:

```python
NO_DEADHEAT_BOOKS = {"kalshi", "polymarket"}
```

ProphetX is NOT added to this set. ProphetX uses traditional odds format where dead-heat rules apply. If ProphetX later turns out to use binary contracts, it can be added then.

**Important:** This rename requires updating references in `src/core/edge.py` (covered in section 03). After this section is complete, `edge.py` will have a broken reference to `config.KALSHI_NO_DEADHEAT_BOOKS` until section 03 is implemented. To avoid this, keep the old name as an alias:

```python
NO_DEADHEAT_BOOKS = {"kalshi", "polymarket"}
KALSHI_NO_DEADHEAT_BOOKS = NO_DEADHEAT_BOOKS  # Deprecated alias — removed in section 03
```

This approach lets tests pass at each section boundary.

## Existing Code Context

The current `config.py` uses a flat module-level constants pattern with sections delimited by `# ---` comments. The new constants should follow this same style. Key reference points:

- Kalshi constants are at lines 22-33
- `BOOK_WEIGHTS` is at lines 74-91
- `KALSHI_NO_DEADHEAT_BOOKS` is at line 134

## Verification Checklist

After implementation, all of the following should be true:

1. `config.env_flag("X", "0")` returns `False` (not `True` like `bool("0")` would)
2. `config.env_flag("X", "1")` returns `True`
3. `config.POLYMARKET_ENABLED` is `True` by default
4. `config.PROPHETX_ENABLED` is `False` when no credentials in env
5. `"polymarket"` appears in `config.BOOK_WEIGHTS["win"]` and `config.BOOK_WEIGHTS["placement"]`
6. `"polymarket"` does NOT appear in `config.BOOK_WEIGHTS["make_cut"]`
7. `"prophetx"` appears in `config.BOOK_WEIGHTS["win"]`, `"placement"`, and `"make_cut"`
8. `config.NO_DEADHEAT_BOOKS` contains `{"kalshi", "polymarket"}`
9. `"prophetx"` is NOT in `config.NO_DEADHEAT_BOOKS`
10. All Polymarket URL, rate limit, volume, spread, and fee constants are present and correctly typed
11. All ProphetX URL, credential, rate limit, OI, and spread constants are present
12. Existing tests (especially `tests/test_kalshi_edge.py`) still pass -- the deprecated alias for `KALSHI_NO_DEADHEAT_BOOKS` prevents breakage
