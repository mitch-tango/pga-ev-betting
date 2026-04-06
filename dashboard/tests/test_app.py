class TestAppSmoke:
    def test_app_runs_without_error(self):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app.py", default_timeout=10)
        at.run()
        assert not at.exception, f"App raised: {at.exception}"

    def test_sidebar_has_refresh_button(self):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app.py", default_timeout=10)
        at.run()
        buttons = [b.label for b in at.sidebar.button]
        assert "Refresh Data" in buttons

    def test_active_bets_is_default_page(self):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app.py", default_timeout=10)
        at.run()
        # The default page should render "Active Bets" header
        headers = [h.value for h in at.header]
        assert "Active Bets" in headers
