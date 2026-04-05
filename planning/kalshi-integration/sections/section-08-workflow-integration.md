# Section 8: Workflow Integration

## Overview

This section wires the Kalshi pipeline (pull, merge, edge calculation) into the two main workflow scripts: `scripts/run_pretournament.py` and `scripts/run_preround.py`. It also adds graceful degradation so Kalshi failures never block the DG-only pipeline, and adds Polymarket TODO comments at integration points.

**Dependencies:** This section assumes sections 05 (pipeline pull), 06 (pipeline merge), and 07 (edge/dead-heat) are complete. Specifically, it depends on:
- `src/pipeline/pull_kalshi.py` providing `pull_kalshi_outrights()` and `pull_kalshi_matchups()` (section 05)
- Merge functions `merge_kalshi_into_outrights()` and `merge_kalshi_into_matchups()` from `src/pipeline/pull_kalshi.py` (section 06)
- Edge calculator changes that handle `"kalshi"` as a book column with per-book dead-heat adjustments (section 07)

**Files to modify:**
- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/scripts/run_pretournament.py`
- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/scripts/run_preround.py`

**New test file:**
- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/tests/test_kalshi_workflow.py`

**New test file (graceful degradation):**
- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/tests/test_kalshi_degradation.py`

---

## Tests

Write tests BEFORE implementing the workflow changes. There are two test files: one for workflow integration behavior and one for graceful degradation.

### `tests/test_kalshi_workflow.py`

```python
"""Tests for Kalshi integration into workflow scripts."""
import pytest


class TestPreTournamentWithKalshi:
    """Verify run_pretournament pulls and merges Kalshi data."""

    def test_pulls_kalshi_after_dg(self):
        """run_pretournament calls pull_kalshi_outrights after pull_all_outrights.
        Mock both pipeline functions. Verify call order: DG first, then Kalshi."""

    def test_kalshi_failure_doesnt_prevent_dg_only(self):
        """If pull_kalshi_outrights raises or returns empty, the pipeline
        proceeds with DG-only data and calculates edges normally."""

    def test_merged_data_includes_kalshi_book(self):
        """After merge, at least one player record in the outrights dict
        has a 'kalshi' key containing an American odds string."""

    def test_candidates_can_have_best_book_kalshi(self):
        """When Kalshi offers the best edge, CandidateBet.best_book == 'kalshi'."""


class TestPreRoundKalshiGuard:
    """Verify pre-round Kalshi guard logic."""

    def test_with_live_dg_includes_kalshi(self):
        """When pipeline uses live DG predictions (get_live_predictions available),
        Kalshi tournament-long markets are pulled and merged."""

    def test_without_live_dg_skips_kalshi(self):
        """When pipeline uses pre-tournament DG data only (no live model),
        Kalshi tournament markets are NOT pulled (stale model risk)."""

    def test_skipping_logs_warning(self):
        """When Kalshi is skipped due to no live DG, a warning is logged/printed."""
```

### `tests/test_kalshi_degradation.py`

```python
"""Tests for graceful degradation when Kalshi is unavailable."""
import pytest


class TestGracefulDegradation:
    """Pipeline completes with DG-only data under various Kalshi failure modes."""

    def test_api_unreachable(self):
        """Kalshi API network error -> pipeline completes with DG-only data."""

    def test_no_golf_events(self):
        """No open golf events on Kalshi -> pipeline completes with DG-only data."""

    def test_tournament_cant_be_matched(self):
        """Tournament matching fails -> pipeline completes with warning logged."""

    def test_all_below_oi_threshold(self):
        """All Kalshi players below OI threshold -> no 'kalshi' key in consensus."""

    def test_all_exceed_spread_threshold(self):
        """All Kalshi players exceed spread threshold -> no 'kalshi' in consensus."""

    def test_rate_limit_retries_then_proceeds(self):
        """429 rate limit -> client retries, then pipeline proceeds without Kalshi."""

    def test_partial_data_uses_available(self):
        """Some markets available (win OK, t10 empty) -> uses what's available."""
```

