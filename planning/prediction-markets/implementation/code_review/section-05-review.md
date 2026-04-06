# Code Review: Section 05 - Polymarket Tournament Matching & Player Extraction

The implementation is structurally sound and follows the Kalshi matching pattern well, but has several issues ranging from a spec deviation to logic bugs:

1. **MISSING: rapidfuzz fallback (spec deviation)** — The plan explicitly states: 'Use rapidfuzz.fuzz.token_set_ratio if available, else fall back to difflib.SequenceMatcher.' The implementation uses only SequenceMatcher with no attempt to import or use rapidfuzz. This is not just a nice-to-have; token_set_ratio handles word reordering which SequenceMatcher.ratio() does not. The 0.85 threshold was calibrated with token_set_ratio in mind.

2. **Regex strips only one prefix/suffix per pass** — _TITLE_STRIP_PATTERNS uses alternation with anchors. A title like 'PGA Tour: The Masters Winner' would strip only the prefix OR the suffix in a single .sub() call, not both. At 0.85 threshold, leaving ' Winner' on the cleaned title will depress fuzzy scores below threshold.

3. **Pass 1 date matching returns first overlapping PGA event without name validation** — If Polymarket has multiple PGA events running on overlapping weeks, the date overlap pass will return the first one encountered regardless of whether the tournament name matches.

4. **_is_pga_event is overly restrictive for regular-season events** — Events titled 'The Players Championship Winner' or 'Arnold Palmer Invitational Winner' (no 'PGA' in title) would fail the PGA safety check.

5. **Slug-based extraction has a fallthrough bug** — When the market slug does NOT start with the event_slug, the code sets player_part = market_slug (the entire market slug). This means for a slug like 'scottie-scheffler-masters-winner', it would title-case the entire slug.

6. **groupItemTitle filtering is fragile** — The substring check for 'no' would reject 'Justin Thomas' because 'no' is a substring of 'Thomas'. Needs word-boundary awareness.

7. **Missing test for timezone edge cases** — The plan specifies this test but it wasn't implemented.

8. **No type hint for client parameter** — match_all_market_types accepts client as untyped.

9. **extract_player_name uses groupItemTitle as priority 1** — The plan says slug is priority 1, question is priority 2. groupItemTitle is not in the plan. May be a reasonable improvement but is an undocumented deviation.
