# Section 10 Code Review Interview

## Auto-fixes Applied

1. **Duplicate ProphetX matchup API call in pull_live_edges.py** — Replaced `_pull_prophetx_block(outrights, [], ...)` with inline outright-only code. Matchups are merged separately in step 7, avoiding the wasteful duplicate `pull_prophetx_matchups()` call.

## Let Go

- Missing pull-order/full-pipeline integration tests — heavyweight, belong in section 11
- No Polymarket import in preround — by design (outrights only, not relevant for rounds)
- Silent exception swallowing in step 7 matchup merge — matches existing Kalshi pattern
- Inline test imports — avoids module-level side effects, functional
- Tournament name guard inconsistency — pretournament always has tournament_name from DG
