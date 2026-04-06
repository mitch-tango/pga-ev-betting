# Section 2: Supabase Data Layer

## Implementation Status: COMPLETE

## Deviations from Plan

- **Defensive pnl handling**: `get_weekly_pnl` uses `b["pnl"] or 0` to handle NULL pnl on settled bets (schema allows nullable pnl).
- **Deterministic ordering**: `get_current_tournament` adds `.order("start_date", desc=True)` before `.limit(1)` to handle overlapping tournament windows.
- **Date filter assertions**: Tests now verify exact `.lte()` / `.gte()` arguments, not just return values — ensures date math is correct.
- **Test structure**: Tests use inline mock clients rather than conftest.py fixtures (more explicit for data-layer unit tests). Conftest fixtures reserved for page-level tests in section-03.
- **20 tests total** (3 client + 17 queries) all passing.

## Overview

This section implements the dashboard's database connection and query layer: a Supabase client singleton using Streamlit-native patterns, and a query module with cached functions for fetching tournament, bet, and P&L data. These modules live in `dashboard/lib/` and are consumed by the Active Bets page (section 03) and any future dashboard pages.

**Important:** The dashboard does NOT import from the existing `src/db/supabase_client.py`. That module uses `python-dotenv` and module-level globals. The dashboard instead uses `st.cache_resource`, `st.secrets`, and returns plain Python data (list of dicts, single dict, or scalar). However, the existing module serves as the authoritative reference for query logic and table schemas.

## Dependencies

- **Section 01 (Scaffolding)** must be complete: the `dashboard/lib/` directory, `__init__.py`, and `requirements.txt` (with `supabase>=2.28.0` and `streamlit>=1.40.0`) must exist.

## Files to Create

| File | Purpose |
|------|---------|
| `dashboard/lib/supabase_client.py` | Connection singleton |
| `dashboard/lib/queries.py` | All database queries with caching |
| `dashboard/tests/test_supabase_client.py` | Client connection tests |
| `dashboard/tests/test_queries.py` | Query function tests |

## Database Schema Reference

The queries target two tables. Here are the relevant columns:

**`tournaments`** table:
- `id` (UUID, PK)
- `tournament_name` (TEXT)
- `dg_event_id` (TEXT)
- `season` (INTEGER)
- `start_date` (DATE)
- `purse` (BIGINT)
- `is_signature` (BOOLEAN)
- `is_no_cut` (BOOLEAN)
- `putting_surface` (TEXT)
- `created_at` (TIMESTAMPTZ)

**`bets`** table:
- `id` (UUID, PK)
- `tournament_id` (UUID, FK to tournaments)
- `market_type` (TEXT)
- `player_name` (TEXT)
- `opponent_name` (TEXT, nullable)
- `book` (TEXT)
- `bet_timestamp` (TIMESTAMPTZ, DEFAULT NOW())
- `odds_at_bet_decimal` (REAL)
- `odds_at_bet_american` (TEXT)
- `implied_prob_at_bet` (REAL)
- `your_prob` (REAL)
- `edge` (REAL)
- `stake` (REAL)
- `clv` (REAL, nullable)
- `outcome` (TEXT, nullable -- NULL means unsettled)
- `pnl` (REAL, nullable)
- `payout` (REAL, nullable)

## Tests (Write First)

### `dashboard/tests/test_supabase_client.py`

```python
# Test: get_client raises clear error when SUPABASE_URL missing from secrets
# Test: get_client raises clear error when SUPABASE_KEY missing from secrets
# Test: get_client returns a Supabase Client instance when secrets are configured
```

All three tests should mock `st.secrets` as a dict-like object. The first two should verify that a meaningful error message (not a raw KeyError) is raised when credentials are absent. The third should mock `create_client` to avoid hitting a real Supabase instance and verify the return type.

### `dashboard/tests/test_queries.py`

