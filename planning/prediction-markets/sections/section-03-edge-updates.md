# Section 03: Edge Calculation Updates

## Overview

This section generalizes `src/core/edge.py` to support Polymarket and ProphetX (and any future prediction markets) without per-book conditional logic. Three changes are required:

1. **Update the dead-heat bypass config reference** from `KALSHI_NO_DEADHEAT_BOOKS` to `NO_DEADHEAT_BOOKS`.
2. **Generalize ask-based pricing** so any book with a `_{book}_ask_prob` key in the player record uses that value for bettable decimal computation (replacing the current Kalshi-only `if book == "kalshi"` check).
3. **Validate ask probability values** before using them.

**Depends on:** section-01-config (for `NO_DEADHEAT_BOOKS` set and updated `BOOK_WEIGHTS`), section-02-devig-refactor (for renamed `binary_price_to_decimal` function).

**Blocks:** section-10-workflow (workflow scripts rely on correct edge calculation for all markets).

---

## Files to Modify

| File | Change |
|------|--------|
| `config.py` | Rename `KALSHI_NO_DEADHEAT_BOOKS` to `NO_DEADHEAT_BOOKS`, add `"polymarket"` (done in section-01, but update reference here if alias needs cleanup) |
| `src/core/edge.py` | Generalize ask-based pricing, update dead-heat config reference |

## Files to Create

| File | Purpose |
|------|---------|
| `tests/test_edge_prediction_markets.py` | Tests for generalized edge calculation with multiple prediction markets |

---

## Tests (Write First)

All tests go in `tests/test_edge_prediction_markets.py`.

```python
# tests/test_edge_prediction_markets.py

# --- Dead-heat bypass ---
# Test: NO_DEADHEAT_BOOKS used instead of KALSHI_NO_DEADHEAT_BOOKS
#   Assert config has NO_DEADHEAT_BOOKS attribute.

# Test: Polymarket edges skip dead-heat reduction
#   Build a player record with "polymarket" American odds and "_polymarket_ask_prob".
#   Run calculate_placement_edges for market_type="t10". Verify the resulting
#   CandidateBet for polymarket has deadheat_adj == 0.0.

# Test: ProphetX edges apply dead-heat reduction (not in NO_DEADHEAT_BOOKS)
#   Build a player record with "prophetx" American odds.
#   Run calculate_placement_edges for market_type="t10". Verify the resulting
#   CandidateBet has deadheat_adj != 0.0 (reduction applied).

# Test: Kalshi edges still skip dead-heat reduction (regression)
#   Same test pattern as existing test_kalshi_edge.py. Verify kalshi
#   best_book has deadheat_adj == 0.0.

# --- Generalized ask-based pricing ---
# Test: edge calc uses _polymarket_ask_prob for bettable decimal
#   Build player record with "polymarket": "+400" and "_polymarket_ask_prob": 0.22.
#   Verify best_odds_decimal == binary_price_to_decimal("0.22"),
#   NOT american_to_decimal("+400").

# Test: edge calc uses _prophetx_ask_prob for bettable decimal (when binary)
#   Build player record with "prophetx": "+300" and "_prophetx_ask_prob": 0.28.
#   Verify bettable decimal uses the ask prob.

# Test: edge calc uses _kalshi_ask_prob for bettable decimal (regression)
#   Build player record with "kalshi": "+1900" and "_kalshi_ask_prob": 0.06.
#   Verify bettable decimal == binary_price_to_decimal("0.06").

# Test: edge calc skips ask-based pricing when ask key not present (traditional book)
#   Build player record with "draftkings": "+400" (no _draftkings_ask_prob key).
#   Verify bettable decimal uses standard american_to_decimal conversion.

# Test: edge calc validates ask prob is numeric and in (0, 1), warns on invalid
#   Build player record with "_polymarket_ask_prob": 1.5 (invalid).
#   Verify edge calc falls back to standard pricing, does not crash.
#   Build player record with "_polymarket_ask_prob": "not_a_number".
#   Verify same fallback behavior.

# Test: Polymarket fee rate already reflected in stored _polymarket_ask_prob
#   Build player with _polymarket_ask_prob = 0.222 (0.22 ask + 0.002 fee).
#   Verify edge calc uses 0.222 directly without further adjustment.

# --- Consensus ---
# Test: blend.py picks up polymarket and prophetx from BOOK_WEIGHTS automatically
#   Verify BOOK_WEIGHTS["win"] contains "polymarket" and "prophetx" keys.

# Test: consensus calculation works with 0, 1, 2, or 3 prediction markets present
#   Build player records with varying subsets of kalshi/polymarket/prophetx odds.
#   Verify no crashes and edges are calculated correctly.
```

