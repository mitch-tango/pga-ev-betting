# Section 3: Active Bets Page

## Overview

This section implements the primary dashboard page at `dashboard/pages/active_bets.py` along with a supporting aggregation helpers module at `dashboard/lib/aggregations.py`. The page is what users see when they open the app during a tournament week. It displays tournament context, exposure summary by market type, a filterable/sortable table of all open bets with edge and CLV color coding, and a weekly P&L summary.

**Depends on:**
- **section-01-scaffolding** — `dashboard/app.py` (entrypoint with navigation), `dashboard/lib/theme.py` (color constants, formatting helpers), `dashboard/tests/conftest.py` (test fixtures)
- **section-02-data-layer** — `dashboard/lib/queries.py` (provides `get_current_tournament()`, `get_active_bets()`, `get_weekly_pnl()`), `dashboard/lib/supabase_client.py`
- **section-04-charts** — `dashboard/lib/charts.py` (provides `build_exposure_by_market()`)

**Blocks:** section-05-deployment

---

## Files to Create

| File | Purpose |
|------|---------|
| `dashboard/lib/aggregations.py` | Pure-Python aggregation helpers (no Streamlit dependency) |
| `dashboard/pages/active_bets.py` | Streamlit page module for Active Bets |
| `dashboard/tests/test_active_bets_page.py` | Page-level tests using `AppTest` and mocks |
| `dashboard/tests/test_aggregations.py` | Pure logic unit tests for aggregation helpers |

---

## Tests First

### `dashboard/tests/test_aggregations.py`

Pure logic tests for the aggregation helpers. These have no Streamlit dependency and test plain Python functions.

```python
"""Tests for dashboard/lib/aggregations.py — pure aggregation logic."""

import pytest


# --- group_by_market_type ---

# Test: group_by_market_type groups bets correctly with multiple market types
# Input: list of bet dicts with varying market_type values
# Expected: dict keyed by market_type, each value a list of matching bets

# Test: group_by_market_type returns empty dict for empty bet list


# --- compute_exposure ---

# Test: compute_exposure returns correct count, stake sum, potential return per group
# Input: {"outright": [bet1, bet2], "matchup": [bet3]}
# Expected: dict per group with keys "count", "total_stake", "potential_return"
# potential_return = sum(stake * odds_at_bet_decimal) for each bet

# Test: compute_exposure handles empty bet list — returns empty dict

# Test: compute_exposure totals row includes sum across all market types


# --- compute_weekly_pnl ---

# Test: compute_weekly_pnl sums settled and unsettled correctly
# Input: list with mix of settled (outcome not None, has pnl) and unsettled bets
# Expected: {"settled_pnl": sum of pnl, "unsettled_stake": sum of unsettled stakes, "net_position": settled - unsettled}

# Test: compute_weekly_pnl net position = settled_pnl - unsettled_stake

# Test: compute_weekly_pnl with all bets open (zero settled)

# Test: compute_weekly_pnl with all bets settled (zero unsettled)
```

### `dashboard/tests/test_active_bets_page.py`

Page-level tests. Uses `streamlit.testing.v1.AppTest` for smoke tests and mocked query functions for logic tests. Where `AppTest` is too heavyweight, test the rendering logic by calling helper functions directly.

