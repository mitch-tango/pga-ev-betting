"""Tests for Polymarket & ProphetX configuration constants."""

import importlib
import os
from unittest.mock import patch

import pytest


class TestEnvFlag:
    """env_flag helper correctly parses boolean env vars."""

    def test_true_values(self):
        import config
        for val in ("1", "true", "yes", "True", "YES", "TRUE"):
            assert config.env_flag("X", val) is True, f"Expected True for {val!r}"

    def test_false_values(self):
        import config
        for val in ("0", "false", "no", "False", "", "NO"):
            assert config.env_flag("X", val) is False, f"Expected False for {val!r}"

    def test_bool_zero_gotcha_avoided(self):
        """bool('0') is True in Python, but env_flag('X', '0') must be False."""
        import config
        assert config.env_flag("X", "0") is False

    def test_reads_actual_env_var(self):
        """env_flag reads from os.environ, not just the default."""
        import config
        with patch.dict(os.environ, {"_TEST_FLAG": "yes"}):
            assert config.env_flag("_TEST_FLAG", "0") is True
        with patch.dict(os.environ, {"_TEST_FLAG": "0"}):
            assert config.env_flag("_TEST_FLAG", "1") is False


@pytest.fixture(autouse=True)
def _reload_config_after_env_tests():
    """Reload config after tests that mutate module-level state via importlib.reload."""
    yield
    import config
    importlib.reload(config)


class TestPolymarketEnabled:
    """POLYMARKET_ENABLED flag respects env var."""

    def test_default_enabled(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("POLYMARKET_ENABLED", None)
            import config
            importlib.reload(config)
            assert config.POLYMARKET_ENABLED is True

    def test_disabled_by_env(self):
        with patch.dict(os.environ, {"POLYMARKET_ENABLED": "0"}):
            import config
            importlib.reload(config)
            assert config.POLYMARKET_ENABLED is False


class TestProphetxEnabled:
    """PROPHETX_ENABLED auto-detects credentials."""

    def test_disabled_without_credentials(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("PROPHETX_EMAIL", "PROPHETX_PASSWORD")}
        with patch.dict(os.environ, env, clear=True):
            import config
            importlib.reload(config)
            assert config.PROPHETX_ENABLED is False

    def test_enabled_with_credentials(self):
        with patch.dict(os.environ, {
            "PROPHETX_EMAIL": "test@example.com",
            "PROPHETX_PASSWORD": "secret",
        }):
            import config
            importlib.reload(config)
            assert config.PROPHETX_ENABLED is True


class TestBookWeights:
    """BOOK_WEIGHTS includes prediction market entries."""

    def test_polymarket_in_win(self):
        import config
        assert "polymarket" in config.BOOK_WEIGHTS["win"]

    def test_polymarket_in_placement(self):
        import config
        assert "polymarket" in config.BOOK_WEIGHTS["placement"]

    def test_polymarket_not_in_make_cut(self):
        import config
        assert "polymarket" not in config.BOOK_WEIGHTS["make_cut"]

    def test_prophetx_in_win(self):
        import config
        assert "prophetx" in config.BOOK_WEIGHTS["win"]

    def test_prophetx_in_placement(self):
        import config
        assert "prophetx" in config.BOOK_WEIGHTS["placement"]

    def test_prophetx_in_make_cut(self):
        import config
        assert "prophetx" in config.BOOK_WEIGHTS["make_cut"]


class TestNoDeadheatBooks:
    """NO_DEADHEAT_BOOKS set contains correct entries."""

    def test_contains_kalshi(self):
        import config
        assert "kalshi" in config.NO_DEADHEAT_BOOKS

    def test_contains_polymarket(self):
        import config
        assert "polymarket" in config.NO_DEADHEAT_BOOKS

    def test_prophetx_not_included(self):
        import config
        assert "prophetx" not in config.NO_DEADHEAT_BOOKS

    def test_deprecated_alias_still_works(self):
        """Backward compat: KALSHI_NO_DEADHEAT_BOOKS still exists."""
        import config
        assert config.KALSHI_NO_DEADHEAT_BOOKS is config.NO_DEADHEAT_BOOKS


class TestPolymarketConstants:
    """Polymarket URL, rate limit, volume, spread, and fee constants."""

    def test_gamma_url(self):
        import config
        assert config.POLYMARKET_GAMMA_URL == "https://gamma-api.polymarket.com"

    def test_clob_url(self):
        import config
        assert config.POLYMARKET_CLOB_URL == "https://clob.polymarket.com"

    def test_fee_rate_positive_float(self):
        import config
        assert isinstance(config.POLYMARKET_FEE_RATE, float)
        assert config.POLYMARKET_FEE_RATE > 0

    def test_min_volume_positive_int(self):
        import config
        assert isinstance(config.POLYMARKET_MIN_VOLUME, int)
        assert config.POLYMARKET_MIN_VOLUME > 0

    def test_max_spread_abs_positive(self):
        import config
        assert isinstance(config.POLYMARKET_MAX_SPREAD_ABS, float)
        assert config.POLYMARKET_MAX_SPREAD_ABS > 0

    def test_max_spread_rel_positive(self):
        import config
        assert isinstance(config.POLYMARKET_MAX_SPREAD_REL, float)
        assert config.POLYMARKET_MAX_SPREAD_REL > 0

    def test_market_types_dict(self):
        import config
        assert "win" in config.POLYMARKET_MARKET_TYPES
        assert "t10" in config.POLYMARKET_MARKET_TYPES
        assert "t20" in config.POLYMARKET_MARKET_TYPES


class TestProphetxConstants:
    """ProphetX URL, credential, rate limit, OI, and spread constants."""

    def test_base_url(self):
        import config
        assert config.PROPHETX_BASE_URL == "https://cash.api.prophetx.co"

    def test_rate_limit_delay(self):
        import config
        assert config.PROPHETX_RATE_LIMIT_DELAY == 0.1

    def test_min_open_interest(self):
        import config
        assert isinstance(config.PROPHETX_MIN_OPEN_INTEREST, int)
        assert config.PROPHETX_MIN_OPEN_INTEREST > 0

    def test_max_spread(self):
        import config
        assert isinstance(config.PROPHETX_MAX_SPREAD, float)
        assert config.PROPHETX_MAX_SPREAD > 0
