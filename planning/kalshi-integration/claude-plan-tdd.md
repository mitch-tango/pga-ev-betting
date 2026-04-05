# TDD Plan: Kalshi Integration

Testing framework: **pytest** with class-based test organization (matching existing `tests/` conventions).

Tests are organized to mirror the implementation plan sections. Each section lists test stubs to write BEFORE implementing.

---

## 3. Kalshi API Client — `tests/test_kalshi_client.py`

### TestKalshiClientInit
- Test: client initializes with default config values (base_url, rate_limit_delay)
- Test: client initializes with custom base_url override
- Test: client creates cache directory if it doesn't exist

### TestKalshiApiCall
- Test: successful GET returns `{"status": "ok", "data": ...}` envelope
- Test: 429 response triggers retry with backoff
- Test: 5xx response triggers retry
- Test: persistent failure returns `{"status": "error", ...}` after max retries
- Test: network timeout triggers retry
- Test: rate limiting delay is respected between calls

### TestKalshiPagination
- Test: single page response returns all results
- Test: multi-page response concatenates results across pages
- Test: empty cursor stops pagination

### TestGetGolfEvents
- Test: returns open events for a given series ticker
- Test: filters to only open status events
- Test: returns empty list when no events found

### TestGetEventMarkets
- Test: returns all markets for a given event ticker
- Test: handles paginated market responses
- Test: returns empty list for unknown event ticker

### TestCacheResponse
- Test: caches response to correct path with timestamp
- Test: tournament_slug creates subdirectory
- Test: cached file contains valid JSON

---

## 4. Tournament & Player Matching — `tests/test_kalshi_matching.py`

### TestTournamentMatching
- Test: matches Kalshi event by expiration date within tournament week
- Test: falls back to fuzzy name match when date match fails
- Test: returns None when no match found
- Test: rejects non-PGA events (e.g., LIV Golf) even if dates overlap
- Test: handles multiple open events for same series ticker (picks correct week)

### TestPlayerNameExtraction
- Test: extracts player name from outright contract title (e.g., "Will Scottie Scheffler win...")
- Test: extracts player name from simple subtitle format
- Test: extracts both player names from H2H contract
- Test: handles suffixes (Jr., III) correctly
- Test: handles international characters (e.g., Ludvig Åberg)

### TestPlayerNameMatching
- Test: exact match against known DG canonical name
- Test: fuzzy match finds close variant (e.g., "Xander Schauffele" vs "Xander Schauffele")
- Test: creates alias in player_aliases table on first match
- Test: uses cached alias on subsequent lookups
- Test: returns None for genuinely unknown player
- Test: source is set to "kalshi" in alias table

---

## 5. Pipeline Module — `tests/test_pull_kalshi.py`

### TestPullKalshiOutrights
- Test: returns dict with "win", "t10", "t20" keys
- Test: each market entry has player_name, kalshi_mid_prob, kalshi_ask_prob, open_interest
- Test: filters out players below OI threshold (100)
- Test: filters out players with bid-ask spread > $0.05
- Test: validates prices are in 0–1 range
- Test: returns empty dict when Kalshi API is down (graceful degradation)
- Test: returns empty dict when no golf events found
- Test: caches raw response to data/raw/

### TestPullKalshiMatchups
- Test: returns list of H2H matchup dicts with p1/p2 names and probs
- Test: filters by OI threshold
- Test: filters by spread threshold
- Test: returns empty list when no H2H events found

### TestMergeKalshiIntoOutrights
- Test: adds "kalshi" key with American odds string to matching players
- Test: American odds string is derived from midpoint probability
- Test: unmatched Kalshi players are skipped (no crash)
- Test: existing book columns are not modified
- Test: players with no Kalshi data have no "kalshi" key added
- Test: stores raw ask data alongside for bettable edge evaluation