```python
"""Tests for dashboard/pages/active_bets.py — page rendering and display logic."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta


# ===== 3.1 Tournament Header =====

# Test: displays empty-state message when get_current_tournament returns None
# Mock get_current_tournament to return None
# Assert page shows "No active tournament this week" message
# Assert bet table and exposure cards are NOT rendered

# Test: does not render bet table or cards when no active tournament
# (complement to above — verify st.dataframe / st.metric not called)

# Test: displays tournament name as heading when tournament is active
# Mock get_current_tournament to return sample_tournament fixture
# Assert tournament name appears in page output

# Test: formats date range correctly (e.g., "Apr 3 – Apr 6, 2026")
# Verify format_date_range("2026-04-03") produces "Apr 3 – Apr 6, 2026"

# Test: displays "Est. Round 1" when today == start_date
# Test: displays "Est. Round 2" when today == start_date + 1
# Test: omits round estimate when today < start_date
# Test: omits round estimate when today > start_date + 4


# ===== 3.2 Exposure Summary =====

# Test: aggregates bet count by market type correctly
# Test: aggregates total stake by market type correctly
# Test: computes potential return as stake * odds_at_bet_decimal per market type
# Test: shows totals across all market types
# Test: handles single market type (no breakdown needed, just totals)
# Test: disclaimer text present for potential return ("Assumes no dead heats")


# ===== 3.3 Active Bet Table =====

# Test: table includes all required columns
#   (Player, Opponent, Market, Book, Odds, Stake, Edge, CLV, Potential Return)
# Test: opponent column blank for non-matchup markets
# Test: filtering by market type reduces displayed rows
# Test: filtering by book reduces displayed rows
# Test: default sort is newest first by bet_timestamp
# Test: multiselect filters populated from actual data values (not hardcoded)


# ===== 3.4 Edge & CLV Display =====

# Test: positive edge values display with COLOR_POSITIVE
# Test: negative edge values display with COLOR_NEGATIVE
# Test: null CLV displays as dash or COLOR_NEUTRAL
# Test: CLV formatted as percentage with sign ("+3.2%", "-1.1%")


# ===== 3.5 Weekly P&L =====

# Test: settled P&L displayed with color coding (positive green, negative gray)
# Test: open exposure displayed as neutral metric
# Test: net position computed and displayed correctly
# Test: handles zero settled P&L (all bets still open)
```

---

## Implementation Details

### `dashboard/lib/aggregations.py`

A pure-Python module with no Streamlit imports. This keeps aggregation logic testable without mocking Streamlit. All functions operate on lists of bet dicts (as returned by `queries.get_active_bets()`).

```python
"""Pure aggregation helpers for bet data. No Streamlit dependency."""
from __future__ import annotations
from datetime import date, timedelta


def group_by_market_type(bets: list[dict]) -> dict[str, list[dict]]:
    """Group a list of bet dicts by their 'market_type' field.

    Returns dict mapping market_type string to list of matching bets.
    """


def compute_exposure(bets: list[dict]) -> dict[str, dict]:
    """Compute exposure metrics grouped by market type.

    Returns dict keyed by market_type with values:
        {"count": int, "total_stake": float, "potential_return": float}

    Also includes a "__total__" key with aggregate across all types.
    potential_return = sum(stake * odds_at_bet_decimal) for each bet.
    """


def compute_weekly_pnl(all_tournament_bets: list[dict]) -> dict:
    """Compute weekly P&L summary from all bets for a tournament.

    Args:
        all_tournament_bets: All bets for the tournament (settled and unsettled).

    Returns dict:
        settled_pnl: sum of 'pnl' for bets where outcome is not None
        unsettled_stake: sum of 'stake' for bets where outcome is None
        net_position: settled_pnl - unsettled_stake
    """


def estimate_round(start_date_str: str, today: date | None = None) -> int | None:
    """Estimate current tournament round from start date.

    Returns 1-4 if today is within the tournament window (start_date to start_date + 3).
    Returns None if today is before start_date or more than 4 days after.

    Args:
        start_date_str: ISO format date string (e.g., "2026-04-03")
        today: Override for testing. Defaults to date.today().
    """


def format_date_range(start_date_str: str) -> str:
    """Format a tournament date range as 'Apr 3 – Apr 6, 2026'.

    Assumes 4-day tournament (Thu-Sun). Uses en-dash between dates.
    """
```

### `dashboard/pages/active_bets.py`

The Streamlit page module. This file is registered with `st.navigation` via `app.py` (from section-01). It follows this top-to-bottom layout:

**Page structure (pseudocode flow):**

```python
"""Active Bets page — primary tournament monitoring view."""
import streamlit as st
import pandas as pd

from lib.queries import get_current_tournament, get_active_bets, get_weekly_pnl
from lib.aggregations import (
    group_by_market_type, compute_exposure, compute_weekly_pnl,
    estimate_round, format_date_range,
)
from lib.theme import (
    format_american_odds, format_currency, format_percentage,
    color_value, COLOR_POSITIVE, COLOR_NEGATIVE, COLOR_NEUTRAL,
)
from lib.charts import build_exposure_by_market


def render():
    """Main render function for the Active Bets page."""
    # 1. Tournament header
    # 2. If no tournament, show empty state and return early
    # 3. Fetch active bets
    # 4. Exposure summary cards
    # 5. Exposure chart (if 2+ market types)
    # 6. Filter controls + active bet table
    # 7. Weekly P&L summary
    # 8. Last-updated timestamp


render()
```