Tests use a `mock_supabase_client` fixture (defined in `conftest.py` from section 01) that patches `get_client()` to return a mock whose `.table().select().eq().execute()` chain returns fixture data.

```python
# --- get_current_tournament ---
# Test: returns tournament dict when a tournament is active (start_date within window)
# Test: returns None during off-week (no tournament in date range)
# Test: handles Wednesday before tournament starts (start_date = tomorrow) -- should return the tournament
# Test: handles Monday after tournament ends (start_date + 4 < today) -- should return None
# Test: selects explicit columns, not "*"

# --- get_active_bets ---
# Test: returns list of dicts for open bets (outcome IS NULL)
# Test: filters by tournament_id when provided
# Test: returns empty list when no open bets exist
# Test: returned dicts contain all required display columns
#       (player_name, market_type, book, odds_at_bet_american, odds_at_bet_decimal, stake, edge, clv)
# Test: selects explicit columns, not "*"

# --- get_weekly_pnl ---
# Test: computes settled_pnl as sum of pnl for settled bets
# Test: computes unsettled_stake as sum of stake for open bets
# Test: computes net_position as settled_pnl - unsettled_stake
# Test: handles tournament with zero settled bets (all open)
# Test: handles tournament with zero open bets (all settled)

# --- error handling ---
# Test: query functions raise exceptions on Supabase failure (NOT return empty defaults)
# Test: successful results are cacheable (return serializable data -- dicts/lists, not ORM objects)
```

**Testing the explicit-column-select constraint:** For `get_current_tournament` and `get_active_bets`, assert that the mock's `.select()` was called with a string argument that does NOT equal `"*"`. This ensures queries specify explicit column lists.

**Testing date logic for `get_current_tournament`:** The function computes date boundaries and passes them to Supabase filters. Tests should freeze today's date (e.g., via `unittest.mock.patch` on the date source) and verify the correct filter values are passed to the mock client's `.gte()` and `.lte()` calls, or verify the return value against fixture data for various date scenarios.

**Testing error propagation:** Mock the Supabase client to raise an exception on `.execute()`. Verify the exception propagates up -- the query functions must NOT catch exceptions and return empty defaults, because Streamlit's `@st.cache_data` would cache that empty result for the full TTL.

## Implementation Details

### Connection: `dashboard/lib/supabase_client.py`

```python
import streamlit as st
from supabase import create_client, Client


@st.cache_resource
def get_client() -> Client:
    """Create and cache a Supabase client using Streamlit secrets.

    Uses the anon key (not service key) -- sufficient for read-only SELECTs.
    The client is cached for the lifetime of the Streamlit server process.
    Raises a clear error if secrets are not configured.
    """
```

Implementation notes:
- Access `st.secrets["SUPABASE_URL"]` and `st.secrets["SUPABASE_KEY"]` inside a try/except block. On `KeyError`, raise a `RuntimeError` with a message explaining that the user needs to configure `.streamlit/secrets.toml` (local) or the Secrets panel (Streamlit Cloud). Include the expected TOML format in the error message.
- Call `create_client(url, key)` and return the `Client`.
- The `@st.cache_resource` decorator ensures one client per server process lifetime (infinite TTL).

### Query Module: `dashboard/lib/queries.py`

Every function returns plain Python data. Each is decorated with `@st.cache_data(ttl=300)` for active/live data (5-minute TTL).

#### `get_current_tournament`

```python
@st.cache_data(ttl=300)
def get_current_tournament() -> dict | None:
    """Fetch the current week's tournament.

    Query: tournaments where start_date <= today + 1 day AND start_date + 4 days >= today.
    This covers Thu-Sun tournaments with a 1-day buffer for Wednesday arrivals.
    Returns None if no active tournament (off-week).
    """
```

