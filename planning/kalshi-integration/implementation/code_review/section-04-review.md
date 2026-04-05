# Code Review: Section 04 - Tournament Matching

## Critical Issues

### 1. Missing warning logs on extraction failure (Medium)
extract_player_name_outright() and extract_player_names_h2h() return None without logging. Plan requires warnings.

### 2. Regex greediness bug in H2H "beat" pattern (High)
"Will Tiger Woods beat Phil Mickelson in the Masters?" — second capture group grabs trailing context.

### 3. _NAME_SUFFIXES is dead code (Low)
Defined but never referenced anywhere.

### 4. Fuzzy matching compares asymmetric strings (Medium)
Short tournament name vs long Kalshi title produces low scores. Should normalize title first.

### 5. Tests for PlayerNameMatching are superficial (Medium)
Tests just verify a one-line wrapper calls through. test_fuzzy_match passes exact name, not variant.

### 6. match_all_series has no tests (Medium)
No test coverage. Bare except Exception could hide auth/rate limit failures.

### 7. _PGA_INDICATORS list is too long (Low-Medium)
Plan specified 5 items. Implementation has 30+ sponsor-specific names that change often.

### 8. No error handling on missing event_ticker key (Medium)
Direct dict access event["event_ticker"] will crash on malformed events.
