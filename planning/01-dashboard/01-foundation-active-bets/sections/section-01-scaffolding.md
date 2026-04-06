# Section 1: Project Scaffolding & Theme

## Implementation Status: COMPLETE

## Overview

This section creates the `dashboard/` directory structure, the Streamlit app entrypoint with navigation and sidebar, the theme/formatting module, `requirements.txt`, and the shared test fixtures. This is the foundation that all other sections build on — it has no dependencies and blocks every subsequent section.

## Deviations from Plan

- **Python 3.9 compatibility**: Added `from __future__ import annotations` in `theme.py` to support `float | None` union syntax. Removed `from typing import Optional`.
- **Input validation**: `format_american_odds` raises `ValueError` for `decimal_odds <= 1.0` (not in original plan; added during code review to prevent ZeroDivisionError).
- **Test imports**: Changed from `dashboard.lib.theme` to `lib.theme` since tests run with `dashboard/` as cwd per the test command.
- **Mock fixture path**: `conftest.py` patches `lib.supabase_client.get_client` (not `dashboard.lib.supabase_client`) to match cwd-relative imports.
- **Dead code removed**: `test_app.py` had an unused `_mock_supabase()` helper — removed during review. Section-03 will handle Supabase mocking when it replaces the placeholder page.
- **Additional tests**: Added `test_invalid_odds_raises` and `test_below_one_raises` for edge-case coverage (17 tests total vs 15 planned).

## Files to Create

```
dashboard/
  app.py
  pages/
    active_bets.py          # Placeholder (populated in section-03)
  lib/
    __init__.py
    theme.py
  .streamlit/
    config.toml
  requirements.txt
  tests/
    __init__.py
    conftest.py
    test_theme.py
    test_app.py
```

---

## Tests First

All tests live under `dashboard/tests/`. Run with `cd /Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland\ Thompson/Working/EV/pga-ev-betting/dashboard && pytest tests/ -v`.

### `dashboard/tests/conftest.py`

Shared fixtures used across all dashboard test files. Define these here so sections 2-5 can rely on them.

```python
import pytest

@pytest.fixture
def sample_tournament() -> dict:
    """Dict matching the tournaments table schema.
    
    Fields: id, tournament_name, start_date, purse, dg_event_id, season,
    is_signature, is_no_cut, putting_surface.
    Use a start_date of '2026-04-02' (a Thursday) for deterministic round math.
    """

@pytest.fixture
def sample_bets() -> list[dict]:
    """List of 5-6 bet dicts with varied market types, books, and outcomes.
    
    Include a mix of:
    - 2 matchup bets (one settled win, one unsettled)
    - 1 outright bet (unsettled)
    - 1 placement bet (settled loss)
    - 1 3-ball bet (unsettled)
    
    Each dict should have all columns the dashboard displays: id, tournament_id,
    player_name, opponent_name, market_type, book, odds_at_bet_american,
    odds_at_bet_decimal, stake, edge, clv, outcome, pnl, bet_timestamp.
    """

@pytest.fixture
def sample_active_bets(sample_bets) -> list[dict]:
    """Subset of sample_bets where outcome is None."""

@pytest.fixture
def sample_settled_bets(sample_bets) -> list[dict]:
    """Subset of sample_bets where outcome is not None."""

@pytest.fixture
def mock_supabase_client(monkeypatch):
    """Patched Supabase client that returns fixture data.
    
    Patches dashboard.lib.supabase_client.get_client to return a MagicMock
    with chainable .table().select().eq().is_().execute() calls.
    """
```

### `dashboard/tests/test_theme.py`

Tests for all formatting helpers and color constants in `lib/theme.py`. These are pure-logic tests with no Streamlit dependency.

