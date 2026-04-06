# Code Review: Section 07 - ProphetX API Client

## Critical
1. **Log redaction not implemented** — Plan requires stripping auth headers/tokens from logs. Not done.
2. **No credential validation** — Constructor accepts None credentials silently.
3. **_refresh_auth silently swallows non-200** — Falls through to _authenticate without logging.
4. **401 retry consumes retry budget** — Re-auth on 401 uses one of max_retries attempts.
5. **Public methods never cache** — get_golf_events/get_markets_for_events don't call _cache_response.

## Medium
6. **Cache check only on label, not endpoint** — Plan says check both.
7. **Test _make_client patch fragility** — Config patch may not be active when methods run.
8. **Missing 429 retry test**
9. **Missing rate_limit_delay test**
10. **Missing 5xx retry test**

## Minor
11. KalshiClient doesn't prefix cache files, ProphetX does — intentional inconsistency.
12. Public methods have no failure logging.
13. Unused PropertyMock import.
