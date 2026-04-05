# Section 06: Pipeline Merge -- Merging Kalshi Data into Existing Data Structures

## Overview

This section implements the merge functions that inject Kalshi outright and matchup data as additional book columns into the existing DataGolf data structures. After section-05 pulls raw Kalshi data, these merge functions convert and inject it so the existing edge calculator (`src/core/edge.py`) picks up Kalshi naturally as another book -- no modifications to edge.py's core book-discovery logic are needed (except for dead-heat, handled in section-07).

The key design principle is **dual-price usage**:
- **Midpoint probability** (average of bid and ask) is converted to an American odds string and injected as the `"kalshi"` book column. This is what the edge calculator reads for de-vig and consensus blending.
- **Ask probability** (the price you would actually pay) is stored as supplemental data so that `all_book_odds` in the final `CandidateBet` reflects the real cost of buying the contract, not the midpoint.

## Dependencies

- **Section 01 (Odds Conversion):** Provides `kalshi_price_to_american()`, `kalshi_price_to_decimal()`, and `kalshi_midpoint()` in `src/core/devig.py`.
- **Section 03 (Config Schema):** Provides `KALSHI_SERIES_TICKERS`, `KALSHI_MIN_OPEN_INTEREST`, `KALSHI_MAX_SPREAD`, and the `"kalshi"` entry in `BOOK_WEIGHTS`.
- **Section 05 (Pipeline Pull):** Provides `pull_kalshi_outrights()` and `pull_kalshi_matchups()` which return the normalized Kalshi data dicts that these merge functions consume.

## Files to Create/Modify

| File | Action |
|------|--------|
| `src/pipeline/pull_kalshi.py` | Add `merge_kalshi_into_outrights()` and `merge_kalshi_into_matchups()` functions (same module as the pull functions from section-05) |
| `tests/test_pull_kalshi.py` | Add `TestMergeKalshiIntoOutrights` and `TestMergeKalshiIntoMatchups` test classes |
| `tests/test_kalshi_edge.py` | New file with `TestKalshiDevigBehavior`, `TestKalshiMatchupExclusion`, `TestKalshiAllBookOdds` test classes |

## Tests First

All tests go in two files. Write these before implementing.

### `tests/test_pull_kalshi.py` -- Merge Tests

Add these test classes to the same file created in section-05.

```python
class TestMergeKalshiIntoOutrights:
    """Tests for merge_kalshi_into_outrights()."""

    def test_adds_kalshi_key_with_american_odds_to_matching_players(self):
        """Matching player gets a 'kalshi' key whose value is an American odds string
        (starts with '+' or '-'), derived from the midpoint probability."""

    def test_american_odds_derived_from_midpoint_not_ask(self):
        """Verify the injected American odds come from (bid+ask)/2, not from ask alone.
        E.g., bid=0.04, ask=0.06 -> mid=0.05 -> '+1900', NOT ask=0.06 -> '+1567'."""

    def test_unmatched_kalshi_players_skipped_no_crash(self):
        """Kalshi players not in the DG data are silently skipped."""

    def test_existing_book_columns_not_modified(self):
        """Other book columns (draftkings, fanduel, etc.) remain unchanged after merge."""

    def test_players_without_kalshi_data_have_no_kalshi_key(self):
        """DG players with no corresponding Kalshi contract get no 'kalshi' key added."""

    def test_stores_ask_data_for_bettable_edge(self):
        """Each player record gets a '_kalshi_ask_prob' field (float) storing
        the raw ask probability for use in all_book_odds calculation."""
```

```python
class TestMergeKalshiIntoMatchups:
    """Tests for merge_kalshi_into_matchups()."""

    def test_injects_kalshi_into_matchup_odds_dict(self):
        """Matched H2H pairings get a 'kalshi' entry in their odds dict,
        with 'p1' and 'p2' American odds strings."""

    def test_unmatched_pairings_skipped(self):
        """H2H pairings where either player doesn't match are silently skipped."""

    def test_kalshi_odds_same_format_as_other_books(self):
        """The 'kalshi' entry in odds_dict has the same {'p1': str, 'p2': str}
        structure as other book entries like 'draftkings'."""
```

