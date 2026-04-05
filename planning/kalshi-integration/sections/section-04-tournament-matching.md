# Section 04: Tournament Matching

## Overview

This section implements the logic to (a) match a Kalshi event to the current DataGolf tournament and (b) extract and match player names from Kalshi contract titles to DataGolf canonical names. The result is a set of pure functions and a thin database integration layer that the pipeline pull module (section 05) calls to align Kalshi data with the existing system.

**Files to create:**
- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/src/pipeline/kalshi_matching.py`
- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/tests/test_kalshi_matching.py`

**Dependencies (must be completed first):**
- **Section 02 (Kalshi Client):** `KalshiClient.get_golf_events()` is called to fetch open events for matching. The matching module receives event data as dicts, so it can be tested with mock data independently.
- **Section 03 (Config Schema):** `KALSHI_SERIES_TICKERS` dict mapping market types to series tickers (e.g., `{"win": "KXPGATOUR", "t10": "KXPGATOP10", ...}`).

**Existing code this builds on:**
- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/src/normalize/players.py` -- contains `resolve_player()` which handles alias lookup, fuzzy matching, and alias creation in Supabase. The Kalshi matching module uses this with `source="kalshi"`.
- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/src/parsers/start_merger.py` -- reference for how Start sportsbook names are matched to DG names via last-name + similarity scoring.

---

## Tests First -- `tests/test_kalshi_matching.py`

Write these tests before implementing. All tests use mock data (no live API or database calls). Use `unittest.mock.patch` to mock Supabase/database calls where needed.

### TestTournamentMatching

Five test cases covering the core matching logic:

- **test_matches_by_expiration_date_within_tournament_week**: Given a Kalshi event with `expected_expiration_time` falling within the tournament's start/end date range, the matcher returns that event's ticker. Provide a tournament with dates (e.g., Thursday Apr 9 to Sunday Apr 12) and a Kalshi event expiring Sunday Apr 12. The function should return the event ticker.

- **test_falls_back_to_fuzzy_name_match**: When no event's expiration date falls within the tournament week, fall back to fuzzy string matching on the event title. A Kalshi event titled "PGA Tour: Valero Texas Open Winner" should match a DG tournament named "Valero Texas Open" even when dates don't align exactly.

- **test_returns_none_when_no_match_found**: When no event matches by date or name, the function returns `None`. Pass events for completely different tournaments (wrong dates, unrelated names).

- **test_rejects_non_pga_events**: A LIV Golf event whose dates overlap with the current PGA tournament must be rejected. The safety check requires the event title to contain "PGA" or a recognized PGA tournament name.

- **test_handles_multiple_open_events_picks_correct_week**: When multiple events are open for the same series ticker (e.g., this week's and next week's), the matcher picks the one whose expiration aligns with the current tournament dates, not the other.

### TestPlayerNameExtraction

Five test cases for parsing player names out of Kalshi contract titles/subtitles:

- **test_extracts_from_outright_title**: A contract with title like "Will Scottie Scheffler win the Masters?" should extract "Scottie Scheffler".

- **test_extracts_from_simple_subtitle**: A contract with a `subtitle` field containing just the player name (e.g., "Scottie Scheffler") should return that name directly.

- **test_extracts_both_names_from_h2h**: A head-to-head contract title like "Scottie Scheffler vs Rory McIlroy" should extract both names as a tuple.

- **test_handles_suffixes**: Names with suffixes like "Davis Love III" or "Harold Varner III" or "Sam Burns Jr." should be extracted with suffixes intact.

- **test_handles_international_characters**: Names like "Ludvig Aberg" (with or without the a-ring) should be extracted correctly without mangling unicode.

### TestPlayerNameMatching

Six test cases for resolving Kalshi player names to DG canonical names:

- **test_exact_match_against_canonical**: When the Kalshi name exactly matches a DG canonical name, `resolve_player()` returns the player record. Mock the database to return a match.