Implementation notes:
- Compute `today` from `datetime.date.today()`.
- The query filters use: `start_date <= today + timedelta(days=1)` (tournament has started or starts tomorrow) AND `start_date >= today - timedelta(days=4)` (tournament hasn't ended more than 4 days ago). This range covers the full Thu-Sun window with buffer.
- Supabase filter chain: `.select("id, tournament_name, start_date, purse, is_signature, is_no_cut, putting_surface, dg_event_id, season").lte("start_date", ...).gte("start_date", ...).limit(1).execute()`
- Return `result.data[0]` if data exists, else `None`.

#### `get_active_bets`

```python
@st.cache_data(ttl=300)
def get_active_bets(tournament_id: str | None = None) -> list[dict]:
    """Fetch all bets with outcome IS NULL.

    Optionally filtered by tournament_id.
    Returns list of bet dicts with all columns needed for display.
    """
```

Implementation notes:
- Explicit column select: `"id, tournament_id, market_type, player_name, opponent_name, book, bet_timestamp, odds_at_bet_decimal, odds_at_bet_american, implied_prob_at_bet, your_prob, edge, stake, clv"`
- Filter: `.is_("outcome", "null")` -- this is the Supabase Python client's way to filter `IS NULL`.
- If `tournament_id` is provided, add `.eq("tournament_id", tournament_id)`.
- Order by `bet_timestamp` descending (newest first) for default display order.
- Return `result.data` (list of dicts, possibly empty).

#### `get_weekly_pnl`

```python
@st.cache_data(ttl=300)
def get_weekly_pnl(tournament_id: str) -> dict:
    """Calculate P&L summary for a tournament.

    Returns dict with:
      settled_pnl: sum of pnl where outcome IS NOT NULL
      unsettled_stake: sum of stake where outcome IS NULL
      net_position: settled_pnl - unsettled_stake
    """
```

Implementation notes:
- This requires two queries (or one query with all bets for the tournament, then Python aggregation). The simpler approach: fetch all bets for the tournament with explicit columns `"id, stake, pnl, outcome"`, then split in Python.
- Settled bets: those where `outcome` is not None. Sum their `pnl` values.
- Unsettled bets: those where `outcome` is None. Sum their `stake` values.
- Net position = `settled_pnl - unsettled_stake` (worst-case scenario if all open bets lose).
- Return a dict: `{"settled_pnl": float, "unsettled_stake": float, "net_position": float}`.
- Handle edge cases: if no settled bets, `settled_pnl = 0.0`. If no unsettled bets, `unsettled_stake = 0.0`.

### Error Handling Pattern

Query functions raise exceptions on failure. They do NOT wrap Supabase errors in try/except and return safe defaults. The reason: `@st.cache_data` would cache an empty result for the full TTL (5 minutes), showing "no bets" even when bets exist. The page layer (section 03) is responsible for wrapping calls in try/except, displaying `st.error()` banners, and preventing error states from being cached.

### Secrets Configuration

**Local development** -- create `dashboard/.streamlit/secrets.toml` (this file is gitignored per section 05):

```toml
SUPABASE_URL = "https://xxxx.supabase.co"
SUPABASE_KEY = "your-anon-key"
```

**Streamlit Cloud** -- paste the same TOML content into the app's Secrets panel in the Streamlit Cloud dashboard settings.

The anon key is sufficient for all dashboard queries (read-only SELECTs). Do not use the service key.

### Caching Strategy

| Function | Decorator | TTL | Rationale |
|----------|-----------|-----|-----------|
| `get_client` | `@st.cache_resource` | Infinite | One connection per server process |
| `get_current_tournament` | `@st.cache_data` | 300s (5 min) | Tournament context rarely changes mid-week |
| `get_active_bets` | `@st.cache_data` | 300s (5 min) | Bets placed/settled during rounds |
| `get_weekly_pnl` | `@st.cache_data` | 300s (5 min) | Updates as bets settle |

The sidebar "Refresh Data" button (from section 01) calls `st.cache_data.clear()` for manual invalidation when the 5-minute TTL feels stale during live monitoring.