#### 3.1 Tournament Header

- Call `get_current_tournament()` wrapped in try/except. On error, show `st.error()` and return.
- If returns `None`, display `st.info("No active tournament this week. Check back on Thursday!")` and `st.stop()` to halt further rendering.
- When active: `st.title(tournament["tournament_name"])`, then a subtitle line with the formatted date range and round estimate.
- Round estimate uses `estimate_round(tournament["start_date"])`. If it returns a value, show "Est. Round X" as a caption. If None, omit entirely.
- The tournament dict has fields: `id`, `tournament_name`, `start_date`, `dg_event_id`, `season`.

#### 3.2 Exposure Summary Cards

- Call `get_active_bets(tournament_id=tournament["id"])` wrapped in try/except.
- Run `compute_exposure(bets)` to get per-market-type and total metrics.
- Render using `st.columns()` — one column per market type plus one for totals.
- Each column contains `st.metric()` calls for Count, Total Stake (formatted as currency), and Potential Return (formatted as currency).
- Below the cards, a small `st.caption("Potential return assumes no dead heats.")` disclaimer.
- If `get_active_bets` returns empty, show `st.info("No active bets for this tournament.")` and still render the P&L section (there may be settled bets).

#### 3.3 Active Bet Table

- Build a `pandas.DataFrame` from the active bets list.
- Add a computed "Potential Return" column: `stake * odds_at_bet_decimal`.
- Format display columns:
  - `opponent_name`: fill NaN with empty string (non-matchup markets have no opponent)
  - `odds_at_bet_american`: display as-is (already a string like "+850")
  - `stake` and Potential Return: format as currency
  - `edge` and `clv`: format as signed percentage
- **Filter controls** above the table using `st.columns()`:
  - `st.multiselect("Market Type", options=sorted(df["market_type"].unique()))` — no default selection means show all
  - `st.multiselect("Book", options=sorted(df["book"].unique()))` — same pattern
  - Apply filters: if selections are non-empty, filter the DataFrame
- **Display** with `st.dataframe()`:
  - Use `column_config` to set display names, format numbers
  - Default sort by `bet_timestamp` descending (sort DataFrame before passing)
  - Use `st.column_config.NumberColumn` for Stake, Potential Return with `format="$%.2f"`
  - Edge and CLV columns: apply color styling using `df.style.applymap()` with the `color_value()` helper to set cell text color
  - Hide the raw `bet_timestamp`, `odds_at_bet_decimal`, and other non-display columns using `column_order` parameter
  - Set `hide_index=True`

**Table column ordering:** Player, Opponent, Market, Book, Odds, Stake, Edge, CLV, Potential Return.

#### 3.4 Edge & CLV Color Coding

Integrated into the table (3.3). Use Pandas Styler or `st.dataframe` `column_config` to color-code cells:

- Positive edge/CLV: text color = `COLOR_POSITIVE` (green)
- Negative edge/CLV: text color = `COLOR_NEGATIVE` (muted warm gray, NOT red, NOT pure black)
- Null CLV: display as "—" (em-dash), gray text (`COLOR_NEUTRAL`)

Since `st.dataframe` has limited cell-level color support, the recommended approach is to use Pandas Styler (`df.style`) with a custom function that applies CSS color based on the value sign, then pass the styled DataFrame to `st.dataframe`. Alternatively, format the Edge and CLV columns as styled HTML strings if using `st.markdown` for the table.

If Pandas Styler proves too complex with `st.dataframe`, an acceptable fallback is to format the values as strings with their signs ("+5.2%", "-1.1%") and rely on the sign to communicate direction, without color.

#### 3.5 Weekly P&L Summary

- Call `get_weekly_pnl(tournament["id"])` wrapped in try/except. This returns `{"settled_pnl", "unsettled_stake", "net_position"}`.
- Render as a horizontal row of `st.metric()` in `st.columns(3)`:
  - **Settled P&L**: value formatted as currency with sign, colored via `st.metric`'s `delta` parameter or custom styling
  - **Open Exposure**: unsettled stake as currency (neutral, no color)
  - **Net Position**: settled_pnl - open_exposure, colored green/gray
