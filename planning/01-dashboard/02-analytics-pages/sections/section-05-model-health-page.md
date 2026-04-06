# Section 5: Model Health Page

## Overview

This section implements the **Model Health** page (`pages/model_health.py`) and its tests. The page provides calibration and diagnostic insights: sample size indicators, CLV (Closing Line Value) trends, prediction calibration, and ROI by edge tier. It answers "Is the model working well?" rather than "Am I making money?" (Performance page's job).

**Dependencies:** Sections 01 (Data Layer) and 02 (Charts) must be complete. Requires:
- **Queries**: `get_settled_bet_stats()`, `get_clv_weekly()`, `get_calibration()`, `get_roi_by_edge_tier()`
- **Charts**: `build_clv_trend()`, `build_calibration()`, `build_roi_by_edge_tier()`

## Files to Create

- `dashboard/pages/model_health.py`
- `dashboard/tests/test_model_health_page.py`

---

## Tests First

### Test File: `dashboard/tests/test_model_health_page.py`

Tests use Streamlit's `AppTest` framework. All data-layer functions are mocked.

### Inline Fixtures

```python
MOCK_STATS = {
    "total_count": 142,
    "by_market_type": {"matchup": 85, "outright": 32, "placement": 25},
    "latest_timestamp": "2026-04-04T18:30:00Z",
}

MOCK_CLV_WEEKLY = [
    {"week": "2026-03-02", "bets": 18, "avg_clv_pct": 1.2, "weekly_pnl": 45.0, "avg_edge_pct": 3.1},
    {"week": "2026-03-09", "bets": 22, "avg_clv_pct": -0.5, "weekly_pnl": -12.0, "avg_edge_pct": 2.8},
    {"week": "2026-03-16", "bets": 15, "avg_clv_pct": 2.1, "weekly_pnl": 67.0, "avg_edge_pct": 4.0},
]

MOCK_CALIBRATION = [
    {"prob_bucket": "30-40%", "n": 20, "avg_predicted_pct": 35.0, "actual_hit_pct": 38.0},
    {"prob_bucket": "40-50%", "n": 45, "avg_predicted_pct": 45.0, "actual_hit_pct": 42.0},
    {"prob_bucket": "50-60%", "n": 30, "avg_predicted_pct": 55.0, "actual_hit_pct": 57.0},
]

MOCK_EDGE_TIERS = [
    {"edge_tier": "0-2%", "total_bets": 40, "total_staked": 800.0, "total_pnl": -32.0, "roi_pct": -4.0, "avg_clv_pct": -0.5},
    {"edge_tier": "2-5%", "total_bets": 55, "total_staked": 1375.0, "total_pnl": 96.25, "roi_pct": 7.0, "avg_clv_pct": 1.2},
    {"edge_tier": "5-10%", "total_bets": 35, "total_staked": 875.0, "total_pnl": 131.25, "roi_pct": 15.0, "avg_clv_pct": 3.1},
]
```

### Test Cases

```python
# Test: page renders title "Model Health"
# Test: sample size metrics render (total bets, by market, freshness)
# Test: CLV trend chart renders when data exists
# Test: calibration chart renders
# Test: edge tier chart renders
# Test: shows info message when no CLV data (get_clv_weekly returns [])
# Test: timestamp footer present
```

### Mock Pattern

Patch four query functions at module import path (e.g., `pages.model_health.get_clv_weekly`). Optionally patch chart builders to return `go.Figure()` or `None`.

**Empty state test:** When `get_clv_weekly` returns `[]`, page shows `st.info("Not enough settled bets to analyze model health.")` and `st.stop()`. No charts render.

### Unit Test for Relative Time Helper

```python
# Test: _format_relative_time returns "just now" for < 1 minute
# Test: returns "X minutes ago" for minutes
# Test: returns "X hours ago" for hours
# Test: returns "X days ago" for days
```

---

## Implementation Details

### Page File: `dashboard/pages/model_health.py`

```python
"""Model Health page — calibration, CLV trends, and edge tier analysis."""
from datetime import datetime, timezone

import streamlit as st

from lib.queries import get_settled_bet_stats, get_clv_weekly, get_calibration, get_roi_by_edge_tier
from lib.charts import build_clv_trend, build_calibration, build_roi_by_edge_tier


def render():
    """Main render function for the Model Health page."""
    ...

render()
```

### Page Layout (top to bottom)

**1. Title** -- `st.title("Model Health")`

**2. Sample Size Indicators** -- Row of three `st.metric()` boxes in `st.columns(3)`:
- **Total Settled Bets**: `total_count` from `get_settled_bet_stats()`
- **By Market Type**: Comma-separated summary from `by_market_type` dict (e.g., "matchup: 85, outright: 32, placement: 25")
- **Latest Bet**: `latest_timestamp` formatted as relative time via `_format_relative_time()`

**3. CLV Trend Chart** -- Fetch via `get_clv_weekly()`. If empty, show `st.info("Not enough settled bets to analyze model health.")` and `st.stop()`. Otherwise render with `build_clv_trend()`. Add caption: `st.caption("Positive CLV indicates your model consistently beats closing lines.")`

**4. Calibration Chart** -- Fetch via `get_calibration()`. Pass to `build_calibration()`. Skip if returns `None`. Add caption: `st.caption("Points near the diagonal indicate well-calibrated predictions. Above = underconfident, below = overconfident.")`

**5. Edge Tier Analysis** -- Fetch via `get_roi_by_edge_tier()`. Pass to `build_roi_by_edge_tier()`. Skip if returns `None`. Add caption: `st.caption("Higher-edge bets should produce higher returns if the model is well-calibrated.")`

**6. Timestamp Footer** -- `st.caption(f"Last updated: {datetime.now().strftime('%I:%M %p')}")`

### Relative Time Helper

```python
def _format_relative_time(iso_timestamp: str) -> str:
    """Convert ISO timestamp to human-readable relative time string.

    Examples: 'just now', '5 minutes ago', '3 hours ago', '2 days ago'.
    Uses datetime and timedelta from standard library — no external dependency.
    """
```

Parse the ISO timestamp, compute delta from `datetime.now(timezone.utc)`, return a human-friendly string. Handle: < 1 min → "just now", minutes, hours, days.

### Chart Rendering

Use `st.plotly_chart()` with consistent kwargs:
```python
st.plotly_chart(fig, theme="streamlit", use_container_width=True, config={"responsive": True}, key="<unique_key>")
```

Keys: `"clv_trend"`, `"calibration"`, `"roi_edge_tier"`.

### Error Handling

Wrap each query in try/except with `st.error()`. If `get_settled_bet_stats()` fails, show error but continue. If `get_clv_weekly()` fails, return early.

### Empty State Logic

The primary gate is on CLV weekly data. If empty → info + stop. Sample size metrics render before this check so users see bet counts even without chart data. Calibration and edge tier handle their own empty states via chart builder returning `None`.

---

## Verification

```bash
uv run pytest dashboard/tests/test_model_health_page.py -v
uv run pytest dashboard/tests/ -v
```

---

## Implementation Notes

### Files Created
- `dashboard/pages/model_health.py` — Model Health page with render function
- `dashboard/tests/test_model_health_page.py` — 17 tests (charts, data flow, relative time helper)

### Deviations from Plan
- **Tests use data-flow pattern instead of AppTest**: Consistent with performance and bankroll page test patterns in the codebase. Tests verify chart builders with page-specific fixture data and the `_format_relative_time` helper directly.
- **`_format_relative_time` handles singular forms**: Added proper singular/plural grammar ("1 minute ago" vs "2 minutes ago") — not specified in plan but important for UX.
- **`if stats is not None:` guard**: Changed from `if stats:` to properly handle edge case where stats dict exists but has zero counts.

### Test Results
- 17 tests passing (6 chart, 4 data flow, 7 relative time)
- Full suite: 221 tests passing
