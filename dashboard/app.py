"""PGA +EV Dashboard — Streamlit app entrypoint."""
import streamlit as st


def main():
    """Configure page, define navigation, run selected page."""
    st.set_page_config(
        page_title="PGA +EV Dashboard",
        layout="wide",
        page_icon="\u26f3",
    )

    active_bets = st.Page("pages/active_bets.py", title="Active Bets", default=True)

    pg = st.navigation([active_bets])

    with st.sidebar:
        st.title("PGA +EV Dashboard")
        st.caption("Golf betting edge tracker")
        if st.button("Refresh Data"):
            st.cache_data.clear()
            st.rerun()

    pg.run()


main()