```python
# Test: format_american_odds converts decimal 2.5 to "+150"
# Test: format_american_odds converts decimal 1.5 to "-200"
# Test: format_american_odds handles even money (2.0 -> "+100")
# Test: format_currency formats positive as "$25.00"
# Test: format_currency formats negative as "-$12.50"
# Test: format_currency handles zero as "$0.00"
# Test: format_percentage formats 0.05 as "+5.0%"
# Test: format_percentage formats -0.03 as "-3.0%"
# Test: format_percentage handles None/null gracefully
# Test: color_value returns COLOR_POSITIVE for positive floats
# Test: color_value returns COLOR_NEGATIVE for negative floats
# Test: color_value returns COLOR_NEUTRAL for zero
```

Each test imports directly from `dashboard.lib.theme` and asserts exact return values. No mocking required.

### `dashboard/tests/test_app.py`

Smoke tests for the Streamlit app entrypoint using Streamlit's `AppTest` harness.

```python
from streamlit.testing.v1 import AppTest

# Test: app.py entrypoint runs without error (smoke test via AppTest)
#   - AppTest.from_file("app.py") should run without exceptions
#   - Note: mock out supabase_client.get_client to avoid real DB calls

# Test: sidebar contains "Refresh Data" button
#   - After running the app, check at.sidebar.button elements

# Test: navigation includes Active Bets page as default
#   - Verify the app renders the active_bets page content by default
```

The `AppTest` harness requires the working directory to be `dashboard/` or the app path to be absolute. These tests need the Supabase client mocked since the app will attempt a connection on load if any page calls queries.

---

## Implementation Details

### `dashboard/.streamlit/config.toml`

Bloomberg-inspired dark theme configuration.

```toml
[theme]
base = "dark"
primaryColor = "#4A90D9"
backgroundColor = "#1a1a2e"
secondaryBackgroundColor = "#252540"
textColor = "#e0e0e0"
font = "sans serif"
```

The `base = "dark"` is critical. The specific hex values create a dark-gray-blue palette (not pure black). `primaryColor` is the professional blue used for interactive elements.

### `dashboard/lib/__init__.py`

Empty file. Exists so `dashboard/lib/` is an importable package.

### `dashboard/lib/theme.py`

Contains color constants and pure formatting functions. No Streamlit imports needed in this module.

```python
"""Color palette and formatting helpers for the PGA +EV Dashboard.

Bloomberg-inspired dark theme palette with green for positive values
and muted warm gray for negative values (avoids red per user preference).
"""

# Color constants
COLOR_POSITIVE: str   # Green for positive edge/CLV/PnL, e.g., "#00C853"
COLOR_NEGATIVE: str   # Muted warm gray for negative values, e.g., "#9E9E9E"
                      # NOT red, NOT pure black (invisible on dark bg)
COLOR_NEUTRAL: str    # Gray for zero/null, e.g., "#616161"

# Chart color palette: 6-8 distinguishable colors for dark backgrounds
# Muted blues, teals, oranges, purples in Bloomberg data-viz style
CHART_COLORS: list[str]

def format_american_odds(decimal_odds: float) -> str:
    """Convert decimal odds to American format string.
    
    Formula:
    - decimal >= 2.0: American = +((decimal - 1) * 100), e.g., 2.5 -> "+150"
    - decimal < 2.0:  American = -100 / (decimal - 1), e.g., 1.5 -> "-200"
    - decimal == 2.0:  "+100"
    
    Always includes sign prefix (+ or -).
    """

def format_currency(amount: float) -> str:
    """Format as currency with sign.
    
    Positive: "$25.00"
    Negative: "-$12.50"
    Zero: "$0.00"
    """

def format_percentage(value: float | None) -> str:
    """Format as percentage with sign and one decimal place.
    
    0.05 -> "+5.0%"
    -0.03 -> "-3.0%"
    None -> "—" (em dash)
    """

def color_value(value: float) -> str:
    """Return COLOR_POSITIVE, COLOR_NEGATIVE, or COLOR_NEUTRAL based on sign.
    
    Positive -> COLOR_POSITIVE
    Negative -> COLOR_NEGATIVE
    Zero -> COLOR_NEUTRAL
    """
```

Key implementation notes for `format_american_odds`:
- The formula is `round((decimal_odds - 1) * 100)` for favorites and `round(-100 / (decimal_odds - 1))` for underdogs
- Always return a string with the sign prefix
- The existing codebase stores `odds_at_bet_american` as a string in the bets table, but this function is needed for any computed odds display

