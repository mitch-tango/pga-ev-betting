# Section 7: Edge Calculator Dead-Heat Per-Book Adjustment

## Overview

This section modifies the dead-heat adjustment logic in `calculate_placement_edges()` so that it is applied **per-book** rather than globally. Currently, the dead-heat reduction is applied once to the single best raw edge. After this change, each book candidate gets its own adjusted edge -- and for Kalshi specifically, the dead-heat adjustment is skipped entirely for T10/T20 markets because Kalshi binary contracts pay full value on ties (no dead-heat reduction).

This is a significant structural advantage for Kalshi placement bets and will frequently cause Kalshi to surface as the "best book" for T10/T20 even when its raw odds are slightly worse than a traditional sportsbook.

**Depends on:** section-03-config-schema (for `KALSHI_NO_DEADHEAT_BOOKS` or equivalent config, and Kalshi being present in `BOOK_WEIGHTS`).

**Blocks:** section-08-workflow-integration.

## Files to Modify

- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/src/core/edge.py` -- modify `calculate_placement_edges()`
- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/src/core/settlement.py` -- no changes needed to `adjust_edge_for_deadheat()` itself
- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/config.py` -- add a set of books that are exempt from dead-heat adjustment

## Files to Create

- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/tests/test_kalshi_edge.py` -- new test file (the `TestKalshiDeadHeatBypass` class)

---

## Tests (Write First)

Create `tests/test_kalshi_edge.py` with the following test class. These tests target the per-book dead-heat logic in `calculate_placement_edges()`.

### TestKalshiDeadHeatBypass

```python
class TestKalshiDeadHeatBypass:
    """Dead-heat adjustment is skipped when best_book is Kalshi for placement markets."""

    def test_kalshi_t10_no_deadheat_adj(self):
        """When best_book is 'kalshi' and market is t10, deadheat_adj should be 0.0."""

    def test_kalshi_t20_no_deadheat_adj(self):
        """When best_book is 'kalshi' and market is t20, deadheat_adj should be 0.0."""

    def test_sportsbook_t10_has_deadheat_adj(self):
        """When best_book is 'draftkings' and market is t10, deadheat_adj > 0."""

    def test_kalshi_wins_best_book_via_dh_advantage(self):
        """Kalshi wins 'best book' over a sportsbook with better raw odds due to DH advantage.

        Example scenario:
          your_prob = 0.30
          DraftKings: implied = 0.22, raw_edge = 8.0%, DH adj = -4.4%, effective = 3.6%
          Kalshi:     implied = 0.23, raw_edge = 7.0%, DH adj =  0.0%, effective = 7.0%
          -> Kalshi should be selected as best_book despite worse raw odds.
        """
```

**Test strategy:** Each test should construct minimal outright player data with at least two books (one traditional sportsbook and one "kalshi" entry), then call `calculate_placement_edges()` with `market_type="t10"` or `"t20"` and verify:

1. The returned `CandidateBet.deadheat_adj` is `0.0` when `best_book == "kalshi"`.
2. The returned `CandidateBet.deadheat_adj` is negative (from `config.DEADHEAT_AVG_REDUCTION`) when `best_book` is a traditional sportsbook.
3. In a scenario where a sportsbook has a better raw edge but Kalshi has a better effective (post-DH) edge, Kalshi is chosen as `best_book`.

The test data format must match the outrights data structure that `calculate_placement_edges()` expects: a list of player dicts where each dict has `"player_name"`, `"dg_id"`, `"datagolf"` (nested with `"baseline_history_fit"`), and book columns as American odds strings (e.g., `"draftkings": "+350"`, `"kalshi": "+340"`). You need enough players (at least 10) for the de-vig step to proceed.

To isolate the dead-heat behavior, you can mock or patch `blend_probabilities` and `build_book_consensus` to return predictable values, or construct data where the blended probability is known.

---

## Implementation Details

### Current Behavior (Lines 238-241 of edge.py)

Currently, `calculate_placement_edges()` finds the single best book by raw edge, then applies the dead-heat adjustment once:

```python
# Dead-heat adjustment
adjusted_edge, dh_adj = adjust_edge_for_deadheat(
    best_edge, market_type, best_decimal
)
```

This happens AFTER the best-book selection loop (lines 215-232), meaning the dead-heat adjustment does not influence which book is selected. The adjustment only determines whether the already-chosen best book's edge meets the `min_edge` threshold.

### Required Change: Per-Book Dead-Heat Adjustment

The best-book selection loop must be restructured so that each book candidate gets its own dead-heat-adjusted edge, and the best book is selected based on the **adjusted** edge rather than the raw edge. The key logic change:

