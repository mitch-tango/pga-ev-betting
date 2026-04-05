<!-- PROJECT_CONFIG
runtime: python-uv
test_command: uv run pytest
END_PROJECT_CONFIG -->

<!-- SECTION_MANIFEST
section-01-config
section-02-devig-refactor
section-03-edge-updates
section-04-polymarket-client
section-05-polymarket-matching
section-06-polymarket-pull
section-07-prophetx-client
section-08-prophetx-matching
section-09-prophetx-pull
section-10-workflow
section-11-testing
END_MANIFEST -->

# Implementation Sections Index

## Dependency Graph

| Section | Depends On | Blocks | Parallelizable With |
|---------|------------|--------|---------------------|
| section-01-config | - | all | - |
| section-02-devig-refactor | 01 | 03, 06, 09 | 04, 05, 07, 08 |
| section-03-edge-updates | 01, 02 | 10 | 04, 05, 07, 08 |
| section-04-polymarket-client | 01 | 05, 06 | 02, 03, 07, 08 |
| section-05-polymarket-matching | 01, 04 | 06 | 02, 03, 07, 08 |
| section-06-polymarket-pull | 01, 02, 04, 05 | 10 | 07, 08, 09 |
| section-07-prophetx-client | 01 | 08, 09 | 02, 03, 04, 05 |
| section-08-prophetx-matching | 01, 07 | 09 | 02, 03, 04, 05 |
| section-09-prophetx-pull | 01, 02, 07, 08 | 10 | 04, 05, 06 |
| section-10-workflow | 01, 03, 06, 09 | 11 | - |
| section-11-testing | all | - | - |

## Execution Order

1. **section-01-config** (no dependencies — foundation for everything)
2. **section-02-devig-refactor**, **section-04-polymarket-client**, **section-07-prophetx-client** (parallel after 01)
3. **section-03-edge-updates**, **section-05-polymarket-matching**, **section-08-prophetx-matching** (parallel after batch 2)
4. **section-06-polymarket-pull**, **section-09-prophetx-pull** (parallel after their matching sections)
5. **section-10-workflow** (requires 03, 06, 09)
6. **section-11-testing** (final integration tests)

## Section Summaries

### section-01-config
Configuration constants in `config.py`: Polymarket URLs, ProphetX URLs/credentials, book weights, dead-heat set rename, enabled flags with proper env parsing, fee rate, quality filter constants.

### section-02-devig-refactor
Rename Kalshi-specific functions in `devig.py` to generic names (`binary_price_to_american`, etc.) with backward-compatible aliases.

### section-03-edge-updates
Generalize `edge.py`: use `NO_DEADHEAT_BOOKS` set, generalize ask-based pricing to any `_{book}_ask_prob` key, validate ask values.

### section-04-polymarket-client
`src/api/polymarket.py`: PolymarketClient with dual-URL support (Gamma + CLOB), retry/rate-limit, pagination, caching, token_id batch chunking (50 per request).

### section-05-polymarket-matching
`src/pipeline/polymarket_matching.py`: UTC date range overlap matching, token-based fuzzy match ≥0.85, non-PGA exclusion, YES token identification, slug/regex player name extraction.

### section-06-polymarket-pull
`src/pipeline/pull_polymarket.py`: Pull outrights (win/t10/t20), empty orderbook handling, relative spread filter, fee-adjusted ask prob, merge into DG data.

### section-07-prophetx-client
`src/api/prophetx.py`: ProphetXClient with JWT auth (lazy login, refresh, re-auth on 401), User-Agent header, auth response exclusion from cache, credential redaction in logs.

### section-08-prophetx-matching
`src/pipeline/prophetx_matching.py`: Flexible field name detection, market type classification (outright/matchup/make_cut), UTC date matching, player extraction from competitor data.

### section-09-prophetx-pull
`src/pipeline/pull_prophetx.py`: Pull outrights + matchups, detect American (int/str) vs binary odds format, merge into DG data with format-appropriate ask prob handling.

### section-10-workflow
Update `run_pretournament.py`, `run_preround.py`, `run_live_check.py`: add Polymarket + ProphetX pull/merge blocks with enabled checks and try/except graceful degradation.

### section-11-testing
Integration tests: full pipeline with all 3 markets, partial failure, total failure, DG-only regression. Test helpers/factories for both markets.