- **test_fuzzy_match_finds_close_variant**: "Xander Schauffele" (minor spelling variants) should fuzzy-match against the canonical form. Mock the database with a canonical name and verify the match score exceeds the 0.85 threshold.

- **test_creates_alias_on_first_match**: After a successful fuzzy match, `add_player_alias` is called with `source="kalshi"` and the Kalshi name. Verify this via mock.

- **test_uses_cached_alias_on_subsequent_lookups**: On second lookup of the same Kalshi name, the alias table returns the player directly (no fuzzy matching needed). Mock `lookup_player_by_alias` to return a hit.

- **test_returns_none_for_unknown_player**: A completely unknown name with `auto_create=False` returns `None`. No crash, no side effects.

- **test_source_is_kalshi**: When creating a new alias, the source string passed to the database is exactly `"kalshi"`.

---

## Implementation Details

### Module: `src/pipeline/kalshi_matching.py`

This module contains three groups of functions:

#### 1. Tournament Matching

```python
def match_tournament(
    kalshi_events: list[dict],
    tournament_name: str,
    tournament_start: str,  # ISO date string "YYYY-MM-DD"
    tournament_end: str,    # ISO date string "YYYY-MM-DD"
) -> str | None:
    """Find the Kalshi event ticker matching the current DG tournament.

    Matching strategy:
    1. Date-based: find event whose expected_expiration_time falls
       within [tournament_start, tournament_end + 1 day] (to handle
       Sunday evening settlement).
    2. Fuzzy name fallback: if no date match, compare event titles
       against tournament_name using substring/fuzzy matching.
    3. Safety check: reject events whose title doesn't contain "PGA"
       or a recognized PGA tour indicator.

    Returns the event_ticker string, or None if no match found.
    """
```

```python
def match_all_series(
    client,  # KalshiClient instance
    tournament_name: str,
    tournament_start: str,
    tournament_end: str,
    series_tickers: dict[str, str],  # from config.KALSHI_SERIES_TICKERS
) -> dict[str, str]:
    """Match all Kalshi series to the current tournament.

    Calls client.get_golf_events() for each series ticker, then
    match_tournament() on the results.

    Returns {"win": "KXPGATOUR-...", "t10": "KXPGATOP10-...", ...}
    with only successfully matched entries. Missing matches are
    omitted (not None values).
    """
```

**Date matching logic:** Parse `expected_expiration_time` from the Kalshi event (ISO 8601 timestamp). Convert to date. Check if it falls within the range `[tournament_start, tournament_end + timedelta(days=1)]`. The extra day accounts for Kalshi settling on Sunday evening or Monday morning after the tournament ends Sunday.

**Fuzzy name fallback:** Use a simple approach -- check if a normalized version of the DG tournament name appears as a substring of the Kalshi event title (after lowercasing both). If substring matching fails, fall back to `difflib.SequenceMatcher` with a threshold of 0.7 on the title.

**PGA safety check:** Before returning a match, verify the event title contains one of: `"PGA"`, `"Masters"`, `"U.S. Open"`, `"Open Championship"`, `"PGA Championship"`. This prevents matching LIV Golf or DP World Tour events that may overlap in dates.

#### 2. Player Name Extraction

```python
def extract_player_name_outright(contract: dict) -> str | None:
    """Extract player name from a Kalshi outright contract.

    Tries these fields in order:
    1. contract["subtitle"] -- often just the player name
    2. contract["title"] -- parse "Will [Name] win..." or
       "Will [Name] finish in the Top..."

    Returns cleaned player name string, or None if unparseable.
    """
```

```python
def extract_player_names_h2h(contract: dict) -> tuple[str, str] | None:
    """Extract both player names from a Kalshi H2H contract.

    Parses patterns like:
    - "[Player A] vs [Player B]"
    - "[Player A] vs. [Player B]"
    - "Will [Player A] beat [Player B]..."

    Returns (player_a_name, player_b_name) or None if unparseable.
    """
```

