# Section 6: App Navigation Update

## Overview

This section updates `dashboard/app.py` to register the three new analytics pages (Performance, Bankroll, Model Health) in the sidebar navigation. It also updates `dashboard/tests/test_app.py` to verify the new pages appear in the correct order.

**Dependencies:** Sections 03, 04, and 05 must be complete (the page files must exist).

## Files to Modify

- `dashboard/app.py` — Add three `st.Page()` entries
- `dashboard/tests/test_app.py` — Add navigation order tests

---

## Tests First

### Updates to `dashboard/tests/test_app.py`

Add a new `TestNavigation` class. All existing tests remain unchanged.

```python
class TestNavigation:
    """Verify all analytics pages are registered in the correct order."""

    # Test: navigation includes Performance page
    # Test: navigation includes Bankroll page
    # Test: navigation includes Model Health page
    # Test: page order is Active Bets, Performance, Bankroll, Model Health
```

### Mock Strategy

Tests must mock all query functions across all pages since Streamlit loads all page modules. Create a helper that patches every query function:

```python
def _mock_all_queries(self):
    """Patch targets covering all page query dependencies."""
    # lib.queries.get_current_tournament -> None
    # lib.queries.get_active_bets -> []
    # lib.queries.get_weekly_pnl -> {settled_pnl: 0, unsettled_stake: 0, net_position: 0}
    # lib.queries.get_settled_bets -> []
    # lib.queries.get_bankroll_curve -> []
    # lib.queries.get_weekly_exposure -> []
    # lib.queries.get_settled_bet_stats -> {total_count: 0, by_market_type: {}, latest_timestamp: None}
    # lib.queries.get_clv_weekly -> []
    # lib.queries.get_calibration -> []
    # lib.queries.get_roi_by_edge_tier -> []
```

### Page Order Test

The most reliable approach: patch `st.navigation` to capture the pages list, then assert titles match `["Active Bets", "Performance", "Bankroll", "Model Health"]`.

---

## Implementation Details

### Changes to `dashboard/app.py`

The changes are minimal. In the existing navigation setup:

1. Create three new `st.Page()` objects:
   ```python
   performance = st.Page("pages/performance.py", title="Performance")
   bankroll = st.Page("pages/bankroll.py", title="Bankroll")
   model_health = st.Page("pages/model_health.py", title="Model Health")
   ```

2. Pass all four pages to `st.navigation()`:
   ```python
   pg = st.navigation([active_bets, performance, bankroll, model_health])
   ```

3. `active_bets` remains `default=True` (landing page).

### Key Constraints

- **Page order matters**: `st.navigation()` renders pages in sidebar in list order. Required: Active Bets, Performance, Bankroll, Model Health.
- **No grouping needed**: All pages at top level (no section headers).
- **File paths relative to `app.py`**: `"pages/performance.py"`, `"pages/bankroll.py"`, `"pages/model_health.py"` (matching existing `"pages/active_bets.py"` pattern).
- **No other changes**: Sidebar title, caption, refresh button stay as-is.

---

## Verification

```bash
uv run pytest dashboard/tests/test_app.py -v
uv run pytest dashboard/tests/ -v
```

---

## Implementation Notes

### Files Modified
- `dashboard/app.py` — Added 3 `st.Page()` entries for Performance, Bankroll, Model Health
- `dashboard/tests/test_app.py` — Refactored to shared `_run_app()` with QUERY_PATCHES; added TestNavigation class

### Deviations from Plan
- **Navigation tests use source text validation instead of st.navigation patching**: Plan called for patching `st.navigation` to capture page args, but the `_run_app()` smoke test already validates the app loads without errors (catching import/runtime failures). The text-based navigation tests verify the configuration directly.
- **Refactored existing TestAppSmoke to use shared mock helper**: Old per-test `@patch` decorators replaced with centralized `QUERY_PATCHES` dict and `_run_app()` function, which scales to cover all page dependencies.

### Test Results
- 7 tests passing (3 smoke + 4 navigation)
- Full suite: 225 tests passing
