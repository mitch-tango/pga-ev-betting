# Section 4: Charts Module

## Overview

This section implements `dashboard/lib/charts.py` -- a module containing reusable Plotly figure builders. For this initial dashboard split, only one chart is needed (Exposure by Market Type), but the module establishes conventions that all future chart functions will follow.

**Dependencies:** Section 01 (scaffolding) must be complete so that `dashboard/lib/` exists and `plotly` is in `requirements.txt`. This section does NOT depend on section 02 (data layer) or section 03 (active bets page). The chart functions are pure: they accept Python data and return Plotly figures.

## Files to Create

| File | Purpose |
|------|---------|
| `dashboard/lib/charts.py` | Plotly figure builders |
| `dashboard/tests/test_charts.py` | Chart function tests |

## Tests (Write First)

All tests live in `dashboard/tests/test_charts.py`. The chart module is pure Python with no Streamlit dependency, so tests are straightforward pytest without `AppTest`.

```python
"""Tests for dashboard.lib.charts — Plotly figure builders."""

import pytest
import plotly.graph_objects as go
import plotly.io as pio


# --- build_exposure_by_market ---

# Test: returns a plotly go.Figure instance when given a non-empty bet list
def test_build_exposure_by_market_returns_figure():
    """build_exposure_by_market should return a go.Figure."""

# Test: creates a horizontal bar chart (bar trace with orientation='h')
def test_build_exposure_by_market_horizontal_bars():
    """The figure should contain a Bar trace with orientation='h'."""

# Test: handles empty bet list gracefully — returns None (caller decides not to render)
def test_build_exposure_by_market_empty_list_returns_none():
    """An empty bet list should return None, not an empty figure."""

# Test: uses correct market type labels derived from input data
def test_build_exposure_by_market_correct_labels():
    """Bar labels (y-axis categories) should match the distinct market_type values in the input."""

# Test: figure has compact margins matching the convention
def test_build_exposure_by_market_compact_margins():
    """Figure layout margins should be l=10, r=10, t=40, b=10."""

# Test: figure is JSON-serializable (required for Streamlit rendering)
def test_build_exposure_by_market_serializable():
    """The figure should serialize to JSON without error via plotly.io.to_json."""
```

**Test data pattern:** Tests should construct sample bet lists inline as lists of dicts. Each dict needs at minimum `market_type` (str) and `stake` (float). Example:

```python
SAMPLE_BETS = [
    {"market_type": "matchup", "stake": 25.0},
    {"market_type": "matchup", "stake": 30.0},
    {"market_type": "outright", "stake": 10.0},
    {"market_type": "placement", "stake": 15.0},
]
```

With this data, the chart should show three bars: matchup ($55), placement ($15), outright ($10) -- sorted by total stake descending.

## Implementation Details

### `dashboard/lib/charts.py`

The module exposes one public function for this split plus a private helper for shared layout settings.

#### Chart Conventions (All Figures)

Every figure builder in this module must apply these shared settings. Define a private helper `_apply_common_layout(fig: go.Figure) -> go.Figure` that sets:

- **Compact margins:** `margin=dict(l=10, r=10, t=40, b=10)` -- saves space on mobile and in dashboard cards
- **Transparent paper/plot background:** `paper_bgcolor="rgba(0,0,0,0)"` and `plot_bgcolor="rgba(0,0,0,0)"` -- lets the Streamlit dark theme show through rather than fighting it with a separate background
- **Legend position:** horizontal, below the chart area: `legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5)`
- **Font color:** light gray (`"#E0E0E0"`) for axis labels and title text so they are readable on dark backgrounds

These conventions exist so that when future chart functions are added (bankroll curve, ROI by book, edge distribution, calibration plot), they all share a consistent look.

#### Caller-Side Conventions

When the page layer (section 03) renders a chart, it must call `st.plotly_chart()` with these arguments:

- `theme="streamlit"` -- inherits the Streamlit dark theme
- `use_container_width=True` -- responsive width
- `config={"responsive": True}` -- enables resize handling
- `key="some_unique_key"` -- required by Streamlit to avoid component ID collisions