### `dashboard/pages/active_bets.py`

A minimal placeholder for this section. The full implementation is in section-03.

```python
"""Active Bets page — default dashboard view during tournament weeks."""
import streamlit as st

st.header("Active Bets")
st.info("Page under construction.")
```

This placeholder is necessary so `app.py` can reference the page module without import errors.

### `dashboard/app.py`

The Streamlit entrypoint. Uses the `st.navigation` / `st.Page` API (available in Streamlit 1.40+).

```python
"""PGA +EV Dashboard — Streamlit app entrypoint."""
import streamlit as st

def main():
    """Configure page, define navigation, run selected page."""
    # 1. Page config (must be first Streamlit call)
    #    title="PGA +EV Dashboard", layout="wide", page_icon="golf-related emoji"
    
    # 2. Define pages using st.Page
    #    active_bets = st.Page("pages/active_bets.py", title="Active Bets", default=True)
    #    Group into sections: "Live" for active_bets
    #    (Future sections: "Analytics" placeholder)
    
    # 3. st.navigation([active_bets]) — returns selected page
    
    # 4. Sidebar content:
    #    - App title/branding: "PGA +EV Dashboard" with brief tagline
    #    - "Refresh Data" button: on click, calls st.cache_data.clear()
    #      and st.rerun() to force fresh queries
    
    # 5. pg.run() to dispatch to selected page

main()
```

The sidebar "Refresh Data" button pattern:

```python
with st.sidebar:
    st.title("PGA +EV Dashboard")
    st.caption("Golf betting edge tracker")
    if st.button("Refresh Data"):
        st.cache_data.clear()
        st.rerun()
```

### `dashboard/requirements.txt`

```
streamlit>=1.40.0
supabase>=2.28.0
plotly>=6.0.0
pandas>=2.2.0
```

Pin minimum versions only. Do not include sub-packages of `supabase` (e.g., `postgrest`, `gotrue` are transitive dependencies). These four packages are all that's needed.

### `dashboard/tests/__init__.py`

Empty file. Makes the tests directory an importable package for pytest discovery.

---

## Background Context

The PGA +EV Betting System is a Python-based sports betting tool at `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting`. The existing codebase lives under `src/` with a Supabase database backend. The `dashboard/` directory is entirely new — it does not exist yet.

The existing codebase uses `python-dotenv` and a module-global singleton for the Supabase client (in `src/db/supabase_client.py`). The dashboard intentionally does NOT import from `src/` — it uses Streamlit-native patterns (`st.secrets`, `st.cache_resource`) instead. This keeps the dashboard self-contained and deployable on Streamlit Cloud without the full project's dependencies.

The bets table has these columns relevant to the dashboard: `id`, `tournament_id`, `player_name`, `opponent_name`, `market_type`, `book`, `odds_at_bet_american`, `odds_at_bet_decimal`, `implied_prob_at_bet`, `your_prob`, `edge`, `stake`, `clv`, `outcome`, `pnl`, `bet_timestamp`, `is_live`, `round_number`.

The repo `.gitignore` at `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/.gitignore` already covers `__pycache__/` globally but does NOT yet cover `dashboard/.streamlit/secrets.toml`. That addition is handled in section-05 (deployment).

---

## Downstream Dependencies

The following sections depend on this scaffolding being complete:

- **section-02-data-layer**: Adds `lib/supabase_client.py` and `lib/queries.py` to the `dashboard/lib/` directory created here. Uses `requirements.txt` dependencies.
- **section-03-active-bets-page**: Replaces the placeholder `pages/active_bets.py` with the full implementation. Uses `lib/theme.py` formatting helpers.
- **section-04-charts**: Adds `lib/charts.py` using the `CHART_COLORS` palette from `lib/theme.py`.
- **section-05-deployment**: Adds `README.md`, updates `.gitignore`, validates `config.toml` and `requirements.txt`.
