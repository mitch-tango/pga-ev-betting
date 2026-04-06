# Code Review: section-03-edge-updates

## Findings

1. **Import ordering** (medium): `logger = logging.getLogger(__name__)` is between import blocks
2. **Bool subclass** (medium): `isinstance(True, (int, float))` is True — booleans pass isinstance check
3. **Numeric strings** (medium): String ask_prob values like "0.15" silently fall to warning path — behavioral regression from old Kalshi code which accepted strings
4. **Weak invalid-input tests** (medium): caplog captured but never inspected; no fallback verification
5. **Missing boundary tests** (low): No tests for 0.0, 1.0, negative, near-boundary values
6. **Integer ask_prob dead code** (low): No integers exist in (0,1) exclusive, so `int` in isinstance is dead code
7. **Duplicated fallback logic** (low): Lines 244-245 identical to 247-248
8. **ProphetX design question** (low): Not in NO_DEADHEAT_BOOKS but uses binary_price_to_decimal — intentional per plan