These are NOT set inside `charts.py` -- they are the responsibility of the calling page. Documenting them here ensures the page implementer knows what to pass.

#### `build_exposure_by_market`

```python
def build_exposure_by_market(bets: list[dict]) -> go.Figure | None:
    """Build a horizontal bar chart showing total stake by market type.

    Args:
        bets: List of bet dicts. Each must have 'market_type' (str) and 'stake' (float).

    Returns:
        A Plotly Figure with a horizontal bar chart, or None if bets is empty.
        Returning None allows the caller to skip rendering entirely.
    """
```

Implementation notes:

1. **Return None for empty input.** If `bets` is empty (or has no entries with positive stake), return `None`. The caller (active bets page) checks for `None` and simply does not render the chart section. This is cleaner than rendering an empty chart with no bars.

2. **Aggregate stakes by market type.** Group the bet list by `market_type` and sum `stake` within each group. This can be done with a simple dict comprehension or `collections.defaultdict` -- no pandas needed for this aggregation.

3. **Sort by total stake descending.** The market type with the highest exposure appears at the top of the horizontal bar chart. This makes the most important information immediately visible.

4. **Create horizontal bar chart.** Use `go.Bar` with `orientation="h"`. The y-axis contains market type labels, the x-axis contains dollar amounts.

5. **Color palette.** Use the Bloomberg-inspired dark palette from `theme.py` (section 01 defines a `CHART_COLORS` sequence of 6-8 distinguishable colors). Import the palette and assign colors per bar. If `CHART_COLORS` is not yet available, define a local fallback list of muted blues/teals/oranges that work on dark backgrounds.

6. **Apply common layout** via `_apply_common_layout(fig)`.

7. **Axis formatting.** The x-axis should show dollar values (prefix with `$`). The y-axis shows market type names as-is. Hide grid lines on the y-axis for cleanliness; keep light grid lines on the x-axis for readability.

8. **Title.** Set a brief chart title: "Exposure by Market Type". Applied via `fig.update_layout(title_text=...)`.

#### Optional Rendering Logic

The chart should only be rendered on the active bets page if there are 2 or more distinct market types with active bets. If all bets are in a single market type, the bar chart adds no information beyond what the exposure summary cards already show. The caller (section 03) handles this check -- the chart function itself always builds the figure if given non-empty data.

## Integration Notes for Section 03

When section 03 (Active Bets Page) integrates this chart, the pattern is:

```python
from lib.charts import build_exposure_by_market

# After fetching active bets and before rendering the bet table:
if len(distinct_market_types) >= 2:
    fig = build_exposure_by_market(active_bets)
    if fig is not None:
        st.plotly_chart(
            fig,
            theme="streamlit",
            use_container_width=True,
            config={"responsive": True},
            key="exposure_by_market",
        )
```

This is provided as guidance for the section 03 implementer -- do not implement page rendering in this section.

---

## Implementation Status

**Status:** Implemented  
**Date:** 2026-04-06

### Files Created/Modified

| File | Action |
|------|--------|
| `dashboard/lib/charts.py` | Created — Plotly figure builders with `build_exposure_by_market` and `_apply_common_layout` |
| `dashboard/tests/test_charts.py` | Created — 9 tests for chart module |
| `dashboard/pages/active_bets.py` | Modified — integrated exposure chart rendering (2+ market types) |

### Deviations from Plan

1. **Zero/negative stake guard** — Added post-aggregation check returning None if all stakes are <= 0 (review finding).
2. **Layout call order** — `_apply_common_layout` called before chart-specific overrides so chart settings take precedence (review finding).
3. **Page integration included** — Plan said page rendering was section-03's responsibility, but since section-03 was already committed without the chart (forward dependency), the integration was done here.

### Test Coverage

- 83 total tests passing (9 new for this section)
- Chart tests: returns figure, horizontal bars, empty list, zero stakes, correct labels, sort order, aggregated values, compact margins, JSON serializable
