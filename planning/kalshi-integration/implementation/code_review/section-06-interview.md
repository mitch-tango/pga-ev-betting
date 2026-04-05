# Section 06 Code Review Interview

## Auto-fixes Applied

- **#1 (Kelly sizing with wrong decimal):** Fixed `best_decimal` to use ask-based `bettable_decimal` when Kalshi is the best book, not midpoint-derived `implied_prob_to_decimal`. This prevents oversizing Kalshi bets.

## Let Go

- **#2:** Matchup American->decimal round-trip is acceptable and lossless to FP precision
- **#3, #4:** Integration test assertions are data-dependent by nature; core logic tested at unit level
- **#5, #6, #7:** Low severity, not blocking
