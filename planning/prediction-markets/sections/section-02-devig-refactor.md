# Section 02: Devig Refactor — Rename Kalshi Functions to Generic Names

## Overview

This section renames the three Kalshi-specific binary contract conversion functions in `src/core/devig.py` to generic prediction market names. The old names are kept as backward-compatible aliases so existing Kalshi code and tests continue to work without modification. This refactoring must happen early because new Polymarket and ProphetX code will call the generic names.

**Depends on:** section-01-config (for configuration constants to exist, though this section only modifies `devig.py`)

**Blocks:** section-03-edge-updates, section-06-polymarket-pull, section-09-prophetx-pull (all will import the new generic names)

---

## File to Modify

`src/core/devig.py`

---

## Tests First

Create or extend: `tests/test_devig.py`

Add a new test class at the end of the existing test file. The tests verify that the new generic names produce identical output to the old Kalshi-specific names, and that the old names still work as aliases.

### Test stubs

```python
# --- New generic function equivalence ---
# Test: binary_price_to_american() produces same output as kalshi_price_to_american() for a representative set of inputs
# Test: binary_price_to_decimal() produces same output as kalshi_price_to_decimal() for a representative set of inputs
# Test: binary_midpoint() produces same output as kalshi_midpoint() for a representative set of inputs

# --- Aliases still work ---
# Test: kalshi_price_to_american is still callable and returns correct results (backward compat)
# Test: kalshi_price_to_decimal is still callable and returns correct results (backward compat)
# Test: kalshi_midpoint is still callable and returns correct results (backward compat)

# --- Edge cases on new names ---
# Test: binary_price_to_american handles 0.0 input (returns "")
# Test: binary_price_to_american handles 1.0 input (returns "")
# Test: binary_price_to_american handles 0.5 input (returns "+100")
# Test: binary_price_to_american handles string input ("0.30") correctly
# Test: binary_price_to_american handles float-like string ("0.06") same as kalshi version
# Test: binary_price_to_decimal handles None input (returns None)
# Test: binary_price_to_decimal handles empty string (returns None)
# Test: binary_midpoint handles typical bid/ask pair
# Test: binary_midpoint handles None inputs (returns None)

# --- Identity check ---
# Test: binary_price_to_american IS the same function object as kalshi_price_to_american (alias, not copy)
# Test: binary_price_to_decimal IS the same function object as kalshi_price_to_decimal (alias, not copy)
# Test: binary_midpoint IS the same function object as kalshi_midpoint (alias, not copy)
```

The tests should import both the old and new names:

```python
from src.core.devig import (
    binary_price_to_american,
    binary_price_to_decimal,
    binary_midpoint,
    kalshi_price_to_american,
    kalshi_price_to_decimal,
    kalshi_midpoint,
)
```

The identity checks (`binary_price_to_american is kalshi_price_to_american`) confirm the aliasing approach rather than a copy, ensuring any future bugfix to the function applies to both names automatically.

---

## Implementation Details

### What to change in `src/core/devig.py`

The current file has three functions at the bottom (lines 248-305) under the comment `# ---- Kalshi Odds Conversion ----`:

- `kalshi_price_to_american(price_str: str) -> str` (line 248)
- `kalshi_price_to_decimal(price_str: str) -> float | None` (line 272)
- `kalshi_midpoint(bid_str: str, ask_str: str) -> float | None` (line 288)

### Steps

1. **Rename the section comment** from `# ---- Kalshi Odds Conversion ----` to `# ---- Binary Contract Odds Conversion ----`

2. **Rename the three function definitions** to their generic names:
   - `kalshi_price_to_american` becomes `binary_price_to_american`
   - `kalshi_price_to_decimal` becomes `binary_price_to_decimal`
   - `kalshi_midpoint` becomes `binary_midpoint`

3. **Update the docstrings** to reference "binary contract" instead of "Kalshi" specifically. For example, `binary_price_to_american` docstring should say "Convert a binary contract price string (0.00-1.00) to American odds string" rather than mentioning Kalshi.

4. **Add backward-compatible aliases** immediately after the function definitions:

   ```python
   # Backward-compatible aliases (used by existing Kalshi code and tests)
   kalshi_price_to_american = binary_price_to_american
   kalshi_price_to_decimal = binary_price_to_decimal
   kalshi_midpoint = binary_midpoint
   ```

5. **Do NOT modify any other files** in this section. The existing imports in `src/core/edge.py`, `src/pipeline/pull_kalshi.py`, and `tests/test_devig.py` all reference the old `kalshi_*` names, which will continue to work through the aliases.

### Why aliases instead of a full rename

The Kalshi pull code (`src/pipeline/pull_kalshi.py` at line 12), edge calculation code (`src/core/edge.py` at line 26), and existing tests (`tests/test_devig.py` at lines 17-19) all import the old names. A full rename would require touching many files in a single section and risk merge conflicts with other parallel sections. The alias approach is zero-risk: the old names resolve to the exact same function objects.

### Function behavior

The function implementations do not change at all. These functions convert any binary contract price (a probability between 0 and 1) to American odds or decimal odds. They were always generic in behavior — only the naming was Kalshi-specific. The rename makes this explicit.

For reference, the key conversion logic:
- `binary_price_to_american`: takes a string like `"0.06"`, converts to American odds like `"+1567"`
- `binary_price_to_decimal`: takes a string like `"0.06"`, converts to decimal odds like `16.667`
- `binary_midpoint`: takes bid and ask strings like `("0.04", "0.06")`, returns midpoint float `0.05`

---

## Verification Checklist

After implementation, verify:

1. `uv run pytest tests/test_devig.py` passes — all existing Kalshi tests still work through aliases
2. The new generic-name tests also pass
3. No other files were modified in this section
4. Both `from src.core.devig import binary_price_to_american` and `from src.core.devig import kalshi_price_to_american` work and return the same function object
5. `binary_price_to_american is kalshi_price_to_american` evaluates to `True`
