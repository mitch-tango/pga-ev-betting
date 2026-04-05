# Code Review: Section 02 - Kalshi Client

1. MISSING: retries parameter on _api_call (inconsistency with DataGolfClient)
2. MISSING: getattr fallback for API_TIMEOUT and API_MAX_RETRIES
3. SILENT DATA LOSS in _paginated_call on mid-pagination errors
4. MUTATION BUG risk with shallow copy in _paginated_call (low risk)
5. TEST GAPS: test_cache_dir_creation misleading, test_paginated_markets trivial, no tests for get_market/get_orderbook
6. INCONSISTENT ERROR RETURN in get_market/get_orderbook (unwrapped data vs error envelope)
7. PRINT STATEMENTS for logging (inherited from DataGolfClient)
8. NO INFINITE LOOP PROTECTION in _paginated_call