**Name cleaning:** After extraction, strip leading/trailing whitespace, normalize unicode (NFC form), and preserve suffixes (Jr., III, IV). Do NOT strip suffixes -- the `resolve_player()` function in `src/normalize/players.py` handles fuzzy matching with suffixes intact.

**Important note on Kalshi contract format:** The exact field names and title patterns should be verified against live Kalshi API responses when first testing. The extraction functions should handle multiple patterns gracefully and log a warning (not raise) if a contract title can't be parsed.

#### 3. Player Name Resolution (Thin Wrapper)

```python
def resolve_kalshi_player(
    kalshi_name: str,
    auto_create: bool = False,
) -> dict | None:
    """Resolve a Kalshi player name to a canonical DG player record.

    Delegates to src/normalize/players.resolve_player() with
    source="kalshi". Uses auto_create=False by default to avoid
    polluting the player table with unverified names.

    Returns player dict from database, or None if unresolvable.
    """
```

This is a thin wrapper around the existing `resolve_player()` function. The key design choice: `auto_create=False` by default. Kalshi contracts may include players not in the DG field (withdrawn, alternates). We do not want to auto-create player records for names that can't be matched. Unmatched players are simply skipped in the pipeline with a logged warning.

For bulk resolution during a pipeline run, iterate over extracted names and collect results into a `{kalshi_name: canonical_name}` mapping dict. This mapping is then used by the pull module (section 05) to align Kalshi data with DG data.

---

## Key Design Decisions

1. **Date-first matching strategy.** Tournament names can vary between Kalshi and DG ("Valero Texas Open" vs "Texas Open presented by Valero"). Dates are unambiguous. The fuzzy name fallback is a safety net, not the primary mechanism.

2. **Safety check against non-PGA events.** Kalshi may list LIV Golf or DP World Tour events under similar series tickers in the future. The PGA title check prevents cross-tour contamination.

3. **No auto-create for player names.** Unlike the DG source (where every name is trustworthy), Kalshi names might include non-standard entries. Only matched players flow into the pipeline. Unmatched players generate a warning log, not an error.

4. **Reuse existing `resolve_player()`.** The alias table approach (source="kalshi") means first-run matching requires fuzzy search, but all subsequent runs hit the alias cache instantly. This is the same pattern used for "datagolf", "draftkings", "start", etc.

5. **Contract format flexibility.** The extraction functions try multiple patterns (subtitle, title regex) and fail gracefully. The exact Kalshi API format may evolve, so the parser should be permissive rather than brittle.

---

## Implementation Notes

**Implemented as planned with these deviations from code review:**

- **PGA indicators trimmed:** Reduced from 30+ sponsor names to 6 core indicators per plan spec (pga, masters, u.s. open, us open, open championship, pga championship)
- **Title normalization for fuzzy matching:** Added `_TITLE_STRIP_PATTERNS` to strip "PGA Tour:", "Winner", "Top N" from Kalshi titles before SequenceMatcher comparison
- **H2H "beat" regex tightened:** Stops capturing at "in/at/during" to avoid grabbing trailing context
- **Defensive dict access:** All `event["event_ticker"]` changed to `event.get("event_ticker")` with None checks
- **Warning logs added:** `extract_player_name_outright` and `extract_player_names_h2h` now log warnings on parse failure
- **Dead code removed:** Unused `_NAME_SUFFIXES` set removed

**Files created:** `src/pipeline/kalshi_matching.py`, `tests/test_kalshi_matching.py`
**Tests:** 16 tests (5 tournament matching, 5 name extraction, 6 name resolution), 256 total pass

## Error Handling

All functions in this module follow the system's graceful degradation principle:

- `match_tournament()` returns `None` on no match -- never raises.
- `extract_player_name_outright()` returns `None` on unparseable contracts -- logs a warning.
- `resolve_kalshi_player()` returns `None` on unresolvable names -- logs a warning.
- The calling code (section 05) checks for `None` and skips accordingly.