# Code Review: Section 08 - ProphetX Matching

1. **Pass 1 returns any date-overlapping event regardless of name quality** — No minimum name threshold for date-matched events.
2. **RapidFuzz not attempted** — Uses only SequenceMatcher (not token-based).
3. **extract_player_name_outright doesn't try direct market fields** — Only checks competitors array.
4. **_clean_name/_is_pga_event duplicated across 3 files** — Design smell.
5. **Silently skips events with only start date** — No fallback or warning.
6. **classify_markets H2H detection fragile** — Ordering could misclassify some markets.
7. **No test for wrong date-overlap selection**.
8. **_parse_date doesn't handle all formats** — Unix timestamps, other formats.
9. **Config bookkeeping** — section-08 not yet marked complete (expected at this stage).
