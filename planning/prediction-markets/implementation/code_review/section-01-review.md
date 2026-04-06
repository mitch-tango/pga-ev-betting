# Code Review: Section 01 - Configuration & Constants

The implementation faithfully covers every requirement in the plan. All constants, the env_flag helper, BOOK_WEIGHTS updates, NO_DEADHEAT_BOOKS with deprecated alias, and the test file are present and correct. That said, there are several issues worth flagging:

1. RELOAD SIDE EFFECTS IN TESTS (medium severity): Tests in TestPolymarketEnabled and TestProphetxEnabled call importlib.reload(config) which re-executes the entire config module, including load_dotenv(). This means the .env file on disk gets re-read on every reload, potentially overriding the patched environment variables. If .env contains POLYMARKET_ENABLED=0 or PROPHETX_EMAIL/PROPHETX_PASSWORD, the tests could pass or fail depending on the developer's local .env file. The reload happens inside the patch.dict context manager, but load_dotenv() at module scope (line 12 of config.py) calls os.environ updates that could race with the patch. load_dotenv(override=False) is the default behavior, so existing env vars win, but this is fragile and undocumented in the tests.

2. ENV_FLAG DOES NOT TEST ACTUAL ENV VAR LOOKUP (low severity): TestEnvFlag only tests the default parameter path of env_flag (passing values as the default argument). It never patches an actual environment variable and calls env_flag with a real env var name to verify the os.getenv path works. If someone broke the os.getenv call, these tests would still pass.

3. NO TEST ISOLATION / TEARDOWN FOR RELOADS (medium severity): After importlib.reload(config) in test_disabled_by_env or test_enabled_with_credentials, the module-level constants like POLYMARKET_ENABLED and PROPHETX_ENABLED are left mutated for subsequent tests in the same process. If test execution order changes, tests in TestBookWeights or TestNoDeadheatBooks that import config without reloading could see stale or unexpected values. There is no fixture to reload config back to a clean state after these tests.

4. MISSING RATE_LIMIT_DELAY TEST FOR POLYMARKET (low severity): TestProphetxConstants tests PROPHETX_RATE_LIMIT_DELAY explicitly but TestPolymarketConstants has no equivalent test for POLYMARKET_RATE_LIMIT_DELAY. Minor gap in symmetry.

5. MISSING GOLF_TAG_ID TEST (low severity): POLYMARKET_GOLF_TAG_ID is defined in config but has no test asserting it exists or that it defaults to None when the env var is unset.

6. NO CREDENTIAL TESTS FOR PROPHETX_EMAIL/PASSWORD (low severity): TestProphetxConstants does not test that PROPHETX_EMAIL and PROPHETX_PASSWORD attributes exist on the config module. The plan's verification checklist item 11 says 'All ProphetX URL, credential, rate limit, OI, and spread constants are present' but credential presence is only tested indirectly through PROPHETX_ENABLED.