### `tests/test_kalshi_edge.py` -- Edge Behavior Tests

New test file. These tests verify that the edge calculator handles merged Kalshi data correctly without changes to edge.py's core logic (other than dead-heat, covered in section-07).

```python
class TestKalshiDevigBehavior:
    """Verify de-vig math works correctly on Kalshi midpoint data."""

    def test_power_devig_on_midpoint_field_k_near_one(self):
        """When Kalshi midpoints sum to ~1.0 for a winner market,
        power_devig returns k approximately 1.0 and probabilities nearly unchanged."""

    def test_devig_independent_on_t10_midpoints_nearly_unchanged(self):
        """T10 midpoints summing to ~10 pass through devig_independent with
        minimal adjustment."""

    def test_mixed_field_traditional_plus_kalshi_reasonable(self):
        """A field containing both traditional sportsbook odds and Kalshi midpoint
        odds produces sensible de-vigged results for all books."""
```

```python
class TestKalshiMatchupExclusion:
    """Verify Kalshi is excluded from matchup consensus but included for betting."""

    def test_kalshi_excluded_from_matchup_book_consensus(self):
        """When computing book_consensus_p1 for matchup blending,
        Kalshi's fair probabilities are NOT included in the average."""

    def test_kalshi_included_in_matchup_best_edge_evaluation(self):
        """Kalshi IS evaluated when finding the best-edge book for matchups.
        If Kalshi has the highest edge, it can be selected."""

    def test_kalshi_can_be_best_book_for_matchup(self):
        """A CandidateBet can have best_book='kalshi' for a tournament_matchup."""
```

```python
class TestKalshiAllBookOdds:
    """Verify all_book_odds stores ask-based decimal odds for Kalshi."""

    def test_all_book_odds_includes_kalshi_with_ask_decimal(self):
        """The all_book_odds dict in CandidateBet includes 'kalshi' with
        decimal odds derived from the ask price, not the midpoint."""

    def test_kalshi_decimal_differs_from_midpoint_derived(self):
        """Ask-based decimal odds are lower (worse for bettor) than midpoint-derived
        decimal odds, because ask > midpoint probability."""
```

## Implementation Details

### Merge Function: Outrights

Add `merge_kalshi_into_outrights()` to `src/pipeline/pull_kalshi.py`.

**Function signature:**

```python
def merge_kalshi_into_outrights(
    dg_outrights: dict[str, list[dict]],
    kalshi_outrights: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """Inject Kalshi data as book columns into DG outright data.

    For each market type (win, t10, t20), finds matching players between
    the DG data and Kalshi data by canonical player name, then:
    1. Adds a "kalshi" key with American odds string (from midpoint prob)
    2. Adds a "_kalshi_ask_prob" key with the raw ask probability (float)

    The "kalshi" key uses American odds format so the edge calculator's
    book-discovery logic (which looks for strings starting with +/-) 
    picks it up automatically.

    The "_kalshi_ask_prob" key is prefixed with underscore so it's ignored
    by book discovery but available for all_book_odds computation.

    Args:
        dg_outrights: Output from pull_all_outrights(), keyed by market
            (e.g., {"win": [player_records], "top_10": [...], ...})
        kalshi_outrights: Output from pull_kalshi_outrights(), keyed by market
            (e.g., {"win": [...], "t10": [...], "t20": [...]})

    Returns:
        The same dg_outrights dict, mutated in-place with Kalshi columns added.
    """
```

**Key implementation details:**

1. **Market type mapping.** DG uses `"top_10"` / `"top_20"` while Kalshi pull returns `"t10"` / `"t20"`. The merge function maps between these: `{"win": "win", "top_10": "t10", "top_20": "t20"}`.

