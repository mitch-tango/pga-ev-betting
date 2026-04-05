<!-- PROJECT_CONFIG
runtime: python-pip
test_command: pytest
END_PROJECT_CONFIG -->

<!-- SECTION_MANIFEST
section-01-odds-conversion
section-02-kalshi-client
section-03-config-schema
section-04-tournament-matching
section-05-pipeline-pull
section-06-pipeline-merge
section-07-edge-deadheat
section-08-workflow-integration
END_MANIFEST -->

# Implementation Sections Index

## Dependency Graph

| Section | Depends On | Blocks | Parallelizable |
|---------|------------|--------|----------------|
| section-01-odds-conversion | - | 05, 06 | Yes |
| section-02-kalshi-client | - | 04, 05 | Yes |
| section-03-config-schema | - | 04, 05, 06, 07 | Yes |
| section-04-tournament-matching | 02, 03 | 05 | No |
| section-05-pipeline-pull | 01, 02, 03, 04 | 06 | No |
| section-06-pipeline-merge | 01, 03, 05 | 08 | No |
| section-07-edge-deadheat | 03 | 08 | Yes |
| section-08-workflow-integration | 05, 06, 07 | - | No |

## Execution Order

1. **Batch 1** (no dependencies): section-01-odds-conversion, section-02-kalshi-client, section-03-config-schema
2. **Batch 2** (after batch 1): section-04-tournament-matching, section-07-edge-deadheat
3. **Batch 3** (after batch 2): section-05-pipeline-pull
4. **Batch 4** (after batch 3): section-06-pipeline-merge
5. **Batch 5** (after batch 4): section-08-workflow-integration

## Section Summaries

### section-01-odds-conversion
Add Kalshi-specific conversion utilities to `src/core/devig.py`: `kalshi_price_to_american()`, `kalshi_price_to_decimal()`, `kalshi_midpoint()`. Extend existing tests in `tests/test_devig.py`.

**Plan refs:** Section 9 (Odds Conversion Utilities)
**TDD refs:** Section 9 (TestKalshiPriceToAmerican, TestKalshiPriceToDecimal, TestKalshiMidpoint)

### section-02-kalshi-client
New `KalshiClient` class in `src/api/kalshi.py` with rate limiting, retry, pagination, caching. New test file `tests/test_kalshi_client.py`.

**Plan refs:** Section 3 (Kalshi API Client)
**TDD refs:** Section 3 (TestKalshiClientInit, TestKalshiApiCall, TestKalshiPagination, etc.)

### section-03-config-schema
Add Kalshi config constants to `config.py` (base URL, rate limit, OI threshold, spread threshold, series tickers, book weights). Add Kalshi settlement rules to `schema.sql`. Add Polymarket TODO comments.

**Plan refs:** Section 6.1 (Config Additions), Section 7 (Schema Additions), Section 12 (Polymarket TODO)
**TDD refs:** Section 6 (TestKalshiBookWeights)

### section-04-tournament-matching
Tournament matching logic (date-based + fuzzy name fallback) and player name extraction/matching for Kalshi contracts. New test file `tests/test_kalshi_matching.py`.

**Plan refs:** Section 4 (Tournament & Player Matching)
**TDD refs:** Section 4 (TestTournamentMatching, TestPlayerNameExtraction, TestPlayerNameMatching)

### section-05-pipeline-pull
New `src/pipeline/pull_kalshi.py` with `pull_kalshi_outrights()` and `pull_kalshi_matchups()`. Fetches, filters (OI + spread), normalizes player names. New test file `tests/test_pull_kalshi.py`.

**Plan refs:** Section 5.1 (Pipeline Module)
**TDD refs:** Section 5 (TestPullKalshiOutrights, TestPullKalshiMatchups)

### section-06-pipeline-merge
Merge functions to inject Kalshi data as book columns into existing DG outright and matchup data structures. Handles midpoint→American conversion for consensus and ask-based decimal for bettable evaluation.

**Plan refs:** Section 5.2 (Merging Kalshi Data), Section 6.2 (De-vig Behavior), Section 6.4 (Matchup Handling)
**TDD refs:** Section 5 (TestMergeKalshiIntoOutrights, TestMergeKalshiIntoMatchups), Section 6 (TestKalshiDevigBehavior, TestKalshiMatchupExclusion, TestKalshiAllBookOdds)

### section-07-edge-deadheat
Modify `calculate_placement_edges()` to apply dead-heat adjustment per-book instead of globally. Skip DH adjustment when best_book is "kalshi" for T10/T20.

**Plan refs:** Section 6.3.1 (Dead-Heat Advantage)
**TDD refs:** Section 6 (TestKalshiDeadHeatBypass)

### section-08-workflow-integration
Wire everything into `run_pretournament.py` and `run_preround.py`. Add pre-round Kalshi guard (skip tournament markets without live DG). Graceful degradation throughout. Polymarket TODO comments in workflow scripts.

**Plan refs:** Section 8 (Workflow Integration), Section 10 (Graceful Degradation)
**TDD refs:** Section 8 (TestPreTournamentWithKalshi, TestPreRoundKalshiGuard), Section 10 (TestGracefulDegradation)
