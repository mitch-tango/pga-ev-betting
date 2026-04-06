# Section 10 Code Review

## HIGH: ProphetX matchups called twice in pull_live_edges.py
`_pull_prophetx_block` calls `pull_prophetx_matchups()` into a throwaway `[]`, then step 7 calls it again. Wasteful duplicate API call.

## MEDIUM
- No Polymarket import in preround (by design — comment explains skip)
- No pull-order test or full pipeline integration test (plan specified)
- No test for run_live_check.py display lines

## LOW
- Preround ProphetX has tournament_name guard; pretournament doesn't
- Silent exception swallowing in step 7 ProphetX matchup merge
- Inline imports in test methods (works, but re-executed each test)
