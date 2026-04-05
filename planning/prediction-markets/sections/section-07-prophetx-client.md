# Section 07: ProphetX API Client

## Overview

This section implements `src/api/prophetx.py`, an authenticated API client for the ProphetX prediction market. ProphetX requires JWT-based login (email/password), token refresh, and re-authentication on 401 responses. The client follows the same structural pattern as `KalshiClient` but adds an authentication layer with security precautions.

## Dependencies

- **Section 01 (config):** `PROPHETX_BASE_URL`, `PROPHETX_EMAIL`, `PROPHETX_PASSWORD`, `PROPHETX_RATE_LIMIT_DELAY`
- No dependency on Polymarket sections or devig refactoring.

## Files to Create

| File | Purpose |
|------|---------|
| `src/api/prophetx.py` | ProphetX API client class |
| `tests/test_prophetx_client.py` | Unit tests |

## Tests First

```python
# tests/test_prophetx_client.py

# --- Constructor ---
# Test: ProphetXClient reads email/password from config
# Test: ProphetXClient sets User-Agent header on session

# --- Authentication ---
# Test: _authenticate sends POST to /api/v1/auth/login with {"email": ..., "password": ...}
# Test: _authenticate stores access_token and refresh_token from response
# Test: _authenticate reads expires_in and sets token_expiry = now + expires_in - 5min buffer
# Test: _authenticate falls back to 55-minute expiry when expires_in absent
# Test: _authenticate returns error envelope on login failure
# Test: _refresh_auth sends refresh_token to /api/v1/auth/extend-session
# Test: _refresh_auth falls back to full _authenticate when refresh fails
# Test: _ensure_auth calls _authenticate on first request (lazy init)
# Test: _ensure_auth calls _refresh_auth when token expired
# Test: _ensure_auth is no-op when token valid

# --- _api_call ---
# Test: _api_call adds Authorization: Bearer header
# Test: _api_call calls _ensure_auth before request
# Test: _api_call re-authenticates on 401, then retries once
# Test: _api_call retries on 429 with exponential backoff
# Test: _api_call retries on 5xx with backoff
# Test: _api_call returns ok envelope on 200
# Test: _api_call returns error envelope on 400 (no retry)
# Test: _api_call returns error envelope after max retries exhausted
# Test: _api_call respects rate_limit_delay

# --- _cache_response ---
# Test: writes JSON to data/raw/{slug}/{timestamp}/prophetx_{label}.json
# Test: creates directories if needed
# Test: SKIPS endpoints/labels containing "/auth/" (security)
# Test: does not write tokens or credentials to disk

# --- Public methods ---
# Test: get_golf_events returns list of golf event dicts
# Test: get_markets_for_events returns market dicts with odds and competitor info
```

## Implementation Details

### Class: `ProphetXClient`

Key differences from `KalshiClient`:
1. **Authentication required** (Kalshi is read-only)
2. **Uses `requests.Session`** for persistent auth headers and User-Agent
3. **Cache exclusion** for auth endpoints

### Constructor

- Accepts optional `base_url`, `cache_dir` for testability
- Reads credentials from config via `getattr(config, ...)`
- Initializes `access_token = None`, `refresh_token = None`, `token_expiry = None`
- Creates `requests.Session()` with browser-like `User-Agent` header

### Authentication Methods

**`_authenticate()`** — Full login:
- `POST {base_url}/api/v1/auth/login` with `{"email": email, "password": password}`
- Store `access_token`, `refresh_token`
- Read `expires_in` (seconds) if present → `token_expiry = now + timedelta(seconds=expires_in) - 5min`
- Fall back to `now + 55 minutes` if `expires_in` absent
- On failure: return error envelope, do not raise
- **Never cache auth responses**

**`_refresh_auth()`** — Token refresh:
- `POST {base_url}/api/v1/auth/extend-session` with Bearer refresh_token
- Update `access_token` and `token_expiry` (same `expires_in` logic)
- On failure: fall back to full `_authenticate()`

**`_ensure_auth()`** — Called at start of every `_api_call()`:
- `access_token is None` → `_authenticate()` (first use)
- `now > token_expiry` → `_refresh_auth()`
- Otherwise: no-op

### `_api_call(endpoint, params=None, method="GET")`

Same retry/rate-limit as KalshiClient with additions:
- Calls `_ensure_auth()` before request
- Sets `Authorization: Bearer {access_token}` via session
- **401**: re-authenticate once, retry. If still 401, return error envelope
- All other codes: same as Kalshi (200→ok, 429→backoff, 400→error, 5xx→retry)
- Sleeps `rate_limit_delay` after successful 200
- Supports `method` param for POST calls (auth endpoints)

### `_cache_response(data, label, tournament_slug=None)`

Same as KalshiClient with **critical security addition**:
- **Skip if label/endpoint contains `/auth/` or `auth`** — prevents tokens/credentials on disk
- Same directory structure: `data/raw/{slug}/{timestamp}/prophetx_{label}.json`

### Public Methods

**`get_golf_events()`** — Calls sport/events endpoint filtered for golf/PGA. Returns list of event dicts. Empty list on failure.

**`get_markets_for_events(event_ids)`** — Accepts list of event IDs, returns market dicts with `line_id`, odds, competitor info, market type. Empty list on failure.

Both methods are defensive: log unknown response shapes, handle unexpected fields, never crash.

### Security Requirements (Non-negotiable)

1. **Never cache auth responses** — `_cache_response()` must skip auth-related calls
2. **Redact sensitive data in logs** — strip Authorization headers and tokens before logging
3. **No credentials in `__repr__`** — email/password should not appear in string representations

### Design Notes

- ProphetX may return American odds as int (`400`) or string (`"+400"`). The client doesn't handle this distinction — that's the pull layer's job (section-09).
- `get_golf_events()` and `get_markets_for_events()` signatures may need refinement with real API responses. Build with exploratory logging.
- `requests.Session` preferred for persistent headers and connection pooling.

### Reference: KalshiClient Pattern

Follow `src/api/kalshi.py` structure:
- Constructor reads config via `getattr(config, ...)`
- `_api_call()` returns envelope dicts
- `_cache_response()` writes to `data/raw/` with prefix
- Error handling uses logging, never raises to callers

## Verification Checklist

1. Auth flow: lazy init → token refresh → re-auth on 401
2. Token expiry reads `expires_in` from response, falls back to 55min
3. Auth responses never cached to disk
4. User-Agent header set on session
5. Same retry/backoff/envelope pattern as Kalshi
6. `uv run pytest tests/test_prophetx_client.py` passes