2. **Player matching.** For each DG player record, look up their `player_name` in the Kalshi data. Build a lookup dict from the Kalshi list keyed by normalized player name for O(1) matching. Use case-insensitive, stripped comparison.

3. **Midpoint to American conversion.** For a matched player, take the Kalshi record's `kalshi_mid_prob` (a float, e.g., 0.05) and convert it to an American odds string using `kalshi_price_to_american(str(mid_prob))`. Inject this as `player_record["kalshi"] = "+1900"`.

4. **Ask probability storage.** Also store `player_record["_kalshi_ask_prob"] = kalshi_record["kalshi_ask_prob"]`. The underscore prefix ensures the edge calculator's `SKIP_KEYS` or string-format check skips it during book discovery, but it can be read when building `all_book_odds`.

5. **Non-destructive.** Only add keys; never remove or modify existing keys. Players without Kalshi data get no new keys added.

6. **Metadata keys preserved.** The `_event_name` and other metadata keys in `dg_outrights` pass through untouched.

### Merge Function: Matchups

Add `merge_kalshi_into_matchups()` to `src/pipeline/pull_kalshi.py`.

**Function signature:**

```python
def merge_kalshi_into_matchups(
    dg_matchups: list[dict],
    kalshi_matchups: list[dict],
) -> list[dict]:
    """Inject Kalshi H2H data into DG matchup odds dicts.

    For each DG matchup, finds a matching Kalshi H2H pairing (by player
    names, order-independent), then adds a "kalshi" entry to the matchup's
    odds dict with p1/p2 American odds strings.

    Important: Kalshi is added as a bettable outlet only. The edge calculator
    should EXCLUDE Kalshi from matchup book consensus blending but INCLUDE
    it in the best-edge evaluation. This exclusion logic lives in edge.py
    (section-08 wiring), not here -- this function just injects the data.

    Args:
        dg_matchups: List of matchup dicts from DG API, each with
            "p1_player_name", "p2_player_name", and "odds" dict.
        kalshi_matchups: Output from pull_kalshi_matchups(), list of
            {"p1_name", "p2_name", "p1_prob", "p2_prob", ...} dicts.

    Returns:
        The same dg_matchups list, mutated in-place with Kalshi odds added.
    """
```

**Key implementation details:**

1. **Pairing matching.** Build a lookup from Kalshi matchups keyed by frozenset of normalized player names `{p1_name_lower, p2_name_lower}`. For each DG matchup, check if `frozenset({p1_player_name_lower, p2_player_name_lower})` exists in the lookup.

2. **Player order alignment.** The DG matchup has a fixed p1/p2 order. The Kalshi matchup may have the players in opposite order. When injecting, check which Kalshi player matches DG's p1 and assign probabilities accordingly.

