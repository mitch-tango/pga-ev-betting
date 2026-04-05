# Section 08 Code Review Interview

## Triage

| # | Issue | Severity | Action |
|---|-------|----------|--------|
| 1 | `timedelta` import inside try block | Medium | **Auto-fix** |
| 2 | Preround `db` undefined | N/A | Not an issue (already imported) |
| 3 | Empty tournament name misleading msg | Low | **Auto-fix** |
| 4 | Source-string tests | Low | Let go |
| 5 | Missing OI/spread tests | Low | Let go |
| 6 | No --kalshi flag | Low | Let go |
| 7 | Magic number 4 days | Info | **Auto-fix** (comment) |

## Auto-fixes Applied

### Fix 1: Move `timedelta` import to module top
Both `run_pretournament.py` and `run_preround.py` now import `timedelta` alongside `datetime` at module level instead of inside try blocks.

### Fix 3: Empty tournament name handling
Added explicit check in pretournament: if `_event_name` is empty, prints a warning and raises to trigger the graceful degradation path with a clear message.

### Fix 7: Document 4-day window
Added comment: "PGA tournaments run Thu-Sun (4 days)" next to the `timedelta(days=4)` in both scripts.

## Items Let Go
- #4: Source-string tests are pragmatic for workflow scripts that require DB/API/interactive input. Full behavioral tests would need extensive mocking of the entire main() flow.
- #5: OI/spread filtering is already tested in `test_pull_kalshi.py`. The degradation tests verify the merge-noop behavior which is the workflow-level concern.
- #6: The `--kalshi` flag is deferred until live DG predictions are implemented.
