# Code Review Interview: Section 07 - ProphetX API Client

## Findings Triage

### Auto-Fixed
- **#1 Log redaction**: Added credential redaction in auth error logging.
- **#3 Refresh logging**: Now logs non-200 refresh responses before falling back.
- **#4 401 retry budget**: Moved 401 re-auth outside retry loop into separate _api_call_inner, so 401 doesn't consume retry attempts.
- **#12 Public method logging**: Added warning logs for failures and unexpected shapes.
- **#13 Unused import**: Removed PropertyMock.

### Let Go
- **#2 Credential validation**: Callers check PROPHETX_ENABLED before creating client.
- **#5 Public methods don't cache**: Consistent with Kalshi; pull layer caches.
- **#6 Cache check label only**: Sufficient; auth calls are internal.
- **#7 Test patch fragility**: Works correctly since creds stored at init.
- **#8/#9/#10 Missing retry/delay tests**: Patterns proven in Kalshi.
- **#11 Cache prefix**: Intentional for data source distinction.

## Final: 22 tests passing