3. **Probability to American odds.** Convert `p1_prob` and `p2_prob` from the Kalshi matchup to American odds strings. These are the ask-based probabilities (what you'd pay). For matchups, there is no midpoint/ask distinction since both sides are directly offered prices. Use `kalshi_price_to_american(str(prob))` for each side.

4. **Odds dict format.** The injected entry follows the same format as other books in the DG matchup `odds` dict:
   ```python
   matchup["odds"]["kalshi"] = {"p1": "+150", "p2": "-180"}
   ```
   where p1/p2 correspond to the DG matchup's p1/p2, not Kalshi's original ordering.

### How the Edge Calculator Consumes Merged Data

After merging, the DG outright data flows into `calculate_placement_edges()` unchanged. Here is how each step handles Kalshi:

**Step 1 -- Book discovery:** The edge calculator iterates player record keys, looking for string values starting with `"+"` or `"-"`. The injected `"kalshi": "+1900"` string matches this pattern, so `"kalshi"` is added to `books_in_data`. The `"_kalshi_ask_prob"` key is a float, not a string starting with +/-, so it is naturally excluded.

**Step 2 -- De-vig:** For winner markets, `power_devig()` is called on Kalshi's full field of midpoint-derived American odds. Because midpoints sum to approximately 1.0, the power de-vig exponent k will be close to 1.0 and probabilities will be nearly unchanged. For T10/T20, `devig_independent()` normalizes toward the expected outcome count (10 or 20), and midpoint sums should approximate these values, so minimal adjustment occurs. No special-case code is needed.

**Step 3 -- Consensus and edge:** `build_book_consensus()` in `src/core/blend.py` uses `BOOK_WEIGHTS` to weight each book. Since section-03 adds `"kalshi": 2` for win and `"kalshi": 1` for placement to the weight config, Kalshi participates in consensus with the configured weight. No changes to blend.py are needed.

**Step 3b -- all_book_odds override for Kalshi:** In `calculate_placement_edges()`, when building the `all_odds` dict (line ~226 in the current code), the standard path reads `american_to_decimal(str(player.get(book, "")))` for each book. For Kalshi, this would convert the midpoint-based American odds back to decimal, which is not what we want -- we want the ask-based decimal odds (the actual price to buy). 

This requires a small modification to edge.py's `all_odds` construction: when the book is `"kalshi"` and the player record has a `"_kalshi_ask_prob"` key, use `kalshi_price_to_decimal(str(ask_prob))` instead of the standard American-to-decimal conversion. This gives the actual bettable odds rather than the midpoint-derived odds.

Specifically, modify the `all_odds[book]` assignment in `calculate_placement_edges()`:

```python
# Inside the per-book loop in Step 3:
if book == "kalshi" and "_kalshi_ask_prob" in player:
    all_odds[book] = kalshi_price_to_decimal(str(player["_kalshi_ask_prob"]))
else:
    all_odds[book] = american_to_decimal(str(player.get(book, "")))
```

This is the only modification to `edge.py` needed for this section. Import `kalshi_price_to_decimal` at the top of edge.py.

### Matchup Consensus Exclusion

For matchups, the plan specifies that Kalshi should be **excluded from book consensus blending** but **included in best-edge evaluation**. In the current `calculate_matchup_edges()`, the book consensus is computed at line ~363:

```python
book_p1_probs = {b: d["p1_fair"] for b, d in all_book_odds.items()}
book_consensus_p1 = sum(book_p1_probs.values()) / len(book_p1_probs)
```

This needs modification to exclude Kalshi:

```python
book_p1_probs = {b: d["p1_fair"] for b, d in all_book_odds.items() if b != "kalshi"}
```

The best-edge loop that follows already iterates over all books in `all_book_odds` (including Kalshi), so no change is needed there. Kalshi can still be selected as `best_book` for matchup bets.

### Summary of edge.py Modifications (This Section)

1. Add import: `from src.core.devig import kalshi_price_to_decimal` (add to existing import line)
2. In `calculate_placement_edges()`, modify the `all_odds[book]` assignment to use ask-based decimal for Kalshi
3. In `calculate_matchup_edges()`, exclude `"kalshi"` from `book_p1_probs` dict comprehension

These are minimal, targeted changes. The dead-heat per-book logic is handled separately in section-07.

### Edge Cases and Error Handling

- **Empty Kalshi data.** If `kalshi_outrights` is empty or missing a market key, the merge function simply does nothing for that market. No error raised.
- **Duplicate player names.** If Kalshi somehow has duplicate entries for the same player, take the first match. Log a warning if this happens.
- **Price edge cases.** If a Kalshi record has `kalshi_mid_prob` of 0 or 1, skip it (cannot convert to finite American odds). The conversion functions from section-01 handle this by returning None/empty string.
- **Non-standard market keys.** The merge function only processes known market mappings (`win`, `top_10`, `top_20`). Unknown keys in either dict are ignored.