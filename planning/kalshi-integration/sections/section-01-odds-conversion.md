# Section 01: Odds Conversion Utilities

## Overview

This section adds three Kalshi-specific conversion functions to the existing `src/core/devig.py` module and extends the existing test file `tests/test_devig.py` with corresponding test classes. These utilities are foundational -- they are used by later sections (section-05 pipeline pull, section-06 pipeline merge) to convert Kalshi dollar-based prices into the American odds and decimal odds formats used throughout the system.

## Background

Kalshi binary contracts are priced in dollars (0.00 to 1.00), where the price represents the cost to buy a YES contract that pays $1 if the outcome occurs. For example, a contract priced at $0.06 implies a 6% probability and corresponds to decimal odds of 16.67 or American odds of +1567.

The system needs three conversions:

1. **Midpoint calculation** -- average of bid and ask prices to get a fair-value probability for consensus blending.
2. **Price to American odds** -- the midpoint probability is converted to an American odds string so Kalshi can be injected as a "book column" recognized by the edge calculator's book discovery logic (which detects string values starting with "+" or "-").
3. **Price to decimal odds** -- the ask price is converted to decimal odds for the `all_book_odds` dictionary, representing what you would actually pay to buy the contract.

## Files to Modify

- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/src/core/devig.py` -- add three new functions
- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/tests/test_devig.py` -- add three new test classes

## Dependencies

None. This section has no dependencies on other sections and can be implemented first (Batch 1).

---

## Tests (write first)

Add the following three test classes to `tests/test_devig.py`. The new functions must be added to the import block at the top of the file alongside the existing imports from `src.core.devig`.

### TestKalshiPriceToAmerican

Tests for converting a Kalshi dollar price string to an American odds string. The conversion formula is: given a probability `p` (the float value of the price string), if `p >= 0.5` return a negative American odds string (`-round(p / (1 - p) * 100)`), and if `p < 0.5` return a positive American odds string (`+round((1 - p) / p * 100)`). At exactly `p = 0.5`, return `"+100"`.

Test cases:

- `'0.06'` produces `'+1567'` (longshot: `(1 - 0.06) / 0.06 * 100 = 1566.67`, rounds to 1567)
- `'0.55'` produces `'-122'` (favorite: `0.55 / 0.45 * 100 = 122.22`, rounds to 122)
- `'0.50'` produces `'+100'` (even money)
- `'0.01'` produces `'+9900'` (extreme longshot)
- `'0.95'` produces `'-1900'` (heavy favorite)
- Result is always an integer string with `+` or `-` prefix (no decimals)
- `None` or empty string input returns `""` (empty string, matching `decimal_to_american` convention)

### TestKalshiPriceToDecimal

Tests for converting a Kalshi dollar price string to decimal odds. The formula is `1.0 / float(price_str)`.

Test cases:

- `'0.06'` produces approximately `16.667`
- `'0.55'` produces approximately `1.818`
- `'0.50'` produces exactly `2.0`
- `'0.0'` or zero-valued input returns `None` (division by zero)
- `'1.0'` returns `None` (probability of 1.0 means decimal odds of 1.0, which is not a valid betting line -- you pay $1 to win $1 with no profit)
- Non-numeric string (e.g., `'abc'`) returns `None`
- `None` input returns `None`

### TestKalshiMidpoint

Tests for computing the midpoint probability from Kalshi bid and ask price strings.

Test cases:

- `('0.04', '0.06')` produces `0.05`
- `('0.50', '0.52')` produces `0.51`
- Missing or `None` bid returns `None`
- Missing or `None` ask returns `None`
- Both empty strings return `None`

---

## Implementation

Add three functions to the bottom of `src/core/devig.py`, after the existing `devig_three_way` function.

### `kalshi_price_to_american(price_str: str) -> str`

Converts a Kalshi dollar price string (e.g., `'0.06'`) to an American odds string (e.g., `'+1567'`).

Steps:
1. If `price_str` is `None`, empty, or not a string, return `""`.
2. Parse to float. If parsing fails, return `""`.
3. If the value is outside the open interval `(0, 1)`, return `""`.
4. Use the existing relationship between probability and American odds:
   - If `prob < 0.5`: American = `+round((1 - prob) / prob * 100)`
   - If `prob > 0.5`: American = `-round(prob / (1 - prob) * 100)`
   - If `prob == 0.5`: return `"+100"`
5. Return the formatted string with sign prefix.

Note: this is the inverse of what `parse_american_odds` does. The function `decimal_to_american` already exists and converts decimal odds to American. An alternative implementation could use `decimal_to_american(1.0 / prob)` -- this produces equivalent results and reuses existing code. Either approach is acceptable; the key constraint is that the round-trip `parse_american_odds(kalshi_price_to_american(p))` should recover the original probability to within rounding tolerance.

### `kalshi_price_to_decimal(price_str: str) -> float | None`

Converts a Kalshi dollar price string to decimal odds.

Steps:
1. If `price_str` is `None`, empty, or not a string, return `None`.
2. Parse to float. If parsing fails, return `None`.
3. If the value is `<= 0` or `>= 1.0`, return `None`.
4. Return `1.0 / prob`.

This is equivalent to `implied_prob_to_decimal` but accepts a string input and handles Kalshi-specific edge cases. Alternatively, this could simply call `implied_prob_to_decimal(float(price_str))` with appropriate guards.

### `kalshi_midpoint(bid_str: str, ask_str: str) -> float | None`

Computes the midpoint probability from Kalshi bid and ask dollar prices.

Steps:
1. If either input is `None`, empty, or not a string, return `None`.
2. Parse both to float. If either fails, return `None`.
3. Return `(bid + ask) / 2.0`.

No range validation is strictly necessary on the midpoint itself since bid and ask are both in `[0, 1]` and their average will be too. However, if either parsed value is negative, returning `None` is a reasonable safety guard.

---

## Precision Notes

When the midpoint is converted to American odds and later parsed back to a probability by the edge calculator, there is minor rounding loss. For example, a 6% midpoint: `0.06` becomes `"+1567"` which parses back to `100 / 1667 = 0.05998...`. This ~0.002 percentage point error is acceptable and consistent with the rounding applied to all other books via `parse_american_odds`.

## Verification

After implementation, run:

```
pytest tests/test_devig.py -v
```

All existing tests should continue to pass. The three new test classes (`TestKalshiPriceToAmerican`, `TestKalshiPriceToDecimal`, `TestKalshiMidpoint`) should all pass.