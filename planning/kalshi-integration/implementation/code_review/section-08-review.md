# Section 08 Code Review: Workflow Integration

## Findings

### 1. `timedelta` import inside try block (medium)
`from datetime import timedelta` is inside the try/except at runtime. Should be at module top.

### 2. Preround: latent `db` reference may crash (medium)
`db.get_tournament_by_id()` called in preround Kalshi block but `db` is already imported at top of file. Actually `db` IS imported (line 27 of run_preround.py). **Not a real issue.**

### 3. Empty tournament name gives misleading message (low)
If `_event_name` is empty, prints "no outright data available" instead of "tournament name unknown".

### 4. Source-string-matching tests vs behavioral (low)
Tests use `open(mod.__file__).read()` instead of exercising `main()`. This is pragmatic for workflow scripts with many dependencies (DB, API, interactive input).

### 5. Missing OI/spread threshold degradation tests (low)
Plan specified these; implementation substituted merge-noop tests instead. The OI/spread filtering is already tested in pull_kalshi tests.

### 6. No `--kalshi` CLI flag for preround (low)
Plan suggested it; implementation uses hardcoded boolean. OK for now since feature is disabled.

### 7. Magic number `timedelta(days=4)` (info)
4-day tournament window not documented.