All tests should mock the Kalshi pipeline functions (`pull_kalshi_outrights`, `pull_kalshi_matchups`, `merge_kalshi_into_outrights`, `merge_kalshi_into_matchups`) and the DG pipeline functions. The tests verify behavior of the workflow scripts' `main()` logic, not of the underlying pipeline modules (those are tested in sections 05 and 06).

---

## Implementation Details

### 8.1 Changes to `scripts/run_pretournament.py`

The existing `main()` function in `run_pretournament.py` follows this flow:

1. Pull DG outrights via `pull_all_outrights()`
2. Pull DG matchups via `pull_tournament_matchups()`
3. Optionally merge Start book odds
4. Calculate placement edges and matchup edges
5. Display and interactively place bets

The Kalshi integration inserts a new step between steps 2-3 (after pulling DG data, before edge calculation). The changes are:

**Add imports** at the top of the file:
- `from src.pipeline.pull_kalshi import pull_kalshi_outrights, pull_kalshi_matchups, merge_kalshi_into_outrights, merge_kalshi_into_matchups`

**Add Kalshi pull-and-merge block** after the DG matchup pull (after the existing "Pulling tournament matchups..." section, before "Detect tournament info"). The block should:

1. Print `"\nPulling Kalshi odds..."`
2. Call `pull_kalshi_outrights(tournament_slug)` inside a try/except that catches any `Exception`.
3. If successful and non-empty, call `merge_kalshi_into_outrights(outrights, kalshi_outrights)` to inject Kalshi as book columns into the existing outrights dict. Print a summary of how many Kalshi players were merged per market.
4. Call `pull_kalshi_matchups(tournament_slug)` inside the same try/except block.
5. If successful and non-empty, call `merge_kalshi_into_matchups(matchups, kalshi_matchups)` to inject Kalshi H2H odds. Print how many matchups were augmented.
6. On any exception, print a warning like `"  Warning: Kalshi data unavailable ({error}), proceeding with DG-only"` and continue.

The Kalshi block should appear BEFORE the Start book merge, so both Kalshi and Start can be present in the data when edges are calculated.

**Add Polymarket TODO comment** after the Kalshi block:
```python
# TODO: Polymarket integration — pull_polymarket_outrights() would follow
# the same pattern here. Polymarket covers win/T10/T20 but NOT matchups.
# Requires keyword-based event discovery (no golf-specific ticker).
```

No other changes to `run_pretournament.py` are needed. The edge calculator already discovers book columns dynamically, so `"kalshi"` will be picked up automatically once it is injected into the data.

### 8.2 Changes to `scripts/run_preround.py`

The pre-round script currently pulls round matchups and 3-balls only. Kalshi does not offer round-specific markets, but it does offer tournament-long markets (win, T10, T20, tournament H2H) that trade live during the event.

**The guard logic:** Kalshi tournament-long prices reflect in-tournament performance. Comparing live Kalshi prices against stale pre-tournament DG probabilities would create massive false-positive edges. Therefore, only pull Kalshi tournament markets during pre-round if the pipeline also has access to live DG predictions.

Implementation:

1. **Add imports** for the Kalshi pipeline functions (same as pretournament).
2. **Add a `--kalshi` flag** (or detect automatically) that controls whether to pull Kalshi tournament markets. The automatic detection checks whether the run is using live DG data (i.e., whether `get_live_predictions()` is available and returns data for this tournament). If the system does not yet have a `get_live_predictions()` function, use a simple flag or config check.
3. **If Kalshi is enabled for pre-round:** pull tournament outrights and matchups, merge into any outright data the pre-round script may have, and include in edge calculation. Wrap in try/except for graceful degradation.
4. **If Kalshi is skipped:** print a message like `"  Skipping Kalshi tournament markets (no live DG model — stale model risk)"`.
5. **Add Polymarket TODO comment** similar to pretournament.

Since the current `run_preround.py` only handles round matchups and 3-balls (no outrights), the Kalshi tournament outright integration for pre-round is a future enhancement. For now, the main integration point is tournament matchups — if the pre-round script pulls tournament matchups alongside round matchups, Kalshi H2H can be merged there. If it does not, the Kalshi guard simply skips with a log message. The guard implementation ensures the code path exists and is safe for future expansion.

