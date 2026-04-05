# Section 06 Code Review

## HIGH

### 1. Kelly sizing uses wrong decimal when Kalshi is best book for outrights
`best_decimal = decimal_odds` at edge.py:232 carries midpoint-derived decimal into Kelly sizing. But the actual bettable price is the ask-based decimal (worse odds). System will oversize Kalshi bets. Fix: override `decimal_odds` with ask-based decimal when `book == "kalshi"`.

### 2. Matchup American->decimal round-trip
Matchup merge converts ask probs to American, then edge.py converts back to decimal. Should be lossless but fragile.

## MEDIUM

### 3. Weak edge tests with conditional guards
Several tests guarded by `if results_with and results_without` or `if ... "kalshi" in r.all_book_odds` — could pass vacuously.

### 4. Matchup best_book tests only assert list type
Don't verify Kalshi was actually selected as best_book.

## LOW

### 5. No duplicate player name warning
### 6. No boundary guard on matchup probs (0 or 1) before conversion
### 7. Float-to-string for kalshi_price_to_american — works but could be brittle
