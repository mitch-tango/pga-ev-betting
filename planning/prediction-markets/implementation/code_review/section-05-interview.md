# Code Review Interview: Section 05 - Polymarket Matching

## Findings Triage

### Asked User
- **#3 Date overlap without name validation**: User confirmed — add name-match preference. Happens 2-3 times/year with overlapping events. → FIXED: Pass 1 now collects all overlapping candidates and sorts by name score.
- **#4 _is_pga_event too restrictive**: User chose "any event not in exclusion list" approach. → FIXED: Changed to exclusion-only logic (LIV, DPWT, LPGA, Korn Ferry).

### Auto-Fixed
- **#2 Regex strips only one prefix/suffix**: Split into two separate patterns (_TITLE_PREFIX_PATTERN, _TITLE_SUFFIX_PATTERN) applied sequentially.
- **#5 Slug fallthrough bug**: Now only extracts from slug when market_slug.startswith(event_slug). Else skips to question regex.
- **#6 groupItemTitle substring check**: Changed from `in` to `re.search(r"\b...\b")` for word-boundary matching. "Justin Thomas" no longer falsely rejected.

### Let Go
- **#1 rapidfuzz**: Not installed; SequenceMatcher sufficient for current use.
- **#7 Timezone edge case test**: Date-only comparison handles this.
- **#8 Type hint for client**: Consistent with Kalshi module.
- **#9 groupItemTitle priority**: Reasonable improvement; Polymarket reliably provides it.

## Tests Added
- `test_prefers_best_name_among_overlapping_dates` — verifies name preference when multiple events overlap
- `test_accepts_non_excluded_non_pga_titled_event` — verifies events without "PGA" in title are accepted

## Final: 18 tests passing