### TestMergeKalshiIntoMatchups
- Test: injects kalshi into matchup odds_dict for matched pairings
- Test: unmatched pairings are skipped
- Test: kalshi odds follow the same format as other books in odds_dict

---

## 6. Book Consensus & Edge Changes — `tests/test_kalshi_edge.py`

### TestKalshiBookWeights
- Test: kalshi has weight 2 in win market (sharp)
- Test: kalshi has weight 1 in placement market
- Test: kalshi is absent from make_cut weights
- Test: build_book_consensus includes kalshi with correct weight

### TestKalshiDevigBehavior
- Test: power_devig on Kalshi midpoint field (sum ≈ 1.0) returns k ≈ 1.0, probs unchanged
- Test: devig_independent on Kalshi T10 midpoints (sum ≈ 10) returns probs nearly unchanged
- Test: mixed field with traditional books + Kalshi devig produces reasonable results

### TestKalshiDeadHeatBypass
- Test: when best_book is "kalshi" and market is t10, deadheat_adj is 0.0
- Test: when best_book is "kalshi" and market is t20, deadheat_adj is 0.0
- Test: when best_book is "draftkings" and market is t10, deadheat_adj > 0
- Test: Kalshi wins "best book" over sportsbook with better raw odds due to DH advantage
  (e.g., DK raw_edge=8%, DH adj=4.4%, effective=3.6% vs Kalshi raw_edge=7%, effective=7%)

### TestKalshiMatchupExclusion
- Test: Kalshi is excluded from matchup book consensus blending
- Test: Kalshi is included in matchup best-edge evaluation (bettable outlet)
- Test: Kalshi can be selected as best_book for matchup bet

### TestKalshiAllBookOdds
- Test: all_book_odds dict includes "kalshi" with ask-based decimal odds
- Test: kalshi decimal odds differ from midpoint-derived odds (ask > mid)

---

## 9. Odds Conversion — `tests/test_devig.py` (extend existing)

### TestKalshiPriceToAmerican
- Test: '0.06' -> '+1567' (longshot)
- Test: '0.55' -> '-122' (favorite)
- Test: '0.50' -> '+100' (even money)
- Test: '0.01' -> '+9900' (extreme longshot)
- Test: '0.95' -> '-1900' (heavy favorite)
- Test: rounds to integer (no decimal American odds)
- Test: None/empty input returns empty string

### TestKalshiPriceToDecimal
- Test: '0.06' -> 16.667
- Test: '0.55' -> 1.818
- Test: '0.50' -> 2.0
- Test: '0.0' returns None
- Test: '1.0' returns None
- Test: invalid string returns None

### TestKalshiMidpoint
- Test: ('0.04', '0.06') -> 0.05
- Test: ('0.50', '0.52') -> 0.51
- Test: missing bid returns None
- Test: missing ask returns None

---

## 8. Workflow Integration — `tests/test_kalshi_workflow.py`

### TestPreTournamentWithKalshi
- Test: run_pretournament pulls Kalshi data after DG data
- Test: Kalshi failure doesn't prevent DG-only edge calculation
- Test: merged data includes kalshi as a book column
- Test: candidates can have best_book="kalshi"

### TestPreRoundKalshiGuard
- Test: pre-round scan with live DG model includes Kalshi data
- Test: pre-round scan without live DG model skips Kalshi tournament markets
- Test: skipping Kalshi logs a warning message

---

## 10. Graceful Degradation — `tests/test_kalshi_degradation.py`

### TestGracefulDegradation
- Test: API unreachable -> pipeline completes with DG-only data
- Test: no golf events -> pipeline completes with DG-only data
- Test: tournament can't be matched -> pipeline completes with warning
- Test: all Kalshi players below OI threshold -> no kalshi in consensus
- Test: all Kalshi players exceed spread threshold -> no kalshi in consensus
- Test: 429 rate limit -> retries then proceeds without
- Test: partial data (some markets available, others not) -> uses what's available