### 8.3 Graceful Degradation Pattern

Every call to Kalshi functions in the workflow scripts must follow this pattern:

```python
# Pull Kalshi (graceful degradation — never blocks DG pipeline)
kalshi_outrights = {}
try:
    kalshi_outrights = pull_kalshi_outrights(tournament_slug)
    # ... merge and log
except Exception as e:
    print(f"  Warning: Kalshi unavailable ({e}), proceeding with DG-only")
```

The key principle: Kalshi is additive. The pipeline must always be able to complete with DG-only data. No Kalshi failure mode should raise an unhandled exception, return a non-standard data format, or alter the DG data in a way that breaks downstream processing.

The merge functions (from section 06) are designed to be no-ops when given empty Kalshi data, so passing an empty dict or list through the merge is safe.

### 8.4 Discord Bot

The bot (`src/discord_bot/`) already displays whatever `best_book` the edge calculator selects and shows `all_book_odds` in its detail view. Since Kalshi is injected as a standard book column, it appears automatically in:
- `/scan` results when Kalshi offers the best edge
- `/place` logging with `book = "kalshi"`
- `/status` dashboard tracked in the `v_roi_by_book` view

No bot code changes are needed. If the display format needs adjustment for the "kalshi" book name (e.g., capitalization), that is a cosmetic follow-up, not part of this section.

### 8.5 Polymarket TODO Comments

Add TODO comments in these locations:
- **`scripts/run_pretournament.py`** — after the Kalshi block (as described above)
- **`scripts/run_preround.py`** — after the Kalshi guard block, same pattern

These comments should note that Polymarket covers outrights and top-N but not matchups, requires keyword-based event discovery (no golf-specific ticker), and would use the `py-clob-client` SDK.

---

## Implementation Notes

**Actual changes made:**

1. **`scripts/run_pretournament.py`**: Added Kalshi imports, pull-and-merge block after DG pulls with try/except graceful degradation. Tournament name check added — skips Kalshi with a warning if `_event_name` is empty. Polymarket TODO comment added. `timedelta` imported at module top.

2. **`scripts/run_preround.py`**: Added Kalshi imports, guard block with `kalshi_enabled = False` (disabled until live DG predictions exist). When enabled, pulls tournament matchups and merges into round data. Skip message printed when disabled. Polymarket TODO comment added. `timedelta` imported at module top.

3. **`tests/test_kalshi_workflow.py`**: 7 tests covering pretournament Kalshi integration (import presence, call ordering, graceful degradation pattern, merge behavior, CandidateBet compatibility) and preround guard (source inspection for Kalshi presence, skip warning, imports). Tests use source inspection for workflow scripts due to complex dependency chain.

4. **`tests/test_kalshi_degradation.py`**: 7 tests covering API unreachable, no golf events, tournament matching failure, empty merge no-ops, partial data handling, and rate limit handling. Tests exercise pull_kalshi functions directly with mocked KalshiClient.

**Deviations from plan:**
- Pull function signatures require `(tournament_name, tournament_start, tournament_end)` not just `(tournament_slug)` — implementation adapted
- No `--kalshi` CLI flag added to preround (deferred: feature is disabled)
- OI/spread threshold degradation tests replaced with merge-noop tests (OI/spread filtering already tested in `test_pull_kalshi.py`)
- Workflow tests use source inspection pattern instead of full behavioral mocking (pragmatic for interactive CLI scripts)

**Code review fixes applied:**
- Moved `timedelta` import from inside try blocks to module-level
- Added tournament name validation with clear warning message
- Added comments documenting the 4-day tournament window

---

## Summary Checklist

1. `tests/test_kalshi_workflow.py` — 7 tests, all pass
2. `tests/test_kalshi_degradation.py` — 7 tests, all pass
3. `scripts/run_pretournament.py` modified with Kalshi block + Polymarket TODO
4. `scripts/run_preround.py` modified with Kalshi guard + Polymarket TODO
5. Full test suite: 304 tests pass, 0 failures
6. DG-only flow unaffected when Kalshi data is empty or unavailable