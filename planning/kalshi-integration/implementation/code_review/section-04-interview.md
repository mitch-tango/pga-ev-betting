# Code Review Interview: Section 04 - Tournament Matching

## Triage Summary

| # | Finding | Decision |
|---|---------|----------|
| 1 | Missing warning logs | **Auto-fix** — added logger.warning calls |
| 2 | H2H "beat" regex too greedy | **Auto-fix** — tightened to stop at "in/at/during" |
| 3 | Dead _NAME_SUFFIXES code | **Auto-fix** — removed |
| 4 | Fuzzy matching asymmetric strings | **Fix** — user chose strip title prefixes |
| 5 | Superficial wrapper tests | **Let go** — tests verify integration point |
| 6 | No match_all_series tests | **Let go** — thin orchestrator |
| 7 | _PGA_INDICATORS too long | **Fix** — user chose plan's 5 core indicators |
| 8 | Missing .get() for event_ticker | **Auto-fix** — switched to .get() |

## Fixes Applied

1. **Warning logs:** Added logger.warning in extract_player_name_outright and extract_player_names_h2h on parse failure
2. **H2H regex:** Changed "beat" pattern to stop capturing at "in/at/during" keywords
3. **Dead code:** Removed unused _NAME_SUFFIXES set
4. **Title normalization:** Added _TITLE_STRIP_PATTERNS regex to strip "PGA Tour:", "Winner", "Top N" from titles before fuzzy comparison
5. **PGA indicators:** Trimmed from 30+ to 6 core indicators per plan
6. **Defensive access:** Changed event["event_ticker"] to event.get("event_ticker") with None checks
