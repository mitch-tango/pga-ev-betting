import lib.queries  # noqa: F401 — force submodule into sys.modules for @patch resolution

from unittest.mock import patch

QUERY_PATCHES = {
    "lib.queries.get_current_tournament": None,
    "lib.queries.get_active_bets": [],
    "lib.queries.get_weekly_pnl": {"settled_pnl": 0, "unsettled_stake": 0, "net_position": 0},
    "lib.queries.get_settled_bets": [],
    "lib.queries.get_bankroll_curve": [],
    "lib.queries.get_weekly_exposure": [],
    "lib.queries.get_settled_bet_stats": {"total_count": 0, "by_market_type": {}, "latest_timestamp": None},
    "lib.queries.get_clv_weekly": [],
    "lib.queries.get_calibration": [],
    "lib.queries.get_roi_by_edge_tier": [],
}


def _run_app():
    """Run app.py with all query functions mocked."""
    from streamlit.testing.v1 import AppTest

    patchers = [patch(k, return_value=v) for k, v in QUERY_PATCHES.items()]
    for p in patchers:
        p.start()
    try:
        at = AppTest.from_file("app.py", default_timeout=10)
        at.run()
    finally:
        for p in patchers:
            p.stop()
    return at


class TestAppSmoke:
    def test_app_runs_without_error(self):
        at = _run_app()
        assert not at.exception, f"App raised: {at.exception}"

    def test_sidebar_has_refresh_button(self):
        at = _run_app()
        buttons = [b.label for b in at.sidebar.button]
        assert "Refresh Data" in buttons

    def test_active_bets_is_default_page(self):
        at = _run_app()
        # Default page is Active Bets — shows info when no tournament
        info_values = [el.value for el in at.info]
        assert any("No active tournament" in v for v in info_values)


class TestNavigation:
    """Verify all analytics pages are registered in the correct order."""

    def test_navigation_includes_performance(self):
        assert "pages/performance.py" in open("app.py").read()

    def test_navigation_includes_bankroll(self):
        assert "pages/bankroll.py" in open("app.py").read()

    def test_navigation_includes_model_health(self):
        assert "pages/model_health.py" in open("app.py").read()

    def test_page_order(self):
        """Verify pages are registered in correct order in app.py."""
        content = open("app.py").read()
        nav_line = [line for line in content.splitlines() if "st.navigation" in line][0]
        assert "active_bets, performance, bankroll, model_health" in nav_line