**Inside the per-book loop (currently lines 215-232),** for each book candidate:

1. Compute `raw_edge = your_prob - book_prob` (unchanged).
2. Determine whether this book is exempt from dead-heat adjustment. A book is exempt if it appears in a config set (e.g., `config.KALSHI_NO_DEADHEAT_BOOKS = {"kalshi"}`). Kalshi binary contracts pay full value on ties -- there is no dead-heat reduction.
3. If the book is NOT exempt, call `adjust_edge_for_deadheat(raw_edge, market_type, decimal_odds)` to get `(adjusted_edge, dh_adj)`.
4. If the book IS exempt (Kalshi), set `adjusted_edge = raw_edge` and `dh_adj = 0.0`.
5. Select the book with the highest `adjusted_edge` as `best_book`.

After the loop, the winning book's `adjusted_edge`, `raw_edge`, and `dh_adj` are used to populate the `CandidateBet` fields. The `min_edge` threshold check uses `adjusted_edge`.

### Pseudocode for the Modified Loop

```python
best_adjusted_edge = -1
best_book = ""
best_book_prob = 0
best_decimal = 0
best_raw_edge = 0
best_dh_adj = 0.0

for book, devigged_list in book_devigged.items():
    # ... existing validity checks ...
    raw_edge = your_prob - book_prob
    decimal_odds = implied_prob_to_decimal(book_prob)

    # Per-book dead-heat adjustment
    if book in config.KALSHI_NO_DEADHEAT_BOOKS:
        adj_edge = raw_edge
        dh_adj = 0.0
    else:
        adj_edge, dh_adj = adjust_edge_for_deadheat(raw_edge, market_type, decimal_odds)

    all_odds[book] = american_to_decimal(str(player.get(book, "")))

    if adj_edge > best_adjusted_edge:
        best_adjusted_edge = adj_edge
        best_book = book
        best_book_prob = book_prob
        best_decimal = decimal_odds
        best_raw_edge = raw_edge
        best_dh_adj = dh_adj

# After loop: use best_adjusted_edge for threshold check
if best_adjusted_edge < min_edge:
    continue
```

The `CandidateBet` construction then uses:
- `raw_edge=best_raw_edge`
- `deadheat_adj=best_dh_adj` (will be `0.0` for Kalshi, negative for sportsbooks)
- `edge=best_adjusted_edge`

### Config Addition

Add to `config.py`:

```python
# Books exempt from dead-heat adjustment (binary contract payout, no DH reduction)
KALSHI_NO_DEADHEAT_BOOKS = {"kalshi"}
```

This is a set so it can be extended in the future (e.g., if Polymarket also uses binary contracts with no dead-heat reduction).

### Why This Matters (Worked Example)

Consider a T10 market where the system calculates `your_prob = 0.30`:

| Book | Implied Prob | Raw Edge | DH Adj | Effective Edge |
|------|-------------|----------|--------|----------------|
| DraftKings | 0.22 | 8.0% | -4.4% | 3.6% |
| FanDuel | 0.23 | 7.0% | -4.4% | 2.6% |
| Kalshi | 0.23 | 7.0% | 0.0% | **7.0%** |

Under the old logic (global DH adjustment after best-book selection), DraftKings would win on raw edge (8.0%) and then get reduced to 3.6%. Under the new per-book logic, Kalshi wins with an effective edge of 7.0% -- nearly double the DraftKings effective edge -- despite having worse raw odds.

This structural advantage is the primary reason to integrate Kalshi for placement markets.

### What NOT to Change

- `adjust_edge_for_deadheat()` in `settlement.py` does not need modification. It already returns `(raw_edge, 0.0)` for market types not in `DEADHEAT_AVG_REDUCTION` (i.e., "win", "make_cut"). The per-book bypass is handled in `edge.py` before calling this function.
- `calculate_matchup_edges()` already sets `deadheat_adj=0.0` for all matchups (line 420 of current code). No change needed there.
- `calculate_3ball_edges()` also sets `deadheat_adj=0.0`. No change needed.

---

## Verification Checklist

1. All four `TestKalshiDeadHeatBypass` tests pass.
2. Existing tests in `tests/test_settlement.py` still pass (no regressions in settlement logic).
3. For non-Kalshi books in T10/T20 markets, behavior is identical to before (same DH adjustment values).
4. For "win" and "make_cut" markets, no change in behavior (DH adjustment is already 0.0 for these).
5. The `KALSHI_NO_DEADHEAT_BOOKS` config set is defined and contains `"kalshi"`.