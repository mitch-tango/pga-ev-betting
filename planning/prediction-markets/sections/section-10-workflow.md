# Section 10: Workflow Integration

## Overview

This section updates the three workflow scripts to pull and merge Polymarket and ProphetX odds alongside Kalshi. Each new market gets its own try/except block with graceful degradation.

## Dependencies

- **section-01-config**: `POLYMARKET_ENABLED`, `PROPHETX_ENABLED` flags
- **section-03-edge-updates**: Generalized edge calculation
- **section-06-polymarket-pull**: `pull_polymarket_outrights()`, `merge_polymarket_into_outrights()`
- **section-09-prophetx-pull**: `pull_prophetx_outrights()`, `pull_prophetx_matchups()`, `merge_prophetx_into_outrights()`, `merge_prophetx_into_matchups()`

## Files to Modify

| File | Changes |
|------|---------|
| `scripts/run_pretournament.py` | Add Polymarket + ProphetX pull/merge blocks |
| `scripts/run_preround.py` | Add Polymarket + ProphetX pull/merge blocks |
| `src/pipeline/pull_live_edges.py` | Add Polymarket + ProphetX pull/merge blocks |

## Tests First

Create `tests/test_workflow_integration.py`.

```python
# --- run_pretournament.py ---
# Test: Polymarket block runs when POLYMARKET_ENABLED=True
# Test: Polymarket block skips when POLYMARKET_ENABLED=False
# Test: Polymarket failure prints warning and continues
# Test: ProphetX block runs when PROPHETX_ENABLED=True
# Test: ProphetX block skips when PROPHETX_ENABLED=False
# Test: ProphetX failure prints warning and continues
# Test: Pipeline works with all prediction markets failing (DG-only)

# --- run_preround.py ---
# Test: same enabled/disabled/failure patterns

# --- run_live_check.py ---
# Test: live check includes prediction market edges when available
# Test: live check graceful degradation when markets fail

# --- Integration ---
# Test: full pipeline with all 3 prediction markets returns valid edges
# Test: full pipeline with only DG + Kalshi returns valid edges (regression)
# Test: pull order: DG → Kalshi → Polymarket → ProphetX → edge calc
```

## Implementation Details

### Imports to Add (all three files)

```python
from src.pipeline.pull_polymarket import (
    pull_polymarket_outrights,
    merge_polymarket_into_outrights,
)
from src.pipeline.pull_prophetx import (
    pull_prophetx_outrights, pull_prophetx_matchups,
    merge_prophetx_into_outrights, merge_prophetx_into_matchups,
)
```

### Changes to `scripts/run_pretournament.py`

Insert after the Kalshi block (after ~line 285), before edge calculation. Replace TODO comments.

**Variable hoisting**: Move `today` and `end_date` computation from inside the Kalshi try/except to just before it, so all three markets can use them.

**Polymarket block:**
```
if config.POLYMARKET_ENABLED:
    print("\nPulling Polymarket odds...")
    try:
        polymarket_outrights = pull_polymarket_outrights(
            tournament_name_for_kalshi, today, end_date,
            tournament_slug=tournament_slug,
        )
        if any(len(v) > 0 for v in polymarket_outrights.values()):
            merge_polymarket_into_outrights(outrights, polymarket_outrights)
            for mkt, players in polymarket_outrights.items():
                if players:
                    print(f"  Polymarket {mkt}: {len(players)} players merged")
        else:
            print("  Polymarket: no outright data available")
    except Exception as e:
        print(f"  Warning: Polymarket unavailable ({e}), proceeding without")
else:
    print("\nPolymarket: disabled")
```

**ProphetX block** (immediately after Polymarket):
```
if config.PROPHETX_ENABLED:
    print("\nPulling ProphetX odds...")
    try:
        prophetx_outrights = pull_prophetx_outrights(
            tournament_name_for_kalshi, today, end_date,
            tournament_slug=tournament_slug,
        )
        if any(len(v) > 0 for v in prophetx_outrights.values()):
            merge_prophetx_into_outrights(outrights, prophetx_outrights)
            for mkt, players in prophetx_outrights.items():
                if players:
                    print(f"  ProphetX {mkt}: {len(players)} players merged")

        prophetx_matchup_data = pull_prophetx_matchups(
            tournament_name_for_kalshi, today, end_date,
            tournament_slug=tournament_slug,
        )
        if prophetx_matchup_data:
            merge_prophetx_into_matchups(matchups, prophetx_matchup_data)
            print(f"  ProphetX matchups: {len(prophetx_matchup_data)} merged")
    except Exception as e:
        print(f"  Warning: ProphetX unavailable ({e}), proceeding without")
else:
    print("\nProphetX: disabled (no credentials)")
```

### Changes to `scripts/run_preround.py`

Insert after Kalshi block (~line 255). Preround focuses on matchups:

- **Polymarket**: Skip in preround (no matchups, and outrights not relevant for round analysis) — add comment explaining
- **ProphetX**: Pull matchups only, merge into `round_matchups`

Ensure `tournament_name_for_kalshi` is initialized before the conditional block.

### Changes to `src/pipeline/pull_live_edges.py`

Insert after Kalshi merge (~line 186), before bankroll step.

Add Polymarket outright merge and ProphetX outright + matchup merge blocks. Update `stats` dict with `polymarket_merged`, `prophetx_merged`, `polymarket_error`, `prophetx_error` keys.

Hoist `today`/`end_date` above Kalshi block.

Add stats display lines in `run_live_check.py` (~line 63).

### Pull Order

1. DG outrights/matchups (existing)
2. Kalshi outrights + matchups (existing)
3. Polymarket outrights (new)
4. ProphetX outrights + matchups (new)
5. Edge calculation (existing — now sees more book columns)

### Graceful Degradation

The pipeline must work in every combination:
- All 3 markets up → best consensus
- Any 1-2 down → reduced consensus, still valid
- All down → DG-only, identical to pre-integration behavior
- Markets disabled via config → no API calls, clean skip

Each market is independent. Failure in one does not affect others.

## Implementation Notes

### Files Modified
- `scripts/run_pretournament.py` — Added `_pull_polymarket_block` and `_pull_prophetx_block` helpers
- `scripts/run_preround.py` — Added `_pull_prophetx_matchup_block` helper (Polymarket skipped by design)
- `src/pipeline/pull_live_edges.py` — Added `_pull_polymarket_block`, `_pull_prophetx_block` helpers + inline ProphetX outrights in live pipeline
- `scripts/run_live_check.py` — Added Polymarket/ProphetX stats display lines
- `tests/test_workflow_integration.py` — 12 tests

### Deviations from Plan
- **Helper function extraction**: Prediction market blocks extracted as testable `_pull_*_block()` functions rather than inline code, enabling cleaner testing
- **Polymarket not imported in preround**: Only ProphetX (matchups-only) added. Polymarket is outrights-only, not relevant for round analysis
- **Live pipeline ProphetX outrights**: Inlined rather than using `_pull_prophetx_block` to avoid duplicate `pull_prophetx_matchups()` API call (matchups merged separately in step 7)
- **Pull-order and full-pipeline integration tests**: Deferred to section 11 (testing section)

## Verification Checklist

1. Pretournament + live scripts import Polymarket and ProphetX modules ✓
2. Polymarket block checks `POLYMARKET_ENABLED` before pulling ✓
3. ProphetX block checks `PROPHETX_ENABLED` before pulling ✓
4. Each block wrapped in its own try/except ✓
5. Date variables hoisted above Kalshi block ✓
6. Pipeline works DG-only when all markets fail ✓
7. `uv run pytest tests/test_workflow_integration.py` — 12 passed ✓