- Add `st.caption()` with last-updated timestamp: display the current time as "Last updated: HH:MM AM/PM" so the user knows data freshness relative to the 5-minute cache TTL.

---

## Database Schema Reference

The `bets` table columns relevant to this page (from the existing `src/db/supabase_client.py` `insert_bet` function):

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `tournament_id` | UUID | FK to tournaments |
| `market_type` | text | "outright", "matchup", "placement", etc. |
| `player_name` | text | Golfer name |
| `opponent_name` | text | Nullable, for matchups only |
| `book` | text | "DraftKings", "FanDuel", "Kalshi", etc. |
| `odds_at_bet_decimal` | float | Decimal odds at time of bet |
| `odds_at_bet_american` | text | American odds string ("+850") |
| `stake` | float | Dollar amount wagered |
| `edge` | float | Edge percentage as decimal (0.05 = 5%) |
| `clv` | float | Closing line value, nullable |
| `pnl` | float | Profit/loss, nullable (null = unsettled) |
| `outcome` | text | Nullable — null means unsettled |
| `bet_timestamp` | timestamp | When the bet was placed (auto-set) |

The `tournaments` table columns:

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `tournament_name` | text | Full name |
| `start_date` | date | Thursday of tournament week |
| `dg_event_id` | text | DataGolf event identifier |
| `season` | int | Tour season year |

---

## Key Implementation Notes

1. **Early return pattern**: If no active tournament, call `st.stop()` after the info message. This prevents rendering empty tables and zero-value cards.

2. **Error handling**: Every query call is wrapped in try/except. On exception, show `st.error()` with a user-friendly message. Do NOT catch the error silently — the user needs to know data may be stale.

3. **Cache interaction**: This page does NOT manage caching directly. The query functions in `lib/queries.py` handle `@st.cache_data` with 5-minute TTL. The sidebar "Refresh Data" button (from section-01) clears all caches.

4. **Last-updated timestamp**: Display `st.caption(f"Last updated: {datetime.now().strftime('%I:%M %p')}")` at the bottom of the page. This reflects render time, not data fetch time, but is sufficient given the 5-minute cache.

5. **Aggregation in Python**: Exposure summary and P&L are computed in Python from the cached bet list, not via separate database queries. The bet count per tournament is small enough (typically 10-50) that this is efficient.

6. **Filter state**: Multiselect filters default to empty (meaning "show all"). When a user selects specific values, only matching rows are shown. This is standard Streamlit multiselect behavior.

---

## Implementation Status

**Status:** Implemented  
**Date:** 2026-04-06

### Files Created/Modified

| File | Action |
|------|--------|
| `dashboard/lib/aggregations.py` | Created — pure aggregation helpers |
| `dashboard/pages/active_bets.py` | Modified — replaced placeholder with full page |
| `dashboard/tests/test_aggregations.py` | Created — 17 tests for aggregation logic |
| `dashboard/tests/test_active_bets_page.py` | Created — 20 tests (page smoke + logic) |
| `dashboard/tests/test_app.py` | Modified — updated default page test to mock queries |

### Deviations from Plan

1. **Exposure chart skipped** — `build_exposure_by_market()` from `lib/charts.py` is a section-04 dependency. Chart rendering will be added in section-04.
2. **P&L uses `get_weekly_pnl()` query** — Plan note #5 said compute in Python, but `get_weekly_pnl()` in queries.py already implements the same logic with caching. Kept the existing query path; removed unused `compute_weekly_pnl` import from page.
3. **Edge/CLV color coding deferred** — `st.dataframe` has limited cell-level color support. Edge/CLV displayed as signed percentage strings (+5.2%, -1.1%) which conveys direction without complex Pandas Styler.
4. **`format_date_range` portability** — Replaced GNU-only `%-d` with `f"{day}"` pattern for cross-platform support.
5. **Market type labels** — Used `st.markdown(**bold**)` instead of `st.metric` for market type names (semantic improvement).

### Test Coverage

- 74 total tests passing (37 new for this section)
- Aggregation logic: 17 tests (group_by, exposure, weekly_pnl, estimate_round, format_date_range)
- Page smoke tests: 3 AppTest-based tests (no tournament, hidden table, tournament name display)
- Theme/display logic: 4 tests (color values, percentage formatting)
- P&L computation: 4 tests (settled, open, net, all-open)
