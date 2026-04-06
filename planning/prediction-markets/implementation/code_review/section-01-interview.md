# Code Review Interview: Section 01 - Configuration & Constants

## Triage Summary

| # | Finding | Severity | Decision |
|---|---------|----------|----------|
| 1 | Reload side effects with load_dotenv | Medium | Auto-fix: added autouse fixture to reload config after each test |
| 2 | env_flag doesn't test actual env var lookup | Low | Auto-fix: added test_reads_actual_env_var test |
| 3 | No test isolation/teardown for reloads | Medium | Auto-fix: added _reload_config_after_env_tests autouse fixture |
| 4 | Missing POLYMARKET_RATE_LIMIT_DELAY test | Low | Let go: trivial constant |
| 5 | Missing GOLF_TAG_ID test | Low | Let go: env-dependent optional value |
| 6 | Missing PROPHETX_EMAIL/PASSWORD tests | Low | Let go: tested indirectly via PROPHETX_ENABLED |

## Auto-fixes Applied

1. Added `_reload_config_after_env_tests` autouse fixture that reloads config module after every test, preventing mutation leakage across test classes.
2. Added `test_reads_actual_env_var` test that patches real env vars and verifies env_flag reads from os.environ.

## Result

29 tests passing after fixes.
