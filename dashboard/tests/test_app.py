import lib.queries  # noqa: F401 — force submodule into sys.modules for @patch resolution

from unittest.mock import patch


class TestAppSmoke:
    @patch("lib.queries.get_weekly_pnl", return_value={"settled_pnl": 0, "unsettled_stake": 0, "net_position": 0})
    @patch("lib.queries.get_active_bets", return_value=[])
    @patch("lib.queries.get_current_tournament", return_value=None)
    def test_app_runs_without_error(self, mock_tournament, mock_bets, mock_pnl):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app.py", default_timeout=10)
        at.run()
        assert not at.exception, f"App raised: {at.exception}"

    @patch("lib.queries.get_weekly_pnl", return_value={"settled_pnl": 0, "unsettled_stake": 0, "net_position": 0})
    @patch("lib.queries.get_active_bets", return_value=[])
    @patch("lib.queries.get_current_tournament", return_value=None)
    def test_sidebar_has_refresh_button(self, mock_tournament, mock_bets, mock_pnl):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app.py", default_timeout=10)
        at.run()
        buttons = [b.label for b in at.sidebar.button]
        assert "Refresh Data" in buttons

    @patch("lib.queries.get_weekly_pnl", return_value={"settled_pnl": 0, "unsettled_stake": 0, "net_position": 0})
    @patch("lib.queries.get_active_bets", return_value=[])
    @patch("lib.queries.get_current_tournament", return_value=None)
    def test_active_bets_is_default_page(self, mock_tournament, mock_bets, mock_pnl):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app.py", default_timeout=10)
        at.run()
        # Default page is Active Bets — shows info when no tournament
        info_values = [el.value for el in at.info]
        assert any("No active tournament" in v for v in info_values)
