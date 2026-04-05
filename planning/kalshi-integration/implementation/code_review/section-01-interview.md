# Code Review Interview: Section 01 - Odds Conversion

## Triage

| # | Finding | Severity | Action |
|---|---------|----------|--------|
| 1 | Midpoint bid/ask > 1.0 validation | Medium | Auto-fix |
| 2 | Crossed market (bid > ask) | Low | Let go |
| 3 | Float equality prob == 0.5 | Low | Let go |
| 4 | Missing round-trip test | Medium | Auto-fix |
| 5 | Integer string inputs | Low | Let go |
| 6 | Non-string input tests | Low | Let go |
| 7 | Missing empty-string test for decimal | Low | Auto-fix |

## User Decision

User approved the triage: auto-fix items 1, 4, 7; let go of items 2, 3, 5, 6.

## Auto-fixes Applied

1. Added `bid > 1.0 or ask > 1.0` guard to `kalshi_midpoint` + 2 tests
2. Added `TestKalshiRoundTrip` class with 5 round-trip tests
3. Added `test_empty_string` to `TestKalshiPriceToDecimal`

## Result

68 tests passing (39 existing + 29 new Kalshi tests including round-trip).