### Test Data Pattern

Each test builds a minimal outrights list suitable for `calculate_placement_edges()`. A player record after merge looks like:

```python
{
    "player_name": "Scottie Scheffler",
    "dg_id": "18417",
    "datagolf": {"baseline_history_fit": "+300"},
    "draftkings": "+350",
    "fanduel": "+380",
    "kalshi": "+355",
    "_kalshi_ask_prob": 0.24,
    "polymarket": "+400",
    "_polymarket_ask_prob": 0.222,  # fee-adjusted
    "prophetx": "+300",
    "_prophetx_ask_prob": 0.28,    # only present if binary format
}
```

The field needs at least 10 players with valid odds for de-vig to work. Test fixtures should include ~15 players.

---

## Implementation Details

### Change 1: Update Dead-Heat Reference in `edge.py`

**Location:** `src/core/edge.py`, line 239.

Current code:
```python
if book in config.KALSHI_NO_DEADHEAT_BOOKS:
```

Change to:
```python
if book in config.NO_DEADHEAT_BOOKS:
```

This is the only place in `edge.py` that references the config set name. The logic itself (skip dead-heat adjustment for books in the set) remains identical.

### Change 2: Generalize Ask-Based Pricing in `edge.py`

**Location:** `src/core/edge.py`, lines 228-232.

Current code (Kalshi-specific):
```python
if book == "kalshi" and "_kalshi_ask_prob" in player:
    bettable_decimal = kalshi_price_to_decimal(
        str(player["_kalshi_ask_prob"]))
    all_odds[book] = bettable_decimal
```

Replace with a generalized check:
```python
ask_key = f"_{book}_ask_prob"
if ask_key in player:
    ask_val = player[ask_key]
    # Validate: must be numeric and in (0, 1)
    if isinstance(ask_val, (int, float)) and 0 < float(ask_val) < 1:
        bettable_decimal = binary_price_to_decimal(str(ask_val))
        all_odds[book] = bettable_decimal
    else:
        # Invalid ask prob -- fall back to standard pricing
        import logging
        logging.getLogger(__name__).warning(
            "Invalid %s value %r for %s, using standard pricing",
            ask_key, ask_val, player.get("player_name", "unknown"))
        bettable_decimal = implied_prob_to_decimal(book_prob)
        all_odds[book] = american_to_decimal(str(player.get(book, "")))
else:
    bettable_decimal = implied_prob_to_decimal(book_prob)
    all_odds[book] = american_to_decimal(str(player.get(book, "")))
```

Key points:
- The pattern `f"_{book}_ask_prob"` produces `_kalshi_ask_prob`, `_polymarket_ask_prob`, `_prophetx_ask_prob` automatically.
- Validation prevents crashes from bad values. Fallback uses standard pricing path.
- `binary_price_to_decimal` is the renamed version from section-02-devig-refactor.

### Change 3: Update Import in `edge.py`

**Location:** `src/core/edge.py`, line 23.

Change `kalshi_price_to_decimal` to `binary_price_to_decimal` in the import statement. Either name works (section-02 keeps aliases), but new code should use the generic name.

---

## Design Rationale

### Why generalize instead of per-market conditionals

The current `if book == "kalshi"` would require adding `or book == "polymarket" or book == "prophetx"`. The `f"_{book}_ask_prob"` pattern is data-driven: any book that stores an ask probability key gets ask-based pricing automatically.

### Fee adjustment happens at merge time, not edge time

`_polymarket_ask_prob` already includes the fee adjustment (ask + 0.002) when stored by the Polymarket merge step (section-06). Edge.py doesn't need to know about fees.

### ProphetX ask prob is conditional

ProphetX may return American odds directly. When American, the merge step (section-09) will NOT store `_prophetx_ask_prob`, and edge.py naturally uses the standard `implied_prob_to_decimal(book_prob)` path.

---

## Verification Checklist

1. `config.NO_DEADHEAT_BOOKS` exists and contains `{"kalshi", "polymarket"}`
2. `edge.py` references `config.NO_DEADHEAT_BOOKS` (not `KALSHI_NO_DEADHEAT_BOOKS`)
3. `edge.py` uses the generalized `f"_{book}_ask_prob"` pattern
4. `edge.py` imports `binary_price_to_decimal`
5. Ask probability validation rejects values outside (0, 1) with a logged warning
6. All existing Kalshi edge tests pass without modification (regression)
7. New tests for Polymarket and ProphetX dead-heat and ask-based pricing pass
